from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from services.pandascore_service import (
    PandaScoreClient,
    PandaScoreStateRepository,
    describe_match_update,
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
                {"channel_id": None, "match_snapshots": {}, "tracked_matches": []},
            )

            repository.save(123, {"1": "running|1|0|None"}, [])

            self.assertEqual(
                repository.load(),
                {"channel_id": 123, "match_snapshots": {"1": "running|1|0|None"}, "tracked_matches": []},
            )
        finally:
            if state_path.exists():
                state_path.unlink()

    def test_client_fetches_only_lol_and_counter_strike_matches(self) -> None:
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
                return []

        client = FakeClient()

        running_matches = client._fetch_running_matches()
        upcoming_matches = client._fetch_upcoming_matches(10)

        self.assertEqual([match.videogame for match in running_matches], ["League of Legends", "Counter-Strike"])
        self.assertEqual([match.match_id for match in upcoming_matches], [123, 456])
        self.assertEqual(
            client.paths,
            [
                "/lol/matches/running",
                "/csgo/matches/running",
                "/lol/matches/upcoming",
                "/csgo/matches/upcoming",
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


if __name__ == "__main__":
    unittest.main()
