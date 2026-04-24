"""Keyword-based relevance classifier.

Stage 1: MUST-keyword gate (at least one MUST, no EXCLUDE).
Stage 2: entity rule — title or first 200 chars of snippet matches a BDC ticker
         or manager name (boost rule).

Returns (is_relevant: bool, rule_name: str).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from bdc_news.paths import CONFIG_DIR


def _compile(patterns: list[str]) -> re.Pattern[str]:
    if not patterns:
        # Pattern that never matches
        return re.compile(r"(?!)")
    # Word boundary for ASCII; for JP/mixed, use plain substring (still regex).
    escaped = [re.escape(p) for p in patterns]
    return re.compile("|".join(escaped), re.IGNORECASE)


@dataclass
class Classifier:
    must_en: re.Pattern[str]
    must_ja: re.Pattern[str]
    should_en: re.Pattern[str]
    should_ja: re.Pattern[str]
    exclude_en: re.Pattern[str]
    exclude_ja: re.Pattern[str]

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> "Classifier":
        p = Path(path) if path else CONFIG_DIR / "keywords.yaml"
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        must = data.get("must", {}) or {}
        should = data.get("should", {}) or {}
        excl = data.get("exclude", {}) or {}
        return cls(
            must_en=_compile(must.get("en", [])),
            must_ja=_compile(must.get("ja", [])),
            should_en=_compile(should.get("en", [])),
            should_ja=_compile(should.get("ja", [])),
            exclude_en=_compile(excl.get("en", [])),
            exclude_ja=_compile(excl.get("ja", [])),
        )

    def classify(self, title: str, snippet: str, language: str | None = None) -> tuple[bool, str]:
        blob = f"{title or ''}\n{snippet or ''}"
        lang = (language or "en").lower()
        must = self.must_ja if lang.startswith("ja") else self.must_en
        excl = self.exclude_ja if lang.startswith("ja") else self.exclude_en
        should = self.should_ja if lang.startswith("ja") else self.should_en

        # Also try the other language if nothing matches — mixed-language titles happen
        other_must = self.must_en if lang.startswith("ja") else self.must_ja
        other_should = self.should_en if lang.startswith("ja") else self.should_ja

        if excl.search(blob):
            return False, "excluded"

        must_hit = must.search(blob) or other_must.search(blob)
        should_hit = should.search(blob) or other_should.search(blob)

        if must_hit:
            return True, "must"
        if should_hit and _title_mentions_finance(title):
            # Secondary: ticker/manager in title plus finance context in snippet
            return True, "should_entity"
        return False, "no_match"


_FINANCE_CONTEXT = re.compile(
    r"(credit|loan|debt|lending|BDC|NAV|default|fund|yield|dividend|spread|"
    r"クレジット|ローン|債務|融資|BDC|NAV|デフォルト|ファンド|利回り|配当|スプレッド)",
    re.IGNORECASE,
)


def _title_mentions_finance(title: str) -> bool:
    return bool(title and _FINANCE_CONTEXT.search(title))
