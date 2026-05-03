from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cogs.brasileirao import EMBED_COLOR as BRASILEIRAO_COLOR
from cogs.brasileirao import Brasileirao
from cogs.football_colors import color_for_fixture
from cogs.futebol import COMPETITIONS, Futebol
from services.brasileirao_service import BrasileiraoFixture


class FootballEmbedTests(unittest.TestCase):
    def test_color_for_fixture_is_stable_for_same_fixture(self) -> None:
        fixture = _fixture(1, "Sao Paulo", "Bahia")

        self.assertEqual(color_for_fixture(fixture), color_for_fixture(fixture))

    def test_color_for_fixture_can_differ_between_games(self) -> None:
        colors = {
            color_for_fixture(_fixture(index, f"Time {index}", f"Rival {index}"))
            for index in range(1, 8)
        }

        self.assertGreater(len(colors), 1)

    def test_futebol_group_builds_one_embed_per_fixture_using_competition_color(self) -> None:
        fixtures = [_fixture(1, "Sao Paulo", "Bahia"), _fixture(2, "Flamengo", "Vasco da Gama")]
        competition_name = COMPETITIONS[0][0]
        competition_color = COMPETITIONS[0][4]

        embeds = Futebol._build_matches_embeds({competition_name: fixtures}, {}, fixtures[0].kickoff_at.date(), "hoje")

        self.assertEqual(len(embeds), 2)
        self.assertEqual(embeds[0].color.value, competition_color)
        self.assertEqual(embeds[1].color.value, competition_color)

    def test_brasileirao_round_builds_one_embed_per_fixture_using_competition_color(self) -> None:
        fixtures = [_fixture(1, "Sao Paulo", "Bahia"), _fixture(2, "Flamengo", "Vasco da Gama")]

        embeds = Brasileirao._build_round_embeds(fixtures, "rodada atual")

        self.assertEqual(len(embeds), 2)
        self.assertEqual(embeds[0].color.value, BRASILEIRAO_COLOR)
        self.assertEqual(embeds[1].color.value, BRASILEIRAO_COLOR)

    def test_single_match_score_embed_uses_fixture_color(self) -> None:
        fixture = _fixture(1, "Sao Paulo", "Bahia")

        embed = Brasileirao._build_score_embed(fixture, reason="Atualizacao de placar")

        self.assertEqual(embed.color.value, color_for_fixture(fixture))


def _fixture(fixture_id: int, home_team: str, away_team: str) -> BrasileiraoFixture:
    return BrasileiraoFixture(
        fixture_id=fixture_id,
        league_id=1,
        league_name="Brasileirao Serie A",
        round_number=1,
        home_team=home_team,
        away_team=away_team,
        home_goals=None,
        away_goals=None,
        status_short="notstarted",
        status_long="Nao iniciado",
        elapsed=None,
        kickoff_at=datetime(2026, 5, 3, 19, 0, tzinfo=timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
