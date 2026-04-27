"""Tests for the BDC domain sentiment overlay (Issue #4).

Verifies:
1. Each polarity bucket (bearish credit, dilution, positive credit, ratings)
   shifts the score in the expected direction.
2. ``context_required`` gating prevents false fires (e.g. PIK without
   "increased", non-accrual without bearish direction words).
3. JP rules apply only to JP-language input and vice versa.
4. Final scores are clamped to [-1.0, +1.0].
5. The pre-overlay ``sentiment_pre_bdc`` and ``bdc_overrides_applied``
   fields are populated for transparency.
"""
from __future__ import annotations

import pytest

from bdc_news.pipeline.bdc_overrides import BdcOverrideOverlay, BdcOverrideRule
from bdc_news.pipeline.sentiment import SentimentScorer


@pytest.fixture(scope="module")
def overlay() -> BdcOverrideOverlay:
    return BdcOverrideOverlay.from_yaml()


@pytest.fixture(scope="module")
def scorer() -> SentimentScorer:
    return SentimentScorer()


# ----------------------------------------------------------- bearish credit
def test_amend_and_extend_is_bearish(overlay):
    r = overlay.apply(0.0, "Issuer completed amend and extend on its term loan", "en")
    assert r.delta < 0
    assert "amend and extend" in r.fired


def test_covenant_lite_is_bearish(overlay):
    r = overlay.apply(0.0, "covenant lite loan structure flagged", "en")
    assert r.delta < 0


def test_writedown_is_bearish(overlay):
    r = overlay.apply(0.0, "Manager announced a writedown of two investments", "en")
    assert r.delta < 0


def test_rights_offering_is_bearish(overlay):
    r = overlay.apply(0.0, "Company priced rights offering at discount", "en")
    assert r.delta <= -0.30


def test_downgrade_is_bearish(overlay):
    r = overlay.apply(0.0, "Moody's announced downgrade to Ba2", "en")
    assert r.delta <= -0.30


# ---------------------------------------------------------- positive signals
def test_supplemental_distribution_is_positive(overlay):
    r = overlay.apply(0.0, "Board declared supplemental distribution", "en")
    assert r.delta > 0


def test_first_lien_is_positive(overlay):
    r = overlay.apply(0.0, "Senior first lien position in capital structure", "en")
    assert r.delta > 0


def test_buyback_is_positive(overlay):
    r = overlay.apply(0.0, "Board approved a $50M buyback program", "en")
    assert r.delta > 0


# ---------------------------------------------------- context_required gating
def test_pik_without_growth_context_does_not_fire(overlay):
    r = overlay.apply(0.0, "PIK income from a single portfolio company", "en")
    assert "PIK income" not in r.fired
    assert r.delta == 0


def test_pik_with_growth_context_fires(overlay):
    r = overlay.apply(0.0, "PIK income increased materially in Q3", "en")
    assert "PIK income" in r.fired
    assert r.delta < 0


def test_non_accrual_when_declining_does_not_fire(overlay):
    """non-accrual rule must NOT fire if direction is bearish-decline."""
    r = overlay.apply(0.0, "non-accruals declined for the quarter", "en")
    # No bearish-direction context word, so non-accrual rule stays silent.
    assert "non-accrual" not in r.fired


def test_non_accrual_rising_fires(overlay):
    r = overlay.apply(0.0, "non-accrual rate rose for the third quarter", "en")
    assert "non-accrual" in r.fired
    assert r.delta < 0


def test_placed_on_non_accrual_always_fires(overlay):
    """The explicit event phrase has no context gate."""
    r = overlay.apply(0.0, "Manager placed on non-accrual a senior loan", "en")
    assert "placed on non-accrual" in r.fired
    assert r.delta <= -0.50


# ---------------------------------------------------------- language gating
def test_jp_rule_does_not_fire_on_en(overlay):
    r = overlay.apply(0.0, "downgrade announced; outlook revised", "en")
    assert "格下げ" not in r.fired


def test_en_rule_does_not_fire_on_jp_text(overlay):
    r = overlay.apply(0.0, "amend and extend は債務再編シグナル", "ja")
    assert "amend and extend" not in r.fired


def test_jp_kakusage_fires_on_jp(overlay):
    r = overlay.apply(0.0, "S&Pが格下げを発表", "ja")
    assert "格下げ" in r.fired
    assert r.delta < 0


def test_jp_zoshi_fires_on_jp(overlay):
    r = overlay.apply(0.0, "増配を発表、業績は堅調", "ja")
    assert "増配" in r.fired
    assert r.delta > 0


# ----------------------------------------------------------------- clamping
def test_overlay_clamps_to_minus_one():
    overlay = BdcOverrideOverlay(
        [BdcOverrideRule(pattern="x", polarity=-2.0, lang="en")]
    )
    r = overlay.apply(-0.5, "x", "en")
    assert r.new_sentiment == -1.0


def test_overlay_clamps_to_plus_one():
    overlay = BdcOverrideOverlay(
        [BdcOverrideRule(pattern="x", polarity=+2.0, lang="en")]
    )
    r = overlay.apply(+0.5, "x", "en")
    assert r.new_sentiment == 1.0


# ------------------------------------------------------- scorer integration
def test_scorer_records_pre_bdc_and_delta(scorer):
    s = scorer.score(
        "Manager placed on non-accrual a senior loan to a portfolio company.",
        language="en",
    )
    assert s.bdc_overrides_applied  # at least one rule fired
    assert s.sentiment_pre_bdc is not None
    # Final sentiment should be at least as bearish as pre-BDC
    assert s.sentiment <= s.sentiment_pre_bdc
    assert s.bdc_override_delta < 0


def test_scorer_no_overlay_when_no_rules_match(scorer):
    s = scorer.score("Weather forecast for Tokyo this weekend", language="en")
    # Either no rules fired, or pre and post sentiment are equal.
    assert s.bdc_override_delta == 0.0
    assert s.bdc_overrides_applied == ()
    assert s.sentiment_pre_bdc == s.sentiment


def test_scorer_model_string_marks_bdc(scorer):
    s = scorer.score("BDC raises dividend by 5%", language="en")
    assert s.bdc_overrides_applied
    assert "+bdc" in s.model
