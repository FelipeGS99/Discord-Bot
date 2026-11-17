from __future__ import annotations

import copy
import asyncio
import aiohttp
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from aiohttp import web
from discord.ext import tasks

from services.riot_service import RiotClient, DataDragon, RiotError, recent_stats
from services.lol_presentation import (
    demo_data,
    live_embeds,
    build_embeds,
    report_embeds,
    build_recommendation,
    demo_advice,
    fallback_catalog,
)
from services.lol_tracker_repository import LoLRepository
from services.lol_tracker_service import LoLMonitor
from services.pro_live_service import LiveRepository
from cogs.lol_tracker import LoLTracker
from services.lol_channel_service import LoLChannels, LoLChannelError

CATALOG = json.loads((Path(__file__).parent / "fixtures/lol_catalog.json").read_text())


class RiotHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = 200
        self.body = {"puuid": "simulated", "gameName": "Mochila", "tagLine": "bunny"}
        self.count = 0
        self.paths = []
        self.delay = 0
        self.headers = {"Retry-After": "12"}

        async def handle(request):
            self.count += 1
            if self.delay:
                await asyncio.sleep(self.delay)
            self.paths.append(request.path)
            self.assertEqual(request.headers.get("X-Riot-Token"), "dummy-test-key")
            return web.json_response(
                self.body, status=self.status, headers=self.headers
            )

        app = web.Application()
        app.router.add_get("/{path:.*}", handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        self.client = RiotClient("dummy-test-key", interval=0, base_url=self.url)

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def test_account_resolution_escaping_and_cache(self):
        a = await self.client.account("Nome com espaço#BR1")
        self.assertEqual(a["puuid"], "simulated")
        await self.client.account("Nome com espaço#BR1")
        self.assertEqual(self.count, 1)
        self.assertIn("Nome com espaço/BR1", self.paths[0])

    async def test_spectator_404_means_no_game_and_healthy_connection(self):
        self.status = 404
        self.assertIsNone(await self.client.spectator("p"))
        self.assertEqual(self.client.health, "conectada")

    async def test_account_404_is_not_account_success(self):
        self.status = 404
        with self.assertRaises(RiotError) as e:
            await self.client.account("Mochila#bunny")
        self.assertEqual(e.exception.status, 404)

    async def test_forbidden_is_not_no_game(self):
        self.status = 403
        with self.assertRaises(RiotError) as e:
            await self.client.spectator("p")
        self.assertEqual(e.exception.status, 403)
        self.assertIn("403", self.client.health)

    async def test_rate_limit_enforces_shared_retry_after_without_more_calls(self):
        self.status = 429
        with self.assertRaises(RiotError) as e:
            await self.client.spectator("p")
        self.assertEqual(e.exception.retry_after, 12)
        with self.assertRaises(RiotError):
            await self.client.spectator("other")
        self.assertEqual(self.count, 1)

    async def test_transient_service_failure_retries_bounded(self):
        self.status = 503
        with self.assertRaises(RiotError) as e:
            await self.client.spectator("p")
        self.assertEqual(e.exception.status, 503)
        self.assertEqual(self.count, 3)

    async def test_invalid_spectator_200_is_not_success(self):
        self.body = {"status": {"message": "not a game"}}
        with self.assertRaises(RiotError):
            await self.client.spectator("p")

    async def test_delayed_match_404_is_retryable(self):
        self.status = 404
        self.assertIsNone(await self.client.match("BR1_123"))
        self.status = 200
        self.body = {"metadata": {"matchId": "BR1_123"}, "info": {"participants": []}}
        self.assertIsNotNone(await self.client.match("BR1_123"))
        self.assertEqual(self.count, 2)

    async def test_missing_key_never_calls_service(self):
        self.client.key = None
        with self.assertRaises(RiotError):
            await self.client.account("Mochila#bunny")
        self.assertEqual(self.count, 0)

    async def test_riot_id_validation(self):
        for name in ["Mochila", "x#", "#x", ""]:
            with self.assertRaises(ValueError):
                await self.client.account(name)
        self.assertEqual(self.count, 0)

    async def test_timeout_retries_three_times_and_reports_network_failure(self):
        self.delay = 0.05
        self.client.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=0.01)
        )
        with self.assertRaises(RiotError) as error:
            await self.client.spectator("p")
        self.assertEqual(error.exception.status, 0)
        self.assertEqual(self.count, 3)
        self.assertIn("timeout", self.client.health)

    async def test_successful_response_quota_headers_adjust_global_pacing(self):
        self.headers = {"X-App-Rate-Limit": "10:60", "X-App-Rate-Limit-Count": "10:60"}
        await self.client.account("Mochila#bunny")
        self.assertGreaterEqual(self.client.interval, 6)
        with self.assertRaises(RiotError):
            await self.client.spectator("another")
        self.assertEqual(self.count, 1)

    async def test_forbidden_circuit_avoids_repeated_invalid_authentication(self):
        self.status = 403
        for _ in range(2):
            with self.assertRaises(RiotError) as e:
                await self.client.spectator("p")
            self.assertEqual(e.exception.status, 403)
        self.assertEqual(self.count, 1)

    async def test_match_identity_mismatch_rejected(self):
        self.body = {"metadata": {"matchId": "BR1_OTHER"}, "info": {"participants": []}}
        with self.assertRaises(RiotError):
            await self.client.match("BR1_123")

    async def test_official_timeline_route_identity_and_cache(self):
        self.body = {
            "metadata": {"matchId": "BR1_123"},
            "info": {"frames": [{"events": []}]},
        }
        data = await self.client.timeline("BR1_123")
        self.assertEqual(data["metadata"]["matchId"], "BR1_123")
        self.assertTrue(self.paths[-1].endswith("/BR1_123/timeline"))
        await self.client.timeline("BR1_123")
        self.assertEqual(self.count, 1)

    async def test_timeline_wrong_identity_and_invalid_shape_rejected(self):
        for body in [
            {"metadata": {"matchId": "BR1_OTHER"}, "info": {"frames": []}},
            {"metadata": {"matchId": "BR1_123"}, "info": {"frames": None}},
        ]:
            self.client.cache.clear()
            self.body = body
            with self.assertRaises(RiotError):
                await self.client.timeline("BR1_123")


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.game, self.watched, self.context, self.result = demo_data(CATALOG)

    def batches(self):
        return [
            live_embeds(self.game, self.watched, self.context, CATALOG, True),
            build_embeds(self.game, self.watched[0], CATALOG, True),
            report_embeds(self.result, self.watched, self.context, CATALOG, True),
        ]

    def test_all_demo_embeds_are_labeled_and_under_discord_limits(self):
        for batch in self.batches():
            self.assertLessEqual(len(batch), 10)
            self.assertLessEqual(sum(len(e) for e in batch), 6000)
            for e in batch:
                self.assertIn("MODO TESTE", e.title)
                self.assertLessEqual(len(e.fields), 25)
                for f in e.fields:
                    self.assertLessEqual(len(f.name), 256)
                    self.assertLessEqual(len(f.value), 1024)

    def test_live_includes_both_teams_and_history_distinction(self):
        e = self.batches()[0][0]
        self.assertIn("históricos", e.description)
        self.assertIn("Equipe azul", e.fields[0].name)
        self.assertTrue(any("Equipe vermelha" in f.name for f in e.fields))
        self.assertIn("partidas anteriores", str(e.to_dict()))

    def test_ten_watched_players_with_historical_stats_fit_discord(self):
        watched = [
            {"puuid": p["puuid"], "riot_id": p["riotId"], "platform": "BR1"}
            for p in self.game["participants"]
        ]
        context = {p["puuid"]: copy.deepcopy(self.context["DEMO-0"]) for p in watched}
        e = live_embeds(self.game, watched, context, CATALOG)[0]
        self.assertLessEqual(len(e), 6000)
        self.assertLessEqual(len(e.fields), 25)
        for f in e.fields:
            self.assertLessEqual(len(f.value), 1024)
        self.assertIn("WR", str(e.to_dict()))

    def test_hidden_identities_not_looked_up_in_context(self):
        p = self.game["participants"][1]
        p.pop("riotId")
        self.context[p["puuid"]] = {"rank": "SECRET-NAME"}
        e = live_embeds(self.game, self.watched, self.context, CATALOG)[0]
        self.assertNotIn("SECRET-NAME", str(e.to_dict()))
        self.assertIn("Identidade ocultada", str(e.to_dict()))

    def test_builds_use_only_current_available_items_and_no_runes(self):
        p = self.game["participants"][0]
        b = build_recommendation(
            CATALOG, p["championId"], self.game["participants"][5:]
        )
        for i in b["starters"] + b["boots"] + b["core"]:
            self.assertTrue(CATALOG["items"][str(i)]["gold"]["purchasable"])
            self.assertTrue(CATALOG["items"][str(i)]["maps"]["11"])
        embeds = build_embeds(
            self.game, self.watched[0], CATALOG, advice=demo_advice(CATALOG)
        )
        self.assertGreater(len(embeds), 1)
        output = str([e.to_dict() for e in embeds])
        self.assertIn("Riot Match-V5", output)
        self.assertNotIn("runas", output.lower())
        self.assertTrue(
            embeds[1].thumbnail.url.startswith("https://ddragon.leagueoflegends.com/")
        )

    def test_enemy_classes_cannot_create_a_validated_build_without_data(self):
        all_tanks = [{"championId": 54}, {"championId": 54}, {"championId": 16}]
        b = build_recommendation(CATALOG, 103, all_tanks)
        self.assertFalse(b["available"])
        self.assertEqual(b["core"], [])

    def test_unavailable_patch_never_presents_validated_items(self):
        e = build_embeds(self.game, self.watched[0], fallback_catalog())[0]
        self.assertIn("Dados insuficientes", [f.name for f in e.fields])

    def test_post_report_has_computed_stats_and_real_baseline(self):
        e = report_embeds(self.result, self.watched, self.context, CATALOG)[0]
        self.assertIn("VITORIA", e.title)
        self.assertIn("6.33", e.fields[0].value)
        self.assertIn("217 CS", e.fields[1].value)
        self.assertTrue(any(f.name == "Comparação histórica" for f in e.fields))
        self.assertIn("Itens finais", [f.name for f in e.fields])

    def test_missing_fields_are_not_fabricated_as_zero(self):
        result = copy.deepcopy(self.result)
        result["info"]["participants"] = [{"puuid": "DEMO-0"}]
        e = report_embeds(result, self.watched, {}, CATALOG)[0]
        self.assertIn("RESULTADO INDISPONIVEL", e.title)
        self.assertEqual(e.fields[0].value, "indisponivel")
        self.assertEqual(e.fields[2].value, "indisponivel")

    def test_history_averages_only_collected_matches(self):
        s = recent_stats([self.result], "DEMO-0")
        self.assertEqual(s["count"], 1)
        self.assertEqual(s["win_rate"], 100)
        self.assertIsNone(recent_stats([self.result], "other"))


class DataDragonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.count = 0
        self.bad = False

        async def handler(request):
            self.count += 1
            if self.bad:
                return web.json_response({"unexpected": True})
            if request.path.endswith("versions.json"):
                return web.json_response([CATALOG["version"]])
            if request.path.endswith("champion.json"):
                return web.json_response({"data": CATALOG["champions"]})
            return web.json_response({"data": CATALOG["items"]})

        app = web.Application()
        app.router.add_get("/{path:.*}", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.client = DataDragon(
            f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        )

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def test_catalog_version_content_and_cache(self):
        c = await self.client.catalog()
        self.assertEqual(c["version"], CATALOG["version"])
        self.assertTrue(c["items"])
        self.assertIn("103", c["champions"])
        await self.client.catalog()
        self.assertEqual(self.count, 3)

    async def test_http_200_wrong_envelope_rejected(self):
        self.bad = True
        with self.assertRaises(RiotError):
            await self.client.catalog()


class TrackerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = LoLRepository(Path(self.tmp.name) / "bot.sqlite3")
        self.game, self.watched, self.context, self.result = demo_data(CATALOG)
        self.puuid = self.watched[0]["puuid"]
        self.gid = 1
        self.mid = f"BR1_{self.game['gameId']}"
        self.messages = []
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id = 100
        self.channel.guild = NS(id=1)
        self.channel.permissions_for.return_value = NS(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            read_message_history=True,
        )

        async def history(**kwargs):
            for message in reversed(self.messages):
                yield message

        async def send(**kwargs):
            m = NS(
                id=len(self.messages) + 1,
                author=NS(id=999),
                embeds=kwargs["embeds"],
                jump_url=f"https://discord.com/channels/1/100/{len(self.messages) + 1}",
            )

            async def edit(**updated):
                m.embeds = updated["embeds"]

            m.edit = AsyncMock(side_effect=edit)
            self.messages.append(m)
            return m

        self.channel.history = history
        self.channel.send = AsyncMock(side_effect=send)

        async def fetch_message(mid):
            return next(m for m in self.messages if m.id == mid)

        self.channel.fetch_message = AsyncMock(side_effect=fetch_message)
        self.bot = NS(
            user=NS(id=999),
            get_channel=lambda cid: self.channel if cid == 100 else None,
            fetch_channel=AsyncMock(),
        )
        self.riot = AsyncMock(spec=RiotClient)
        self.riot.key = "fake-test-key"
        self.riot.health = "conectada"
        self.riot.spectator.return_value = self.game
        self.riot.rank.return_value = "GOLD II"
        self.riot.history.return_value = [self.result]
        self.riot.mastery.return_value = None
        self.riot.match.return_value = self.result
        self.dd = AsyncMock(spec=DataDragon)
        self.dd.catalog.return_value = CATALOG
        self.sessions = AsyncMock(spec=LoLChannels)
        self.sessions.ensure.return_value = 100
        self.sessions.cleanup.return_value = []
        self.sessions.configure.return_value = NS(id=123)

        async def destination(gid, puuid):
            return (await self.repo.channels()).get(gid)

        self.sessions.channel_for.side_effect = destination
        self.monitor = LoLMonitor(
            self.bot, self.repo, self.riot, self.dd, sessions=self.sessions
        )
        await self.repo.configure(1, 100)
        await self.repo.configure_sessions(1, 123, None)
        await self.repo.follow(1, self.puuid, "Mochila#bunny")

    async def test_follow_duplicate_remove_and_reactivate_persist(self):
        self.assertFalse(await self.repo.follow(1, self.puuid, "Mochila#bunny"))
        self.assertTrue(await self.repo.unfollow(1, "MOCHILA#BUNNY"))
        self.assertEqual(await self.repo.players(1), [])
        self.assertTrue(await self.repo.follow(1, self.puuid, "Mochila#bunny"))
        repo = LoLRepository(self.repo.path)
        self.assertEqual((await repo.players(1))[0]["puuid"], self.puuid)
        self.assertEqual(await repo.channels(), {1: 100})

    async def test_schema_namespaces_preserve_existing_bot_tables(self):
        live = LiveRepository(self.repo.path)
        await live.subscribe(5, 500)
        await self.repo.follow(1, "another", "Other#TAG")
        self.assertEqual(await live.subscriptions(), {5: 500})

    async def test_automatic_live_build_then_no_repeat_after_restart(self):
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        player = (await self.repo.players(1))[0]
        self.assertEqual(player["current_match"], self.mid)
        self.assertEqual(player["last_notified"], self.mid)
        monitor = LoLMonitor(
            self.bot,
            LoLRepository(self.repo.path),
            self.riot,
            self.dd,
            sessions=self.sessions,
        )
        await monitor.poll()
        self.assertEqual(len(self.messages), 2)

    async def test_delayed_match_result_then_final_report_once(self):
        await self.monitor.poll()
        self.riot.spectator.return_value = None
        self.riot.match.return_value = None
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        self.assertEqual((await self.repo.matches())[0]["phase"], "waiting")
        self.riot.match.return_value = self.result
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 3)
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 3)
        self.assertEqual(await self.repo.matches(), [])

    async def test_riot_error_does_not_end_game_or_duplicate_live(self):
        await self.monitor.poll()
        self.riot.spectator.side_effect = RiotError(403, "sem autorizacao")
        await self.monitor.poll()
        self.riot.match.assert_not_awaited()
        self.assertEqual(len(self.messages), 2)
        self.assertEqual((await self.repo.matches())[0]["phase"], "live")

    async def test_two_tracked_teammates_get_individual_live_build_and_report(self):
        other = self.game["participants"][1]["puuid"]
        await self.repo.follow(1, other, "Outro#TESTE")
        second = copy.deepcopy(self.result["info"]["participants"][0])
        second["puuid"] = other
        self.result["info"]["participants"].append(second)
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 4)
        self.riot.spectator.return_value = None
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 6)
        self.assertEqual(len(self.messages[-1].embeds), 1)

    async def test_successful_send_before_ack_recovered_from_history(self):
        game = live_embeds(self.game, self.watched, self.context, CATALOG)
        with patch.object(
            self.repo,
            "acknowledge",
            side_effect=RuntimeError("simulated process interruption"),
        ):
            with self.assertRaises(RuntimeError):
                await self.monitor.deliver(1, self.mid, "live", self.puuid, game)
        self.assertEqual(len(self.messages), 1)
        monitor = LoLMonitor(
            self.bot,
            LoLRepository(self.repo.path),
            self.riot,
            self.dd,
            sessions=self.sessions,
        )
        self.assertTrue(await monitor.deliver(1, self.mid, "live", self.puuid, game))
        self.assertEqual(len(self.messages), 1)

    async def test_send_failure_remains_pending_then_retries(self):
        effect = self.channel.send.side_effect
        self.channel.send.side_effect = discord.Forbidden(
            NS(status=403, reason="Forbidden"), "test"
        )
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 0)
        self.channel.send.side_effect = effect
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)

    async def test_no_destination_means_no_riot_queries_and_no_sends(self):
        await self.repo._run(lambda c: c.execute("DELETE FROM lol_channel_config"))
        await self.monitor.poll()
        self.riot.spectator.assert_not_awaited()
        self.assertEqual(len(self.messages), 0)

    async def test_other_guild_and_wrong_destination_not_leaked(self):
        await self.repo.configure(2, 100)
        await self.repo.configure_sessions(2, 123, None)
        await self.repo.follow(2, self.puuid, "Mochila#bunny")
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        self.assertFalse(
            await self.monitor.deliver(
                2,
                self.mid,
                "live",
                self.puuid,
                live_embeds(self.game, self.watched, {}, CATALOG),
            )
        )

    async def test_unfollow_stops_only_that_player(self):
        await self.repo.follow(1, "other", "Outro#TESTE")
        self.assertTrue(await self.repo.unfollow(1, "Mochila#bunny"))
        self.assertEqual([p["puuid"] for p in await self.repo.players(1)], ["other"])

    async def test_missing_key_preserves_players_without_queries(self):
        self.riot.key = None
        await self.monitor.poll()
        self.riot.spectator.assert_not_awaited()
        self.assertIn("RIOT_API_KEY", self.monitor.last_error)

    async def test_live_is_sent_before_history_then_enriched_by_edit(self):
        async def history(puuid, platform, **kwargs):
            self.assertEqual(len(self.messages), 1)
            return [self.result]

        self.riot.history.side_effect = history
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        self.messages[0].edit.assert_awaited_once()
        self.assertEqual(self.riot.history.await_count, 10)
        self.assertEqual(self.riot.mastery.await_count, 10)

    async def test_partial_hidden_identity_does_not_requery_entire_roster_each_tick(
        self,
    ):
        hidden = self.game["participants"][9]
        hidden.pop("riotId")
        hidden["riotIdGameName"] = "Hidden partial name"
        await self.monitor.poll()
        calls = self.riot.history.await_count
        self.assertEqual(calls, 9)
        await self.monitor.poll()
        self.assertEqual(self.riot.history.await_count, calls)

    async def test_enrichment_does_not_query_hidden_opponent(self):
        hidden = self.game["participants"][9]
        hidden.pop("riotId")
        await self.monitor._context(self.game, self.watched)
        self.assertNotIn(
            hidden["puuid"],
            [call.args[0] for call in self.riot.history.await_args_list],
        )
        self.assertNotIn(
            hidden["puuid"], [call.args[0] for call in self.riot.rank.await_args_list]
        )

    async def test_channel_change_routes_next_notification_only_to_new_channel(self):
        await self.monitor.poll()
        old_send = self.channel.send
        other = MagicMock(spec=discord.TextChannel)
        other.id = 101
        other.guild = NS(id=1)

        async def history(**kwargs):
            if False:
                yield None

        other.history = history
        other.send = AsyncMock(return_value=NS(id=987))
        self.bot.get_channel = lambda cid: other if cid == 101 else self.channel
        self.sessions.channel_for.side_effect = None
        self.sessions.channel_for.return_value = 101
        self.riot.spectator.return_value = None
        await self.monitor.poll()
        other.send.assert_awaited_once()
        self.assertEqual(old_send.await_count, 2)

    async def test_unfollow_cancels_game_and_reactivation_never_sends_old_report(self):
        await self.monitor.poll()
        await self.repo.unfollow(1, "Mochila#bunny")
        self.assertEqual(await self.repo.matches(), [])
        await self.repo.follow(1, self.puuid, "Mochila#bunny")
        self.riot.spectator.return_value = None
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        self.riot.match.assert_not_awaited()

    async def test_context_excludes_current_game_from_historical_baseline(self):
        current = copy.deepcopy(self.result)
        current["metadata"]["matchId"] = self.mid
        self.riot.history.return_value = [current]
        context = await self.monitor._context(self.game, self.watched)
        self.assertIsNone(context[self.puuid]["recent"])

    async def test_data_dragon_failure_defers_build_and_recovers_later(self):
        self.dd.catalog.side_effect = RiotError(0, "network")
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 1)
        self.dd.catalog.side_effect = None
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)

    async def test_simultaneous_ticks_are_serialized(self):
        await asyncio.gather(self.monitor.poll(), self.monitor.poll())
        self.assertEqual(len(self.messages), 2)

    async def test_build_collection_or_source_failure_does_not_interrupt_tracking(self):
        self.monitor.builds.ingest = AsyncMock(
            side_effect=RuntimeError("cache failure")
        )
        self.monitor.builds.advise = AsyncMock(
            side_effect=RiotError(503, "source unavailable")
        )
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        self.assertTrue(
            any(
                f.name == "Dados insuficientes"
                for f in self.messages[1].embeds[0].fields
            )
        )
        self.riot.spectator.return_value = None
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 3)

    async def test_build_source_update_edits_the_existing_message_without_duplicates(
        self,
    ):
        from services.lol_builds import insufficient

        first = insufficient(CATALOG, "Sem amostra", 0)
        next_data = insufficient(CATALOG, "Amostra ainda insuficiente", 2)
        self.monitor.builds.advise = AsyncMock(side_effect=[first, next_data])
        await self.monitor.poll()
        await self.monitor.poll()
        self.assertEqual(len(self.messages), 2)
        self.messages[1].edit.assert_awaited_once()
        self.assertIn("2 partidas", str(self.messages[1].embeds[0].to_dict()))

    def cog(self):
        cog = object.__new__(LoLTracker)
        cog.bot, cog.repository, cog.riot, cog.ddragon, cog.monitor = (
            self.bot,
            self.repo,
            self.riot,
            self.dd,
            self.monitor,
        )
        return cog

    def ctx(self, admin=True):
        return NS(
            guild=NS(id=1, owner_id=9999, me=NS()),
            channel=NS(category=None),
            author=NS(
                id=10, guild_permissions=NS(administrator=admin, manage_guild=False)
            ),
            send=AsyncMock(),
        )

    async def test_demo_sends_exactly_three_labeled_messages_to_configured_channel(
        self,
    ):
        ctx = self.ctx()
        await LoLTracker.demo.callback(self.cog(), ctx)
        self.assertEqual(len(self.messages), 3)
        self.assertTrue(
            all("MODO TESTE" in e.title for m in self.messages for e in m.embeds)
        )
        self.assertEqual(len(self.messages[1].embeds), 6)
        self.assertIn("https://discord.com/channels/1/100/", ctx.send.call_args.args[0])

    async def test_demo_denies_missing_lol_role_and_nonadmin(self):
        await LoLTracker.demo.callback(self.cog(), self.ctx(False))
        self.assertEqual(len(self.messages), 0)
        self.sessions.configure.side_effect = LoLChannelError("Cargo LOL ausente")
        await LoLTracker.demo.callback(self.cog(), self.ctx())
        self.assertEqual(len(self.messages), 0)

    async def test_legacy_channel_command_only_sets_category_and_checks_guild(self):
        cog = self.cog()
        ctx = self.ctx()
        self.channel.guild.id = 2
        await LoLTracker.channel.callback(cog, ctx, self.channel)
        self.sessions.configure.assert_not_awaited()
        self.channel.guild.id = 1
        await LoLTracker.channel.callback(cog, ctx, self.channel)
        self.sessions.configure.assert_awaited_once_with(
            ctx.guild, self.channel.category
        )
        self.channel.send.assert_not_awaited()

    async def test_command_registration_preserves_old_lol_commands(self):
        from bot import create_bot

        async with create_bot() as bot:
            with patch.object(tasks.Loop, "start"):
                await bot.load_extension("cogs.esports")
                await bot.load_extension("cogs.lol_tracker")
            for name in [
                "lol canal",
                "lol status",
                "lol hoje",
                "cs2 canal",
                "valorant hoje",
                "loltrack canal",
                "loltrack seguir",
                "loltrack deixar",
                "loltrack lista",
                "loltrack status",
                "loltrack teste",
            ]:
                self.assertIsNotNone(bot.get_command(name), name)
            self.assertEqual(bot.tree.get_commands(), [])

    async def test_follow_command_handles_not_found_and_duplicate(self):
        cog = self.cog()
        ctx = self.ctx()
        self.riot.account.side_effect = RiotError(404, "not found")
        await LoLTracker.follow.callback(cog, ctx, riot_id="Mochila#bunny")
        self.assertIn("nao encontrada", ctx.send.call_args.args[0])
        self.riot.account.side_effect = None
        self.riot.account.return_value = {
            "puuid": self.puuid,
            "gameName": "Mochila",
            "tagLine": "bunny",
        }
        await LoLTracker.follow.callback(cog, ctx, riot_id="Mochila#bunny")
        self.assertIn("ja estava", ctx.send.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
