from __future__ import annotations

import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import discord

from services.discord_messages import brand_embed, send_response


class DiscordMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_help_and_fields_are_paginated_without_losing_content(self):
        target = NS(send=AsyncMock())
        description = "Orientação detalhada.\n" * 450
        field = "Detalhe adicional. " * 300
        await send_response(
            target, description, feature="Ajuda", fields=(("Detalhes", field),)
        )
        cards = [call.kwargs["embed"] for call in target.send.await_args_list]
        self.assertGreater(len(cards), 1)
        rendered = " ".join(
            part
            for card in cards
            for part in [card.description or "", *(f.value for f in card.fields)]
        )
        rendered = " ".join(rendered.split())
        self.assertEqual(rendered.count("Orientação detalhada."), 450)
        self.assertEqual(rendered.count("Detalhe adicional."), 300)
        for card in cards:
            self.assertLessEqual(len(card), 6000)
            self.assertLessEqual(len(card.description or ""), 4096)
            self.assertLessEqual(len(card.fields), 25)
            self.assertTrue(all(len(f.value) <= 1024 for f in card.fields))

    async def test_plain_text_fallback_keeps_role_details_and_disables_pings(self):
        target = NS(
            guild=NS(me=object()),
            send=AsyncMock(),
            channel=NS(permissions_for=lambda _: NS(embed_links=False)),
        )
        await send_response(
            target,
            "Acompanhamento ativado. " * 120,
            feature="Futebol",
            fields=(("Acesso", "<@&123> @everyone"),),
        )
        output = "\n".join(call.args[0] for call in target.send.await_args_list)
        self.assertIn("<@&123>", output)
        for call in target.send.await_args_list:
            self.assertLessEqual(len(call.args[0]), 2000)
            self.assertNotIn("embed", call.kwargs)
            mentions = call.kwargs["allowed_mentions"].to_dict()
            self.assertEqual(mentions["parse"], [])

    async def test_notices_keep_expiry_and_safe_mentions(self):
        target = NS(send=AsyncMock())
        await send_response(
            target,
            "Verifique o canal de voz.",
            feature="Voz",
            tone="warning",
            delete_after=10,
        )
        options = target.send.call_args.kwargs
        self.assertEqual(options["delete_after"], 10)
        self.assertEqual(options["embed"].footer.text, "Tigrão • Voz")
        self.assertEqual(options["allowed_mentions"].to_dict()["parse"], [])

    def test_branding_preserves_notification_recovery_markers(self):
        embed = discord.Embed(title="Partida")
        embed.set_footer(text="Tigrao LoL • evento marcador-de-teste")
        self.assertIs(brand_embed(embed, "LoL"), embed)
        self.assertEqual(embed.footer.text, "Tigrao LoL • evento marcador-de-teste")

    async def test_all_feature_help_cards_fit_discord_and_keep_custom_prefix(self):
        from cogs.brasileirao import Brasileirao
        from cogs.copadobrasil import CopaDoBrasil
        from cogs.esports import Esports
        from cogs.futebol import Futebol
        from cogs.ge_news import GeNews
        from cogs.hangman import Hangman
        from cogs.libertadores import Libertadores
        from cogs.lol_tracker import LoLTracker
        from cogs.moderation import Moderation
        from cogs.pro_lives import ProLives
        from cogs.sulamericana import Sulamericana

        commands = (
            Moderation.commands_list,
            Brasileirao.brasileirao_group,
            CopaDoBrasil.copadobrasil_group,
            Esports.esports_group,
            Futebol.futebol_group,
            GeNews.ge_news_group,
            Hangman.hangman_group,
            Libertadores.libertadores_group,
            LoLTracker.tracker,
            ProLives.pro_lives,
            Sulamericana.sulamericana_group,
        )
        for command in commands:
            with self.subTest(command=command.name):
                ctx = NS(prefix="!", send=AsyncMock())
                await command.callback(None, ctx)
                cards = [call.kwargs["embed"] for call in ctx.send.await_args_list]
                output = "".join(str(card.to_dict()) for card in cards)
                self.assertIn("!", output)
                for card in cards:
                    self.assertLessEqual(len(card), 6000)
                    self.assertTrue(card.title)
                    self.assertIn("Tigrão", card.footer.text)
                    self.assertTrue(all(len(f.value) <= 1024 for f in card.fields))

    async def test_provider_failure_never_exposes_raw_diagnostics(self):
        from cogs.brasileirao import Brasileirao
        from cogs.copadobrasil import CopaDoBrasil
        from cogs.esports import Esports, GAME_CONFIGS
        from cogs.futebol import Futebol
        from cogs.ge_news import GeNews
        from cogs.libertadores import Libertadores
        from cogs.sulamericana import Sulamericana

        ctx = NS(
            send=AsyncMock(),
            guild=NS(owner_id=1),
            author=NS(id=1, guild_permissions=NS(administrator=True)),
        )
        for cls in (
            Brasileirao,
            CopaDoBrasil,
            Libertadores,
            Sulamericana,
            Futebol,
            Esports,
            GeNews,
        ):
            with self.subTest(feature=cls.__name__):
                cog = object.__new__(cls)
                failing = AsyncMock(
                    side_effect=RuntimeError("private-provider-diagnostic")
                )
                cog.api_client = NS(
                    fetch_fixtures=failing, fetch_running_matches=failing
                )
                if cls is Futebol:
                    cog._fetch_grouped_fixtures = failing
                    action = cog.today.callback(cog, ctx)
                elif cls is Esports:
                    action = cog._send_running_matches(ctx, GAME_CONFIGS["lol"])
                elif cls is GeNews:
                    cog.feed_client = NS(fetch_news=failing)
                    action = cog.set_channel.callback(cog, ctx, NS(id=1))
                else:
                    cog.league_id = 9
                    action = cog.today.callback(cog, ctx)
                with self.assertLogs(level="ERROR"):
                    await action
                card = ctx.send.call_args.kwargs["embed"]
                self.assertNotIn("private-provider-diagnostic", str(card.to_dict()))
                self.assertIn("Tente novamente", card.description)


if __name__ == "__main__":
    unittest.main()
