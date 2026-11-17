from __future__ import annotations

import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from services.lol_builds import (
    BuildService,
    available,
    combat_profile,
    observations,
    patch_key,
    purchase_facts,
    recommend,
    item_answers,
)
from services.lol_analysis import analyze, baseline_for, metrics, performance_rows
from services.lol_presentation import (
    build_embeds,
    demo_data,
    live_embeds,
    report_embeds,
)
from services.lol_tracker_repository import LoLRepository
from services.riot_service import RiotClient, RiotError

CATALOG = json.loads((Path(__file__).parent / "fixtures/lol_catalog.json").read_text())
NOW = time.time()


def samples(n=24, champion=804, role="BOTTOM", core=None):
    core = core or [6672, 3085, 3031]
    return [
        {
            "match_id": f"TEST_{i}",
            "participant_id": 1,
            "patch": patch_key(CATALOG["version"]),
            "played_at": NOW - i * 1800,
            "champion_id": champion,
            "role": role,
            "map_id": 11,
            "queue_id": 420,
            "win": i < 14,
            "items": core
            + [3006]
            + ([2512] if 2512 not in core and i % 2 == 0 else []),
            "enemies": [54, 86, 64, 16, 99],
            "purchases": {"core": core, "starters": [1055, 2003]},
        }
        for i in range(n)
    ]


def match(mid="BR1_TEST", champion=804, role="BOTTOM"):
    p = {
        "puuid": "watched",
        "participantId": 1,
        "championId": champion,
        "championName": "Yunara",
        "teamPosition": role,
        "teamId": 100,
        "kills": 8,
        "deaths": 3,
        "assists": 7,
        "win": True,
        "totalMinionsKilled": 200,
        "neutralMinionsKilled": 10,
        "totalDamageDealtToChampions": 20000,
        "totalDamageTaken": 18000,
        "goldEarned": 14000,
        "visionScore": 20,
        "item0": 6672,
        "item1": 3085,
        "item2": 3031,
        "item3": 3006,
        "item4": 2512,
        "item5": 0,
        "item6": 3363,
    }
    members = [p] + [
        {
            **p,
            "participantId": i + 1,
            "puuid": f"player-{i}",
            "championId": 54,
            "kills": 3,
            "assists": 2,
            "totalDamageDealtToChampions": 10000,
        }
        for i in range(1, 5)
    ]
    return {
        "metadata": {"matchId": mid},
        "info": {
            "gameVersion": "16.22.500.1",
            "mapId": 11,
            "queueId": 420,
            "gameDuration": 1800,
            "gameEndTimestamp": int(NOW * 1000),
            "participants": members,
            "teams": [{"teamId": 100, "objectives": {"champion": {"kills": 20}}}],
        },
    }


def timeline(mid):
    events = [
        {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": i, "timestamp": t}
        for i, t in [
            (1055, 0),
            (3006, 300000),
            (6672, 600000),
            (3085, 900000),
            (3031, 1200000),
        ]
    ]
    return {"metadata": {"matchId": mid}, "info": {"frames": [{"events": events}]}}


class BuildStatisticsTests(unittest.TestCase):
    def test_yunara_sequence_is_empirical_not_marksman_pool(self):
        advice = recommend(CATALOG, 804, [], samples(), role="BOTTOM", now=NOW)
        self.assertTrue(advice["available"])
        self.assertEqual(advice["core"], [6672, 3085, 3031])
        self.assertNotIn(3094, advice["core"])
        self.assertEqual(advice["sample"], 24)
        self.assertEqual(advice["sequence_games"], 24)
        self.assertAlmostEqual(advice["sequence_win_rate"], 14 / 24 * 100)

    def test_no_data_never_falls_back_to_class_heuristic(self):
        for cid in [804, 103, 54, 222]:
            advice = recommend(CATALOG, cid, [], [], now=NOW)
            self.assertFalse(advice["available"])
            self.assertEqual(advice["core"], [])

    def test_insufficient_sample_is_explicit(self):
        advice = recommend(CATALOG, 804, [], samples(2), now=NOW)
        self.assertFalse(advice["available"])
        self.assertIn("2/20", advice["reason"])

    def test_different_patches_champions_roles_queues_and_maps_not_mixed(self):
        for field, value in [
            ("patch", "16.21"),
            ("champion_id", 103),
            ("role", "TOP"),
            ("queue_id", 450),
            ("map_id", 12),
        ]:
            rows = samples()
            for r in rows:
                r[field] = value
            advice = recommend(CATALOG, 804, [], rows, role="BOTTOM", now=NOW)
            self.assertFalse(advice["available"], field)

    def test_stale_and_future_samples_are_rejected(self):
        for when in [NOW - 15 * 86400, NOW + 1]:
            rows = samples()
            for r in rows:
                r["played_at"] = when
            self.assertFalse(recommend(CATALOG, 804, [], rows, now=NOW)["available"])

    def test_duplicate_match_participant_does_not_inflate_sample(self):
        rows = [samples(1)[0]] * 100
        self.assertEqual(recommend(CATALOG, 804, [], rows, now=NOW)["sample"], 1)

    def test_final_inventory_is_not_claimed_as_purchase_order(self):
        rows = samples()
        for r in rows:
            r.pop("purchases")
        advice = recommend(CATALOG, 804, [], rows, now=NOW)
        self.assertFalse(advice["available"])
        self.assertIn("Ordem", advice["reason"])

    def test_sequence_needs_minimum_occurrences(self):
        rows = samples()
        for r in rows[4:]:
            r.pop("purchases")
        self.assertFalse(recommend(CATALOG, 804, [], rows, now=NOW)["available"])

    def test_removed_items_invalid_ids_and_arena_variants_are_rejected(self):
        for iid in [999999, 222512]:
            self.assertFalse(available(iid, CATALOG, 11, 804))
            rows = samples(core=[6672, iid, 3031])
            self.assertFalse(recommend(CATALOG, 804, [], rows, now=NOW)["available"])

    def test_unknown_position_is_labeled_as_reference_not_current_role(self):
        advice = recommend(CATALOG, 804, [], samples(), now=NOW)
        self.assertTrue(advice["role_reference"])
        self.assertEqual(advice["role"], "BOTTOM")

    def test_alternatives_require_observed_frequency(self):
        rows = samples()
        for r in rows[:4]:
            r["items"].append(3094)
        advice = recommend(CATALOG, 804, [], rows, now=NOW)
        alternatives = {a["item_id"] for a in advice["alternatives"]}
        self.assertIn(2512, alternatives)
        self.assertNotIn(3094, alternatives)

    def test_yunara_audit_does_not_invent_winrate_for_unseen_cannon(self):
        advice = recommend(CATALOG, 804, [], samples(), now=NOW)
        cannon = next(a for a in advice["audit_items"] if a["item_id"] == 3094)
        self.assertEqual(cannon["games"], 0)
        self.assertIsNone(cannon["win_rate"])

    def test_runaan_conditional_uses_nearby_targets_and_observed_rows(self):
        rows = samples(core=[6672, 2512, 3031])
        for r in rows[:12]:
            r["items"].append(3085)
        advice = recommend(
            CATALOG,
            804,
            [{"championId": 54}, {"championId": 86}, {"championId": 64}],
            rows,
            now=NOW,
        )
        near = next(a for a in advice["adaptations"] if "curto alcance" in a["label"])
        self.assertEqual(near["sample"], 24)
        self.assertIn(3085, [i["item_id"] for i in near["items"]])
        self.assertNotIn(3094, [i["item_id"] for i in near["items"]])

    def test_conditional_small_sample_does_not_promote_a_counter(self):
        rows = samples()
        for r in rows[4:]:
            r["enemies"] = []
        advice = recommend(
            CATALOG,
            804,
            [{"championId": 54}, {"championId": 86}, {"championId": 64}],
            rows,
            now=NOW,
        )
        near = next(a for a in advice["adaptations"] if "curto alcance" in a["label"])
        self.assertEqual(near["sample"], 4)
        self.assertNotIn("items", near)

    def test_class_is_not_treated_as_exact_damage_or_range(self):
        catalog = copy.deepcopy(CATALOG)
        catalog["champions"]["999"] = {
            "id": "Unknown",
            "tags": ["Mage", "Tank", "Fighter"],
            "name": "Unknown",
        }
        profile = combat_profile([999], catalog)
        self.assertEqual(profile["known_kits"], 0)
        self.assertEqual(profile["known_ranges"], 0)
        self.assertEqual(profile["magic"], 0)
        self.assertEqual(profile["tank"], 0)

    def test_item_effects_do_not_promote_attack_speed_as_healing_reduction(self):
        self.assertFalse(item_answers(3085, "healing", CATALOG))
        self.assertTrue(item_answers(3165, "healing", CATALOG))
        self.assertTrue(item_answers(3085, "short_range", CATALOG))

    def test_observations_omit_puuid_and_require_real_patch_and_role(self):
        m = match()
        rows = observations([m])
        self.assertTrue(rows)
        self.assertNotIn("puuid", str(rows))
        self.assertEqual(rows[0]["patch"], "16.22")
        m["info"].pop("gameVersion")
        self.assertEqual(observations([m]), [])

    def test_timeline_orders_completed_items_and_respects_undo(self):
        t = timeline("BR1_TEST")
        t["info"]["frames"][0]["events"] += [
            {
                "type": "ITEM_PURCHASED",
                "participantId": 1,
                "itemId": 3094,
                "timestamp": 1500000,
            },
            {
                "type": "ITEM_UNDO",
                "participantId": 1,
                "beforeId": 3094,
                "afterId": 0,
                "timestamp": 1501000,
            },
        ]
        facts = purchase_facts(t, CATALOG, 11, 804, 1, [6672, 3085, 3031, 3094])
        self.assertEqual(facts["core"], [6672, 3085, 3031])
        self.assertEqual(facts["starters"], [1055])

    def test_later_sale_does_not_rewrite_the_actual_first_core_purchase(self):
        t = timeline("BR1_TEST")
        events = t["info"]["frames"][0]["events"]
        events.insert(
            0,
            {
                "type": "ITEM_PURCHASED",
                "participantId": 1,
                "itemId": 3094,
                "timestamp": 400000,
            },
        )
        events.append(
            {
                "type": "ITEM_SOLD",
                "participantId": 1,
                "itemId": 3094,
                "timestamp": 1500000,
            }
        )
        facts = purchase_facts(t, CATALOG, 11, 804, 1, [6672, 3085, 3031])
        self.assertEqual(facts["core"], [3094, 6672, 3085])

    def test_patch_normalization_keeps_statistical_patch_separate_from_asset_build(
        self,
    ):
        self.assertEqual(patch_key("16.22.500.123"), "16.22")
        self.assertIsNone(patch_key("not-a-version"))


class BuildPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = LoLRepository(Path(self.tmp.name) / "stats.sqlite3")
        self.riot = AsyncMock(spec=RiotClient)
        self.riot.timeline.side_effect = lambda mid, platform: timeline(mid)
        self.service = BuildService(self.riot, self.repo, clock=lambda: NOW)
        self.game = {
            "participants": [{"puuid": "watched", "championId": 804, "teamId": 100}],
            "mapId": 11,
            "gameQueueConfigId": 420,
        }
        self.player = {"puuid": "watched", "platform": "BR1"}

    async def test_persisted_samples_survive_restart_and_preserve_timeline_on_reingest(
        self,
    ):
        rows = samples()
        await self.repo.store_build_samples(rows)
        for r in rows:
            r.pop("purchases")
        await self.repo.store_build_samples(rows)
        loaded = await LoLRepository(self.repo.path).build_samples(
            "16.22", 804, 11, 420
        )
        self.assertEqual(len(loaded), 24)
        self.assertIn("purchases", loaded[0])

    async def test_real_client_timeline_calls_are_bounded_and_cached(self):
        rows = samples()
        for r in rows:
            r.pop("purchases")
        await self.repo.store_build_samples(rows)
        advice = await self.service.advise(self.game, self.player, CATALOG)
        self.assertTrue(advice["available"])
        self.assertEqual(self.riot.timeline.await_count, 8)
        await self.service.advise(self.game, self.player, CATALOG)
        self.assertEqual(self.riot.timeline.await_count, 8)

    async def test_source_error_does_not_fake_a_build(self):
        rows = samples()
        for r in rows:
            r.pop("purchases")
        await self.repo.store_build_samples(rows)
        self.riot.timeline.side_effect = RiotError(403, "not authorized")
        advice = await self.service.advise(self.game, self.player, CATALOG)
        self.assertFalse(advice["available"])
        self.assertEqual(self.riot.timeline.await_count, 1)

    async def test_patch_change_invalidates_cache_and_does_not_mix_prior_build(self):
        await self.repo.store_build_samples(samples())
        self.assertTrue(
            (await self.service.advise(self.game, self.player, CATALOG))["available"]
        )
        changed = {**CATALOG, "version": "16.23.1"}
        self.assertFalse(
            (await self.service.advise(self.game, self.player, changed))["available"]
        )

    async def test_ingest_stores_current_official_facts_without_duplicate_players(self):
        await self.service.ingest([match(), match()])
        rows = await self.repo.build_samples("16.22", 804, 11, 420)
        self.assertEqual(len(rows), 1)


class PerformanceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.m = match()
        self.p = self.m["info"]["participants"][0]

    def test_kill_participation_is_percentage_of_team_kills(self):
        result = analyze(self.m["info"], self.p, {})
        self.assertEqual(result["kp"], 75)
        self.assertIn("75.0%", result["indicators"])
        self.assertIn("(15/20)", result["indicators"])

    def test_team_sum_fallback_uses_all_teammates(self):
        self.m["info"].pop("teams")
        self.assertEqual(analyze(self.m["info"], self.p, {})["kp"], 75)

    def test_zero_missing_or_inconsistent_team_kills_never_divides_or_clamps(self):
        for total in [0, 10, None]:
            self.m["info"]["teams"][0]["objectives"]["champion"]["kills"] = total
            if total is None:
                self.m["info"]["participants"] = [self.p]
            self.assertIsNone(analyze(self.m["info"], self.p, {})["kp"])

    def test_role_champion_baseline_preferred_when_sufficient(self):
        history = performance_rows([match(f"OLD_{i}") for i in range(3)], "watched")
        extra = copy.deepcopy(history[0])
        extra["championId"] = 103
        extra["kills"] = 50
        result = analyze(self.m["info"], self.p, {"performances": history + [extra]})
        self.assertEqual(result["baseline"]["count"], 3)
        self.assertEqual(result["baseline"]["scope"], "mesmo campeao e posicao")
        self.assertIn("proximo", result["comparison"])

    def test_historical_comparison_filters_other_queues_and_maps(self):
        history = performance_rows([match(f"OLD_{i}") for i in range(3)], "watched")
        for row in history:
            row["queue_id"] = 450
        base = baseline_for(self.m["info"], self.p, history)
        self.assertFalse(base["enough"])
        self.assertEqual(base["count"], 0)

    def test_small_sample_has_no_categorical_above_or_below_claim(self):
        h = performance_rows([match("OLD")], "watched")
        result = analyze(self.m["info"], self.p, {"performances": h})
        self.assertIn("Amostra insuficiente", result["comparison"])
        self.assertNotIn("acima da media", result["comparison"])

    def test_support_includes_vision_rate_and_descriptive_comparison(self):
        self.p["teamPosition"] = "UTILITY"
        h = performance_rows(
            [{**self.m, "metadata": {"matchId": f"SUP_{i}"}} for i in range(3)],
            "watched",
        )
        result = analyze(self.m["info"], self.p, {"performances": h})
        self.assertIn("Visao/min", result["indicators"])
        self.assertIn("Visao/min", result["comparison"])

    def test_duplicate_historical_match_does_not_inflate_baseline(self):
        rows = performance_rows([self.m, self.m, self.m], "watched")
        self.assertEqual(len(rows), 1)
        self.assertFalse(baseline_for(self.m["info"], self.p, rows)["enough"])

    def test_missing_metrics_remain_unavailable(self):
        self.assertEqual(metrics({}, 1800), {})
        result = analyze({"gameDuration": 0, "participants": []}, {}, {})
        self.assertIsNone(result["kp"])
        self.assertIn("indisponivel", result["indicators"])


class NewPresentationTests(unittest.TestCase):
    def test_real_build_without_evidence_shows_limitation_not_class_pool(self):
        game, watched, context, result = demo_data(CATALOG)
        cards = build_embeds(game, watched[0], CATALOG)
        self.assertEqual(len(cards), 1)
        self.assertTrue(any(f.name == "Dados insuficientes" for f in cards[0].fields))
        self.assertNotIn("Canhão Fumegante", str(cards[0].to_dict()))

    def test_yunara_stats_source_sample_and_item_names_are_visible(self):
        game = {
            "participants": [{"puuid": "watched", "championId": 804, "teamId": 100}],
            "mapId": 11,
            "gameQueueConfigId": 420,
        }
        advice = recommend(CATALOG, 804, [], samples(), now=NOW)
        cards = build_embeds(
            game,
            {"puuid": "watched", "riot_id": "Mochila#bunny"},
            CATALOG,
            advice=advice,
        )
        out = str([e.to_dict() for e in cards])
        for phrase in [
            "16.22",
            "Riot Match-V5",
            "24",
            "Mata-Cráquens",
            "Dardos",
            "Amostra",
            "Posição",
        ]:
            self.assertIn(phrase, out)
        self.assertLessEqual(sum(len(e) for e in cards), 6000)

    def test_post_match_top_is_unchanged_against_approved_golden(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures/lol_post_approved.json").read_text()
        )
        e = report_embeds(fixture["match"], fixture["watched"], {}, CATALOG)[
            0
        ].to_dict()
        self.assertEqual(
            {k: e.get(k) for k in ["title", "description", "color", "thumbnail"]},
            fixture["top"],
        )
        self.assertEqual(e["fields"][:7], fixture["fields"])
        self.assertEqual(e["fields"][7]["name"], "ANÁLISE DE DESEMPENHO")

    def test_full_live_roster_has_individual_inline_fields_without_information_loss(
        self,
    ):
        game, watched, context, result = demo_data(CATALOG)
        for p in game["participants"]:
            context[p["puuid"]] = copy.deepcopy(context["DEMO-0"])
        e = live_embeds(game, watched, context, CATALOG)[0]
        self.assertEqual(sum(f.inline for f in e.fields), 10)
        for p in game["participants"]:
            self.assertIn(p["riotId"], str(e.to_dict()))
        self.assertIn("pontos", str(e.to_dict()))
        self.assertIn("K/D/A médio", str(e.to_dict()))
        self.assertLessEqual(len(e), 6000)

    def test_three_demo_messages_share_real_renderers_and_remain_labeled(self):
        game, watched, context, result = demo_data(CATALOG)
        batches = [
            live_embeds(game, watched, context, CATALOG, True),
            build_embeds(game, watched[0], CATALOG, True),
            report_embeds(result, watched, context, CATALOG, True),
        ]
        for batch in batches:
            self.assertLessEqual(sum(len(e) for e in batch), 6000)
            self.assertLessEqual(len(batch), 10)
            for e in batch:
                self.assertIn("MODO TESTE", e.title)
                self.assertLessEqual(len(e.fields), 25)
                for f in e.fields:
                    self.assertLessEqual(len(f.value), 1024)


if __name__ == "__main__":
    unittest.main()
