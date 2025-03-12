import discord
from discord.ext import commands
import openai
from dotenv import load_dotenv
import os
import yt_dlp
import asyncio
from collections import deque

load_dotenv()

openai.api_key = os.getenv('OPENAI_API_KEY')
discord_token = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.all()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='?', intents=intents)
lista_mensagens = []
queue = deque()
bot.skip_triggered = False  # Transformando skip_triggered em atributo do bot

def enviar_mensagem(mensagem, lista_mensagens=[]):
    try:
        lista_mensagens.append({"role": "user", "content": mensagem})
        resposta = openai.chat.completions.create(model='gpt-4o', messages=lista_mensagens)
        return resposta.choices[0].message.content
    except Exception as e:
        return f"Erro ao processar a mensagem: {e}"

@bot.command()
async def marcar(ctx, membro: discord.Member, quant:int):
    if quant > 50:
        await ctx.send(f'{membro.mention} Quem marca mais de 50 vezes é Corno')
        return
    for _ in range(quant):
        await ctx.send(f'{membro.mention}, bora uminha!!!!!')

@bot.command()
async def mover(ctx, membro: discord.Member, canal_destino: discord.VoiceChannel, quantidade: int):
    try:
        if not membro:
            await ctx.send(f"Usuário '{membro}' não encontrado no servidor, marque o usuário corretamente.")
            return
        if not canal_destino:
            await ctx.send(f"Canal de voz '{canal_destino}' não encontrado no servidor, marque o canal corretamente.")
            return
        if quantidade <= 0:
            await ctx.send("A quantidade deve ser um número positivo.")
            return
    
        if ctx.author.voice:
            canal_origem = ctx.author.voice.channel
            if membro.voice:
                canal_origem_membro = membro.voice.channel
                if ctx.author.guild_permissions.move_members:
                    for _ in range(quantidade):
                        await membro.move_to(canal_destino)
                        await membro.move_to(canal_origem)
                    await ctx.send(f'{membro.mention} foi movido entre {canal_origem} e {canal_destino} {quantidade} vezes.')
                else:
                    await ctx.send('Você não tem permissão para mover membros.')
            else:
                await ctx.send(f'{membro.mention} não está em um canal de voz.')
        else:
            await ctx.send('Você não está em um canal de voz.')
    except discord.ext.commands.errors.MemberNotFound:
        await ctx.send("Membro não encontrado. Verifique a menção e tente novamente.")
    except discord.ext.commands.errors.ChannelNotFound:
        await ctx.send("Canal de voz não encontrado. Verifique o nome e tente novamente.")
    except discord.ext.commands.errors.BadArgument:
        await ctx.send("A quantidade deve ser um número inteiro positivo.")
    except Exception as e:
        await ctx.send(f"Ocorreu um erro: {e}")

@bot.command()
async def gpt(ctx, *, arg):
    resposta_chatgpt = enviar_mensagem(arg, lista_mensagens)
    lista_mensagens.append({"role": "assistant", "content": resposta_chatgpt})
    await ctx.send(f'{ctx.author.mention} {resposta_chatgpt}')

@bot.command()
async def play(ctx, url: str):
    """Toca uma música do YouTube diretamente no canal de voz"""
    ydl_opts = {
        'format': 'bestaudio/best',
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
        await play_next(vc, ctx)

async def play_next(vc, ctx):
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
                asyncio.run_coroutine_threadsafe(after_play(vc, ctx), bot.loop)

            vc.play(discord.FFmpegPCMAudio(url, before_options=ffmpeg_options), after=after_callback)
            await ctx.channel.send(f"🎶 Agora tocando: **{title}**")
        else:
            await ctx.send("❌ O bot foi desconectado do canal de voz.")
    else:
        if vc and vc.is_connected():
            await asyncio.sleep(10)  # Espera antes de sair, para caso novas músicas sejam adicionadas
            if not vc.is_playing():
                await vc.disconnect()

async def after_play(vc, ctx):
    """Função chamada após a música terminar."""
    if queue:
        await play_next(vc, ctx)
    else:
        print("Fila vazia. A música terminou, aguardando antes de desconectar.")
        await asyncio.sleep(10)
        if vc and vc.is_connected() and not vc.is_playing() and not queue:
            await vc.disconnect()
            print("Bot desconectado por inatividade.")

@bot.command()
async def queue_list(ctx):
    """Mostra a fila de músicas"""
    if queue:
        fila = '\n'.join([f"{idx+1}. {title}" for idx, (_, title) in enumerate(queue)])
        await ctx.send(f"📜 **Fila de músicas:**\n{fila}")
    else:
        await ctx.send("📭 A fila está vazia.")

@bot.command()
async def skip(ctx):
    """Pula para a próxima música."""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()  # Para a música atual, acionando `after_play`
        await ctx.send("⏭️ Música pulada!")
    else:
        await ctx.send("⚠️ Não há música tocando no momento!")

@bot.command()
async def stop(ctx):
    """Para a música, limpa a fila e desconecta o bot do canal de voz."""
    if ctx.voice_client:
        queue.clear()
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("🛑 O bot parou a música, limpou a fila e saiu do canal de voz.")
    else:
        await ctx.send("❌ O bot não está em um canal de voz.")

@bot.command()
async def pause(ctx):
    """Pausa a música atual."""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Música pausada.")
    else:
        await ctx.send("⚠️ Nenhuma música está tocando.")

@bot.command()
async def resume(ctx):
    """Retoma a música pausada."""    
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Música retomada.")
    else:
        await ctx.send("⚠️ Nenhuma música está pausada.")

@bot.command()
async def leave(ctx):
    """Faz o bot sair do canal de voz"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Saindo do canal de voz!")
    else:
        await ctx.send("❌ Eu não estou em nenhum canal de voz!")

@bot.command()
@commands.has_permissions(manage_messages = True)  # Garante que apenas usuários com permissão possam usar
async def clear(ctx, amount: int):
    """Apaga um número específico de mensagens no chat."""
    if amount < 1:
        await ctx.send("❌ O número de mensagens a apagar deve ser pelo menos 1.")
        return
    
    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 para incluir o próprio comando
    await ctx.send(f"🗑️ {len(deleted) - 1} mensagens foram apagadas!", delete_after=3)

bot.run(discord_token)