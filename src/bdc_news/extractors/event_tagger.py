"""BDC event tagger — rule-based stage 1 (Issue #1).

Reads ``config/event_taxonomy.yaml`` and assigns multi-label event tags to
article (title + snippet) text. Completely offline; no model download.

Stage 2 (lightweight classifier on weak labels) is tracked as a separate PR.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from bdc_news.paths import CONFIG_DIR

SEVERITY_RANK = {None: 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class TagResult:
    tags: list[str]              # primary categories that matched, e.g. ["earnings", "dividend_action"]
    sub_tags: list[str]          # sub-classifications, e.g. ["dividend_raise"]
    severity: str | None         # highest severity across matched categories
    confidence: float            # 0.0 - 1.0 — heuristic from match count / text length
    matched_phrases: list[str]   # phrases that triggered, useful for debugging / unit tests


class EventTagger:
    """Rule-based multi-label tagger driven by ``event_taxonomy.yaml``."""

    def __init__(self, taxonomy: dict | None = None) -> None:
        if taxonomy is None:
            taxonomy = self._load_default()
        self._categories: dict[str, dict] = taxonomy.get("events", {}) or {}
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        for cat, spec in self._categories.items():
            patterns = spec.get("patterns") or []
            self._compiled_patterns[cat] = [re.compile(p, re.IGNORECASE) for p in patterns]

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> "EventTagger":
        target = path or (CONFIG_DIR / "event_taxonomy.yaml")
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return cls(taxonomy=data)

    @staticmethod
    def _load_default() -> dict:
        return yaml.safe_load((CONFIG_DIR / "event_taxonomy.yaml").read_text(encoding="utf-8")) or {}

    @property
    def categories(self) -> list[str]:
        return list(self._categories.keys())

    def tag(self, title: str, snippet: str = "") -> TagResult:
        """Return a TagResult for the given article fragment.

        Matching is done over ``title + ' ' + snippet`` lowercased once.
        Both English keywords and Japanese keywords are checked. JP keywords
        are matched against the original (non-lowercased) text in addition,
        since lowercasing is a no-op for kana/kanji but case-insensitive
        compare is preserved for any romanized terms inside ``keywords_jp``.
        """
        text = f"{title or ''} {snippet or ''}"
        text_low = text.lower()

        matched: dict[str, list[str]] = {}
        sub_matches: list[str] = []

        for cat, spec in self._categories.items():
            hits: list[str] = []

            for kw in (spec.get("keywords_en") or []):
                if kw.lower() in text_low:
                    hits.append(kw)

            for kw in (spec.get("keywords_jp") or []):
                if kw in text or kw.lower() in text_low:
                    hits.append(kw)

            for pat in self._compiled_patterns.get(cat, []):
                m = pat.search(text)
                if m:
                    hits.append(m.group(0))

            if not hits:
                continue
            matched[cat] = hits

            sub_kw_map = spec.get("sub_type_keywords") or {}
            for sub, phrases in sub_kw_map.items():
                for ph in phrases:
                    if ph.lower() in text_low or ph in text:
                        sub_matches.append(sub)
                        break

        # Severity = highest among matched categories
        sev: str | None = None
        sev_rank = 0
        for cat in matched:
            cat_sev = self._categories[cat].get("severity")
            if SEVERITY_RANK.get(cat_sev, 0) > sev_rank:
                sev_rank = SEVERITY_RANK.get(cat_sev, 0)
                sev = cat_sev

        # Confidence — # matched phrases relative to text length, clamped
        n_phrases = sum(len(v) for v in matched.values())
        denom = max(len(text_low.split()), 1)
        density = n_phrases / denom
        confidence = min(1.0, density * 6) if matched else 0.0

        flat_phrases: list[str] = []
        for v in matched.values():
            flat_phrases.extend(v)

        return TagResult(
            tags=sorted(matched.keys()),
            sub_tags=sorted(set(sub_matches)),
            severity=sev,
            confidence=round(confidence, 4),
            matched_phrases=flat_phrases,
        )
