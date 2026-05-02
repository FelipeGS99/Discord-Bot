from __future__ import annotations

import unittest

from bot import COGS
from config import settings


class CopaDoBrasilConfigTests(unittest.TestCase):
    def test_copadobrasil_cog_is_loaded(self) -> None:
        self.assertIn("cogs.copadobrasil", COGS)

    def test_futebol_cog_is_loaded(self) -> None:
        self.assertIn("cogs.futebol", COGS)

    def test_copadobrasil_default_league_id(self) -> None:
        self.assertEqual(settings.copadobrasil_league_id, 35)


if __name__ == "__main__":
    unittest.main()
