from __future__ import annotations

import asyncio
import logging
from collections import Counter
from pathlib import Path

import discord
from discord.ext import commands, tasks

from services.pro_live_service import Account, Delivery, LiveMonitor, LiveRepository


from services.discord_messages import response_sender, brand_embed

reply = response_sender("Lives profissionais")

log = logging.getLogger(__name__)
POLL_INTERVAL_MINUTES = 4
BASE_PATH = Path(__file__).resolve().parent.parent


def live_embed(account: Account, delivery: Delivery) -> discord.Embed:
    embed = discord.Embed(
        title=f"{account.name} está ao vivo"[:256],
        url=account.url,
        description=discord.utils.escape_markdown(delivery.title)[:1000]
        or "Transmissão ao vivo",
        color=0x9146FF,
    )
    embed.add_field(
        name="Jogador", value=discord.utils.escape_markdown(account.name), inline=True
    )
    embed.add_field(
        name="Equipe / Liga",
        value=discord.utils.escape_markdown(f"{account.team} / {account.league}"),
        inline=True,
    )
    embed.add_field(name="Posição", value=account.role, inline=True)
    embed.add_field(name="Plataforma", value=account.platform.upper(), inline=True)
    embed.add_field(
        name="Assistir", value=f"[Assistir à transmissão]({account.url})", inline=False
    )
    return brand_embed(embed, "Lives profissionais")


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
        await reply(
            ctx,
            "**Lives profissionais de LoL — Ásia e Twitch de todas as regiões**\n"
            f"`{prefix}prolives canal #canal` — Ativar alertas neste servidor.\n"
            f"`{prefix}prolives parar` — Desativar alertas.\n"
            f"`{prefix}prolives status` — Cobertura, última consulta e falhas.\n"
            f"`{prefix}prolives jogadores` — Contas confirmadas monitoradas.\n"
            f"`{prefix}prolives recarregar` — Reler o catálogo verificado.\n"
            "Consultas a cada 4 minutos. A primeira observação serve de referência, sem alertar lives já abertas.",
        )

    @pro_lives.command(name="canal")
    @commands.has_guild_permissions(manage_channels=True)
    async def set_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        if channel.guild.id != ctx.guild.id:
            await reply(ctx, "Escolha um canal deste servidor.", tone="warning")
            return
        permissions = channel.permissions_for(ctx.guild.me)
        if not (
            permissions.view_channel
            and permissions.send_messages
            and permissions.embed_links
        ):
            await reply(
                ctx,
                "O bot precisa das permissões Ver canal, Enviar mensagens e Inserir links neste canal.",
                tone="warning",
            )
            return
        await self.repository.subscribe(ctx.guild.id, channel.id)
        await self.monitor.reload()
        await reply(
            ctx,
            f"O canal {channel.mention} receberá as novas transmissões detectadas.\n\n"
            + self._coverage(),
            title="Alertas de lives ativados",
            tone="success",
        )

    @pro_lives.command(name="parar")
    @commands.has_guild_permissions(manage_channels=True)
    async def stop(self, ctx: commands.Context) -> None:
        await self.repository.subscribe(ctx.guild.id, None)
        self.delivery_errors.pop(ctx.guild.id, None)
        await reply(
            ctx,
            "Os alertas de lives profissionais foram desativados neste servidor.",
            title="Alertas desativados",
            tone="success",
        )

    def _coverage(self) -> str:
        if self.monitor.catalog_error:
            return self.monitor.catalog_error
        catalog = self.monitor.catalog
        if not catalog.accounts and not catalog.pending_accounts:
            return "Nenhuma conta verificada elegível. O monitoramento aguarda o catálogo com fontes e datas atuais."
        linked = len({a.player_id for a in catalog.accounts})
        review_players = len({warning.player_id for warning in catalog.review_warnings})
        return (
            f"**Cobertura:** {linked} jogadores com {len(catalog.accounts)} contas confirmadas.\n"
            f"**Sem conta confirmada:** {catalog.eligible_players - linked} jogadores elegíveis.\n"
            f"**Contas a validar:** {len(catalog.pending_accounts)}.\n"
            f"**Fora do escopo:** {catalog.excluded_players} registros.\n"
            f"**Revisões pendentes:** {review_players} jogadores; o monitoramento permanece ativo."
        )

    @pro_lives.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        await self.monitor.reload()
        channel_id = (await self.repository.subscriptions()).get(ctx.guild.id)
        last = self.monitor.last_check
        lines = [
            "**Status das lives profissionais**",
            self._coverage(),
            f"Canal: <#{channel_id}>"
            if channel_id
            else "Alertas desativados neste servidor.",
            "Intervalo: 4 minutos.",
            f"Última consulta: {discord.utils.format_dt(last, 'R')}"
            if last
            else "Nenhuma consulta executada.",
        ]
        counts = Counter((a.league, a.role) for a in self.monitor.catalog.accounts)
        if counts:
            lines.append(
                "Contas por liga/posição: "
                + ", ".join(
                    f"{league} {role}: {count}"
                    for (league, role), count in sorted(counts.items())
                )
            )
        lines.extend(
            f"Revisar {discord.utils.escape_markdown(warning.name)}: {warning.message}"
            for warning in self.monitor.catalog.review_warnings
        )
        lines.extend(
            f"Pendente: {discord.utils.escape_markdown(item.account.name)} / "
            f"{item.account.platform.upper()} — {discord.utils.escape_markdown(item.reason)}"
            for item in self.monitor.catalog.pending_accounts
        )
        errors = Counter(
            value for value in self.monitor.health.values() if value != "ok"
        )
        lines.extend(
            f"{count} conta(s): {message}" for message, count in errors.items()
        )
        if ctx.guild.id in self.delivery_errors:
            lines.append(self.delivery_errors[ctx.guild.id])
        for start in range(0, len(lines), 6):
            await reply(
                ctx,
                "\n".join(lines[start : start + 6])[:1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @pro_lives.command(name="jogadores")
    async def players(self, ctx: commands.Context) -> None:
        await self.monitor.reload()
        if (
            not self.monitor.catalog.accounts
            and not self.monitor.catalog.pending_accounts
        ):
            await reply(ctx, self._coverage())
            return
        review_players = {
            warning.player_id for warning in self.monitor.catalog.review_warnings
        }
        lines = [
            f"{a.name}{' [revisão pendente]' if a.player_id in review_players else ''} — {a.team} / {a.league} / {a.role} — {a.platform.upper()}: {a.url}"
            for a in self.monitor.catalog.accounts
        ]
        for start in range(0, len(lines), 5):
            await reply(
                ctx,
                "\n".join(lines[start : start + 5]),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        for item in self.monitor.catalog.pending_accounts:
            a = item.account
            await reply(
                ctx,
                f"[PENDENTE] {a.name} — {a.team} / {a.league} / {a.role} — "
                f"{a.platform.upper()}: {a.url}\n{item.reason}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @pro_lives.command(name="recarregar")
    @commands.has_guild_permissions(manage_channels=True)
    async def reload_catalog(self, ctx: commands.Context) -> None:
        await self.monitor.reload()
        await reply(ctx, self._coverage())

    async def _deliver(self, delivery: Delivery, accounts: dict[str, Account]) -> None:
        async with self.delivery_slots:
            # Re-check settings in case an administrator disabled/replaced the
            # channel while platform requests were running.
            if (await self.repository.subscriptions()).get(
                delivery.guild_id
            ) != delivery.channel_id:
                return
            account = accounts.get(delivery.account_key)
            if account is None:
                return
            channel = self.bot.get_channel(delivery.channel_id)
            if (
                not isinstance(channel, discord.TextChannel)
                or channel.guild.id != delivery.guild_id
            ):
                self.delivery_errors[delivery.guild_id] = (
                    "Canal de alertas indisponível. Configure-o novamente."
                )
                return
            try:
                async with asyncio.timeout(20):
                    await channel.send(
                        embed=live_embed(account, delivery),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except (discord.HTTPException, TimeoutError) as exc:
                self.delivery_errors[delivery.guild_id] = (
                    f"Falha ao enviar alerta: {type(exc).__name__}; nova tentativa no próximo ciclo."
                )
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
            log.error("Prolives: ciclo falhou (%s)", type(exc).__name__)

    @check_pro_lives.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.NoPrivateMessage):
            await reply(ctx, "Use este comando em um servidor.", tone="warning")
        elif isinstance(error, commands.MissingPermissions):
            await reply(
                ctx, "Você precisa da permissão Gerenciar canais.", tone="warning"
            )
        elif isinstance(
            error, (commands.MissingRequiredArgument, commands.BadArgument)
        ):
            await reply(
                ctx,
                "Informe um canal de texto válido. Exemplo: `prolives canal #lives`.",
                tone="warning",
            )
        else:
            log.error("Prolives: comando falhou (%s)", type(error).__name__)
            await reply(
                ctx,
                "Não foi possível concluir o comando. Verifique o armazenamento e os logs do bot.",
                tone="error",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProLives(bot))
