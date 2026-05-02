from __future__ import annotations

import unittest
from pathlib import Path

from bot import COGS
from cogs.telegram_alerts import _normalize_command
from services.telegram_service import TelegramStateRepository


class TelegramServiceTests(unittest.TestCase):
    def test_telegram_cog_is_loaded(self) -> None:
        self.assertIn("cogs.telegram_alerts", COGS)

    def test_normalize_command_keeps_arguments_after_bot_mention(self) -> None:
        self.assertEqual(_normalize_command("/parar@MeuBot lol"), "parar lol")

    def test_state_repository_defaults_and_save(self) -> None:
        state_path = Path(__file__).resolve().parent / "_tmp_telegram_state.json"
        if state_path.exists():
            state_path.unlink()

        try:
            repository = TelegramStateRepository(state_path)
            state = repository.load()

            self.assertEqual(state["subscriptions"]["futebol"], [])
            self.assertEqual(state["subscriptions"]["lol"], [])
            self.assertIsNone(state["update_offset"])

            state["update_offset"] = 10
            state["subscriptions"]["lol"] = [123, 456]
            state["football"]["checked_dates"]["Brasileirao"] = "2026-05-02"
            state["esports"]["lol"]["match_snapshots"]["1"] = "running|0|0|None"
            repository.save(state)

            loaded_state = repository.load()

            self.assertEqual(loaded_state["update_offset"], 10)
            self.assertEqual(loaded_state["subscriptions"]["lol"], [123, 456])
            self.assertEqual(loaded_state["football"]["checked_dates"]["Brasileirao"], "2026-05-02")
            self.assertEqual(loaded_state["esports"]["lol"]["match_snapshots"]["1"], "running|0|0|None")
        finally:
            if state_path.exists():
                state_path.unlink()


if __name__ == "__main__":
    unittest.main()
