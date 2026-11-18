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

from services.discord_messages import response_sender

reply = response_sender("LoL • Acompanhamento")

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
        await reply(
            ctx,
            "Use este comando em um servidor com permissão de gerenciar o servidor.",
            tone="warning",
        )
        return False

    @commands.group(name="loltrack", invoke_without_command=True)
    async def tracker(self, ctx: commands.Context):
        prefix = ctx.prefix or "?"
        await reply(
            ctx,
            f"**Tigrão • LoL Live Tracker**\n"
            f"`{prefix}loltrack categoria [categoria]` — categoria dos canais privados (opcional).\n"
            f"`{prefix}loltrack seguir Nome#TAG` — cria canal privado quando o jogador entrar em partida (BR1).\n"
            f"`{prefix}loltrack deixar Nome#TAG` — interrompe o acompanhamento.\n"
            f"`{prefix}loltrack lista` / `{prefix}loltrack status` — jogadores e saúde.\n"
            f"`{prefix}loltrack teste` — cria canal privado de demonstração para o cargo LOL.\n"
            "Canais por jogador são reutilizados e excluídos 1 hora após o último jogo confirmado, sem nova partida.\n"
            "Configuração, cadastro, remoção e teste exigem Gerenciar servidor. Campeonatos profissionais continuam em `lol`.",
        )

    @tracker.command(name="canal")
    async def channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if not await self.require_admin(ctx):
            return
        if channel.guild.id != ctx.guild.id:
            await reply(ctx, "Escolha um canal deste servidor.", tone="warning")
            return
        async with self.monitor.lock:
            try:
                await self.monitor.sessions.configure(ctx.guild, channel.category)
            except LoLChannelError as exc:
                await reply(ctx, str(exc), tone="warning")
                return
        await reply(
            ctx,
            "A categoria desse canal será usada como referência. Os alertas agora vão para canais privados por jogador, acessíveis ao cargo LOL.",
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
                await reply(ctx, str(exc), tone="warning")
                return
        await reply(
            ctx,
            "Categoria dos próximos canais LOL atualizada. Sem categoria, os canais ficam na raiz do servidor.",
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
            await reply(ctx, str(exc), tone="warning")
            return
        except RiotError as exc:
            await reply(
                ctx,
                "Conta não encontrada na Riot. Confira o Riot ID no formato `Nome#TAG`."
                if exc.status == 404
                else "O limite de consultas da Riot foi atingido. Aguarde alguns instantes e tente novamente."
                if exc.status == 429
                else "A Riot recusou a autenticação. Solicite a revisão da integração a um administrador do bot."
                if exc.status in (401, 403)
                else "Não foi possível validar a conta na Riot. Tente novamente em alguns instantes.",
                title="Não foi possível iniciar o acompanhamento",
                tone="error",
            )
            return
        await reply(
            ctx,
            f"**{text(canonical)}** {'será acompanhado automaticamente.' if added else 'já está sendo acompanhado neste servidor.'}",
            title="Acompanhamento ativado" if added else "Acompanhamento já ativo",
            tone="success" if added else "info",
            fields=(
                (
                    "Canal da partida",
                    "Criado automaticamente com o nome do jogador quando uma partida for detectada.",
                ),
                (
                    "Acesso",
                    "Privado para o cargo **LOL** e administradores do servidor.",
                ),
                (
                    "Duração",
                    "Partidas consecutivas usam o mesmo canal. A exclusão ocorre **1 hora após o fim da última partida**, caso não haja outra em andamento.",
                ),
            ),
        )

    @tracker.command(name="deixar")
    async def unfollow(self, ctx: commands.Context, *, riot_id: str):
        if not await self.require_admin(ctx):
            return
        async with self.monitor.lock:
            removed = await self.repository.unfollow(ctx.guild.id, riot_id.strip())
        await reply(
            ctx,
            "Monitoramento interrompido para essa conta."
            if removed
            else "Essa conta não está ativa neste servidor.",
        )

    @tracker.command(name="lista")
    async def players(self, ctx: commands.Context):
        if ctx.guild is None:
            await reply(ctx, "Use este comando em um servidor.", tone="warning")
            return
        rows = await self.repository.players(ctx.guild.id, active=False)
        if not rows:
            await reply(
                ctx,
                "Nenhum jogador cadastrado. Use `loltrack seguir Nome#TAG`.",
                tone="warning",
            )
            return
        lines = [
            f"{text(p['riot_id'])} · {p['platform']} · {'ativo' if p['active'] else 'inativo'} · {p['status']}"
            for p in rows
        ]
        for index in range(0, len(lines), 12):
            await reply(
                ctx,
                "\n".join(lines[index : index + 12])[:1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @tracker.command(name="status")
    async def status(self, ctx: commands.Context):
        if ctx.guild is None:
            await reply(ctx, "Use este comando em um servidor.", tone="warning")
            return
        rows = await self.repository.players(ctx.guild.id)
        cfg = (await self.repository.session_configs()).get(ctx.guild.id, {})
        sessions = [
            s for s in await self.repository.sessions() if s["guild_id"] == ctx.guild.id
        ]
        role_text = f"<@&{cfg['role_id']}>" if cfg else "não configurado"
        last = (
            f"<t:{int(self.monitor.last_check)}:R>"
            if self.monitor.last_check
            else "ainda não realizada"
        )
        operational = self.monitoring.is_running() and bool(self.riot.key) and bool(cfg)
        await reply(
            ctx,
            f"**LoL Tracker**\nMonitoramento: {'em execução' if operational else 'aguardando configuração ou tarefa parada'}\n"
            f"Jogadores ativos: {len(rows)}\nCanais privados abertos: {len(sessions)}\nCargo: {role_text}\n"
            f"Riot: {self.riot.health}\nUltima verificacao: {last}\n"
            f"Intervalo: aproximadamente 60s; respeita espera Riot e volume de jogadores.\n"
            f"Última ocorrencia: {self.monitor.last_error or 'nenhuma'}",
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
                await reply(ctx, str(exc), tone="warning")
                return
            try:
                catalog = await self.ddragon.catalog()
            except RiotError:
                await reply(
                    ctx,
                    "Data Dragon indisponível; o teste visual com itens e imagens deve ser repetido quando a conexao voltar.",
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
                channel_id = await self.monitor.sessions.ensure(demo, mid, demo=True)
                channel = self.bot.get_channel(channel_id) if channel_id else None
                if channel is None and channel_id:
                    channel = await self.bot.fetch_channel(channel_id)
                if (
                    not isinstance(channel, discord.TextChannel)
                    or channel.guild.id != ctx.guild.id
                ):
                    await reply(
                        ctx,
                        "Não foi possível recuperar o canal privado de demonstração.",
                        tone="error",
                    )
                    return
                sent = []
                for embeds in batches:
                    message = await channel.send(
                        embeds=embeds, allowed_mentions=discord.AllowedMentions.none()
                    )
                    sent.append(message.jump_url)
            except LoLChannelError as exc:
                await reply(ctx, str(exc), tone="warning")
                return
            finally:
                await self.monitor.sessions.finished(ctx.guild.id, demo["puuid"], mid)
        await reply(
            ctx,
            "Três exemplos foram enviados ao canal privado de demonstração.\n\n"
            + "\n".join(sent),
            title="Demonstração concluída",
            tone="success",
        )

    @category.error
    @channel.error
    @follow.error
    @unfollow.error
    @demo.error
    async def tracker_error(self, ctx, error):
        if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            await reply(
                ctx, "Confira os argumentos. Use `loltrack` para ver os exemplos."
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await reply(
                ctx,
                f"Aguarde {error.retry_after:.0f}s antes de repetir o teste.",
                tone="warning",
            )
        elif isinstance(error, commands.CommandInvokeError) and isinstance(
            error.original, LoLChannelError
        ):
            await reply(ctx, str(error.original), tone="warning")
        elif isinstance(error, commands.CommandInvokeError) and isinstance(
            error.original, discord.HTTPException
        ):
            await reply(
                ctx,
                "Discord recusou a operação. Confira as permissões do canal configurado.",
                tone="error",
            )
        else:
            raise error

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.monitor.recover_channels()
        except Exception:
            self.monitor.last_error = (
                "Falha na recuperacao dos canais; nova tentativa no próximo ciclo."
            )
            log.exception("Falha ao recuperar canais LoL")

    @commands.Cog.listener()
    async def on_resumed(self):
        await self.on_ready()

    @tasks.loop(seconds=60)
    async def monitoring(self):
        try:
            await self.monitor.poll()
        except Exception:
            self.monitor.last_error = "Falha interna; nova tentativa no próximo ciclo."
            log.exception("Falha no monitor LoL")

    @monitoring.before_loop
    async def before_monitoring(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(LoLTracker(bot))
