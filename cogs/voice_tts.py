from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import discord
from discord.ext import commands


VOICE_TTS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "voice_tts_config.json"


@dataclass(frozen=True)
class VoiceTTSConfig:
    voice: str = "pt-BR-AntonioNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    max_characters: int = 250
    idle_disconnect_seconds: int = 15
    voice_connect_timeout_seconds: int = 60
    ffmpeg_before_options: str = "-nostdin"
    ffmpeg_options: str = "-vn"


DEFAULT_TTS_CONFIG = VoiceTTSConfig()


def load_voice_tts_config(path: Path = VOICE_TTS_CONFIG_PATH) -> VoiceTTSConfig:
    if not path.exists():
        return DEFAULT_TTS_CONFIG

    try:
        with path.open("r", encoding="utf-8") as config_file:
            raw_config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Nao foi possivel carregar a configuracao de voz em {path}.") from exc

    if not isinstance(raw_config, dict):
        raise RuntimeError(f"A configuracao de voz em {path} precisa ser um objeto JSON.")

    return VoiceTTSConfig(
        voice=_text_config(raw_config, "voice", DEFAULT_TTS_CONFIG.voice),
        rate=_text_config(raw_config, "rate", DEFAULT_TTS_CONFIG.rate),
        volume=_text_config(raw_config, "volume", DEFAULT_TTS_CONFIG.volume),
        pitch=_text_config(raw_config, "pitch", DEFAULT_TTS_CONFIG.pitch),
        max_characters=_positive_int_config(raw_config, "max_characters", DEFAULT_TTS_CONFIG.max_characters),
        idle_disconnect_seconds=_positive_int_config(
            raw_config,
            "idle_disconnect_seconds",
            DEFAULT_TTS_CONFIG.idle_disconnect_seconds,
        ),
        voice_connect_timeout_seconds=_positive_int_config(
            raw_config,
            "voice_connect_timeout_seconds",
            DEFAULT_TTS_CONFIG.voice_connect_timeout_seconds,
        ),
        ffmpeg_before_options=_text_config(
            raw_config,
            "ffmpeg_before_options",
            DEFAULT_TTS_CONFIG.ffmpeg_before_options,
        ),
        ffmpeg_options=_text_config(raw_config, "ffmpeg_options", DEFAULT_TTS_CONFIG.ffmpeg_options),
    )


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


VOICE_TTS_CONFIG = load_voice_tts_config()
MAX_TTS_CHARACTERS = VOICE_TTS_CONFIG.max_characters
IDLE_DISCONNECT_SECONDS = VOICE_TTS_CONFIG.idle_disconnect_seconds
VOICE_CONNECT_TIMEOUT_SECONDS = VOICE_TTS_CONFIG.voice_connect_timeout_seconds
TTS_VOICE = VOICE_TTS_CONFIG.voice


@dataclass(frozen=True)
class SpeechRequest:
    channel: discord.VoiceChannel
    text: str
    text_channel: discord.abc.Messageable | None = None
    requester_id: int | None = None


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

        await self.enqueue_speech(
            channel=parsed.channel,
            text=parsed.text,
            text_channel=ctx.channel,
            requester_id=ctx.author.id,
        )
        await ctx.send("Mensagem adicionada na fila de voz.", delete_after=5)

    async def enqueue_speech(
        self,
        channel: discord.VoiceChannel,
        text: str,
        text_channel: discord.abc.Messageable | None = None,
        requester_id: int | None = None,
    ) -> None:
        guild_id = channel.guild.id
        queue = self.queues.setdefault(guild_id, asyncio.Queue())
        await queue.put(
            SpeechRequest(
                channel=channel,
                text=text,
                text_channel=text_channel,
                requester_id=requester_id,
            )
        )
        if guild_id not in self.queue_tasks or self.queue_tasks[guild_id].done():
            self.queue_tasks[guild_id] = asyncio.create_task(self._process_queue(guild_id))

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
                    if request.text_channel is not None:
                        await request.text_channel.send(f"Nao consegui reproduzir o audio: {_format_error(exc)}", delete_after=10)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            await self._disconnect_guild_voice(guild_id)
            raise

    async def _speak_request(self, request: SpeechRequest) -> None:
        voice_client = await self._connect_or_move(request.channel)
        await self._wait_until_connected(voice_client, request.channel)
        audio_path = await synthesize_speech(request.text)
        playback_done = asyncio.Event()
        playback_error: Exception | None = None
        source: discord.AudioSource | None = None

        def after_playback(error: Exception | None) -> None:
            nonlocal playback_error
            playback_error = error
            self.bot.loop.call_soon_threadsafe(playback_done.set)

        try:
            ffmpeg_executable = shutil.which("ffmpeg") or "ffmpeg"
            if not voice_client.is_connected():
                raise RuntimeError("A conexao de voz nao ficou pronta antes da reproducao.")
            source = discord.FFmpegOpusAudio(
                str(audio_path),
                executable=ffmpeg_executable,
                before_options=VOICE_TTS_CONFIG.ffmpeg_before_options,
                options=VOICE_TTS_CONFIG.ffmpeg_options,
            )
            voice_client.play(source, after=after_playback)
            await playback_done.wait()
            if playback_error is not None:
                raise playback_error
        except Exception:
            if source is not None:
                source.cleanup()
            raise
        finally:
            audio_path.unlink(missing_ok=True)

    async def _connect_or_move(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        existing = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        if existing is not None:
            if existing.is_connected():
                if existing.channel != channel:
                    await existing.move_to(channel, timeout=VOICE_CONNECT_TIMEOUT_SECONDS)
                return existing
            await existing.disconnect(force=True)

        try:
            return await channel.connect(
                timeout=VOICE_CONNECT_TIMEOUT_SECONDS,
                reconnect=True,
                self_deaf=True,
            )
        except asyncio.TimeoutError:
            await self._disconnect_guild_voice(channel.guild.id)
            raise

    async def _wait_until_connected(
        self,
        voice_client: discord.VoiceClient,
        channel: discord.VoiceChannel,
    ) -> None:
        if voice_client.is_connected():
            return

        connected = await asyncio.to_thread(voice_client.wait_until_connected, VOICE_CONNECT_TIMEOUT_SECONDS)
        if not connected:
            await voice_client.disconnect(force=True)
            raise RuntimeError("Nao consegui concluir a conexao de voz com o Discord.")

    async def _disconnect_guild_voice(self, guild_id: int) -> None:
        voice_client = next(
            (client for client in self.bot.voice_clients if client.guild and client.guild.id == guild_id),
            None,
        )
        if voice_client is not None:
            await voice_client.disconnect(force=True)


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


async def synthesize_speech(text: str, config: VoiceTTSConfig = VOICE_TTS_CONFIG) -> Path:
    import edge_tts

    temporary_file = tempfile.NamedTemporaryFile(prefix="discord_tts_", suffix=".mp3", delete=False)
    audio_path = Path(temporary_file.name)
    temporary_file.close()

    communicate = edge_tts.Communicate(
        text,
        config.voice,
        rate=config.rate,
        volume=config.volume,
        pitch=config.pitch,
    )
    await communicate.save(str(audio_path))
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        raise RuntimeError("O TTS gerou um arquivo de audio vazio.")
    return audio_path


def _channel_id_from_token(token: str) -> int | None:
    if token.startswith("<#") and token.endswith(">"):
        token = token[2:-1]
    if token.isdigit():
        return int(token)
    return None


def _format_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "tempo limite ao conectar no canal de voz."
    message = str(error).strip()
    if "davey library needed" in message.lower():
        return "biblioteca de voz davey ausente no ambiente."
    return message or error.__class__.__name__


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceTTS(bot))
