"""Issue #4 — BDC / private-credit domain sentiment overlay.

Loads ``config/sentiment_overrides_bdc.yaml`` and provides a lightweight
overlay applied as the **final** stage of sentiment scoring. Unlike the
older ``lexicons/domain_override.csv`` (which adds positive/negative
hits), this overlay operates on the post-aggregation sentiment value
itself: each matching rule contributes its declared ``polarity`` (a
float in [-1.0, +1.0]) directly, and the result is clamped.

Rules can declare ``context_required`` to gate firing on a co-occurring
keyword — useful for terms whose polarity flips depending on context
(e.g., "PIK income" is bearish only when "increased"/"rose" appears).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from bdc_news.paths import CONFIG_DIR

log = logging.getLogger(__name__)


@dataclass
class BdcOverrideRule:
    pattern: str
    polarity: float
    lang: str = "en"
    context_required: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""

    def matches(self, text: str, lang: str) -> bool:
        haystack = text or ""
        if self.lang.startswith("en"):
            if self.pattern.lower() not in haystack.lower():
                return False
        else:
            if self.pattern not in haystack:
                return False
        if self.context_required:
            ctx_hay = haystack if self.lang.startswith("ja") else haystack.lower()
            ctx_terms = (
                self.context_required
                if self.lang.startswith("ja")
                else tuple(c.lower() for c in self.context_required)
            )
            if not any(c in ctx_hay for c in ctx_terms):
                return False
        return True


@dataclass
class OverlayResult:
    delta: float
    new_sentiment: float
    fired: list[str]


class BdcOverrideOverlay:
    """Applies BDC-specific polarity adjustments after base scoring."""

    def __init__(self, rules: Iterable[BdcOverrideRule]):
        self.rules = list(rules)
        log.info("BdcOverrideOverlay loaded with %d rules", len(self.rules))

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> "BdcOverrideOverlay":
        path = path or (CONFIG_DIR / "sentiment_overrides_bdc.yaml")
        if not path.exists():
            return cls([])
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = []
        for raw in data.get("rules", []) or []:
            try:
                rules.append(
                    BdcOverrideRule(
                        pattern=str(raw["pattern"]),
                        polarity=float(raw.get("polarity", 0.0)),
                        lang=str(raw.get("lang", "en")),
                        context_required=tuple(raw.get("context_required") or ()),
                        rationale=str(raw.get("rationale", "")),
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                log.warning("skipping malformed override rule %r: %s", raw, e)
        return cls(rules)

    def apply(self, sentiment: float, text: str, language: str | None = None) -> OverlayResult:
        lang = (language or "").lower()
        delta = 0.0
        fired: list[str] = []
        for rule in self.rules:
            # Language gate: EN rules apply to non-JP text; JP rules to JP text.
            if rule.lang.startswith("ja") and not lang.startswith("ja"):
                continue
            if rule.lang.startswith("en") and lang.startswith("ja"):
                continue
            if rule.matches(text, lang):
                delta += rule.polarity
                fired.append(rule.pattern)
        new = max(-1.0, min(1.0, sentiment + delta))
        return OverlayResult(delta=round(delta, 4), new_sentiment=round(new, 4), fired=fired)
