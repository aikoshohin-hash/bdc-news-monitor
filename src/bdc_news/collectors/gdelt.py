"""GDELT DOC 2.0 Article Search API (free, no key).

https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=ArtList&format=JSON
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterable

import httpx
from dateutil import parser as dateparser

from bdc_news.collectors.base import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    CollectedItem,
)

log = logging.getLogger(__name__)

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltCollector:
    id = "gdelt"

    def __init__(self, queries: list[str], maxrecords: int = 100, timespan: str = "24h"):
        self.queries = queries
        self.maxrecords = min(maxrecords, 250)
        self.timespan = timespan

    def collect(self) -> Iterable[CollectedItem]:
        with httpx.Client(
            headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT, follow_redirects=True
        ) as client:
            for q in self.queries:
                params = {
                    "query": q,
                    "mode": "ArtList",
                    "format": "JSON",
                    "maxrecords": str(self.maxrecords),
                    "timespan": self.timespan,
                    "sort": "DateDesc",
                }
                log.info("GDELT fetch: %s", q)
                try:
                    r = client.get(GDELT_DOC, params=params)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:  # noqa: BLE001
                    log.warning("GDELT fetch failed: %s (%s)", q, e)
                    continue

                for art in data.get("articles", []) or []:
                    yield self._to_item(art)
                time.sleep(2.0)

    @staticmethod
    def _to_item(art: dict) -> CollectedItem:
        url = art.get("url", "")
        title = art.get("title", "")
        snippet = art.get("excerpt", "") or art.get("seendate", "")
        if len(snippet) > 400:
            snippet = snippet[:400]
        seendate = art.get("seendate")
        dt: datetime | None = None
        if seendate:
            try:
                # format: "20260424T123000Z" -> parse
                if len(seendate) == 16:
                    dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(
                        tzinfo=timezone.utc
                    )
                else:
                    dt = dateparser.parse(seendate)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                dt = None
        lang = art.get("language", "").lower()
        if lang == "english":
            lang = "en"
        elif lang == "japanese":
            lang = "ja"
        return CollectedItem(
            url=url,
            title=title,
            snippet=snippet,
            source_name=art.get("domain"),
            source_id="gdelt",
            published_at=dt,
            language=lang or None,
        )
