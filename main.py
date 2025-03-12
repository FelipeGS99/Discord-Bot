import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='?', intents=intents)

# Carregar os Cogs (módulos)
async def load_cogs():
    for cog in ["moderation", "music", "gpt"]:
        await bot.load_extension(f"cogs.{cog}")

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    await load_cogs()  # Carregar os módulos

bot.run(os.getenv('DISCORD_TOKEN'))