import discord
from discord.ext import commands
import openai
import os

openai.api_key = os.getenv('OPENAI_API_KEY')

def enviar_mensagem(mensagem, lista_mensagens=[]):
    """Função para interagir com o ChatGPT"""
    try:
        lista_mensagens.append({"role": "user", "content": mensagem})
        resposta = openai.chat.completions.create(model='gpt-4o', messages=lista_mensagens)
        return resposta.choices[0].message.content
    except Exception as e:
        return f"Erro ao processar a mensagem: {e}"

class ChatGPT(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lista_mensagens = []

    @commands.command()
    async def gpt(self, ctx, *, arg):
        """Envia uma mensagem para o ChatGPT e retorna a resposta."""
        resposta_chatgpt = enviar_mensagem(arg, self.lista_mensagens)
        self.lista_mensagens.append({"role": "assistant", "content": resposta_chatgpt})
        await ctx.send(f'{ctx.author.mention} {resposta_chatgpt}')

async def setup(bot):
    await bot.add_cog(ChatGPT(bot))