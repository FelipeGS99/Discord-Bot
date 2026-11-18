"""Private per-player channels, persisted across consecutive matches and restarts."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import hashlib
import time
import unicodedata
import re

import discord
from services.riot_service import RiotError


class LoLChannelError(ValueError):
    pass


class LoLChannels:
    def __init__(self, bot, repository, clock=time.time):
        self.bot, self.repository, self.clock = bot, repository, clock
        self._locks = defaultdict(asyncio.Lock)

    @staticmethod
    def overwrites(guild, role):
        if (
            role is None
            or role == guild.default_role
            or role.guild.id != guild.id
            or guild.me is None
        ):
            raise LoLChannelError(
                "Cargo LOL indisponível. Crie o cargo LOL neste servidor e ative novamente."
            )
        return {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

    async def configure(self, guild, category=None):
        cfg = (await self.repository.session_configs()).get(guild.id, {})
        role = guild.get_role(cfg["role_id"]) if cfg else None
        if role is None:
            candidates = [r for r in guild.roles if r.name.casefold() == "lol"]
            if len(candidates) != 1:
                raise LoLChannelError("Crie um unico cargo chamado LOL neste servidor.")
            role = candidates[0]
        self.overwrites(guild, role)
        if category is not None and (
            not isinstance(category, discord.CategoryChannel)
            or category.guild.id != guild.id
        ):
            raise LoLChannelError("Escolha uma categoria deste servidor.")
        category_id = category.id if category is not None else cfg.get("category_id")
        await self.repository.configure_sessions(guild.id, role.id, category_id)
        return role

    @staticmethod
    def marker(gid, puuid, generation):
        digest = hashlib.sha256(puuid.encode()).hexdigest()[:24]
        return f"loltrack-player:{gid}:{digest}:{generation}"

    @staticmethod
    def name(riot_id):
        value = riot_id.rpartition("#")[0] or riot_id
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode()
            .lower()
        )
        return re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:90] or "jogador-lol"

    async def _owned(self, session, *, refresh=False):
        gid, puuid = session["guild_id"], session["puuid"]
        guild = self.bot.get_guild(gid)
        if guild is None:
            raise LoLChannelError("Servidor não encontrado.")
        marker = self.marker(gid, puuid, session["generation"])
        if session["channel_id"] is None:
            channel = next(
                (
                    c
                    for c in await guild.fetch_channels()
                    if isinstance(c, discord.TextChannel) and c.topic == marker
                ),
                None,
            )
            if channel:
                await self.repository.session_update(gid, puuid, channel_id=channel.id)
            return channel
        channel = guild.get_channel(session["channel_id"])
        if channel is None or refresh:
            try:
                channel = await guild.fetch_channel(session["channel_id"])
            except discord.NotFound:
                return None
        if (
            not isinstance(channel, discord.TextChannel)
            or channel.guild.id != gid
            or channel.topic != marker
        ):
            raise LoLChannelError(
                "Identificador do canal alterado; operação cancelada para proteger canais externos."
            )
        return channel

    async def ensure(self, player, mid, *, demo=False):
        async with self._locks[(player["guild_id"], player["puuid"])]:
            return await self._ensure(player, mid, demo=demo)

    async def _ensure(self, player, mid, *, demo=False):
        gid, puuid = player["guild_id"], player["puuid"]
        cfg = (await self.repository.session_configs()).get(gid)
        guild = self.bot.get_guild(gid)
        if not cfg or guild is None:
            raise LoLChannelError("Ative o tracker com o cargo LOL neste servidor.")
        role = guild.get_role(cfg["role_id"])
        overwrites = self.overwrites(guild, role)
        session = await self.repository.session(gid, puuid)
        if (
            session
            and session["closed"]
            and session["last_match"] == mid
            and session.get("close_reason") != "missing"
        ):
            return None
        deadline = self.clock() + 3600 if demo else None
        if session is None or session["closed"]:
            # Durable creation intent lets us recover after Discord creates a channel but times out.
            session = await self.repository.new_session(
                gid,
                puuid,
                mid,
                self.clock(),
                delete_at=deadline,
                reset_delivery=bool(
                    session and session.get("close_reason") == "missing"
                ),
            )
        elif demo:
            # Persist BEFORE Discord I/O, including when reusing an existing demo channel.
            await self.repository.session_update(gid, puuid, delete_at=deadline)
        channel = await self._owned(session, refresh=True)
        if channel is None and session["channel_id"] is not None:
            session = await self.repository.new_session(
                gid,
                puuid,
                mid,
                self.clock(),
                delete_at=deadline,
                reset_delivery=True,
            )
        if channel is None:
            category = (
                guild.get_channel(cfg["category_id"])
                if cfg.get("category_id")
                else None
            )
            if cfg.get("category_id") and not isinstance(
                category, discord.CategoryChannel
            ):
                raise LoLChannelError(
                    "Categoria removida. Configure outra com loltrack categoria."
                )
            channel = await guild.create_text_channel(
                self.name(player["riot_id"]),
                category=category,
                topic=self.marker(gid, puuid, session["generation"]),
                overwrites=overwrites,
                reason="Jogador acompanhado entrou em partida de LoL",
            )
        elif channel.overwrites != overwrites:
            await channel.edit(
                overwrites=overwrites, reason="Garantir acesso exclusivo ao cargo LOL"
            )
        await self.repository.session_update(
            gid,
            puuid,
            channel_id=channel.id,
            last_match=mid,
            last_live=self.clock(),
            delete_at=deadline,
        )
        return channel.id

    async def channel_for(self, gid, puuid):
        async with self._locks[(gid, puuid)]:
            return await self._channel_for(gid, puuid)

    async def _channel_for(self, gid, puuid):
        session = await self.repository.session(gid, puuid)
        if session is None or session["closed"]:
            return None
        cfg = (await self.repository.session_configs()).get(gid)
        guild = self.bot.get_guild(gid)
        if cfg is None or guild is None:
            raise LoLChannelError("Configuração do servidor indisponível.")
        overwrites = self.overwrites(guild, guild.get_role(cfg["role_id"]))
        channel = await self._owned(session)
        if channel is None:
            if session["channel_id"] is not None:
                await self.repository.session_update(
                    gid, puuid, closed=1, close_reason="missing"
                )
            return None
        if channel.overwrites != overwrites:
            await channel.edit(
                overwrites=overwrites, reason="Garantir privacidade do canal LOL"
            )
        return channel.id

    async def finished(self, gid, puuid, mid, *, ended_at=None):
        async with self._locks[(gid, puuid)]:
            await self._finished(gid, puuid, mid, ended_at=ended_at)

    async def _finished(self, gid, puuid, mid, *, ended_at=None):
        session = await self.repository.session(gid, puuid)
        if (
            session
            and not session["closed"]
            and session["last_match"] == mid
            and session["delete_at"] is None
        ):
            end = self.clock()
            if isinstance(ended_at, (int, float)) and 0 < ended_at <= end:
                end = ended_at
            await self.repository.session_update(gid, puuid, delete_at=end + 3600)

    async def cleanup(self, observed, active, pending, verify=None, *, recover=False):
        """Check fresh Spectator state BEFORE expiry; never delete during a queued new game."""
        errors = []
        for session in await self.repository.sessions():
            key = (session["guild_id"], session["puuid"])
            async with self._locks[key]:
                # Another poll/ready event may have renewed or closed this session while waiting.
                session = await self.repository.session(*key)
                if (
                    not session
                    or session["closed"]
                    or session["delete_at"] is None
                    or session["delete_at"] > self.clock()
                    or key in pending
                ):
                    continue
                error = await self._expire(session, observed, active, verify, recover)
                if error:
                    errors.append(error)
        return errors

    async def _expire(self, session, observed, active, verify, recover):
        key = (session["guild_id"], session["puuid"])
        if key in active:
            player = active[key]
            state = observed.get((player["platform"], session["puuid"]), "unknown")
            if state != "unknown" and state is not None:
                return
            if state == "unknown" and (not recover or verify is None):
                return
            # Recheck immediately before deleting, independently of slow match enrichment.
            if verify is not None:
                try:
                    current = await verify(session["puuid"], player["platform"])
                    if current is not None:
                        await self._ensure(
                            player, f"{player['platform']}_{current['gameId']}"
                        )
                        return
                except (RiotError, discord.HTTPException, LoLChannelError):
                    return "Verificacao antes da exclusão falhou; canal LOL preservado."
        try:
            channel = await self._owned(session, refresh=True)
            if channel:
                try:
                    await channel.delete(reason="Uma hora sem nova partida de LoL")
                except discord.NotFound:
                    pass
            await self.repository.session_update(*key, closed=1, close_reason="expired")
        except (discord.HTTPException, LoLChannelError):
            return "Falha ao excluir um canal LOL; nova tentativa no próximo ciclo."
