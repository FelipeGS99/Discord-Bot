from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks

from config import settings
from services.brasileirao_service import (
    ApiFootballClient,
    BrasileiraoFixture,
    BrasileiraoStateRepository,
    describe_fixture_update,
    deserialize_fixtures,
    select_missing_live_fixture_ids,
    serialize_fixtures,
    should_monitor_fixtures,
)


EMBED_COLOR = 0x2F80ED
POLL_INTERVAL_MINUTES = 1


COMPETITIONS = (
    ("Brasileirao Serie A", "Brasileirao Serie A", "brasileirao_league_id", "brasileirao_state.json", 0x009C3B),
    ("Libertadores", "Libertadores", "libertadores_league_id", "libertadores_state.json", 0x003B7A),
    ("Sul-Americana", "Sul-Americana", "sulamericana_league_id", "sulamericana_state.json", 0xF28C28),
)


class Futebol(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api_client = ApiFootballClient(settings.bsd_api_key) if settings.bsd_api_key else None
        self.base_path = Path(__file__).resolve().parent.parent
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
                    f"`{prefix}futebol hoje` - Mostra jogos de hoje nas competicoes monitoradas.",
                    f"`{prefix}futebol amanha` - Mostra jogos de amanha nas competicoes monitoradas.",
                ]
            )
        )

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

        await ctx.send(embed=self._build_matches_embed(grouped_fixtures, scorers_by_fixture, fixture_date, label))

    async def _fetch_grouped_fixtures(self, fixture_date: date) -> dict[str, list[BrasileiraoFixture]]:
        grouped_fixtures: dict[str, list[BrasileiraoFixture]] = {}
        for title, _author, setting_name, _state_name, _color in COMPETITIONS:
            league_id = getattr(settings, setting_name)
            grouped_fixtures[title] = await self.api_client.fetch_fixtures(league_id, fixture_date)
        return grouped_fixtures

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_scores(self) -> None:
        if self.api_client is None:
            return

        try:
            all_live_fixtures = await self.api_client.fetch_all_live_fixtures()
        except Exception as exc:
            print(f"Erro ao buscar placares ao vivo: {exc}")
            return

        for competition_name, author_name, setting_name, state_name, color in COMPETITIONS:
            league_id = getattr(settings, setting_name)
            live_fixtures = [
                fixture for fixture in all_live_fixtures if fixture.league_id == league_id
            ]
            await self._process_competition_scores(
                competition_name=competition_name,
                author_name=author_name,
                state_name=state_name,
                color=color,
                league_id=league_id,
                live_fixtures=live_fixtures,
            )

    @check_scores.before_loop
    async def before_check_scores(self) -> None:
        await self.bot.wait_until_ready()

    async def _process_competition_scores(
        self,
        competition_name: str,
        author_name: str,
        state_name: str,
        color: int,
        league_id: int,
        live_fixtures: list[BrasileiraoFixture],
    ) -> None:
        repository = BrasileiraoStateRepository(self.base_path / state_name)
        state = repository.load()
        channel_id = state["channel_id"]
        if channel_id is None:
            return

        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            print(f"Canal de placares de {competition_name} nao encontrado: {channel_id}")
            return

        checked_date = state["checked_date"]
        fixture_snapshots = {
            str(key): str(value) for key, value in state["fixture_snapshots"].items()
        }
        fixtures_today = deserialize_fixtures(state["fixtures_today"])
        fixtures_to_compare = live_fixtures
        if fixtures_to_compare:
            checked_date = date.today().isoformat()
            missing_live_fixture_ids = select_missing_live_fixture_ids(fixtures_today, live_fixtures)
            if missing_live_fixture_ids:
                try:
                    fixtures_today = await self.api_client.fetch_fixtures(league_id, date.today())
                except Exception as exc:
                    print(f"Erro ao consultar jogos encerrados ou em intervalo de {competition_name}: {exc}")
                    return

                live_fixture_ids = {fixture.fixture_id for fixture in live_fixtures}
                tracked_updates = [
                    fixture
                    for fixture in fixtures_today
                    if fixture.fixture_id in missing_live_fixture_ids
                    and fixture.fixture_id not in live_fixture_ids
                ]
                fixtures_to_compare = live_fixtures + tracked_updates

        if not fixtures_to_compare:
            had_live_snapshot = any(fixture.is_live for fixture in fixtures_today)
            if not had_live_snapshot:
                if checked_date == date.today().isoformat() and not should_monitor_fixtures(fixtures_today):
                    return
                try:
                    fixtures_today = await self.api_client.fetch_fixtures(league_id, date.today())
                except Exception as exc:
                    print(f"Erro ao consultar jogos de {competition_name}: {exc}")
                    return
                checked_date = date.today().isoformat()
                if not should_monitor_fixtures(fixtures_today):
                    self._save_competition_state(repository, channel_id, checked_date, fixture_snapshots, fixtures_today)
                    return
            else:
                try:
                    fixtures_today = await self.api_client.fetch_fixtures(league_id, date.today())
                except Exception as exc:
                    print(f"Erro ao consultar encerramento de {competition_name}: {exc}")
                    return
                checked_date = date.today().isoformat()

            fixtures_to_compare = fixtures_today

        changed_fixtures = [
            fixture
            for fixture in fixtures_to_compare
            if fixture_snapshots.get(str(fixture.fixture_id)) != fixture.snapshot_key
        ]
        if not changed_fixtures:
            self._save_competition_state(repository, channel_id, checked_date, fixture_snapshots, fixtures_to_compare)
            return

        for fixture in changed_fixtures:
            scorers = await self._fetch_goal_scorers(fixture)
            reason = describe_fixture_update(fixture, fixture_snapshots.get(str(fixture.fixture_id)))
            try:
                await channel.send(embed=self._build_score_embed(fixture, author_name, color, scorers, reason))
            except discord.Forbidden:
                print(f"Sem permissao para enviar placares no canal {channel.id}.")
                return
            except discord.HTTPException as exc:
                print(f"Erro ao enviar placar no Discord: {exc}")
                return

            fixture_snapshots[str(fixture.fixture_id)] = fixture.snapshot_key

        self._save_competition_state(repository, channel_id, checked_date, fixture_snapshots, fixtures_to_compare)

    async def _fetch_goal_scorers(self, fixture: BrasileiraoFixture) -> list[str]:
        if self.api_client is None or fixture.home_goals is None or fixture.away_goals is None:
            return []
        if fixture.home_goals + fixture.away_goals <= 0:
            return []
        try:
            return await self.api_client.fetch_goal_scorers(fixture.fixture_id)
        except Exception as exc:
            print(f"Erro ao buscar autores dos gols: {exc}")
            return []

    @staticmethod
    def _save_competition_state(
        repository: BrasileiraoStateRepository,
        channel_id: int | None,
        checked_date: str | None,
        fixture_snapshots: dict[str, str],
        fixtures_today: list[BrasileiraoFixture],
    ) -> None:
        repository.save(channel_id, checked_date, fixture_snapshots, serialize_fixtures(fixtures_today))

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
    def _build_matches_embed(
        grouped_fixtures: dict[str, list[BrasileiraoFixture]],
        scorers_by_fixture: dict[int, list[str]],
        fixture_date: date,
        label: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Futebol - {label}",
            description=f"Data: `{fixture_date.isoformat()}`",
            color=EMBED_COLOR,
        )

        for competition_name, fixtures in grouped_fixtures.items():
            if not fixtures:
                continue
            value = "\n\n".join(
                _format_fixture(fixture, scorers_by_fixture.get(fixture.fixture_id))
                for fixture in fixtures
            )
            embed.add_field(name=competition_name, value=value[:1024], inline=False)

        return embed

    @staticmethod
    def _build_score_embed(
        fixture: BrasileiraoFixture,
        author_name: str,
        color: int,
        scorers: list[str] | None,
        reason: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{reason}: {fixture.home_team} {fixture.score_text} {fixture.away_team}",
            description=_format_fixture(fixture),
            color=color,
        )
        embed.set_author(name=author_name)
        if scorers:
            embed.add_field(name="Gols", value="\n".join(scorers), inline=False)
        if fixture.kickoff_at is not None:
            embed.timestamp = fixture.kickoff_at
        return embed


def _format_fixture(fixture: BrasileiraoFixture, scorers: list[str] | None = None) -> str:
    status = fixture.status_long or fixture.status_short or "Status indisponivel"
    elapsed = f" - {fixture.elapsed}'" if fixture.elapsed is not None else ""
    kickoff = f"\nData: <t:{int(fixture.kickoff_at.timestamp())}:f>" if fixture.kickoff_at is not None else ""
    scorers_line = f"\nGols:\n**{chr(10).join(scorers)}**" if scorers else ""
    return f"**{fixture.home_team} {fixture.score_text} {fixture.away_team}**\nStatus: **{status}{elapsed}**{kickoff}{scorers_line}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Futebol(bot))
