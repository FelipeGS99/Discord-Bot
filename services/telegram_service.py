from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TELEGRAM_BASE_URL = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class TelegramMessage:
    update_id: int
    chat_id: int
    text: str


class TelegramClient:
    def __init__(self, bot_token: str, base_url: str = TELEGRAM_BASE_URL) -> None:
        self.bot_token = bot_token
        self.base_url = base_url.rstrip("/")

    async def fetch_updates(self, offset: int | None) -> list[TelegramMessage]:
        return await asyncio.to_thread(self._fetch_updates, offset)

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:
        await asyncio.to_thread(self._send_message, chat_id, text, parse_mode)

    def _fetch_updates(self, offset: int | None) -> list[TelegramMessage]:
        params: dict[str, Any] = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset

        payload = self._post_json("getUpdates", params)
        if not payload.get("ok"):
            return []

        messages: list[TelegramMessage] = []
        for update in payload.get("result", []):
            if not isinstance(update, dict):
                continue
            update_id = _optional_int(update.get("update_id"))
            message = update.get("message")
            if update_id is None or not isinstance(message, dict):
                continue
            chat = message.get("chat")
            if not isinstance(chat, dict):
                continue
            chat_id = _optional_int(chat.get("id"))
            text = str(message.get("text") or "").strip()
            if chat_id is None or not text:
                continue
            messages.append(TelegramMessage(update_id=update_id, chat_id=chat_id, text=text))
        return messages

    def _send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> None:
        params = {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }
        if parse_mode is not None:
            params["parse_mode"] = parse_mode

        self._post_json(
            "sendMessage",
            params,
        )

    def _post_json(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        data = urlencode(params).encode("utf-8")
        request = Request(
            f"{self.base_url}/bot{self.bot_token}/{method}",
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}


class TelegramStateRepository:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return _default_state()

        with self.state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        state = _default_state()
        state["update_offset"] = data.get("update_offset") if isinstance(data.get("update_offset"), int) else None

        subscriptions = data.get("subscriptions")
        if isinstance(subscriptions, dict):
            for key in state["subscriptions"]:
                chat_ids = subscriptions.get(key)
                if isinstance(chat_ids, list):
                    state["subscriptions"][key] = [chat_id for chat_id in chat_ids if isinstance(chat_id, int)]

        football = data.get("football")
        if isinstance(football, dict):
            checked_dates = football.get("checked_dates")
            snapshots = football.get("fixture_snapshots")
            fixtures = football.get("fixtures_today")
            if isinstance(checked_dates, dict):
                state["football"]["checked_dates"] = checked_dates
            if isinstance(snapshots, dict):
                state["football"]["fixture_snapshots"] = snapshots
            if isinstance(fixtures, dict):
                state["football"]["fixtures_today"] = fixtures

        esports = data.get("esports")
        if isinstance(esports, dict):
            for key, game_state in state["esports"].items():
                raw_game_state = esports.get(key)
                if not isinstance(raw_game_state, dict):
                    continue
                for field in ("match_snapshots", "game_snapshots"):
                    value = raw_game_state.get(field)
                    if isinstance(value, dict):
                        game_state[field] = value
                tracked_matches = raw_game_state.get("tracked_matches")
                if isinstance(tracked_matches, list):
                    game_state["tracked_matches"] = tracked_matches

        return state

    def save(self, state: dict[str, Any]) -> None:
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)


def _default_state() -> dict[str, Any]:
    return {
        "update_offset": None,
        "subscriptions": {
            "futebol": [],
            "lol": [],
            "valorant": [],
            "cs2": [],
        },
        "football": {
            "checked_dates": {},
            "fixture_snapshots": {},
            "fixtures_today": {},
        },
        "esports": {
            "lol": _default_esports_game_state(),
            "valorant": _default_esports_game_state(),
            "cs2": _default_esports_game_state(),
        },
    }


def _default_esports_game_state() -> dict[str, Any]:
    return {
        "match_snapshots": {},
        "game_snapshots": {},
        "tracked_matches": [],
    }


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
