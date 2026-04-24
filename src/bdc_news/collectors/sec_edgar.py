"""SEC EDGAR full-text search (free, no key).

https://efts.sec.gov/LATEST/search-index?q=...&forms=N-2
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

EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"


class SecEdgarCollector:
    id = "sec_edgar"

    def __init__(self, forms: list[str] | None = None, query: str = "\"business development company\""):
        self.forms = forms or ["N-2", "10-K", "10-Q", "8-K"]
        self.query = query

    def collect(self) -> Iterable[CollectedItem]:
        headers = {
            **DEFAULT_HEADERS,
            "Accept": "application/json",
            "Host": "efts.sec.gov",
        }
        params = {
            "q": self.query,
            "forms": ",".join(self.forms),
        }
        with httpx.Client(headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            try:
                r = client.get(EDGAR_FTS, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:  # noqa: BLE001
                log.warning("EDGAR fetch failed: %s", e)
                return

            hits = ((data or {}).get("hits") or {}).get("hits", [])
            for h in hits:
                yield self._to_item(h)
                time.sleep(0.5)

    @staticmethod
    def _to_item(h: dict) -> CollectedItem:
        src = h.get("_source", {}) or {}
        adsh = (h.get("_id") or "").split(":")[0]
        accession = adsh.replace("-", "")
        cik = src.get("ciks", [""])[0] if src.get("ciks") else ""
        display = src.get("display_names", [""])[0] if src.get("display_names") else ""
        forms = src.get("form", "")
        title = f"[{forms}] {display}".strip()
        snippet = " / ".join(filter(None, [src.get("adsh"), forms, display]))
        if len(snippet) > 400:
            snippet = snippet[:400]
        file_date = src.get("file_date")
        dt = None
        if file_date:
            try:
                dt = dateparser.parse(file_date)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                dt = None
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}" if cik else "https://www.sec.gov/edgar/search/"
        if cik and accession:
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/"
        return CollectedItem(
            url=url,
            title=title,
            snippet=snippet,
            source_name="SEC EDGAR",
            source_id="sec_edgar",
            published_at=dt,
            language="en",
        )
