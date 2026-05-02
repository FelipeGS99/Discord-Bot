from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from cogs.esports import (
    _new_running_games,
    _official_stream_url,
    _stream_link_for_match,
)
from services.pandascore_service import (
    PandaScoreClient,
    PandaScoreStateRepository,
    describe_match_update,
    game_snapshot_key,
    parse_lol_champion_picks,
    parse_live_matches,
    parse_match,
    parse_matches,
    select_missing_running_match_ids,
)


MATCH_SAMPLE = {
    "id": 123,
    "name": "Team A vs Team B",
    "videogame": {"name": "League of Legends"},
    "league": {"name": "LCS"},
    "serie": {"full_name": "Spring 2026"},
    "tournament": {"name": "Playoffs"},
    "status": "running",
    "opponents": [
        {"opponent": {"id": 10, "name": "Team A"}},
        {"opponent": {"id": 20, "name": "Team B"}},
    ],
    "results": [
        {"team_id": 10, "score": 1},
        {"team_id": 20, "score": 0},
    ],
    "winner_id": None,
    "begin_at": "2026-05-02T18:00:00Z",
    "scheduled_at": "2026-05-02T18:00:00Z",
    "number_of_games": 3,
    "match_type": "best_of",
    "streams_list": [{"raw_url": "https://example.com/live"}],
    "games": [
        {"id": 1, "match_id": 123, "position": 1, "status": "finished"},
        {"id": 2, "match_id": 123, "position": 2, "status": "running"},
        {"id": 3, "match_id": 123, "position": 3, "status": "not_started"},
    ],
}


class PandaScoreServiceTests(unittest.TestCase):
    def test_parse_match_extracts_core_fields(self) -> None:
        match = parse_match(MATCH_SAMPLE)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.match_id, 123)
        self.assertEqual(match.videogame, "League of Legends")
        self.assertEqual(match.opponents, ("Team A", "Team B"))
        self.assertEqual(match.scores, (1, 0))
        self.assertEqual(match.score_text, "1 x 0")
        self.assertTrue(match.is_running)
        self.assertEqual(match.stream_url, "https://example.com/live")
        self.assertEqual(len(match.games), 3)
        self.assertEqual(match.games[1].position, 2)
        self.assertEqual(match.games[1].status, "running")

    def test_describe_match_update_finished(self) -> None:
        finished_payload = {
            **MATCH_SAMPLE,
            "status": "finished",
            "winner_id": 10,
            "end_at": "2026-05-02T19:00:00Z",
        }
        match = parse_match(finished_payload)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(describe_match_update(match, "running|1|0|None"), "Fim de partida")

    def test_select_missing_running_match_ids(self) -> None:
        previous_matches = parse_matches(
            [
                MATCH_SAMPLE,
                {
                    **MATCH_SAMPLE,
                    "id": 456,
                    "name": "Team C vs Team D",
                    "opponents": [
                        {"opponent": {"id": 30, "name": "Team C"}},
                        {"opponent": {"id": 40, "name": "Team D"}},
                    ],
                },
            ]
        )
        current_running_matches = parse_matches([{**MATCH_SAMPLE, "id": 456}])

        self.assertEqual(select_missing_running_match_ids(previous_matches, current_running_matches), {123})

    def test_state_repository_defaults_and_save(self) -> None:
        state_path = Path(__file__).resolve().parent / "_tmp_esports_state.json"
        if state_path.exists():
            state_path.unlink()

        try:
            repository = PandaScoreStateRepository(state_path)
            self.assertEqual(
                repository.load(),
                {"channel_ids": [], "match_snapshots": {}, "game_snapshots": {}, "tracked_matches": []},
            )

            repository.save([123, 456], {"1": "running|1|0|None"}, {"1:2": "running"}, [])

            self.assertEqual(
                repository.load(),
                {
                    "channel_ids": [123, 456],
                    "match_snapshots": {"1": "running|1|0|None"},
                    "game_snapshots": {"1:2": "running"},
                    "tracked_matches": [],
                },
            )
        finally:
            if state_path.exists():
                state_path.unlink()

    def test_state_repository_loads_legacy_single_channel_id(self) -> None:
        state_path = Path(__file__).resolve().parent / "_tmp_esports_state.json"
        if state_path.exists():
            state_path.unlink()

        try:
            state_path.write_text(
                '{"channel_id": 123, "match_snapshots": {}, "tracked_matches": []}',
                encoding="utf-8",
            )
            repository = PandaScoreStateRepository(state_path)

            self.assertEqual(
                repository.load(),
                {"channel_ids": [123], "match_snapshots": {}, "game_snapshots": {}, "tracked_matches": []},
            )
        finally:
            if state_path.exists():
                state_path.unlink()

    def test_client_fetches_supported_videogame_matches(self) -> None:
        class FakeClient(PandaScoreClient):
            def __init__(self) -> None:
                super().__init__("token")
                self.paths: list[str] = []

            def _get_json(self, path: str, params: dict[str, object]) -> object:
                self.paths.append(path)
                if path.startswith("/lol/"):
                    return [MATCH_SAMPLE]
                if path.startswith("/csgo/"):
                    return [{**MATCH_SAMPLE, "id": 456, "videogame": {"name": "Counter-Strike"}}]
                if path.startswith("/valorant/"):
                    return [{**MATCH_SAMPLE, "id": 789, "videogame": {"name": "Valorant"}}]
                return []

        client = FakeClient()

        running_matches = client._fetch_running_matches()
        upcoming_matches = client._fetch_upcoming_matches(10)

        self.assertEqual([match.videogame for match in running_matches], ["League of Legends", "Counter-Strike", "Valorant"])
        self.assertEqual([match.match_id for match in upcoming_matches], [123, 456, 789])
        self.assertEqual(
            client.paths,
            [
                "/lol/matches/running",
                "/csgo/matches/running",
                "/valorant/matches/running",
                "/lol/matches/upcoming",
                "/csgo/matches/upcoming",
                "/valorant/matches/upcoming",
            ],
        )

    def test_client_fetches_single_videogame_matches(self) -> None:
        class FakeClient(PandaScoreClient):
            def __init__(self) -> None:
                super().__init__("token")
                self.paths: list[str] = []

            def _get_json(self, path: str, params: dict[str, object]) -> object:
                self.paths.append(path)
                return [MATCH_SAMPLE]

        client = FakeClient()

        client._fetch_running_matches("lol")
        client._fetch_upcoming_matches(10, "csgo")

        self.assertEqual(client.paths, ["/lol/matches/running", "/csgo/matches/upcoming"])

    def test_client_fetches_matches_for_local_date(self) -> None:
        class FakeClient(PandaScoreClient):
            def __init__(self) -> None:
                super().__init__("token")
                self.requests: list[tuple[str, dict[str, object]]] = []

            def _get_json(self, path: str, params: dict[str, object]) -> object:
                self.requests.append((path, params))
                return [
                    {
                        **MATCH_SAMPLE,
                        "id": 1,
                        "begin_at": "2026-05-03T02:30:00Z",
                        "scheduled_at": "2026-05-03T02:30:00Z",
                    },
                    {
                        **MATCH_SAMPLE,
                        "id": 2,
                        "begin_at": "2026-05-03T03:30:00Z",
                        "scheduled_at": "2026-05-03T03:30:00Z",
                    },
                ]

        client = FakeClient()

        matches = client._fetch_matches_for_date("lol", date(2026, 5, 2), 100)

        self.assertEqual([match.match_id for match in matches], [1])
        self.assertEqual(
            client.requests,
            [
                (
                    "/lol/matches",
                    {
                        "filter[begin_at]": "2026-05-02",
                        "per_page": 100,
                        "sort": "begin_at",
                    },
                ),
                (
                    "/lol/matches",
                    {
                        "filter[begin_at]": "2026-05-03",
                        "per_page": 100,
                        "sort": "begin_at",
                    },
                )
            ],
        )

    def test_parse_live_matches_extracts_games(self) -> None:
        matches = parse_live_matches([{"match": MATCH_SAMPLE}])

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].match_id, 123)
        self.assertEqual(
            [(game.position, game.status) for game in matches[0].games],
            [(1, "finished"), (2, "running"), (3, "not_started")],
        )

    def test_client_fetches_live_matches_for_single_videogame(self) -> None:
        class FakeClient(PandaScoreClient):
            def __init__(self) -> None:
                super().__init__("token")
                self.paths: list[str] = []

            def _get_json(self, path: str, params: dict[str, object]) -> object:
                self.paths.append(path)
                return [
                    {"match": MATCH_SAMPLE},
                    {"match": {**MATCH_SAMPLE, "id": 456, "videogame": {"name": "Counter-Strike"}}},
                    {"match": {**MATCH_SAMPLE, "id": 789, "videogame": {"name": "Valorant"}}},
                ]

        client = FakeClient()

        matches = client._fetch_live_matches("lol")

        self.assertEqual([match.match_id for match in matches], [123])
        self.assertEqual(client.paths, ["/lives"])

        valorant_matches = client._fetch_live_matches("valorant")

        self.assertEqual([match.match_id for match in valorant_matches], [789])
        self.assertEqual(client.paths, ["/lives", "/lives"])

    def test_official_stream_url_uses_local_competition_map(self) -> None:
        match = parse_match(MATCH_SAMPLE)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(_official_stream_url(match), "https://www.twitch.tv/lcs")

    def test_official_stream_url_returns_none_for_unknown_competition(self) -> None:
        match = parse_match(
            {
                **MATCH_SAMPLE,
                "league": {"name": "Unknown League"},
                "serie": {"full_name": "Unknown Serie"},
                "tournament": {"name": "Unknown Tournament"},
            }
        )

        self.assertIsNotNone(match)
        assert match is not None
        self.assertIsNone(_official_stream_url(match))

    def test_stream_link_for_match_falls_back_to_pandascore_stream(self) -> None:
        match = parse_match(
            {
                **MATCH_SAMPLE,
                "league": {"name": "Unknown League"},
                "serie": {"full_name": "Unknown Serie"},
                "tournament": {"name": "Unknown Tournament"},
            }
        )

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(_stream_link_for_match(match), ("Transmissão", "https://example.com/live"))

    def test_new_running_games_requires_real_status_transition(self) -> None:
        match = parse_match(MATCH_SAMPLE)

        self.assertIsNotNone(match)
        assert match is not None
        snapshots = {
            game_snapshot_key(match.match_id, 1): "finished",
            game_snapshot_key(match.match_id, 2): "not_started",
            game_snapshot_key(match.match_id, 3): "not_started",
        }

        new_running_games = _new_running_games([match], snapshots)

        self.assertEqual(len(new_running_games), 1)
        self.assertEqual(new_running_games[0][1].position, 2)

    def test_new_running_games_ignores_unknown_status_to_avoid_startup_spam(self) -> None:
        match = parse_match(MATCH_SAMPLE)

        self.assertIsNotNone(match)
        assert match is not None

        self.assertEqual(_new_running_games([match], {}), [])

    def test_parse_lol_champion_picks(self) -> None:
        picks = parse_lol_champion_picks(
            [
                {
                    "team": {"name": "Team A"},
                    "player": {"name": "Midlaner"},
                    "role": "mid",
                    "champion": {"name": "Ahri"},
                }
            ]
        )

        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0].team_name, "Team A")
        self.assertEqual(picks[0].player_name, "Midlaner")
        self.assertEqual(picks[0].role, "mid")
        self.assertEqual(picks[0].champion_name, "Ahri")

    def test_client_fetches_lol_match_champion_picks(self) -> None:
        class FakeClient(PandaScoreClient):
            def __init__(self) -> None:
                super().__init__("token")
                self.paths: list[str] = []

            def _get_json(self, path: str, params: dict[str, object]) -> object:
                self.paths.append(path)
                return [
                    {
                        "team_name": "Team A",
                        "player_name": "Midlaner",
                        "role": "mid",
                        "champion_name": "Ahri",
                    }
                ]

        client = FakeClient()

        picks = client._fetch_lol_match_champion_picks(123)

        self.assertEqual([pick.champion_name for pick in picks], ["Ahri"])
        self.assertEqual(client.paths, ["/lol/matches/123/players/stats"])


if __name__ == "__main__":
    unittest.main()
