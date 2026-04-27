"""SEC EDGAR XBRL companyfacts client (Issue #2).

Fetches structured XBRL data from
``https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`` and the filings
list from ``https://data.sec.gov/submissions/CIK{cik}.json``. Both endpoints
are free and do not require an API key. SEC requires a descriptive
User-Agent and rate-limits to ~10 req/sec.

Responses are cached on disk (``data/edgar_cache/``) so re-runs (and tests)
do not need to hit the network repeatedly.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import os

import httpx

from bdc_news.collectors.base import DEFAULT_TIMEOUT
from bdc_news.paths import DATA_DIR

log = logging.getLogger(__name__)

EDGAR_HOST = "https://data.sec.gov"
COMPANYFACTS_TPL = EDGAR_HOST + "/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_TPL = EDGAR_HOST + "/submissions/CIK{cik}.json"
EDGAR_CACHE_DIR = DATA_DIR / "edgar_cache"

# SEC EDGAR Fair Access policy requires a User-Agent identifying the
# requester with a contact email. Override via SEC_EDGAR_USER_AGENT env var
# in CI/local to put your own contact info there.
_DEFAULT_UA = (
    "bdc-news-monitor/0.1 (research; contact: bdc-news-monitor@example.com)"
)


def _build_headers() -> dict[str, str]:
    ua = os.environ.get("SEC_EDGAR_USER_AGENT") or _DEFAULT_UA
    return {
        "User-Agent": ua,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


class EdgarClient:
    """Thin HTTP client for SEC EDGAR's XBRL & submissions APIs.

    Disk cache is keyed by URL filename. Pass ``offline=True`` (or set
    ``BDC_EDGAR_OFFLINE=1``) to forbid network access — the client will then
    raise ``FileNotFoundError`` if a cached file is missing, which is the
    behaviour tests rely on.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        offline: bool = False,
        sleep_seconds: float = 0.15,
    ) -> None:
        self.cache_dir = cache_dir or EDGAR_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.sleep_seconds = sleep_seconds

    def companyfacts(self, cik: str) -> dict[str, Any]:
        cik_padded = self._pad_cik(cik)
        url = COMPANYFACTS_TPL.format(cik=cik_padded)
        return self._get_json(url, f"companyfacts_CIK{cik_padded}.json")

    def submissions(self, cik: str) -> dict[str, Any]:
        cik_padded = self._pad_cik(cik)
        url = SUBMISSIONS_TPL.format(cik=cik_padded)
        return self._get_json(url, f"submissions_CIK{cik_padded}.json")

    @staticmethod
    def _pad_cik(cik: str) -> str:
        s = str(cik).strip().lstrip("CIK").lstrip("0")
        if not s:
            return "0000000000"
        return s.zfill(10)

    def _get_json(self, url: str, cache_name: str) -> dict[str, Any]:
        cached = self.cache_dir / cache_name
        if cached.exists():
            try:
                return json.loads(cached.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warning("EDGAR cache read failed for %s: %s", cached, e)
        if self.offline:
            raise FileNotFoundError(f"offline mode: no cached file at {cached}")
        log.info("EDGAR fetch %s", url)
        with httpx.Client(headers=_build_headers(), timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
        cached.write_text(json.dumps(data), encoding="utf-8")
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return data
