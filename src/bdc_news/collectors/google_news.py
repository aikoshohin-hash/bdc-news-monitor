"""Google News RSS collector (no API key).

Google News exposes an RSS feed for any search query:
  https://news.google.com/rss/search?q=<query>&hl=<lang>&gl=<country>&ceid=<country>:<lang>
"""
from __future__ import annotations

import logging
import time
import urllib.parse
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

RSS_BASE = "https://news.google.com/rss/search"


class GoogleNewsCollector:
    id = "google_news"

    def __init__(self, queries_en: list[dict], queries_ja: list[dict]):
        self.queries = []
        for q in queries_en:
            self.queries.append({**q, "_lang": "en"})
        for q in queries_ja:
            self.queries.append({**q, "_lang": "ja"})

    def _build_url(self, q: dict) -> str:
        params = {
            "q": q["q"],
            "hl": q.get("hl", "en-US"),
            "gl": q.get("gl", "US"),
            "ceid": q.get("ceid", "US:en"),
        }
        return f"{RSS_BASE}?{urllib.parse.urlencode(params, safe=':')}"

    def collect(self) -> Iterable[CollectedItem]:
        with httpx.Client(
            headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        ) as client:
            for q in self.queries:
                url = self._build_url(q)
                log.info("GoogleNews fetch: %s", q["q"])
                try:
                    r = client.get(url)
                    r.raise_for_status()
                except Exception as e:  # noqa: BLE001
                    log.warning("GoogleNews fetch failed: %s (%s)", q["q"], e)
                    continue

                parsed = feedparser.parse(r.content)
                for entry in parsed.entries:
                    yield self._to_item(entry, q)
                time.sleep(2.0)  # be polite

    @staticmethod
    def _to_item(entry, q) -> CollectedItem:
        title = entry.get("title", "")
        link = entry.get("link", "")
        source = entry.get("source", {}).get("title") if entry.get("source") else None
        snippet = entry.get("summary", "") or entry.get("description", "")
        # Strip HTML tags crudely from the summary
        import re
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
            source_name=source,
            source_id="google_news",
            published_at=dt,
            language=q.get("_lang"),
        )
