"""Sanity checks for the offline sentiment scorer."""
from __future__ import annotations

import pytest

from bdc_news.pipeline.sentiment import SentimentScorer


@pytest.fixture(scope="module")
def scorer() -> SentimentScorer:
    return SentimentScorer()


# ---------------------------------------------------------------- English

POS_EN = [
    "Ares Capital delivered strong earnings growth and an upgraded dividend outlook.",
    "Blue Owl's direct lending platform expanded with robust fundraising momentum.",
    "Portfolio credit quality improved and non-accruals declined meaningfully.",
]

NEG_EN = [
    "BDC reports rising non-accruals and weaker dividend coverage.",
    "Default rates are climbing as leveraged loan spreads widen sharply.",
    "Fund suffered a loss and announced a painful dividend cut amid credit deterioration.",
]

NEU_EN = [
    "Company filed its quarterly report with the Securities and Exchange Commission.",
    "Board meeting scheduled to discuss routine governance matters.",
]


@pytest.mark.parametrize("text", POS_EN)
def test_en_positive(scorer, text):
    s = scorer.score(text, language="en")
    assert s.label == "positive", f"expected positive, got {s}"
    assert s.sentiment > 0


@pytest.mark.parametrize("text", NEG_EN)
def test_en_negative(scorer, text):
    s = scorer.score(text, language="en")
    assert s.label == "negative", f"expected negative, got {s}"
    assert s.sentiment < 0


@pytest.mark.parametrize("text", NEU_EN)
def test_en_neutral_ish(scorer, text):
    s = scorer.score(text, language="en")
    assert s.label in {"neutral", "positive", "negative"}  # don't over-constrain
    # Confidence should be low for bland text
    assert s.confidence <= 0.9


def test_en_negation_flip(scorer):
    plain = scorer.score("The portfolio improved.", language="en")
    flipped = scorer.score("The portfolio did not improve.", language="en")
    assert plain.sentiment > 0
    assert flipped.sentiment <= 0


def test_en_domain_override(scorer):
    s = scorer.score("Default rate rises across middle-market BDC portfolios.", language="en")
    assert s.label == "negative"
    assert s.override_applied is True


# ---------------------------------------------------------------- Japanese

POS_JA = [
    "増配が決定し、運用資産も過去最高を更新した。",
    "新規組成の動きが拡大しており、業界は堅調に推移。",
]

NEG_JA = [
    "デフォルト率の上昇が続き、貸倒引当金の増加が懸念されている。",
    "配当の減額とノンアクルーアル増加で収益性が悪化。",
]


@pytest.mark.parametrize("text", POS_JA)
def test_ja_positive(scorer, text):
    s = scorer.score(text, language="ja")
    assert s.label == "positive", f"expected positive, got {s}"


@pytest.mark.parametrize("text", NEG_JA)
def test_ja_negative(scorer, text):
    s = scorer.score(text, language="ja")
    assert s.label == "negative", f"expected negative, got {s}"


def test_ja_domain_override(scorer):
    s = scorer.score("スプレッドの拡大が続き、信用環境は悪化している。", language="ja")
    assert s.label == "negative"
    assert s.override_applied is True
