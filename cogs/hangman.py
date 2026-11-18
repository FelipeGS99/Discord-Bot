from __future__ import annotations

from pathlib import Path

import discord
from discord.ext import commands

from services.hangman_service import HangmanGame, WordRepository, normalize_difficulty


from services.discord_messages import response_sender

reply = response_sender("Jogo da Forca")


class Hangman(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        data_path = Path(__file__).resolve().parent.parent / "words.json"
        self.word_repository = WordRepository(data_path)
        self.active_games: dict[int, HangmanGame] = {}

    @commands.group(name="forca", invoke_without_command=True)
    async def hangman_group(self, ctx: commands.Context) -> None:
        prefix = ctx.prefix or "?"
        await reply(
            ctx,
            "\n".join(
                [
                    "**Jogo da Forca**",
                    "Jogue uma partida de forca com os membros do canal. Cada canal pode ter uma partida ativa.",
                    f"`{prefix}forca iniciar <facil|medio|dificil>` - Começa uma partida. Exemplo: `{prefix}forca iniciar medio`.",
                    f"`{prefix}forca letra <letra>` - Tenta uma letra. Exemplo: `{prefix}forca letra a`.",
                    f"`{prefix}forca palavra <palpite>` - Envia um palpite para a palavra completa. Exemplo: `{prefix}forca palavra futebol`.",
                    f"`{prefix}forca status` — Consulta palavra parcial, erros e tentativas já feitas.",
                    f"`{prefix}forca parar` - Encerra a partida atual e mostra a resposta.",
                    "Durante a partida, também é possível enviar uma letra ou palavra diretamente neste canal.",
                ]
            ),
        )

    @hangman_group.command(name="iniciar")
    async def start_game(self, ctx: commands.Context, dificuldade: str) -> None:
        channel_id = ctx.channel.id
        if channel_id in self.active_games:
            await reply(
                ctx,
                "Já existe uma partida em andamento neste canal. Use `forca parar` para encerrar.",
                tone="warning",
            )
            return

        try:
            normalized_difficulty = normalize_difficulty(dificuldade)
        except ValueError:
            await reply(
                ctx,
                "Escolha uma dificuldade válida: `facil`, `medio` ou `dificil`.",
                tone="warning",
            )
            return

        selected_word = self.word_repository.draw_word(normalized_difficulty)
        game = HangmanGame(
            word=selected_word.word,
            theme=selected_word.theme,
            difficulty=selected_word.difficulty,
        )
        self.active_games[channel_id] = game

        await reply(ctx, self._format_game_message(game, title="Partida iniciada"))

    @hangman_group.command(name="letra")
    async def guess_letter(self, ctx: commands.Context, letra: str) -> None:
        if ctx.channel.id not in self.active_games:
            await reply(
                ctx,
                "Não ha partida ativa neste canal. Use `forca iniciar <dificuldade>`.",
                tone="warning",
            )
            return

        await self._handle_letter_guess(ctx.channel, ctx.channel.id, letra)

    @hangman_group.command(name="palavra")
    async def guess_full_word(self, ctx: commands.Context, *, palpite: str) -> None:
        if ctx.channel.id not in self.active_games:
            await reply(
                ctx,
                "Não ha partida ativa neste canal. Use `forca iniciar <dificuldade>`.",
                tone="warning",
            )
            return

        await self._handle_word_guess(ctx.channel, ctx.channel.id, palpite)

    @hangman_group.command(name="status")
    async def game_status(self, ctx: commands.Context) -> None:
        game = self.active_games.get(ctx.channel.id)
        if game is None:
            await reply(ctx, "Não ha partida ativa neste canal.", tone="warning")
            return

        await reply(ctx, self._format_game_message(game, title="Status da partida"))

    @hangman_group.command(name="parar")
    async def stop_game(self, ctx: commands.Context) -> None:
        game = self.active_games.pop(ctx.channel.id, None)
        if game is None:
            await reply(ctx, "Não ha partida ativa neste canal.", tone="warning")
            return

        await reply(ctx, f"Partida encerrada. A palavra era `{game.word}`.")

    @start_game.error
    @guess_letter.error
    @guess_full_word.error
    async def hangman_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await reply(
                ctx,
                "Faltou um argumento no comando. Use `forca` para ver como jogar.",
                tone="warning",
            )
            return
        raise error

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        channel_id = message.channel.id
        if channel_id not in self.active_games:
            return

        content = message.content.strip()
        if not content:
            return

        prefixes = self.bot.command_prefix
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        elif isinstance(prefixes, list):
            prefixes = tuple(prefixes)
        else:
            prefixes = tuple(prefix for prefix in prefixes if isinstance(prefix, str))

        if any(content.startswith(prefix) for prefix in prefixes):
            return

        if len(content) == 1 and content.isalpha():
            await self._handle_letter_guess(message.channel, channel_id, content)
            return

        if content.isalpha():
            await self._handle_word_guess(message.channel, channel_id, content)

    async def _handle_letter_guess(
        self,
        channel: discord.abc.Messageable,
        channel_id: int,
        letter: str,
    ) -> None:
        game = self.active_games[channel_id]
        result = game.guess(letter)
        if result == "invalid":
            await reply(channel, "Envie apenas uma letra por vez.")
            return
        if result == "repeated":
            await reply(
                channel, "Essa letra já foi tentada. Escolha outra.", tone="warning"
            )
            return

        if game.is_won:
            await self._finish_game(channel, channel_id, game, "Vitória na partida")
            return

        if game.is_lost:
            await self._finish_game(channel, channel_id, game, "Tentativas esgotadas")
            return

        feedback = "Letra correta" if result == "correct" else "Letra incorreta."
        await reply(channel, self._format_game_message(game, title=feedback))

    async def _handle_word_guess(
        self,
        channel: discord.abc.Messageable,
        channel_id: int,
        guessed_word: str,
    ) -> None:
        game = self.active_games[channel_id]
        result = game.guess_word(guessed_word)
        if result == "invalid":
            await reply(channel, "Envie uma palavra válida para o palpite.")
            return
        if result == "repeated":
            await reply(
                channel,
                "Essa palavra já foi tentada. Escolha outro palpite.",
                tone="warning",
            )
            return

        if game.is_won:
            await self._finish_game(channel, channel_id, game, "Vitória na partida")
            return

        if game.is_lost:
            await self._finish_game(channel, channel_id, game, "Tentativas esgotadas")
            return

        await reply(
            channel,
            self._format_game_message(
                game,
                title="Palpite incorreto.",
                extra_line="Nenhuma letra foi revelada.",
            ),
        )

    async def _finish_game(
        self,
        channel: discord.abc.Messageable,
        channel_id: int,
        game: HangmanGame,
        title: str,
    ) -> None:
        await reply(
            channel,
            self._format_game_message(
                game,
                title=title,
                extra_line=f"A palavra era `{game.word}`.",
            ),
        )
        self.active_games.pop(channel_id, None)

    @staticmethod
    def _format_game_message(
        game: HangmanGame, title: str, extra_line: str | None = None
    ) -> str:
        wrong_letters = (
            ", ".join(sorted(game.wrong_letters)) if game.wrong_letters else "nenhuma"
        )
        wrong_words = (
            ", ".join(sorted(game.wrong_words)) if game.wrong_words else "nenhum"
        )
        lines = [
            f"**{title}**",
            f"Tema: **{game.theme}**",
            f"Dificuldade: **{ {'facil': 'Fácil', 'medio': 'Médio', 'dificil': 'Difícil'}.get(game.difficulty, game.difficulty) }**",
            f"Palavra: `{game.masked_word}`",
            f"Letras erradas: `{wrong_letters}`",
            f"Palavras erradas: `{wrong_words}`",
            f"Erros restantes: **{game.errors_left}**/5",
        ]
        if extra_line:
            lines.append(extra_line)
        return "\n".join(lines)


async def setup(bot) -> None:
    await bot.add_cog(Hangman(bot))
