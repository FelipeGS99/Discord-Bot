from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

import discord
from discord.ext import commands


MAX_TTS_CHARACTERS = 250
TTS_VOICE = "pt-BR-FranciscaNeural"
IDLE_DISCONNECT_SECONDS = 15


@dataclass(frozen=True)
class SpeechRequest:
    channel: discord.VoiceChannel
    text: str


@dataclass(frozen=True)
class ParsedSpeech:
    channel: discord.VoiceChannel | None
    text: str
    used_explicit_channel: bool
    error: str | None = None


class VoiceTTS(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.queues: dict[int, asyncio.Queue[SpeechRequest]] = {}
        self.queue_tasks: dict[int, asyncio.Task[None]] = {}

    async def cog_unload(self) -> None:
        for task in self.queue_tasks.values():
            task.cancel()
        for voice_client in self.bot.voice_clients:
            if voice_client.is_connected():
                await voice_client.disconnect(force=True)

    @commands.command(name="falar")
    async def speak(self, ctx: commands.Context, *, content: str | None = None) -> None:
        if ctx.guild is None:
            await ctx.send("Esse comando so funciona dentro de um servidor.")
            return

        parsed = parse_speech_content(ctx, content or "")
        if parsed.error is not None:
            await ctx.send(parsed.error)
            return
        if parsed.channel is None:
            await ctx.send("Entre em um canal de voz ou informe um canal. Exemplo: `?falar #Geral oi`.")
            return
        if len(parsed.text) > MAX_TTS_CHARACTERS:
            await ctx.send(f"A mensagem pode ter no maximo {MAX_TTS_CHARACTERS} caracteres.")
            return

        permissions = parsed.channel.permissions_for(ctx.guild.me)
        if not permissions.connect or not permissions.speak:
            await ctx.send("Nao tenho permissao para entrar e falar nesse canal de voz.")
            return

        queue = self.queues.setdefault(ctx.guild.id, asyncio.Queue())
        await queue.put(SpeechRequest(channel=parsed.channel, text=parsed.text))
        if ctx.guild.id not in self.queue_tasks or self.queue_tasks[ctx.guild.id].done():
            self.queue_tasks[ctx.guild.id] = asyncio.create_task(self._process_queue(ctx.guild.id))

        await ctx.send("Mensagem adicionada na fila de voz.", delete_after=5)

    async def _process_queue(self, guild_id: int) -> None:
        queue = self.queues[guild_id]
        try:
            while True:
                try:
                    request = await asyncio.wait_for(queue.get(), timeout=IDLE_DISCONNECT_SECONDS)
                except asyncio.TimeoutError:
                    await self._disconnect_guild_voice(guild_id)
                    return

                try:
                    await self._speak_request(request)
                except Exception as exc:
                    print(f"Erro ao processar TTS: {exc}")
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            await self._disconnect_guild_voice(guild_id)
            raise

    async def _speak_request(self, request: SpeechRequest) -> None:
        voice_client = await self._connect_or_move(request.channel)
        audio_path = await synthesize_speech(request.text)
        playback_done = asyncio.Event()

        def after_playback(error: Exception | None) -> None:
            if error is not None:
                print(f"Erro ao reproduzir TTS: {error}")
            self.bot.loop.call_soon_threadsafe(playback_done.set)

        try:
            source = discord.FFmpegPCMAudio(str(audio_path))
            voice_client.play(source, after=after_playback)
            await playback_done.wait()
        finally:
            audio_path.unlink(missing_ok=True)

    async def _connect_or_move(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        existing = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        if existing is not None and existing.is_connected():
            if existing.channel != channel:
                await existing.move_to(channel)
            return existing
        return await channel.connect()

    async def _disconnect_guild_voice(self, guild_id: int) -> None:
        voice_client = discord.utils.get(self.bot.voice_clients, guild__id=guild_id)
        if voice_client is not None and voice_client.is_connected():
            await voice_client.disconnect()


def parse_speech_content(ctx: commands.Context, content: str) -> ParsedSpeech:
    text = content.strip()
    if not text:
        return ParsedSpeech(channel=None, text="", used_explicit_channel=False, error="Informe o texto para eu falar.")

    channel, token_was_channel_reference, remainder = resolve_voice_channel_prefix(ctx.guild, text)
    if channel is not None:
        speech_text = remainder.strip()
        if not speech_text:
            return ParsedSpeech(
                channel=channel,
                text="",
                used_explicit_channel=True,
                error="Informe o texto que devo falar depois do canal.",
            )
        return ParsedSpeech(channel=channel, text=speech_text, used_explicit_channel=True)

    if token_was_channel_reference:
        return ParsedSpeech(
            channel=None,
            text="",
            used_explicit_channel=True,
            error="Informe um canal de voz valido.",
        )

    author_voice = getattr(ctx.author, "voice", None)
    author_channel = getattr(author_voice, "channel", None)
    if isinstance(author_channel, discord.VoiceChannel):
        return ParsedSpeech(channel=author_channel, text=text, used_explicit_channel=False)

    return ParsedSpeech(
        channel=None,
        text=text,
        used_explicit_channel=False,
        error="Entre em um canal de voz ou mencione um canal de voz. Exemplo: `?falar #Geral oi`.",
    )


def resolve_voice_channel_prefix(
    guild: discord.Guild | None,
    content: str,
) -> tuple[discord.VoiceChannel | None, bool, str]:
    if guild is None:
        return None, False, content

    first_token, _separator, token_remainder = content.partition(" ")

    channel_id = _channel_id_from_token(first_token)
    if channel_id is not None:
        channel = guild.get_channel(channel_id)
        return (channel if isinstance(channel, discord.VoiceChannel) else None), True, token_remainder

    normalized_content = content.casefold()
    for channel in sorted(guild.voice_channels, key=lambda item: len(item.name), reverse=True):
        normalized_name = channel.name.casefold()
        if normalized_content == normalized_name:
            return channel, True, ""
        if normalized_content.startswith(f"{normalized_name} "):
            return channel, True, content[len(channel.name):]
    return None, False, content


async def synthesize_speech(text: str) -> Path:
    import edge_tts

    temporary_file = tempfile.NamedTemporaryFile(prefix="discord_tts_", suffix=".mp3", delete=False)
    audio_path = Path(temporary_file.name)
    temporary_file.close()

    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(audio_path))
    return audio_path


def _channel_id_from_token(token: str) -> int | None:
    if token.startswith("<#") and token.endswith(">"):
        token = token[2:-1]
    if token.isdigit():
        return int(token)
    return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceTTS(bot))
