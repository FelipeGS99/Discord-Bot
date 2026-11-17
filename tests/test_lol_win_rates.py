from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from services.riot_service import RiotClient, RiotError, recent_stats, win_rate_stats
from services.lol_tracker_service import LoLMonitor
from services.lol_presentation import live_embeds, demo_data
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / "fixtures/lol_catalog.json").read_text())


def game(mid, win=True, champion=804, queue=420, puuid="p", remake=False):
    return {
        "metadata": {"matchId": str(mid)},
        "info": {
            "queueId": queue,
            "gameDuration": 1800,
            "gameEndTimestamp": 1900000000000 - int(mid) * 10000
            if str(mid).isdigit()
            else 1900000000000,
            "participants": [
                {
                    "puuid": puuid,
                    "championId": champion,
                    "win": win,
                    "kills": 5,
                    "deaths": 2,
                    "assists": 7,
                    "gameEndedInEarlySurrender": remake,
                }
            ],
        },
    }


class WinRateCalculationTests(unittest.TestCase):
    def test_three_of_five_is_sixty_not_seasonal_wr(self):
        rows = [game(i, i < 3) for i in range(5)]
        s = recent_stats(rows, "p")
        self.assertEqual((s["wins"], s["losses"], s["count"]), (3, 2, 5))
        self.assertEqual(s["win_rate"], 60.0)

    def test_fractional_rates_are_not_rounded_to_integer_in_data(self):
        s = win_rate_stats([game(i, i < 2) for i in range(3)], "p")
        self.assertAlmostEqual(s["win_rate"], 200 / 3)
        self.assertNotEqual(s["win_rate"], 67)

    def test_zero_and_all_wins_are_real_values_not_unavailable(self):
        for win, expected in [(False, 0), (True, 100)]:
            s = win_rate_stats([game(1, win)], "p")
            self.assertEqual(s["win_rate"], expected)

    def test_no_champion_matches_are_unavailable_not_zero_percent(self):
        self.assertIsNone(win_rate_stats([game(1, champion=103)], "p", champion_id=804))

    def test_selected_champion_and_current_queue_are_filtered(self):
        rows = [
            game(1, True),
            game(2, False),
            game(3, True, champion=103),
            game(4, True, queue=440),
        ]
        s = win_rate_stats(rows, "p", champion_id=804, queue_id=420)
        self.assertEqual((s["wins"], s["losses"], s["count"]), (1, 1, 2))

    def test_recent_limit_is_applied_after_queue_and_remake_filters(self):
        rows = [game(0, True, queue=450), game(1, True, remake=True)] + [
            game(i, i % 2 == 0) for i in range(2, 10)
        ]
        s = recent_stats(rows, "p", queue_id=420, limit=5)
        self.assertEqual(s["count"], 5)
        self.assertEqual(s["wins"], 3)

    def test_duplicate_match_cannot_inflate_champion_wr(self):
        a = game(1, True)
        b = game(2, False)
        s = win_rate_stats([a, a, a, b], "p", champion_id=804)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["win_rate"], 50)

    def test_missing_kda_does_not_remove_a_valid_win_from_wr(self):
        a = game(1, True)
        a["info"]["participants"][0].pop("kills")
        s = recent_stats([a, game(2, False)], "p")
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["win_rate"], 50)
        self.assertEqual(s["kda_count"], 1)

    def test_non_boolean_outcome_is_rejected(self):
        a = game(1)
        a["info"]["participants"][0]["win"] = 1
        self.assertIsNone(win_rate_stats([a], "p"))


class RankedWinRateHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = 0
        self.query = None
        self.data = [
            {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "EMERALD",
                "rank": "I",
                "leaguePoints": 53,
                "wins": 196,
                "losses": 193,
            },
            {
                "queueType": "RANKED_FLEX_SR",
                "tier": "GOLD",
                "rank": "II",
                "leaguePoints": 12,
                "wins": 5,
                "losses": 15,
            },
        ]

        async def handle(request):
            self.calls += 1
            self.query = dict(request.query)
            return web.json_response(self.data)

        app = web.Application()
        app.router.add_get("/{path:.*}", handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.client = RiotClient(
            "fake",
            interval=0,
            base_url=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}",
        )

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def test_actual_counts_reproduce_50_point_4_percent_and_share_rank_cache(
        self,
    ):
        rank = await self.client.rank("p")
        s = await self.client.ranked_stats("p")
        self.assertIn("EMERALD I", rank)
        self.assertAlmostEqual(s["win_rate"], 196 / 389 * 100)
        self.assertEqual(s["count"], 389)
        self.assertEqual(self.calls, 1)

    async def test_flex_is_not_mixed_with_solo(self):
        rank = await self.client.rank("p", queue_id=440)
        s = await self.client.ranked_stats("p", queue_id=440)
        self.assertIn("GOLD II", rank)
        self.assertEqual(s["win_rate"], 25)
        self.assertEqual(s["queue_name"], "Flex")

    async def test_unranked_and_zero_games_are_not_zero_wr(self):
        self.data = []
        s = await self.client.ranked_stats("p")
        self.assertEqual(s["count"], 0)
        self.assertIsNone(s["win_rate"])

    async def test_negative_or_missing_seasonal_totals_are_invalid_data(self):
        for bad in [-1, None, True]:
            self.client.cache.clear()
            self.data[0]["wins"] = bad
            with self.assertRaises(RiotError):
                await self.client.ranked_stats("p")

    async def test_history_request_is_bounded_and_uses_supported_queue_filter(self):
        self.data = []
        await self.client.history("p", count=20, queue=420)
        self.assertEqual(self.query["count"], "20")
        self.assertEqual(self.query["queue"], "420")


class WinRateContextAndRenderingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.riot = AsyncMock(spec=RiotClient)
        self.riot.key = "fake"
        self.riot.rank.return_value = "EMERALD I · 53 LP"
        self.riot.ranked_stats.return_value = {
            "queue_name": "Solo/Duo",
            "wins": 196,
            "losses": 193,
            "count": 389,
            "win_rate": 196 / 389 * 100,
        }
        self.riot.mastery.return_value = None
        rows = [game(i, i < 3, champion=804 if i in [0, 3] else 103) for i in range(5)]

        async def history(puuid, platform, **kwargs):
            result = copy.deepcopy(rows)
            for m in result:
                m["info"]["participants"][0]["puuid"] = puuid
            return result

        self.riot.history.side_effect = history
        repo = SimpleNamespace(store_build_samples=AsyncMock())
        self.monitor = LoLMonitor(SimpleNamespace(), repo, self.riot, SimpleNamespace())
        self.live = {
            "gameId": 999,
            "gameQueueConfigId": 420,
            "participants": [
                {
                    "puuid": "p",
                    "championId": 804,
                    "teamId": 100,
                    "riotId": "Mochila#bunny",
                },
                {"puuid": "q", "championId": 103, "teamId": 200, "riotId": "Outro#TAG"},
                {"puuid": "hidden", "championId": 222, "teamId": 200},
            ],
        }
        self.watched = [{"puuid": "p", "riot_id": "Mochila#bunny", "platform": "BR1"}]

    async def test_both_teams_get_separate_ranked_recent_and_selected_champion_rates(
        self,
    ):
        context = await self.monitor._context(self.live, self.watched)
        self.assertAlmostEqual(context["p"]["ranked_wr"]["win_rate"], 50.385604113)
        self.assertEqual(context["p"]["recent"]["win_rate"], 60)
        self.assertEqual(context["p"]["champion_wr"]["win_rate"], 50)
        self.assertEqual(context["q"]["champion_wr"]["win_rate"], 200 / 3)
        self.assertEqual(context["p"]["history_window"], 5)
        for call in self.riot.history.await_args_list:
            self.assertEqual(call.kwargs, {"count": 20, "queue": 420})

    async def test_hidden_participant_is_not_queried_for_any_wr(self):
        context = await self.monitor._context(self.live, self.watched)
        self.assertNotIn("hidden", context)
        for method in [self.riot.history, self.riot.rank, self.riot.ranked_stats]:
            self.assertNotIn(
                "hidden", [call.args[0] for call in method.await_args_list]
            )

    async def test_live_labels_are_scoped_and_show_counts_with_one_decimal(self):
        context = await self.monitor._context(self.live, self.watched)
        output = str(
            live_embeds(self.live, self.watched, context, CATALOG)[0].to_dict()
        )
        for value in [
            "50,4%",
            "196V/193D",
            "WR no campeão",
            "66,7%",
            "amostra pequena",
            "até 20",
        ]:
            self.assertIn(value, output)
        self.assertIn("não total da temporada", output)
        self.assertNotIn("WR recente", output)
        self.assertNotIn("60,0%", output)
        self.assertIn("KDA recente", output)

    async def test_absent_champion_games_are_not_displayed_as_zero_percent(self):
        context = await self.monitor._context(self.live, self.watched)
        context["p"]["champion_wr"] = None
        e = live_embeds(self.live, self.watched, context, CATALOG)[0]
        pfield = next(f for f in e.fields if "Mochila" in f.name)
        self.assertIn("sem jogos nos 5", pfield.value)
        self.assertNotIn(
            "0,0%",
            next(line for line in pfield.value.splitlines() if "WR no campeão" in line),
        )

    async def test_full_roster_with_all_wr_scopes_fits_discord_limits(self):
        g, watched, context, result = demo_data(CATALOG)
        for p in g["participants"]:
            context[p["puuid"]] = copy.deepcopy(context["DEMO-0"])
        e = live_embeds(g, watched, context, CATALOG)[0]
        self.assertLessEqual(len(e), 6000)
        for f in e.fields:
            self.assertLessEqual(len(f.value), 1024)


if __name__ == "__main__":
    unittest.main()
