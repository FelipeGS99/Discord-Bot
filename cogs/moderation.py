from __future__ import annotations

import asyncio

import discord
from discord.ext import commands


class Moderation(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @staticmethod
    def _can_manage_messages(ctx: commands.Context) -> bool:
        permissions = ctx.author.guild_permissions
        return (
            ctx.guild is not None
            and (
                ctx.author.id == ctx.guild.owner_id
                or permissions.administrator
                or permissions.manage_messages
            )
        )

    @staticmethod
    def _can_move_members(ctx: commands.Context) -> bool:
        permissions = ctx.author.guild_permissions
        return (
            ctx.guild is not None
            and (
                ctx.author.id == ctx.guild.owner_id
                or permissions.administrator
                or permissions.move_members
            )
        )

    @commands.command(name="help", aliases=["commands"])
    async def commands_list(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        message = "\n".join(
            [
                "**Ajuda do bot**",
                "Use estes comandos para abrir a ajuda detalhada de cada area:",
                f"`{prefix}help` - Mostra esta ajuda geral.",
                f"`{prefix}futebol` - Ver jogos de futebol do dia e de amanha.",
                f"`{prefix}brasileirao` - Jogos, rodadas e alertas do Brasileirao Serie A.",
                f"`{prefix}libertadores` - Jogos e alertas da Libertadores.",
                f"`{prefix}sulamericana` - Jogos e alertas da Sul-Americana.",
                f"`{prefix}lol` - Partidas e alertas de League of Legends.",
                f"`{prefix}cs2` - Partidas e alertas de CS2.",
                f"`{prefix}genoticias` - Noticias de futebol do GE.",
                f"`{prefix}forca` - Jogo da forca no canal.",
                "",
                "**Moderacao**",
                f"`{prefix}clear <quantidade>` - Apaga mensagens recentes do canal. Exemplo: `{prefix}clear 10`.",
                f"`{prefix}mover <membro> <canal_de_voz> <vezes>` - Move alguem entre canais de voz. Exemplo: `{prefix}mover @Usuario Geral 3`.",
                "",
                "**Dica**",
                "Use `#canal` quando um comando pedir canal de texto, por exemplo `#placares`.",
            ]
        )
        await ctx.send(message)

    @commands.command()
    async def clear(self, ctx: commands.Context, amount: int) -> None:
        if not self._can_manage_messages(ctx):
            await ctx.send("Voce nao tem permissao para usar este comando.")
            return

        if amount < 1:
            await ctx.send("O numero de mensagens deve ser pelo menos 1.")
            return

        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"{len(deleted) - 1} mensagens apagadas.", delete_after=3)

    @commands.command()
    async def mover(
        self,
        ctx: commands.Context,
        membro: discord.Member,
        canal_destino: discord.VoiceChannel,
        quantidade: int,
    ) -> None:
        if not self._can_move_members(ctx):
            await ctx.send("Voce nao tem permissao para usar este comando.")
            return

        if not membro.voice or not membro.voice.channel:
            await ctx.send(f"{membro.mention} nao esta em um canal de voz.")
            return

        if quantidade <= 0:
            await ctx.send("A quantidade deve ser um numero positivo.")
            return

        canal_origem = membro.voice.channel

        try:
            for _ in range(quantidade):
                await membro.move_to(canal_destino)
                await asyncio.sleep(1)
                await membro.move_to(canal_origem)
        except discord.Forbidden:
            await ctx.send("O bot nao tem permissao para mover membros.")
            return
        except Exception as exc:
            await ctx.send(f"Ocorreu um erro ao mover o membro: {exc}")
            return

        await ctx.send(
            f"{membro.mention} foi movido entre {canal_origem} e {canal_destino} {quantidade} vezes."
        )

    @clear.error
    @mover.error
    async def moderation_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.BadArgument):
            await ctx.send("Argumento invalido. Verifique se marcou o usuario e o canal corretamente.")
            return
        raise error


async def setup(bot) -> None:
    await bot.add_cog(Moderation(bot))
