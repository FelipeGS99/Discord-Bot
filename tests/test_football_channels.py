from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.futebol import Futebol
from services.brasileirao_service import BsdFootballClient, BrasileiraoFixture
from services.football_channel_service import (
    FootballChannelManager, FootballChannelRepository, channel_name,
)


def fixture(identifier=1, status="1st_half", goals=0, league=9):
    return BrasileiraoFixture(identifier, league, "Brasileirao", 1, "São Paulo", "Palmeiras",
                              goals, 0, status, status, 1, datetime(2026, 11, 16, 23, 50, tzinfo=timezone.utc))


def http_error(kind=discord.HTTPException):
    return kind(SimpleNamespace(status=404 if kind is discord.NotFound else 403, reason="test"), "test")


def guild(identifier):
    g = MagicMock(spec=discord.Guild)
    g.id = identifier
    g.default_role = MagicMock(spec=discord.Role)
    g.default_role.id = identifier
    g.default_role.guild = g
    g.me = MagicMock(spec=discord.Member)
    g.me.id = identifier + 100
    role = MagicMock(spec=discord.Role)
    role.id, role.name, role.guild = identifier + 1, "Futebol", g
    role.mention = f"<@&{role.id}>"
    g.roles = [g.default_role, role]
    g.get_role.side_effect = lambda rid: next((r for r in g.roles if r.id == rid), None)
    channels = {}
    g.get_channel.side_effect = channels.get

    async def fetch(cid):
        if cid not in channels:
            raise http_error(discord.NotFound)
        return channels[cid]

    async def create(name, **kwargs):
        c = MagicMock(spec=discord.TextChannel)
        c.id, c.name, c.guild, c.topic = identifier * 1000 + len(channels) + 1, name, g, kwargs['topic']
        c.send, c.edit = AsyncMock(), AsyncMock()

        async def delete(**kw):
            channels.pop(c.id, None)

        c.delete = AsyncMock(side_effect=delete)
        channels[c.id] = c
        return c

    async def fetch_all():
        return list(channels.values())

    g.create_text_channel = AsyncMock(side_effect=create)
    g.fetch_channels, g.fetch_channel = AsyncMock(side_effect=fetch_all), AsyncMock(side_effect=fetch)
    return g, role, channels


class FootballChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = FootballChannelRepository(Path(self.tmp.name) / "state.json")
        self.guild, self.role, self.channels = guild(10)
        self.guild2, self.role2, self.channels2 = guild(20)
        self.bot = SimpleNamespace(get_guild=lambda gid: {10:self.guild, 20:self.guild2}.get(gid))
        self.client = AsyncMock(spec=BsdFootballClient)
        self.client.fetch_all_live_fixtures.return_value = [fixture()]
        self.client.fetch_fixture.return_value = None
        self.client.fetch_goal_scorers.return_value = ["São Paulo: Jogador"]
        self.now = 1000.0
        self.manager = self.build_manager()
        await self.manager.enable(self.guild, 9, self.role)

    def build_manager(self):
        return FootballChannelManager(self.bot, self.client, self.repo,
            lambda f, scorers, reason, live: Futebol._build_score_embed(f, "Brasileirao", 1, scorers, reason, live),
            clock=lambda:self.now)

    async def open_match(self):
        await self.manager.poll()
        return next(iter(self.channels.values()))

    async def finish_match(self):
        self.client.fetch_all_live_fixtures.return_value = []
        self.client.fetch_fixture.return_value = fixture(status="finished", goals=2)
        await self.manager.poll()

    async def test_private_from_creation_and_no_inherited_public_overwrites(self):
        channel = await self.open_match()
        kwargs = self.guild.create_text_channel.call_args.kwargs
        self.assertEqual(channel.name, 'spfc-x-pal')
        ow = kwargs['overwrites']
        self.assertEqual(set(ow), {self.guild.default_role, self.role, self.guild.me})
        self.assertFalse(ow[self.guild.default_role].view_channel)
        self.assertTrue(ow[self.role].view_channel)
        self.assertTrue(ow[self.guild.me].view_channel)
        self.assertEqual(kwargs['topic'], 'football-match:10:1')

    def test_channel_names_handle_accents_punctuation_and_discord_length_limit(self):
        self.assertEqual(channel_name('São Paulo','Palmeiras'),'spfc-x-pal')
        name=channel_name('Atlético! ' * 30,'@Rival/Com espaços' * 30)
        self.assertLessEqual(len(name),100)
        self.assertRegex(name,r'^[a-z0-9-]+$')

    async def test_changes_only_and_scorers(self):
        channel = await self.open_match()
        await self.manager.poll()
        self.assertEqual(channel.send.await_count, 1)
        self.client.fetch_all_live_fixtures.return_value = [fixture(goals=1)]
        await self.manager.poll()
        self.assertEqual(channel.send.await_count, 2)
        self.assertIn('Gol:',channel.send.call_args.kwargs['embed'].title)
        self.assertEqual(channel.send.call_args.kwargs['embed'].fields[0].name,'Gols')
        self.client.fetch_all_live_fixtures.return_value = [fixture(status='halftime',goals=1)]
        await self.manager.poll()
        self.assertIn('Intervalo:',channel.send.call_args.kwargs['embed'].title)

    async def test_one_hour_after_confirmed_finish_then_delete(self):
        channel = await self.open_match()
        await self.finish_match()
        match = self.manager.state['matches']['10:1']
        self.assertEqual(match['delete_at'],4600)
        self.assertIn('Fim de jogo',channel.send.call_args.kwargs['embed'].title)
        self.now = 4599
        await self.manager.poll()
        channel.delete.assert_not_awaited()
        self.now = 4600
        await self.manager.poll()
        channel.delete.assert_awaited_once()
        self.assertTrue(match['closed'])

    async def test_restart_reuses_channel_and_deadline(self):
        channel = await self.open_match()
        self.manager = self.build_manager()
        await self.manager.poll()
        self.assertEqual(self.guild.create_text_channel.await_count,1)
        self.assertEqual(channel.send.await_count,1)
        await self.finish_match()
        self.manager = self.build_manager()
        self.now = 4600
        await self.manager.poll()
        channel.delete.assert_awaited_once()

    async def test_timeout_after_create_then_restart_after_finish_recovers_intent(self):
        create = self.guild.create_text_channel.side_effect

        async def created_but_timed_out(*args, **kwargs):
            await create(*args, **kwargs)
            raise http_error()

        self.guild.create_text_channel.side_effect = created_but_timed_out
        await self.manager.poll()
        self.assertIsNone(self.repo.load()['matches']['10:1']['channel_id'])
        self.manager = self.build_manager()
        self.client.fetch_all_live_fixtures.return_value = []
        self.client.fetch_fixture.return_value = fixture(status='finished')
        await self.manager.poll()
        channel = next(iter(self.channels.values()))
        self.assertEqual(self.guild.create_text_channel.await_count,1)
        self.assertEqual(self.manager.state['matches']['10:1']['channel_id'],channel.id)
        self.now = 4600
        await self.manager.poll()
        channel.delete.assert_awaited_once()

    async def test_create_failure_retries_without_creating_past_finished_games(self):
        self.guild.create_text_channel.side_effect = http_error()
        await self.manager.poll()
        self.assertIsNone(self.repo.load()['matches']['10:1']['channel_id'])
        self.client.fetch_all_live_fixtures.return_value = []
        self.client.fetch_fixture.return_value = fixture(status='finished')
        await self.manager.poll()
        self.assertTrue(self.manager.state['matches']['10:1']['closed'])
        self.assertEqual(self.guild.create_text_channel.await_count,1)

    async def test_disable_pending_creation_does_not_create_new_channel(self):
        self.guild.create_text_channel.side_effect = http_error()
        await self.manager.poll()
        await self.manager.disable(10,9)
        await self.manager.poll()
        self.assertEqual(self.guild.create_text_channel.await_count,1)
        self.assertTrue(self.manager.state['matches']['10:1']['closed'])

    async def test_cancelled_after_start_schedules_cleanup(self):
        channel = await self.open_match()
        self.client.fetch_all_live_fixtures.return_value = []
        self.client.fetch_fixture.return_value = fixture(status='cancelled')
        await self.manager.poll()
        self.assertEqual(self.manager.state['matches']['10:1']['delete_at'],4600)
        self.now=4600
        await self.manager.poll()
        channel.delete.assert_awaited_once()

    async def test_post_match_correction_updates_without_extending_deadline(self):
        channel = await self.open_match()
        await self.finish_match()
        self.now=1100
        self.client.fetch_fixture.return_value=fixture(status='finished',goals=1)
        await self.manager.poll()
        self.assertEqual(channel.send.await_count,3)
        self.assertIn('1 x 0',channel.send.call_args.kwargs['embed'].title)
        self.assertEqual(self.manager.state['matches']['10:1']['delete_at'],4600)

    async def test_missing_live_is_not_finished_even_across_midnight(self):
        channel = await self.open_match()
        self.client.fetch_all_live_fixtures.return_value = []
        self.client.fetch_fixture.side_effect = TimeoutError()
        self.now += 7200
        await self.manager.poll()
        self.assertIsNone(self.manager.state['matches']['10:1']['delete_at'])
        channel.delete.assert_not_awaited()
        self.client.fetch_fixture.assert_awaited_with(1)

    async def test_cleanup_continues_during_api_outage(self):
        channel = await self.open_match()
        await self.finish_match()
        self.now = 4600
        self.client.fetch_all_live_fixtures.side_effect = TimeoutError()
        await self.manager.poll()
        channel.delete.assert_awaited_once()

    async def test_disabled_league_still_finishes_existing_channels(self):
        channel = await self.open_match()
        await self.manager.disable(10,9)
        self.client.fetch_all_live_fixtures.return_value = [fixture(2)]
        self.client.fetch_fixture.return_value = fixture(status='finished')
        await self.manager.poll()
        self.assertEqual(self.guild.create_text_channel.await_count,1)
        self.assertIsNotNone(self.manager.state['matches']['10:1']['delete_at'])
        self.now = 4600
        await self.manager.poll()
        channel.delete.assert_awaited_once()

    async def test_multiple_guilds_independent_deliveries_and_shared_live_query(self):
        await self.manager.enable(self.guild2,9,self.role2)
        await self.manager.poll()
        self.assertEqual(len(self.channels),1)
        self.assertEqual(len(self.channels2),1)
        self.client.fetch_all_live_fixtures.assert_awaited_once()
        c = next(iter(self.channels.values()))
        c2 = next(iter(self.channels2.values()))
        c.send.side_effect = http_error()
        self.client.fetch_all_live_fixtures.return_value = [fixture(goals=1)]
        await self.manager.poll()
        self.assertEqual(c2.send.await_count,2)
        c.send.side_effect = None
        await self.manager.poll()
        self.assertEqual(c2.send.await_count,2)
        self.assertEqual(c.send.await_count,3)
        self.assertEqual(self.client.fetch_goal_scorers.await_count,2)

    async def test_recover_channel_created_before_crash(self):
        orphan = await self.guild.create_text_channel('spfc-x-pal',topic='football-match:10:1')
        await self.manager.poll()
        self.assertEqual(self.guild.create_text_channel.await_count,1)
        orphan.edit.assert_awaited_once()
        orphan.send.assert_awaited_once()

    async def test_never_create_for_scheduled_finished_or_disabled_league(self):
        self.client.fetch_all_live_fixtures.return_value = [fixture(1,'notstarted'),fixture(2,'finished'),fixture(3,league=35)]
        await self.manager.poll()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_manual_deletion_is_respected(self):
        c = await self.open_match()
        self.channels.clear()
        await self.manager.poll()
        self.assertTrue(self.manager.state['matches']['10:1']['closed'])
        await self.manager.poll()
        self.assertEqual(self.guild.create_text_channel.await_count,1)

    async def test_foreign_topic_never_deleted(self):
        c = await self.open_match()
        await self.finish_match()
        c.topic = 'canal humano'
        self.now = 4600
        await self.manager.poll()
        c.delete.assert_not_awaited()
        self.assertFalse(self.manager.state['matches']['10:1']['closed'])

    async def test_delete_failure_retries(self):
        c = await self.open_match()
        await self.finish_match()
        c.delete.side_effect = http_error()
        self.now = 4600
        await self.manager.poll()
        self.assertFalse(self.manager.state['matches']['10:1']['closed'])
        c.delete.side_effect = None
        await self.manager.poll()
        self.assertTrue(self.manager.state['matches']['10:1']['closed'])

    async def test_closed_tombstone_blocks_stale_live_data(self):
        await self.open_match()
        await self.finish_match()
        self.now = 4600
        await self.manager.poll()
        self.client.fetch_all_live_fixtures.return_value = [fixture()]
        await self.manager.poll()
        self.assertEqual(self.guild.create_text_channel.await_count,1)

    async def test_retention_updates_existing_deadline_and_survives_restart(self):
        await self.open_match()
        await self.finish_match()
        await self.manager.retention(10,120)
        self.manager = self.build_manager()
        self.assertEqual(self.manager.state['matches']['10:1']['delete_at'],8200)
        with self.assertRaises(ValueError):await self.manager.retention(10,0)
        with self.assertRaises(ValueError):await self.manager.retention(10,1441)

    async def test_api_correction_back_to_live_cancels_deletion(self):
        c = await self.open_match()
        await self.finish_match()
        self.client.fetch_all_live_fixtures.return_value = [fixture(status='2nd_half')]
        await self.manager.poll()
        self.assertIsNone(self.manager.state['matches']['10:1']['delete_at'])
        self.now = 4600
        await self.manager.poll()
        c.delete.assert_not_awaited()

    async def test_role_removed_never_falls_back_to_public(self):
        self.guild.get_role.side_effect = lambda rid:None
        await self.manager.poll()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_existing_channel_still_expires_if_role_was_removed(self):
        c=await self.open_match()
        self.guild.get_role.side_effect=lambda rid:None
        await self.finish_match()
        self.now=4600
        await self.manager.poll()
        c.delete.assert_awaited_once()

    async def test_everyone_and_foreign_roles_rejected(self):
        with self.assertRaises(ValueError):await self.manager.enable(self.guild,9,self.guild.default_role)
        with self.assertRaises(ValueError):await self.manager.enable(self.guild,9,self.role2)
        with self.assertRaises(ValueError):await self.manager.enable(self.guild,9,self.role,SimpleNamespace(guild=self.guild2))

    async def test_role_change_replaces_old_access_immediately(self):
        c = await self.open_match()
        role = MagicMock(spec=discord.Role)
        role.guild,role.id = self.guild,99
        self.guild.roles.append(role)
        await self.manager.enable(self.guild,9,role)
        overwrites = c.edit.call_args.kwargs['overwrites']
        self.assertIn(role,overwrites)
        self.assertNotIn(self.role,overwrites)
        self.assertFalse(overwrites[self.guild.default_role].view_channel)

    async def test_missing_category_never_creates_public_fallback(self):
        category=MagicMock(spec=discord.CategoryChannel)
        category.guild,category.id=self.guild,999
        await self.manager.enable(self.guild,9,self.role,category)
        await self.manager.poll()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_explicit_category_is_preserved_with_private_overwrites(self):
        category=MagicMock(spec=discord.CategoryChannel)
        category.guild,category.id=self.guild,999
        self.channels[999]=category
        await self.manager.enable(self.guild,9,self.role,category)
        await self.manager.poll()
        kwargs=self.guild.create_text_channel.call_args.kwargs
        self.assertIs(kwargs['category'],category)
        self.assertFalse(kwargs['overwrites'][self.guild.default_role].view_channel)

    async def test_concurrent_polls_never_duplicate_channels(self):
        await asyncio.gather(self.manager.poll(),self.manager.poll())
        self.guild.create_text_channel.assert_awaited_once()
        next(iter(self.channels.values())).send.assert_awaited_once()

    async def test_no_queries_without_subscriptions_or_matches(self):
        await self.manager.disable(10,9)
        await self.manager.poll()
        self.client.fetch_all_live_fixtures.assert_not_awaited()

    async def test_command_detects_futebol_role_and_persists_id(self):
        cog = object.__new__(Futebol)
        cog.channel_manager,cog.api_client = self.manager,self.client
        self.guild.owner_id=100
        ctx = SimpleNamespace(guild=self.guild,channel=SimpleNamespace(category=None),
             author=SimpleNamespace(id=100),send=AsyncMock())
        self.manager.state['guilds'].clear()
        await cog.enable_league(ctx,'brasileirao')
        self.assertEqual(self.manager.config(10)['role_id'],self.role.id)
        self.assertIn(9,self.manager.config(10)['leagues'])
        self.role.name='Torcida'
        await cog.enable_league(ctx,'libertadores')
        self.assertEqual(self.manager.config(10)['role_id'],self.role.id)
        self.assertIn(32,self.manager.config(10)['leagues'])

    async def test_command_refuses_missing_role_dm_and_unauthorized_user(self):
        cog = object.__new__(Futebol)
        cog.channel_manager,cog.api_client = self.manager,self.client
        self.manager.state['guilds'].clear()
        self.guild.roles=[]
        self.guild.owner_id=100
        ctx=SimpleNamespace(guild=self.guild,channel=SimpleNamespace(category=None),author=SimpleNamespace(id=100),send=AsyncMock())
        await cog.enable_league(ctx,'brasileirao')
        self.assertFalse(self.manager.config(10))
        ctx.guild=None
        await cog.enable_league(ctx,'brasileirao')
        ctx.guild=self.guild
        ctx.author=SimpleNamespace(id=101,guild_permissions=SimpleNamespace(administrator=False,manage_channels=False))
        await cog.enable_league(ctx,'brasileirao')
        self.assertFalse(self.manager.config(10))

    async def test_detail_client_parses_real_event_envelope(self):
        client=BsdFootballClient('dummy')
        with patch.object(client,'_get_json',return_value={'id':1,'league':{'id':9},'home_team':'São Paulo','away_team':'Palmeiras','status':'finished','home_score':2,'away_score':1}):
            f=await client.fetch_fixture(1)
        self.assertTrue(f.is_finished)
        self.assertEqual(f.score_text,'2 x 1')

    async def test_repository_corruption_not_silently_overwritten(self):
        self.repo.path.write_text('{"guilds": []}')
        with self.assertRaises(ValueError):self.repo.load()
        self.assertEqual(self.repo.path.read_text(),'{"guilds": []}')

    async def test_all_league_commands_delegate_to_central_monitor(self):
        from bot import create_bot
        from discord.ext import tasks
        bot=create_bot()
        async with bot:
            with patch.object(tasks.Loop,'start'), patch('cogs.futebol.FootballChannelRepository',return_value=self.repo):
                for extension in ['brasileirao','libertadores','sulamericana','copadobrasil','futebol']:
                    await bot.load_extension('cogs.'+extension)
            cog=bot.get_cog('Futebol')
            cog.enable_league=AsyncMock()
            ctx=SimpleNamespace()
            for league in ['brasileirao','libertadores','sulamericana','copadobrasil']:
                command=bot.get_command(league+' ativar')
                self.assertIsNotNone(command)
                self.assertIsNone(bot.get_command(league+' canal'))
                await command.callback(command.cog,ctx)
                cog.enable_league.assert_awaited_with(ctx,league,None,None)
            for name in ['futebol ativar','futebol prazo','futebol parar','futebol status']:
                self.assertIsNotNone(bot.get_command(name))


if __name__ == '__main__':
    unittest.main()
