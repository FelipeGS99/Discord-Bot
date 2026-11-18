from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from aiohttp import web

from cogs.pro_lives import ProLives, live_embed
from services.pro_live_platforms import (
    LiveState, PlatformClient, PlatformError, parse_bilibili, parse_chzzk_page,
    parse_douyu, parse_huya, parse_soop, retry_seconds,
)
from services.pro_live_service import Account, Catalog, Delivery, LiveMonitor, LiveRepository, load_catalog


NOW = datetime.now(timezone.utc)


def player(**overrides):
    value = {
        "id": "fixture-player", "name": "Fixture", "team": "Fixture team",
        "league": "LPL", "division": 1, "role": "MID", "active": True,
        "verified_at": (NOW - timedelta(hours=1)).isoformat(),
        "valid_until": (NOW + timedelta(days=6)).isoformat(),
        "roster_sources": ["https://example.com/official-roster"],
        "channels": [{"platform": "douyu", "channel_id": "123",
                      "verified_at": NOW.isoformat(), "source_urls": ["https://example.com/official-channel"]}],
    }
    value.update(overrides)
    return value


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "roster.json"

    def load(self, *players):
        self.path.write_text(json.dumps({"schema_version": 1, "players": list(players)}))
        return load_catalog(self.path, NOW)

    def test_accepts_all_roles_and_nationalities(self):
        for role in ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT"):
            with self.subTest(role=role):
                result = self.load(player(role=role, nationality="KR"))
                self.assertEqual(result.accounts[0].role, role)
                self.assertEqual(result.accounts[0].league, "LPL")

    def test_excludes_other_leagues_divisions_and_nonplayers(self):
        for overrides in ({"league": "LCK CL"}, {"division": 2},
                          {"role": "STREAMER"}, {"role": "COACH"}, {"division": True}):
            with self.subTest(overrides=overrides):
                result = self.load(player(**overrides))
                self.assertEqual(result.accounts, ())
                self.assertEqual(result.excluded_players, 1)

    def test_review_dates_warn_without_removing_players_or_channels(self):
        cases = [
            {"valid_until": NOW.isoformat()},
            {"verified_at": (NOW + timedelta(hours=1)).isoformat()},
            {"valid_until": (NOW + timedelta(days=8)).isoformat()},
        ]
        for data in cases:
            with self.subTest(data=data):
                result = self.load(player(**data))
                self.assertEqual(len(result.accounts), 1)
                self.assertEqual(result.eligible_players, 1)
                self.assertEqual(result.excluded_players, 0)
                self.assertEqual(result.review_warnings[0].player_id, "fixture-player")

    def test_unconfirmed_channels_not_inferred_from_name(self):
        result = self.load(player(channels=[]))
        self.assertEqual(result.eligible_players, 1)
        self.assertFalse(result.accounts)

    def test_stale_channel_verification_warns_and_preserves_channel(self):
        item = player()
        item["channels"][0]["verified_at"] = (NOW - timedelta(days=31)).isoformat()
        result = self.load(item)
        self.assertEqual(result.accounts[0].channel_id, "123")
        self.assertIn("30 dias", result.review_warnings[0].message)

    def test_expired_or_unconfirmed_contract_keeps_competitive_eligibility(self):
        for contract in ("unknown", "confirmed", "expired", "renewal_unconfirmed"):
            with self.subTest(contract=contract):
                result = self.load(player(competitive_status="tier1", contract_status=contract,
                                          valid_until=NOW.isoformat()))
                self.assertEqual(len(result.accounts), 1)
                self.assertEqual(result.excluded_players, 0)
                self.assertTrue(result.review_warnings)

    def test_unconfirmed_competitive_status_and_legacy_inactive_flag_are_not_departure(self):
        for overrides in ({"competitive_status": "unconfirmed"}, {"active": False},
                          {"competitive_status": "tier1", "active": False}):
            with self.subTest(overrides=overrides):
                result = self.load(player(**overrides))
                self.assertEqual(len(result.accounts), 1)
                self.assertTrue(result.review_warnings)

    def test_departure_without_complete_effective_confirmation_keeps_monitoring(self):
        for confirmation in (None, {}, {"reason": "Rumor"},
                             {"sources": ["https://example.com/official-departure"]},
                             {"sources": [], "verified_at": NOW.isoformat(), "reason": "Unconfirmed"},
                             {"sources": ["https://example.com/official-departure"],
                              "verified_at": (NOW + timedelta(days=1)).isoformat(), "reason": "Future decision"}):
            with self.subTest(confirmation=confirmation):
                result = self.load(player(active=False, competitive_status="out_of_scope",
                                          competitive_status_confirmation=confirmation))
                self.assertEqual(len(result.accounts), 1)
                self.assertTrue(result.review_warnings)

    def test_confirmed_tier1_departure_excludes_even_with_current_contract(self):
        result = self.load(player(competitive_status="out_of_scope", contract_status="confirmed",
                                  competitive_status_confirmation={
                                      "sources": ["https://example.com/official-departure"],
                                      "verified_at": NOW.isoformat(), "reason": "Retirement confirmed by team"}))
        self.assertFalse(result.accounts)
        self.assertEqual(result.excluded_players, 1)

    def test_invalid_competitive_or_contract_metadata_fails_explicitly(self):
        for overrides in ({"competitive_status": "typo"}, {"contract_status": "typo"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.load(player(**overrides))

    def test_future_channel_verification_warns_without_removing_channel(self):
        item = player()
        item["channels"][0]["verified_at"] = (NOW + timedelta(days=1)).isoformat()
        result = self.load(item)
        self.assertEqual(len(result.accounts), 1)
        self.assertTrue(result.review_warnings)

    def test_expired_reviews_do_not_hide_duplicate_channels(self):
        with self.assertRaises(ValueError):
            self.load(player(valid_until=NOW.isoformat()), player(id="another"))

    def test_actual_catalog_keeps_33_players_34_channels_after_all_review_dates(self):
        path = Path(__file__).resolve().parent.parent / "pro_lives_roster.json"
        raw = json.loads(path.read_text())
        expected = {(p["id"], c["platform"], c["channel_id"]) for p in raw["players"]
                    for c in p["channels"] if c["platform"] != "twitch"}
        for at in (datetime(2026, 11, 17, tzinfo=timezone.utc),
                   datetime(2026, 11, 24, tzinfo=timezone.utc),
                   datetime(2027, 2, 1, tzinfo=timezone.utc)):
            with self.subTest(at=at):
                catalog = load_catalog(path, at)
                original_accounts = [a for a in catalog.accounts if a.platform != "twitch"]
                self.assertEqual(len({a.player_id for a in original_accounts}), 33)
                self.assertEqual(len(original_accounts), 34)
                self.assertEqual(catalog.excluded_players, 0)
                self.assertEqual({(a.player_id, a.platform, a.channel_id) for a in original_accounts}, expected)
                overdue = {w.player_id for w in catalog.review_warnings}
                self.assertTrue({"flandre", "viper"} <= overdue)

    def test_rejects_sources_missing_timezone_and_cross_league_platform(self):
        cases = [player(roster_sources=[]), player(verified_at="2026-11-16T00:00:00"), player(league="LCK")]
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    self.load(item)

    def test_rejects_duplicate_channel_associations_and_player_ids(self):
        first = player()
        second = player(id="another", name="Another")
        with self.assertRaises(ValueError):
            self.load(first, second)
        with self.assertRaises(ValueError):
            self.load(first, copy.deepcopy(first))

    def test_rejects_urls_as_channel_ids(self):
        item = player()
        item["channels"][0]["channel_id"] = "https://www.douyu.com/123"
        with self.assertRaises(ValueError):
            self.load(item)


class ParserTests(unittest.TestCase):
    def test_douyu_live_offline_replay_and_wrong_room(self):
        room = {"room_id": 123, "show_status": 1, "videoLoop": 0, "show_id": 456, "room_name": "Fixture"}
        self.assertEqual(parse_douyu({"room": room}, "123").session_id, "456")
        for change in ({"show_status": 2}, {"videoLoop": 1}):
            self.assertFalse(parse_douyu({"room": dict(room, **change)}, "123").live)
        with self.assertRaises(PlatformError):
            parse_douyu({"room": room}, "999")
        with self.assertRaises(PlatformError):
            parse_douyu({"room": dict(room, show_status="captcha")}, "123")

    def test_huya_strict_json_no_script_execution(self):
        room = {"profileRoom": 123, "state": "ON", "isOn": True, "isReplay": False,
                "liveId": "456", "introduction": "Fixture"}
        def page(data): return "<script>var TT_ROOM_DATA = " + json.dumps(data) + "; dangerous();</script>"
        self.assertEqual(parse_huya(page(room), "123").session_id, "456")
        self.assertFalse(parse_huya(page(dict(room, isReplay=True)), "123").live)
        self.assertFalse(parse_huya(page(dict(room, state="OFF", isOn=False)), "123").live)
        for content in ("<html>challenge</html>", page(dict(room, profileRoom=999))):
            with self.assertRaises(PlatformError): parse_huya(content, "123")

    def test_bilibili_live_replay_offline_and_block(self):
        room = {"room_id": 123, "live_status": 1, "live_time": "2026-11-16 16:00:00", "title": "Fixture"}
        self.assertTrue(parse_bilibili({"code": 0, "data": room}, "123").live)
        for status in (0, 2):
            self.assertFalse(parse_bilibili({"code": 0, "data": dict(room, live_status=status)}, "123").live)
        with self.assertRaises(PlatformError): parse_bilibili({"code": -412}, "123")

    def test_soop_ambiguous_result_is_never_offline(self):
        station = {"station": {"userId": "fixture", "stationNo": 123, "userNick": "Fixture"}}
        self.assertEqual(parse_soop({"CHANNEL": {"RESULT": 1, "BJID": "fixture", "BNO": "456", "TITLE": "Fixture"}}, "fixture", station).session_id, "456")
        for code in (0, -6, -7):
            with self.assertRaises(PlatformError): parse_soop({"CHANNEL": {"RESULT": code}}, "fixture", {})

    def test_chzzk_official_envelope_and_pagination(self):
        page = {"code": 200, "content": {"data": [{"channelId": "a" * 32, "liveId": 456, "liveTitle": "Fixture"}], "page": {"next": "cursor"}}}
        found, cursor = parse_chzzk_page(page)
        self.assertEqual(found["a" * 32].session_id, "456")
        self.assertEqual(cursor, "cursor")
        with self.assertRaises(PlatformError): parse_chzzk_page({"code": 401})

    def test_retry_after_seconds_and_date(self):
        self.assertEqual(retry_seconds("600"), 600)
        self.assertGreaterEqual(retry_seconds("Wed, 01 Jan 2031 00:00:00 GMT"), 60)
        self.assertEqual(retry_seconds(None), 300)


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "lives.sqlite3"
        self.repo = LiveRepository(self.path)
        await self.repo.subscribe(1, 10)

    async def test_first_live_baseline_does_not_spam(self):
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])
        await self.repo.observe({"a": LiveState(False)})
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])

    async def test_transition_restart_and_per_target_acknowledgement(self):
        await self.repo.subscribe(2, 20)
        await self.repo.observe({"a": LiveState(False)})
        jobs = await self.repo.observe({"a": LiveState(True, "s1", "Title")})
        self.assertEqual(len(jobs), 2)
        await self.repo.acknowledge(jobs[0])
        # New repository object reads the persisted session/outbox.
        restarted = LiveRepository(self.path)
        retry = await restarted.observe({"a": LiveState(True, "s1")})
        self.assertEqual(len(retry), 1)
        self.assertNotEqual(retry[0].guild_id, jobs[0].guild_id)
        await restarted.acknowledge(retry[0])
        self.assertEqual(await restarted.observe({"a": LiveState(True, "s1")}), [])
        self.assertEqual(len(await restarted.observe({"a": LiveState(True, "s2")})), 2)

    async def test_failed_consultation_does_not_become_offline(self):
        await self.repo.observe({"a": LiveState(True, "s1")})
        await self.repo.observe({})
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])

    async def test_disable_and_channel_change_remove_pending_targets(self):
        await self.repo.observe({"a": LiveState(False)})
        await self.repo.observe({"a": LiveState(True, "s1")})
        await self.repo.subscribe(1, None)
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])
        await self.repo.subscribe(1, 11)
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])
        jobs = await self.repo.observe({"a": LiveState(True, "s2")})
        self.assertEqual(jobs[0].channel_id, 11)

    async def test_pending_expires_and_old_sessions_not_sent(self):
        await self.repo.observe({"a": LiveState(False)}, now=100)
        await self.repo.observe({"a": LiveState(True, "s1")}, now=101)
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}, now=2000), [])
        jobs = await self.repo.observe({"a": LiveState(True, "s2")}, now=2001)
        self.assertEqual([j.session_id for j in jobs], ["s2"])

    async def test_acknowledged_session_not_resent_after_offline_glitch(self):
        await self.repo.observe({"a": LiveState(False)})
        jobs = await self.repo.observe({"a": LiveState(True, "s1")})
        await self.repo.acknowledge(jobs[0])
        await self.repo.observe({"a": LiveState(False)})
        self.assertEqual(await self.repo.observe({"a": LiveState(True, "s1")}), [])


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "roster.json"
        self.path.write_text(json.dumps({"schema_version": 1, "players": [player()]}))
        self.repo = LiveRepository(Path(self.tmp.name) / "db")
        await self.repo.subscribe(1, 10)
        self.client = SimpleNamespace(check=AsyncMock(return_value=LiveState(False)), chzzk=AsyncMock())
        self.monitor = LiveMonitor(self.path, self.repo, self.client)

    async def test_failure_isolated_and_no_duplicate_after_recovery(self):
        await self.monitor.poll()
        self.client.check.return_value = LiveState(True, "456")
        jobs = await self.monitor.poll()
        self.assertEqual(len(jobs), 1)
        await self.repo.acknowledge(jobs[0])
        self.client.check.side_effect = PlatformError("HTTP 412")
        self.assertEqual(await self.monitor.poll(), [])
        self.assertIn("HTTP 412", next(iter(self.monitor.health.values())))
        self.client.check.side_effect = None
        self.assertEqual(await self.monitor.poll(), [])

    async def test_invalid_catalog_never_uses_cached_accounts(self):
        await self.monitor.poll()
        self.path.write_text("{invalid")
        self.client.check.reset_mock()
        self.assertEqual(await self.monitor.poll(), [])
        self.assertFalse(self.monitor.catalog.accounts)
        self.assertIsNotNone(self.monitor.catalog_error)
        self.client.check.assert_not_called()

    async def test_expiry_does_not_interrupt_checks_or_duplicate_after_restart(self):
        clock = [NOW]
        with patch("services.pro_live_service.load_catalog", side_effect=lambda path: load_catalog(path, clock[0])):
            self.assertEqual(await self.monitor.poll(), [])
            self.client.check.return_value = LiveState(True, "persistent-session")
            jobs = await self.monitor.poll()
            self.assertEqual(len(jobs), 1)
            await self.repo.acknowledge(jobs[0])
            clock[0] = NOW + timedelta(days=60)
            restarted_repo = LiveRepository(self.repo.path)
            restarted = LiveMonitor(self.path, restarted_repo, self.client)
            self.client.check.reset_mock()
            self.assertEqual(await restarted.poll(), [])
            self.client.check.assert_awaited_once()
            self.assertTrue(restarted.catalog.review_warnings)
            self.assertEqual(len(restarted.catalog.accounts), 1)
            self.client.check.return_value = LiveState(False)
            self.assertEqual(await restarted.poll(), [])
            self.client.check.return_value = LiveState(True, "persistent-session")
            self.assertEqual(await restarted.poll(), [])
            self.client.check.return_value = LiveState(True, "new-session")
            self.assertEqual(len(await restarted.poll()), 1)

    async def test_confirmed_departure_stops_queries_but_preserves_history(self):
        await self.monitor.poll()
        self.client.check.return_value = LiveState(True, "session")
        jobs = await self.monitor.poll()
        await self.repo.acknowledge(jobs[0])
        value = json.loads(self.path.read_text())
        value["players"][0].update(competitive_status="out_of_scope", competitive_status_confirmation={
            "verified_at": NOW.isoformat(), "sources": ["https://example.com/official-departure"],
            "reason": "Confirmed move to Academy"})
        self.path.write_text(json.dumps(value))
        self.client.check.reset_mock()
        self.assertEqual(await self.monitor.poll(), [])
        self.client.check.assert_not_called()
        self.assertEqual(self.monitor.catalog.excluded_players, 1)
        value["players"][0]["competitive_status"] = "tier1"
        self.path.write_text(json.dumps(value))
        self.assertEqual(await self.monitor.poll(), [])
        self.assertTrue(self.monitor.catalog.accounts)

    async def test_pending_notification_survives_review_expiry(self):
        await self.monitor.poll()
        self.client.check.return_value = LiveState(True, "pending-session")
        pending = await self.monitor.poll()
        self.assertEqual(len(pending), 1)
        item = player(valid_until=NOW.isoformat(), contract_status="expired")
        self.path.write_text(json.dumps({"schema_version": 1, "players": [item]}))
        restarted = LiveMonitor(self.path, LiveRepository(self.repo.path), self.client)
        self.assertEqual(await restarted.poll(), pending)
        await restarted.repository.acknowledge(pending[0])
        self.assertEqual(await restarted.poll(), [])

    async def test_no_network_without_subscribers(self):
        await self.repo.subscribe(1, None)
        await self.monitor.poll()
        self.client.check.assert_not_called()

    async def test_accounts_run_concurrently_and_failure_does_not_stop_other_platform(self):
        item = player(id="other", name="Other")
        item["channels"][0].update(platform="huya", channel_id="456")
        self.path.write_text(json.dumps({"schema_version": 1, "players": [player(), item]}))
        entered = set()
        async def check(platform, channel):
            entered.add(platform)
            for _ in range(100):
                if len(entered) == 2: break
                await asyncio.sleep(0)
            self.assertEqual(len(entered), 2, "requests ran sequentially")
            if platform == "huya": raise PlatformError("HTTP 403")
            return LiveState(False)
        self.client.check.side_effect = check
        await self.monitor.poll()
        self.assertIn("ok", self.monitor.health.values())
        self.assertIn("HTTP 403", self.monitor.health.values())


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = PlatformClient()
        self.runner = None

    async def asyncTearDown(self):
        await self.client.close()
        if self.runner: await self.runner.cleanup()

    async def serve(self, handler):
        app = web.Application()
        app.router.add_get("/", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/"

    async def test_chunked_response_fully_read(self):
        async def handler(request):
            response = web.StreamResponse(headers={"Content-Type": "application/json"})
            await response.prepare(request)
            await response.write(b'{"value":')
            await asyncio.sleep(.01)
            await response.write(b'123}')
            await response.write_eof()
            return response
        url = await self.serve(handler)
        self.assertEqual(await self.client.request("douyu", url), {"value": 123})

    async def test_429_cooldown_and_no_response_body_in_errors(self):
        calls = []
        async def handler(request):
            calls.append(1)
            return web.Response(status=429, text="sensitive-response", headers={"Retry-After": "600"})
        url = await self.serve(handler)
        with self.assertRaises(PlatformError) as found: await self.client.request("douyu", url)
        self.assertNotIn("sensitive", str(found.exception))
        with self.assertRaises(PlatformError): await self.client.request("douyu", url)
        self.assertEqual(len(calls), 1)

    async def test_chzzk_full_pagination_and_incomplete_never_offline(self):
        pages = [
            {"code": 200, "content": {"data": [{"channelId": "a", "liveId": 1, "liveTitle": "Fixture"}], "page": {"next": "two"}}},
            {"code": 200, "content": {"data": [], "page": {}}},
        ]
        with patch.dict("os.environ", {"CHZZK_CLIENT_ID": "fixture", "CHZZK_CLIENT_SECRET": "fixture"}):
            self.client.request = AsyncMock(side_effect=pages)
            result = await self.client.chzzk(["a", "b"])
            self.assertTrue(result["a"].live)
            self.assertFalse(result["b"].live)
            self.client.request = AsyncMock(return_value=pages[0])
            with self.assertRaises(PlatformError): await self.client.chzzk(["b"])


class CogTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_exposes_contract_and_review_warnings_with_33_players(self):
        with patch.object(ProLives.check_pro_lives, "start"):
            cog = ProLives(MagicMock())
        try:
            catalog_path = Path(__file__).resolve().parent.parent / "pro_lives_roster.json"
            catalog = load_catalog(catalog_path, datetime(2026, 11, 17, tzinfo=timezone.utc))
            cog.monitor.catalog = catalog
            cog.monitor.reload = AsyncMock()
            cog.repository = SimpleNamespace(subscriptions=AsyncMock(return_value={}))
            ctx = SimpleNamespace(guild=SimpleNamespace(id=1), send=AsyncMock())
            await ProLives.status.callback(cog, ctx)
            output = "\n".join(call.kwargs["embed"].description for call in ctx.send.await_args_list)
            linked = len({a.player_id for a in catalog.accounts})
            self.assertIn(f"{linked} jogadores com {len(catalog.accounts)} contas", output)
            self.assertIn("Flandre", output)
            self.assertIn("Viper", output)
            self.assertIn("Prazo de revisão vencido", output)
            self.assertIn("Renovação contratual não confirmada", output)
            self.assertIn("monitoramento mantido", output)
            self.assertTrue(all(len(call.kwargs["embed"].description) <= 1900 for call in ctx.send.await_args_list))
        finally:
            await cog.cog_unload()

    async def test_all_bot_extensions_and_pro_live_commands_load_and_unload(self):
        from bot import COGS, create_bot
        async with create_bot() as bot:
            await bot.setup_hook()
            self.assertEqual(len(bot.extensions), len(COGS))
            command = bot.get_command("prolives")
            self.assertIsNotNone(command)
            self.assertEqual({c.name for c in command.commands},
                             {"canal", "parar", "status", "jogadores", "recarregar"})
        self.assertTrue(bot.is_closed())
        self.assertFalse(bot.extensions)

    async def test_failed_destination_does_not_ack_or_prevent_other_delivery(self):
        bot = MagicMock()
        first = MagicMock(spec=discord.TextChannel)
        first.guild = SimpleNamespace(id=1)
        first.send = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied"))
        second = MagicMock(spec=discord.TextChannel)
        second.guild = SimpleNamespace(id=2)
        second.send = AsyncMock()
        bot.get_channel.side_effect = lambda id: {10: first, 20: second}[id]
        with patch.object(ProLives.check_pro_lives, "start"):
            cog = ProLives(bot)
        cog.repository = SimpleNamespace(subscriptions=AsyncMock(return_value={1: 10, 2: 20}), acknowledge=AsyncMock())
        account = Account("fixture", "Fixture", "Team", "LPL", "MID", "douyu", "123")
        jobs = [Delivery(account.key, "s1", 1, 10, "Fixture"), Delivery(account.key, "s1", 2, 20, "Fixture")]
        await asyncio.gather(*(cog._deliver(job, {account.key: account}) for job in jobs))
        cog.repository.acknowledge.assert_awaited_once_with(jobs[1])
        second.send.assert_awaited_once()
        self.assertIn(1, cog.delivery_errors)
        self.assertEqual(live_embed(account, jobs[1]).url, "https://www.douyu.com/123")
        await cog.cog_unload()

    async def test_disabled_destination_not_sent(self):
        with patch.object(ProLives.check_pro_lives, "start"):
            cog = ProLives(MagicMock())
        cog.repository = SimpleNamespace(subscriptions=AsyncMock(return_value={}), acknowledge=AsyncMock())
        await cog._deliver(Delivery("a", "s", 1, 10, "Title"), {})
        cog.bot.get_channel.assert_not_called()
        await cog.cog_unload()
