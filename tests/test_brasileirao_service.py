from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from services.brasileirao_service import (
    BrasileiraoStateRepository,
    describe_fixture_update,
    parse_goal_scorers,
    parse_fixtures_response,
    select_current_round_fixtures,
    select_missing_live_fixture_ids,
    select_next_round_fixtures,
    select_previous_round_fixtures,
    should_monitor_fixtures,
)


FIXTURES_SAMPLE = {
    "results": [
        {
            "id": 123,
            "league": {"id": 9, "name": "Brasileirao Serie A"},
            "round_number": 4,
            "home_team": "Flamengo",
            "away_team": "Palmeiras",
            "home_score": 1,
            "away_score": 0,
            "status": "1st_half",
            "current_minute": 22,
            "event_date": "2026-05-01T19:00:00+00:00",
        }
    ]
}


class BrasileiraoServiceTests(unittest.TestCase):
    def test_parse_fixtures_response_extracts_score_and_status(self) -> None:
        fixtures = parse_fixtures_response(FIXTURES_SAMPLE)

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].fixture_id, 123)
        self.assertEqual(fixtures[0].home_team, "Flamengo")
        self.assertEqual(fixtures[0].away_team, "Palmeiras")
        self.assertEqual(fixtures[0].round_number, 4)
        self.assertEqual(fixtures[0].score_text, "1 x 0")
        self.assertEqual(fixtures[0].status_short, "1st_half")

    def test_should_monitor_live_fixture(self) -> None:
        fixtures = parse_fixtures_response(FIXTURES_SAMPLE)

        self.assertTrue(should_monitor_fixtures(fixtures))

    def test_should_monitor_near_kickoff_fixture(self) -> None:
        payload = {
            "results": [
                {
                    "id": 456,
                    "league": {"id": 9, "name": "Brasileirao Serie A"},
                    "round_number": 4,
                    "home_team": "Santos",
                    "away_team": "Sao Paulo",
                    "home_score": None,
                    "away_score": None,
                    "status": "notstarted",
                    "current_minute": None,
                    "event_date": "2026-05-01T19:00:00+00:00",
                }
            ]
        }
        fixtures = parse_fixtures_response(payload)
        now = datetime(2026, 5, 1, 18, 45, tzinfo=timezone.utc)

        self.assertTrue(should_monitor_fixtures(fixtures, now=now))

    def test_select_missing_live_fixture_ids(self) -> None:
        previous_fixtures = parse_fixtures_response(
            {
                "results": [
                    {
                        "id": 1,
                        "league": {"id": 9, "name": "Sul-Americana"},
                        "home_team": "Red Bull Bragantino",
                        "away_team": "River Plate",
                        "home_score": 0,
                        "away_score": 1,
                        "status": "2nd_half",
                    },
                    {
                        "id": 2,
                        "league": {"id": 9, "name": "Sul-Americana"},
                        "home_team": "Alianza Atletico",
                        "away_team": "Macara",
                        "home_score": 0,
                        "away_score": 2,
                        "status": "1st_half",
                    },
                ]
            }
        )
        current_live_fixtures = parse_fixtures_response(
            {
                "results": [
                    {
                        "id": 2,
                        "league": {"id": 9, "name": "Sul-Americana"},
                        "home_team": "Alianza Atletico",
                        "away_team": "Macara",
                        "home_score": 0,
                        "away_score": 2,
                        "status": "1st_half",
                    }
                ]
            }
        )

        self.assertEqual(select_missing_live_fixture_ids(previous_fixtures, current_live_fixtures), {1})

    def test_select_current_and_next_round_fixtures(self) -> None:
        payload = {
            "results": [
                {
                    "id": 1,
                    "league": {"id": 9, "name": "Brasileirao Serie A"},
                    "round_number": 1,
                    "home_team": "Time A",
                    "away_team": "Time B",
                    "home_score": 1,
                    "away_score": 0,
                    "status": "finished",
                    "event_date": "2026-04-01T19:00:00+00:00",
                },
                {
                    "id": 2,
                    "league": {"id": 9, "name": "Brasileirao Serie A"},
                    "round_number": 2,
                    "home_team": "Time C",
                    "away_team": "Time D",
                    "home_score": None,
                    "away_score": None,
                    "status": "notstarted",
                    "event_date": "2026-04-08T19:00:00+00:00",
                },
                {
                    "id": 3,
                    "league": {"id": 9, "name": "Brasileirao Serie A"},
                    "round_number": 3,
                    "home_team": "Time E",
                    "away_team": "Time F",
                    "home_score": None,
                    "away_score": None,
                    "status": "notstarted",
                    "event_date": "2026-04-15T19:00:00+00:00",
                },
            ]
        }
        fixtures = parse_fixtures_response(payload)

        now = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)

        self.assertEqual([fixture.fixture_id for fixture in select_current_round_fixtures(fixtures, now=now)], [2])
        self.assertEqual([fixture.fixture_id for fixture in select_next_round_fixtures(fixtures, now=now)], [3])
        self.assertEqual([fixture.fixture_id for fixture in select_previous_round_fixtures(fixtures, now=now)], [1])

    def test_select_current_round_ignores_old_postponed_fixture(self) -> None:
        payload = {
            "results": [
                {
                    "id": 1,
                    "league": {"id": 9, "name": "Brasileirao Serie A"},
                    "round_number": 2,
                    "home_team": "Time A",
                    "away_team": "Time B",
                    "home_score": None,
                    "away_score": None,
                    "status": "postponed",
                    "event_date": "2026-02-01T19:00:00+00:00",
                },
                {
                    "id": 2,
                    "league": {"id": 9, "name": "Brasileirao Serie A"},
                    "round_number": 14,
                    "home_team": "Time C",
                    "away_team": "Time D",
                    "home_score": None,
                    "away_score": None,
                    "status": "notstarted",
                    "event_date": "2026-05-02T19:00:00+00:00",
                },
            ]
        }
        fixtures = parse_fixtures_response(payload)
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        self.assertEqual([fixture.fixture_id for fixture in select_current_round_fixtures(fixtures, now=now)], [2])

    def test_parse_goal_scorers_from_lineups(self) -> None:
        payload = {
            "home_team": "Corinthians",
            "away_team": "Peñarol",
            "lineups": {
                "home": {
                    "players": [
                        {"name": "G. Henrique", "goals": 1},
                        {"name": "J. Lingard", "goals": 2},
                    ],
                    "substitutes": [{"name": "Reserva", "goals": 0}],
                },
                "away": {
                    "players": [{"name": "Visitante", "goals": 1}],
                    "substitutes": [],
                },
            }
        }

        self.assertEqual(
            parse_goal_scorers(payload),
            ["Corinthians: G. Henrique, J. Lingard (2)", "Peñarol: Visitante"],
        )

    def test_describe_fixture_update_goal(self) -> None:
        fixture = parse_fixtures_response(
            {
                "results": [
                    {
                        "id": 1,
                        "league": {"id": 9, "name": "Brasileirao Serie A"},
                        "home_team": "Time A",
                        "away_team": "Time B",
                        "home_score": 1,
                        "away_score": 0,
                        "status": "1st_half",
                    }
                ]
            }
        )[0]

        self.assertEqual(describe_fixture_update(fixture, "0|0|1st_half"), "Gol")

    def test_describe_fixture_update_halftime_and_finished(self) -> None:
        halftime = parse_fixtures_response(
            {
                "results": [
                    {
                        "id": 1,
                        "league": {"id": 9, "name": "Brasileirao Serie A"},
                        "home_team": "Time A",
                        "away_team": "Time B",
                        "home_score": 0,
                        "away_score": 0,
                        "status": "halftime",
                    }
                ]
            }
        )[0]
        finished = parse_fixtures_response(
            {
                "results": [
                    {
                        "id": 1,
                        "league": {"id": 9, "name": "Brasileirao Serie A"},
                        "home_team": "Time A",
                        "away_team": "Time B",
                        "home_score": 0,
                        "away_score": 0,
                        "status": "finished",
                    }
                ]
            }
        )[0]

        self.assertEqual(describe_fixture_update(halftime, "0|0|1st_half"), "Intervalo")
        self.assertEqual(describe_fixture_update(finished, "0|0|2nd_half"), "Fim de jogo")

    def test_state_repository_defaults_and_save_multiple_channels(self) -> None:
        state_path = Path(__file__).resolve().parent / "_tmp_football_state.json"
        if state_path.exists():
            state_path.unlink()

        try:
            repository = BrasileiraoStateRepository(state_path)
            self.assertEqual(
                repository.load(),
                {"channel_ids": [], "checked_date": None, "fixture_snapshots": {}, "fixtures_today": []},
            )

            repository.save([123, 456], "2026-05-02", {"1": "0|0|notstarted"}, [])

            self.assertEqual(
                repository.load(),
                {
                    "channel_ids": [123, 456],
                    "checked_date": "2026-05-02",
                    "fixture_snapshots": {"1": "0|0|notstarted"},
                    "fixtures_today": [],
                },
            )
        finally:
            if state_path.exists():
                state_path.unlink()

    def test_state_repository_loads_legacy_single_channel_id(self) -> None:
        state_path = Path(__file__).resolve().parent / "_tmp_football_state.json"
        if state_path.exists():
            state_path.unlink()

        try:
            state_path.write_text(
                '{"channel_id": 123, "checked_date": null, "fixture_snapshots": {}, "fixtures_today": []}',
                encoding="utf-8",
            )
            repository = BrasileiraoStateRepository(state_path)

            self.assertEqual(
                repository.load(),
                {"channel_ids": [123], "checked_date": None, "fixture_snapshots": {}, "fixtures_today": []},
            )
        finally:
            if state_path.exists():
                state_path.unlink()


if __name__ == "__main__":
    unittest.main()
