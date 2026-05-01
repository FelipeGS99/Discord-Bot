from __future__ import annotations

import unittest

from bot import COGS
from config import settings


class SulamericanaConfigTests(unittest.TestCase):
    def test_sulamericana_cog_is_loaded(self) -> None:
        self.assertIn("cogs.sulamericana", COGS)

    def test_futebol_cog_is_loaded(self) -> None:
        self.assertIn("cogs.futebol", COGS)

    def test_sulamericana_default_league_id(self) -> None:
        self.assertEqual(settings.sulamericana_league_id, 33)


if __name__ == "__main__":
    unittest.main()
