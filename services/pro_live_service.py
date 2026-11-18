from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from services.pro_live_platforms import LiveState, PlatformClient, PlatformError


log = logging.getLogger(__name__)
PLATFORMS = {"LCK": {"soop", "chzzk"}, "LPL": {"huya", "douyu", "bilibili"}}
ROLES = {"TOP", "JUNGLE", "MID", "ADC", "SUPPORT"}
URLS = {
    "soop": "https://play.sooplive.com/{}",
    "chzzk": "https://chzzk.naver.com/live/{}",
    "huya": "https://www.huya.com/{}",
    "douyu": "https://www.douyu.com/{}",
    "bilibili": "https://live.bilibili.com/{}",
    "twitch": "https://www.twitch.tv/{}",
}


@dataclass(frozen=True)
class Account:
    player_id: str
    name: str
    team: str
    league: str
    role: str
    platform: str
    channel_id: str
    platform_user_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.player_id}:{self.platform}:{self.channel_id}"

    @property
    def url(self) -> str:
        return URLS[self.platform].format(self.channel_id)


@dataclass(frozen=True)
class ReviewWarning:
    player_id: str
    name: str
    message: str


@dataclass(frozen=True)
class PendingAccount:
    account: Account
    reason: str


@dataclass(frozen=True)
class Catalog:
    accounts: tuple[Account, ...] = ()
    eligible_players: int = 0
    excluded_players: int = 0
    review_warnings: tuple[ReviewWarning, ...] = ()
    pending_accounts: tuple[PendingAccount, ...] = ()


def _date(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Datas precisam de fuso horario.")
    return result


def _sources(values: object) -> None:
    if not isinstance(values, list) or not values or len(values) > 10:
        raise ValueError("Informe fontes de verificacao.")
    for value in values:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Fontes devem ser URLs HTTPS publicas sem credenciais.")


def load_catalog(path: Path, now: datetime | None = None) -> Catalog:
    """Load an explicitly reviewed roster; never derive channel IDs from names.

    This is evidence metadata, not automated certification of its sources.
    Review/contract dates never revoke competitive eligibility or channel
    ownership. Departure requires an explicit, sourced competitive decision.
    Unsupported scope is excluded; malformed configuration still fails closed.
    """
    now = now or datetime.now(timezone.utc)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("players"), list):
        raise ValueError("Catalogo precisa de schema_version=1 e players[].")
    if len(raw["players"]) > 200:
        raise ValueError("Catalogo excede 200 jogadores.")
    accounts, players, seen_players, seen_channels = [], 0, set(), set()
    pending: list[PendingAccount] = []
    seen_twitch_users: set[str] = set()
    warnings: list[ReviewWarning] = []
    for player in raw["players"]:
        if not isinstance(player, dict):
            raise ValueError("Jogador invalido.")
        league = player.get("league")
        channels = player.get("channels")
        global_twitch = (isinstance(league, str) and 0 < len(league.strip()) <= 40
                         and isinstance(channels, list)
                         and any(isinstance(c, dict) and c.get("platform") == "twitch" for c in channels))
        regional = league in PLATFORMS and type(player.get("division")) is int and player["division"] == 1
        if (not (regional or global_twitch) or player.get("role") not in ROLES):
            continue
        for field in ("id", "name", "team"):
            if not isinstance(player[field], str) or not player[field].strip() or len(player[field]) > 80:
                raise ValueError("ID, nome e equipe devem ter 1 a 80 caracteres.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", player["id"]) or player["id"] in seen_players:
            raise ValueError("ID de jogador invalido ou duplicado.")
        seen_players.add(player["id"])

        def review(message: str) -> None:
            warnings.append(ReviewWarning(player["id"], player["name"], message))

        _sources(player["roster_sources"])
        competitive = player.get("competitive_status", "tier1")
        if competitive not in ("tier1", "unconfirmed", "out_of_scope"):
            raise ValueError("Status competitivo invalido.")
        if competitive == "out_of_scope":
            confirmation = player.get("competitive_status_confirmation")
            if (isinstance(confirmation, dict) and confirmation.get("sources")
                    and confirmation.get("verified_at") and isinstance(confirmation.get("reason"), str)
                    and confirmation["reason"].strip()):
                _sources(confirmation["sources"])
                if _date(confirmation["verified_at"]) <= now:
                    continue
            review("Saida Tier 1 sem confirmacao efetiva completa; monitoramento mantido.")
        elif competitive == "unconfirmed":
            review("Vinculo competitivo em revisao; monitoramento mantido.")
        if player.get("active") is not True:
            review("Indicador active legado nao confirma saida Tier 1; revisar status competitivo.")

        verified, expires = _date(player["verified_at"]), _date(player["valid_until"])
        if expires <= now:
            review("Prazo de revisão vencido; monitoramento mantido.")
        elif verified > now or expires <= verified or expires - verified > timedelta(days=7):
            review("Datas de revisao inconsistentes ou intervalo superior a sete dias; monitoramento mantido.")

        contract = player.get("contract_status", "unknown")
        if contract not in ("unknown", "confirmed", "expired", "renewal_unconfirmed"):
            raise ValueError("Status contratual invalido.")
        if contract == "expired":
            review("Contrato vencido; status competitivo preservado ate confirmacao de saida Tier 1.")
        elif contract == "renewal_unconfirmed":
            review("Renovação contratual não confirmada; monitoramento mantido.")
        players += 1
        if not isinstance(player["channels"], list) or len(player["channels"]) > 5:
            raise ValueError("channels deve ter ate 5 contas confirmadas.")
        for channel in player["channels"]:
            platform, channel_id = channel["platform"], channel["channel_id"]
            if platform != "twitch" and (not regional or platform not in PLATFORMS.get(league, set())):
                raise ValueError("Plataforma fora das permitidas para a liga.")
            if not isinstance(channel_id, str):
                raise ValueError("channel_id precisa ser string.")
            pattern = (r"[a-z0-9_]{1,25}" if platform == "twitch" else
                       r"[a-f0-9]{32}" if platform == "chzzk" else
                       r"[A-Za-z0-9_]{1,40}" if platform == "soop" else r"[1-9][0-9]{0,19}")
            if not re.fullmatch(pattern, channel_id):
                raise ValueError("channel_id invalido; use ID canonico, nao URL ou apelido.")
            _sources(channel["source_urls"])
            identity = (platform, channel_id)
            if identity in seen_channels:
                raise ValueError("Uma conta nao pode estar associada a varios jogadores.")
            seen_channels.add(identity)
            user_id = channel.get("user_id", "") if platform == "twitch" else ""
            status = channel.get("monitoring_status", "ready")
            if status not in ("ready", "pending"):
                raise ValueError("Status de monitoramento invalido.")
            account = Account(player["id"], player["name"], player["team"], league,
                              player["role"], platform, channel_id, user_id)
            if status == "pending":
                reason = channel.get("pending_reason")
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                    raise ValueError("Informe motivo da conta pendente.")
                pending.append(PendingAccount(account, reason))
                continue
            if platform == "twitch" and (not isinstance(user_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", user_id)):
                raise ValueError("Conta Twitch pronta exige user_id numerico confirmado.")
            if platform == "twitch":
                if user_id in seen_twitch_users:
                    raise ValueError("Titular Twitch associado a mais de uma conta; revise os logins.")
                seen_twitch_users.add(user_id)
            checked = _date(channel["verified_at"])
            if checked > now or now - checked > timedelta(days=30):
                review(f"Revisar associacao {platform}/{channel_id}: data futura ou verificacao com mais de 30 dias; canal mantido.")
            accounts.append(account)
    if len(accounts) + len(pending) > 200:
        raise ValueError("Catalogo excede 200 contas.")
    return Catalog(tuple(accounts), players, len(raw["players"]) - players, tuple(warnings), tuple(pending))


@dataclass(frozen=True)
class Delivery:
    account_key: str
    session_id: str
    guild_id: int
    channel_id: int
    title: str


class LiveRepository:
    """SQLite transactions run in threads; connections are never shared across threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS live_state (
                account TEXT PRIMARY KEY, live INTEGER NOT NULL,
                session TEXT NOT NULL, title TEXT NOT NULL, checked REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS seen_sessions (
                account TEXT NOT NULL, session TEXT NOT NULL, checked REAL NOT NULL,
                PRIMARY KEY (account, session));
            CREATE TABLE IF NOT EXISTS deliveries (
                account TEXT NOT NULL, session TEXT NOT NULL,
                guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
                created REAL NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account, session, guild_id, channel_id));
        """)
        return connection

    async def _run(self, operation):
        async with self.lock:
            def work():
                connection = self._connect()
                try:
                    with connection:
                        return operation(connection)
                finally:
                    connection.close()
            return await asyncio.to_thread(work)

    async def subscribe(self, guild_id: int, channel_id: int | None) -> None:
        def work(c):
            c.execute("DELETE FROM deliveries WHERE guild_id=? AND sent=0", (guild_id,))
            if channel_id is None:
                c.execute("DELETE FROM subscriptions WHERE guild_id=?", (guild_id,))
            else:
                c.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?)", (guild_id, channel_id))
        await self._run(work)

    async def subscriptions(self) -> dict[int, int]:
        return await self._run(lambda c: dict(c.execute("SELECT guild_id, channel_id FROM subscriptions")))

    async def observe(self, states: dict[str, LiveState], now: float | None = None) -> list[Delivery]:
        now = time.time() if now is None else now
        def work(c):
            c.execute("DELETE FROM deliveries WHERE (sent=0 AND created<?) OR created<?", (now - 1800, now - 30 * 86400))
            c.execute("DELETE FROM live_state WHERE checked<?", (now - 30 * 86400,))
            c.execute("DELETE FROM seen_sessions WHERE checked<?", (now - 30 * 86400,))
            targets = list(c.execute("SELECT guild_id, channel_id FROM subscriptions"))
            result = []
            for key, state in states.items():
                old = c.execute("SELECT live, session FROM live_state WHERE account=?", (key,)).fetchone()
                # First observation is a baseline; session changes catch restarts
                # that happen between two polls without an observed offline state.
                unseen_session = False
                if state.live:
                    unseen_session = c.execute(
                        "INSERT OR IGNORE INTO seen_sessions VALUES (?, ?, ?)",
                        (key, state.session_id, now),
                    ).rowcount == 1
                    c.execute("UPDATE seen_sessions SET checked=? WHERE account=? AND session=?",
                              (now, key, state.session_id))
                if state.live and unseen_session and old and (not old[0] or old[1] != state.session_id):
                    for guild, channel in targets:
                        c.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, ?, ?, 0)",
                                  (key, state.session_id, guild, channel, now))
                c.execute("INSERT OR REPLACE INTO live_state VALUES (?, ?, ?, ?, ?)",
                          (key, int(state.live), state.session_id, state.title, now))
                if state.live:
                    for session, guild, channel in c.execute("""
                        SELECT d.session, d.guild_id, d.channel_id FROM deliveries d
                        JOIN subscriptions s ON s.guild_id=d.guild_id AND s.channel_id=d.channel_id
                        WHERE d.account=? AND d.session=? AND d.sent=0
                    """, (key, state.session_id)):
                        result.append(Delivery(key, session, guild, channel, state.title))
            return result
        return await self._run(work)

    async def acknowledge(self, delivery: Delivery) -> None:
        await self._run(lambda c: c.execute("""
            UPDATE deliveries SET sent=1 WHERE account=? AND session=? AND guild_id=? AND channel_id=?
        """, (delivery.account_key, delivery.session_id, delivery.guild_id, delivery.channel_id)).rowcount)


class LiveMonitor:
    def __init__(self, roster_path: Path, repository: LiveRepository, client: PlatformClient | None = None) -> None:
        self.roster_path = roster_path
        self.repository = repository
        self.client = client or PlatformClient()
        self.catalog = Catalog()
        self.catalog_error: str | None = None
        self.health: dict[str, str] = {}
        self.last_check: datetime | None = None
        self.lock = asyncio.Lock()

    async def reload(self) -> None:
        try:
            self.catalog = await asyncio.to_thread(load_catalog, self.roster_path)
            self.catalog_error = None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.catalog = Catalog()
            self.catalog_error = "Catalogo ausente ou invalido; corrija pro_lives_roster.json conforme docs/pro_lives.md."

    async def poll(self) -> list[Delivery]:
        async with self.lock:
            await self.reload()
            self.health = {}
            if not self.catalog.accounts or not await self.repository.subscriptions():
                return []
            states: dict[str, LiveState] = {}
            async def one(account: Account) -> None:
                try:
                    states[account.key] = await self.client.check(account.platform, account.channel_id)
                    self.health[account.key] = "ok"
                except PlatformError as exc:
                    self.health[account.key] = str(exc)
                except Exception as exc:
                    self.health[account.key] = f"Erro de consulta: {type(exc).__name__}"
                    log.warning("ProLives %s: %s", account.platform, type(exc).__name__)
            chzzk_accounts = [a for a in self.catalog.accounts if a.platform == "chzzk"]
            twitch_accounts = [a for a in self.catalog.accounts if a.platform == "twitch"]
            async def chzzk() -> None:
                try:
                    found = await self.client.chzzk([a.channel_id for a in chzzk_accounts])
                    for a in chzzk_accounts:
                        states[a.key] = found[a.channel_id]
                        self.health[a.key] = "ok"
                except Exception as exc:
                    message = str(exc) if isinstance(exc, PlatformError) else f"Erro CHZZK: {type(exc).__name__}"
                    for a in chzzk_accounts:
                        self.health[a.key] = message
            async def twitch() -> None:
                try:
                    found = await self.client.twitch({a.channel_id: a.platform_user_id for a in twitch_accounts})
                    for a in twitch_accounts:
                        result = found.get(a.channel_id)
                        if isinstance(result, LiveState):
                            states[a.key] = result
                            self.health[a.key] = "ok"
                        else:
                            self.health[a.key] = str(result) if isinstance(result, PlatformError) else "Twitch: conta sem estado valido."
                except Exception as exc:
                    message = str(exc) if isinstance(exc, PlatformError) else f"Erro Twitch: {type(exc).__name__}"
                    for a in twitch_accounts:
                        self.health[a.key] = message
            jobs = [asyncio.create_task(one(a)) for a in self.catalog.accounts if a.platform not in ("chzzk", "twitch")]
            if chzzk_accounts:
                jobs.append(asyncio.create_task(chzzk()))
            if twitch_accounts:
                jobs.append(asyncio.create_task(twitch()))
            try:
                async with asyncio.timeout(210):
                    await asyncio.gather(*jobs)
            except TimeoutError:
                for a in self.catalog.accounts:
                    self.health.setdefault(a.key, "Ciclo excedeu 210s; estado desconhecido.")
            finally:
                for job in jobs:
                    if not job.done():
                        job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
            self.last_check = datetime.now(timezone.utc)
            return await self.repository.observe(states)
