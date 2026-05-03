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
    0xFF6B6B,
    0x4ECDC4,
    0x45B7D1,
    0x96CEB4,
    0xFFEAA7,
    0xD63031,
    0x6C5CE7,
    0x00CEC9,
)


def color_for_fixture(fixture: BrasileiraoFixture) -> int:
    seed = f"{fixture.fixture_id}:{fixture.home_team}:{fixture.away_team}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return FOOTBALL_FIXTURE_PALETTE[int.from_bytes(digest[:2], "big") % len(FOOTBALL_FIXTURE_PALETTE)]


def color_for_active_fixture(
    fixture: BrasileiraoFixture,
    active_fixtures: list[BrasileiraoFixture] | None,
) -> int:
    if not active_fixtures:
        return color_for_fixture(fixture)

    active_fixture_ids = [
        item.fixture_id
        for item in sorted(
            {item.fixture_id: item for item in active_fixtures}.values(),
            key=lambda item: (
                item.kickoff_at is None,
                item.kickoff_at,
                item.home_team,
                item.away_team,
                item.fixture_id,
            ),
        )
    ]
    try:
        fixture_index = active_fixture_ids.index(fixture.fixture_id)
    except ValueError:
        return color_for_fixture(fixture)
    return FOOTBALL_FIXTURE_PALETTE[fixture_index % len(FOOTBALL_FIXTURE_PALETTE)]
