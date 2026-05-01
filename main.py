from __future__ import annotations

import asyncio

from bot import create_bot


def main() -> None:
    bot = create_bot()
    asyncio.run(bot.start_bot())


if __name__ == "__main__":
    main()
