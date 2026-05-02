from __future__ import annotations

from datetime import date
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
    serialize_fixtures,
    should_monitor_fixtures,
)


POLL_INTERVAL_MINUTES = 1
EMBED_COLOR = 0x003B7A


class Libertadores(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        state_path = Path(__file__).resolve().parent.parent / "libertadores_state.json"
        self.state_repository = BrasileiraoStateRepository(state_path)
        self.api_client = ApiFootballClient(settings.bsd_api_key) if settings.bsd_api_key else None
        self.league_id = settings.libertadores_league_id

        state = self.state_repository.load()
        self.channel_id: int | None = state["channel_id"]
        self.checked_date: str | None = state["checked_date"]
        self.fixture_snapshots: dict[str, str] = {
            str(key): str(value) for key, value in state["fixture_snapshots"].items()
        }
        self.fixtures_today: list[BrasileiraoFixture] = deserialize_fixtures(state["fixtures_today"])

        # Periodic polling is centralized in cogs.futebol to avoid duplicate API calls.

    async def cog_unload(self) -> None:
        self.check_libertadores_scores.cancel()

    @commands.group(name="libertadores", invoke_without_command=True)
    async def libertadores_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "\n".join(
                [
                    "**Libertadores**",
                    "Use para consultar jogos e configurar alertas automáticos da Libertadores.",
                    f"`{prefix}libertadores hoje` - Mostra jogos de hoje com horário, placar, status e gols quando disponível.",
                    f"`{prefix}libertadores canal #canal` - Ativa alertas de início, gol, intervalo, volta de status e fim de jogo. Exemplo: `{prefix}libertadores canal #placares`.",
                    f"`{prefix}libertadores status` - Mostra canal configurado, API, liga e cache atual.",
                    f"`{prefix}libertadores parar` - Desativa os alertas automáticos da Libertadores.",
                ]
            )
        )

    @libertadores_group.command(name="canal")
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        if not self._can_manage_scores(ctx):
            await ctx.send("Voce nao tem permissao para configurar os placares da Libertadores.")
            return
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        self.channel_id = channel.id
        await self._refresh_today_fixtures(force=True)
        self.fixture_snapshots = {
            str(fixture.fixture_id): fixture.snapshot_key for fixture in self.fixtures_today
        }
        self._save_state()

        await ctx.send(
            f"Placares da Libertadores ativados em {channel.mention}. "
            "Vou avisar quando houver mudanca de status ou placar."
        )

    @libertadores_group.command(name="hoje")
    async def today(self, ctx: commands.Context) -> None:
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        try:
            fixtures = await self._refresh_today_fixtures(force=True)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a BSD agora: {exc}")
            return

        if not fixtures:
            await ctx.send("Nao encontrei jogos da Libertadores para hoje.")
            return

        scorers_by_fixture = await self._fetch_goal_scorers_by_fixture(fixtures)
        await ctx.send(embed=self._build_today_embed(fixtures, scorers_by_fixture))

    @libertadores_group.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        channel_text = "desativado"
        if self.channel_id is not None:
            channel = self.bot.get_channel(self.channel_id)
            channel_text = channel.mention if isinstance(channel, discord.TextChannel) else f"`{self.channel_id}`"

        await ctx.send(
            "\n".join(
                [
                    "**Libertadores**",
                    f"Canal: {channel_text}",
                    f"API key: {'configurada' if self.api_client else 'ausente'}",
                    f"Liga: `{self.league_id}`",
                    f"Intervalo ao vivo: {POLL_INTERVAL_MINUTES} minutos",
                    f"Data em cache: `{self.checked_date or 'nenhuma'}`",
                    f"Jogos em cache: {len(self.fixtures_today)}",
                ]
            )
        )

    @libertadores_group.command(name="parar")
    async def stop_scores(self, ctx: commands.Context) -> None:
        if not self._can_manage_scores(ctx):
            await ctx.send("Voce nao tem permissao para configurar os placares da Libertadores.")
            return

        self.channel_id = None
        self._save_state()
        await ctx.send("Placares da Libertadores desativados.")

    @set_channel.error
    async def set_channel_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Informe o canal. Exemplo: `libertadores canal #placares`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("Canal invalido. Marque um canal de texto valido.")
            return
        raise error

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_libertadores_scores(self) -> None:
        if self.channel_id is None or self.api_client is None:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            print(f"Canal de placares da Libertadores nao encontrado: {self.channel_id}")
            return

        try:
            fixtures = await self._fetch_live_fixtures()
        except Exception as exc:
            print(f"Erro ao atualizar placares ao vivo da Libertadores: {exc}")
            return

        if not fixtures:
            had_live_snapshot = any(fixture.is_live for fixture in self.fixtures_today)
            try:
                fixtures = await self._refresh_today_fixtures(force=had_live_snapshot)
            except Exception as exc:
                print(f"Erro ao consultar placares da Libertadores: {exc}")
                return
            if not had_live_snapshot and not should_monitor_fixtures(fixtures):
                return
            try:
                live_fixtures = await self._fetch_live_fixtures()
            except Exception as exc:
                print(f"Erro ao atualizar placares ao vivo da Libertadores: {exc}")
                return
            if live_fixtures:
                fixtures = live_fixtures

        self._store_today_fixtures(fixtures)
        changed_fixtures = self._get_changed_fixtures(fixtures)
        if not changed_fixtures:
            self._save_state()
            return
        for fixture in changed_fixtures:
            try:
                scorers = await self._fetch_goal_scorers(fixture)
                reason = describe_fixture_update(
                    fixture,
                    self.fixture_snapshots.get(str(fixture.fixture_id)),
                )
                await channel.send(embed=self._build_score_embed(fixture, scorers, reason))
            except discord.Forbidden:
                print(f"Sem permissao para enviar placares no canal {channel.id}.")
                return
            except discord.HTTPException as exc:
                print(f"Erro ao enviar placar no Discord: {exc}")
                return

            self.fixture_snapshots[str(fixture.fixture_id)] = fixture.snapshot_key
            self._save_state()

    @check_libertadores_scores.before_loop
    async def before_check_libertadores_scores(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh_today_fixtures(self, force: bool) -> list[BrasileiraoFixture]:
        today = date.today().isoformat()
        if not force and self.checked_date == today:
            return self.fixtures_today

        fixtures = await self._fetch_today_fixtures()
        self._store_today_fixtures(fixtures)
        self.fixture_snapshots = {
            str(fixture.fixture_id): self.fixture_snapshots.get(str(fixture.fixture_id), fixture.snapshot_key)
            for fixture in fixtures
        }
        self._save_state()
        return fixtures

    async def _fetch_today_fixtures(self) -> list[BrasileiraoFixture]:
        if self.api_client is None:
            return []
        return await self.api_client.fetch_fixtures(self.league_id, date.today())

    async def _fetch_live_fixtures(self) -> list[BrasileiraoFixture]:
        if self.api_client is None:
            return []
        return await self.api_client.fetch_live_fixtures(self.league_id)

    def _store_today_fixtures(self, fixtures: list[BrasileiraoFixture]) -> None:
        self.checked_date = date.today().isoformat()
        self.fixtures_today = fixtures

    async def _fetch_goal_scorers(self, fixture: BrasileiraoFixture) -> list[str]:
        if self.api_client is None or fixture.home_goals is None or fixture.away_goals is None:
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

    def _get_changed_fixtures(self, fixtures: list[BrasileiraoFixture]) -> list[BrasileiraoFixture]:
        changed: list[BrasileiraoFixture] = []
        for fixture in fixtures:
            fixture_id = str(fixture.fixture_id)
            if self.fixture_snapshots.get(fixture_id) != fixture.snapshot_key:
                changed.append(fixture)
        return changed

    def _save_state(self) -> None:
        self.state_repository.save(
            self.channel_id,
            self.checked_date,
            self.fixture_snapshots,
            serialize_fixtures(self.fixtures_today),
        )

    @staticmethod
    def _can_manage_scores(ctx: commands.Context) -> bool:
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
    def _build_today_embed(
        fixtures: list[BrasileiraoFixture],
        scorers_by_fixture: dict[int, list[str]] | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Libertadores - jogos de hoje",
            color=EMBED_COLOR,
        )
        for fixture in fixtures:
            details = _format_fixture_details(fixture, (scorers_by_fixture or {}).get(fixture.fixture_id))
            embed.add_field(
                name=_format_fixture_title(fixture),
                value=details,
                inline=False,
            )
        return embed

    @staticmethod
    def _build_score_embed(
        fixture: BrasileiraoFixture,
        scorers: list[str] | None = None,
        reason: str | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"{reason + ': ' if reason else ''}{fixture.home_team} {fixture.score_text} {fixture.away_team}",
            description=_format_fixture_line(fixture),
            color=EMBED_COLOR,
        )
        embed.set_author(name="Libertadores")
        if scorers:
            embed.add_field(name="Gols", value="\n".join(scorers), inline=False)
        if fixture.kickoff_at is not None:
            embed.timestamp = fixture.kickoff_at
        return embed



def _format_fixture_line(fixture: BrasileiraoFixture) -> str:
    return f"{_format_fixture_title(fixture)}\n{_format_fixture_details(fixture)}"


def _format_fixture_title(fixture: BrasileiraoFixture) -> str:
    return f"{fixture.home_team} {fixture.score_text} {fixture.away_team}"


def _format_fixture_details(fixture: BrasileiraoFixture, scorers: list[str] | None = None) -> str:
    status = fixture.status_long or fixture.status_short or "Status indisponível"
    elapsed = f" - {fixture.elapsed}'" if fixture.elapsed is not None else ""
    kickoff = ""
    if fixture.kickoff_at is not None and fixture.status_short == "NS":
        kickoff = f"\nInício: <t:{int(fixture.kickoff_at.timestamp())}:t>"
    scorers_line = f"\nGols:\n**{chr(10).join(scorers)}**" if scorers else ""
    return f"Status: **{status}{elapsed}**{kickoff}{scorers_line}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Libertadores(bot))
