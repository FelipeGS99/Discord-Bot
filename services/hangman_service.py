from __future__ import annotations

import json
import random
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


MAX_ERRORS = 5
VALID_DIFFICULTIES = {
    "facil": "facil",
    "medio": "medio",
    "dificil": "dificil",
}


@dataclass(frozen=True)
class WordEntry:
    theme: str
    difficulty: str
    word: str


@dataclass
class HangmanGame:
    word: str
    theme: str
    difficulty: str
    guessed_letters: set[str] = field(default_factory=set)
    wrong_letters: set[str] = field(default_factory=set)
    wrong_words: set[str] = field(default_factory=set)
    max_errors: int = MAX_ERRORS

    def guess(self, letter: str) -> str:
        normalized_letter = letter.strip().lower()
        if len(normalized_letter) != 1 or not normalized_letter.isalpha():
            return "invalid"

        if normalized_letter in self.guessed_letters or normalized_letter in self.wrong_letters:
            return "repeated"

        if normalized_letter in self.word:
            self.guessed_letters.add(normalized_letter)
            return "correct"

        self.wrong_letters.add(normalized_letter)
        return "wrong"

    def guess_word(self, guessed_word: str) -> str:
        normalized_word = guessed_word.strip().lower()
        if len(normalized_word) < 2 or not normalized_word.isalpha():
            return "invalid"

        if normalized_word == self.word:
            self.guessed_letters.update({letter for letter in self.word if letter.isalpha()})
            return "correct"

        if normalized_word in self.wrong_words:
            return "repeated"

        self.wrong_words.add(normalized_word)
        return "wrong"

    @property
    def errors_left(self) -> int:
        return self.max_errors - self.total_errors

    @property
    def total_errors(self) -> int:
        return len(self.wrong_letters) + len(self.wrong_words)

    @property
    def masked_word(self) -> str:
        return " ".join(
            letter if letter in self.guessed_letters else "_"
            for letter in self.word
        )

    @property
    def is_won(self) -> bool:
        unique_letters = {letter for letter in self.word if letter.isalpha()}
        return unique_letters.issubset(self.guessed_letters)

    @property
    def is_lost(self) -> bool:
        return self.total_errors >= self.max_errors


class WordRepository:
    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self._words_by_difficulty = self._load_words()
        self._used_words: set[tuple[str, str]] = set()

    def _load_words(self) -> dict[str, list[WordEntry]]:
        with self.data_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        words_by_difficulty = {"facil": [], "medio": [], "dificil": []}

        for theme_data in data.get("temas", []):
            theme = str(theme_data["tema"]).strip()
            for difficulty in words_by_difficulty:
                for word in theme_data.get(difficulty, []):
                    clean_word = str(word).strip().lower()
                    if clean_word:
                        words_by_difficulty[difficulty].append(
                            WordEntry(theme=theme, difficulty=difficulty, word=clean_word)
                        )

        return words_by_difficulty

    def draw_word(self, difficulty: str) -> WordEntry:
        normalized_difficulty = normalize_difficulty(difficulty)
        available_words = self._words_by_difficulty.get(normalized_difficulty, [])
        if not available_words:
            raise RuntimeError(f"Nenhuma palavra cadastrada para a dificuldade {normalized_difficulty}.")

        unused_words = [
            entry
            for entry in available_words
            if (entry.difficulty, entry.word) not in self._used_words
        ]

        if not unused_words:
            self._used_words = {
                used_entry
                for used_entry in self._used_words
                if used_entry[0] != normalized_difficulty
            }
            unused_words = list(available_words)

        selected_entry = random.choice(unused_words)
        self._used_words.add((selected_entry.difficulty, selected_entry.word))
        return selected_entry


def normalize_difficulty(difficulty: str) -> str:
    sanitized = "".join(
        character
        for character in unicodedata.normalize("NFD", difficulty.strip().lower())
        if unicodedata.category(character) != "Mn"
    )
    normalized = VALID_DIFFICULTIES.get(sanitized)
    if normalized is None:
        raise ValueError("Dificuldade invalida.")
    return normalized
