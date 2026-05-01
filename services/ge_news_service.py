from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from xml.etree.ElementTree import ParseError


GE_FOOTBALL_RSS_URL = "https://ge.globo.com/Esportes/Rss/0,,AS0-9825,00.xml"
GE_FOOTBALL_PAGE_URL = "https://ge.globo.com/futebol/"
MAX_SEEN_ITEMS = 300
REQUEST_TIMEOUT_SECONDS = 20
MAX_NEWS_AGE_DAYS = 2
MAX_NEWS_PER_CHECK = 3


@dataclass(frozen=True)
class GeNewsItem:
    identifier: str
    title: str
    link: str
    summary: str
    published_at: datetime | None


class GeNewsFeedClient:
    def __init__(self, feed_url: str = GE_FOOTBALL_PAGE_URL) -> None:
        self.feed_url = feed_url

    async def fetch_news(self) -> list[GeNewsItem]:
        content = await asyncio.to_thread(self._fetch_feed_content)
        return parse_ge_news_content(content)

    def _fetch_feed_content(self) -> str:
        request = Request(
            self.feed_url,
            headers={
                "User-Agent": "Mozilla/5.0 DiscordBot/1.0 (+https://discord.com)",
                "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
            },
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(content_type, errors="replace")


class GeNewsStateRepository:
    def __init__(self, state_path: Path, max_seen_items: int = MAX_SEEN_ITEMS) -> None:
        self.state_path = state_path
        self.max_seen_items = max_seen_items

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"channel_id": None, "seen_ids": []}

        with self.state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        channel_id = data.get("channel_id")
        seen_ids = data.get("seen_ids", [])
        if not isinstance(channel_id, int):
            channel_id = None
        if not isinstance(seen_ids, list):
            seen_ids = []

        return {
            "channel_id": channel_id,
            "seen_ids": [str(item) for item in seen_ids],
        }

    def save(self, channel_id: int | None, seen_ids: list[str]) -> None:
        trimmed_seen_ids = seen_ids[-self.max_seen_items :]
        data = {
            "channel_id": channel_id,
            "seen_ids": trimmed_seen_ids,
        }

        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)


def parse_ge_news_content(content: str) -> list[GeNewsItem]:
    sanitized_content = content.lstrip("\ufeff\r\n\t ")
    if not sanitized_content.startswith("<"):
        preview = sanitized_content[:80].replace("\n", " ").replace("\r", " ")
        raise ValueError(f"GE nao retornou HTML/XML valido. Inicio da resposta: {preview!r}")

    if re.match(r"<(?:!DOCTYPE\s+)?html\b", sanitized_content[:80], re.IGNORECASE):
        return parse_ge_news_page(sanitized_content)

    return parse_ge_news_feed(sanitized_content)


def parse_ge_news_feed(xml_content: str) -> list[GeNewsItem]:
    sanitized_content = xml_content.lstrip("\ufeff\r\n\t ")
    if not sanitized_content.startswith("<"):
        preview = sanitized_content[:80].replace("\n", " ").replace("\r", " ")
        raise ValueError(f"Feed do GE nao retornou XML valido. Inicio da resposta: {preview!r}")

    try:
        root = ElementTree.fromstring(sanitized_content)
    except ParseError as exc:
        preview = sanitized_content[:80].replace("\n", " ").replace("\r", " ")
        raise ValueError(f"Feed do GE retornou XML invalido: {exc}. Inicio da resposta: {preview!r}") from exc

    items = root.findall(".//item")
    news_items: list[GeNewsItem] = []

    for item in items:
        title = _clean_text(_find_text(item, "title"))
        link = _clean_text(_find_text(item, "link"))
        summary = _clean_text(_find_text(item, "description"))
        guid = _clean_text(_find_text(item, "guid"))
        published_at = _parse_rss_date(_find_text(item, "pubDate"))
        identifier = guid or link

        if not title or not link or not identifier:
            continue

        news_items.append(
            GeNewsItem(
                identifier=identifier,
                title=title,
                link=link,
                summary=summary,
                published_at=published_at,
            )
        )

    return news_items


def parse_ge_news_page(html_content: str) -> list[GeNewsItem]:
    links = re.findall(
        r'<a\b[^>]*href=["\'](https://ge\.globo\.com/[^"\']+?\.ghtml)["\'][^>]*>(.*?)</a>',
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    news_items: list[GeNewsItem] = []
    seen_links: set[str] = set()

    for link, raw_title in links:
        normalized_link = _normalize_ge_link(link)
        if normalized_link in seen_links or not _is_ge_news_link(normalized_link):
            continue

        title = _clean_text(raw_title)
        if not title or title.lower() == "mostrar mais":
            continue

        seen_links.add(normalized_link)
        news_items.append(
            GeNewsItem(
                identifier=normalized_link,
                title=title,
                link=normalized_link,
                summary="",
                published_at=None,
            )
        )

    if not news_items:
        raise ValueError("Pagina do GE nao trouxe links de noticias reconheciveis.")

    return news_items


def get_unseen_news(items: list[GeNewsItem], seen_ids: set[str]) -> list[GeNewsItem]:
    unseen = [item for item in items if item.identifier not in seen_ids]
    return list(reversed(unseen))


def get_recent_unseen_news(
    items: list[GeNewsItem],
    seen_ids: set[str],
    max_age_days: int = MAX_NEWS_AGE_DAYS,
) -> list[GeNewsItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    recent_items = [
        item
        for item in items
        if item.published_at is None or _as_utc(item.published_at) >= cutoff
    ]
    return get_unseen_news(recent_items, seen_ids)


def _find_text(element: ElementTree.Element, tag_name: str) -> str:
    child = element.find(tag_name)
    if child is not None and child.text:
        return child.text

    for namespaced_child in element:
        if namespaced_child.tag.endswith(f"}}{tag_name}") and namespaced_child.text:
            return namespaced_child.text

    return ""


def _clean_text(value: str) -> str:
    unescaped = html.unescape(value or "")
    without_tags = re.sub(r"<[^>]+>", "", unescaped)
    return re.sub(r"\s+", " ", without_tags).strip()


def _normalize_ge_link(link: str) -> str:
    return link.split("#", 1)[0].split("?", 1)[0]


def _is_ge_news_link(link: str) -> bool:
    if "/jogo/" in link or "/index/feed/" in link:
        return False
    return "/futebol/" in link and ("/noticia/" in link or "/post/" in link)


def _parse_rss_date(value: str) -> datetime | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
