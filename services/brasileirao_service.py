from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


BSD_BASE_URL = "https://sports.bzzoiro.com/api"
REQUEST_TIMEOUT_SECONDS = 20
LIVE_STATUS_CODES = {"inprogress", "1st_half", "halftime", "2nd_half"}
FINISHED_STATUS_CODES = {"finished"}
NOT_STARTED_STATUS_CODE = "notstarted"


@dataclass(frozen=True)
class BrasileiraoFixture:
    fixture_id: int
    league_id: int | None
    league_name: str
    round_number: int | None
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    status_short: str
    status_long: str
    elapsed: int | None
    kickoff_at: datetime | None

    @property
    def snapshot_key(self) -> str:
        return "|".join(
            [
                str(self.home_goals),
                str(self.away_goals),
                self.status_short,
            ]
        )

    @property
    def is_live(self) -> bool:
        return self.status_short in LIVE_STATUS_CODES

    @property
    def is_finished(self) -> bool:
        return self.status_short in FINISHED_STATUS_CODES

    @property
    def score_text(self) -> str:
        home = "-" if self.home_goals is None else str(self.home_goals)
        away = "-" if self.away_goals is None else str(self.away_goals)
        return f"{home} x {away}"


class BsdFootballClient:
    def __init__(self, api_key: str, base_url: str = BSD_BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def fetch_fixtures(
        self,
        league_id: int,
        fixture_date: date,
    ) -> list[BrasileiraoFixture]:
        return await asyncio.to_thread(self._fetch_fixtures, league_id, fixture_date)

    async def fetch_live_fixtures(self, league_id: int) -> list[BrasileiraoFixture]:
        return await asyncio.to_thread(self._fetch_live_fixtures, league_id)

    async def fetch_all_live_fixtures(self) -> list[BrasileiraoFixture]:
        return await asyncio.to_thread(self._fetch_all_live_fixtures)

    async def fetch_season_fixtures(self, league_id: int) -> list[BrasileiraoFixture]:
        return await asyncio.to_thread(self._fetch_season_fixtures, league_id)

    async def fetch_goal_scorers(self, fixture_id: int) -> list[str]:
        return await asyncio.to_thread(self._fetch_goal_scorers, fixture_id)

    def _fetch_fixtures(self, league_id: int, fixture_date: date) -> list[BrasileiraoFixture]:
        query = urlencode(
            {
                "league": league_id,
                "date_from": fixture_date.isoformat(),
                "date_to": fixture_date.isoformat(),
                "tz": "America/Sao_Paulo",
                "limit": 200,
            }
        )
        payload = self._get_json(f"/events/?{query}")
        return parse_fixtures_response(payload)

    def _fetch_live_fixtures(self, league_id: int) -> list[BrasileiraoFixture]:
        fixtures = self._fetch_all_live_fixtures()
        return [fixture for fixture in fixtures if fixture.league_id == league_id]

    def _fetch_all_live_fixtures(self) -> list[BrasileiraoFixture]:
        query = urlencode({"tz": "America/Sao_Paulo", "limit": 200})
        payload = self._get_json(f"/live/?{query}")
        return parse_fixtures_response(payload)

    def _fetch_season_fixtures(self, league_id: int) -> list[BrasileiraoFixture]:
        season_id = self._get_current_season_id(league_id)
        if season_id is None:
            return []

        fixtures: list[BrasileiraoFixture] = []
        offset = 0
        limit = 200
        while True:
            query = urlencode(
                {
                    "league": league_id,
                    "season": season_id,
                    "tz": "America/Sao_Paulo",
                    "limit": limit,
                    "offset": offset,
                }
            )
            payload = self._get_json(f"/events/?{query}")
            page_fixtures = parse_fixtures_response(payload)
            fixtures.extend(page_fixtures)
            if not payload.get("next") or not page_fixtures:
                break
            offset += limit

        return fixtures

    def _get_current_season_id(self, league_id: int) -> int | None:
        payload = self._get_json(f"/leagues/{league_id}/")
        current_season = payload.get("current_season")
        if not isinstance(current_season, dict):
            return None
        return _optional_int(current_season.get("id"))

    def _fetch_goal_scorers(self, fixture_id: int) -> list[str]:
        payload = self._get_json(f"/events/{fixture_id}/")
        return parse_goal_scorers(payload)

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Token {self.api_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError(
                    "BSD recusou a chave de API. Verifique se BSD_API_KEY no .env contem a chave da BSD, "
                    "nao a chave antiga da API-Football."
                ) from exc
            raise


# Backwards-compatible alias for existing cogs.
ApiFootballClient = BsdFootballClient


class BrasileiraoStateRepository:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "channel_id": None,
                "checked_date": None,
                "fixture_snapshots": {},
                "fixtures_today": [],
            }

        with self.state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return {
            "channel_id": data.get("channel_id") if isinstance(data.get("channel_id"), int) else None,
            "checked_date": data.get("checked_date") if isinstance(data.get("checked_date"), str) else None,
            "fixture_snapshots": data.get("fixture_snapshots") if isinstance(data.get("fixture_snapshots"), dict) else {},
            "fixtures_today": data.get("fixtures_today") if isinstance(data.get("fixtures_today"), list) else [],
        }

    def save(
        self,
        channel_id: int | None,
        checked_date: str | None,
        fixture_snapshots: dict[str, str],
        fixtures_today: list[dict[str, Any]],
    ) -> None:
        data = {
            "channel_id": channel_id,
            "checked_date": checked_date,
            "fixture_snapshots": fixture_snapshots,
            "fixtures_today": fixtures_today,
        }
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)


def parse_fixtures_response(payload: dict[str, Any]) -> list[BrasileiraoFixture]:
    entries = payload.get("results")
    if entries is None:
        entries = payload.get("response", [])

    fixtures: list[BrasileiraoFixture] = []
    for entry in entries:
        fixture = _parse_bsd_fixture(entry)
        if fixture is not None:
            fixtures.append(fixture)

    return sorted(fixtures, key=lambda fixture: fixture.kickoff_at or datetime.max.replace(tzinfo=timezone.utc))


def parse_goal_scorers(payload: dict[str, Any]) -> list[str]:
    lineups = payload.get("lineups")
    if not isinstance(lineups, dict):
        return []

    scorers: list[str] = []
    team_names = {
        "home": str(payload.get("home_team") or "Mandante"),
        "away": str(payload.get("away_team") or "Visitante"),
    }
    for side in ("home", "away"):
        side_lineup = lineups.get(side)
        if not isinstance(side_lineup, dict):
            continue
        side_scorers: list[str] = []
        for group_name in ("players", "substitutes"):
            players = side_lineup.get(group_name)
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                goals = _optional_int(player.get("goals")) or 0
                name = str(player.get("name") or "").strip()
                if goals <= 0 or not name:
                    continue
                side_scorers.append(f"{name} ({goals})" if goals > 1 else name)

        if side_scorers:
            scorers.append(f"{team_names[side]}: {', '.join(side_scorers)}")

    return scorers


def describe_fixture_update(
    fixture: BrasileiraoFixture,
    previous_snapshot: str | None,
) -> str:
    if not previous_snapshot:
        if fixture.is_live:
            return "Inicio de jogo"
        return "Atualizacao de placar"

    previous_home_goals, previous_away_goals, previous_status = _parse_snapshot(previous_snapshot)
    current_home_goals = fixture.home_goals
    current_away_goals = fixture.away_goals

    if (
        previous_home_goals is not None
        and previous_away_goals is not None
        and current_home_goals is not None
        and current_away_goals is not None
        and current_home_goals + current_away_goals > previous_home_goals + previous_away_goals
    ):
        return "Gol"

    if fixture.status_short == "halftime" and previous_status != "halftime":
        return "Intervalo"
    if fixture.status_short == "finished" and previous_status != "finished":
        return "Fim de jogo"
    if fixture.is_live and previous_status == NOT_STARTED_STATUS_CODE:
        return "Inicio de jogo"

    return "Atualizacao de status"


def _parse_snapshot(snapshot: str) -> tuple[int | None, int | None, str]:
    parts = snapshot.split("|")
    if len(parts) != 3:
        return None, None, ""
    return _optional_int(parts[0]), _optional_int(parts[1]), parts[2]


def should_monitor_fixtures(fixtures: list[BrasileiraoFixture], now: datetime | None = None) -> bool:
    if not fixtures:
        return False

    current_time = now or datetime.now(timezone.utc)
    for fixture in fixtures:
        if fixture.is_live:
            return True
        if fixture.kickoff_at is None or fixture.is_finished:
            continue
        monitor_start = fixture.kickoff_at - timedelta(minutes=30)
        monitor_end = fixture.kickoff_at + timedelta(hours=3)
        if monitor_start <= current_time <= monitor_end:
            return True

    return False


def serialize_fixtures(fixtures: list[BrasileiraoFixture]) -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": fixture.fixture_id,
            "league_id": fixture.league_id,
            "league_name": fixture.league_name,
            "round_number": fixture.round_number,
            "home_team": fixture.home_team,
            "away_team": fixture.away_team,
            "home_goals": fixture.home_goals,
            "away_goals": fixture.away_goals,
            "status_short": fixture.status_short,
            "status_long": fixture.status_long,
            "elapsed": fixture.elapsed,
            "kickoff_at": fixture.kickoff_at.isoformat() if fixture.kickoff_at else None,
        }
        for fixture in fixtures
    ]


def deserialize_fixtures(data: list[dict[str, Any]]) -> list[BrasileiraoFixture]:
    fixtures: list[BrasileiraoFixture] = []
    for item in data:
        try:
            fixtures.append(
                BrasileiraoFixture(
                    fixture_id=int(item["fixture_id"]),
                    league_id=_optional_int(item.get("league_id")),
                    league_name=str(item.get("league_name") or ""),
                    round_number=_optional_int(item.get("round_number")),
                    home_team=str(item["home_team"]),
                    away_team=str(item["away_team"]),
                    home_goals=_optional_int(item.get("home_goals")),
                    away_goals=_optional_int(item.get("away_goals")),
                    status_short=str(item.get("status_short") or ""),
                    status_long=str(item.get("status_long") or ""),
                    elapsed=_optional_int(item.get("elapsed")),
                    kickoff_at=_parse_api_datetime(item.get("kickoff_at")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return fixtures


def _parse_bsd_fixture(entry: dict[str, Any]) -> BrasileiraoFixture | None:
    fixture_id = entry.get("id")
    home_team = entry.get("home_team")
    away_team = entry.get("away_team")
    if not isinstance(fixture_id, int) or not home_team or not away_team:
        return None

    league_data = entry.get("league") if isinstance(entry.get("league"), dict) else {}
    status = str(entry.get("status") or "")
    return BrasileiraoFixture(
        fixture_id=fixture_id,
        league_id=_optional_int(league_data.get("id")),
        league_name=str(league_data.get("name") or ""),
        round_number=_optional_int(entry.get("round_number")),
        home_team=str(home_team),
        away_team=str(away_team),
        home_goals=_optional_int(entry.get("home_score")),
        away_goals=_optional_int(entry.get("away_score")),
        status_short=status,
        status_long=_format_status(status),
        elapsed=_optional_int(entry.get("current_minute")),
        kickoff_at=_parse_api_datetime(entry.get("event_date")),
    )


def _format_status(status: str) -> str:
    labels = {
        "notstarted": "Nao iniciado",
        "inprogress": "Em andamento",
        "1st_half": "Primeiro tempo",
        "halftime": "Intervalo",
        "2nd_half": "Segundo tempo",
        "finished": "Encerrado",
        "postponed": "Adiado",
        "cancelled": "Cancelado",
    }
    return labels.get(status, status or "Status indisponivel")


def select_current_round_fixtures(
    fixtures: list[BrasileiraoFixture],
    now: datetime | None = None,
) -> list[BrasileiraoFixture]:
    grouped = _group_rounds(fixtures)
    if not grouped:
        return []

    current_time = now or datetime.now(timezone.utc)
    for round_fixtures in _sorted_round_groups(grouped):
        round_end = _round_end(round_fixtures)
        if round_end is None or round_end >= current_time - timedelta(days=2):
            return round_fixtures

    return _sorted_round_groups(grouped)[-1]


def select_next_round_fixtures(
    fixtures: list[BrasileiraoFixture],
    now: datetime | None = None,
) -> list[BrasileiraoFixture]:
    grouped = _group_rounds(fixtures)
    if not grouped:
        return []

    current_round = select_current_round_fixtures(fixtures, now=now)
    if not current_round:
        return []

    current_round_number = current_round[0].round_number
    for round_number in sorted(grouped):
        if current_round_number is not None and round_number > current_round_number:
            return grouped[round_number]
    return []


def select_previous_round_fixtures(
    fixtures: list[BrasileiraoFixture],
    now: datetime | None = None,
) -> list[BrasileiraoFixture]:
    grouped = _group_rounds(fixtures)
    if not grouped:
        return []

    current_round = select_current_round_fixtures(fixtures, now=now)
    if not current_round:
        return []

    current_round_number = current_round[0].round_number
    previous_rounds = [
        round_number
        for round_number in sorted(grouped)
        if current_round_number is not None and round_number < current_round_number
    ]
    if not previous_rounds:
        return []

    return grouped[previous_rounds[-1]]


def _group_rounds(fixtures: list[BrasileiraoFixture]) -> dict[int, list[BrasileiraoFixture]]:
    grouped: dict[int, list[BrasileiraoFixture]] = {}
    for fixture in fixtures:
        if fixture.round_number is None:
            continue
        grouped.setdefault(fixture.round_number, []).append(fixture)

    for round_fixtures in grouped.values():
        round_fixtures.sort(key=lambda fixture: fixture.kickoff_at or datetime.max.replace(tzinfo=timezone.utc))

    return grouped


def _sorted_round_groups(grouped: dict[int, list[BrasileiraoFixture]]) -> list[list[BrasileiraoFixture]]:
    return [
        grouped[round_number]
        for round_number in sorted(grouped)
    ]


def _round_end(fixtures: list[BrasileiraoFixture]) -> datetime | None:
    dates = [fixture.kickoff_at for fixture in fixtures if fixture.kickoff_at is not None]
    if not dates:
        return None
    return max(dates)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_api_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
