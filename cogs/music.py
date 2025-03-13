import discord
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
import os

queue = deque()

COOKIES_PATH = "cookies.txt"

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def play(self, ctx, url: str):
        """Toca uma música do YouTube diretamente no canal de voz"""
        ydl_opts = {
            'format': 'bestaudio/best',
            "cookiefile": COOKIES_PATH,  # Agora usando o arquivo .txt correto
            'quiet': True,
            'noplaylist': True
        }

        if not ctx.author.voice:
            await ctx.send("❌ Você precisa estar em um canal de voz para usar este comando!")
            return

        channel = ctx.author.voice.channel
        vc = ctx.voice_client

        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            # Permite trocar de canal apenas se estiver sozinho no outro
            if len(vc.channel.members) == 1:
                await vc.move_to(channel)
            else:
                await ctx.send("❌ Já estou em outro canal de voz com outras pessoas!")
                return

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            url2 = info.get('url', None)

        if url2 is None:
            await ctx.send("❌ Erro ao obter a URL de áudio do YouTube.")
            return

        queue.append((url2, info['title']))
        await ctx.send(f"🎵 Adicionado à fila: **{info['title']}**")

        if not vc.is_playing():
            await self.play_next(vc, ctx)

    async def play_next(self, vc, ctx):
        """Toca a próxima música na fila."""
        if queue:
            url, title = queue.popleft()
            ffmpeg_options = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -vn"
            print(f"Tocando próxima música: {title}")

            if vc and vc.is_connected():
                if vc.is_playing():
                    vc.stop()

                def after_callback(error):
                    if error:
                        print(f"Ocorreu um erro ao tocar a música: {error}")
                    asyncio.run_coroutine_threadsafe(self.after_play(vc, ctx), self.bot.loop)

                vc.play(discord.FFmpegPCMAudio(url, before_options=ffmpeg_options), after=after_callback)
                await ctx.channel.send(f"🎶 Agora tocando: **{title}**")
            else:
                await ctx.send("❌ O bot foi desconectado do canal de voz.")
        else:
            if vc and vc.is_connected():
                await asyncio.sleep(10)  # Espera antes de sair, para caso novas músicas sejam adicionadas
                if not vc.is_playing():
                    await vc.disconnect()

    async def after_play(self, vc, ctx):
        """Função chamada após a música terminar."""
        if queue:  # Só toca a próxima música se houver algo na fila
            await self.play_next(vc, ctx)
        else:
            if vc and vc.is_connected():
                await vc.disconnect()
                await ctx.send("❌ Fila de músicas vazia. Desconectando do canal de voz.")

    @commands.command()
    async def skip(self, ctx):
        """Pula a música atual e toca a próxima da fila"""
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.stop()  # Para a música atual; o after_play será acionado automaticamente para tocar a próxima
            await ctx.send("⏭️ Música pulada!")
        else:
            await ctx.send("❌ Não estou tocando nada.")

    @commands.command()
    async def queue_list(self, ctx):
        """Mostra a fila de músicas"""
        if queue:
            fila = '\n'.join([f"{idx+1}. {title}" for idx, (_, title) in enumerate(queue)])
            await ctx.send(f"📜 **Fila de músicas:**\n{fila}")
        else:
            await ctx.send("❌ Fila de músicas vazia.")

    @commands.command()
    async def stop(self, ctx):
        """Para a música atual e limpa a fila"""
        vc = ctx.voice_client

        if vc and vc.is_playing():
            vc.stop()
            queue.clear()
            await vc.disconnect()
            await ctx.send("⏹️ Música parada e fila limpa.")
        else:
            await ctx.send("❌ Não estou tocando nada.")
            return
    
    @commands.command()
    async def pause(self, ctx):
        """Pausa a música atual"""
        vc = ctx.voice_client

        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸️ Música pausada.")
        else:
            await ctx.send("❌ Não estou tocando nada.")
            return
    
    @commands.command()
    async def resume(self, ctx):
        """Retoma a música pausada"""
        vc = ctx.voice_client

        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶️ Música retomada.")
        else:
            await ctx.send("❌ Não estou tocando nada.")
            return
    
    @commands.command()
    async def leave(self, ctx):
        """Faz o bot sair do canal de voz"""
        vc = ctx.voice_client

        if vc:
            await vc.disconnect()
            await ctx.send("👋 Saindo do canal de voz!")
        else:
            await ctx.send("❌ Eu não estou em nenhum canal de voz!")
            return

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member == self.bot.user:
            if before.channel and not after.channel:
                if not [m for m in before.channel.members if not m.bot]:
                    await self.leave(member.guild.voice_client)
            elif after.channel and not before.channel:
                if not [m for m in after.channel.members if not m.bot]:
                    await self.leave(member.guild.voice_client)

async def setup(bot):
    await bot.add_cog(Music(bot))