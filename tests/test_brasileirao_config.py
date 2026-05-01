from __future__ import annotations

import unittest

from config import settings


class BrasileiraoConfigTests(unittest.TestCase):
    def test_brasileirao_default_league_id(self) -> None:
        self.assertEqual(settings.brasileirao_league_id, 9)


if __name__ == "__main__":
    unittest.main()
