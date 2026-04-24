"""URL normalization, language detection, content hashing."""
from __future__ import annotations

import hashlib
import re
import urllib.parse

try:
    from langdetect import detect as _langdetect_detect, DetectorFactory
    DetectorFactory.seed = 42
    _HAS_LANGDETECT = True
except Exception:  # noqa: BLE001
    _HAS_LANGDETECT = False


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "_hsenc", "_hsmi",
}


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    # Strip tracking params
    qsl = urllib.parse.parse_qsl(p.query, keep_blank_values=False)
    qsl = [(k, v) for k, v in qsl if k.lower() not in _TRACKING_PARAMS]
    query = urllib.parse.urlencode(qsl)
    path = re.sub(r"/+$", "", p.path) or "/"
    return urllib.parse.urlunsplit((p.scheme.lower() or "https", netloc, path, query, ""))


_JA_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def detect_language(text: str, fallback: str | None = None) -> str:
    if not text:
        return fallback or "en"
    # Cheap heuristic first: any Japanese kana/kanji → "ja"
    if _JA_RE.search(text):
        return "ja"
    if _HAS_LANGDETECT:
        try:
            return _langdetect_detect(text)
        except Exception:  # noqa: BLE001
            return fallback or "en"
    return fallback or "en"


def compute_hash(*parts: str) -> str:
    """Stable short hash for deduplication. SHA-1 first 16 hex chars."""
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()[:16]
