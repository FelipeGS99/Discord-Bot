from __future__ import annotations

import hashlib

from services.brasileirao_service import BrasileiraoFixture


FOOTBALL_FIXTURE_PALETTE = (
    0x2F80ED,
    0x27AE60,
    0xF2994A,
    0xEB5757,
    0x9B51E0,
    0x00B8A9,
    0xF2C94C,
    0x56CCF2,
    0xBB6BD9,
    0x219653,
)


def color_for_fixture(fixture: BrasileiraoFixture) -> int:
    seed = f"{fixture.fixture_id}:{fixture.home_team}:{fixture.away_team}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return FOOTBALL_FIXTURE_PALETTE[int.from_bytes(digest[:2], "big") % len(FOOTBALL_FIXTURE_PALETTE)]
