from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from services.ge_news_service import (
    GeNewsItem,
    GeNewsStateRepository,
    get_recent_unseen_news,
    get_unseen_news,
    parse_ge_news_content,
    parse_ge_news_feed,
    parse_ge_news_page,
)


RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>GE Futebol</title>
    <item>
      <title>Primeira noticia</title>
      <link>https://ge.globo.com/futebol/noticia/primeira.ghtml</link>
      <guid>noticia-1</guid>
      <description><![CDATA[<p>Resumo da primeira noticia.</p>]]></description>
      <pubDate>Thu, 30 Apr 2026 20:10:00 -0300</pubDate>
    </item>
    <item>
      <title>Segunda noticia</title>
      <link>https://ge.globo.com/futebol/noticia/segunda.ghtml</link>
      <description>Resumo da segunda noticia.</description>
    </item>
  </channel>
</rss>
"""

HTML_SAMPLE = """
<!DOCTYPE html>
<html>
  <body>
    <a class="feed-post-link" href="https://ge.globo.com/futebol/times/palmeiras/noticia/2026/04/30/noticia-nova.ghtml">
      <h2>Noticia nova do Palmeiras</h2>
    </a>
    <a href="https://ge.globo.com/futebol/times/palmeiras/noticia/2026/04/30/noticia-nova.ghtml">
      <img alt="Noticia nova do Palmeiras">
    </a>
    <a href="https://ge.globo.com/futebol/libertadores/jogo/30-04-2026/time-a-time-b.ghtml">
      Time A x Time B - Ao vivo
    </a>
    <a href="https://ge.globo.com/futebol/index/feed/pagina-2.ghtml">Mostrar mais</a>
    <a href="https://ge.globo.com/blogs/blog-do-irlan-simoes/post/2026/04/30/postagem.ghtml">
      Blog com assunto de futebol
    </a>
    <a href="https://ge.globo.com/basquete/noticia/2026/04/30/noticia-do-nbb.ghtml">
      Noticia do NBB
    </a>
  </body>
</html>
"""


class GeNewsServiceTests(unittest.TestCase):
    def test_parse_ge_news_feed_extracts_items(self) -> None:
        items = parse_ge_news_feed(RSS_SAMPLE)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].identifier, "noticia-1")
        self.assertEqual(items[0].title, "Primeira noticia")
        self.assertEqual(items[0].summary, "Resumo da primeira noticia.")
        self.assertIsNotNone(items[0].published_at)
        self.assertEqual(items[1].identifier, "https://ge.globo.com/futebol/noticia/segunda.ghtml")

    def test_parse_ge_news_content_accepts_rss(self) -> None:
        items = parse_ge_news_content(RSS_SAMPLE)

        self.assertEqual([item.title for item in items], ["Primeira noticia", "Segunda noticia"])

    def test_parse_ge_news_page_extracts_current_news_links(self) -> None:
        items = parse_ge_news_page(HTML_SAMPLE)

        self.assertEqual([item.title for item in items], ["Noticia nova do Palmeiras"])
        self.assertEqual(
            items[0].identifier,
            "https://ge.globo.com/futebol/times/palmeiras/noticia/2026/04/30/noticia-nova.ghtml",
        )
        self.assertIsNone(items[0].published_at)

    def test_get_unseen_news_returns_oldest_first(self) -> None:
        items = parse_ge_news_feed(RSS_SAMPLE)

        unseen = get_unseen_news(items, {"noticia-1"})

        self.assertEqual([item.title for item in unseen], ["Segunda noticia"])

    def test_get_recent_unseen_news_filters_old_items(self) -> None:
        recent = GeNewsItem(
            identifier="recent",
            title="Recente",
            link="https://ge.globo.com/recent.ghtml",
            summary="",
            published_at=datetime.now(timezone.utc),
        )
        old = GeNewsItem(
            identifier="old",
            title="Antiga",
            link="https://ge.globo.com/old.ghtml",
            summary="",
            published_at=datetime.now(timezone.utc) - timedelta(days=30),
        )

        unseen = get_recent_unseen_news([recent, old], set())

        self.assertEqual([item.identifier for item in unseen], ["recent"])

    def test_state_repository_marks_initial_state_empty(self) -> None:
        state_path = Path.cwd() / f"ge_news_state_test_{uuid4().hex}.json"
        repository = GeNewsStateRepository(state_path)

        try:
            self.assertEqual(repository.load(), {"channel_id": None, "seen_ids": []})

            repository.save(123, ["a", "b"])

            self.assertEqual(repository.load(), {"channel_id": 123, "seen_ids": ["a", "b"]})
        finally:
            state_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
