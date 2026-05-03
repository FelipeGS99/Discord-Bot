from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from bot import COGS
from cogs.telegram_alerts import _format_esports_update, _format_football_update, _normalize_command
from services.brasileirao_service import BrasileiraoFixture
from services.pandascore_service import PandaScoreMatch
from services.telegram_service import TelegramClient, TelegramStateRepository


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

    def test_telegram_client_sends_optional_html_parse_mode(self) -> None:
        client = CapturingTelegramClient("token")

        client._send_message(123, "<b>Teste</b>", parse_mode="HTML")

        self.assertEqual(client.last_method, "sendMessage")
        self.assertEqual(client.last_params["chat_id"], 123)
        self.assertEqual(client.last_params["parse_mode"], "HTML")
        self.assertTrue(client.last_params["disable_web_page_preview"])

    def test_football_update_uses_html_layout_and_escapes_dynamic_text(self) -> None:
        fixture = BrasileiraoFixture(
            fixture_id=1,
            league_id=10,
            league_name="Brasileirão Série A",
            round_number=1,
            home_team="Palmeiras <SP>",
            away_team="Santos & Vila",
            home_goals=1,
            away_goals=1,
            status_short="finished",
            status_long="Encerrado",
            elapsed=90,
            kickoff_at=datetime(2026, 5, 2, 21, 30, tzinfo=timezone.utc),
        )

        message = _format_football_update("Brasileirão Série A", fixture, "Fim de jogo", ["Atacante & Meia"])

        self.assertIn("<b>Brasileirão Série A</b>", message)
        self.assertIn("<b>Fim de jogo</b>", message)
        self.assertIn("Palmeiras &lt;SP&gt; <b>1 x 1</b> Santos &amp; Vila", message)
        self.assertIn("<b>Status:</b> Encerrado - 90&#x27;", message)
        self.assertIn("<b>Data:</b> 02/05/2026 18:30", message)
        self.assertIn("<b>Gols:</b> Atacante &amp; Meia", message)

    def test_esports_update_uses_html_status_translation_and_clickable_stream(self) -> None:
        match = PandaScoreMatch(
            match_id=1,
            name="KRÜ Esports vs 100 Thieves",
            videogame="Valorant",
            league="Liga <Teste>",
            serie="Série & Especial",
            tournament="Grupo Omega",
            status="finished",
            opponents=("KRÜ Esports", "100 Thieves"),
            scores=(1, 2),
            winner_id=2,
            begin_at=datetime(2026, 5, 2, 21, 5, tzinfo=timezone.utc),
            scheduled_at=None,
            end_at=None,
            number_of_games=3,
            match_type="best_of",
            stream_url="https://example.com/live?team=KRÜ&round=<final>",
        )

        message = _format_esports_update("Valorant", match, "Fim de partida")

        self.assertIn("<b>Valorant - Liga &lt;Teste&gt; - Série &amp; Especial - Grupo Omega</b>", message)
        self.assertIn("<b>Fim de partida</b>", message)
        self.assertIn("KRÜ Esports <b>1 x 2</b> 100 Thieves", message)
        self.assertIn("<b>Status:</b> Encerrada", message)
        self.assertIn("<b>Horário:</b> 02/05/2026 18:05", message)
        self.assertIn("<b>Formato:</b> Melhor de 3", message)
        self.assertIn(">Assistir</a>", message)
        self.assertNotIn("Transmissão oficial: https://example.com/live", message)
        self.assertIn("round=&lt;final&gt;", message)


class CapturingTelegramClient(TelegramClient):
    def __init__(self, bot_token: str) -> None:
        super().__init__(bot_token)
        self.last_method: str | None = None
        self.last_params: dict[str, object] = {}

    def _post_json(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.last_method = method
        self.last_params = params
        return {"ok": True}


if __name__ == "__main__":
    unittest.main()
