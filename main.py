import discord
from discord.ext import commands
import openai
from dotenv import load_dotenv
import os

load_dotenv()

openai.api_key = os.getenv('openai_key')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='?', intents=intents)
lista_mensagens = []

def enviar_mensagem(mensagem, lista_mensagens=[]):
    lista_mensagens.append({"role": "user", "content": mensagem})
    resposta = openai.chat.completions.create(model='gpt-4o', messages=lista_mensagens)
    return resposta.choices[0].message.content

@bot.command()
async def gpt(ctx, *, arg):
    if ctx.channel.id == 1298410787240673320:
        resposta_chatgpt = enviar_mensagem(arg, lista_mensagens)
        lista_mensagens.append({"role": "assistant", "content": resposta_chatgpt})
        await ctx.send(f'{ctx.author.mention} {resposta_chatgpt}')

@bot.command()
async def marcar(ctx, membro: discord.Member, quant:int):
    if quant > 50:
        await ctx.send(f'{membro.mention} Quem marca mais de 50 vezes é Corno')
        return
    for _ in range(quant):
        await ctx.send(f'{membro.mention}, bora uminha!!!!!')

bot.run(os.getenv('discord_key'))