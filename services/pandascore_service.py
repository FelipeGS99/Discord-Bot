from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PANDASCORE_BASE_URL = "https://api.pandascore.co"
REQUEST_TIMEOUT_SECONDS = 20
RUNNING_STATUS = "running"
FINISHED_STATUS = "finished"
SUPPORTED_VIDEOGAME_PATHS = ("lol", "csgo")
APP_TIMEZONE = timezone(timedelta(hours=-3), "America/Sao_Paulo")


@dataclass(frozen=True)
class PandaScoreMatch:
    match_id: int
    name: str
    videogame: str
    league: str
    serie: str
    tournament: str
    status: str
    opponents: tuple[str, str]
    scores: tuple[int | None, int | None]
    winner_id: int | None
    begin_at: datetime | None
    scheduled_at: datetime | None
    end_at: datetime | None
    number_of_games: int | None
    match_type: str
    stream_url: str | None

    @property
    def is_running(self) -> bool:
        return self.status == RUNNING_STATUS

    @property
    def is_finished(self) -> bool:
        return self.status == FINISHED_STATUS

    @property
    def score_text(self) -> str:
        first = "-" if self.scores[0] is None else str(self.scores[0])
        second = "-" if self.scores[1] is None else str(self.scores[1])
        return f"{first} x {second}"

    @property
    def snapshot_key(self) -> str:
        return "|".join(
            [
                self.status,
                str(self.scores[0]),
                str(self.scores[1]),
                str(self.winner_id),
            ]
        )


@dataclass(frozen=True)
class LolChampionPick:
    team_name: str
    player_name: str
    role: str
    champion_name: str


class PandaScoreClient:
    def __init__(self, api_token: str, base_url: str = PANDASCORE_BASE_URL) -> None:
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")

    async def fetch_running_matches(self, videogame_path: str | None = None) -> list[PandaScoreMatch]:
        return await asyncio.to_thread(self._fetch_running_matches, videogame_path)

    async def fetch_upcoming_matches(self, limit: int = 10, videogame_path: str | None = None) -> list[PandaScoreMatch]:
        return await asyncio.to_thread(self._fetch_upcoming_matches, limit, videogame_path)

    async def fetch_matches_for_date(
        self,
        videogame_path: str,
        match_date: date,
        limit: int = 100,
    ) -> list[PandaScoreMatch]:
        return await asyncio.to_thread(self._fetch_matches_for_date, videogame_path, match_date, limit)

    async def fetch_match(self, match_id: int) -> PandaScoreMatch | None:
        return await asyncio.to_thread(self._fetch_match, match_id)

    async def fetch_lol_match_champion_picks(self, match_id: int) -> list[LolChampionPick]:
        return await asyncio.to_thread(self._fetch_lol_match_champion_picks, match_id)

    def _fetch_running_matches(self, videogame_path: str | None = None) -> list[PandaScoreMatch]:
        if videogame_path:
            return self._get_matches(f"/{videogame_path}/matches/running", {"per_page": 50})
        return self._get_supported_videogame_matches("running", {"per_page": 50})

    def _fetch_upcoming_matches(self, limit: int, videogame_path: str | None = None) -> list[PandaScoreMatch]:
        per_page = max(1, min(limit, 100))
        if videogame_path:
            return self._get_matches(f"/{videogame_path}/matches/upcoming", {"per_page": per_page, "sort": "begin_at"})
        return self._get_supported_videogame_matches("upcoming", {"per_page": per_page, "sort": "begin_at"})

    def _fetch_matches_for_date(
        self,
        videogame_path: str,
        match_date: date,
        limit: int,
    ) -> list[PandaScoreMatch]:
        per_page = max(1, min(limit, 100))
        utc_dates = _utc_dates_for_local_date(match_date)
        matches_by_id: dict[int, PandaScoreMatch] = {}
        for utc_date in utc_dates:
            matches = self._get_matches(
                f"/{videogame_path}/matches",
                {
                    "filter[begin_at]": utc_date.isoformat(),
                    "per_page": per_page,
                    "sort": "begin_at",
                },
            )
            for match in matches:
                matches_by_id[match.match_id] = match

        return [
            match
            for match in sorted(
                matches_by_id.values(),
                key=lambda item: item.begin_at or item.scheduled_at or datetime.max.replace(tzinfo=timezone.utc),
            )
            if _match_local_date(match) == match_date
        ]

    def _fetch_match(self, match_id: int) -> PandaScoreMatch | None:
        payload = self._get_json(f"/matches/{match_id}", {})
        if not isinstance(payload, dict):
            return None
        return parse_match(payload)

    def _fetch_lol_match_champion_picks(self, match_id: int) -> list[LolChampionPick]:
        payload = self._get_json(f"/lol/matches/{match_id}/players/stats", {})
        if not isinstance(payload, list):
            return []
        return parse_lol_champion_picks(payload)

    def _get_matches(self, path: str, params: dict[str, Any]) -> list[PandaScoreMatch]:
        payload = self._get_json(path, params)
        if not isinstance(payload, list):
            return []
        return parse_matches(payload)

    def _get_supported_videogame_matches(self, status_path: str, params: dict[str, Any]) -> list[PandaScoreMatch]:
        matches: list[PandaScoreMatch] = []
        for videogame_path in SUPPORTED_VIDEOGAME_PATHS:
            matches.extend(self._get_matches(f"/{videogame_path}/matches/{status_path}", params))
        return sorted(
            matches,
            key=lambda match: match.begin_at or match.scheduled_at or datetime.max.replace(tzinfo=timezone.utc),
        )

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        query = urlencode(params)
        suffix = f"?{query}" if query else ""
        request = Request(
            f"{self.base_url}{path}{suffix}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_token}",
            },
        )
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("PandaScore recusou o token. Verifique PANDASCORE_API_TOKEN no .env.") from exc
            if exc.code == 403:
                raise RuntimeError("Seu plano da PandaScore não permite acessar esse endpoint.") from exc
            if exc.code == 429:
                raise RuntimeError("Limite de requisicoes da PandaScore atingido. Tente novamente mais tarde.") from exc
            raise


class PandaScoreStateRepository:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "channel_id": None,
                "match_snapshots": {},
                "tracked_matches": [],
            }

        with self.state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return {
            "channel_id": data.get("channel_id") if isinstance(data.get("channel_id"), int) else None,
            "match_snapshots": data.get("match_snapshots") if isinstance(data.get("match_snapshots"), dict) else {},
            "tracked_matches": data.get("tracked_matches") if isinstance(data.get("tracked_matches"), list) else [],
        }

    def save(
        self,
        channel_id: int | None,
        match_snapshots: dict[str, str],
        tracked_matches: list[dict[str, Any]],
    ) -> None:
        data = {
            "channel_id": channel_id,
            "match_snapshots": match_snapshots,
            "tracked_matches": tracked_matches,
        }
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)


def parse_matches(payload: list[dict[str, Any]]) -> list[PandaScoreMatch]:
    matches: list[PandaScoreMatch] = []
    for entry in payload:
        match = parse_match(entry)
        if match is not None:
            matches.append(match)
    return sorted(matches, key=lambda match: match.begin_at or match.scheduled_at or datetime.max.replace(tzinfo=timezone.utc))


def parse_lol_champion_picks(payload: list[dict[str, Any]]) -> list[LolChampionPick]:
    picks: list[LolChampionPick] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        champion_name = _nested_name(entry.get("champion")) or str(entry.get("champion_name") or "").strip()
        if not champion_name:
            continue
        picks.append(
            LolChampionPick(
                team_name=_nested_name(entry.get("team")) or str(entry.get("team_name") or "Time").strip(),
                player_name=_nested_name(entry.get("player")) or str(entry.get("player_name") or "Jogador").strip(),
                role=str(entry.get("role") or entry.get("position") or "").strip(),
                champion_name=champion_name,
            )
        )
    return picks


def parse_match(entry: dict[str, Any]) -> PandaScoreMatch | None:
    match_id = _optional_int(entry.get("id"))
    if match_id is None:
        return None

    opponents = _parse_opponents(entry)
    scores = _parse_scores(entry, opponents)
    streams = entry.get("streams_list")

    return PandaScoreMatch(
        match_id=match_id,
        name=str(entry.get("name") or "Partida sem nome"),
        videogame=_nested_name(entry.get("videogame")),
        league=_nested_name(entry.get("league")),
        serie=_nested_name(entry.get("serie"), fallback_key="full_name"),
        tournament=_nested_name(entry.get("tournament")),
        status=str(entry.get("status") or "unknown"),
        opponents=opponents,
        scores=scores,
        winner_id=_optional_int(entry.get("winner_id")),
        begin_at=_parse_datetime(entry.get("begin_at")),
        scheduled_at=_parse_datetime(entry.get("scheduled_at")),
        end_at=_parse_datetime(entry.get("end_at")),
        number_of_games=_optional_int(entry.get("number_of_games")),
        match_type=str(entry.get("match_type") or ""),
        stream_url=_first_stream_url(streams),
    )


def describe_match_update(match: PandaScoreMatch, previous_snapshot: str | None) -> str:
    if not previous_snapshot:
        if match.is_running:
            return "Início de partida"
        if match.is_finished:
            return "Fim de partida"
        return "Atualização de partida"

    previous_status, previous_first_score, previous_second_score, _previous_winner_id = _parse_snapshot(previous_snapshot)
    if match.is_finished and previous_status != FINISHED_STATUS:
        return "Fim de partida"
    if match.is_running and previous_status != RUNNING_STATUS:
        return "Início de partida"
    if (
        str(match.scores[0]) != previous_first_score
        or str(match.scores[1]) != previous_second_score
    ):
        return "Atualização de placar"
    return "Atualização de status"


def serialize_matches(matches: list[PandaScoreMatch]) -> list[dict[str, Any]]:
    return [
        {
            "match_id": match.match_id,
            "name": match.name,
            "videogame": match.videogame,
            "league": match.league,
            "serie": match.serie,
            "tournament": match.tournament,
            "status": match.status,
            "opponents": list(match.opponents),
            "scores": list(match.scores),
            "winner_id": match.winner_id,
            "begin_at": match.begin_at.isoformat() if match.begin_at else None,
            "scheduled_at": match.scheduled_at.isoformat() if match.scheduled_at else None,
            "end_at": match.end_at.isoformat() if match.end_at else None,
            "number_of_games": match.number_of_games,
            "match_type": match.match_type,
            "stream_url": match.stream_url,
        }
        for match in matches
    ]


def deserialize_matches(data: list[dict[str, Any]]) -> list[PandaScoreMatch]:
    matches: list[PandaScoreMatch] = []
    for item in data:
        try:
            matches.append(
                PandaScoreMatch(
                    match_id=int(item["match_id"]),
                    name=str(item.get("name") or "Partida sem nome"),
                    videogame=str(item.get("videogame") or ""),
                    league=str(item.get("league") or ""),
                    serie=str(item.get("serie") or ""),
                    tournament=str(item.get("tournament") or ""),
                    status=str(item.get("status") or "unknown"),
                    opponents=(str(item.get("opponents", ["", ""])[0]), str(item.get("opponents", ["", ""])[1])),
                    scores=(_optional_int(item.get("scores", [None, None])[0]), _optional_int(item.get("scores", [None, None])[1])),
                    winner_id=_optional_int(item.get("winner_id")),
                    begin_at=_parse_datetime(item.get("begin_at")),
                    scheduled_at=_parse_datetime(item.get("scheduled_at")),
                    end_at=_parse_datetime(item.get("end_at")),
                    number_of_games=_optional_int(item.get("number_of_games")),
                    match_type=str(item.get("match_type") or ""),
                    stream_url=str(item.get("stream_url")) if item.get("stream_url") else None,
                )
            )
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return matches


def select_missing_running_match_ids(
    previous_matches: list[PandaScoreMatch],
    current_running_matches: list[PandaScoreMatch],
) -> set[int]:
    current_running_ids = {match.match_id for match in current_running_matches}
    return {
        match.match_id
        for match in previous_matches
        if match.is_running and match.match_id not in current_running_ids
    }


def _parse_opponents(entry: dict[str, Any]) -> tuple[str, str]:
    raw_opponents = entry.get("opponents")
    names: list[str] = []
    if isinstance(raw_opponents, list):
        for opponent_entry in raw_opponents[:2]:
            if not isinstance(opponent_entry, dict):
                continue
            opponent = opponent_entry.get("opponent")
            name = _nested_name(opponent)
            if name:
                names.append(name)

    while len(names) < 2:
        names.append("TBD")
    return names[0], names[1]


def _parse_scores(entry: dict[str, Any], opponents: tuple[str, str]) -> tuple[int | None, int | None]:
    raw_results = entry.get("results")
    if not isinstance(raw_results, list):
        return None, None

    scores_by_team_id: dict[int, int] = {}
    ordered_scores: list[int] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        score = _optional_int(result.get("score"))
        if score is None:
            continue
        team_id = _optional_int(result.get("team_id"))
        if team_id is not None:
            scores_by_team_id[team_id] = score
        ordered_scores.append(score)

    raw_opponents = entry.get("opponents")
    scores: list[int | None] = []
    if isinstance(raw_opponents, list):
        for opponent_entry in raw_opponents[:2]:
            opponent = opponent_entry.get("opponent") if isinstance(opponent_entry, dict) else None
            team_id = _optional_int(opponent.get("id")) if isinstance(opponent, dict) else None
            scores.append(scores_by_team_id.get(team_id) if team_id is not None else None)

    if len(scores) == 2 and any(score is not None for score in scores):
        return scores[0], scores[1]
    if len(ordered_scores) >= 2:
        return ordered_scores[0], ordered_scores[1]
    if opponents == ("TBD", "TBD"):
        return None, None
    return None, None


def _nested_name(value: Any, fallback_key: str = "name") -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get(fallback_key) or value.get("name") or "")


def _first_stream_url(streams: Any) -> str | None:
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        raw_url = stream.get("raw_url") or stream.get("embed_url")
        if raw_url:
            return str(raw_url)
    return None


def _parse_snapshot(snapshot: str) -> tuple[str, str, str, str]:
    parts = snapshot.split("|")
    if len(parts) != 4:
        return "", "", "", ""
    return parts[0], parts[1], parts[2], parts[3]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_dates_for_local_date(local_date: date) -> list[date]:
    start = datetime.combine(local_date, datetime.min.time(), tzinfo=APP_TIMEZONE)
    end = start + timedelta(days=1, microseconds=-1)
    return sorted({start.astimezone(timezone.utc).date(), end.astimezone(timezone.utc).date()})


def _match_local_date(match: PandaScoreMatch) -> date | None:
    match_datetime = match.begin_at or match.scheduled_at
    if match_datetime is None:
        return None
    return match_datetime.astimezone(APP_TIMEZONE).date()
