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

from cogs.pro_lives import ProLives
from services.pro_live_platforms import PlatformClient, PlatformError, parse_soop
from services.pro_live_service import LiveMonitor, LiveRepository


CAPTURED = json.loads((Path(__file__).parent / "fixtures" / "soop_status.json").read_text(encoding="utf-8"))


class SoopParserTests(unittest.TestCase):
    def test_real_public_online_and_offline_captures(self):
        for name, expected in (("online", True), ("offline", False)):
            with self.subTest(state=name):
                sample = CAPTURED[name]
                channel_id = sample["station"]["station"]["userId"]
                state = parse_soop(sample["player"], channel_id, sample["station"])
                self.assertEqual(state.live, expected)
                if expected:
                    self.assertEqual(state.session_id, sample["player"]["CHANNEL"]["BNO"])
                    self.assertEqual(state.title, sample["player"]["CHANNEL"]["TITLE"])
                else:
                    self.assertEqual(state.session_id, "")

    def test_result_zero_without_valid_station_never_means_offline(self):
        sample = CAPTURED["offline"]
        for station in (None, {}, [], {"station": None}, {"station": {}},
                        {"station": {"userId": "different", "stationNo": 123, "userNick": "Other"}}):
            with self.subTest(station=station), self.assertRaises(PlatformError):
                parse_soop(sample["player"], "rldls5656", station)

    def test_restrictions_and_malformed_codes_are_unknown_even_with_valid_station(self):
        station = CAPTURED["offline"]["station"]
        for code in (-1, -2, -5, -6, -7, -8, -10, -13, 2, None, False, True, "0", "1"):
            with self.subTest(code=code), self.assertRaises(PlatformError):
                parse_soop({"CHANNEL": {"RESULT": code}}, "rldls5656", station)
        for body in ([], None, {}, {"CHANNEL": None}, {"CHANNEL": []}, {"code": 200}):
            with self.subTest(body=body), self.assertRaises(PlatformError):
                parse_soop(body, "rldls5656", station)

    def test_mismatched_identity_and_contradictory_offline_are_unknown(self):
        station = CAPTURED["offline"]["station"]
        for room in ({"RESULT": 0, "BJID": "other"}, {"RESULT": 0, "BNO": "123"}):
            with self.subTest(room=room), self.assertRaises(PlatformError):
                parse_soop({"CHANNEL": room}, "rldls5656", station)

    def test_online_requires_valid_session_title_and_same_identity(self):
        sample = CAPTURED["online"]
        channel_id = sample["station"]["station"]["userId"]
        for update in ({"BJID": "other"}, {"BJID": None}, {"BNO": None}, {"BNO": ""},
                       {"BNO": "0"}, {"BNO": -1}, {"BNO": True}, {"BNO": "1" * 21}, {"TITLE": None}):
            with self.subTest(update=update), self.assertRaises(PlatformError):
                room = dict(sample["player"]["CHANNEL"], **update)
                parse_soop({"CHANNEL": room}, channel_id, sample["station"])


class SoopHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = PlatformClient()
        self.calls = []
        self.station_body = copy.deepcopy(CAPTURED["offline"]["station"])
        self.player_body = copy.deepcopy(CAPTURED["offline"]["player"])
        self.player_status = 200

        async def station(request):
            self.calls.append((request.method, request.path))
            if request.match_info["channel_id"] == "missing":
                return web.json_response({"code": "CHA0001"}, status=404)
            return web.json_response(self.station_body)

        async def player(request):
            self.calls.append((request.method, request.path))
            form = await request.post()
            self.assertEqual(request.query["bjid"], "rldls5656")
            self.assertEqual(form["bid"], "rldls5656")
            self.assertEqual(form["type"], "live")
            self.assertEqual(form["mode"], "live")
            self.assertEqual(form["bno"], "")
            return web.json_response(self.player_body, status=self.player_status)

        app = web.Application()
        app.router.add_get("/channel/{channel_id}/station", station)
        app.router.add_post("/player", player)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        self.station_patch = patch("services.pro_live_platforms.SOOP_STATION_URL", base + "/channel/{channel_id}/station")
        self.player_patch = patch("services.pro_live_platforms.SOOP_PLAYER_URL", base + "/player")
        self.station_patch.start()
        self.player_patch.start()

    async def asyncTearDown(self):
        self.station_patch.stop()
        self.player_patch.stop()
        await self.client.close()
        await self.runner.cleanup()

    async def test_actual_http_methods_parameters_and_offline_detection(self):
        state = await self.client.check("soop", "rldls5656")
        self.assertFalse(state.live)
        self.assertEqual(self.calls, [("GET", "/channel/rldls5656/station"), ("POST", "/player")])

    async def test_invalid_account_404_does_not_suspend_other_accounts(self):
        with self.assertRaises(PlatformError):
            await self.client.check("soop", "missing")
        self.assertFalse((await self.client.check("soop", "rldls5656")).live)
        self.assertEqual(sum(method == "POST" for method, _ in self.calls), 1)
        self.assertNotIn("soop", self.client.blocked_until)

    async def test_http_200_with_invalid_identity_does_not_query_player(self):
        self.station_body = {"station": {"userId": "wrong", "stationNo": 1, "userNick": "Wrong"}}
        with self.assertRaises(PlatformError):
            await self.client.check("soop", "rldls5656")
        self.assertEqual(len(self.calls), 1)

    async def test_http_200_with_non_status_body_is_not_offline(self):
        self.player_body = {"message": "temporary failure"}
        with self.assertRaises(PlatformError):
            await self.client.check("soop", "rldls5656")

    async def test_service_failure_stays_unknown_and_applies_backoff(self):
        self.player_status = 503
        with self.assertRaises(PlatformError):
            await self.client.check("soop", "rldls5656")
        calls = len(self.calls)
        with self.assertRaises(PlatformError):
            await self.client.check("soop", "rldls5656")
        self.assertEqual(len(self.calls), calls)
        self.assertIn("soop", self.client.blocked_until)


class SoopNotificationTests(unittest.IsolatedAsyncioTestCase):
    """Synthetic transitions through real parser, monitor, SQLite and embed delivery.

    Discord is mocked: these tests never send messages to a real server.
    """

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "history.sqlite3"
        self.roster = self.root / "roster.json"
        now = datetime.now(timezone.utc)
        self.roster.write_text(json.dumps({"schema_version": 1, "players": [{
            "id": "fixture", "name": "Fixture", "team": "Fixture team", "league": "LCK",
            "division": 1, "role": "MID", "active": True,
            "verified_at": (now - timedelta(minutes=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
            "roster_sources": ["https://example.com/synthetic-roster"],
            "channels": [{"platform": "soop", "channel_id": "fixture", "verified_at": now.isoformat(),
                          "source_urls": ["https://example.com/synthetic-channel"]}],
        }]}))
        self.live = False
        self.session_id = "100"
        self.query_fails = False
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.guild = SimpleNamespace(id=1)
        self.channel.send = AsyncMock()
        self.bot = MagicMock()
        self.bot.get_channel.return_value = self.channel
        self.cog = self.make_cog()
        await self.cog.repository.subscribe(1, 10)

    def make_cog(self):
        client = PlatformClient()

        async def transport(platform, url, **kwargs):
            self.assertEqual(platform, "soop")
            if url.endswith("/station"):
                return {"station": {"userId": "fixture", "stationNo": 123, "userNick": "Fixture"}}
            if self.query_fails:
                raise PlatformError("soop: HTTP 503.")
            if self.live:
                return {"CHANNEL": {"RESULT": 1, "BJID": "fixture", "BNO": self.session_id, "TITLE": "Synthetic live"}}
            return {"CHANNEL": {"RESULT": 0}}

        client.request = AsyncMock(side_effect=transport)
        with patch.object(ProLives.check_pro_lives, "start"):
            cog = ProLives(self.bot)
        cog.repository = LiveRepository(self.db)
        cog.monitor = LiveMonitor(self.roster, cog.repository, client)
        return cog

    async def asyncTearDown(self):
        await self.cog.cog_unload()

    async def poll(self):
        await ProLives.check_pro_lives.coro(self.cog)
        self.assertIsNone(self.cog.monitor.catalog_error)

    async def restart(self):
        await self.cog.cog_unload()
        self.cog = self.make_cog()

    async def test_start_end_failure_restart_and_new_session_deduplication(self):
        await self.poll()  # offline reference
        self.channel.send.assert_not_awaited()
        self.live = True
        await self.poll()
        self.channel.send.assert_awaited_once()
        embed = self.channel.send.call_args.kwargs["embed"]
        self.assertEqual(embed.url, "https://play.sooplive.com/fixture")
        self.assertEqual(embed.description, "Synthetic live")
        self.assertEqual({field.name: field.value for field in embed.fields}["Plataforma"], "SOOP")
        await self.poll()
        self.query_fails = True
        await self.poll()
        self.assertTrue(any("503" in value for value in self.cog.monitor.health.values()))
        last_live = await self.cog.repository._run(lambda c: c.execute("SELECT live FROM live_state").fetchone()[0])
        self.assertEqual(last_live, 1)  # errors never fabricate an end
        self.query_fails = False
        await self.restart()
        await self.poll()
        self.channel.send.assert_awaited_once()
        self.live = False
        await self.poll()
        last_live = await self.cog.repository._run(lambda c: c.execute("SELECT live FROM live_state").fetchone()[0])
        self.assertEqual(last_live, 0)  # actual offline result records the end
        self.live = True
        await self.poll()  # same session after inconsistent offline must not duplicate
        self.channel.send.assert_awaited_once()
        self.session_id = "101"
        await self.poll()
        await self.poll()
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_failed_notification_retried_once_after_restart(self):
        await self.poll()
        self.live = True
        self.channel.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied")
        await self.poll()
        self.assertIn(1, self.cog.delivery_errors)
        self.channel.send.side_effect = None
        await self.restart()
        await self.poll()
        await self.poll()
        self.assertEqual(self.channel.send.await_count, 2)  # failed attempt + one delivered
        pending = await self.cog.repository._run(lambda c: c.execute("SELECT COUNT(*) FROM deliveries WHERE sent=0").fetchone()[0])
        self.assertEqual(pending, 0)

    async def test_first_online_is_baseline_even_across_restart(self):
        self.live = True
        await self.poll()
        await self.restart()
        await self.poll()
        self.live = False
        await self.poll()
        self.live = True
        await self.poll()
        self.channel.send.assert_not_awaited()
        self.session_id = "101"
        await self.poll()
        self.channel.send.assert_awaited_once()
