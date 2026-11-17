from __future__ import annotations

import asyncio
import logging
from collections import Counter
from pathlib import Path

import discord
from discord.ext import commands, tasks

from services.pro_live_service import Account, Delivery, LiveMonitor, LiveRepository


log = logging.getLogger(__name__)
POLL_INTERVAL_MINUTES = 4
BASE_PATH = Path(__file__).resolve().parent.parent


def live_embed(account: Account, delivery: Delivery) -> discord.Embed:
    embed = discord.Embed(
        title=f"{account.name} iniciou uma live!"[:256],
        url=account.url,
        description=discord.utils.escape_markdown(delivery.title)[:1000] or "Transmissao ao vivo",
        color=0x9146FF,
    )
    embed.add_field(name="Jogador", value=discord.utils.escape_markdown(account.name), inline=True)
    embed.add_field(name="Equipe / Liga", value=discord.utils.escape_markdown(f"{account.team} / {account.league}"), inline=True)
    embed.add_field(name="Posicao", value=account.role, inline=True)
    embed.add_field(name="Plataforma", value=account.platform.upper(), inline=True)
    embed.add_field(name="Assistir", value=f"[Abrir live]({account.url})", inline=False)
    return embed


class ProLives(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.repository = LiveRepository(BASE_PATH / "pro_lives.sqlite3")
        self.monitor = LiveMonitor(BASE_PATH / "pro_lives_roster.json", self.repository)
        self.delivery_slots = asyncio.Semaphore(3)
        self.delivery_errors: dict[int, str] = {}
        self.check_pro_lives.start()

    async def cog_unload(self) -> None:
        self.check_pro_lives.cancel()
        task = self.check_pro_lives.get_task()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await self.monitor.client.close()

    @commands.group(name="prolives", invoke_without_command=True)
    @commands.guild_only()
    async def pro_lives(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "**Lives profissionais de LoL — Asia e Twitch de todas as regioes**\n"
            f"`{prefix}prolives canal #canal` — Ativar alertas neste servidor.\n"
            f"`{prefix}prolives parar` — Desativar alertas.\n"
            f"`{prefix}prolives status` — Cobertura, ultima consulta e falhas.\n"
            f"`{prefix}prolives jogadores` — Contas confirmadas monitoradas.\n"
            f"`{prefix}prolives recarregar` — Reler o catalogo verificado.\n"
            "Consultas a cada 4 minutos. A primeira observacao serve de referencia, sem alertar lives ja abertas."
        )

    @pro_lives.command(name="canal")
    @commands.has_guild_permissions(manage_channels=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Escolha um canal deste servidor.")
            return
        permissions = channel.permissions_for(ctx.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            await ctx.send("Preciso de permissoes para ver o canal, enviar mensagens e inserir links/embeds.")
            return
        await self.repository.subscribe(ctx.guild.id, channel.id)
        await self.monitor.reload()
        await ctx.send(f"Alertas configurados em {channel.mention}. " + self._coverage())

    @pro_lives.command(name="parar")
    @commands.has_guild_permissions(manage_channels=True)
    async def stop(self, ctx: commands.Context) -> None:
        await self.repository.subscribe(ctx.guild.id, None)
        self.delivery_errors.pop(ctx.guild.id, None)
        await ctx.send("Alertas de lives profissionais desativados neste servidor.")

    def _coverage(self) -> str:
        if self.monitor.catalog_error:
            return self.monitor.catalog_error
        catalog = self.monitor.catalog
        if not catalog.accounts and not catalog.pending_accounts:
            return "Nenhuma conta verificada elegivel. O monitoramento aguarda o catalogo com fontes e datas atuais."
        linked = len({a.player_id for a in catalog.accounts})
        review_players = len({warning.player_id for warning in catalog.review_warnings})
        return (f"{linked} jogadores com {len(catalog.accounts)} contas confirmadas; "
                f"{catalog.eligible_players - linked} jogadores elegiveis sem conta confirmada. "
                f"{len(catalog.pending_accounts)} contas pendentes de validacao. "
                f"{catalog.excluded_players} registros excluidos por escopo ou saida competitiva confirmada. "
                f"{review_players} jogadores com revisao pendente, sem suspender o monitoramento.")

    @pro_lives.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        await self.monitor.reload()
        channel_id = (await self.repository.subscriptions()).get(ctx.guild.id)
        last = self.monitor.last_check
        lines = ["**Status das lives profissionais**", self._coverage(),
                 f"Canal: <#{channel_id}>" if channel_id else "Alertas desativados neste servidor.",
                 "Intervalo: 4 minutos.",
                 f"Ultima consulta: {discord.utils.format_dt(last, 'R')}" if last else "Nenhuma consulta executada."]
        counts = Counter((a.league, a.role) for a in self.monitor.catalog.accounts)
        if counts:
            lines.append("Contas por liga/posicao: " + ", ".join(f"{league} {role}: {count}" for (league, role), count in sorted(counts.items())))
        lines.extend(f"Revisar {discord.utils.escape_markdown(warning.name)}: {warning.message}"
                     for warning in self.monitor.catalog.review_warnings)
        lines.extend(f"Pendente: {discord.utils.escape_markdown(item.account.name)} / "
                     f"{item.account.platform.upper()} — {discord.utils.escape_markdown(item.reason)}"
                     for item in self.monitor.catalog.pending_accounts)
        errors = Counter(value for value in self.monitor.health.values() if value != "ok")
        lines.extend(f"{count} conta(s): {message}" for message, count in errors.items())
        if ctx.guild.id in self.delivery_errors:
            lines.append(self.delivery_errors[ctx.guild.id])
        for start in range(0, len(lines), 6):
            await ctx.send("\n".join(lines[start:start + 6])[:1900], allowed_mentions=discord.AllowedMentions.none())

    @pro_lives.command(name="jogadores")
    async def players(self, ctx: commands.Context) -> None:
        await self.monitor.reload()
        if not self.monitor.catalog.accounts and not self.monitor.catalog.pending_accounts:
            await ctx.send(self._coverage())
            return
        review_players = {warning.player_id for warning in self.monitor.catalog.review_warnings}
        lines = [f"{a.name}{' [revisao pendente]' if a.player_id in review_players else ''} — {a.team} / {a.league} / {a.role} — {a.platform.upper()}: {a.url}"
                 for a in self.monitor.catalog.accounts]
        for start in range(0, len(lines), 5):
            await ctx.send("\n".join(lines[start:start + 5]), allowed_mentions=discord.AllowedMentions.none())
        for item in self.monitor.catalog.pending_accounts:
            a = item.account
            await ctx.send(f"[PENDENTE] {a.name} — {a.team} / {a.league} / {a.role} — "
                           f"{a.platform.upper()}: {a.url}\n{item.reason}",
                           allowed_mentions=discord.AllowedMentions.none())

    @pro_lives.command(name="recarregar")
    @commands.has_guild_permissions(manage_channels=True)
    async def reload_catalog(self, ctx: commands.Context) -> None:
        await self.monitor.reload()
        await ctx.send(self._coverage())

    async def _deliver(self, delivery: Delivery, accounts: dict[str, Account]) -> None:
        async with self.delivery_slots:
            # Re-check settings in case an administrator disabled/replaced the
            # channel while platform requests were running.
            if (await self.repository.subscriptions()).get(delivery.guild_id) != delivery.channel_id:
                return
            account = accounts.get(delivery.account_key)
            if account is None:
                return
            channel = self.bot.get_channel(delivery.channel_id)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != delivery.guild_id:
                self.delivery_errors[delivery.guild_id] = "Canal de alertas indisponivel. Configure-o novamente."
                return
            try:
                async with asyncio.timeout(20):
                    await channel.send(embed=live_embed(account, delivery), allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, TimeoutError) as exc:
                self.delivery_errors[delivery.guild_id] = f"Falha ao enviar alerta: {type(exc).__name__}; nova tentativa no proximo ciclo."
                return
            await self.repository.acknowledge(delivery)
            self.delivery_errors.pop(delivery.guild_id, None)

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_pro_lives(self) -> None:
        try:
            deliveries = await self.monitor.poll()
            accounts = {a.key: a for a in self.monitor.catalog.accounts}
            await asyncio.gather(*(self._deliver(d, accounts) for d in deliveries))
        except Exception as exc:
            # DB/storage failures must not permanently kill the polling loop.
            log.error("ProLives: ciclo falhou (%s)", type(exc).__name__)

    @check_pro_lives.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("Use este comando em um servidor.")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("Voce precisa da permissao Gerenciar canais.")
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.send("Informe um canal de texto valido. Exemplo: `prolives canal #lives`.")
        else:
            log.error("ProLives: comando falhou (%s)", type(error).__name__)
            await ctx.send("Nao foi possivel concluir o comando. Verifique o armazenamento e os logs do bot.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProLives(bot))
