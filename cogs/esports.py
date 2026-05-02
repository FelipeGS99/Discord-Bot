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
    PandaScoreGame,
    PandaScoreMatch,
    PandaScoreStateRepository,
    describe_match_update,
    deserialize_matches,
    game_snapshot_key,
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
    "valorant": EsportsGameConfig(
        key="valorant",
        title="Valorant",
        api_path="valorant",
        state_file="valorant_state.json",
        color=0xFF4655,
    ),
}


OFFICIAL_STREAMS = {
    "cblol": "https://www.youtube.com/@CBLOL",
    "lck": "https://www.youtube.com/@LCK",
    "lpl": "https://www.youtube.com/@LPL_English",
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
    "valorant": "https://www.youtube.com/@ValorantEsports",
    "vct": "https://www.youtube.com/@ValorantEsports",
    "challengers": "https://www.youtube.com/@ValorantEsports",
    "game changers": "https://www.youtube.com/@ValorantEsports",
}


class EsportsGameState:
    def __init__(self, base_path: Path, config: EsportsGameConfig) -> None:
        self.config = config
        self.repository = PandaScoreStateRepository(base_path / config.state_file)

        state = self.repository.load()
        self.channel_ids: list[int] = state["channel_ids"]
        self.match_snapshots: dict[str, str] = {
            str(key): str(value) for key, value in state["match_snapshots"].items()
        }
        self.game_snapshots: dict[str, str] = {
            str(key): str(value) for key, value in state["game_snapshots"].items()
        }
        self.tracked_matches: list[PandaScoreMatch] = deserialize_matches(state["tracked_matches"])

    def save(self) -> None:
        self.repository.save(
            self.channel_ids,
            self.match_snapshots,
            self.game_snapshots,
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
                    "Use `lol`, `cs2` e `valorant` separadamente para consultar partidas e ativar notificações em canais diferentes.",
                    f"`{prefix}lol` - Ajuda completa dos comandos de League of Legends.",
                    f"`{prefix}cs2` - Ajuda completa dos comandos de CS2.",
                    f"`{prefix}valorant` - Ajuda completa dos comandos de Valorant.",
                    f"`{prefix}lol hoje` - Mostra partidas de LoL de hoje.",
                    f"`{prefix}cs2 hoje` - Mostra partidas de CS2 de hoje.",
                    f"`{prefix}valorant hoje` - Mostra partidas de Valorant de hoje.",
                    f"`{prefix}lol canal #canal` - Ativa alertas de LoL. Exemplo: `{prefix}lol canal #lol`.",
                    f"`{prefix}cs2 canal #canal` - Ativa alertas de CS2. Exemplo: `{prefix}cs2 canal #cs2`.",
                    f"`{prefix}valorant canal #canal` - Ativa alertas de Valorant. Exemplo: `{prefix}valorant canal #valorant`.",
                ]
            )
        )

    @commands.group(name="lol", invoke_without_command=True)
    async def lol_group(self, ctx: commands.Context) -> None:
        await self._send_game_help(ctx, GAME_CONFIGS["lol"])

    @commands.group(name="cs2", aliases=["counterstrike"], invoke_without_command=True)
    async def cs2_group(self, ctx: commands.Context) -> None:
        await self._send_game_help(ctx, GAME_CONFIGS["cs2"])

    @commands.group(name="valorant", aliases=["val"], invoke_without_command=True)
    async def valorant_group(self, ctx: commands.Context) -> None:
        await self._send_game_help(ctx, GAME_CONFIGS["valorant"])

    @lol_group.command(name="canal")
    async def lol_set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._set_channel(ctx, GAME_CONFIGS["lol"], channel)

    @cs2_group.command(name="canal")
    async def cs2_set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._set_channel(ctx, GAME_CONFIGS["cs2"], channel)

    @valorant_group.command(name="canal")
    async def valorant_set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self._set_channel(ctx, GAME_CONFIGS["valorant"], channel)

    @lol_group.command(name="aovivo", aliases=["live"])
    async def lol_running(self, ctx: commands.Context) -> None:
        await self._send_running_matches(ctx, GAME_CONFIGS["lol"])

    @cs2_group.command(name="aovivo", aliases=["live"])
    async def cs2_running(self, ctx: commands.Context) -> None:
        await self._send_running_matches(ctx, GAME_CONFIGS["cs2"])

    @valorant_group.command(name="aovivo", aliases=["live"])
    async def valorant_running(self, ctx: commands.Context) -> None:
        await self._send_running_matches(ctx, GAME_CONFIGS["valorant"])

    @lol_group.command(name="hoje")
    async def lol_today(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["lol"], date.today(), "hoje")

    @cs2_group.command(name="hoje")
    async def cs2_today(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["cs2"], date.today(), "hoje")

    @valorant_group.command(name="hoje")
    async def valorant_today(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["valorant"], date.today(), "hoje")

    @lol_group.command(name="amanha")
    async def lol_tomorrow(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["lol"], date.today() + timedelta(days=1), "amanha")

    @cs2_group.command(name="amanha")
    async def cs2_tomorrow(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["cs2"], date.today() + timedelta(days=1), "amanha")

    @valorant_group.command(name="amanha")
    async def valorant_tomorrow(self, ctx: commands.Context) -> None:
        await self._send_matches_for_date(ctx, GAME_CONFIGS["valorant"], date.today() + timedelta(days=1), "amanha")

    @lol_group.command(name="status")
    async def lol_status(self, ctx: commands.Context) -> None:
        await self._send_status(ctx, GAME_CONFIGS["lol"])

    @cs2_group.command(name="status")
    async def cs2_status(self, ctx: commands.Context) -> None:
        await self._send_status(ctx, GAME_CONFIGS["cs2"])

    @valorant_group.command(name="status")
    async def valorant_status(self, ctx: commands.Context) -> None:
        await self._send_status(ctx, GAME_CONFIGS["valorant"])

    @lol_group.command(name="parar")
    async def lol_stop_alerts(self, ctx: commands.Context) -> None:
        await self._stop_alerts(ctx, GAME_CONFIGS["lol"])

    @cs2_group.command(name="parar")
    async def cs2_stop_alerts(self, ctx: commands.Context) -> None:
        await self._stop_alerts(ctx, GAME_CONFIGS["cs2"])

    @valorant_group.command(name="parar")
    async def valorant_stop_alerts(self, ctx: commands.Context) -> None:
        await self._stop_alerts(ctx, GAME_CONFIGS["valorant"])

    @lol_set_channel.error
    @cs2_set_channel.error
    @valorant_set_channel.error
    async def set_channel_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Informe o canal. Exemplo: `lol canal #placares`, `cs2 canal #placares` ou `valorant canal #placares`.")
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
                    "Os alertas avisam início de partida, início de mapas/jogos, mudança de placar/status e fim de partida.",
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
        live_matches = await self._fetch_live_matches(config)

        game_state = self.game_states[config.key]
        if channel.id not in game_state.channel_ids:
            game_state.channel_ids.append(channel.id)
        game_state.tracked_matches = running_matches[:MAX_TRACKED_MATCHES]
        for match in game_state.tracked_matches:
            game_state.match_snapshots.setdefault(str(match.match_id), match.snapshot_key)
        self._store_current_game_snapshots(game_state, live_matches)
        game_state.save()

        await ctx.send(
            f"Alertas de {config.title} ativados em {channel.mention}. "
            "Vou avisar quando partidas começarem, mapas/jogos começarem, terminarem ou mudarem de placar."
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
        if game_state.channel_ids:
            channel_mentions = []
            for channel_id in game_state.channel_ids:
                channel = self.bot.get_channel(channel_id)
                channel_mentions.append(channel.mention if isinstance(channel, discord.TextChannel) else f"`{channel_id}`")
            channel_text = ", ".join(channel_mentions)

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
        if ctx.channel.id in game_state.channel_ids:
            game_state.channel_ids.remove(ctx.channel.id)
        game_state.save()
        await ctx.send(f"Alertas de {config.title} desativados neste canal.")

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_esports_matches(self) -> None:
        if self.api_client is None:
            return

        live_matches = await self._fetch_live_matches()
        for config in GAME_CONFIGS.values():
            await self._check_game_matches(config, _filter_live_matches(live_matches, config))

    async def _check_game_matches(
        self,
        config: EsportsGameConfig,
        live_matches: list[PandaScoreMatch] | None = None,
    ) -> None:
        game_state = self.game_states[config.key]
        if not game_state.channel_ids:
            return

        try:
            running_matches = await self.api_client.fetch_running_matches(config.api_path)
        except Exception as exc:
            print(f"Erro ao buscar partidas ao vivo de {config.title} na PandaScore: {exc}")
            return
        if live_matches is None:
            live_matches = await self._fetch_live_matches(config)

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
            sent_channels = await self._send_to_alert_channels(
                game_state,
                config,
                self._build_match_update_embed(match, reason, config),
            )
            if config.key == "lol" and is_match_start:
                for channel in sent_channels:
                    await self._send_lol_composition_if_available(channel, match, config)

            game_state.match_snapshots[str(match.match_id)] = match.snapshot_key

        for match, game in _new_running_games(live_matches, game_state.game_snapshots):
            await self._send_to_alert_channels(
                game_state,
                config,
                self._build_game_update_embed(match, game, config),
            )

        game_state.tracked_matches = [
            match for match in matches_to_compare if not match.is_finished
        ][:MAX_TRACKED_MATCHES]
        tracked_match_ids = {str(match.match_id) for match in game_state.tracked_matches}
        game_state.match_snapshots = {
            match_id: snapshot
            for match_id, snapshot in game_state.match_snapshots.items()
            if match_id in tracked_match_ids
        }
        self._store_current_game_snapshots(game_state, live_matches)
        game_state.save()

    async def _fetch_live_matches(self, config: EsportsGameConfig | None = None) -> list[PandaScoreMatch]:
        if self.api_client is None:
            return []
        try:
            return await self.api_client.fetch_live_matches(config.api_path if config else None)
        except Exception as exc:
            game_name = config.title if config else "e-sports"
            print(f"Erro ao buscar lives de {game_name} na PandaScore: {exc}")
            return []

    @staticmethod
    def _store_current_game_snapshots(
        game_state: EsportsGameState,
        live_matches: list[PandaScoreMatch],
    ) -> None:
        live_match_ids = {match.match_id for match in live_matches}
        for match in live_matches:
            for game in match.games:
                game_state.game_snapshots[game_snapshot_key(match.match_id, game.position)] = game.status

        game_state.game_snapshots = {
            key: status
            for key, status in game_state.game_snapshots.items()
            if _snapshot_match_id(key) in live_match_ids
        }

    async def _send_to_alert_channels(
        self,
        game_state: EsportsGameState,
        config: EsportsGameConfig,
        embed: discord.Embed,
    ) -> list[discord.TextChannel]:
        sent_channels: list[discord.TextChannel] = []
        for channel_id in game_state.channel_ids:
            channel = self.bot.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                print(f"Canal de alertas de {config.title} não encontrado: {channel_id}")
                continue
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                print(f"Sem permissão para enviar alertas de {config.title} no canal {channel.id}.")
                continue
            except discord.HTTPException as exc:
                print(f"Erro ao enviar alerta de {config.title} no Discord: {exc}")
                continue
            sent_channels.append(channel)
        return sent_channels

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
        _add_stream_field(embed, match)
        return embed

    @staticmethod
    def _build_game_update_embed(
        match: PandaScoreMatch,
        game: PandaScoreGame,
        config: EsportsGameConfig,
    ) -> discord.Embed:
        author_name = _format_match_context(match, config)
        competition_name = _format_competition_name(match) or "Competição indisponível"
        label = _game_label(config)
        embed = discord.Embed(
            title=f"Início do {label} {game.position}",
            description=_format_game_update_details(match, game, config),
            color=_color_for_name(competition_name),
        )
        embed.set_author(name=author_name)
        if game.begin_at is not None:
            embed.timestamp = game.begin_at
        _add_stream_field(embed, match)
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


def _format_game_update_details(
    match: PandaScoreMatch,
    game: PandaScoreGame,
    config: EsportsGameConfig,
) -> str:
    label = _game_label(config)
    lines = [
        f"**{_format_match_title(match)}**",
        f"{label.capitalize()}: **{game.position}**",
        f"Status do {label}: **{_format_status(game.status)}**",
        f"Status da série: **{_format_status(match.status)}**",
    ]
    start_at = game.begin_at or match.begin_at or match.scheduled_at
    if start_at is not None:
        lines.append(f"Horário: <t:{int(start_at.timestamp())}:f>")
    if match.number_of_games is not None:
        lines.append(f"Formato: **{_format_match_format(match)}**")
    return "\n".join(lines)


def _game_label(config: EsportsGameConfig) -> str:
    if config.key in {"cs2", "valorant"}:
        return "mapa"
    return "jogo"


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


def _stream_link_for_match(match: PandaScoreMatch) -> tuple[str, str] | None:
    official_stream_url = _official_stream_url(match)
    if official_stream_url:
        return ("Transmissão oficial", official_stream_url)
    if match.stream_url:
        return ("Transmissão", match.stream_url)
    return None


def _add_stream_field(embed: discord.Embed, match: PandaScoreMatch) -> None:
    stream_link = _stream_link_for_match(match)
    if stream_link is None:
        return
    field_name, stream_url = stream_link
    embed.add_field(name=field_name, value=f"[Assistir]({stream_url})", inline=False)


def _new_running_games(
    live_matches: list[PandaScoreMatch],
    game_snapshots: dict[str, str],
) -> list[tuple[PandaScoreMatch, PandaScoreGame]]:
    new_running_games: list[tuple[PandaScoreMatch, PandaScoreGame]] = []
    for match in live_matches:
        for game in match.games:
            snapshot_key = game_snapshot_key(match.match_id, game.position)
            previous_status = game_snapshots.get(snapshot_key)
            if previous_status is None:
                continue
            if previous_status != "running" and game.status == "running" and game.position > 1:
                new_running_games.append((match, game))
    return new_running_games


def _filter_live_matches(
    live_matches: list[PandaScoreMatch],
    config: EsportsGameConfig,
) -> list[PandaScoreMatch]:
    return [
        match
        for match in live_matches
        if _match_belongs_to_config(match, config)
    ]


def _match_belongs_to_config(match: PandaScoreMatch, config: EsportsGameConfig) -> bool:
    videogame = match.videogame.lower()
    if config.api_path == "lol":
        return "league of legends" in videogame
    if config.api_path == "csgo":
        return "counter-strike" in videogame or "cs2" in videogame or "cs:go" in videogame
    if config.api_path == "valorant":
        return "valorant" in videogame
    return False


def _snapshot_match_id(snapshot_key: str) -> int | None:
    match_id_text, _separator, _position = snapshot_key.partition(":")
    try:
        return int(match_id_text)
    except ValueError:
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
