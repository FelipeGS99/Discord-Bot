from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import discord
from discord.ext import commands
from openai import AsyncOpenAI

from config import settings

AI_CHAT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "ai_chat_config.json"


@dataclass(frozen=True)
class AIChatConfig:
    model: str = "gpt-5.5"
    system_prompt: str = (
        "Voce e o Tigrao, um bot brasileiro de Discord. Responda em PT-BR, "
        "com tom natural, bem-humorado quando combinar, e sem enrolar."
    )
    max_response_characters: int = 250
    max_prompt_characters: int = 500
    channel_memory_max_turns: int = 6
    channel_memory_ttl_minutes: int = 120
    per_user_cooldown_seconds: int = 15
    request_timeout_seconds: int = 30
    max_output_tokens: int = 120
    reasoning_effort: str = "low"
    text_verbosity: str = "low"


DEFAULT_AI_CHAT_CONFIG = AIChatConfig()


@dataclass(frozen=True)
class ConversationTurn:
    author_name: str
    user_text: str
    assistant_text: str
    updated_at: float


class ChatResponder(Protocol):
    async def generate_reply(
        self,
        prompt: str,
        author_name: str,
        history: list[ConversationTurn],
    ) -> str:
        ...


class MissingOpenAIKey(RuntimeError):
    pass


def _text_config(raw_config: dict[str, object], key: str, default: str) -> str:
    value = raw_config.get(key, default)
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def _positive_int_config(raw_config: dict[str, object], key: str, default: int) -> int:
    value = raw_config.get(key, default)
    if isinstance(value, bool):
        return default
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return default
    return parsed_value if parsed_value > 0 else default


def load_ai_chat_config(path: Path = AI_CHAT_CONFIG_PATH) -> AIChatConfig:
    if not path.exists():
        return DEFAULT_AI_CHAT_CONFIG

    try:
        with path.open("r", encoding="utf-8") as config_file:
            raw_config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Nao foi possivel carregar a configuracao de IA em {path}.") from exc

    if not isinstance(raw_config, dict):
        raise RuntimeError(f"A configuracao de IA em {path} precisa ser um objeto JSON.")

    return AIChatConfig(
        model=_text_config(raw_config, "model", DEFAULT_AI_CHAT_CONFIG.model),
        system_prompt=_text_config(raw_config, "system_prompt", DEFAULT_AI_CHAT_CONFIG.system_prompt),
        max_response_characters=_positive_int_config(
            raw_config,
            "max_response_characters",
            DEFAULT_AI_CHAT_CONFIG.max_response_characters,
        ),
        max_prompt_characters=_positive_int_config(
            raw_config,
            "max_prompt_characters",
            DEFAULT_AI_CHAT_CONFIG.max_prompt_characters,
        ),
        channel_memory_max_turns=_positive_int_config(
            raw_config,
            "channel_memory_max_turns",
            DEFAULT_AI_CHAT_CONFIG.channel_memory_max_turns,
        ),
        channel_memory_ttl_minutes=_positive_int_config(
            raw_config,
            "channel_memory_ttl_minutes",
            DEFAULT_AI_CHAT_CONFIG.channel_memory_ttl_minutes,
        ),
        per_user_cooldown_seconds=_positive_int_config(
            raw_config,
            "per_user_cooldown_seconds",
            DEFAULT_AI_CHAT_CONFIG.per_user_cooldown_seconds,
        ),
        request_timeout_seconds=_positive_int_config(
            raw_config,
            "request_timeout_seconds",
            DEFAULT_AI_CHAT_CONFIG.request_timeout_seconds,
        ),
        max_output_tokens=_positive_int_config(raw_config, "max_output_tokens", DEFAULT_AI_CHAT_CONFIG.max_output_tokens),
        reasoning_effort=_text_config(raw_config, "reasoning_effort", DEFAULT_AI_CHAT_CONFIG.reasoning_effort),
        text_verbosity=_text_config(raw_config, "text_verbosity", DEFAULT_AI_CHAT_CONFIG.text_verbosity),
    )


class ChannelMemory:
    def __init__(self, config: AIChatConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self.clock = clock
        self.turns_by_channel: dict[tuple[int, int], list[ConversationTurn]] = {}

    def get_history(self, channel_key: tuple[int, int]) -> list[ConversationTurn]:
        self._expire_channel(channel_key)
        return list(self.turns_by_channel.get(channel_key, []))

    def add_turn(
        self,
        channel_key: tuple[int, int],
        author_name: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        self._expire_channel(channel_key)
        turns = self.turns_by_channel.setdefault(channel_key, [])
        turns.append(
            ConversationTurn(
                author_name=author_name,
                user_text=user_text,
                assistant_text=assistant_text,
                updated_at=self.clock(),
            )
        )
        del turns[: max(0, len(turns) - self.config.channel_memory_max_turns)]

    def _expire_channel(self, channel_key: tuple[int, int]) -> None:
        turns = self.turns_by_channel.get(channel_key)
        if not turns:
            return
        ttl_seconds = self.config.channel_memory_ttl_minutes * 60
        if self.clock() - turns[-1].updated_at > ttl_seconds:
            self.turns_by_channel.pop(channel_key, None)


class OpenAIChatResponder:
    def __init__(self, api_key: str | None, config: AIChatConfig) -> None:
        self.config = config
        self.client = (
            AsyncOpenAI(api_key=api_key, timeout=config.request_timeout_seconds)
            if api_key
            else None
        )

    async def generate_reply(
        self,
        prompt: str,
        author_name: str,
        history: list[ConversationTurn],
    ) -> str:
        if self.client is None:
            raise MissingOpenAIKey("OPENAI_API_KEY nao foi configurada.")

        response = await self.client.responses.create(
            model=self.config.model,
            instructions=build_instructions(self.config),
            input=build_response_input(history, author_name, prompt),
            max_output_tokens=self.config.max_output_tokens,
            reasoning={"effort": self.config.reasoning_effort},
            text={"verbosity": self.config.text_verbosity},
            store=False,
        )
        output_text = normalize_response_text(getattr(response, "output_text", "") or "")
        if not output_text:
            return "Nao consegui montar uma resposta agora."
        return limit_response_text(output_text, self.config.max_response_characters)


class AIChat(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        config: AIChatConfig = load_ai_chat_config(),
        responder: ChatResponder | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bot = bot
        self.config = config
        self.clock = clock
        self.memory = ChannelMemory(config, clock=clock)
        self.responder = responder or OpenAIChatResponder(settings.openai_api_key, config)
        self.cooldowns: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not should_handle_ai_mention(message, self.bot.user, self.bot.command_prefix):
            return

        assert message.guild is not None
        assert self.bot.user is not None

        prompt = extract_mention_prompt(message.content, self.bot.user.id)
        if not prompt:
            await reply_without_mentions(message, "Me diga o que voce quer perguntar.")
            return
        if len(prompt) > self.config.max_prompt_characters:
            await reply_without_mentions(message, f"Sua mensagem pode ter no maximo {self.config.max_prompt_characters} caracteres.")
            return

        cooldown_remaining = self._cooldown_remaining(message.guild.id, message.author.id)
        if cooldown_remaining > 0:
            await reply_without_mentions(message, f"Espera {cooldown_remaining}s antes de me chamar de novo.")
            return
        self._mark_cooldown(message.guild.id, message.author.id)

        channel_key = (message.guild.id, message.channel.id)
        history = self.memory.get_history(channel_key)
        author_name = display_name_for(message.author)

        try:
            async with message.channel.typing():
                answer = await self.responder.generate_reply(prompt, author_name, history)
        except MissingOpenAIKey:
            await reply_without_mentions(message, "A OPENAI_API_KEY nao foi configurada no .env.")
            return
        except Exception:
            await reply_without_mentions(message, "Nao consegui falar com a OpenAI agora. Tenta de novo em instantes.")
            return

        answer = limit_response_text(answer, self.config.max_response_characters)
        self.memory.add_turn(channel_key, author_name, prompt, answer)
        voice_note = await self._queue_voice_response(message, answer)
        reply_text = answer if voice_note is None else f"{answer}\n\n{voice_note}"
        await reply_without_mentions(message, reply_text)

    async def _queue_voice_response(self, message: discord.Message, answer: str) -> str | None:
        voice_channel = author_voice_channel(message.author)
        if voice_channel is None:
            return "Nao encontrei voce em um canal de voz, entao respondi so por texto."

        assert message.guild is not None
        permissions = voice_channel.permissions_for(message.guild.me)
        if not permissions.connect or not permissions.speak:
            return "Nao tenho permissao para entrar e falar no seu canal de voz."

        voice_tts = self.bot.get_cog("VoiceTTS")
        if voice_tts is None or not hasattr(voice_tts, "enqueue_speech"):
            return "O sistema de voz nao esta carregado agora."

        await voice_tts.enqueue_speech(
            channel=voice_channel,
            text=answer,
            text_channel=message.channel,
            requester_id=message.author.id,
        )
        return None

    def _cooldown_remaining(self, guild_id: int, user_id: int) -> int:
        cooldown_seconds = self.config.per_user_cooldown_seconds
        last_used = self.cooldowns.get((guild_id, user_id))
        if last_used is None:
            return 0
        elapsed = self.clock() - last_used
        if elapsed >= cooldown_seconds:
            return 0
        return max(1, math.ceil(cooldown_seconds - elapsed))

    def _mark_cooldown(self, guild_id: int, user_id: int) -> None:
        self.cooldowns[(guild_id, user_id)] = self.clock()


def should_handle_ai_mention(
    message: discord.Message,
    bot_user: discord.ClientUser | None,
    command_prefix: object,
) -> bool:
    if bot_user is None or message.author.bot or message.guild is None:
        return False
    content = message.content.strip()
    if not content or starts_with_command_prefix(content, command_prefix):
        return False
    return any(getattr(user, "id", None) == bot_user.id for user in message.mentions)


def starts_with_command_prefix(content: str, command_prefix: object) -> bool:
    prefixes: tuple[str, ...]
    if isinstance(command_prefix, str):
        prefixes = (command_prefix,)
    elif isinstance(command_prefix, (list, tuple)):
        prefixes = tuple(prefix for prefix in command_prefix if isinstance(prefix, str))
    else:
        prefixes = ()
    return any(content.startswith(prefix) for prefix in prefixes)


def extract_mention_prompt(content: str, bot_user_id: int) -> str:
    text = content.replace(f"<@{bot_user_id}>", " ").replace(f"<@!{bot_user_id}>", " ")
    return " ".join(text.split())


def author_voice_channel(author: discord.abc.User) -> discord.VoiceChannel | None:
    voice_state = getattr(author, "voice", None)
    channel = getattr(voice_state, "channel", None)
    return channel if channel is not None and hasattr(channel, "permissions_for") else None


def display_name_for(author: discord.abc.User) -> str:
    return getattr(author, "display_name", None) or getattr(author, "name", "Usuario")


async def reply_without_mentions(message: discord.Message, content: str) -> None:
    await message.reply(
        content,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )


def build_instructions(config: AIChatConfig) -> str:
    return (
        f"{config.system_prompt}\n\n"
        f"Responda com no maximo {config.max_response_characters} caracteres. "
        "Nao use Markdown, listas longas nem blocos de codigo. "
        "Se a pergunta for ambigua, responda de forma curta e natural."
    )


def build_response_input(
    history: list[ConversationTurn],
    author_name: str,
    prompt: str,
) -> list[dict[str, str]]:
    response_input: list[dict[str, str]] = []
    for turn in history:
        response_input.append({"role": "user", "content": f"{turn.author_name}: {turn.user_text}"})
        response_input.append({"role": "assistant", "content": turn.assistant_text})
    response_input.append({"role": "user", "content": f"{author_name}: {prompt}"})
    return response_input


def normalize_response_text(text: str) -> str:
    return " ".join(text.split())


def limit_response_text(text: str, max_characters: int) -> str:
    normalized_text = normalize_response_text(text)
    if len(normalized_text) <= max_characters:
        return normalized_text
    if max_characters <= 3:
        return normalized_text[:max_characters]

    cut = normalized_text[: max_characters - 3].rstrip()
    last_space = cut.rfind(" ")
    if last_space >= max(20, (max_characters - 3) // 2):
        cut = cut[:last_space].rstrip()
    return f"{cut}..."


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChat(bot))
