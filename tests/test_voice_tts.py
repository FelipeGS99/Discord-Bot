from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import discord

from bot import COGS
from cogs.voice_tts import MAX_TTS_CHARACTERS, SpeechRequest, parse_speech_content


class VoiceTTSTests(unittest.IsolatedAsyncioTestCase):
    def test_voice_tts_cog_is_loaded(self) -> None:
        self.assertIn("cogs.voice_tts", COGS)

    def test_parse_uses_author_voice_channel_when_channel_is_not_mentioned(self) -> None:
        channel = _voice_channel(123, "Geral")
        ctx = _context(_guild([channel]), author_channel=channel)

        parsed = parse_speech_content(ctx, "oi")

        self.assertIs(parsed.channel, channel)
        self.assertEqual(parsed.text, "oi")
        self.assertFalse(parsed.used_explicit_channel)
        self.assertIsNone(parsed.error)

    def test_parse_mentioned_channel_without_author_voice(self) -> None:
        channel = _voice_channel(123, "Geral")
        ctx = _context(_guild([channel]), author_channel=None)

        parsed = parse_speech_content(ctx, "<#123> teste")

        self.assertIs(parsed.channel, channel)
        self.assertEqual(parsed.text, "teste")
        self.assertTrue(parsed.used_explicit_channel)
        self.assertIsNone(parsed.error)

    def test_parse_channel_id_without_author_voice(self) -> None:
        channel = _voice_channel(123, "Geral")
        ctx = _context(_guild([channel]), author_channel=None)

        parsed = parse_speech_content(ctx, "123 teste")

        self.assertIs(parsed.channel, channel)
        self.assertEqual(parsed.text, "teste")
        self.assertTrue(parsed.used_explicit_channel)

    def test_parse_voice_channel_name_with_spaces(self) -> None:
        channel = _voice_channel(123, "Sala Geral")
        ctx = _context(_guild([channel]), author_channel=None)

        parsed = parse_speech_content(ctx, "Sala Geral bom dia")

        self.assertIs(parsed.channel, channel)
        self.assertEqual(parsed.text, "bom dia")
        self.assertTrue(parsed.used_explicit_channel)

    def test_parse_errors_without_channel_and_author_voice(self) -> None:
        ctx = _context(_guild([]), author_channel=None)

        parsed = parse_speech_content(ctx, "oi")

        self.assertIsNotNone(parsed.error)

    def test_parse_errors_without_text(self) -> None:
        channel = _voice_channel(123, "Geral")
        ctx = _context(_guild([channel]), author_channel=channel)

        parsed = parse_speech_content(ctx, "")

        self.assertEqual(parsed.error, "Informe o texto para eu falar.")

    def test_parse_errors_when_channel_has_no_message(self) -> None:
        channel = _voice_channel(123, "Geral")
        ctx = _context(_guild([channel]), author_channel=None)

        parsed = parse_speech_content(ctx, "<#123>")

        self.assertEqual(parsed.error, "Informe o texto que devo falar depois do canal.")

    def test_text_limit_constant(self) -> None:
        self.assertEqual(MAX_TTS_CHARACTERS, 250)

    async def test_queue_preserves_order(self) -> None:
        first_channel = _voice_channel(1, "Um")
        second_channel = _voice_channel(2, "Dois")
        queue: asyncio.Queue[SpeechRequest] = asyncio.Queue()

        await queue.put(SpeechRequest(first_channel, "primeiro"))
        await queue.put(SpeechRequest(second_channel, "segundo"))

        self.assertEqual((await queue.get()).text, "primeiro")
        self.assertEqual((await queue.get()).text, "segundo")


def _voice_channel(channel_id: int, name: str) -> discord.VoiceChannel:
    channel = object.__new__(discord.VoiceChannel)
    channel.id = channel_id
    channel.name = name
    return channel


def _guild(channels: list[discord.VoiceChannel]) -> SimpleNamespace:
    channels_by_id = {channel.id: channel for channel in channels}
    guild = SimpleNamespace(
        voice_channels=channels,
        get_channel=lambda channel_id: channels_by_id.get(channel_id),
    )
    for channel in channels:
        channel.guild = guild
    return guild


def _context(guild: SimpleNamespace, author_channel: discord.VoiceChannel | None) -> SimpleNamespace:
    voice = SimpleNamespace(channel=author_channel) if author_channel is not None else None
    return SimpleNamespace(guild=guild, author=SimpleNamespace(voice=voice))


if __name__ == "__main__":
    unittest.main()
