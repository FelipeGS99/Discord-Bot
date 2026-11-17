"""Official Riot and Data Dragon clients. No client-side agent or hidden identities."""

from __future__ import annotations

import asyncio
import copy
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import aiohttp


class RiotError(RuntimeError):
    def __init__(self, status: int, message: str, retry_after: float = 0):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class RiotClient:
    ROUTES = {
        "BR1": "americas",
        "NA1": "americas",
        "LA1": "americas",
        "LA2": "americas",
        "EUW1": "europe",
        "EUN1": "europe",
        "TR1": "europe",
        "RU": "europe",
        "KR": "asia",
        "JP1": "asia",
        "OC1": "sea",
        "SG2": "sea",
        "TW2": "sea",
        "VN2": "sea",
    }

    def __init__(
        self, key: str | None, *, interval: float = 1.25, base_url: str | None = None
    ):
        self.key, self.interval, self.base_url = key, interval, base_url
        self.session = None
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.blocked_until = 0.0
        self.blocked_error = None
        self.cache = {}
        self.health = "nao configurada" if not key else "aguardando consulta"

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    @classmethod
    def region(cls, platform):
        try:
            return cls.ROUTES[platform.upper()]
        except KeyError:
            raise ValueError("Regiao Riot nao suportada.") from None

    async def get(self, host, path, *, ttl=0, missing=False):
        if not self.key:
            raise RiotError(0, "RIOT_API_KEY nao configurada.")
        url = (self.base_url or f"https://{host}.api.riotgames.com") + path
        cached = self.cache.get(url)
        if cached and cached[0] > time.monotonic():
            return copy.deepcopy(cached[1])
        async with self.lock:
            if self.blocked_until > time.monotonic():
                raise RiotError(
                    self.blocked_error.status if self.blocked_error else 429,
                    str(self.blocked_error)
                    if self.blocked_error
                    else "Riot em espera por limite de requisicoes.",
                    self.blocked_until - time.monotonic(),
                )
            if self.session is None:
                self.session = aiohttp.ClientSession(
                    trust_env=True, timeout=aiohttp.ClientTimeout(total=15, connect=5)
                )
            for attempt in range(3):
                await asyncio.sleep(max(0, self.next_request - time.monotonic()))
                self.next_request = time.monotonic() + self.interval
                try:
                    async with self.session.get(
                        url, headers={"X-Riot-Token": self.key}
                    ) as response:
                        status = response.status
                        if status == 404 and missing:
                            self.health = "conectada"
                            return None
                        if status == 429:
                            try:
                                delay = max(
                                    1, float(response.headers.get("Retry-After", 60))
                                )
                            except ValueError:
                                try:
                                    delay = max(
                                        1,
                                        parsedate_to_datetime(
                                            response.headers["Retry-After"]
                                        ).timestamp()
                                        - time.time(),
                                    )
                                except (ValueError, KeyError, TypeError):
                                    delay = 60
                            self.blocked_until = time.monotonic() + delay
                            self.blocked_error = RiotError(
                                429,
                                "Limite Riot atingido; aguardando Retry-After.",
                                delay,
                            )
                            raise self.blocked_error
                        if status in (401, 403):
                            self.blocked_until = time.monotonic() + 60
                            self.blocked_error = RiotError(
                                status,
                                f"Riot HTTP {status}: chave invalida, expirada ou sem autorizacao.",
                            )
                            raise self.blocked_error
                        if status >= 500:
                            if attempt < 2:
                                await asyncio.sleep(2**attempt)
                                continue
                            raise RiotError(
                                status,
                                f"Riot HTTP {status}: servico temporariamente indisponivel.",
                            )
                        if status != 200:
                            raise RiotError(
                                status, f"Riot HTTP {status}: consulta recusada."
                            )
                        try:
                            data = await response.json()
                        except (ValueError, aiohttp.ContentTypeError):
                            raise RiotError(
                                200, "Riot retornou formato JSON invalido."
                            ) from None
                        if not isinstance(data, (dict, list)):
                            raise RiotError(200, "Riot retornou estrutura inesperada.")
                        # Respect application limits even if the key's quota differs from the default.
                        try:
                            limits = {
                                float(window): float(limit)
                                for limit, window in (
                                    v.split(":")
                                    for v in response.headers.get(
                                        "X-App-Rate-Limit", ""
                                    ).split(",")
                                    if v
                                )
                            }
                            counts = {
                                float(window): float(count)
                                for count, window in (
                                    v.split(":")
                                    for v in response.headers.get(
                                        "X-App-Rate-Limit-Count", ""
                                    ).split(",")
                                    if v
                                )
                            }
                            for window, limit in limits.items():
                                if limit > 0:
                                    self.interval = max(
                                        self.interval, window / limit * 1.05
                                    )
                                if counts.get(window, 0) >= limit > 0:
                                    self.blocked_until = max(
                                        self.blocked_until, time.monotonic() + window
                                    )
                                    self.blocked_error = RiotError(
                                        429,
                                        "Cota Riot preenchida; aguardando nova janela.",
                                        window,
                                    )
                        except ValueError:
                            pass
                        self.health = "conectada"
                        if ttl:
                            self.cache[url] = (time.monotonic() + ttl, data)
                            if len(self.cache) > 2000:
                                self.cache = {
                                    k: v
                                    for k, v in self.cache.items()
                                    if v[0] > time.monotonic()
                                }
                        return copy.deepcopy(data)
                except RiotError as exc:
                    self.health = str(exc)
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    self.health = "falha de rede/TLS ou timeout ao consultar Riot"
                    raise RiotError(0, self.health) from None

    async def account(self, riot_id, platform="BR1"):
        name, sep, tag = riot_id.strip().rpartition("#")
        if not sep or not name.strip() or not tag.strip() or len(riot_id) > 100:
            raise ValueError("Use o Riot ID no formato Nome#TAG.")
        data = await self.get(
            self.region(platform),
            f"/riot/account/v1/accounts/by-riot-id/{quote(name.strip(), safe='')}/{quote(tag.strip(), safe='')}",
            ttl=3600,
        )
        if not isinstance(data, dict) or not data.get("puuid"):
            raise RiotError(200, "Riot nao retornou um PUUID valido.")
        return data

    async def spectator(self, puuid, platform="BR1"):
        self.region(platform)
        data = await self.get(
            platform.lower(),
            "/lol/spectator/v5/active-games/by-summoner/" + quote(puuid, safe=""),
            ttl=15,
            missing=True,
        )
        if data is not None and (
            not isinstance(data, dict)
            or not isinstance(data.get("participants"), list)
            or not all(isinstance(p, dict) for p in data.get("participants", []))
            or not data.get("gameId")
        ):
            raise RiotError(200, "Spectator retornou partida invalida.")
        return data

    async def match(self, match_id, platform="BR1"):
        data = await self.get(
            self.region(platform),
            "/lol/match/v5/matches/" + quote(match_id, safe=""),
            ttl=86400,
            missing=True,
        )
        if data is not None and (
            not isinstance(data, dict)
            or not isinstance(data.get("info"), dict)
            or not isinstance(data.get("info", {}).get("participants"), list)
            or not all(
                isinstance(p, dict)
                for p in data.get("info", {}).get("participants", [])
            )
        ):
            raise RiotError(200, "Match-V5 retornou resultado invalido.")
        if (
            data is not None
            and data.get("metadata", {}).get("matchId", match_id) != match_id
        ):
            raise RiotError(
                200, "Match-V5 retornou um identificador diferente do solicitado."
            )
        return data

    async def timeline(self, match_id, platform="BR1"):
        data = await self.get(
            self.region(platform),
            "/lol/match/v5/matches/" + quote(match_id, safe="") + "/timeline",
            ttl=86400,
            missing=True,
        )
        if data is not None and (
            not isinstance(data, dict)
            or not isinstance(data.get("info"), dict)
            or not isinstance(data["info"].get("frames"), list)
            or data.get("metadata", {}).get("matchId") != match_id
        ):
            raise RiotError(200, "Timeline Riot invalida ou de outra partida.")
        return data

    async def history(self, puuid, platform="BR1", count=5, queue=None):
        count = max(1, min(100, int(count)))
        suffix = f"&queue={int(queue)}" if queue is not None else ""
        ids = await self.get(
            self.region(platform),
            "/lol/match/v5/matches/by-puuid/"
            + quote(puuid, safe="")
            + f"/ids?start=0&count={count}{suffix}",
            ttl=120,
        )
        if not isinstance(ids, list) or not all(isinstance(mid, str) for mid in ids):
            raise RiotError(200, "Historico Riot invalido.")
        return [m for mid in ids if (m := await self.match(mid, platform)) is not None]

    async def rank(self, puuid, platform="BR1", queue_id=420):
        data = await self.get(
            platform.lower(),
            "/lol/league/v4/entries/by-puuid/" + quote(puuid, safe=""),
            ttl=120,
            missing=True,
        )
        if data is None:
            return "indisponivel"
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise RiotError(200, "League-V4 retornou formato invalido.")
        solo = next(
            (
                r
                for r in data
                if r.get("queueType")
                == ("RANKED_FLEX_SR" if queue_id == 440 else "RANKED_SOLO_5x5")
            ),
            None,
        )
        if solo and not all(k in solo for k in ("tier", "rank", "leaguePoints")):
            raise RiotError(200, "Elo Riot incompleto.")
        return (
            f"{solo['tier']} {solo['rank']} · {solo.get('leaguePoints', 0)} LP"
            if solo
            else ("sem elo flex" if queue_id == 440 else "sem elo solo/duo")
        )

    async def ranked_stats(self, puuid, platform="BR1", queue_id=420):
        queue_type = "RANKED_FLEX_SR" if queue_id == 440 else "RANKED_SOLO_5x5"
        queue_name = "Flex" if queue_id == 440 else "Solo/Duo"
        data = await self.get(
            platform.lower(),
            "/lol/league/v4/entries/by-puuid/" + quote(puuid, safe=""),
            ttl=120,
            missing=True,
        )
        if data is None:
            return None
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise RiotError(200, "League-V4 retornou formato invalido.")
        entry = next((r for r in data if r.get("queueType") == queue_type), None)
        if entry is None:
            return {
                "queue_id": 440 if queue_id == 440 else 420,
                "queue_name": queue_name,
                "wins": 0,
                "losses": 0,
                "count": 0,
                "win_rate": None,
                "source": "League-V4",
            }
        wins, losses = entry.get("wins"), entry.get("losses")
        if type(wins) is not int or type(losses) is not int or wins < 0 or losses < 0:
            raise RiotError(
                200, "League-V4 retornou contagens de vitorias/derrotas invalidas."
            )
        count = wins + losses
        return {
            "queue_id": 440 if queue_id == 440 else 420,
            "queue_name": queue_name,
            "wins": wins,
            "losses": losses,
            "count": count,
            "win_rate": 100 * wins / count if count else None,
            "source": "League-V4",
        }

    async def mastery(self, puuid, champion_id, platform="BR1"):
        return await self.get(
            platform.lower(),
            f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{quote(puuid, safe='')}/by-champion/{int(champion_id)}",
            ttl=900,
            missing=True,
        )


class DataDragon:
    """Metadata and official images only; never a source of build performance statistics."""

    def __init__(self, base_url="https://ddragon.leagueoflegends.com"):
        self.base_url, self.session = base_url, None
        self.expires, self.data = 0, None
        self.lock = asyncio.Lock()

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def catalog(self):
        async with self.lock:
            if self.data and self.expires > time.monotonic():
                return self.data
            if self.session is None:
                self.session = aiohttp.ClientSession(
                    trust_env=True, timeout=aiohttp.ClientTimeout(total=15, connect=5)
                )

            async def read(path):
                try:
                    async with self.session.get(self.base_url + path) as response:
                        if response.status != 200:
                            raise RiotError(
                                response.status, "Data Dragon indisponivel."
                            )
                        return await response.json()
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    raise RiotError(
                        0, "Falha de rede ou formato no Data Dragon."
                    ) from None

            versions = await read("/api/versions.json")
            if (
                not isinstance(versions, list)
                or not versions
                or not isinstance(versions[0], str)
            ):
                raise RiotError(200, "Lista de patches invalida.")
            version = versions[0]
            champions, items = await asyncio.gather(
                read(f"/cdn/{version}/data/pt_BR/champion.json"),
                read(f"/cdn/{version}/data/pt_BR/item.json"),
            )
            if (
                not isinstance(champions, dict)
                or not isinstance(items, dict)
                or not isinstance(champions.get("data"), dict)
                or not isinstance(items.get("data"), dict)
            ):
                raise RiotError(200, "Catalogo Data Dragon invalido.")
            self.data = {
                "version": version,
                "champions": {str(c["key"]): c for c in champions["data"].values()},
                "items": items["data"],
            }
            self.expires = time.monotonic() + 1800
            return self.data


def _history_rows(matches, puuid, champion_id=None, queue_id=None, limit=None):
    rows = []
    seen = set()
    for match in matches:
        mid = match.get("metadata", {}).get("matchId")
        if mid and mid in seen:
            continue
        if mid:
            seen.add(mid)
        info = match.get("info", {})
        if queue_id is not None and info.get("queueId") != queue_id:
            continue
        p = next(
            (p for p in info.get("participants", []) if p.get("puuid") == puuid), None
        )
        if (
            not p
            or p.get("gameEndedInEarlySurrender")
            or info.get("gameDuration", 0) < 300
            or not isinstance(p.get("win"), bool)
            or (champion_id is not None and p.get("championId") != champion_id)
        ):
            continue
        rows.append((p, info))
        if limit is not None and len(rows) >= limit:
            break
    return rows


def win_rate_stats(matches, puuid, champion_id=None, queue_id=None, limit=None):
    rows = _history_rows(matches, puuid, champion_id, queue_id, limit)
    if not rows:
        return None
    wins = sum(p["win"] for p, info in rows)
    dates = [
        info.get("gameEndTimestamp") or info.get("gameCreation") for p, info in rows
    ]
    dates = [v for v in dates if isinstance(v, (int, float)) and v > 0]
    return {
        "count": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "win_rate": 100 * wins / len(rows),
        "champion_id": champion_id,
        "queue_id": queue_id,
        "start_at": min(dates) if dates else None,
        "end_at": max(dates) if dates else None,
    }


def recent_stats(matches, puuid, queue_id=None, limit=None):
    stats = win_rate_stats(matches, puuid, queue_id=queue_id, limit=limit)
    if stats is None:
        return None
    pairs = _history_rows(matches, puuid, queue_id=queue_id, limit=limit)
    rows = [
        p
        for p, info in pairs
        if all(
            isinstance(p.get(k), (int, float)) for k in ["kills", "deaths", "assists"]
        )
    ]
    n = len(rows)
    return {
        **stats,
        "kda_count": n,
        "kills": sum(p["kills"] for p in rows) / n if n else None,
        "deaths": sum(p["deaths"] for p in rows) / n if n else None,
        "assists": sum(p["assists"] for p in rows) / n if n else None,
        "kda": sum((p["kills"] + p["assists"]) / max(1, p["deaths"]) for p in rows) / n
        if n
        else None,
        "damage": sum(p["totalDamageDealtToChampions"] for p in rows) / n
        if n and all("totalDamageDealtToChampions" in p for p in rows)
        else None,
    }
