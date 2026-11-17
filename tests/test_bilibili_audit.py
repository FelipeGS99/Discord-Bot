from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web

from services.pro_live_platforms import PlatformClient, PlatformError, PlatformHTTPError, parse_bilibili
from services.pro_live_service import LiveMonitor, LiveRepository


CAPTURED = json.loads((Path(__file__).parent / "fixtures" / "bilibili_status.json").read_text())


class BilibiliParserAuditTests(unittest.TestCase):
    def test_public_online_control_and_all_five_real_offline_rooms(self):
        control = CAPTURED["online_control"]
        state = parse_bilibili(control["response"], control["canonical_id"])
        self.assertTrue(state.live)
        self.assertEqual(state.session_id, control["response"]["data"]["live_time"])
        self.assertEqual(state.title, control["response"]["data"]["title"])
        for sample in CAPTURED["offline_players"]:
            with self.subTest(player=sample["player"]):
                self.assertFalse(parse_bilibili(sample["response"], sample["channel_id"]).live)

    def test_mismatched_canonical_room_is_never_an_offline_result(self):
        for sample in CAPTURED["offline_players"]:
            body = copy.deepcopy(sample["response"])
            body["data"]["room_id"] = 1
            with self.subTest(player=sample["player"]), self.assertRaises(PlatformError):
                parse_bilibili(body, sample["channel_id"])

    def test_malformed_success_envelopes_are_unknown(self):
        sample = CAPTURED["offline_players"][0]
        for body in (None, [], {}, {"code": 0, "data": None}, {"code": 0, "data": []},
                     {"code": False, "data": sample["response"]["data"]},
                     {"code": "0", "data": sample["response"]["data"]},
                     {"code": -412}, {"code": -352}, {"code": 0, "data": {}}):
            with self.subTest(body=body), self.assertRaises(PlatformError):
                parse_bilibili(body, sample["channel_id"])

    def test_online_requires_an_actual_timestamp_and_text_title(self):
        sample = CAPTURED["online_control"]
        for change in ({"live_time": "not-a-date"}, {"live_time": ""}, {"live_time": None},
                       {"live_time": "0000-00-00 00:00:00"}, {"title": None},
                       {"live_status": False}, {"live_status": 3}):
            body = copy.deepcopy(sample["response"])
            body["data"].update(change)
            with self.subTest(change=change), self.assertRaises(PlatformError):
                parse_bilibili(body, sample["canonical_id"])

    def test_replay_is_not_a_live_notification(self):
        sample = CAPTURED["replay_control"]
        self.assertEqual(sample["response"]["data"]["live_status"], 2)
        self.assertFalse(parse_bilibili(sample["response"], sample["channel_id"]).live)


class LocalBilibiliClient(PlatformClient):
    """Use real HTTP/parsing with a local origin; no requests reach Bilibili."""

    def __init__(self, url):
        super().__init__()
        self.url = url

    async def request(self, platform, url, **kwargs):
        return await super().request(platform, self.url, **kwargs)


class BilibiliHttpAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = 200
        self.body = None
        self.bodies = {s["channel_id"]: s["response"] for s in CAPTURED["offline_players"]}

        async def handler(request):
            body = self.bodies[request.query["room_id"]] if self.body is None else self.body
            if isinstance(body, str):
                return web.Response(text=body, status=self.status)
            return web.json_response(body, status=self.status)

        app = web.Application()
        app.router.add_get("/", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/"

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_http_error_is_unknown_even_with_valid_offline_json_body(self):
        channel_id = CAPTURED["offline_players"][0]["channel_id"]
        for status in (403, 404, 412, 429, 500, 503):
            self.status = status
            client = LocalBilibiliClient(self.url)
            try:
                with self.subTest(status=status), self.assertRaises(PlatformHTTPError) as found:
                    await client.check("bilibili", channel_id)
                self.assertEqual(found.exception.status, status)
                self.assertTrue(client.blocked_until)
            finally:
                await client.close()

    async def test_http200_challenge_api_error_and_malformed_payload_are_unknown(self):
        channel_id = CAPTURED["offline_players"][0]["channel_id"]
        for body in ("<html>challenge</html>", {"code": -412}, {"code": -352},
                     {"code": 0, "data": {}}, {"code": 0, "data": []}):
            self.body = body
            client = LocalBilibiliClient(self.url)
            try:
                with self.subTest(body=body), self.assertRaises(PlatformError):
                    await client.check("bilibili", channel_id)
            finally:
                await client.close()

    async def test_five_rooms_transitions_errors_restart_and_deduplication(self):
        # Online player responses below are simulations, not captured live sessions.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            players = []
            for sample in CAPTURED["offline_players"]:
                players.append({
                    "id": sample["player"], "name": sample["player"], "team": "Fixture",
                    "league": "LPL", "division": 1, "role": "MID", "active": True,
                    "verified_at": now.isoformat(), "valid_until": (now + timedelta(days=1)).isoformat(),
                    "roster_sources": ["https://example.com/synthetic-roster"],
                    "channels": [{"platform": "bilibili", "channel_id": sample["channel_id"],
                                  "verified_at": now.isoformat(),
                                  "source_urls": ["https://example.com/synthetic-association"]}],
                })
            path = root / "roster.json"
            path.write_text(json.dumps({"schema_version": 1, "players": players}))
            db = root / "state.sqlite3"
            repo = LiveRepository(db)
            await repo.subscribe(1, 10)

            async def poll():
                client = LocalBilibiliClient(self.url)
                try:
                    monitor = LiveMonitor(path, LiveRepository(db), client)
                    return await monitor.poll(), monitor.health
                finally:
                    await client.close()

            self.assertEqual((await poll())[0], [])
            for sample in CAPTURED["offline_players"]:
                body = copy.deepcopy(sample["response"])
                body["data"].update(live_status=1, live_time="2026-11-16 17:00:00", title="Simulated audit live")
                self.bodies[sample["channel_id"]] = body
            jobs, _ = await poll()
            self.assertEqual(len(jobs), 5)
            self.assertEqual(len({job.account_key for job in jobs}), 5)
            for job in jobs:
                await repo.acknowledge(job)
            self.assertEqual((await poll())[0], [])
            self.status = 412
            jobs, health = await poll()
            self.assertEqual(jobs, [])
            self.assertTrue(all(value != "ok" for value in health.values()))
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM live_state WHERE live=1").fetchone()[0], 5)
            self.status = 200
            self.assertEqual((await poll())[0], [])
            self.bodies = {s["channel_id"]: s["response"] for s in CAPTURED["offline_players"]}
            self.assertEqual((await poll())[0], [])
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM live_state WHERE live=0").fetchone()[0], 5)
