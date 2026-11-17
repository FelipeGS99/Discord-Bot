from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks

from config import settings
from cogs.football_colors import color_for_active_fixture
from services.football_channel_service import FootballChannelManager, FootballChannelRepository
from services.brasileirao_service import (
    ApiFootballClient,
    BrasileiraoFixture,
)


EMBED_COLOR = 0x2F80ED
POLL_INTERVAL_MINUTES = 1


COMPETITIONS = (
    ("Brasileirão Série A", "Brasileirão Série A", "brasileirao_league_id", "brasileirao_state.json", 0x009C3B),
    ("Libertadores", "Libertadores", "libertadores_league_id", "libertadores_state.json", 0x003B7A),
    ("Sul-Americana", "Sul-Americana", "sulamericana_league_id", "sulamericana_state.json", 0xF28C28),
    ("Copa do Brasil", "Copa do Brasil", "copadobrasil_league_id", "copadobrasil_state.json", 0x2F80ED),
)


class Futebol(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api_client = ApiFootballClient(settings.bsd_api_key) if settings.bsd_api_key else None
        self.base_path = Path(__file__).resolve().parent.parent
        self.channel_manager = FootballChannelManager(
            bot, self.api_client, FootballChannelRepository(self.base_path / "football_channels_state.json"),
            lambda fixture, scorers, reason, live: self._build_score_embed(
                fixture, fixture.league_name, EMBED_COLOR, scorers, reason, live),
        )
        self.check_scores.start()

    async def cog_unload(self) -> None:
        self.check_scores.cancel()

    @commands.group(name="futebol", invoke_without_command=True)
    async def futebol_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "\n".join(
                [
                    "**Futebol**",
                    "Use para ver uma lista geral dos jogos monitorados no Brasileirão, Libertadores, Sul-Americana e Copa do Brasil.",
                    f"`{prefix}futebol hoje` - Mostra os jogos de hoje com placar, status, horario e gols quando disponivel.",
                    f"`{prefix}futebol amanha` - Mostra os jogos de amanhã nas competições monitoradas.",
                    "",
                    "**Alertas por competicao**",
                    f"`{prefix}futebol ativar brasileirao` - Ativa canais privados por partida do Brasileirao.",
                    f"`{prefix}futebol ativar libertadores` - Ativa canais privados da Libertadores.",
                    f"`{prefix}futebol ativar sulamericana` - Ativa canais privados da Sul-Americana.",
                    f"`{prefix}futebol ativar copadobrasil` - Ativa canais privados da Copa do Brasil.",
                    f"`{prefix}futebol prazo 60` - Tempo em minutos para apagar canais apos o fim (padrao: 1 hora).",
                    f"`{prefix}futebol status` / `{prefix}futebol parar <liga>` - Consulta ou desativa ligas.",
                    "Acesso pelo cargo Futebol e administradores. Categoria e cargo opcionais: ativar <liga> [categoria] [@cargo].",
                ]
            )
        )

    @staticmethod
    def _league_id(name: str) -> int:
        names = ("brasileirao", "libertadores", "sulamericana", "copadobrasil")
        if name.casefold() not in names:
            raise ValueError("Liga invalida. Use brasileirao, libertadores, sulamericana ou copadobrasil.")
        return getattr(settings, COMPETITIONS[names.index(name.casefold())][2])

    @staticmethod
    def _can_configure(ctx) -> bool:
        return ctx.guild is not None and (
            ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator
            or ctx.author.guild_permissions.manage_channels
        )

    async def enable_league(self, ctx, league: str, category=None, role=None) -> None:
        if not self._can_configure(ctx):
            await ctx.send("Use este comando em um servidor com permissao de gerenciar canais.")
            return
        if self.api_client is None:
            await ctx.send("BSD_API_KEY nao foi configurada; nao foi possivel ativar os jogos.")
            return
        cfg = self.channel_manager.config(ctx.guild.id)
        if role is None:
            role = ctx.guild.get_role(cfg["role_id"]) if cfg.get("role_id") else None
        if role is None:
            candidates = [r for r in ctx.guild.roles if r.name.casefold() == "futebol"]
            if len(candidates) != 1:
                await ctx.send("Crie um cargo chamado Futebol ou informe uma categoria e o @cargo de acesso na ativacao.")
                return
            role = candidates[0]
        if category is None:
            category = ctx.guild.get_channel(cfg["category_id"]) if cfg.get("category_id") else getattr(ctx.channel, "category", None)
            if cfg.get("category_id") and category is None:
                await ctx.send("A categoria configurada foi removida. Informe outra categoria na ativacao.")
                return
        try:
            await self.channel_manager.enable(ctx.guild, self._league_id(league), role, category)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        except discord.HTTPException:
            await ctx.send("Nao consegui atualizar as permissoes dos canais. Confira o acesso do bot e tente novamente.")
            return
        await ctx.send(
            f"Liga {league} ativada neste servidor. Cada partida ao vivo tera um canal privado para {role.mention}. "
            f"Exclusao {self.channel_manager.config(ctx.guild.id)['retention_minutes']} minutos apos o fim. "
            "Administradores tambem tem acesso. Cargo e categoria valem para todas as ligas deste servidor.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def disable_league(self, ctx, league: str) -> None:
        if not self._can_configure(ctx):
            await ctx.send("Use este comando em um servidor com permissao de gerenciar canais.")
            return
        try:
            await self.channel_manager.disable(ctx.guild.id, self._league_id(league))
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Liga {league} desativada neste servidor. Canais existentes seguem ate o fim e o prazo de exclusao.")

    async def league_status(self, ctx, league: str | None = None) -> None:
        if ctx.guild is None:
            await ctx.send("Use este comando em um servidor.")
            return
        cfg = self.channel_manager.config(ctx.guild.id)
        names = ("brasileirao", "libertadores", "sulamericana", "copadobrasil")
        enabled = [n for n in names if self._league_id(n) in cfg.get("leagues", [])]
        matches = [m for m in self.channel_manager.state["matches"].values()
                   if m["guild_id"] == ctx.guild.id and not m.get("closed")]
        lines = ["**Canais privados de futebol**", f"Ligas ativas: {', '.join(enabled) or 'nenhuma'}",
                 f"Cargo: <@&{cfg['role_id']}>" if cfg.get("role_id") else "Cargo: nao configurado",
                 f"Categoria: <#{cfg['category_id']}>" if cfg.get("category_id") else "Categoria: raiz do servidor",
                 f"Exclusao apos o fim: {cfg.get('retention_minutes', 60)} minutos",
                 f"Canais de partidas em acompanhamento: {len(matches)}", "Consulta a cada 1 minuto."]
        if league is not None:
            lines.append(f"{league}: {'ativada' if league in enabled else 'desativada'}")
        if ctx.guild.id in self.channel_manager.errors:
            lines.append(self.channel_manager.errors[ctx.guild.id])
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())

    @futebol_group.command(name="ativar")
    async def activate(self, ctx: commands.Context, liga: str,
                       categoria: discord.CategoryChannel | None = None, cargo: discord.Role | None = None) -> None:
        await self.enable_league(ctx, liga, categoria, cargo)

    @futebol_group.command(name="parar", aliases=["desativar"])
    async def deactivate(self, ctx: commands.Context, liga: str) -> None:
        await self.disable_league(ctx, liga)

    @futebol_group.command(name="prazo")
    async def set_retention(self, ctx: commands.Context, minutos: int) -> None:
        if not self._can_configure(ctx):
            await ctx.send("Use este comando em um servidor com permissao de gerenciar canais.")
            return
        try:
            await self.channel_manager.retention(ctx.guild.id, minutos)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Canais de jogos serao apagados {minutos} minutos apos o fim da partida.")

    @futebol_group.command(name="status")
    async def channels_status(self, ctx: commands.Context) -> None:
        await self.league_status(ctx)

    @activate.error
    @deactivate.error
    @set_retention.error
    async def configuration_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            await ctx.send("Confira os argumentos. Use futebol para ver a ajuda; prazo deve ser um numero de minutos.")
            return
        raise error

    @futebol_group.command(name="hoje")
    async def today(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, date.today(), "hoje")

    @futebol_group.command(name="amanha")
    async def tomorrow(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, date.today() + timedelta(days=1), "amanha")

    async def _send_matches_for_date(
        self,
        ctx: commands.Context,
        fixture_date: date,
        label: str,
    ) -> None:
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        try:
            grouped_fixtures = await self._fetch_grouped_fixtures(fixture_date)
            scorers_by_fixture = await self._fetch_goal_scorers_by_fixture(grouped_fixtures)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a BSD agora: {exc}")
            return

        if not any(grouped_fixtures.values()):
            await ctx.send(f"Nao encontrei jogos para {label} nas competicoes monitoradas.")
            return

        await _send_embeds(
            ctx,
            self._build_matches_embeds(grouped_fixtures, scorers_by_fixture, fixture_date, label),
        )

    async def _fetch_grouped_fixtures(self, fixture_date: date) -> dict[str, list[BrasileiraoFixture]]:
        grouped_fixtures: dict[str, list[BrasileiraoFixture]] = {}
        for title, _author, setting_name, _state_name, _color in COMPETITIONS:
            league_id = getattr(settings, setting_name)
            grouped_fixtures[title] = await self.api_client.fetch_fixtures(league_id, fixture_date)
        return grouped_fixtures

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_scores(self) -> None:
        try:
            await self.channel_manager.poll()
        except Exception:
            # An unexpected state/filesystem error must not permanently kill the monitor.
            logging.getLogger(__name__).exception("Falha no monitor de canais de futebol")

    @check_scores.before_loop
    async def before_check_scores(self) -> None:
        await self.bot.wait_until_ready()

    async def _fetch_goal_scorers_by_fixture(
        self,
        grouped_fixtures: dict[str, list[BrasileiraoFixture]],
    ) -> dict[int, list[str]]:
        scorers_by_fixture: dict[int, list[str]] = {}
        for fixtures in grouped_fixtures.values():
            for fixture in fixtures:
                if fixture.home_goals is None or fixture.away_goals is None:
                    continue
                if fixture.home_goals + fixture.away_goals <= 0:
                    continue
                scorers = await self.api_client.fetch_goal_scorers(fixture.fixture_id)
                if scorers:
                    scorers_by_fixture[fixture.fixture_id] = scorers
        return scorers_by_fixture

    @staticmethod
    def _build_matches_embeds(
        grouped_fixtures: dict[str, list[BrasileiraoFixture]],
        scorers_by_fixture: dict[int, list[str]],
        fixture_date: date,
        label: str,
    ) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []
        colors_by_competition = {competition_name: color for competition_name, *_rest, color in COMPETITIONS}
        for competition_name, fixtures in grouped_fixtures.items():
            if not fixtures:
                continue
            for fixture in fixtures:
                embed = discord.Embed(
                    title=f"{competition_name} - {label}",
                    description=(
                        f"Data: `{fixture_date.isoformat()}`\n\n"
                        f"{_format_fixture(fixture, scorers_by_fixture.get(fixture.fixture_id))}"
                    ),
                    color=colors_by_competition.get(competition_name, EMBED_COLOR),
                )
                embeds.append(embed)

        return embeds

    @staticmethod
    def _build_score_embed(
        fixture: BrasileiraoFixture,
        author_name: str,
        color: int,
        scorers: list[str] | None,
        reason: str,
        active_fixtures: list[BrasileiraoFixture] | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{reason}: {fixture.home_team} {fixture.score_text} {fixture.away_team}",
            description=_format_fixture(fixture),
            color=color_for_active_fixture(fixture, active_fixtures),
        )
        embed.set_author(name=author_name)
        if scorers:
            embed.add_field(name="Gols", value="\n".join(scorers), inline=False)
        return embed


def _format_fixture(fixture: BrasileiraoFixture, scorers: list[str] | None = None) -> str:
    status = fixture.status_long or fixture.status_short or "Status indisponível"
    elapsed = f" - {fixture.elapsed}'" if fixture.elapsed is not None else ""
    kickoff = f"\nData: <t:{int(fixture.kickoff_at.timestamp())}:f>" if fixture.kickoff_at is not None else ""
    scorers_line = f"\nGols:\n**{chr(10).join(scorers)}**" if scorers else ""
    return f"**{fixture.home_team} {fixture.score_text} {fixture.away_team}**\nStatus: **{status}{elapsed}**{kickoff}{scorers_line}"


async def _send_embeds(ctx: commands.Context, embeds: list[discord.Embed]) -> None:
    for index in range(0, len(embeds), 10):
        await ctx.send(embeds=embeds[index:index + 10])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Futebol(bot))
