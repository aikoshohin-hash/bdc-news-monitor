"""Plain RSS / Atom feed collector."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import httpx
from dateutil import parser as dateparser

from bdc_news.collectors.base import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    CollectedItem,
)

log = logging.getLogger(__name__)


class RSSCollector:
    id = "rss"

    def __init__(self, feeds: list[dict]):
        self.feeds = feeds

    def collect(self) -> Iterable[CollectedItem]:
        with httpx.Client(
            headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        ) as client:
            for feed in self.feeds:
                url = feed["url"]
                log.info("RSS fetch: %s", url)
                try:
                    r = client.get(url)
                    r.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    log.warning("RSS fetch failed: %s (%s)", url, e)
                    continue
                parsed = feedparser.parse(r.content)
                for entry in parsed.entries:
                    yield self._to_item(entry, feed)
                time.sleep(2.0)

    @staticmethod
    def _to_item(entry, feed) -> CollectedItem:
        title = entry.get("title", "")
        link = entry.get("link", "")
        snippet = entry.get("summary", "") or entry.get("description", "")
        snippet = re.sub(r"<[^>]+>", " ", snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > 400:
            snippet = snippet[:400]
        published = entry.get("published") or entry.get("updated")
        dt: datetime | None = None
        if published:
            try:
                dt = dateparser.parse(published)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                dt = None
        return CollectedItem(
            url=link,
            title=title,
            snippet=snippet,
            source_name=feed.get("name"),
            source_id=feed.get("id"),
            published_at=dt,
            language=feed.get("language"),
        )
