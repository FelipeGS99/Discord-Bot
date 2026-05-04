from __future__ import annotations

import discord
from discord.errors import LoginFailure
from discord.ext import commands

from config import settings


COGS = (
    "cogs.moderation",
    "cogs.hangman",
    "cogs.ge_news",
    "cogs.brasileirao",
    "cogs.libertadores",
    "cogs.sulamericana",
    "cogs.copadobrasil",
    "cogs.futebol",
    "cogs.esports",
    "cogs.telegram_alerts",
    "cogs.voice_tts",
)


class DiscordBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        intents.voice_states = True

        super().__init__(command_prefix=settings.command_prefix, intents=intents, help_command=None)

    async def setup_hook(self) -> None:
        for cog in COGS:
            await self.load_extension(cog)

    async def on_ready(self) -> None:
        print(f"Bot conectado como {self.user}")

    async def start_bot(self) -> None:
        try:
            async with self:
                await self.start(settings.discord_token)
        except LoginFailure as exc:
            raise RuntimeError(
                "Nao foi possivel autenticar no Discord. Verifique se o DISCORD_TOKEN no arquivo .env "
                "existe, esta completo e pertence ao bot correto."
            ) from exc


def create_bot() -> DiscordBot:
    return DiscordBot()
