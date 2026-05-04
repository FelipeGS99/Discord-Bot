from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import discord

from bot import COGS
from cogs.ai_chat import (
    AIChat,
    AIChatConfig,
    ChannelMemory,
    ConversationTurn,
    build_response_input,
    extract_mention_prompt,
    limit_response_text,
    load_ai_chat_config,
    should_handle_ai_mention,
)


class AIChatTests(unittest.IsolatedAsyncioTestCase):
    def test_ai_chat_cog_is_loaded(self) -> None:
        self.assertIn("cogs.ai_chat", COGS)

    def test_extract_mention_prompt_removes_bot_mentions(self) -> None:
        prompt = extract_mention_prompt("<@123> oi <@!123> tudo bem?", 123)

        self.assertEqual(prompt, "oi tudo bem?")

    def test_should_handle_ai_mention_ignores_commands_and_bots(self) -> None:
        bot_user = SimpleNamespace(id=123)
        guild = SimpleNamespace(id=1)
        author = SimpleNamespace(bot=False)

        self.assertTrue(
            should_handle_ai_mention(
                SimpleNamespace(
                    author=author,
                    guild=guild,
                    content="<@123> oi",
                    mentions=[bot_user],
                ),
                bot_user,
                "?",
            )
        )
        self.assertFalse(
            should_handle_ai_mention(
                SimpleNamespace(
                    author=author,
                    guild=guild,
                    content="?help <@123>",
                    mentions=[bot_user],
                ),
                bot_user,
                "?",
            )
        )
        self.assertFalse(
            should_handle_ai_mention(
                SimpleNamespace(
                    author=SimpleNamespace(bot=True),
                    guild=guild,
                    content="<@123> oi",
                    mentions=[bot_user],
                ),
                bot_user,
                "?",
            )
        )

    def test_limit_response_text_cuts_safely(self) -> None:
        limited = limit_response_text("uma resposta bem longa para caber na voz", 22)

        self.assertLessEqual(len(limited), 22)
        self.assertTrue(limited.endswith("..."))

    def test_load_ai_chat_config_uses_custom_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai_chat_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "model": "gpt-5.5",
                        "system_prompt": "Fale curto.",
                        "max_response_characters": 180,
                        "max_prompt_characters": 300,
                        "channel_memory_max_turns": 4,
                        "channel_memory_ttl_minutes": 30,
                        "per_user_cooldown_seconds": 7,
                        "request_timeout_seconds": 20,
                        "max_output_tokens": 90,
                        "reasoning_effort": "low",
                        "text_verbosity": "low",
                    }
                ),
                encoding="utf-8",
            )

            config = load_ai_chat_config(config_path)

        self.assertEqual(config.system_prompt, "Fale curto.")
        self.assertEqual(config.max_response_characters, 180)
        self.assertEqual(config.max_prompt_characters, 300)
        self.assertEqual(config.channel_memory_max_turns, 4)
        self.assertEqual(config.channel_memory_ttl_minutes, 30)
        self.assertEqual(config.per_user_cooldown_seconds, 7)
        self.assertEqual(config.request_timeout_seconds, 20)
        self.assertEqual(config.max_output_tokens, 90)

    def test_channel_memory_limits_and_expires_turns(self) -> None:
        now = 1000.0

        def clock() -> float:
            return now

        config = AIChatConfig(channel_memory_max_turns=2, channel_memory_ttl_minutes=1)
        memory = ChannelMemory(config, clock=clock)
        key = (1, 2)

        memory.add_turn(key, "A", "oi", "ola")
        memory.add_turn(key, "B", "tudo bem?", "sim")
        memory.add_turn(key, "C", "beleza", "boa")

        self.assertEqual([turn.author_name for turn in memory.get_history(key)], ["B", "C"])

        now = 1200.0

        self.assertEqual(memory.get_history(key), [])

    def test_build_response_input_includes_channel_history(self) -> None:
        response_input = build_response_input(
            [
                ConversationTurn("Felipe", "oi", "fala!", 1.0),
                ConversationTurn("Ana", "beleza?", "sim", 2.0),
            ],
            "Joao",
            "e ai?",
        )

        self.assertEqual(
            response_input,
            [
                {"role": "user", "content": "Felipe: oi"},
                {"role": "assistant", "content": "fala!"},
                {"role": "user", "content": "Ana: beleza?"},
                {"role": "assistant", "content": "sim"},
                {"role": "user", "content": "Joao: e ai?"},
            ],
        )

    async def test_on_message_replies_text_when_author_is_not_in_voice(self) -> None:
        responder = FakeResponder("Oi, tudo certo!")
        cog = AIChat(
            FakeBot(),
            config=AIChatConfig(per_user_cooldown_seconds=0),
            responder=responder,
        )
        message = FakeMessage(content="<@123> oi", author_voice_channel=None)

        await cog.on_message(message)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("Oi, tudo certo!", message.replies[0])
        self.assertIn("respondi so por texto", message.replies[0])
        self.assertEqual(responder.calls[0]["prompt"], "oi")

    async def test_on_message_applies_user_cooldown(self) -> None:
        now = 1000.0

        def clock() -> float:
            return now

        responder = FakeResponder("Oi!")
        cog = AIChat(
            FakeBot(),
            config=AIChatConfig(per_user_cooldown_seconds=10),
            responder=responder,
            clock=clock,
        )

        await cog.on_message(FakeMessage(content="<@123> oi", author_voice_channel=None))
        second_message = FakeMessage(content="<@123> de novo", author_voice_channel=None)
        await cog.on_message(second_message)

        self.assertEqual(len(responder.calls), 1)
        self.assertEqual(second_message.replies, ["Espera 10s antes de me chamar de novo."])

    async def test_on_message_replies_and_queues_voice_when_author_is_in_voice(self) -> None:
        responder = FakeResponder("Resposta longa que deve caber")
        voice_cog = FakeVoiceCog()
        cog = AIChat(
            FakeBot(voice_cog=voice_cog),
            config=AIChatConfig(max_response_characters=18, per_user_cooldown_seconds=0),
            responder=responder,
        )
        voice_channel = _voice_channel(77, "Geral")
        message = FakeMessage(content="<@123> teste", author_voice_channel=voice_channel)

        await cog.on_message(message)

        self.assertEqual(len(message.replies), 1)
        self.assertLessEqual(len(message.replies[0]), 18)
        self.assertEqual(len(voice_cog.queued), 1)
        self.assertEqual(voice_cog.queued[0]["channel"], voice_channel)
        self.assertEqual(voice_cog.queued[0]["text"], message.replies[0])


class FakeResponder:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(
        self,
        prompt: str,
        author_name: str,
        history: list[ConversationTurn],
    ) -> str:
        self.calls.append({"prompt": prompt, "author_name": author_name, "history": history})
        return self.response


class FakeVoiceCog:
    def __init__(self) -> None:
        self.queued: list[dict[str, object]] = []

    async def enqueue_speech(
        self,
        channel: discord.VoiceChannel,
        text: str,
        text_channel: object | None = None,
        requester_id: int | None = None,
    ) -> None:
        self.queued.append(
            {
                "channel": channel,
                "text": text,
                "text_channel": text_channel,
                "requester_id": requester_id,
            }
        )


class FakeBot:
    def __init__(self, voice_cog: FakeVoiceCog | None = None) -> None:
        self.user = SimpleNamespace(id=123)
        self.command_prefix = "?"
        self.voice_cog = voice_cog

    def get_cog(self, name: str) -> FakeVoiceCog | None:
        return self.voice_cog if name == "VoiceTTS" else None


class FakeTyping:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None


class FakeTextChannel:
    id = 55

    def typing(self) -> FakeTyping:
        return FakeTyping()


class FakeMessage:
    def __init__(self, content: str, author_voice_channel: discord.VoiceChannel | None) -> None:
        self.guild = SimpleNamespace(id=1, me=SimpleNamespace(id=999))
        self.channel = FakeTextChannel()
        self.content = content
        self.mentions = [SimpleNamespace(id=123)]
        self.author = SimpleNamespace(
            bot=False,
            id=42,
            display_name="Felipe",
            voice=SimpleNamespace(channel=author_voice_channel) if author_voice_channel is not None else None,
        )
        self.replies: list[str] = []

    async def reply(self, content: str, **_kwargs: object) -> None:
        self.replies.append(content)


def _voice_channel(channel_id: int, name: str) -> discord.VoiceChannel:
    return SimpleNamespace(
        id=channel_id,
        name=name,
        permissions_for=lambda _member: SimpleNamespace(connect=True, speak=True),
    )


if __name__ == "__main__":
    unittest.main()
