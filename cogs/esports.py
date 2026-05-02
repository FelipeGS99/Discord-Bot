from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks

from config import settings
from services.pandascore_service import (
    LolChampionPick,
    PandaScoreClient,
    PandaScoreMatch,
    PandaScoreStateRepository,
    describe_match_update,
    deserialize_matches,
    select_missing_running_match_ids,
    serialize_matches,
)


POLL_INTERVAL_MINUTES = 1
MAX_TRACKED_MATCHES = 100


@dataclass(frozen=True)
class EsportsGameConfig:
    key: str
    title: str
    api_path: str
    state_file: str
    color: int


GAME_CONFIGS = {
    "lol": EsportsGameConfig(
        key="lol",
        title="League of Legends",
        api_path="lol",
        state_file="lol_state.json",
        color=0x0AC8B9,
    ),
    "cs2": EsportsGameConfig(
        key="cs2",
        title="CS2",
        api_path="csgo",
        state_file="cs2_state.json",
        color=0xF0A202,
    ),
}


OFFICIAL_STREAMS = {
    "cblol": "https://www.youtube.com/@CBLOL",
    "lck": "https://www.youtube.com/@LCK",
    "lpl": "https://www.youtube.com/@lpl",
    "lec": "https://www.youtube.com/@LEC",
    "lcs": "https://www.youtube.com/@LCS",
    "lcp": "https://www.youtube.com/@lolesportspacific",
    "msi": "https://www.youtube.com/@lolesports",
    "worlds": "https://www.youtube.com/@lolesports",
    "first stand": "https://www.youtube.com/@lolesports",
    "esl": "https://www.twitch.tv/eslcs",
    "iem": "https://www.twitch.tv/eslcs",
    "blast": "https://www.twitch.tv/blastpremier",
    "pgl": "https://www.twitch.tv/pgl",
    "starladder": "https://www.twitch.tv/starladder_cs_en",
}


class EsportsGameState:
    def __init__(self, base_path: Path, config: EsportsGameConfig) -> None:
        self.config = config
        self.repository = PandaScoreStateRepository(base_path / config.state_file)

        state = self.repository.load()
        self.channel_id: int | None = state["channel_id"]
        self.match_snapshots: dict[str, str] = {
            str(key): str(value) for key, value in state["match_snapshots"].items()
        }
        self.tracked_matches: list[PandaScoreMatch] = deserialize_matches(state["tracked_matches"])

    def save(self) -> None:
        self.repository.save(
            self.channel_id,
            self.match_snapshots,
            serialize_matches(self.tracked_matches),
        )


class Esports(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.base_path = Path(__file__).resolve().parent.parent
        self.api_client = PandaScoreClient(settings.pandascore_api_token) if settings.pandascore_api_token else None
        self.game_states = {
            key: EsportsGameState(self.base_path, config)
            for key, config in GAME_CONFIGS.items()
        }

        self.check_esports_matches.start()

    async def cog_unload(self) -> None:
        self.check_esports_matches.cancel()

    @commands.group(name="esports", aliases=["esportes"], invoke_without_command=True)
    async def esports_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "\n".join(
                [
                    "**E-sports**",
                    "Use `lol` e `cs2` separadamente para consultar partidas e ativar notificações em canais diferentes.",
                    f"`{prefix}lol` - Ajuda completa dos comandos de League of Legends.",
                    f"`{prefix}cs2` - Ajuda completa dos comandos de CS2.",
                    f"`{prefix}lol hoje` - Mostra partidas de LoL de hoje.",
                    f"`{prefix}cs2 hoje` - Mostra partidas de CS2 de hoje.",
                    f"`{prefix}lol canal #canal` - Ativa alertas de LoL. Exemplo: `{prefix}lol canal #lol`.",
                    f"`{prefix}cs2 canal #canal` - Ativa alertas de CS2. Exemplo: `{prefix}cs2 canal #cs2`.",
                ]
            )
        )

    @commands.group(name="lol", invoke_without_command=True)
    async def lol_group(self, ctx: commands.Context) -> None:
        await self._send_game_help(ctx, GAME_CONFIGS["lol"])

    @commands.group(name="cs2", aliases=["counterstrike"], invoke_without_command=True)
    async def cs2_group(self, ctx: commands.Context) -> None:
        await self._send_game_help(ctx, GAME_CONFIGS["cs2"])

    @lol_group.command(name="canal")
    async def lol_set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._set_channel(ctx, GAME_CONFIGS["lol"], channel)

    @cs2_group.command(name="canal")
    async def cs2_set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._set_channel(ctx, GAME_CONFIGS["cs2"], channel)

    @lol_group.command(name="aovivo", aliases=["live"])
    async def lol_running(self, ctx: commands.Context) -> None:
        await self._send_running_matches(ctx, GAME_CONFIGS["lol"])

    @cs2_group.command(name="aovivo", aliases=["live"])
    async def cs2_running(self, ctx: commands.Context) -> None:
        await self._send_running_matches(ctx, GAME_CONFIGS["cs2"])

    @lol_group.command(name="hoje")
    async def lol_today(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["lol"], date.today(), "hoje")

    @cs2_group.command(name="hoje")
    async def cs2_today(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["cs2"], date.today(), "hoje")

    @lol_group.command(name="amanha")
    async def lol_tomorrow(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["lol"], date.today() + timedelta(days=1), "amanha")

    @cs2_group.command(name="amanha")
    async def cs2_tomorrow(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["cs2"], date.today() + timedelta(days=1), "amanha")

    @lol_group.command(name="status")
    async def lol_status(self, ctx: commands.Context) -> None:
        await self._send_status(ctx, GAME_CONFIGS["lol"])

    @cs2_group.command(name="status")
    async def cs2_status(self, ctx: commands.Context) -> None:
        await self._send_status(ctx, GAME_CONFIGS["cs2"])

    @lol_group.command(name="parar")
    async def lol_stop_alerts(self, ctx: commands.Context) -> None:
        await self._stop_alerts(ctx, GAME_CONFIGS["lol"])

    @cs2_group.command(name="parar")
    async def cs2_stop_alerts(self, ctx: commands.Context) -> None:
        await self._stop_alerts(ctx, GAME_CONFIGS["cs2"])

    @lol_set_channel.error
    @cs2_set_channel.error
    async def set_channel_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Informe o canal. Exemplo: `lol canal #placares` ou `cs2 canal #placares`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("Canal invalido. Marque um canal de texto valido.")
            return
        raise error

    async def _send_game_help(self, ctx: commands.Context, config: EsportsGameConfig) -> None:
        prefix = ctx.prefix or "?"
        await ctx.send(
            "\n".join(
                [
                    f"**{config.title}**",
                    "Use para consultar partidas e receber alertas automáticos desse jogo.",
                    f"`{prefix}{config.key} aovivo` - Mostra partidas ao vivo com placar, status e competição.",
                    f"`{prefix}{config.key} hoje` - Mostra partidas de hoje com horário, placar, status e competição.",
                    f"`{prefix}{config.key} amanha` - Mostra partidas de amanhã.",
                    f"`{prefix}{config.key} canal #canal` - Ativa alertas neste canal. Exemplo: `{prefix}{config.key} canal #placares`.",
                    f"`{prefix}{config.key} status` - Mostra canal configurado, API e partidas sendo monitoradas.",
                    f"`{prefix}{config.key} parar` - Desativa os alertas automáticos desse jogo.",
                    "Os alertas avisam início de partida, mudança de placar/status e fim de partida.",
                ]
            )
        )

    async def _set_channel(
        self,
        ctx: commands.Context,
        config: EsportsGameConfig,
        channel: discord.TextChannel,
    ) -> None:
        if not self._can_manage_esports(ctx):
            await ctx.send(f"Voce nao tem permissao para configurar os alertas de {config.title}.")
            return
        if self.api_client is None:
            await ctx.send("A variavel PANDASCORE_API_TOKEN nao foi definida no .env.")
            return

        try:
            running_matches = await self.api_client.fetch_running_matches(config.api_path)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a PandaScore agora: {exc}")
            return

        game_state = self.game_states[config.key]
        game_state.channel_id = channel.id
        game_state.tracked_matches = running_matches[:MAX_TRACKED_MATCHES]
        game_state.match_snapshots = {
            str(match.match_id): match.snapshot_key for match in game_state.tracked_matches
        }
        game_state.save()

        await ctx.send(
            f"Alertas de {config.title} ativados em {channel.mention}. "
            "Vou avisar quando partidas começarem, terminarem ou mudarem de placar."
        )

    async def _send_running_matches(self, ctx: commands.Context, config: EsportsGameConfig) -> None:
        if self.api_client is None:
            await ctx.send("A variavel PANDASCORE_API_TOKEN nao foi definida no .env.")
            return

        try:
            matches = await self.api_client.fetch_running_matches(config.api_path)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a PandaScore agora: {exc}")
            return

        if not matches:
            await ctx.send(f"Nao encontrei partidas de {config.title} ao vivo agora.")
            return

        await _send_embeds(ctx, self._build_matches_embeds(f"{config.title} ao vivo", matches[:10], config))

    async def _send_matches_for_date(
        self,
        ctx: commands.Context,
        config: EsportsGameConfig,
        match_date: date,
        label: str,
    ) -> None:
        if self.api_client is None:
            await ctx.send("A variavel PANDASCORE_API_TOKEN nao foi definida no .env.")
            return

        try:
            matches = await self.api_client.fetch_matches_for_date(config.api_path, match_date)
        except Exception as exc:
            await ctx.send(f"Nao consegui consultar a PandaScore agora: {exc}")
            return

        if not matches:
            await ctx.send(f"Nao encontrei partidas de {config.title} para {label}.")
            return

        await _send_embeds(ctx, self._build_matches_embeds(f"{config.title} - {label}", matches, config))

    async def _send_status(self, ctx: commands.Context, config: EsportsGameConfig) -> None:
        game_state = self.game_states[config.key]
        channel_text = "desativado"
        if game_state.channel_id is not None:
            channel = self.bot.get_channel(game_state.channel_id)
            channel_text = channel.mention if isinstance(channel, discord.TextChannel) else f"`{game_state.channel_id}`"

        await ctx.send(
            "\n".join(
                [
                    f"**{config.title}**",
                    f"Canal: {channel_text}",
                    f"API key: {'configurada' if self.api_client else 'ausente'}",
                    f"Intervalo ao vivo: {POLL_INTERVAL_MINUTES} minutos",
                    f"Partidas monitoradas: {len(game_state.tracked_matches)}",
                ]
            )
        )

    async def _stop_alerts(self, ctx: commands.Context, config: EsportsGameConfig) -> None:
        if not self._can_manage_esports(ctx):
            await ctx.send(f"Voce nao tem permissao para configurar os alertas de {config.title}.")
            return

        game_state = self.game_states[config.key]
        game_state.channel_id = None
        game_state.save()
        await ctx.send(f"Alertas de {config.title} desativados.")

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_esports_matches(self) -> None:
        if self.api_client is None:
            return

        for config in GAME_CONFIGS.values():
            await self._check_game_matches(config)

    async def _check_game_matches(self, config: EsportsGameConfig) -> None:
        game_state = self.game_states[config.key]
        if game_state.channel_id is None:
            return

        channel = self.bot.get_channel(game_state.channel_id)
        if not isinstance(channel, discord.TextChannel):
            print(f"Canal de alertas de {config.title} nao encontrado: {game_state.channel_id}")
            return

        try:
            running_matches = await self.api_client.fetch_running_matches(config.api_path)
        except Exception as exc:
            print(f"Erro ao buscar partidas ao vivo de {config.title} na PandaScore: {exc}")
            return

        matches_to_compare = list(running_matches)
        missing_running_ids = select_missing_running_match_ids(game_state.tracked_matches, running_matches)
        for match_id in missing_running_ids:
            try:
                match = await self.api_client.fetch_match(match_id)
            except Exception as exc:
                print(f"Erro ao buscar partida {match_id} na PandaScore: {exc}")
                continue
            if match is not None:
                matches_to_compare.append(match)

        changed_matches = [
            match
            for match in matches_to_compare
            if game_state.match_snapshots.get(str(match.match_id)) != match.snapshot_key
        ]

        for match in changed_matches:
            previous_snapshot = game_state.match_snapshots.get(str(match.match_id))
            is_match_start = match.is_running and (
                not previous_snapshot or not previous_snapshot.startswith("running|")
            )
            reason = describe_match_update(match, game_state.match_snapshots.get(str(match.match_id)))
            try:
                await channel.send(embed=self._build_match_update_embed(match, reason, config))
                if config.key == "lol" and is_match_start:
                    await self._send_lol_composition_if_available(channel, match, config)
            except discord.Forbidden:
                print(f"Sem permissao para enviar alertas de {config.title} no canal {channel.id}.")
                return
            except discord.HTTPException as exc:
                print(f"Erro ao enviar alerta de {config.title} no Discord: {exc}")
                return

            game_state.match_snapshots[str(match.match_id)] = match.snapshot_key

        game_state.tracked_matches = [
            match for match in matches_to_compare if not match.is_finished
        ][:MAX_TRACKED_MATCHES]
        tracked_match_ids = {str(match.match_id) for match in game_state.tracked_matches}
        game_state.match_snapshots = {
            match_id: snapshot
            for match_id, snapshot in game_state.match_snapshots.items()
            if match_id in tracked_match_ids
        }
        game_state.save()

    async def _send_lol_composition_if_available(
        self,
        channel: discord.TextChannel,
        match: PandaScoreMatch,
        config: EsportsGameConfig,
    ) -> None:
        if self.api_client is None:
            return

        try:
            champion_picks = await self.api_client.fetch_lol_match_champion_picks(match.match_id)
        except RuntimeError as exc:
            if "plano da PandaScore" not in str(exc):
                print(f"Erro ao buscar composição de LoL: {exc}")
            return
        except Exception as exc:
            print(f"Erro ao buscar composição de LoL: {exc}")
            return

        if not champion_picks:
            return

        try:
            await channel.send(embed=_build_lol_composition_embed(match, champion_picks, config))
        except discord.Forbidden:
            print(f"Sem permissão para enviar composição de LoL no canal {channel.id}.")
        except discord.HTTPException as exc:
            print(f"Erro ao enviar composição de LoL no Discord: {exc}")

    @check_esports_matches.before_loop
    async def before_check_esports_matches(self) -> None:
        await self.bot.wait_until_ready()

    @staticmethod
    def _can_manage_esports(ctx: commands.Context) -> bool:
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
    def _build_matches_embeds(
        title: str,
        matches: list[PandaScoreMatch],
        config: EsportsGameConfig,
    ) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []
        for competition_name, competition_matches in _group_matches_by_competition(matches).items():
            value = "\n\n".join(
                _format_grouped_match(match)
                for match in competition_matches
            )
            embed = discord.Embed(
                title=competition_name[:256],
                description=value[:3800],
                color=_color_for_name(competition_name),
            )
            embed.set_author(name=title)
            embeds.append(embed)
        return embeds

    @staticmethod
    def _build_match_update_embed(
        match: PandaScoreMatch,
        reason: str,
        config: EsportsGameConfig,
    ) -> discord.Embed:
        author_name = _format_match_context(match, config)
        competition_name = _format_competition_name(match) or "Competição indisponível"
        embed = discord.Embed(
            title=reason,
            description=_format_match_update_details(match),
            color=_color_for_name(competition_name),
        )
        embed.set_author(name=author_name)
        if match.begin_at is not None:
            embed.timestamp = match.begin_at
        official_stream_url = _official_stream_url(match)
        if official_stream_url:
            embed.add_field(name="Transmissão oficial", value=f"[Assistir]({official_stream_url})", inline=False)
        return embed


def _format_match_title(match: PandaScoreMatch) -> str:
    first, second = match.opponents
    return f"{first} {match.score_text} {second}"


def _format_match_context(match: PandaScoreMatch, config: EsportsGameConfig) -> str:
    competition_name = _format_competition_name(match) or "Competição indisponível"
    if competition_name:
        return f"{config.title} - {competition_name}"
    return config.title


def _format_competition_name(match: PandaScoreMatch) -> str:
    return _join_nonempty([match.league, match.serie, match.tournament])


def _format_match_update_details(match: PandaScoreMatch) -> str:
    lines = [
        f"**{_format_match_title(match)}**",
        f"Status: **{_format_status(match.status)}**",
    ]
    start_at = match.begin_at or match.scheduled_at
    if start_at is not None:
        lines.append(f"Horário: <t:{int(start_at.timestamp())}:f>")
    if match.number_of_games is not None:
        lines.append(f"Formato: **{_format_match_format(match)}**")
    return "\n".join(lines)


def _build_lol_composition_embed(
    match: PandaScoreMatch,
    champion_picks: list[LolChampionPick],
    config: EsportsGameConfig,
) -> discord.Embed:
    author_name = _format_match_context(match, config)
    competition_name = _format_competition_name(match)
    grouped_picks: dict[str, list[LolChampionPick]] = {}
    for pick in champion_picks:
        grouped_picks.setdefault(pick.team_name, []).append(pick)

    embed = discord.Embed(
        title="Composição dos times",
        color=_color_for_name(competition_name),
    )
    embed.set_author(name=author_name)
    for team_name, picks in grouped_picks.items():
        lines = [
            _format_champion_pick(pick)
            for pick in picks
        ]
        embed.add_field(name=team_name[:256], value="\n".join(lines)[:1024], inline=False)
    return embed


def _format_champion_pick(pick: LolChampionPick) -> str:
    role = f"{pick.role}: " if pick.role else ""
    return f"**{role}{pick.player_name}** - {pick.champion_name}"


def _format_match_details(match: PandaScoreMatch) -> str:
    lines = [
        f"Status: **{_format_status(match.status)}**",
        f"Competição: **{_join_nonempty([match.league, match.serie, match.tournament]) or 'Indisponível'}**",
    ]
    start_at = match.begin_at or match.scheduled_at
    if start_at is not None:
        lines.append(f"Horário: <t:{int(start_at.timestamp())}:f>")
    if match.number_of_games is not None:
        lines.append(f"Formato: **{_format_match_format(match)}**")
    return "\n".join(lines)


def _format_grouped_match(match: PandaScoreMatch) -> str:
    start_at = match.begin_at or match.scheduled_at
    time_text = f"<t:{int(start_at.timestamp())}:t>" if start_at is not None else "Horário indefinido"
    first, second = match.opponents
    lines = [
        f"{time_text} **{first} {match.score_text} {second}**",
        f"Status: {_format_status(match.status)}",
    ]
    if match.number_of_games is not None:
        lines.append(f"Formato: {_format_match_format(match)}")
    return "\n".join(lines)


def _format_match_format(match: PandaScoreMatch) -> str:
    if match.match_type == "best_of":
        return f"Melhor de {match.number_of_games}"
    if match.match_type == "first_to":
        return f"Primeiro a {match.number_of_games}"
    return f"{match.match_type or 'partida'} {match.number_of_games}"


def _group_matches_by_competition(matches: list[PandaScoreMatch]) -> dict[str, list[PandaScoreMatch]]:
    grouped_matches: dict[str, list[PandaScoreMatch]] = {}
    for match in matches:
        competition_name = _format_competition_name(match) or "Competição indisponível"
        grouped_matches.setdefault(competition_name, []).append(match)

    return {
        competition_name: sorted(
            competition_matches,
            key=lambda item: item.begin_at or item.scheduled_at,
        )
        for competition_name, competition_matches in sorted(grouped_matches.items())
    }


def _format_status(status: str) -> str:
    labels = {
        "not_started": "Não iniciada",
        "running": "Ao vivo",
        "finished": "Encerrada",
        "canceled": "Cancelada",
        "postponed": "Adiada",
    }
    return labels.get(status, status or "Indisponível")


def _join_nonempty(values: list[str]) -> str:
    return " - ".join(value for value in values if value)


def _official_stream_url(match: PandaScoreMatch) -> str | None:
    competition_text = " ".join(
        value.lower()
        for value in (match.league, match.serie, match.tournament)
        if value
    )
    for keyword, url in OFFICIAL_STREAMS.items():
        if keyword in competition_text:
            return url
    return None


def _color_for_name(name: str) -> int:
    palette = (
        0x00B8A9,
        0xF6416C,
        0xFFDE7D,
        0x6A67CE,
        0x43D9AD,
        0xFF9F1C,
        0x2F80ED,
        0xEB5757,
        0x27AE60,
        0xBB6BD9,
    )
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return palette[int.from_bytes(digest[:2], "big") % len(palette)]


async def _send_embeds(ctx: commands.Context, embeds: list[discord.Embed]) -> None:
    for index in range(0, len(embeds), 10):
        await ctx.send(embeds=embeds[index:index + 10])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Esports(bot))
