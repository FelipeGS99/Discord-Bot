from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord
from discord.voice_state import VoiceConnectionState
from discord.ext import commands


MAX_TTS_CHARACTERS = 250
TTS_VOICE = "pt-BR-FranciscaNeural"
IDLE_DISCONNECT_SECONDS = 15
VOICE_CONNECT_TIMEOUT_SECONDS = 60


class DiagnosticVoiceClient(discord.VoiceClient):
    def create_connection_state(self) -> VoiceConnectionState:
        return VoiceConnectionState(self, hook=_voice_websocket_hook)

    async def on_voice_state_update(self, data: dict[str, Any]) -> None:
        _log(
            "discord_voice_state_update",
            guild_id=data.get("guild_id"),
            channel_id=data.get("channel_id"),
            user_id=data.get("user_id"),
            self_user_id=getattr(self.user, "id", None),
            is_self=str(data.get("user_id")) == str(getattr(self.user, "id", None)),
            has_session=bool(data.get("session_id")),
        )
        await super().on_voice_state_update(data)

    async def on_voice_server_update(self, data: dict[str, Any]) -> None:
        _log(
            "discord_voice_server_update",
            guild_id=data.get("guild_id"),
            endpoint=data.get("endpoint"),
            has_token=bool(data.get("token")),
        )
        await super().on_voice_server_update(data)


async def _voice_websocket_hook(websocket: discord.gateway.DiscordVoiceWebSocket, message: dict[str, Any]) -> None:
    opcode = message.get("op")
    data = message.get("d")
    event_fields: dict[str, object] = {"op": opcode}
    if opcode == websocket.READY and isinstance(data, dict):
        event_fields.update(
            {
                "ssrc": data.get("ssrc"),
                "ip": data.get("ip"),
                "port": data.get("port"),
                "modes": ",".join(str(mode) for mode in data.get("modes", [])),
            }
        )
    elif opcode == websocket.SESSION_DESCRIPTION and isinstance(data, dict):
        event_fields.update(
            {
                "mode": data.get("mode"),
                "has_secret_key": bool(data.get("secret_key")),
            }
        )
    elif opcode == websocket.HELLO and isinstance(data, dict):
        event_fields["heartbeat_interval"] = data.get("heartbeat_interval")
    elif opcode == websocket.HEARTBEAT_ACK:
        event_fields["ack"] = True
    _log("voice_websocket_message", **event_fields)


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
        _enable_discord_voice_logging()

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

        queue = self.queues.setdefault(ctx.guild.id, asyncio.Queue())
        _log(
            "queued",
            guild_id=ctx.guild.id,
            channel_id=parsed.channel.id,
            requester_id=ctx.author.id,
            explicit_channel=parsed.used_explicit_channel,
            text_length=len(parsed.text),
            queue_size=queue.qsize(),
        )
        await queue.put(
            SpeechRequest(
                channel=parsed.channel,
                text=parsed.text,
                text_channel=ctx.channel,
                requester_id=ctx.author.id,
            )
        )
        if ctx.guild.id not in self.queue_tasks or self.queue_tasks[ctx.guild.id].done():
            _log("starting_queue_worker", guild_id=ctx.guild.id)
            self.queue_tasks[ctx.guild.id] = asyncio.create_task(self._process_queue(ctx.guild.id))

        await ctx.send("Mensagem adicionada na fila de voz.", delete_after=5)

    async def _process_queue(self, guild_id: int) -> None:
        queue = self.queues[guild_id]
        _log("queue_worker_started", guild_id=guild_id)
        try:
            while True:
                try:
                    request = await asyncio.wait_for(queue.get(), timeout=IDLE_DISCONNECT_SECONDS)
                except asyncio.TimeoutError:
                    _log("queue_idle_timeout", guild_id=guild_id)
                    await self._disconnect_guild_voice(guild_id)
                    return

                try:
                    _log(
                        "processing_request",
                        guild_id=guild_id,
                        channel_id=request.channel.id,
                        requester_id=request.requester_id,
                        remaining_queue=queue.qsize(),
                    )
                    await self._speak_request(request)
                except Exception as exc:
                    _log("request_failed", guild_id=guild_id, error=repr(exc))
                    if request.text_channel is not None:
                        await request.text_channel.send(f"Nao consegui reproduzir o audio: {_format_error(exc)}", delete_after=10)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            _log("queue_worker_cancelled", guild_id=guild_id)
            await self._disconnect_guild_voice(guild_id)
            raise

    async def _speak_request(self, request: SpeechRequest) -> None:
        _log("connecting_or_moving", guild_id=request.channel.guild.id, channel_id=request.channel.id)
        voice_client = await self._connect_or_move(request.channel)
        await self._wait_until_connected(voice_client, request.channel)
        _log(
            "voice_ready",
            guild_id=request.channel.guild.id,
            channel_id=request.channel.id,
            connected=voice_client.is_connected(),
            playing=voice_client.is_playing(),
        )
        audio_path = await synthesize_speech(request.text)
        playback_done = asyncio.Event()
        source: discord.AudioSource | None = None

        def after_playback(error: Exception | None) -> None:
            if error is not None:
                _log("playback_callback_error", guild_id=request.channel.guild.id, error=repr(error))
            else:
                _log("playback_callback_done", guild_id=request.channel.guild.id)
            self.bot.loop.call_soon_threadsafe(playback_done.set)

        try:
            ffmpeg_executable = shutil.which("ffmpeg") or "ffmpeg"
            _log(
                "starting_playback",
                guild_id=request.channel.guild.id,
                channel_id=request.channel.id,
                audio_path=str(audio_path),
                audio_exists=audio_path.exists(),
                audio_size=audio_path.stat().st_size if audio_path.exists() else 0,
                ffmpeg=ffmpeg_executable,
            )
            if not voice_client.is_connected():
                raise RuntimeError("A conexao de voz nao ficou pronta antes da reproducao.")
            source = discord.FFmpegOpusAudio(
                str(audio_path),
                executable=ffmpeg_executable,
                before_options="-nostdin",
                options="-vn",
            )
            _log(
                "audio_source_created",
                guild_id=request.channel.guild.id,
                channel_id=request.channel.id,
                source_type=source.__class__.__name__,
                source_is_opus=source.is_opus(),
            )
            voice_client.play(source, after=after_playback)
            await playback_done.wait()
            _log("playback_finished", guild_id=request.channel.guild.id, channel_id=request.channel.id)
        except Exception:
            if source is not None:
                source.cleanup()
            raise
        finally:
            _log("removing_audio_file", audio_path=str(audio_path), exists=audio_path.exists())
            audio_path.unlink(missing_ok=True)

    async def _connect_or_move(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        existing = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
        if existing is not None:
            if existing.is_connected():
                if existing.channel != channel:
                    _log(
                        "moving_voice_client",
                        guild_id=channel.guild.id,
                        from_channel_id=getattr(existing.channel, "id", None),
                        to_channel_id=channel.id,
                    )
                    await existing.move_to(channel, timeout=VOICE_CONNECT_TIMEOUT_SECONDS)
                return existing
            _log(
                "cleaning_stale_voice_client",
                guild_id=channel.guild.id,
                channel_id=getattr(existing.channel, "id", None),
                connected=existing.is_connected(),
            )
            await existing.disconnect(force=True)
        _log("connecting_voice_client", guild_id=channel.guild.id, channel_id=channel.id)
        try:
            return await channel.connect(
                timeout=VOICE_CONNECT_TIMEOUT_SECONDS,
                reconnect=True,
                self_deaf=True,
                cls=DiagnosticVoiceClient,
            )
        except asyncio.TimeoutError:
            me_voice = getattr(channel.guild.me, "voice", None)
            me_channel = getattr(me_voice, "channel", None)
            _log(
                "voice_connect_timeout",
                guild_id=channel.guild.id,
                requested_channel_id=channel.id,
                bot_voice_channel_id=getattr(me_channel, "id", None),
                timeout=VOICE_CONNECT_TIMEOUT_SECONDS,
            )
            await self._disconnect_guild_voice(channel.guild.id)
            raise

    async def _wait_until_connected(
        self,
        voice_client: discord.VoiceClient,
        channel: discord.VoiceChannel,
    ) -> None:
        if voice_client.is_connected():
            _log("voice_connection_already_ready", guild_id=channel.guild.id, channel_id=channel.id)
            return

        _log(
            "voice_connection_wait_started",
            guild_id=channel.guild.id,
            channel_id=channel.id,
            timeout=VOICE_CONNECT_TIMEOUT_SECONDS,
        )
        connected = await asyncio.to_thread(voice_client.wait_until_connected, VOICE_CONNECT_TIMEOUT_SECONDS)
        _log(
            "voice_connection_wait_finished",
            guild_id=channel.guild.id,
            channel_id=channel.id,
            connected=connected,
        )
        if not connected:
            await voice_client.disconnect(force=True)
            raise RuntimeError("Nao consegui concluir a conexao de voz com o Discord.")

    async def _disconnect_guild_voice(self, guild_id: int) -> None:
        voice_client = next(
            (client for client in self.bot.voice_clients if client.guild and client.guild.id == guild_id),
            None,
        )
        if voice_client is None:
            _log("disconnect_skipped_no_client", guild_id=guild_id)
            return

        _log(
            "disconnecting_voice_client",
            guild_id=guild_id,
            channel_id=getattr(voice_client.channel, "id", None),
            connected=voice_client.is_connected(),
        )
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


async def synthesize_speech(text: str) -> Path:
    import edge_tts

    _log("tts_generation_started", text_length=len(text), voice=TTS_VOICE)
    temporary_file = tempfile.NamedTemporaryFile(prefix="discord_tts_", suffix=".mp3", delete=False)
    audio_path = Path(temporary_file.name)
    temporary_file.close()

    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(audio_path))
    _log(
        "tts_generation_finished",
        audio_path=str(audio_path),
        audio_exists=audio_path.exists(),
        audio_size=audio_path.stat().st_size if audio_path.exists() else 0,
    )
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        raise RuntimeError("O TTS gerou um arquivo de audio vazio.")
    return audio_path


def _channel_id_from_token(token: str) -> int | None:
    if token.startswith("<#") and token.endswith(">"):
        token = token[2:-1]
    if token.isdigit():
        return int(token)
    return None


def _log(event: str, **fields: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"[voice_tts] event={event} {details}".rstrip(), flush=True)


def _format_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "tempo limite ao conectar no canal de voz."
    message = str(error).strip()
    return message or error.__class__.__name__


def _enable_discord_voice_logging() -> None:
    logger = logging.getLogger("discord.voice_state")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if any(getattr(handler, "_voice_tts_handler", False) for handler in logger.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[discord.voice_state] %(levelname)s %(message)s"))
    handler._voice_tts_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceTTS(bot))
