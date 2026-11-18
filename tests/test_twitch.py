from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web

from services.pro_live_platforms import LiveState, PlatformClient, PlatformError, parse_twitch
from services.pro_live_service import LiveMonitor, LiveRepository, load_catalog

CAPTURED = json.loads((Path(__file__).parent / 'fixtures' / 'twitch_status.json').read_text())
NOW = datetime.now(timezone.utc)


def response(login='alice', uid='11', live=False):
    body = copy.deepcopy(CAPTURED['online_control'] if live else CAPTURED['offline'])
    body['data']['user'].update(id=uid, login=login)
    return body


def player(login='alice', uid='11', league='LEC', pending=False):
    channel = {'platform': 'twitch', 'channel_id': login,
               'source_urls': ['https://example.com/pro-player-channel']}
    if pending:
        channel.update(monitoring_status='pending', pending_reason='Confirmar o link atual.')
    else:
        channel.update(user_id=uid, verified_at=NOW.isoformat())
    return {'id': login, 'name': login, 'team': 'Fixture', 'league': league,
            'division': None, 'role': 'MID', 'active': True,
            'competitive_status': 'unconfirmed', 'contract_status': 'unknown',
            'verified_at': NOW.isoformat(), 'valid_until': (NOW + timedelta(days=7)).isoformat(),
            'roster_sources': ['https://example.com/pro-player'], 'channels': [channel]}


class TwitchParserTests(unittest.TestCase):
    def test_real_online_and_offline(self):
        for key, expected in [('online_control', True), ('offline', False)]:
            user = CAPTURED[key]['data']['user']
            state = parse_twitch(CAPTURED[key], user['login'], user['id'])
            self.assertEqual(state.live, expected)
            if expected:
                self.assertEqual(state.session_id, user['stream']['id'])
                self.assertEqual(state.title, user['broadcastSettings']['title'])

    def test_missing_user_errors_changed_owner_and_partial_data_are_unknown(self):
        missing_stream = response()
        del missing_stream['data']['user']['stream']
        for body in [None, [], {}, {'data': None}, CAPTURED['missing_user'], missing_stream,
                     {'errors': [{'message': 'sensitive-details'}], **response()},
                     response(uid='22'), response(login='other')]:
            with self.subTest(body=body), self.assertRaises(PlatformError) as caught:
                parse_twitch(body, 'alice', '11')
            self.assertNotIn('sensitive-details', str(caught.exception))

    def test_live_requires_valid_session_type_title_and_timestamp(self):
        for change in [{'id': ''}, {'id': '0'}, {'id': True}, {'type': 'unknown'},
                       {'createdAt': 'not-a-date'}, {'createdAt': '2026-11-16T20:00:00'}]:
            body = response(live=True)
            body['data']['user']['stream'].update(change)
            with self.subTest(change=change), self.assertRaises(PlatformError):
                parse_twitch(body, 'alice', '11')
        body = response(live=True)
        body['data']['user']['broadcastSettings'] = None
        with self.assertRaises(PlatformError):
            parse_twitch(body, 'alice', '11')

    def test_rerun_is_not_a_new_live(self):
        body = response(live=True)
        body['data']['user']['stream']['type'] = 'rerun'
        self.assertFalse(parse_twitch(body, 'alice', '11').live)


class TwitchBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_batching_cache_and_per_user_failure(self):
        client = PlatformClient()
        expected = {f'player{i}': str(i + 1) for i in range(21)}
        async def request(platform, url, **kwargs):
            if kwargs.get('text'):
                return 'window.clientId="publictestidentifier1234567890";'
            return [response(op['variables']['login'], expected[op['variables']['login']])
                    if op['variables']['login'] != 'player0' else CAPTURED['missing_user']
                    for op in kwargs['json']]
        client.request = AsyncMock(side_effect=request)
        result = await client.twitch(expected)
        self.assertIsInstance(result['player0'], PlatformError)
        self.assertTrue(all(isinstance(result[f'player{i}'], LiveState) for i in range(1, 21)))
        self.assertEqual(client.request.await_count, 3)
        await client.twitch({'player1': '2'})
        self.assertEqual(client.request.await_count, 4)
        self.assertEqual([len(c.kwargs['json']) for c in client.request.await_args_list if 'json' in c.kwargs], [20, 1, 1])

    async def test_incomplete_or_invalid_batches_are_unknown(self):
        for data in [[], {}, [response(), response()], [{'errors': [{'message': 'denied'}]}]]:
            client = PlatformClient()
            client.twitch_web_client_id = 'publictestidentifier1234567890'
            client.twitch_web_client_expires = time.monotonic() + 3600
            client.request = AsyncMock(return_value=data)
            self.assertIsInstance((await client.twitch({'alice': '11'}))['alice'], PlatformError)

    async def test_missing_public_identifier_is_an_error(self):
        client = PlatformClient()
        client.request = AsyncMock(return_value='<html>challenge</html>')
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(PlatformError):
            await client.twitch({'alice': '11'})
        self.assertEqual(client.request.await_count, 1)

    async def test_http_failures_are_unknown_and_respect_backoff(self):
        status = 412
        async def handler(request):
            return web.json_response([response()], status=status)
        app = web.Application()
        app.router.add_post('/', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
        try:
            for status in [401, 403, 412, 429, 500]:
                client = PlatformClient()
                client.twitch_web_client_id = 'publictestidentifier1234567890'
                client.twitch_web_client_expires = time.monotonic() + 3600
                try:
                    with patch('services.pro_live_platforms.TWITCH_GQL_URL', url):
                        result = await client.twitch({'alice': '11'})
                    self.assertIsInstance(result['alice'], PlatformError)
                    self.assertIn(f'HTTP {status}', str(result['alice']))
                    self.assertGreater(client.blocked_until['twitch'], time.monotonic())
                    if status in [401, 403]:
                        self.assertIsNone(client.twitch_web_client_id)
                finally:
                    await client.close()
        finally:
            await runner.cleanup()


class TwitchCatalogAndMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'roster.json'

    def write(self, *players):
        self.path.write_text(json.dumps({'schema_version': 1, 'players': players}))

    async def test_any_region_and_pending_accounts_are_visible_but_not_polled(self):
        for league in ['LEC', 'CBLOL', 'LCS', 'LCP', 'GLOBAL', 'LCK']:
            self.write(player(league=league), player('missing', pending=True))
            catalog = load_catalog(self.path)
            self.assertEqual(catalog.eligible_players, 2)
            self.assertEqual(len(catalog.accounts), 1)
            self.assertEqual(len(catalog.pending_accounts), 1)
        repo = LiveRepository(self.root / 'db')
        await repo.subscribe(1, 10)
        client = SimpleNamespace(twitch=AsyncMock(return_value={'alice': LiveState(False)}), check=AsyncMock())
        self.assertEqual(await LiveMonitor(self.path, repo, client).poll(), [])
        client.twitch.assert_awaited_once_with({'alice': '11'})
        client.check.assert_not_called()

    async def test_missing_owner_duplicate_owner_and_pending_duplicates_rejected(self):
        invalid = player()
        invalid['channels'][0].pop('user_id')
        for records in [(invalid,), (player(), player('bob', uid='11'))]:
            self.write(*records)
            with self.assertRaises(ValueError):
                load_catalog(self.path)
        duplicate = player('alice', pending=True)
        duplicate['id'] = 'other'
        self.write(player(), duplicate)
        with self.assertRaises(ValueError):
            load_catalog(self.path)
        mixed = player(league='LCK')
        mixed['division'] = 2
        native = copy.deepcopy(mixed['channels'][0])
        native.update(platform='soop', channel_id='academy_station')
        mixed['channels'].append(native)
        self.write(mixed)
        with self.assertRaises(ValueError):
            load_catalog(self.path)

    async def test_transitions_restart_and_failures_preserve_deduplication(self):
        self.write(player(), player('bob', uid='22'), player('missing', pending=True))
        repo = LiveRepository(self.root / 'db')
        await repo.subscribe(1, 10)
        client = SimpleNamespace(twitch=AsyncMock(return_value={'alice': LiveState(False), 'bob': LiveState(False)}))
        monitor = LiveMonitor(self.path, repo, client)
        self.assertEqual(await monitor.poll(), [])
        client.twitch.return_value = {'alice': LiveState(True, '100', 'Live'), 'bob': LiveState(False)}
        jobs = await monitor.poll()
        self.assertEqual(len(jobs), 1)
        await repo.acknowledge(jobs[0])
        client.twitch.return_value = {'alice': PlatformError('HTTP 412'), 'bob': LiveState(True, '200', 'Other')}
        jobs = await monitor.poll()
        self.assertEqual(len(jobs), 1)
        self.assertIn('bob', jobs[0].account_key)
        await repo.acknowledge(jobs[0])
        with sqlite3.connect(repo.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_state WHERE live=1').fetchone()[0], 2)
        restarted = LiveMonitor(self.path, LiveRepository(repo.path), client)
        client.twitch.return_value = {'alice': LiveState(True, '100'), 'bob': LiveState(True, '200')}
        self.assertEqual(await restarted.poll(), [])
        client.twitch.return_value['alice'] = LiveState(True, '101')
        self.assertEqual(len(await restarted.poll()), 1)

    async def test_twitch_failure_does_not_block_asian_platforms(self):
        asian = player('asian')
        asian.update(league='LCK', division=1)
        asian['channels'][0].update(platform='soop', channel_id='confirmed_station')
        self.write(player(), asian)
        repo = LiveRepository(self.root / 'db')
        await repo.subscribe(1, 10)
        client = SimpleNamespace(twitch=AsyncMock(side_effect=PlatformError('Twitch unavailable')),
                                 check=AsyncMock(return_value=LiveState(False)))
        monitor = LiveMonitor(self.path, repo, client)
        await monitor.poll()
        self.assertIn('ok', monitor.health.values())
        self.assertIn('Twitch unavailable', monitor.health.values())

    async def test_player_command_shows_ready_and_pending_accounts_separately(self):
        from cogs.pro_lives import ProLives
        self.write(player(), player('missing', pending=True))
        catalog = load_catalog(self.path)
        cog = SimpleNamespace(monitor=SimpleNamespace(catalog=catalog, reload=AsyncMock()))
        ctx = SimpleNamespace(send=AsyncMock())
        await ProLives.players.callback(cog, ctx)
        output = '\n'.join(call.kwargs["embed"].description for call in ctx.send.await_args_list)
        self.assertIn('https://www.twitch.tv/alice', output)
        self.assertIn('[PENDENTE] missing', output)
        self.assertIn('Confirmar o link atual', output)
