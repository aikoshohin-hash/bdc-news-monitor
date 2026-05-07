"""Tests for near-duplicate article detection (dedup module)."""
from __future__ import annotations

import pytest

from bdc_news.pipeline.dedup import (
    _ngrams,
    jaccard,
    title_similarity,
    _pick_representative,
)


class TestNgrams:
    def test_basic(self):
        ng = _ngrams("hello", 3)
        assert "hel" in ng
        assert "ell" in ng
        assert "llo" in ng

    def test_short_text(self):
        ng = _ngrams("ab", 3)
        assert ng == {"ab"}

    def test_empty(self):
        assert _ngrams("", 3) == set()

    def test_removes_punctuation(self):
        ng = _ngrams("a-b-c", 3)
        assert ng == _ngrams("abc", 3)

    def test_unicode_ja(self):
        ng = _ngrams("プライベートクレジット", 3)
        assert len(ng) > 0
        assert "プラ" not in ng  # 2-char, not 3-char
        assert "プライ" in ng


class TestJaccard:
    def test_identical(self):
        s = {"a", "b", "c"}
        assert jaccard(s, s) == 1.0

    def test_disjoint(self):
        assert jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_overlap(self):
        assert jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)

    def test_empty(self):
        assert jaccard(set(), {"a"}) == 0.0


class TestTitleSimilarity:
    def test_identical_titles(self):
        sim = title_similarity(
            "ARCC Reports Q3 2025 Earnings Results",
            "ARCC Reports Q3 2025 Earnings Results",
        )
        assert sim == 1.0

    def test_near_duplicate(self):
        sim = title_similarity(
            "Ares Capital Reports Strong Q3 Earnings",
            "Ares Capital Reports Strong Q3 2025 Earnings",
        )
        assert sim > 0.7

    def test_same_news_different_source(self):
        sim = title_similarity(
            "Ares Capital Reports Record Q3 Earnings Results",
            "Ares Capital Reports Strong Q3 Earnings Results",
        )
        assert sim > 0.6  # very similar titles from different sources

    def test_unrelated(self):
        sim = title_similarity(
            "Ares Capital Q3 earnings beat expectations",
            "Japan GDP growth slows in Q2",
        )
        assert sim < 0.25

    def test_japanese_near_duplicate(self):
        sim = title_similarity(
            "プライベートクレジット市場が過熱、リスクの蓄積が懸念される",
            "プライベートクレジット市場の過熱、リスク蓄積に警戒感",
        )
        assert sim > 0.35  # Japanese trigrams share less due to particles

    def test_japanese_unrelated(self):
        sim = title_similarity(
            "プライベートクレジット市場が拡大",
            "日銀が金利を据え置き決定",
        )
        assert sim < 0.3


class TestPickRepresentative:
    """Test representative selection logic."""

    def _make_article(self, title="", snippet="", pub_ts=None):
        """Create a mock article for testing."""
        from unittest.mock import MagicMock
        from datetime import datetime

        a = MagicMock()
        a.id = str(id(a))
        a.title = title
        a.snippet = snippet
        a.published_at = pub_ts or datetime(2025, 1, 1)
        return a

    def test_prefers_longer_content(self):
        from datetime import datetime

        short = self._make_article("Short title", "brief", datetime(2025, 1, 1))
        long = self._make_article(
            "Long detailed title about ARCC earnings",
            "This is a much longer snippet with detailed analysis of quarterly results",
            datetime(2025, 1, 1, 12, 0),
        )
        rep = _pick_representative([short, long])
        assert rep.id == long.id

    def test_prefers_earlier_date_on_tie(self):
        from datetime import datetime

        a = self._make_article("Same title", "Same snippet", datetime(2025, 1, 1))
        b = self._make_article("Same title", "Same snippet", datetime(2025, 1, 2))
        rep = _pick_representative([a, b])
        # Earlier publication should win (timestamp comparison)
        assert rep.id == a.id
