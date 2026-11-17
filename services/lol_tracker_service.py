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
from services.lol_channel_service import LoLChannels, LoLChannelError

log = logging.getLogger(__name__)


class LoLMonitor:
    def __init__(self, bot, repository, riot, ddragon, sessions=None):
        self.bot, self.repository, self.riot, self.ddragon = (
            bot,
            repository,
            riot,
            ddragon,
        )
        self.sessions = sessions or LoLChannels(bot, repository)
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
        channel_id = await self.sessions.channel_for(gid, subject)
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
            if await self.sessions.channel_for(gid, subject) != channel_id:
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
        except (discord.HTTPException, LoLChannelError):
            self.last_error = "Discord recusou a entrega ou a leitura do historico; notificacao pendente."
            log.warning("Falha de entrega LoL no servidor %s", gid)
            return False

    async def poll(self):
        async with self.lock:
            self.last_check = time.time()
            self.last_error = None
            configs = await self.repository.session_configs()
            players = [
                p for p in await self.repository.players() if p["guild_id"] in configs
            ]
            active = {(p["guild_id"], p["puuid"]): p for p in players}
            if not players:
                await self.sessions.cleanup({}, active, set())
                return
            if not self.riot.key:
                self.last_error = "RIOT_API_KEY nao configurada."
                await self.sessions.cleanup({}, active, set())
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
                for player in group["players"]:
                    try:
                        await self.sessions.ensure(player, mid)
                    except (discord.HTTPException, LoLChannelError):
                        self.last_error = "Nao foi possivel criar ou recuperar um canal privado LOL; nova tentativa no proximo ciclo."
            for (gid, mid), group in groups.items():
                await self.repository.save_match(
                    gid,
                    mid,
                    group["platform"],
                    0,
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
                except (RiotError, discord.HTTPException, LoLChannelError) as exc:
                    self.last_error = (
                        str(exc)
                        if isinstance(exc, RiotError)
                        else "Falha temporaria no Discord."
                    )
                    log.warning(
                        "Partida LoL %s: processamento adiado", match["match_id"]
                    )

            pending = set()
            for match in await self.repository.matches():
                for player in match["watched"]:
                    if not await self.repository.was_delivered(
                        match["guild_id"], match["match_id"], "report", player["puuid"]
                    ):
                        pending.add((match["guild_id"], player["puuid"]))
            errors = await self.sessions.cleanup(
                observed, active, pending, verify=self.riot.spectator
            )
            if errors:
                self.last_error = errors[0]

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
        # Send each player's first message promptly, before slow optional enrichment.
        delivered_live = {}
        for player in watched:
            try:
                delivered_live[player["puuid"]] = await self.deliver(
                    gid,
                    mid,
                    "live",
                    player["puuid"],
                    live_embeds(game, [player], context, self.catalog),
                )
            except (discord.HTTPException, LoLChannelError):
                delivered_live[player["puuid"]] = False
                self.last_error = (
                    "Canal privado LOL indisponivel; notificacao pendente."
                )
        if not any(delivered_live.values()):
            # A channel deliberately removed by an administrator must not be recreated for the same match.
            sessions = [await self.repository.session(gid, p["puuid"]) for p in watched]
            abandoned = []
            for player, session in zip(watched, sessions):
                state = observed.get((player["platform"], player["puuid"]), "unknown")
                no_longer_live = state != "unknown" and (
                    state is None or f"{match['platform']}_{state['gameId']}" != mid
                )
                abandoned.append(
                    bool(session and session["closed"])
                    or (
                        no_longer_live
                        and (session is None or session["channel_id"] is None)
                    )
                )
            if all(abandoned):
                await self.repository.phase(gid, mid, "complete")
            return
        if not context:
            context = await self._context(game, watched)
            await self.repository.context(gid, mid, context)
        result = match.get("result")
        complete = True
        for player in watched:
            puuid = player["puuid"]
            if not delivered_live[puuid]:
                session = await self.repository.session(gid, puuid)
                if not session or not session["closed"]:
                    complete = False
                continue
            rendered = context.setdefault("_player_rendered", {})
            if puuid not in rendered or rendered[puuid] != self.catalog.get("version"):
                if await self.refresh_live(
                    gid, mid, puuid, live_embeds(game, [player], context, self.catalog)
                ):
                    rendered[puuid] = self.catalog.get("version")
                    await self.repository.context(gid, mid, context)
            await self.repository.mark_notified(gid, puuid, mid)
            if self.catalog.get("version") and catalog_ready:
                await self.deliver(
                    gid, mid, "build", puuid, build_embeds(game, player, self.catalog)
                )
            state = observed.get((player["platform"], puuid), "unknown")
            if state == "unknown" or (
                state and f"{match['platform']}_{state['gameId']}" == mid
            ):
                complete = False
                continue
            result = result or await self.riot.match(mid, match["platform"])
            if result is None:
                self.last_error = (
                    "Aguardando publicacao do resultado na Match-V5; canal preservado."
                )
                await self.repository.phase(gid, mid, "waiting")
                complete = False
                continue
            await self.repository.phase(gid, mid, "waiting", result)
            if not any(
                p.get("puuid") == puuid
                for p in result.get("info", {}).get("participants", [])
            ):
                self.last_error = (
                    "Resultado incompleto; encerramento ainda nao confirmado."
                )
                complete = False
                continue
            await self.sessions.finished(gid, puuid, mid)
            reports = report_embeds(result, [player], context, self.catalog)
            session = await self.repository.session(gid, puuid)
            if reports and session and session["delete_at"] is not None:
                reports[0].add_field(
                    name="Canal temporario",
                    value=f"Exclusao <t:{int(session['delete_at'])}:R> se nao houver nova partida.",
                    inline=False,
                )
            if not await self.deliver(gid, mid, "report", puuid, reports):
                complete = False
        if complete:
            await self.repository.phase(gid, mid, "complete", result)

    async def refresh_live(self, gid, mid, puuid, embeds):
        channel_id = await self.sessions.channel_for(gid, puuid)
        if not channel_id:
            return False
        message_id = await self.repository.delivery(gid, mid, "live", puuid, channel_id)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return False
        if (
            not message_id
            or not isinstance(channel, discord.TextChannel)
            or channel.guild.id != gid
        ):
            return False
        try:
            message = await channel.fetch_message(message_id)
            if message.author.id != self.bot.user.id:
                return False
            embeds[0].set_footer(text=self.marker(gid, mid, "live", puuid))
            await message.edit(
                embeds=embeds, allowed_mentions=discord.AllowedMentions.none()
            )
            return True
        except discord.HTTPException:
            self.last_error = (
                "Live enviado; enriquecimento historico aguardando atualizacao."
            )
            return False
