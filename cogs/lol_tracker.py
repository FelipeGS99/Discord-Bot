from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks

from services.lol_tracker_repository import LoLRepository
from services.lol_tracker_service import LoLMonitor
from services.lol_presentation import (
    live_embeds,
    build_embeds,
    report_embeds,
    demo_data,
    text,
)
from services.riot_service import RiotClient, DataDragon, RiotError
from services.lol_channel_service import LoLChannelError

BASE_PATH = Path(__file__).resolve().parents[1]
log = logging.getLogger(__name__)


class LoLTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.repository = LoLRepository(BASE_PATH / "pro_lives.sqlite3")
        self.riot = RiotClient(os.getenv("RIOT_API_KEY"))
        self.ddragon = DataDragon()
        self.monitor = LoLMonitor(bot, self.repository, self.riot, self.ddragon)
        self.monitoring.start()

    async def cog_unload(self):
        self.monitoring.cancel()
        task = self.monitoring.get_task()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await self.riot.close()
        await self.ddragon.close()

    @staticmethod
    def can_manage(ctx):
        return ctx.guild is not None and (
            ctx.author.id == ctx.guild.owner_id
            or ctx.author.guild_permissions.administrator
            or ctx.author.guild_permissions.manage_guild
        )

    async def require_admin(self, ctx):
        if self.can_manage(ctx):
            return True
        await ctx.send(
            "Use este comando em um servidor com permissao de gerenciar o servidor."
        )
        return False

    @commands.group(name="loltrack", invoke_without_command=True)
    async def tracker(self, ctx: commands.Context):
        prefix = ctx.prefix or "?"
        await ctx.send(
            f"**Tigrao • LoL Live Tracker**\n"
            f"`{prefix}loltrack categoria [categoria]` — categoria dos canais privados (opcional).\n"
            f"`{prefix}loltrack seguir Nome#TAG` — cria canal privado quando o jogador entrar em partida (BR1).\n"
            f"`{prefix}loltrack deixar Nome#TAG` — interrompe o acompanhamento.\n"
            f"`{prefix}loltrack lista` / `{prefix}loltrack status` — jogadores e saude.\n"
            f"`{prefix}loltrack teste` — cria canal privado de demonstracao para o cargo LOL.\n"
            "Canais por jogador sao reutilizados e excluidos 1 hora apos o ultimo jogo confirmado, sem nova partida.\n"
            "Configuracao, cadastro, remocao e teste exigem Gerenciar servidor. Campeonatos profissionais continuam em `lol`."
        )

    @tracker.command(name="canal")
    async def channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if not await self.require_admin(ctx):
            return
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Escolha um canal deste servidor.")
            return
        async with self.monitor.lock:
            try:
                await self.monitor.sessions.configure(ctx.guild, channel.category)
            except LoLChannelError as exc:
                await ctx.send(str(exc))
                return
        await ctx.send(
            "A categoria desse canal sera usada como referencia. Os alertas agora vao para canais privados por jogador, acessiveis ao cargo LOL."
        )

    @tracker.command(name="categoria")
    async def category(
        self, ctx: commands.Context, category: discord.CategoryChannel | None = None
    ):
        if not await self.require_admin(ctx):
            return
        async with self.monitor.lock:
            try:
                role = await self.monitor.sessions.configure(ctx.guild, category)
                if category is None:
                    await self.repository.configure_sessions(
                        ctx.guild.id, role.id, None
                    )
            except LoLChannelError as exc:
                await ctx.send(str(exc))
                return
        await ctx.send(
            "Categoria dos proximos canais LOL atualizada. Sem categoria, os canais ficam na raiz do servidor."
        )

    @tracker.command(name="seguir")
    async def follow(self, ctx: commands.Context, *, riot_id: str):
        if not await self.require_admin(ctx):
            return
        platform = "BR1"
        try:
            async with self.monitor.lock:
                configs = await self.repository.session_configs()
                category = (
                    getattr(ctx.channel, "category", None)
                    if ctx.guild.id not in configs
                    else None
                )
                await self.monitor.sessions.configure(ctx.guild, category)
            account = await self.riot.account(riot_id, platform)
            canonical = f"{account.get('gameName', riot_id.rpartition('#')[0])}#{account.get('tagLine', riot_id.rpartition('#')[2])}"
            async with self.monitor.lock:
                added = await self.repository.follow(
                    ctx.guild.id, account["puuid"], canonical, platform
                )
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        except RiotError as exc:
            await ctx.send(
                "Conta nao encontrada na Riot." if exc.status == 404 else str(exc)
            )
            return
        await ctx.send(
            f"{text(canonical)}: {'monitoramento ativado' if added else 'ja estava sendo acompanhado'}. "
            "O bot criara um canal privado com o nick do jogador para o cargo LOL. Partidas seguidas reutilizam o canal; exclusao apos 1 hora sem novo jogo.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tracker.command(name="deixar")
    async def unfollow(self, ctx: commands.Context, *, riot_id: str):
        if not await self.require_admin(ctx):
            return
        async with self.monitor.lock:
            removed = await self.repository.unfollow(ctx.guild.id, riot_id.strip())
        await ctx.send(
            "Monitoramento interrompido para essa conta."
            if removed
            else "Essa conta nao esta ativa neste servidor."
        )

    @tracker.command(name="lista")
    async def players(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Use este comando em um servidor.")
            return
        rows = await self.repository.players(ctx.guild.id, active=False)
        if not rows:
            await ctx.send("Nenhum jogador cadastrado. Use `loltrack seguir Nome#TAG`.")
            return
        lines = [
            f"{text(p['riot_id'])} · {p['platform']} · {'ativo' if p['active'] else 'inativo'} · {p['status']}"
            for p in rows
        ]
        for index in range(0, len(lines), 12):
            await ctx.send(
                "\n".join(lines[index : index + 12])[:1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @tracker.command(name="status")
    async def status(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Use este comando em um servidor.")
            return
        rows = await self.repository.players(ctx.guild.id)
        cfg = (await self.repository.session_configs()).get(ctx.guild.id, {})
        sessions = [
            s for s in await self.repository.sessions() if s["guild_id"] == ctx.guild.id
        ]
        role_text = f"<@&{cfg['role_id']}>" if cfg else "nao configurado"
        last = (
            f"<t:{int(self.monitor.last_check)}:R>"
            if self.monitor.last_check
            else "ainda nao realizada"
        )
        operational = self.monitoring.is_running() and bool(self.riot.key) and bool(cfg)
        await ctx.send(
            f"**LoL Tracker**\nMonitoramento: {'em execucao' if operational else 'aguardando configuracao ou tarefa parada'}\n"
            f"Jogadores ativos: {len(rows)}\nCanais privados abertos: {len(sessions)}\nCargo: {role_text}\n"
            f"Riot: {self.riot.health}\nUltima verificacao: {last}\n"
            f"Intervalo: aproximadamente 60s; respeita espera Riot e volume de jogadores.\n"
            f"Ultima ocorrencia: {self.monitor.last_error or 'nenhuma'}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tracker.command(name="teste")
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def demo(self, ctx: commands.Context):
        if not await self.require_admin(ctx):
            return
        async with self.monitor.lock:
            try:
                await self.monitor.sessions.configure(
                    ctx.guild, getattr(ctx.channel, "category", None)
                )
            except LoLChannelError as exc:
                await ctx.send(str(exc))
                return
            try:
                catalog = await self.ddragon.catalog()
            except RiotError:
                await ctx.send(
                    "Data Dragon indisponivel; o teste visual com itens e imagens deve ser repetido quando a conexao voltar."
                )
                return
            game, watched, context, result = demo_data(catalog)
            batches = [
                live_embeds(game, watched, context, catalog, True),
                build_embeds(game, watched[0], catalog, True),
                report_embeds(result, watched, context, catalog, True),
            ]
            demo = {
                "guild_id": ctx.guild.id,
                "puuid": f"demo:{ctx.guild.id}",
                "riot_id": "TESTE Mochila#bunny",
                "platform": "BR1",
            }
            mid = f"DEMO_{time.time_ns()}"
            try:
                channel_id = await self.monitor.sessions.ensure(demo, mid)
                channel = self.bot.get_channel(channel_id) if channel_id else None
                if channel is None and channel_id:
                    channel = await self.bot.fetch_channel(channel_id)
                if (
                    not isinstance(channel, discord.TextChannel)
                    or channel.guild.id != ctx.guild.id
                ):
                    await ctx.send(
                        "Nao foi possivel recuperar o canal privado de demonstracao."
                    )
                    return
                sent = []
                for embeds in batches:
                    message = await channel.send(
                        embeds=embeds, allowed_mentions=discord.AllowedMentions.none()
                    )
                    sent.append(message.jump_url)
            except LoLChannelError as exc:
                await ctx.send(str(exc))
                return
            finally:
                await self.monitor.sessions.finished(ctx.guild.id, demo["puuid"], mid)
        await ctx.send("Tres mensagens **MODO TESTE** enviadas:\n" + "\n".join(sent))

    @category.error
    @channel.error
    @follow.error
    @unfollow.error
    @demo.error
    async def tracker_error(self, ctx, error):
        if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            await ctx.send(
                "Confira os argumentos. Use `loltrack` para ver os exemplos."
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"Aguarde {error.retry_after:.0f}s antes de repetir o teste."
            )
        elif isinstance(error, commands.CommandInvokeError) and isinstance(
            error.original, LoLChannelError
        ):
            await ctx.send(str(error.original))
        elif isinstance(error, commands.CommandInvokeError) and isinstance(
            error.original, discord.HTTPException
        ):
            await ctx.send(
                "Discord recusou a operacao. Confira as permissoes do canal configurado."
            )
        else:
            raise error

    @tasks.loop(seconds=60)
    async def monitoring(self):
        try:
            await self.monitor.poll()
        except Exception:
            self.monitor.last_error = "Falha interna; nova tentativa no proximo ciclo."
            log.exception("Falha no monitor LoL")

    @monitoring.before_loop
    async def before_monitoring(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(LoLTracker(bot))
