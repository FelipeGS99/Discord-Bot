from __future__ import annotations

import unittest

from config import settings
from bot import COGS


class LibertadoresConfigTests(unittest.TestCase):
    def test_libertadores_cog_is_loaded(self) -> None:
        self.assertIn("cogs.libertadores", COGS)

    def test_libertadores_default_league_id(self) -> None:
        self.assertEqual(settings.libertadores_league_id, 32)


if __name__ == "__main__":
    unittest.main()
