from __future__ import annotations

from pathlib import Path

import discord
from discord.ext import commands, tasks

from services.ge_news_service import (
    GeNewsFeedClient,
    GeNewsItem,
    GeNewsStateRepository,
    MAX_NEWS_PER_CHECK,
    get_recent_unseen_news,
)


POLL_INTERVAL_MINUTES = 5
EMBED_COLOR = 0x06AA48


class GeNews(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        state_path = Path(__file__).resolve().parent.parent / "ge_news_state.json"
        self.state_repository = GeNewsStateRepository(state_path)
        self.feed_client = GeNewsFeedClient()

        state = self.state_repository.load()
        self.channel_id: int | None = state["channel_id"]
        self.seen_ids: list[str] = state["seen_ids"]

        self.check_ge_news.start()

    async def cog_unload(self) -> None:
        self.check_ge_news.cancel()

    @commands.group(name="genoticias", invoke_without_command=True)
    async def ge_news_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "\n".join(
                [
                    "**Noticias do GE**",
                    "Use para receber novas noticias de futebol do GE automaticamente.",
                    f"`{prefix}genoticias canal #canal` - Ativa noticias no canal marcado. Exemplo: `{prefix}genoticias canal #noticias`.",
                    f"`{prefix}genoticias status` - Mostra se as noticias estao ativas, qual canal recebe e quantas noticias ja foram vistas.",
                    f"`{prefix}genoticias parar` - Desativa o envio automatico de noticias.",
                    "Ao ativar, as noticias atuais sao marcadas como vistas para evitar spam; o bot envia apenas novidades futuras.",
                ]
            )
        )

    @ge_news_group.command(name="canal")
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        if not self._can_manage_news(ctx):
            await ctx.send("Voce nao tem permissao para configurar as noticias do GE.")
            return

        try:
            current_items = await self.feed_client.fetch_news()
        except Exception as exc:
            await ctx.send(f"Nao consegui acessar o feed do GE agora: {exc}")
            return

        self.channel_id = channel.id
        self.seen_ids = [item.identifier for item in current_items]
        self._save_state()

        await ctx.send(
            f"Noticias do GE ativadas em {channel.mention}. "
            "As noticias atuais foram marcadas como vistas; vou enviar apenas novidades futuras."
        )

    @ge_news_group.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        if self.channel_id is None:
            await ctx.send("Noticias do GE estao desativadas.")
            return

        channel = self.bot.get_channel(self.channel_id)
        channel_text = channel.mention if isinstance(channel, discord.TextChannel) else f"`{self.channel_id}`"
        await ctx.send(
            "\n".join(
                [
                    "**Noticias do GE**",
                    f"Canal: {channel_text}",
                    f"Intervalo: {POLL_INTERVAL_MINUTES} minutos",
                    f"Noticias vistas: {len(self.seen_ids)}",
                ]
            )
        )

    @ge_news_group.command(name="parar")
    async def stop_news(self, ctx: commands.Context) -> None:
        if not self._can_manage_news(ctx):
            await ctx.send("Voce nao tem permissao para configurar as noticias do GE.")
            return

        self.channel_id = None
        self._save_state()
        await ctx.send("Noticias do GE desativadas.")

    @set_channel.error
    async def set_channel_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Informe o canal. Exemplo: `genoticias canal #noticias`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("Canal invalido. Marque um canal de texto valido.")
            return
        raise error

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_ge_news(self) -> None:
        if self.channel_id is None:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            print(f"Canal de noticias do GE nao encontrado: {self.channel_id}")
            return

        try:
            current_items = await self.feed_client.fetch_news()
        except Exception as exc:
            print(f"Erro ao buscar noticias do GE: {exc}")
            return

        unseen_items = get_recent_unseen_news(current_items, set(self.seen_ids))
        if not unseen_items:
            return
        if len(unseen_items) > MAX_NEWS_PER_CHECK:
            self.seen_ids = [item.identifier for item in current_items]
            self._save_state()
            print(
                "GE retornou muitas noticias nao vistas de uma vez; "
                f"{len(unseen_items)} itens foram marcados como vistos para evitar spam."
            )
            return

        for item in unseen_items[:MAX_NEWS_PER_CHECK]:
            try:
                await channel.send(embed=self._build_embed(item))
            except discord.Forbidden:
                print(f"Sem permissao para enviar noticias do GE no canal {channel.id}.")
                return
            except discord.HTTPException as exc:
                print(f"Erro ao enviar noticia do GE no Discord: {exc}")
                return

            self.seen_ids.append(item.identifier)
            self._save_state()

    @check_ge_news.before_loop
    async def before_check_ge_news(self) -> None:
        await self.bot.wait_until_ready()

    def _save_state(self) -> None:
        self.state_repository.save(self.channel_id, self.seen_ids)

    @staticmethod
    def _can_manage_news(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False

        permissions = ctx.author.guild_permissions
        return (
            ctx.author.id == ctx.guild.owner_id
            or permissions.administrator
            or permissions.manage_channels
            or permissions.manage_messages
        )

    @staticmethod
    def _build_embed(item: GeNewsItem) -> discord.Embed:
        embed = discord.Embed(
            title=item.title[:256],
            url=item.link,
            description=item.summary[:300] if item.summary else None,
            color=EMBED_COLOR,
        )
        embed.set_author(name="GE - Futebol")
        if item.published_at is not None:
            embed.timestamp = item.published_at
        embed.add_field(name="Link", value=f"[Abrir noticia]({item.link})", inline=False)
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeNews(bot))
