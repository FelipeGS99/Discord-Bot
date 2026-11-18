from __future__ import annotations

import logging

import asyncio

import discord
from discord.ext import commands


from services.discord_messages import response_sender

reply = response_sender("Moderação")


class Moderation(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @staticmethod
    def _can_manage_messages(ctx: commands.Context) -> bool:
        permissions = ctx.author.guild_permissions
        return ctx.guild is not None and (
            ctx.author.id == ctx.guild.owner_id
            or permissions.administrator
            or permissions.manage_messages
        )

    @staticmethod
    def _can_move_members(ctx: commands.Context) -> bool:
        permissions = ctx.author.guild_permissions
        return ctx.guild is not None and (
            ctx.author.id == ctx.guild.owner_id
            or permissions.administrator
            or permissions.move_members
        )

    @commands.command(name="help", aliases=["commands"])
    async def commands_list(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await reply(
            ctx,
            "Consulte as funcionalidades abaixo. Cada comando principal abre a ajuda da respectiva área.",
            title="Central de ajuda",
            fields=(
                (
                    "Futebol",
                    f"`{prefix}futebol` — Jogos e canais privados por partida.\n`{prefix}brasileirao` · `{prefix}libertadores` · `{prefix}sulamericana` · `{prefix}copadobrasil`\n`{prefix}futebol ativar <liga>` · `{prefix}futebol prazo 60`",
                ),
                (
                    "E-sports e jogadores",
                    f"`{prefix}lol` · `{prefix}cs2` · `{prefix}valorant` — Calendário, placares e alertas.\n`{prefix}loltrack` — Acompanhamento de jogadores, builds e relatórios.",
                ),
                (
                    "Lives e notícias",
                    f"`{prefix}prolives` — Transmissões profissionais e cobertura por plataforma.\n`{prefix}genoticias` — Notícias de futebol do GE.",
                ),
                (
                    "Voz e assistente",
                    f"`{prefix}falar <mensagem>` — Reproduz texto no seu canal de voz.\n`{prefix}falar <#canal_de_voz> <mensagem>` — Escolhe outro canal de voz.\nMencione o bot com sua pergunta para conversar com a IA.",
                ),
                (
                    "Jogos e moderação",
                    f"`{prefix}forca` — Partida de forca no canal.\n`{prefix}clear <quantidade>` — Limpeza de mensagens.\n`{prefix}mover <membro> <canal_de_voz> <vezes>` — Movimentação entre canais de voz.\nOs comandos administrativos exigem as permissões correspondentes.",
                ),
            ),
        )

    @commands.command()
    async def clear(self, ctx: commands.Context, amount: int) -> None:
        if not self._can_manage_messages(ctx):
            await reply(
                ctx, "Você não tem permissão para usar este comando.", tone="warning"
            )
            return

        if amount < 1:
            await reply(ctx, "O número de mensagens deve ser pelo menos 1.")
            return

        deleted = await ctx.channel.purge(limit=amount + 1)
        await reply(
            ctx,
            f"{len(deleted) - 1} mensagens apagadas.",
            delete_after=3,
            title="Limpeza concluída",
            tone="success",
        )

    @commands.command()
    async def mover(
        self,
        ctx: commands.Context,
        membro: discord.Member,
        canal_destino: discord.VoiceChannel,
        quantidade: int,
    ) -> None:
        if not self._can_move_members(ctx):
            await reply(
                ctx, "Você não tem permissão para usar este comando.", tone="warning"
            )
            return

        if not membro.voice or not membro.voice.channel:
            await reply(ctx, f"{membro.mention} não está em um canal de voz.")
            return

        if quantidade <= 0:
            await reply(ctx, "A quantidade deve ser um número positivo.")
            return

        canal_origem = membro.voice.channel

        try:
            for _ in range(quantidade):
                await membro.move_to(canal_destino)
                await asyncio.sleep(1)
                await membro.move_to(canal_origem)
        except discord.Forbidden:
            await reply(
                ctx, "O bot não tem permissão para mover membros.", tone="warning"
            )
            return
        except Exception:
            logging.getLogger(__name__).exception("Falha ao executar comando")
            await reply(
                ctx,
                "Não foi possível concluir a movimentação. Verifique os canais e tente novamente.",
                tone="error",
            )
            return

        await reply(
            ctx,
            f"{membro.mention} foi movido entre {canal_origem} e {canal_destino} {quantidade} vezes.",
        )

    @clear.error
    @mover.error
    async def moderation_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.BadArgument):
            await reply(
                ctx,
                "Argumento inválido. Verifique se marcou o usuário e o canal corretamente.",
                tone="warning",
            )
            return
        raise error


async def setup(bot) -> None:
    await bot.add_cog(Moderation(bot))
