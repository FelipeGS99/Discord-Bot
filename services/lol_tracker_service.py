from __future__ import annotations

import asyncio
import hashlib
import logging
import time

import discord

from services.lol_presentation import (
    live_embeds,
    build_embeds,
    report_embeds,
    fallback_catalog,
)
from services.riot_service import RiotError, recent_stats

log = logging.getLogger(__name__)


class LoLMonitor:
    def __init__(self, bot, repository, riot, ddragon):
        self.bot, self.repository, self.riot, self.ddragon = (
            bot,
            repository,
            riot,
            ddragon,
        )
        self.lock = asyncio.Lock()
        self.last_check = None
        self.last_error = None
        self.catalog = fallback_catalog()

    async def _context(self, game, watched):
        context = {}
        tracked = {p["puuid"]: p for p in watched}
        platform = watched[0]["platform"]
        for participant in game.get("participants", []):
            puuid = participant.get("puuid")
            visible = participant.get("riotId") or (
                participant.get("riotIdGameName") and participant.get("riotIdTagline")
            )
            if not puuid or (not visible and puuid not in tracked):
                continue
            row = {}
            if visible:
                try:
                    row["rank"] = await self.riot.rank(puuid, platform)
                except RiotError:
                    row["rank"] = "indisponivel"
            if visible or puuid in tracked:
                try:
                    previous = await self.riot.history(puuid, platform)
                    current_id = f"{platform}_{game['gameId']}"
                    row["recent"] = recent_stats(
                        [
                            m
                            for m in previous
                            if m.get("metadata", {}).get("matchId") != current_id
                        ],
                        puuid,
                    )
                except RiotError:
                    row["recent"] = None
                try:
                    row["mastery"] = await self.riot.mastery(
                        puuid, participant["championId"], platform
                    )
                except RiotError:
                    row["mastery"] = None
            context[puuid] = row
        return context

    @staticmethod
    def marker(gid, mid, kind, subject):
        key = f"{gid}:{mid}:{kind}:{subject}".encode()
        return "Tigrao LoL • evento " + hashlib.sha256(key).hexdigest()[:24]

    async def deliver(self, gid, mid, kind, subject, embeds):
        channels = await self.repository.channels()
        channel_id = channels.get(gid)
        if not channel_id:
            return False
        if (
            await self.repository.delivery(gid, mid, kind, subject, channel_id)
            is not None
        ):
            return True
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                self.last_error = "Canal configurado indisponivel; entrega pendente."
                return False
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != gid:
            self.last_error = "Destino invalido; nenhuma mensagem enviada."
            return False
        marker = self.marker(gid, mid, kind, subject)
        # Recover the small send/commit crash window before issuing a new Discord send.
        try:
            async for message in channel.history(limit=100):
                if message.author.id == self.bot.user.id and any(
                    e.footer.text == marker for e in message.embeds
                ):
                    await self.repository.acknowledge(
                        gid, mid, kind, subject, message.id
                    )
                    return True
            if (await self.repository.channels()).get(gid) != channel_id:
                return False
            outgoing = [e.copy() for e in embeds]
            if not outgoing:
                return False
            outgoing[0].set_footer(text=marker)
            message = await channel.send(
                embeds=outgoing,
                allowed_mentions=discord.AllowedMentions.none(),
                nonce=hashlib.sha256(marker.encode()).hexdigest()[:24],
            )
            await self.repository.acknowledge(gid, mid, kind, subject, message.id)
            return True
        except discord.HTTPException:
            self.last_error = "Discord recusou a entrega ou a leitura do historico; notificacao pendente."
            log.warning("Falha de entrega LoL no servidor %s", gid)
            return False

    async def poll(self):
        async with self.lock:
            self.last_check = time.time()
            self.last_error = None
            channels = await self.repository.channels()
            players = [
                p for p in await self.repository.players() if p["guild_id"] in channels
            ]
            if not players:
                return
            if not self.riot.key:
                self.last_error = "RIOT_API_KEY nao configurada."
                return
            observed = {}
            groups = {}
            for player in players:
                key = (player["platform"], player["puuid"])
                try:
                    if key not in observed:
                        observed[key] = await self.riot.spectator(
                            player["puuid"], player["platform"]
                        )
                    game = observed[key]
                    mid = f"{player['platform']}_{game['gameId']}" if game else None
                    await self.repository.player_state(
                        player["guild_id"],
                        player["puuid"],
                        "em partida" if game else "fora de partida",
                        mid,
                    )
                    if mid:
                        group = groups.setdefault(
                            (player["guild_id"], mid),
                            {
                                "game": game,
                                "players": [],
                                "platform": player["platform"],
                            },
                        )
                        group["players"].append(player)
                except RiotError as exc:
                    self.last_error = str(exc)
                    await self.repository.player_state(
                        player["guild_id"],
                        player["puuid"],
                        "consulta indisponivel",
                        player["current_match"],
                    )
                    if exc.status == 429:
                        break
            for (gid, mid), group in groups.items():
                await self.repository.save_match(
                    gid,
                    mid,
                    group["platform"],
                    channels[gid],
                    group["game"],
                    group["players"],
                )
            catalog_ready = True
            try:
                self.catalog = await self.ddragon.catalog()
            except RiotError:
                catalog_ready = False
                self.last_error = (
                    self.last_error
                    or "Data Dragon indisponivel; builds aguardando catalogo atual."
                )
            for match in await self.repository.matches():
                try:
                    await self._process_match(match, players, observed, catalog_ready)
                except (RiotError, discord.HTTPException) as exc:
                    self.last_error = (
                        str(exc)
                        if isinstance(exc, RiotError)
                        else "Falha temporaria no Discord."
                    )
                    log.warning(
                        "Partida LoL %s: processamento adiado", match["match_id"]
                    )

    async def _process_match(self, match, players, observed, catalog_ready=True):
        gid, mid = match["guild_id"], match["match_id"]
        active = {p["puuid"] for p in players if p["guild_id"] == gid}
        watched = sorted(
            [p for p in match["watched"] if p["puuid"] in active],
            key=lambda p: p["puuid"],
        )
        if not watched:
            await self.repository.phase(gid, mid, "complete")
            return
        game = match["payload"]
        context = match["context"] or {}
        if not context:
            # Notify immediately; optional historical enrichment can span several rate-limit windows.
            if not await self.deliver(
                gid, mid, "live", "game", live_embeds(game, watched, {}, self.catalog)
            ):
                return
            context = await self._context(game, watched)
            await self.repository.context(gid, mid, context)
        if context.get("_rendered_patch") != self.catalog.get(
            "version"
        ) or not context.get("_rendered"):
            if await self.refresh_live(
                gid, mid, live_embeds(game, watched, context, self.catalog)
            ):
                context["_rendered_patch"] = self.catalog.get("version")
                context["_rendered"] = True
                await self.repository.context(gid, mid, context)
        if await self.deliver(
            gid, mid, "live", "game", live_embeds(game, watched, context, self.catalog)
        ):
            for player in watched:
                await self.repository.mark_notified(gid, player["puuid"], mid)
            for player in watched:
                if self.catalog.get("version") and catalog_ready:
                    await self.deliver(
                        gid,
                        mid,
                        "build",
                        player["puuid"],
                        build_embeds(game, player, self.catalog),
                    )
        else:
            return
        states = [observed.get((p["platform"], p["puuid"]), "unknown") for p in watched]
        if any(s == "unknown" for s in states):
            return
        if any(s and f"{match['platform']}_{s['gameId']}" == mid for s in states):
            return
        await self.repository.phase(gid, mid, "waiting", match.get("result"))
        result = match.get("result") or await self.riot.match(mid, match["platform"])
        if result is None:
            self.last_error = (
                "Partida encerrada; aguardando publicacao do resultado na Match-V5."
            )
            return
        await self.repository.phase(gid, mid, "waiting", result)
        reports = report_embeds(result, watched, context, self.catalog)
        expected = {p["puuid"] for p in watched}
        available = {
            p.get("puuid") for p in result.get("info", {}).get("participants", [])
        }
        if not expected <= available:
            self.last_error = (
                "Resultado ainda incompleto; relatorio aguardando participantes."
            )
            return
        delivered = True
        for index in range(0, len(reports), 4):
            delivered = (
                await self.deliver(
                    gid, mid, "report", str(index // 4), reports[index : index + 4]
                )
                and delivered
            )
        if delivered:
            await self.repository.phase(gid, mid, "complete", result)

    async def refresh_live(self, gid, mid, embeds):
        channel_id = (await self.repository.channels()).get(gid)
        if not channel_id:
            return
        message_id = await self.repository.delivery(
            gid, mid, "live", "game", channel_id
        )
        channel = self.bot.get_channel(channel_id)
        if (
            not message_id
            or not isinstance(channel, discord.TextChannel)
            or channel.guild.id != gid
        ):
            return
        try:
            message = await channel.fetch_message(message_id)
            if message.author.id != self.bot.user.id:
                return
            embeds[0].set_footer(text=self.marker(gid, mid, "live", "game"))
            await message.edit(
                embeds=embeds, allowed_mentions=discord.AllowedMentions.none()
            )
            return True
        except discord.HTTPException:
            self.last_error = (
                "Live Match enviado; enriquecimento historico nao pode ser atualizado."
            )
        return False
