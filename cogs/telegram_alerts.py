from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from discord.ext import commands, tasks

from config import settings
from cogs.esports import GAME_CONFIGS, _new_running_games, _stream_link_for_match
from cogs.futebol import COMPETITIONS
from services.brasileirao_service import (
    ApiFootballClient,
    BrasileiraoFixture,
    describe_fixture_update,
    deserialize_fixtures,
    select_missing_live_fixture_ids,
    serialize_fixtures,
    should_monitor_fixtures,
)
from services.pandascore_service import (
    PandaScoreClient,
    PandaScoreGame,
    PandaScoreMatch,
    describe_match_update,
    deserialize_matches,
    game_snapshot_key,
    select_missing_running_match_ids,
    serialize_matches,
)
from services.telegram_service import TelegramClient, TelegramMessage, TelegramStateRepository


COMMANDS = {
    "futebol": "Futebol",
    "lol": "League of Legends",
    "valorant": "Valorant",
    "cs2": "CS2",
}
TELEGRAM_POLL_SECONDS = 5
SCORE_POLL_MINUTES = 1
MAX_TRACKED_MATCHES = 100
TELEGRAM_HTML_PARSE_MODE = "HTML"
ESPORTS_STATUS_LABELS = {
    "not_started": "Não iniciada",
    "notstarted": "Não iniciada",
    "not_started_yet": "Não iniciada",
    "running": "Ao vivo",
    "finished": "Encerrada",
    "canceled": "Cancelada",
    "cancelled": "Cancelada",
    "postponed": "Adiada",
    "delayed": "Atrasada",
}


class TelegramAlerts(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.base_path = Path(__file__).resolve().parent.parent
        self.telegram_client = TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
        self.football_client = ApiFootballClient(settings.bsd_api_key) if settings.bsd_api_key else None
        self.pandascore_client = PandaScoreClient(settings.pandascore_api_token) if settings.pandascore_api_token else None
        self.repository = TelegramStateRepository(self.base_path / "telegram_state.json")
        self.state = self.repository.load()

        self.poll_telegram_commands.start()
        self.check_telegram_scores.start()

    async def cog_unload(self) -> None:
        self.poll_telegram_commands.cancel()
        self.check_telegram_scores.cancel()

    @tasks.loop(seconds=TELEGRAM_POLL_SECONDS)
    async def poll_telegram_commands(self) -> None:
        if self.telegram_client is None:
            return

        try:
            updates = await self.telegram_client.fetch_updates(self.state.get("update_offset"))
        except Exception as exc:
            print(f"Erro ao buscar mensagens do Telegram: {exc}")
            return

        for update in updates:
            await self._handle_telegram_message(update)
            self.state["update_offset"] = update.update_id + 1

        if updates:
            self._save_state()

    @poll_telegram_commands.before_loop
    async def before_poll_telegram_commands(self) -> None:
        await self.bot.wait_until_ready()

    async def _handle_telegram_message(self, message: TelegramMessage) -> None:
        command = _normalize_command(message.text)
        if command in {"start", "help", "ajuda"}:
            await self._send_telegram_message(message.chat_id, _help_text())
            return
        if command in COMMANDS:
            await self._subscribe(message.chat_id, command)
            return
        if command.startswith("parar"):
            await self._unsubscribe(message.chat_id, command)
            return
        if command == "status":
            await self._send_telegram_message(message.chat_id, self._status_text(message.chat_id))
            return
        await self._send_telegram_message(message.chat_id, _help_text())

    async def _subscribe(self, chat_id: int, sport: str) -> None:
        subscriptions = self.state["subscriptions"][sport]
        if chat_id not in subscriptions:
            subscriptions.append(chat_id)

        if sport == "futebol":
            await self._prime_football_state()
        else:
            await self._prime_esports_state(sport)

        self._save_state()
        await self._send_telegram_message(
            chat_id,
            f"Alertas de {COMMANDS[sport]} ativados neste chat.",
        )

    async def _unsubscribe(self, chat_id: int, command: str) -> None:
        parts = command.split()
        targets = list(COMMANDS) if len(parts) == 1 or parts[1] in {"todos", "tudo"} else [parts[1]]
        removed: list[str] = []
        for sport in targets:
            if sport not in COMMANDS:
                continue
            subscriptions = self.state["subscriptions"][sport]
            if chat_id in subscriptions:
                subscriptions.remove(chat_id)
                removed.append(COMMANDS[sport])

        self._save_state()
        if removed:
            await self._send_telegram_message(chat_id, f"Alertas desativados: {', '.join(removed)}.")
        else:
            await self._send_telegram_message(chat_id, "Este chat nao tinha alertas ativos para esse comando.")

    def _status_text(self, chat_id: int) -> str:
        active = [
            label
            for key, label in COMMANDS.items()
            if chat_id in self.state["subscriptions"][key]
        ]
        if not active:
            return "Nenhum alerta ativo neste chat."
        return "Alertas ativos neste chat: " + ", ".join(active)

    @tasks.loop(minutes=SCORE_POLL_MINUTES)
    async def check_telegram_scores(self) -> None:
        if self.telegram_client is None:
            return
        await self._check_football_scores()
        await self._check_esports_scores()
        self._save_state()

    @check_telegram_scores.before_loop
    async def before_check_telegram_scores(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_football_scores(self) -> None:
        chat_ids = self.state["subscriptions"]["futebol"]
        if not chat_ids or self.football_client is None:
            return

        try:
            all_live_fixtures = await self.football_client.fetch_all_live_fixtures()
        except Exception as exc:
            print(f"Erro ao buscar placares de futebol para Telegram: {exc}")
            return

        for competition_name, _author, setting_name, _state_name, _color in COMPETITIONS:
            league_id = getattr(settings, setting_name)
            live_fixtures = [fixture for fixture in all_live_fixtures if fixture.league_id == league_id]
            await self._process_football_competition(chat_ids, competition_name, league_id, live_fixtures)

    async def _process_football_competition(
        self,
        chat_ids: list[int],
        competition_name: str,
        league_id: int,
        live_fixtures: list[BrasileiraoFixture],
    ) -> None:
        football_state = self.state["football"]
        checked_dates = football_state["checked_dates"]
        snapshots_by_competition = football_state["fixture_snapshots"].setdefault(competition_name, {})
        fixtures_by_competition = football_state["fixtures_today"].setdefault(competition_name, [])
        fixtures_today = deserialize_fixtures(fixtures_by_competition)
        fixtures_to_compare = list(live_fixtures)

        if fixtures_to_compare:
            missing_live_fixture_ids = select_missing_live_fixture_ids(fixtures_today, live_fixtures)
            if missing_live_fixture_ids:
                try:
                    fixtures_today = await self.football_client.fetch_fixtures(league_id, date.today())
                except Exception as exc:
                    print(f"Erro ao consultar jogos em intervalo de {competition_name} para Telegram: {exc}")
                    return
                live_fixture_ids = {fixture.fixture_id for fixture in live_fixtures}
                tracked_updates = [
                    fixture
                    for fixture in fixtures_today
                    if fixture.fixture_id in missing_live_fixture_ids and fixture.fixture_id not in live_fixture_ids
                ]
                fixtures_to_compare = live_fixtures + tracked_updates

        if not fixtures_to_compare:
            had_live_snapshot = any(fixture.is_live for fixture in fixtures_today)
            if (
                not had_live_snapshot
                and checked_dates.get(competition_name) == date.today().isoformat()
                and not should_monitor_fixtures(fixtures_today)
            ):
                return
            try:
                fixtures_today = await self.football_client.fetch_fixtures(league_id, date.today())
            except Exception as exc:
                print(f"Erro ao consultar jogos de {competition_name} para Telegram: {exc}")
                return
            checked_dates[competition_name] = date.today().isoformat()
            if not had_live_snapshot and not should_monitor_fixtures(fixtures_today):
                football_state["fixtures_today"][competition_name] = serialize_fixtures(fixtures_today)
                return
            fixtures_to_compare = fixtures_today

        changed_fixtures = [
            fixture
            for fixture in fixtures_to_compare
            if snapshots_by_competition.get(str(fixture.fixture_id)) != fixture.snapshot_key
        ]
        for fixture in changed_fixtures:
            reason = describe_fixture_update(fixture, snapshots_by_competition.get(str(fixture.fixture_id)))
            scorers = await self._fetch_goal_scorers(fixture)
            await self._broadcast(
                chat_ids,
                _format_football_update(competition_name, fixture, reason, scorers),
                parse_mode=TELEGRAM_HTML_PARSE_MODE,
            )
            snapshots_by_competition[str(fixture.fixture_id)] = fixture.snapshot_key

        football_state["fixtures_today"][competition_name] = serialize_fixtures(fixtures_to_compare)

    async def _fetch_goal_scorers(self, fixture: BrasileiraoFixture) -> list[str]:
        if self.football_client is None or fixture.home_goals is None or fixture.away_goals is None:
            return []
        if fixture.home_goals + fixture.away_goals <= 0:
            return []
        try:
            return await self.football_client.fetch_goal_scorers(fixture.fixture_id)
        except Exception as exc:
            print(f"Erro ao buscar autores dos gols para Telegram: {exc}")
            return []

    async def _check_esports_scores(self) -> None:
        if self.pandascore_client is None:
            return

        try:
            live_matches = await self.pandascore_client.fetch_live_matches()
        except Exception as exc:
            print(f"Erro ao buscar lives de e-sports para Telegram: {exc}")
            live_matches = []

        for sport in ("lol", "valorant", "cs2"):
            chat_ids = self.state["subscriptions"][sport]
            if not chat_ids:
                continue
            config = GAME_CONFIGS[sport]
            game_state = self.state["esports"][sport]
            try:
                running_matches = await self.pandascore_client.fetch_running_matches(config.api_path)
            except Exception as exc:
                print(f"Erro ao buscar partidas de {config.title} para Telegram: {exc}")
                continue

            tracked_matches = deserialize_matches(game_state["tracked_matches"])
            matches_to_compare = list(running_matches)
            for match_id in select_missing_running_match_ids(tracked_matches, running_matches):
                match = await self.pandascore_client.fetch_match(match_id)
                if match is not None:
                    matches_to_compare.append(match)

            match_snapshots = game_state["match_snapshots"]
            changed_matches = [
                match
                for match in matches_to_compare
                if match_snapshots.get(str(match.match_id)) != match.snapshot_key
            ]
            for match in changed_matches:
                reason = describe_match_update(match, match_snapshots.get(str(match.match_id)))
                await self._broadcast(
                    chat_ids,
                    _format_esports_update(config.title, match, reason),
                    parse_mode=TELEGRAM_HTML_PARSE_MODE,
                )
                match_snapshots[str(match.match_id)] = match.snapshot_key

            filtered_live_matches = [
                match for match in live_matches if _match_belongs_to_api_path(match, config.api_path)
            ]
            for match, game in _new_running_games(filtered_live_matches, game_state["game_snapshots"]):
                await self._broadcast(
                    chat_ids,
                    _format_esports_game_start(config.title, match, game),
                    parse_mode=TELEGRAM_HTML_PARSE_MODE,
                )

            game_state["tracked_matches"] = serialize_matches(
                [match for match in matches_to_compare if not match.is_finished][:MAX_TRACKED_MATCHES]
            )
            tracked_match_ids = {str(match["match_id"]) for match in game_state["tracked_matches"]}
            game_state["match_snapshots"] = {
                match_id: snapshot
                for match_id, snapshot in match_snapshots.items()
                if match_id in tracked_match_ids
            }
            _store_current_game_snapshots(game_state, filtered_live_matches)

    async def _prime_football_state(self) -> None:
        if self.football_client is None:
            return
        for competition_name, _author, setting_name, _state_name, _color in COMPETITIONS:
            league_id = getattr(settings, setting_name)
            try:
                fixtures = await self.football_client.fetch_fixtures(league_id, date.today())
            except Exception:
                continue
            self.state["football"]["checked_dates"][competition_name] = date.today().isoformat()
            self.state["football"]["fixtures_today"][competition_name] = serialize_fixtures(fixtures)
            snapshots = self.state["football"]["fixture_snapshots"].setdefault(competition_name, {})
            for fixture in fixtures:
                snapshots.setdefault(str(fixture.fixture_id), fixture.snapshot_key)

    async def _prime_esports_state(self, sport: str) -> None:
        if self.pandascore_client is None:
            return
        config = GAME_CONFIGS[sport]
        try:
            running_matches = await self.pandascore_client.fetch_running_matches(config.api_path)
            live_matches = await self.pandascore_client.fetch_live_matches(config.api_path)
        except Exception:
            return
        game_state = self.state["esports"][sport]
        game_state["tracked_matches"] = serialize_matches(running_matches[:MAX_TRACKED_MATCHES])
        for match in running_matches:
            game_state["match_snapshots"].setdefault(str(match.match_id), match.snapshot_key)
        _store_current_game_snapshots(game_state, live_matches)

    async def _broadcast(self, chat_ids: list[int], text: str, parse_mode: str | None = None) -> None:
        for chat_id in chat_ids:
            await self._send_telegram_message(chat_id, text, parse_mode=parse_mode)

    async def _send_telegram_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:
        if self.telegram_client is None:
            return
        try:
            await self.telegram_client.send_message(chat_id, text, parse_mode=parse_mode)
        except Exception as exc:
            print(f"Erro ao enviar mensagem no Telegram para {chat_id}: {exc}")

    def _save_state(self) -> None:
        self.repository.save(self.state)


def _normalize_command(text: str) -> str:
    parts = text.strip().lower().split(maxsplit=1)
    if not parts:
        return ""
    command = parts[0]
    if command.startswith("/"):
        command = command[1:]
    command = command.split("@", 1)[0]
    if len(parts) == 1:
        return command
    return f"{command} {parts[1]}"


def _help_text() -> str:
    return "\n".join(
        [
            "Alertas disponíveis:",
            "/futebol - ativa alertas dos 4 torneios de futebol",
            "/lol - ativa alertas de League of Legends",
            "/valorant - ativa alertas de Valorant",
            "/cs2 - ativa alertas de CS2",
            "/status - mostra alertas ativos neste chat",
            "/parar <opção> - desativa uma opção. Exemplo: /parar lol",
            "/parar todos - desativa tudo neste chat",
        ]
    )


def _format_football_update(
    competition_name: str,
    fixture: BrasileiraoFixture,
    reason: str,
    scorers: list[str],
) -> str:
    status = fixture.status_long or fixture.status_short or "Indisponível"
    if fixture.elapsed is not None:
        status = f"{status} - {fixture.elapsed}'"

    lines = [
        f"<b>{_html(competition_name)}</b>",
        f"<b>{_html(reason)}</b>",
        "",
        _format_score_line(fixture.home_team, fixture.score_text, fixture.away_team),
        "",
        f"<b>Status:</b> {_html(status)}",
    ]
    if fixture.kickoff_at is not None:
        lines.append(f"<b>Data:</b> {_html(fixture.kickoff_at.astimezone().strftime('%d/%m/%Y %H:%M'))}")
    if scorers:
        lines.append(f"<b>Gols:</b> {_html(' | '.join(scorers))}")
    return "\n".join(lines)


def _format_esports_update(game_title: str, match: PandaScoreMatch, reason: str) -> str:
    lines = [
        f"<b>{_html(game_title)} - {_html(_format_competition_name(match))}</b>",
        f"<b>{_html(reason)}</b>",
        "",
        _format_score_line(match.opponents[0], match.score_text, match.opponents[1]),
        "",
        f"<b>Status:</b> {_html(_format_esports_status(match.status))}",
    ]
    start_at = match.begin_at or match.scheduled_at
    if start_at is not None:
        lines.append(f"<b>Horário:</b> {_html(start_at.astimezone().strftime('%d/%m/%Y %H:%M'))}")
    if match.number_of_games is not None:
        lines.append(f"<b>Formato:</b> Melhor de {match.number_of_games}")
    stream_link = _stream_link_for_match(match)
    if stream_link is not None:
        lines.append(_format_telegram_stream_link(stream_link[0], stream_link[1]))
    return "\n".join(lines)


def _format_esports_game_start(game_title: str, match: PandaScoreMatch, game: PandaScoreGame) -> str:
    label = "mapa" if game_title in {"CS2", "Valorant"} else "jogo"
    lines = [
        f"<b>{_html(game_title)} - {_html(_format_competition_name(match))}</b>",
        f"<b>Início do {label} {game.position}</b>",
        "",
        _format_score_line(match.opponents[0], match.score_text, match.opponents[1]),
    ]
    if game.begin_at is not None:
        lines.extend(["", f"<b>Horário:</b> {_html(game.begin_at.astimezone().strftime('%d/%m/%Y %H:%M'))}"])
    stream_link = _stream_link_for_match(match)
    if stream_link is not None:
        lines.append(_format_telegram_stream_link(stream_link[0], stream_link[1]))
    return "\n".join(lines)


def _format_competition_name(match: PandaScoreMatch) -> str:
    return " - ".join(value for value in (match.league, match.serie, match.tournament) if value) or "Competição indisponível"


def _format_score_line(first: str, score_text: str, second: str) -> str:
    return f"{_html(first)} <b>{_html(score_text)}</b> {_html(second)}"


def _format_esports_status(status: str) -> str:
    normalized_status = status.strip().lower()
    return ESPORTS_STATUS_LABELS.get(normalized_status, status or "Indisponível")


def _format_telegram_stream_link(label: str, stream_url: str) -> str:
    return f"<b>{_html(label)}:</b> <a href=\"{_html(stream_url)}\">Assistir</a>"


def _html(value: object) -> str:
    return escape(str(value), quote=True)


def _store_current_game_snapshots(game_state: dict[str, object], live_matches: list[PandaScoreMatch]) -> None:
    snapshots = game_state["game_snapshots"]
    if not isinstance(snapshots, dict):
        return
    live_match_ids = {match.match_id for match in live_matches}
    for match in live_matches:
        for game in match.games:
            snapshots[game_snapshot_key(match.match_id, game.position)] = game.status
    game_state["game_snapshots"] = {
        key: status
        for key, status in snapshots.items()
        if _snapshot_match_id(str(key)) in live_match_ids
    }


def _snapshot_match_id(snapshot_key: str) -> int | None:
    match_id_text, _separator, _position = snapshot_key.partition(":")
    try:
        return int(match_id_text)
    except ValueError:
        return None


def _match_belongs_to_api_path(match: PandaScoreMatch, api_path: str) -> bool:
    videogame = match.videogame.lower()
    if api_path == "lol":
        return "league of legends" in videogame
    if api_path == "valorant":
        return "valorant" in videogame
    if api_path == "csgo":
        return "counter-strike" in videogame or "cs2" in videogame or "cs:go" in videogame
    return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TelegramAlerts(bot))
