import discord
from discord.ext import commands
import asyncio

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int):
        """Apaga mensagens no chat."""
        if amount < 1:
            await ctx.send("❌ O número de mensagens deve ser pelo menos 1.")
            return
        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"🗑️ {len(deleted) - 1} mensagens apagadas!", delete_after=3)

    @commands.command()
    async def mover(self, ctx, membro: discord.Member, canal_destino: discord.VoiceChannel, quantidade: int):
        if not ctx.author.guild_permissions.move_members:
            await ctx.send("❌ Você não tem permissão para mover membros!")
            return
        else:
            """Move um usuário entre canais de voz várias vezes."""
            try:
                if not membro.voice:
                    await ctx.send(f"{membro.mention} não está em um canal de voz.")
                    return

                canal_origem = membro.voice.channel

                if quantidade <= 0:
                    await ctx.send("A quantidade deve ser um número positivo.")
                    return

                for _ in range(quantidade):
                    await membro.move_to(canal_destino)
                    await asyncio.sleep(1)  # Pequeno atraso para evitar spam no servidor
                    await membro.move_to(canal_origem)

                await ctx.send(f"✅ {membro.mention} foi movido entre {canal_origem} e {canal_destino} {quantidade} vezes.")

            except commands.MissingPermissions:
                await ctx.send("❌ Você não tem permissão para mover membros!")
            except discord.Forbidden:
                await ctx.send("❌ O bot não tem permissão para mover membros. Verifique as permissões no servidor!")
            except commands.BadArgument:
                await ctx.send("❌ Argumento inválido! Verifique se marcou o usuário e o canal corretamente.")
            except Exception as e:
                await ctx.send(f"❌ Ocorreu um erro: {e}")

# ✅ Corrige a função setup() para funcionar corretamente
async def setup(bot):
    await bot.add_cog(Moderation(bot))