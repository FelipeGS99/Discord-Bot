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
    select_current_round_fixtures,
    select_next_round_fixtures,
    select_previous_round_fixtures,
    serialize_fixtures,
    should_monitor_fixtures,
)


POLL_INTERVAL_MINUTES = 1
EMBED_COLOR = 0x009C3B


class Brasileirao(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        state_path = Path(__file__).resolve().parent.parent / "brasileirao_state.json"
        self.state_repository = BrasileiraoStateRepository(state_path)
        self.api_client = ApiFootballClient(settings.bsd_api_key) if settings.bsd_api_key else None
        self.league_id = settings.brasileirao_league_id

        state = self.state_repository.load()
        self.channel_ids: list[int] = state["channel_ids"]
        self.checked_date: str | None = state["checked_date"]
        self.fixture_snapshots: dict[str, str] = {
            str(key): str(value) for key, value in state["fixture_snapshots"].items()
        }
        self.fixtures_today: list[BrasileiraoFixture] = deserialize_fixtures(state["fixtures_today"])

        # Periodic polling is centralized in cogs.futebol to avoid duplicate API calls.

    async def cog_unload(self) -> None:
        self.check_brasileirao_scores.cancel()

    @commands.group(name="brasileirao", invoke_without_command=True)
    async def brasileirao_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "\n".join(
                [
                    "**BrasileirÃ£o SÃ©rie A**",
                    "Use para consultar jogos e configurar alertas automÃ¡ticos do BrasileirÃ£o.",
                    f"`{prefix}brasileirao hoje` - Mostra jogos de hoje com horÃ¡rio, placar, status e gols quando disponÃ­vel.",
                    f"`{prefix}brasileirao atual` - Mostra a rodada atual do campeonato.",
                    f"`{prefix}brasileirao proxima` - Mostra a prÃ³xima rodada.",
                    f"`{prefix}brasileirao passada` - Mostra a rodada anterior.",
                    f"`{prefix}brasileirao canal #canal` - Ativa alertas de inÃ­cio, gol, intervalo, volta de status e fim de jogo. Exemplo: `{prefix}brasileirao canal #placares`.",
                    f"`{prefix}brasileirao status` - Mostra canal configurado, API, liga e cache atual.",
                    f"`{prefix}brasileirao parar` - Desativa os alertas automÃ¡ticos do BrasileirÃ£o.",
                ]
            )
        )

    @brasileirao_group.command(name="canal")
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        if not self._can_manage_scores(ctx):
            await ctx.send("Voce nao tem permissao para configurar os placares do Brasileirao.")
            return
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        if channel.id not in self.channel_ids:
            self.channel_ids.append(channel.id)
        await self._refresh_today_fixtures(force=True)
        self.fixture_snapshots = {
            str(fixture.fixture_id): fixture.snapshot_key for fixture in self.fixtures_today
        }
        self._save_state()

        await ctx.send(
            f"Placares do Brasileirao ativados em {channel.mention}. "
            "Vou avisar quando houver mudanca de status ou placar."
        )

    @brasileirao_group.command(name="hoje")
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
            await ctx.send("Nao encontrei jogos do Brasileirao Serie A para hoje.")
            return

        scorers_by_fixture = await self._fetch_goal_scorers_by_fixture(fixtures)
        await ctx.send(embed=self._build_today_embed(fixtures, scorers_by_fixture))

    @brasileirao_group.command(name="atual")
    async def current_round(self, ctx: commands.Context) -> None:
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        try:
            fixtures = await self.api_client.fetch_season_fixtures(self.league_id)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a BSD agora: {exc}")
            return

        round_fixtures = select_current_round_fixtures(fixtures)
        if not round_fixtures:
            await ctx.send("Nao encontrei a rodada atual do Brasileirao Serie A.")
            return

        await ctx.send(embed=self._build_round_embed(round_fixtures, "rodada atual"))

    @brasileirao_group.command(name="passada")
    async def previous_round(self, ctx: commands.Context) -> None:
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        try:
            fixtures = await self.api_client.fetch_season_fixtures(self.league_id)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a BSD agora: {exc}")
            return

        round_fixtures = select_previous_round_fixtures(fixtures)
        if not round_fixtures:
            await ctx.send("Nao encontrei a rodada passada do Brasileirao Serie A.")
            return

        await ctx.send(embed=self._build_round_embed(round_fixtures, "rodada passada"))

    @brasileirao_group.command(name="proxima")
    async def next_round(self, ctx: commands.Context) -> None:
        if self.api_client is None:
            await ctx.send("A variavel BSD_API_KEY nao foi definida no .env.")
            return

        try:
            fixtures = await self.api_client.fetch_season_fixtures(self.league_id)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a BSD agora: {exc}")
            return

        round_fixtures = select_next_round_fixtures(fixtures)
        if not round_fixtures:
            await ctx.send("Nao encontrei a proxima rodada do Brasileirao Serie A.")
            return

        await ctx.send(embed=self._build_round_embed(round_fixtures, "proxima rodada"))

    @brasileirao_group.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        channel_text = "desativado"
        if self.channel_ids:
            channel_mentions = []
            for channel_id in self.channel_ids:
                channel = self.bot.get_channel(channel_id)
                channel_mentions.append(channel.mention if isinstance(channel, discord.TextChannel) else f"`{channel_id}`")
            channel_text = ", ".join(channel_mentions)

        await ctx.send(
            "\n".join(
                [
                    "**Brasileirao Serie A**",
                    f"Canal: {channel_text}",
                    f"API key: {'configurada' if self.api_client else 'ausente'}",
                    f"Liga: `{self.league_id}`",
                    f"Intervalo ao vivo: {POLL_INTERVAL_MINUTES} minutos",
                    f"Data em cache: `{self.checked_date or 'nenhuma'}`",
                    f"Jogos em cache: {len(self.fixtures_today)}",
                ]
            )
        )

    @brasileirao_group.command(name="parar")
    async def stop_scores(self, ctx: commands.Context) -> None:
        if not self._can_manage_scores(ctx):
            await ctx.send("Voce nao tem permissao para configurar os placares do Brasileirao.")
            return

        if ctx.channel.id in self.channel_ids:
            self.channel_ids.remove(ctx.channel.id)
        self._save_state()
        await ctx.send("Placares do Brasileirao desativados neste canal.")

    @set_channel.error
    async def set_channel_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Informe o canal. Exemplo: `brasileirao canal #placares`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("Canal invalido. Marque um canal de texto valido.")
            return
        raise error

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_brasileirao_scores(self) -> None:
        if not self.channel_ids or self.api_client is None:
            return

        try:
            fixtures = await self._fetch_live_fixtures()
        except Exception as exc:
            print(f"Erro ao atualizar placares ao vivo do Brasileirao: {exc}")
            return

        if not fixtures:
            had_live_snapshot = any(fixture.is_live for fixture in self.fixtures_today)
            try:
                fixtures = await self._refresh_today_fixtures(force=had_live_snapshot)
            except Exception as exc:
                print(f"Erro ao consultar placares do Brasileirao: {exc}")
                return
            if not had_live_snapshot and not should_monitor_fixtures(fixtures):
                return
            try:
                live_fixtures = await self._fetch_live_fixtures()
            except Exception as exc:
                print(f"Erro ao atualizar placares ao vivo do Brasileirao: {exc}")
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
                await self._send_score_to_channels(self._build_score_embed(fixture, scorers, reason))
            except discord.Forbidden:
                print("Sem permissao para enviar placares do Brasileirao.")
                return
            except discord.HTTPException as exc:
                print(f"Erro ao enviar placar no Discord: {exc}")
                return

            self.fixture_snapshots[str(fixture.fixture_id)] = fixture.snapshot_key
            self._save_state()

    async def _send_score_to_channels(self, embed: discord.Embed) -> None:
        for channel_id in self.channel_ids:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                print(f"Canal de placares do Brasileirao nao encontrado: {channel_id}")
                continue
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                print(f"Sem permissao para enviar placares no canal {channel.id}.")
                continue
            except discord.HTTPException as exc:
                print(f"Erro ao enviar placar no Discord: {exc}")
                continue

    @check_brasileirao_scores.before_loop
    async def before_check_brasileirao_scores(self) -> None:
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
            print(f"Erro ao buscar autores dos gols do Brasileirao: {exc}")
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
            self.channel_ids,
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
            title="BrasileirÃ£o SÃ©rie A - jogos de hoje",
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
    def _build_round_embed(fixtures: list[BrasileiraoFixture], label: str) -> discord.Embed:
        round_number = fixtures[0].round_number
        title = f"BrasileirÃ£o SÃ©rie A - {label}"
        if round_number is not None:
            title = f"{title} {round_number}"

        embed = discord.Embed(title=title, color=EMBED_COLOR)
        for fixture in fixtures:
            embed.add_field(
                name=_format_fixture_title(fixture),
                value=_format_fixture_details(fixture),
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
        embed.set_author(name="BrasileirÃ£o SÃ©rie A")
        if scorers:
            embed.add_field(name="Gols", value="\n".join(scorers), inline=False)
        return embed



def _format_fixture_line(fixture: BrasileiraoFixture) -> str:
    return f"{_format_fixture_title(fixture)}\n{_format_fixture_details(fixture)}"


def _format_fixture_title(fixture: BrasileiraoFixture) -> str:
    return f"{fixture.home_team} {fixture.score_text} {fixture.away_team}"


def _format_fixture_details(fixture: BrasileiraoFixture, scorers: list[str] | None = None) -> str:
    status = fixture.status_long or fixture.status_short or "Status indisponÃ­vel"
    elapsed = f" - {fixture.elapsed}'" if fixture.elapsed is not None else ""
    kickoff = f"\nData: <t:{int(fixture.kickoff_at.timestamp())}:f>" if fixture.kickoff_at is not None else ""
    scorers_line = f"\nGols:\n**{chr(10).join(scorers)}**" if scorers else ""
    return f"Status: **{status}{elapsed}**{kickoff}{scorers_line}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Brasileirao(bot))


