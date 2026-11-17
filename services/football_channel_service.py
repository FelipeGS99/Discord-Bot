from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Callable

import discord

from services.brasileirao_service import (
    BrasileiraoFixture, describe_fixture_update, serialize_fixtures,
)

log = logging.getLogger(__name__)
TERMINAL_STATUSES = {"finished", "cancelled", "abandoned", "awarded", "walkover", "postponed"}


def channel_name(home: str, away: str) -> str:
    names = {"sao paulo": "spfc", "palmeiras": "pal", "corinthians": "cor",
             "santos": "san", "flamengo": "fla", "vasco da gama": "vas",
             "fluminense": "flu", "botafogo": "bot"}

    def slug(team: str) -> str:
        normalized = unicodedata.normalize("NFKD", team).encode("ascii", "ignore").decode().lower()
        return names.get(normalized, re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:45] or "time")

    return f"{slug(home)}-x-{slug(away)}"


def private_overwrites(guild, role) -> dict:
    if role == guild.default_role or role.guild.id != guild.id or guild.me is None:
        raise ValueError("Escolha um cargo de futebol deste servidor, diferente de @everyone.")
    return {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              read_message_history=True, manage_channels=True, embed_links=True),
    }


class FootballChannelRepository:
    """One atomic state file; owned exclusively by the central football monitor."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return {"guilds": {}, "matches": {}}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not all(isinstance(state.get(k), dict) for k in ("guilds", "matches")):
            raise ValueError("Estado dos canais de futebol invalido; nao sera sobrescrito.")
        return state

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


class FootballChannelManager:
    def __init__(self, bot, client, repository: FootballChannelRepository,
                 embed_factory: Callable, clock: Callable[[], float] = time.time) -> None:
        self.bot, self.client, self.repository = bot, client, repository
        self.embed_factory, self.clock = embed_factory, clock
        self.state = repository.load()
        self.lock = asyncio.Lock()
        self.errors: dict[int, str] = {}

    def config(self, guild_id: int) -> dict:
        return self.state["guilds"].get(str(guild_id), {})

    async def enable(self, guild, league_id: int, role, category=None) -> None:
        private_overwrites(guild, role)
        if category is not None and category.guild.id != guild.id:
            raise ValueError("A categoria deve pertencer a este servidor.")
        async with self.lock:
            cfg = self.config(guild.id)
            cfg = {**cfg, "role_id": role.id, "category_id": category.id if category else None,
                   "retention_minutes": cfg.get("retention_minutes", 60),
                   "leagues": sorted(set(cfg.get("leagues", []) + [league_id]))}
            # Update existing channels first: changing the role must not keep the old role's access.
            for key, match in self.state["matches"].items():
                if match["guild_id"] == guild.id and not match.get("closed"):
                    channel = await self._channel(guild, match, key)
                    if channel is not None:
                        await channel.edit(overwrites=private_overwrites(guild, role),
                                           reason="Cargo de acesso aos jogos atualizado")
                        match["role_id"] = role.id
            self.state["guilds"][str(guild.id)] = cfg
            self.repository.save(self.state)

    async def disable(self, guild_id: int, league_id: int) -> None:
        async with self.lock:
            cfg = self.config(guild_id)
            cfg["leagues"] = [lid for lid in cfg.get("leagues", []) if lid != league_id]
            self.repository.save(self.state)

    async def retention(self, guild_id: int, minutes: int) -> None:
        if not 1 <= minutes <= 1440:
            raise ValueError("Informe um prazo de 1 a 1440 minutos.")
        async with self.lock:
            cfg = self.config(guild_id)
            if not cfg:
                raise ValueError("Ative uma liga primeiro.")
            cfg["retention_minutes"] = minutes
            # Existing post-match channels also respect the new deadline.
            for match in self.state["matches"].values():
                if match["guild_id"] == guild_id and match.get("finished_at") is not None and not match.get("closed"):
                    match["delete_at"] = match["finished_at"] + minutes * 60
            self.repository.save(self.state)

    @staticmethod
    def marker(key: str) -> str:
        return f"football-match:{key}"

    async def _channel(self, guild, match: dict, key: str, *, refresh=False):
        if match["channel_id"] is None:
            channels = await guild.fetch_channels()
            channel = next((c for c in channels if isinstance(c, discord.TextChannel)
                            and c.topic == self.marker(key)), None)
            if channel is not None:
                match["channel_id"] = channel.id
                self.repository.save(self.state)
            return channel
        channel = guild.get_channel(match["channel_id"])
        if channel is None or refresh:
            try:
                channel = await guild.fetch_channel(match["channel_id"])
            except discord.NotFound:
                return None
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id or channel.topic != self.marker(key):
            raise ValueError("Canal sem identificador de propriedade do bot; operacao cancelada.")
        return channel

    async def _cleanup(self) -> None:
        for key, match in list(self.state["matches"].items()):
            if match.get("closed") or match.get("delete_at") is None or self.clock() < match["delete_at"]:
                continue
            guild = self.bot.get_guild(match["guild_id"])
            if guild is None:
                continue
            try:
                channel = await self._channel(guild, match, key, refresh=True)
                if channel is not None:
                    try:
                        await channel.delete(reason="Prazo apos o fim da partida encerrado")
                    except discord.NotFound:
                        pass
                # Keep a tombstone: stale live data must never recreate a deleted match.
                match["closed"] = True
                match["close_reason"] = "expired"
                self.repository.save(self.state)
            except (discord.HTTPException, ValueError):
                self.errors[guild.id] = "Nao foi possivel excluir um canal encerrado; nova tentativa no proximo ciclo."
                log.exception("Falha ao excluir canal de futebol %s", key)

    async def recover_channels(self) -> None:
        """Resume persisted expiration even when the provider is unavailable."""
        async with self.lock:
            await self._cleanup()

    async def poll(self) -> None:
        async with self.lock:
            self.errors.clear()
            self._scorers: dict[int, list[str]] = {}
            # Expired channels can be removed even when the football API is unavailable.
            await self._cleanup()
            active = [m for m in self.state["matches"].values() if not m.get("closed")]
            if self.client is None or (not active and not any(c.get("leagues") for c in self.state["guilds"].values())):
                return
            try:
                live = await self.client.fetch_all_live_fixtures()
            except Exception:
                log.exception("Falha na consulta ao vivo; canais ativos preservados")
                for gid in self.state["guilds"]:
                    self.errors[int(gid)] = "Consulta ao vivo falhou; canais e estados preservados."
                return
            fixtures = {f.fixture_id: f for f in live}
            # Detail lookup works across midnight and confirms the end: absence from /live is not a final whistle.
            for fixture_id in {m["fixture_id"] for m in active} - fixtures.keys():
                try:
                    fixture = await self.client.fetch_fixture(fixture_id)
                    if fixture is not None:
                        fixtures[fixture_id] = fixture
                except Exception:
                    log.exception("Falha ao consultar a partida %s; estado preservado", fixture_id)
                    for match in active:
                        if match["fixture_id"] == fixture_id:
                            self.errors[match["guild_id"]] = "Detalhes de uma partida indisponiveis; encerramento ainda nao confirmado."
            for gid, cfg in list(self.state["guilds"].items()):
                guild = self.bot.get_guild(int(gid))
                if guild is None:
                    continue
                for fixture in fixtures.values():
                    key = f"{gid}:{fixture.fixture_id}"
                    match = self.state["matches"].get(key)
                    if match and match.get("closed"):
                        # Older versions marked a manually deleted live channel as closed.
                        if (not match.get("close_reason") and match.get("delete_at") is None
                                and match.get("channel_id") is not None and fixture.is_live
                                and fixture.league_id in cfg.get("leagues", [])):
                            match["closed"] = False
                            self.repository.save(self.state)
                        else:
                            continue
                    if match is None and (fixture.league_id not in cfg.get("leagues", []) or not fixture.is_live):
                        continue
                    try:
                        await self._update(guild, cfg, key, match, fixture, live)
                    except (discord.HTTPException, ValueError):
                        self.errors[guild.id] = "Falha ao criar ou atualizar canal de jogo; nova tentativa no proximo ciclo."
                        log.exception("Falha no canal da partida %s", key)

    async def _update(self, guild, cfg, key, match, fixture: BrasileiraoFixture, live) -> None:
        role = guild.get_role(cfg["role_id"])
        if role is None:
            if match is not None:
                # Losing the audience role must not prevent eventual cleanup of an existing channel.
                self._observe(match, cfg, fixture)
            raise ValueError("Cargo Futebol removido; reconfigure o cargo antes de criar canais.")
        overwrites = private_overwrites(guild, role)
        if match is None or match["channel_id"] is None:
            if match is None:
                # Persist the intent BEFORE the Discord request, including when that request times out.
                match = {"guild_id": guild.id, "fixture_id": fixture.fixture_id, "league_id": fixture.league_id,
                         "channel_id": None, "role_id": role.id, "snapshot": None,
                         "delete_at": None, "finished_at": None, "closed": False}
                self.state["matches"][key] = match
                self.repository.save(self.state)
            # Recover a successful create followed by a process crash before state was saved.
            channels = await guild.fetch_channels()
            channel = next((c for c in channels if isinstance(c, discord.TextChannel) and c.topic == self.marker(key)), None)
            if channel is None:
                if not fixture.is_live or fixture.league_id not in cfg.get("leagues", []):
                    match["closed"] = True
                    match["close_reason"] = "inactive"
                    self.repository.save(self.state)
                    return
                category = guild.get_channel(cfg["category_id"]) if cfg.get("category_id") else None
                if cfg.get("category_id") and not isinstance(category, discord.CategoryChannel):
                    raise ValueError("Categoria configurada nao encontrada; reative a liga em uma categoria valida.")
                channel = await guild.create_text_channel(
                    channel_name(fixture.home_team, fixture.away_team), category=category,
                    topic=self.marker(key), overwrites=overwrites, reason="Inicio de partida de liga ativada",
                )
            else:
                await channel.edit(overwrites=overwrites, reason="Retomada de canal privado de futebol")
            match["channel_id"], match["role_id"] = channel.id, role.id
            self.repository.save(self.state)
        else:
            channel = await self._channel(guild, match, key, refresh=True)
            if channel is None:
                # A confirmed 404 starts a durable replacement intent. Never reset on 403/timeouts.
                match["channel_id"] = None
                match["snapshot"] = None
                self.repository.save(self.state)
                return await self._update(guild, cfg, key, match, fixture, live)
            if match.get("role_id") != role.id:
                await channel.edit(overwrites=overwrites, reason="Cargo de acesso aos jogos atualizado")
                match["role_id"] = role.id
        self._observe(match, cfg, fixture)
        if match["snapshot"] == fixture.snapshot_key:
            return
        scorers = []
        if (fixture.home_goals or 0) + (fixture.away_goals or 0) > 0:
            if fixture.fixture_id not in self._scorers:
                try:
                    self._scorers[fixture.fixture_id] = await self.client.fetch_goal_scorers(fixture.fixture_id)
                except Exception:
                    self._scorers[fixture.fixture_id] = []
                    log.exception("Artilharia indisponivel para partida %s", fixture.fixture_id)
            scorers = self._scorers[fixture.fixture_id]
        reason = describe_fixture_update(fixture, match["snapshot"])
        if fixture.is_finished and (match["snapshot"] or "").split("|")[-1] != "finished":
            reason = "Fim de jogo"
        embed = self.embed_factory(fixture, scorers, reason, live)
        if match["delete_at"] is not None:
            embed.add_field(name="Canal temporario", value=f"Exclusao prevista: <t:{int(match['delete_at'])}:R>.", inline=False)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        # A failed delivery is retried independently for each guild.
        match["snapshot"] = fixture.snapshot_key
        self.repository.save(self.state)

    def _observe(self, match: dict, cfg: dict, fixture: BrasileiraoFixture) -> None:
        if fixture.status_short in TERMINAL_STATUSES and match.get("finished_at") is None:
            match["finished_at"] = self.clock()
            match["delete_at"] = match["finished_at"] + cfg["retention_minutes"] * 60
        elif fixture.is_live:
            match["finished_at"] = match["delete_at"] = None
        match["fixture"] = serialize_fixtures([fixture])[0]
        self.repository.save(self.state)
