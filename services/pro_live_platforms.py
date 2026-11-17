"""Read-only live metadata. An unavailable/changed endpoint is never 'offline'."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import aiohttp


SOOP_STATION_URL = "https://api-channel.sooplive.com/v1.1/channel/{channel_id}/station"
SOOP_PLAYER_URL = "https://live.sooplive.com/afreeca/player_live_api.php"
TWITCH_PAGE_URL = "https://www.twitch.tv/"
TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_STATUS_QUERY = """query ProLiveStatus($login: String!) {
  user(login: $login) {
    id login displayName broadcastSettings { title }
    stream { id type createdAt }
  }
}"""


def parse_twitch(data: object, login: str, user_id: str) -> LiveState:
    """A missing/deleted user, GraphQL error or changed owner is not offline."""
    if not isinstance(data, dict) or data.get("errors"):
        raise PlatformError("Twitch recusou a consulta; estado desconhecido.")
    payload = data.get("data")
    user = payload.get("user") if isinstance(payload, dict) else None
    if (not isinstance(user, dict) or user.get("login") != login
            or not isinstance(user.get("id"), str) or user["id"] != user_id
            or not re.fullmatch(r"[1-9][0-9]{0,19}", user_id) or "stream" not in user):
        raise PlatformError("Twitch nao confirmou a conta e seu titular; estado desconhecido.")
    stream = user["stream"]
    if stream is None:
        return LiveState(False)
    if not isinstance(stream, dict) or stream.get("type") not in ("live", "rerun"):
        raise PlatformError("Twitch retornou estado de transmissao desconhecido.")
    if stream["type"] == "rerun":
        return LiveState(False)
    session = stream.get("id")
    settings = user.get("broadcastSettings")
    if (not isinstance(session, str) or not re.fullmatch(r"[1-9][0-9]{0,24}", session)
            or not isinstance(settings, dict) or not isinstance(settings.get("title"), str)
            or not isinstance(stream.get("createdAt"), str)):
        raise PlatformError("Twitch retornou live sem sessao, titulo ou horario validos.")
    try:
        started = datetime.fromisoformat(stream["createdAt"].replace("Z", "+00:00"))
        if started.tzinfo is None:
            raise ValueError
    except ValueError:
        raise PlatformError("Twitch retornou horario de live invalido.") from None
    return LiveState(True, session, settings["title"])


class PlatformError(RuntimeError):
    """Messages are safe for logs: never include response bodies or credentials."""


class PlatformHTTPError(PlatformError):
    def __init__(self, platform: str, status: int) -> None:
        super().__init__(f"{platform}: HTTP {status}.")
        self.status = status


@dataclass(frozen=True)
class LiveState:
    live: bool
    session_id: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        if self.live and not self.session_id:
            raise PlatformError("Transmissao sem identificador de sessao.")


def _flag(value: object) -> int:
    if type(value) not in (int, str) or str(value) not in ("0", "1", "2"):
        raise PlatformError("Estado de transmissao desconhecido.")
    return int(value)


def parse_douyu(data: dict, channel_id: str) -> LiveState:
    room = data["room"]
    if str(room["room_id"]) != channel_id:
        raise PlatformError("Douyu retornou outra sala.")
    status = _flag(room["show_status"])
    # videoLoop is replay, not the player streaming live.
    replay = _flag(room["videoLoop"])
    if status != 1 or replay != 0:
        return LiveState(False)
    session = str(room["show_id"])
    if not session.isdigit() or int(session) <= 0:
        raise PlatformError("Douyu sem identificador de live.")
    return LiveState(True, session, str(room["room_name"]))


def parse_huya(page: str, channel_id: str) -> LiveState:
    match = re.search(r"\bvar\s+TT_ROOM_DATA\s*=\s*", page)
    if not match:
        raise PlatformError("Huya sem TT_ROOM_DATA; pagina bloqueada ou formato alterado.")
    room, _ = json.JSONDecoder().raw_decode(page[match.end():])
    if str(room["profileRoom"]) != channel_id:
        raise PlatformError("Huya retornou outra sala; use o ID numerico canonico.")
    if type(room["isOn"]) is not bool or type(room["isReplay"]) is not bool:
        raise PlatformError("Huya retornou estado invalido.")
    if room["isReplay"] or (room["state"] == "OFF" and not room["isOn"]):
        return LiveState(False)
    if room["state"] != "ON" or not room["isOn"]:
        raise PlatformError("Estado Huya desconhecido.")
    session = str(room["liveId"])
    if not session.isdigit() or int(session) <= 0:
        raise PlatformError("Huya sem identificador de live.")
    return LiveState(True, session, str(room["introduction"]))


def parse_bilibili(data: dict, channel_id: str) -> LiveState:
    if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 0:
        raise PlatformError("Bilibili recusou a consulta.")
    room = data.get("data")
    if not isinstance(room, dict) or str(room.get("room_id")) != channel_id:
        raise PlatformError("Bilibili retornou outra sala; use room_id canonico.")
    status = _flag(room.get("live_status"))
    if status in (0, 2):  # 2 is replay/round, not live
        return LiveState(False)
    start, title = room.get("live_time"), room.get("title")
    if (not isinstance(start, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", start)
            or not isinstance(title, str)):
        raise PlatformError("Bilibili sem horario inicial ou titulo validos.")
    try:
        datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise PlatformError("Bilibili sem horario inicial valido.") from None
    return LiveState(True, start, title)


def validate_soop_station(data: object, channel_id: str) -> None:
    station = data.get("station") if isinstance(data, dict) else None
    if (not isinstance(station, dict) or station.get("userId") != channel_id
            or type(station.get("stationNo")) is not int or station["stationNo"] <= 0
            or not isinstance(station.get("userNick"), str) or not station["userNick"].strip()):
        raise PlatformError("SOOP nao confirmou a existencia e a identidade da estacao.")


def parse_soop(data: object, channel_id: str, station: object) -> LiveState:
    """RESULT=0 is offline in SOOP's player, but invalid IDs also return it.

    Require a separately confirmed station on every check, and bind live
    metadata to that same ID. HTTP 200 alone is never a live/offline signal.
    """
    validate_soop_station(station, channel_id)
    room = data.get("CHANNEL") if isinstance(data, dict) else None
    if not isinstance(room, dict) or type(room.get("RESULT")) is not int:
        raise PlatformError("SOOP retornou formato de estado invalido.")
    result = room["RESULT"]
    if "BJID" in room and room["BJID"] != channel_id:
        raise PlatformError("SOOP retornou transmissao de outra estacao.")
    if result == 0:
        if room.get("BNO") not in (None, "", 0, "0"):
            raise PlatformError("SOOP retornou estado offline com sessao ativa; consulta inconclusiva.")
        return LiveState(False)
    if result != 1:
        raise PlatformError(f"SOOP recusou a consulta (RESULT={result}); estado desconhecido.")
    session = str(room.get("BNO", ""))
    if (room.get("BJID") != channel_id or not session.isdigit()
            or len(session) > 20 or int(session) <= 0 or not isinstance(room.get("TITLE"), str)):
        raise PlatformError("SOOP retornou live sem identidade, BNO ou titulo validos.")
    return LiveState(True, session, room["TITLE"])


def parse_chzzk_page(data: dict) -> tuple[dict[str, LiveState], str | None]:
    if data.get("code") != 200:
        raise PlatformError("CHZZK recusou a consulta.")
    content = data["content"]
    states = {}
    for item in content["data"]:
        session = str(item["liveId"])
        if not session.isdigit() or int(session) <= 0:
            raise PlatformError("CHZZK sem liveId valido.")
        states[item["channelId"]] = LiveState(True, session, str(item["liveTitle"]))
    cursor = content["page"].get("next")
    if cursor is not None and not isinstance(cursor, str):
        raise PlatformError("CHZZK retornou paginacao invalida.")
    return states, cursor or None


def retry_seconds(value: str | None) -> float:
    try:
        return max(60.0, float(value))
    except (ValueError, TypeError):
        try:
            return max(60.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 300.0


class PlatformClient:
    """One shared session; <=1 request/sec/platform, four in flight globally.

    Native HTTPS proxy and system CA configuration are retained. No cookies,
    browser automation, signature generation or challenge bypasses are used.
    """

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self.locks: dict[str, asyncio.Lock] = {}
        self.next_request: dict[str, float] = {}
        self.blocked_until: dict[str, float] = {}
        self.failures: dict[str, int] = {}
        self.slots = asyncio.Semaphore(4)
        self.twitch_web_client_id: str | None = None
        self.twitch_web_client_expires = 0.0

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def request(self, platform: str, url: str, *, text: bool = False, method: str = "GET", **kwargs):
        lock = self.locks.setdefault(platform, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            if now < self.blocked_until.get(platform, 0):
                raise PlatformError("Plataforma em espera apos erro ou limite de requisicoes.")
            await asyncio.sleep(max(0, self.next_request.get(platform, 0) - now))
            if self.session is None:
                self.session = aiohttp.ClientSession(
                    trust_env=True,
                    timeout=aiohttp.ClientTimeout(total=12, connect=5),
                    headers={"User-Agent": "DiscordBot-ProLives/1.0", "Accept": "application/json, text/html"},
                )
            try:
                async with self.slots:
                    async with self.session.request(method, url, **kwargs) as response:
                        if response.status != 200:
                            if response.status == 429:
                                self.blocked_until[platform] = time.monotonic() + retry_seconds(response.headers.get("Retry-After"))
                            raise PlatformHTTPError(platform, response.status)
                        # Bound memory even if a platform returns an unexpected page.
                        chunks = []
                        size = 0
                        async for chunk in response.content.iter_chunked(65536):
                            size += len(chunk)
                            if size > 2_000_000:
                                raise PlatformError("Resposta excedeu o limite de 2 MB.")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        content = body.decode("utf-8")
                        result = content if text else json.loads(content)
                        self.failures[platform] = 0
                        return result
            except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError, ValueError, PlatformError) as exc:
                # A removed/nonexistent SOOP station is an account-level error,
                # not a reason to suspend checks of every other player.
                if platform == "soop" and isinstance(exc, PlatformHTTPError) and exc.status == 404:
                    raise
                self.failures[platform] = min(5, self.failures.get(platform, 0) + 1)
                delay = min(1800, 60 * 2 ** (self.failures[platform] - 1))
                self.blocked_until[platform] = max(self.blocked_until.get(platform, 0), time.monotonic() + delay)
                if isinstance(exc, PlatformError):
                    raise
                raise PlatformError(f"{platform}: falha de rede ou resposta invalida ({type(exc).__name__}).") from None
            finally:
                self.next_request[platform] = time.monotonic() + 1

    async def check(self, platform: str, channel_id: str) -> LiveState:
        try:
            if platform == "douyu":
                return parse_douyu(await self.request(platform, f"https://www.douyu.com/betard/{channel_id}"), channel_id)
            if platform == "huya":
                return parse_huya(await self.request(platform, f"https://www.huya.com/{channel_id}", text=True), channel_id)
            if platform == "bilibili":
                return parse_bilibili(await self.request(platform, "https://api.live.bilibili.com/room/v1/Room/get_info", params={"room_id": channel_id}), channel_id)
            if platform == "soop":
                station = await self.request(platform, SOOP_STATION_URL.format(channel_id=channel_id))
                validate_soop_station(station, channel_id)
                data = await self.request(platform, SOOP_PLAYER_URL, method="POST", params={"bjid": channel_id}, data={
                    "bid": channel_id, "bno": "", "type": "live", "from_api": "0", "mode": "live",
                    "player_type": "html5", "stream_type": "common", "pwd": "", "quality": "HD",
                })
                return parse_soop(data, channel_id, station)
            raise PlatformError("Plataforma nao suportada por consulta individual.")
        except (KeyError, TypeError, ValueError):
            raise PlatformError(f"{platform}: formato da resposta mudou.") from None

    async def chzzk(self, channel_ids: list[str]) -> dict[str, LiveState]:
        client_id, secret = os.getenv("CHZZK_CLIENT_ID"), os.getenv("CHZZK_CLIENT_SECRET")
        if not client_id or not secret:
            raise PlatformError("CHZZK exige CHZZK_CLIENT_ID e CHZZK_CLIENT_SECRET de aplicativo registrado.")
        states: dict[str, LiveState] = {}
        cursor = None
        seen = set()
        # Official API only offers the whole live list, 20/page. Do not mark
        # absent channels offline unless traversal actually completed.
        try:
            for _ in range(80):
                params = {"size": "20"}
                if cursor:
                    params["next"] = cursor
                data = await self.request("chzzk", "https://openapi.chzzk.naver.com/open/v1/lives", params=params,
                                          headers={"Client-Id": client_id, "Client-Secret": secret})
                page, cursor = parse_chzzk_page(data)
                states.update(page)
                if not cursor:
                    return {key: states.get(key, LiveState(False)) for key in channel_ids}
                if cursor in seen:
                    break
                seen.add(cursor)
        except (KeyError, TypeError, ValueError):
            raise PlatformError("CHZZK: formato da resposta mudou.") from None
        raise PlatformError("CHZZK: lista incompleta; nenhum canal foi considerado offline.")

    async def twitch(self, expected_ids: dict[str, str]) -> dict[str, LiveState | PlatformError]:
        """Read the public website's metadata, in batches of <=20 accounts.

        The website client identifier is public, discovered from its HTML;
        no user token, playback token or integrity/challenge bypass is used.
        This internal endpoint can change or block access: fail as unknown.
        """
        if not expected_ids:
            return {}
        if len(expected_ids) > 200 or any(
                not re.fullmatch(r"[a-z0-9_]{1,25}", login)
                or not re.fullmatch(r"[1-9][0-9]{0,19}", uid)
                for login, uid in expected_ids.items()):
            raise PlatformError("Twitch exige logins e IDs de titular confirmados.")
        if not self.twitch_web_client_id or time.monotonic() >= self.twitch_web_client_expires:
            page = await self.request("twitch", TWITCH_PAGE_URL, text=True)
            match = re.search(r'(?:"clientId"|\bclientId)\s*[:=]\s*"([A-Za-z0-9]{20,64})"', page)
            if not match:
                raise PlatformError("Twitch nao disponibilizou identificador publico; consulta indisponivel.")
            self.twitch_web_client_id = match[1]
            self.twitch_web_client_expires = time.monotonic() + 6 * 3600
        result: dict[str, LiveState | PlatformError] = {}
        logins = list(expected_ids)
        for offset in range(0, len(logins), 20):
            batch = logins[offset:offset + 20]
            operations = [{"operationName": "ProLiveStatus", "query": TWITCH_STATUS_QUERY,
                           "variables": {"login": login}} for login in batch]
            try:
                data = await self.request("twitch", TWITCH_GQL_URL, method="POST", json=operations,
                                          headers={"Client-ID": self.twitch_web_client_id})
                if not isinstance(data, list) or len(data) != len(batch):
                    raise PlatformError("Twitch retornou lote incompleto; estado desconhecido.")
            except PlatformError as exc:
                if isinstance(exc, PlatformHTTPError) and exc.status in (400, 401, 403):
                    self.twitch_web_client_id = None
                for login in logins[offset:]:
                    result[login] = exc
                break
            for login, item in zip(batch, data):
                try:
                    result[login] = parse_twitch(item, login, expected_ids[login])
                except PlatformError as exc:
                    result[login] = exc
        return result
