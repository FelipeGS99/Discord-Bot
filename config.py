from __future__ import annotations

import os
from dataclasses import dataclass

from pathlib import Path

from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


@dataclass(frozen=True)
class Settings:
    discord_token: str
    command_prefix: str
    bsd_api_key: str | None
    pandascore_api_token: str | None
    brasileirao_league_id: int
    libertadores_league_id: int
    sulamericana_league_id: int
    copadobrasil_league_id: int


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"A variavel de ambiente {name} nao foi definida.")
    return value


settings = Settings(
    discord_token=_get_required_env("DISCORD_TOKEN"),
    command_prefix=os.getenv("BOT_PREFIX", "?"),
    bsd_api_key=os.getenv("BSD_API_KEY") or os.getenv("API_FOOTBALL_KEY"),
    pandascore_api_token=os.getenv("PANDASCORE_API_TOKEN"),
    brasileirao_league_id=int(os.getenv("BRASILEIRAO_LEAGUE_ID", "9")),
    libertadores_league_id=int(os.getenv("LIBERTADORES_LEAGUE_ID", "32")),
    sulamericana_league_id=int(os.getenv("SULAMERICANA_LEAGUE_ID", "33")),
    copadobrasil_league_id=int(os.getenv("COPADOBRASIL_LEAGUE_ID", "35")),
)
