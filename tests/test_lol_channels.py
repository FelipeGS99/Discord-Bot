from __future__ import annotations

import copy
import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import discord

from services.lol_channel_service import LoLChannels, LoLChannelError
from services.lol_tracker_repository import LoLRepository
from services.lol_tracker_service import LoLMonitor
from services.riot_service import RiotClient, DataDragon, RiotError

CATALOG = json.loads((Path(__file__).parent / "fixtures/lol_catalog.json").read_text())


def error(kind=discord.HTTPException):
    return kind(
        NS(status=404 if kind is discord.NotFound else 403, reason="simulated"),
        "simulated",
    )


def guild_fixture(gid):
    g = MagicMock(spec=discord.Guild)
    g.id = gid
    everyone = MagicMock(spec=discord.Role)
    everyone.id = gid
    everyone.guild = g
    role = MagicMock(spec=discord.Role)
    role.id = gid + 1
    role.name = "LOL"
    role.guild = g
    g.default_role = everyone
    g.me = MagicMock(spec=discord.Member)
    g.me.id = 999
    g.roles = [everyone, role]
    g.get_role.side_effect = lambda rid: next((r for r in g.roles if r.id == rid), None)
    channels = {}
    counter = [gid * 1000]
    g.get_channel.side_effect = channels.get

    async def fetch(cid):
        if cid not in channels:
            raise error(discord.NotFound)
        return channels[cid]

    async def fetch_all():
        return list(channels.values())

    async def create(name, **kwargs):
        counter[0] += 1
        c = MagicMock(spec=discord.TextChannel)
        c.id = counter[0]
        c.name = name
        c.guild = g
        c.topic = kwargs["topic"]
        c.overwrites = kwargs["overwrites"]
        messages = []

        async def edit(**kw):
            if "overwrites" in kw:
                c.overwrites = kw["overwrites"]

        async def delete(**kw):
            channels.pop(c.id, None)

        async def send(**kw):
            m = NS(
                id=c.id * 100 + len(messages) + 1,
                author=NS(id=999),
                embeds=kw["embeds"],
                jump_url=f"https://discord.com/channels/{gid}/{c.id}/{len(messages) + 1}",
            )

            async def edit_message(**updated):
                m.embeds = updated["embeds"]

            m.edit = AsyncMock(side_effect=edit_message)
            messages.append(m)
            return m

        async def history(**kw):
            for m in reversed(messages):
                yield m

        async def message(mid):
            return next(m for m in messages if m.id == mid)

        c.edit = AsyncMock(side_effect=edit)
        c.delete = AsyncMock(side_effect=delete)
        c.send = AsyncMock(side_effect=send)
        c.history = history
        c.fetch_message = AsyncMock(side_effect=message)
        channels[c.id] = c
        return c

    g.create_text_channel = AsyncMock(side_effect=create)
    g.fetch_channels = AsyncMock(side_effect=fetch_all)
    g.fetch_channel = AsyncMock(side_effect=fetch)
    return g, role, channels


class LoLChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = LoLRepository(Path(self.tmp.name) / "test.sqlite3")
        self.guild, self.role, self.channels = guild_fixture(10)
        self.guild2, self.role2, self.channels2 = guild_fixture(20)

        async def fetch(cid):
            return await (
                self.guild.fetch_channel(cid)
                if cid < 20000
                else self.guild2.fetch_channel(cid)
            )

        self.bot = NS(
            user=NS(id=999),
            get_guild=lambda gid: {10: self.guild, 20: self.guild2}.get(gid),
            get_channel=lambda cid: self.channels.get(cid) or self.channels2.get(cid),
            fetch_channel=fetch,
        )
        self.now = 1000
        self.manager = LoLChannels(self.bot, self.repo, clock=lambda: self.now)
        self.player = {
            "guild_id": 10,
            "puuid": "SIMULATED-PUUID",
            "riot_id": "Mochila#bunny",
            "platform": "BR1",
        }
        await self.manager.configure(self.guild)

    async def open(self, mid="BR1_1"):
        cid = await self.manager.ensure(self.player, mid)
        return self.channels[cid]

    async def test_private_role_lol_from_first_creation(self):
        c = await self.open()
        self.assertEqual(c.name, "mochila")
        self.assertEqual(
            set(c.overwrites), {self.guild.default_role, self.role, self.guild.me}
        )
        self.assertFalse(c.overwrites[self.guild.default_role].view_channel)
        self.assertTrue(c.overwrites[self.role].view_channel)
        self.assertTrue(c.overwrites[self.guild.me].view_channel)
        self.assertNotIn(self.player["puuid"], c.topic)

    async def test_missing_role_refuses_public_fallback(self):
        self.guild.roles = [self.guild.default_role]
        self.guild.get_role.side_effect = lambda _: None
        with self.assertRaises(LoLChannelError):
            await self.open()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_role_lookup_case_insensitive_and_duplicate_role_rejected(self):
        self.role2.name = "lol"
        await self.manager.configure(self.guild2)
        self.assertEqual(
            (await self.repo.session_configs())[20]["role_id"], self.role2.id
        )
        self.guild2.get_role.side_effect = lambda _: None
        self.guild2.roles.append(self.role2)
        with self.assertRaises(LoLChannelError):
            await self.manager.configure(self.guild2)

    async def test_role_id_survives_rename(self):
        self.role.name = "Outro nome"
        await self.manager.configure(self.guild)
        await self.open()
        self.assertEqual(
            (await self.repo.session_configs())[10]["role_id"], self.role.id
        )

    async def test_repeated_poll_reuses_same_channel(self):
        c = await self.open()
        self.now = 1200
        self.assertEqual(await self.manager.ensure(self.player, "BR1_1"), c.id)
        self.guild.create_text_channel.assert_awaited_once()

    async def test_consecutive_games_cancel_old_deadline_and_restart_after_last_finish(
        self,
    ):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.assertEqual(
            (await self.repo.session(10, self.player["puuid"]))["delete_at"], 4600
        )
        self.now = 4500
        self.assertEqual(await self.manager.ensure(self.player, "BR1_2"), c.id)
        self.assertIsNone(
            (await self.repo.session(10, self.player["puuid"]))["delete_at"]
        )
        # A late result for game 1 cannot close game 2's active channel.
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.assertIsNone(
            (await self.repo.session(10, self.player["puuid"]))["delete_at"]
        )
        self.now = 6500
        await self.manager.finished(10, self.player["puuid"], "BR1_2")
        self.assertEqual(
            (await self.repo.session(10, self.player["puuid"]))["delete_at"], 10100
        )

    async def test_restart_preserves_channel_and_expiry(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.manager = LoLChannels(
            self.bot, LoLRepository(self.repo.path), clock=lambda: self.now
        )
        self.now = 4599
        await self.manager.cleanup(
            {("BR1", self.player["puuid"]): None},
            {(10, self.player["puuid"]): self.player},
            set(),
        )
        c.delete.assert_not_awaited()
        self.now = 4600
        await self.manager.cleanup(
            {("BR1", self.player["puuid"]): None},
            {(10, self.player["puuid"]): self.player},
            set(),
        )
        c.delete.assert_awaited_once()

    async def test_new_game_observed_at_expiry_prevents_deletion(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 4601
        await self.manager.ensure(self.player, "BR1_2")
        await self.manager.cleanup(
            {("BR1", self.player["puuid"]): {"gameId": 2}},
            {(10, self.player["puuid"]): self.player},
            set(),
        )
        c.delete.assert_not_awaited()

    async def test_riot_failure_or_unqueried_player_never_deletes_possibly_active_channel(
        self,
    ):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 9999
        await self.manager.cleanup({}, {(10, self.player["puuid"]): self.player}, set())
        c.delete.assert_not_awaited()

    async def test_pending_report_prevents_cleanup(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 9999
        await self.manager.cleanup(
            {("BR1", self.player["puuid"]): None},
            {(10, self.player["puuid"]): self.player},
            {(10, self.player["puuid"])},
        )
        c.delete.assert_not_awaited()

    async def test_demo_and_stopped_players_expire_without_riot_key(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 4600
        await self.manager.cleanup({}, {}, set())
        c.delete.assert_awaited_once()

    async def test_safe_delete_retries_forbidden_and_checks_marker(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 4600
        c.delete.side_effect = error()
        self.assertTrue(await self.manager.cleanup({}, {}, set()))
        self.assertFalse((await self.repo.session(10, self.player["puuid"]))["closed"])
        c.topic = "canal-externo"
        c.delete.reset_mock()
        await self.manager.cleanup({}, {}, set())
        c.delete.assert_not_awaited()

    async def test_different_players_and_servers_have_separate_channels(self):
        c = await self.open()
        other = {**self.player, "puuid": "OTHER", "riot_id": "Outro#TAG"}
        cid = await self.manager.ensure(other, "BR1_1")
        await self.manager.configure(self.guild2)
        cross = {**self.player, "guild_id": 20}
        cross_id = await self.manager.ensure(cross, "BR1_1")
        self.assertNotEqual(c.id, cid)
        self.assertIn(cross_id, self.channels2)
        self.assertNotIn(self.role, self.channels2[cross_id].overwrites)

    async def test_crash_after_create_before_ack_recovers_without_duplicate(self):
        real = self.guild.create_text_channel.side_effect

        async def timeout(*args, **kwargs):
            await real(*args, **kwargs)
            raise error()

        self.guild.create_text_channel.side_effect = timeout
        with self.assertRaises(discord.HTTPException):
            await self.open()
        self.assertIsNone(
            (await self.repo.session(10, self.player["puuid"]))["channel_id"]
        )
        self.manager = LoLChannels(
            self.bot, LoLRepository(self.repo.path), clock=lambda: self.now
        )
        cid = await self.manager.ensure(self.player, "BR1_1")
        self.assertIn(cid, self.channels)
        self.guild.create_text_channel.assert_awaited_once()

    async def test_manual_deletion_recreated_immediately_for_same_game(self):
        c = await self.open()
        await self.repo.delivery(10, "BR1_1", "live", self.player["puuid"], c.id)
        await self.repo.acknowledge(10, "BR1_1", "live", self.player["puuid"], 123)
        # Other players' delivery acknowledgements must remain intact.
        await self.repo.delivery(10, "BR1_1", "live", "other", 987)
        await self.repo.acknowledge(10, "BR1_1", "live", "other", 456)
        self.channels.clear()
        new = await self.manager.ensure(self.player, "BR1_1")
        self.assertNotEqual(new, c.id)
        self.assertEqual(await self.manager.ensure(self.player, "BR1_1"), new)
        self.assertEqual(self.guild.create_text_channel.await_count, 2)
        self.assertFalse(
            await self.repo.was_delivered(10, "BR1_1", "live", self.player["puuid"])
        )
        self.assertTrue(await self.repo.was_delivered(10, "BR1_1", "live", "other"))
        self.assertFalse(
            self.channels[new].overwrites[self.guild.default_role].view_channel
        )

    async def test_missing_channel_discovered_during_delivery_can_be_recreated(self):
        c = await self.open()
        self.channels.clear()
        self.assertIsNone(await self.manager.channel_for(10, self.player["puuid"]))
        self.assertNotEqual(await self.manager.ensure(self.player, "BR1_1"), c.id)

    async def test_rest_404_overrides_stale_cache_without_duplicate_creations(self):
        c = await self.open()
        self.channels.clear()
        self.guild.get_channel.side_effect = (
            lambda cid: c if cid == c.id else self.channels.get(cid)
        )
        ids = await asyncio.gather(
            *(self.manager.ensure(self.player, "BR1_1") for _ in range(3))
        )
        self.assertEqual(len(set(ids)), 1)
        self.assertNotEqual(ids[0], c.id)
        self.assertEqual(self.guild.create_text_channel.await_count, 2)

    async def test_access_denied_does_not_mean_deleted(self):
        c = await self.open()
        self.guild.fetch_channel.side_effect = error(discord.Forbidden)
        with self.assertRaises(discord.Forbidden):
            await self.manager.ensure(self.player, "BR1_1")
        self.guild.create_text_channel.assert_awaited_once()
        self.assertEqual(
            (await self.repo.session(10, self.player["puuid"]))["channel_id"], c.id
        )

    async def test_auto_expired_channel_recreated_only_for_new_game(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 4600
        await self.manager.cleanup({}, {}, set())
        self.assertIsNone(await self.manager.ensure(self.player, "BR1_1"))
        new = await self.manager.ensure(self.player, "BR1_2")
        self.assertNotEqual(new, c.id)

    async def test_privacy_drift_is_repaired_before_delivery(self):
        c = await self.open()
        c.overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=True)
        }
        cid = await self.manager.channel_for(10, self.player["puuid"])
        self.assertEqual(cid, c.id)
        self.assertFalse(c.overwrites[self.guild.default_role].view_channel)

    async def test_explicit_category_keeps_channels_private(self):
        cat = MagicMock(spec=discord.CategoryChannel)
        cat.id = 99
        cat.guild = self.guild
        self.channels[99] = cat
        await self.manager.configure(self.guild, cat)
        await self.open()
        self.assertIs(self.guild.create_text_channel.call_args.kwargs["category"], cat)
        self.assertFalse(
            self.guild.create_text_channel.call_args.kwargs["overwrites"][
                self.guild.default_role
            ].view_channel
        )

    async def test_removed_category_never_falls_back_to_public_or_root(self):
        cat = MagicMock(spec=discord.CategoryChannel)
        cat.id = 99
        cat.guild = self.guild
        await self.manager.configure(self.guild, cat)
        with self.assertRaises(LoLChannelError):
            await self.open()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_monitor_automatic_sequence_and_private_reports(self):
        from services.lol_presentation import demo_data

        game, watched, context, result = demo_data(CATALOG)
        p = self.player
        watched_puuid = game["participants"][0]["puuid"]
        p["puuid"] = watched_puuid
        await self.repo.follow(10, p["puuid"], p["riot_id"])
        riot = AsyncMock(spec=RiotClient)
        riot.key = "simulated"
        riot.spectator.return_value = game
        riot.rank.return_value = "GOLD"
        riot.history.return_value = []
        riot.mastery.return_value = None
        riot.match.return_value = result
        dd = AsyncMock(spec=DataDragon)
        dd.catalog.return_value = CATALOG
        monitor = LoLMonitor(self.bot, self.repo, riot, dd, sessions=self.manager)
        await monitor.poll()
        c = next(iter(self.channels.values()))
        self.assertEqual(c.send.await_count, 2)
        riot.spectator.return_value = None
        await monitor.poll()
        self.assertEqual(c.send.await_count, 3)
        self.assertEqual((await self.repo.session(10, p["puuid"]))["delete_at"], 4600)
        self.now = 4601
        next_game = copy.deepcopy(game)
        next_game["gameId"] += 1
        riot.spectator.return_value = next_game
        await monitor.poll()
        self.assertEqual(c.send.await_count, 5)
        c.delete.assert_not_awaited()
        self.assertIsNone((await self.repo.session(10, p["puuid"]))["delete_at"])
        self.guild.create_text_channel.assert_awaited_once()

    async def test_two_followed_teammates_get_their_own_private_destinations(self):
        from services.lol_presentation import demo_data

        game, watched, context, result = demo_data(CATALOG)
        for p in game["participants"][:2]:
            await self.repo.follow(10, p["puuid"], p["riotId"])
        riot = AsyncMock(spec=RiotClient)
        riot.key = "simulated"
        riot.spectator.return_value = game
        riot.rank.return_value = "GOLD"
        riot.history.return_value = []
        riot.mastery.return_value = None
        dd = AsyncMock(spec=DataDragon)
        dd.catalog.return_value = CATALOG
        await LoLMonitor(self.bot, self.repo, riot, dd, sessions=self.manager).poll()
        self.assertEqual(len(self.channels), 2)
        for c in self.channels.values():
            self.assertEqual(c.send.await_count, 2)

    async def test_demo_uses_private_temporary_channel_without_riot_key_or_fixed_destination(
        self,
    ):
        from cogs.lol_tracker import LoLTracker

        cog = object.__new__(LoLTracker)
        cog.bot, cog.repository = self.bot, self.repo
        cog.ddragon = AsyncMock(spec=DataDragon)
        cog.ddragon.catalog.return_value = CATALOG
        cog.monitor = NS(lock=asyncio.Lock(), sessions=self.manager)
        ctx = NS(
            guild=self.guild,
            channel=NS(category=None),
            author=NS(
                id=1, guild_permissions=NS(administrator=True, manage_guild=False)
            ),
            send=AsyncMock(),
        )
        await LoLTracker.demo.callback(cog, ctx)
        self.assertEqual(len(self.channels), 1)
        c = next(iter(self.channels.values()))
        self.assertEqual(c.name, "teste-mochila")
        self.assertEqual(c.send.await_count, 3)
        self.assertFalse(c.overwrites[self.guild.default_role].view_channel)
        self.assertTrue(c.overwrites[self.role].view_channel)
        for call in c.send.await_args_list:
            for embed in call.kwargs["embeds"]:
                self.assertIn("MODO TESTE", embed.title)
        session = await self.repo.session(10, "demo:10")
        self.assertEqual(session["delete_at"], 4600)
        # A single command after manual deletion must succeed, without a failed first attempt.
        self.channels.clear()
        await LoLTracker.demo.callback(cog, ctx)
        replacement = next(iter(self.channels.values()))
        self.assertNotEqual(c.id, replacement.id)
        self.assertEqual(replacement.send.await_count, 3)
        self.now = 4600
        await self.manager.cleanup({}, {}, set())
        replacement.delete.assert_awaited_once()

    async def test_missing_lol_role_prevents_follow_before_any_riot_call(self):
        from cogs.lol_tracker import LoLTracker

        cog = object.__new__(LoLTracker)
        cog.bot, cog.repository = self.bot, self.repo
        cog.riot = AsyncMock(spec=RiotClient)
        cog.monitor = NS(lock=asyncio.Lock(), sessions=self.manager)
        self.guild.roles = [self.guild.default_role]
        self.guild.get_role.side_effect = lambda _: None
        ctx = NS(
            guild=self.guild,
            channel=NS(category=None),
            author=NS(
                id=1, guild_permissions=NS(administrator=True, manage_guild=False)
            ),
            send=AsyncMock(),
        )
        await LoLTracker.follow.callback(cog, ctx, riot_id="Mochila#bunny")
        cog.riot.account.assert_not_awaited()
        self.assertIn("LOL", ctx.send.call_args.kwargs["embed"].description)

    async def test_monitor_restarts_and_only_cleans_after_fresh_offline_confirmation(
        self,
    ):
        from services.lol_presentation import demo_data

        game, watched, context, result = demo_data(CATALOG)
        puuid = watched[0]["puuid"]
        await self.repo.follow(10, puuid, "Mochila#bunny")
        riot = AsyncMock(spec=RiotClient)
        riot.key = "simulated"
        riot.spectator.return_value = game
        riot.rank.return_value = "GOLD"
        riot.history.return_value = []
        riot.mastery.return_value = None
        riot.match.return_value = result
        dd = AsyncMock(spec=DataDragon)
        dd.catalog.return_value = CATALOG
        monitor = LoLMonitor(self.bot, self.repo, riot, dd, sessions=self.manager)
        await monitor.poll()
        c = next(iter(self.channels.values()))
        riot.spectator.return_value = None
        await monitor.poll()
        self.now = 4600
        restarted = LoLMonitor(
            self.bot,
            LoLRepository(self.repo.path),
            riot,
            dd,
            sessions=LoLChannels(
                self.bot, LoLRepository(self.repo.path), clock=lambda: self.now
            ),
        )
        riot.spectator.side_effect = RiotError(429, "cota temporaria")
        await restarted.poll()
        c.delete.assert_not_awaited()
        riot.spectator.side_effect = None
        await restarted.poll()
        c.delete.assert_awaited_once()

    async def test_one_manually_deleted_teammate_channel_does_not_block_other_cleanup(
        self,
    ):
        from services.lol_presentation import demo_data

        game, watched, context, result = demo_data(CATALOG)
        for p in game["participants"][:2]:
            await self.repo.follow(10, p["puuid"], p["riotId"])
        second = copy.deepcopy(result["info"]["participants"][0])
        second["puuid"] = game["participants"][1]["puuid"]
        result["info"]["participants"].append(second)
        riot = AsyncMock(spec=RiotClient)
        riot.key = "simulated"
        riot.spectator.return_value = game
        riot.rank.return_value = "GOLD"
        riot.history.return_value = []
        riot.mastery.return_value = None
        riot.match.return_value = result
        dd = AsyncMock(spec=DataDragon)
        dd.catalog.return_value = CATALOG
        monitor = LoLMonitor(self.bot, self.repo, riot, dd, sessions=self.manager)
        await monitor.poll()
        first, other = list(self.channels.values())
        self.channels.pop(first.id)
        await monitor.poll()
        replacement = next(c for c in self.channels.values() if c.id != other.id)
        self.assertNotEqual(replacement.id, first.id)
        self.assertEqual(replacement.send.await_count, 2)
        self.assertEqual(other.send.await_count, 2)
        riot.spectator.return_value = None
        await monitor.poll()
        self.assertEqual(await self.repo.matches(), [])
        self.now = 4600
        await monitor.poll()
        other.delete.assert_awaited_once()
        replacement.delete.assert_awaited_once()

    def recovery_monitor(self, *, key=""):
        riot = AsyncMock(spec=RiotClient)
        riot.key = key
        riot.spectator.return_value = None
        dd = AsyncMock(spec=DataDragon)
        repo = LoLRepository(self.repo.path)
        return LoLMonitor(
            self.bot,
            repo,
            riot,
            dd,
            sessions=LoLChannels(self.bot, repo, clock=lambda: self.now),
        )

    async def test_login_and_resume_clean_expired_demo_without_providers(self):
        from cogs.lol_tracker import LoLTracker

        demo = {**self.player, "puuid": "demo:10"}
        cid = await self.manager.ensure(demo, "DEMO_1", demo=True)
        channel = self.channels[cid]
        monitor = self.recovery_monitor()
        cog = object.__new__(LoLTracker)
        cog.monitor = monitor
        self.now = 4599
        await cog.on_ready()
        channel.delete.assert_not_awaited()
        self.now = 5000  # Deadline elapsed while disconnected.
        # Recovery must work even while the regular monitor is occupied with enrichment.
        async with monitor.lock:
            await asyncio.wait_for(
                asyncio.gather(cog.on_ready(), cog.on_resumed()), timeout=2
            )
        channel.delete.assert_awaited_once()
        monitor.riot.spectator.assert_not_awaited()
        monitor.riot.history.assert_not_awaited()
        monitor.ddragon.catalog.assert_not_awaited()
        self.assertTrue((await monitor.repository.session(10, "demo:10"))["closed"])

    async def test_demo_crash_after_create_preserves_deadline_before_ack(self):
        create = self.guild.create_text_channel.side_effect

        async def timeout(*args, **kw):
            await create(*args, **kw)
            raise error()

        self.guild.create_text_channel.side_effect = timeout
        demo = {**self.player, "puuid": "demo:10"}
        with self.assertRaises(discord.HTTPException):
            await self.manager.ensure(demo, "DEMO_1", demo=True)
        session = await self.repo.session(10, "demo:10")
        self.assertIsNone(session["channel_id"])
        self.assertEqual(session["delete_at"], 4600)
        channel = next(iter(self.channels.values()))
        self.now = 5000
        await self.recovery_monitor().recover_channels()
        channel.delete.assert_awaited_once()
        self.guild.create_text_channel.assert_awaited_once()

    async def test_recovery_verifies_live_state_and_retries_riot_or_discord_failures(
        self,
    ):
        channel = await self.open()
        await self.repo.follow(10, self.player["puuid"], self.player["riot_id"])
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 5000
        monitor = self.recovery_monitor()
        await (
            monitor.recover_channels()
        )  # Missing key preserves potentially live games.
        channel.delete.assert_not_awaited()
        monitor.riot.key = "simulated"
        monitor.riot.spectator.side_effect = RiotError(429, "simulated")
        await monitor.recover_channels()
        channel.delete.assert_not_awaited()
        monitor.riot.spectator.side_effect = None
        channel.delete.side_effect = error(discord.Forbidden)
        await monitor.recover_channels()
        self.assertFalse((await self.repo.session(10, self.player["puuid"]))["closed"])
        channel.delete.side_effect = None
        await monitor.recover_channels()
        self.assertTrue((await self.repo.session(10, self.player["puuid"]))["closed"])
        monitor.ddragon.catalog.assert_not_awaited()

    async def test_recovery_keeps_channel_when_new_match_started_offline(self):
        channel = await self.open()
        await self.repo.follow(10, self.player["puuid"], self.player["riot_id"])
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 5000
        monitor = self.recovery_monitor(key="simulated")
        monitor.riot.spectator.return_value = {"gameId": 2}
        await monitor.recover_channels()
        channel.delete.assert_not_awaited()
        session = await self.repo.session(10, self.player["puuid"])
        self.assertIsNone(session["delete_at"])
        self.assertEqual(session["last_match"], "BR1_2")

    async def test_late_result_uses_game_end_time_instead_of_restarting_hour(self):
        channel = await self.open()
        self.now = 5000
        await self.manager.finished(10, self.player["puuid"], "BR1_1", ended_at=1000)
        self.assertEqual(
            (await self.repo.session(10, self.player["puuid"]))["delete_at"], 4600
        )
        await self.manager.cleanup({}, {}, set())
        channel.delete.assert_awaited_once()

    async def test_legacy_database_migration_preserves_channel_deadline(self):
        path = Path(self.tmp.name) / "legacy.sqlite3"
        with sqlite3.connect(path) as c:
            c.execute("""CREATE TABLE lol_player_channels (
                guild_id INTEGER, puuid TEXT, generation INTEGER NOT NULL,
                channel_id INTEGER, last_match TEXT, last_live REAL, delete_at REAL,
                closed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,puuid))""")
            c.execute(
                "INSERT INTO lol_player_channels VALUES (10,'legacy',3,123,'BR1_1',1000,4600,0)"
            )
            c.execute(
                "INSERT INTO lol_player_channels VALUES (10,'missing',1,124,'BR1_1',1000,NULL,1)"
            )
        repo = LoLRepository(path)
        row = await repo.session(10, "legacy")
        self.assertEqual(
            (row["channel_id"], row["delete_at"], row["generation"]), (123, 4600, 3)
        )
        self.assertIsNone(row["close_reason"])
        self.assertEqual((await repo.session(10, "missing"))["close_reason"], "missing")
        await repo.new_session(10, "legacy", "BR1_2", 5000)
        self.assertEqual((await repo.session(10, "legacy"))["generation"], 4)

    async def test_finished_player_expires_independently_of_teammates_failed_query(
        self,
    ):
        from services.lol_presentation import demo_data

        game, watched, context, result = demo_data(CATALOG)
        first, second = game["participants"][:2]
        for p in (first, second):
            await self.repo.follow(10, p["puuid"], p["riotId"])
        result2 = copy.deepcopy(result["info"]["participants"][0])
        result2["puuid"] = second["puuid"]
        result["info"]["participants"].append(result2)
        riot = AsyncMock(spec=RiotClient)
        riot.key = "simulated"
        riot.spectator.return_value = game
        riot.rank.return_value = "GOLD"
        riot.history.return_value = []
        riot.mastery.return_value = None
        riot.match.return_value = result
        dd = AsyncMock(spec=DataDragon)
        dd.catalog.return_value = CATALOG
        monitor = LoLMonitor(self.bot, self.repo, riot, dd, sessions=self.manager)
        await monitor.poll()
        first_session = await self.repo.session(10, first["puuid"])
        first_channel = self.channels[first_session["channel_id"]]

        async def state(puuid, platform):
            if puuid == first["puuid"]:
                return None
            raise RiotError(0, "simulated network failure")

        riot.spectator.side_effect = state
        await monitor.poll()
        self.now = 4600
        await monitor.poll()
        first_channel.delete.assert_awaited_once()
        other = await self.repo.session(10, second["puuid"])
        self.assertFalse(other["closed"])

    async def test_legacy_fixed_destination_is_never_used_for_notifications(self):
        from services.lol_presentation import demo_data

        legacy = MagicMock(spec=discord.TextChannel)
        legacy.id = 900
        legacy.guild = self.guild
        legacy.topic = "canal-antigo"
        legacy.send = AsyncMock()
        self.channels[900] = legacy
        await self.repo.configure(10, 900)
        game, watched, context, result = demo_data(CATALOG)
        await self.repo.follow(10, watched[0]["puuid"], "Mochila#bunny")
        riot = AsyncMock(spec=RiotClient)
        riot.key = "simulated"
        riot.spectator.return_value = game
        riot.rank.return_value = "GOLD"
        riot.history.return_value = []
        riot.mastery.return_value = None
        dd = AsyncMock(spec=DataDragon)
        dd.catalog.return_value = CATALOG
        await LoLMonitor(self.bot, self.repo, riot, dd, sessions=self.manager).poll()
        legacy.send.assert_not_awaited()
        session = await self.repo.session(10, watched[0]["puuid"])
        self.assertNotEqual(session["channel_id"], 900)
        self.assertEqual(self.channels[session["channel_id"]].send.await_count, 2)

    async def test_final_fresh_check_catches_game_started_during_slow_enrichment(self):
        c = await self.open()
        await self.manager.finished(10, self.player["puuid"], "BR1_1")
        self.now = 4600
        verify = AsyncMock(return_value={"gameId": 2})
        await self.manager.cleanup(
            {("BR1", self.player["puuid"]): None},
            {(10, self.player["puuid"]): self.player},
            set(),
            verify=verify,
        )
        c.delete.assert_not_awaited()
        self.assertIsNone(
            (await self.repo.session(10, self.player["puuid"]))["delete_at"]
        )
        self.assertEqual(
            (await self.repo.session(10, self.player["puuid"]))["last_match"], "BR1_2"
        )
        self.guild.create_text_channel.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
