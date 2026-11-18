from __future__ import annotations

import logging

from datetime import date

import discord
from discord.ext import commands

from config import settings
from cogs.football_colors import color_for_active_fixture
from services.brasileirao_service import (
    ApiFootballClient,
    BrasileiraoFixture,
)


from services.discord_messages import response_sender, brand_embed

reply = response_sender("Libertadores")

EMBED_COLOR = 0x003B7A


class Libertadores(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api_client = (
            ApiFootballClient(settings.bsd_api_key) if settings.bsd_api_key else None
        )
        self.league_id = settings.libertadores_league_id
        self.checked_date: str | None = None
        self.fixtures_today: list[BrasileiraoFixture] = []

    @commands.group(name="libertadores", invoke_without_command=True)
    async def libertadores_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await reply(
            ctx,
            "\n".join(
                [
                    "**Libertadores**",
                    "Use para consultar jogos e configurar alertas automáticos da Libertadores.",
                    f"`{prefix}libertadores hoje` — Consulta jogos de hoje com horário, placar, status e gols quando disponível.",
                    f"`{prefix}libertadores ativar [categoria] [@cargo]` — Ativa canais privados por partida para o cargo Futebol.",
                    f"`{prefix}libertadores status` — Consulta a ativação da liga e os canais temporários deste servidor.",
                    f"`{prefix}libertadores parar` — Desativa os alertas automáticos da Libertadores.",
                ]
            ),
        )

    @libertadores_group.command(name="ativar")
    async def activate(
        self,
        ctx: commands.Context,
        categoria: discord.CategoryChannel | None = None,
        cargo: discord.Role | None = None,
    ) -> None:
        await self.bot.get_cog("Futebol").enable_league(
            ctx, "libertadores", categoria, cargo
        )

    @libertadores_group.command(name="hoje")
    async def today(self, ctx: commands.Context) -> None:
        if self.api_client is None:
            await reply(
                ctx,
                "A integração de futebol ainda não está configurada. Solicite a configuração a um administrador do bot.",
                tone="error",
            )
            return

        try:
            fixtures = await self._refresh_today_fixtures(force=True)
        except Exception:
            logging.getLogger(__name__).exception("Falha ao executar comando")
            await reply(
                ctx,
                "Não foi possível consultar os jogos no momento. Tente novamente em alguns instantes.",
                tone="error",
            )
            return

        if not fixtures:
            await reply(
                ctx, "Não encontrei jogos da Libertadores para hoje.", tone="warning"
            )
            return

        scorers_by_fixture = await self._fetch_goal_scorers_by_fixture(fixtures)
        await _send_embeds(ctx, self._build_today_embeds(fixtures, scorers_by_fixture))

    @libertadores_group.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        await self.bot.get_cog("Futebol").league_status(ctx, "libertadores")

    @libertadores_group.command(name="parar")
    async def stop_scores(self, ctx: commands.Context) -> None:
        await self.bot.get_cog("Futebol").disable_league(ctx, "libertadores")

    @activate.error
    async def activation_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.BadArgument):
            await reply(
                ctx,
                "Informe uma categoria e um cargo válidos deste servidor, ou use ativar sem argumentos para o cargo Futebol.",
                tone="warning",
            )
            return
        raise error

    async def _refresh_today_fixtures(self, force: bool) -> list[BrasileiraoFixture]:
        today = date.today().isoformat()
        if not force and self.checked_date == today:
            return self.fixtures_today

        fixtures = await self._fetch_today_fixtures()
        self._store_today_fixtures(fixtures)
        return fixtures

    async def _fetch_today_fixtures(self) -> list[BrasileiraoFixture]:
        if self.api_client is None:
            return []
        return await self.api_client.fetch_fixtures(self.league_id, date.today())

    def _store_today_fixtures(self, fixtures: list[BrasileiraoFixture]) -> None:
        self.checked_date = date.today().isoformat()
        self.fixtures_today = fixtures

    async def _fetch_goal_scorers(self, fixture: BrasileiraoFixture) -> list[str]:
        if (
            self.api_client is None
            or fixture.home_goals is None
            or fixture.away_goals is None
        ):
            return []
        if fixture.home_goals + fixture.away_goals <= 0:
            return []
        try:
            return await self.api_client.fetch_goal_scorers(fixture.fixture_id)
        except Exception as exc:
            print(f"Erro ao buscar autores dos gols da Libertadores: {exc}")
            return []

    async def _fetch_goal_scorers_by_fixture(
        self,
        fixtures: list[BrasileiraoFixture],
    ) -> dict[int, list[str]]:
        scorers_by_fixture: dict[int, list[str]] = {}
        for fixture in fixtures:
            scorers = await self._fetch_goal_scorers(fixture)
            if scorers:
                scorers_by_fixture[fixture.fixture_id] = scorers
        return scorers_by_fixture

    @staticmethod
    def _build_today_embeds(
        fixtures: list[BrasileiraoFixture],
        scorers_by_fixture: dict[int, list[str]] | None = None,
    ) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []
        for fixture in fixtures:
            details = _format_fixture_details(
                fixture, (scorers_by_fixture or {}).get(fixture.fixture_id)
            )
            embed = discord.Embed(
                title="Libertadores - jogos de hoje",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=_format_fixture_title(fixture),
                value=details,
                inline=False,
            )
            embeds.append(brand_embed(embed, "Futebol"))
        return embeds

    @staticmethod
    def _build_score_embed(
        fixture: BrasileiraoFixture,
        scorers: list[str] | None = None,
        reason: str | None = None,
        active_fixtures: list[BrasileiraoFixture] | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{reason + ': ' if reason else ''}{fixture.home_team} {fixture.score_text} {fixture.away_team}",
            description=_format_fixture_line(fixture),
            color=color_for_active_fixture(fixture, active_fixtures),
        )
        embed.set_author(name="Libertadores")
        if scorers:
            embed.add_field(name="Gols", value="\n".join(scorers), inline=False)
        return brand_embed(embed, "Futebol")


def _format_fixture_line(fixture: BrasileiraoFixture) -> str:
    return f"{_format_fixture_title(fixture)}\n{_format_fixture_details(fixture)}"


def _format_fixture_title(fixture: BrasileiraoFixture) -> str:
    return f"{fixture.home_team} {fixture.score_text} {fixture.away_team}"


def _format_fixture_details(
    fixture: BrasileiraoFixture, scorers: list[str] | None = None
) -> str:
    status = fixture.status_long or fixture.status_short or "Status indisponível"
    elapsed = f" - {fixture.elapsed}'" if fixture.elapsed is not None else ""
    kickoff = ""
    if fixture.kickoff_at is not None and fixture.status_short == "NS":
        kickoff = f"\nInício: <t:{int(fixture.kickoff_at.timestamp())}:t>"
    scorers_line = f"\nGols:\n**{chr(10).join(scorers)}**" if scorers else ""
    return f"Status: **{status}{elapsed}**{kickoff}{scorers_line}"


async def _send_embeds(ctx: commands.Context, embeds: list[discord.Embed]) -> None:
    for index in range(0, len(embeds), 10):
        await ctx.send(embeds=embeds[index : index + 10])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Libertadores(bot))
