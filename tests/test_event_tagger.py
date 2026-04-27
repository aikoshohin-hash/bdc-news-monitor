"""Tests for the BDC event taxonomy tagger (Issue #1).

Coverage target: each of the 10 categories with >=3 cases (positive +
counter-examples). Sub-type detection is also exercised.
"""
from __future__ import annotations

import pytest

from bdc_news.extractors import EventTagger


@pytest.fixture(scope="module")
def tagger() -> EventTagger:
    return EventTagger.from_yaml()


# ---------------------------------------------------------------- earnings
def test_earnings_q3_report(tagger):
    r = tagger.tag("Ares Capital Reports Q3 2025 Net Investment Income")
    assert "earnings" in r.tags


def test_earnings_quarterly_results(tagger):
    r = tagger.tag("Main Street Announces Quarterly Results", "NAV per share rose")
    assert "earnings" in r.tags


def test_earnings_jp(tagger):
    r = tagger.tag("Ares Capital が四半期決算を発表", "純投資利益は前期比で増加")
    assert "earnings" in r.tags


# --------------------------------------------------------------- non_accrual
def test_non_accrual_hyphen(tagger):
    r = tagger.tag("FS KKR Capital places loan on non-accrual")
    assert "non_accrual" in r.tags
    assert r.severity == "high"


def test_non_accrual_no_hyphen(tagger):
    r = tagger.tag("Nonaccrual rate declines for the quarter")
    assert "non_accrual" in r.tags


def test_non_performing(tagger):
    r = tagger.tag("Non-performing loans flat", "")
    assert "non_accrual" in r.tags


# ----------------------------------------------------------------- nav_decline
def test_nav_writedown(tagger):
    r = tagger.tag("BDC announces writedown of two portfolio investments")
    assert "nav_decline" in r.tags
    assert r.severity == "high"


def test_nav_dropped(tagger):
    r = tagger.tag("Hercules Capital NAV dropped 2.3% in Q4")
    assert "nav_decline" in r.tags


def test_impairment_jp(tagger):
    r = tagger.tag("一部投資先の評価損を計上", "減損処理")
    assert "nav_decline" in r.tags


# ------------------------------------------------------------- dividend_action
def test_dividend_raise(tagger):
    r = tagger.tag("Blackstone Secured Lending raises dividend by 5%")
    assert "dividend_action" in r.tags
    assert "dividend_raise" in r.sub_tags


def test_dividend_cut(tagger):
    r = tagger.tag("Prospect Capital cuts dividend amid portfolio stress")
    assert "dividend_action" in r.tags
    assert "dividend_cut" in r.sub_tags


def test_supplemental_distribution(tagger):
    r = tagger.tag("OBDC declares supplemental distribution for Q2")
    assert "dividend_action" in r.tags
    assert "special_dividend" in r.sub_tags


# -------------------------------------------------------------- capital_action
def test_secondary_offering(tagger):
    r = tagger.tag("ARCC announces secondary offering of 8M shares")
    assert "capital_action" in r.tags
    assert "secondary_offering" in r.sub_tags


def test_buyback(tagger):
    r = tagger.tag("BBDC board approves $50M share repurchase program")
    assert "capital_action" in r.tags
    assert "share_repurchase" in r.sub_tags


def test_notes_offering(tagger):
    r = tagger.tag("Sixth Street Specialty Lending Senior Notes due 2030 priced")
    assert "capital_action" in r.tags
    assert "debt_issuance" in r.sub_tags


# ---------------------------------------------------------------------- m_and_a
def test_merger(tagger):
    r = tagger.tag("Two BDCs announce merger of equals", "all-stock deal")
    assert "m_and_a" in r.tags


def test_acquisition(tagger):
    r = tagger.tag("Manager to acquire smaller competitor", "definitive agreement signed")
    assert "m_and_a" in r.tags


def test_acquisition_jp(tagger):
    r = tagger.tag("プライベートクレジットファンドの経営統合を発表", "")
    assert "m_and_a" in r.tags


# ---------------------------------------------------------------- rating_action
def test_downgrade(tagger):
    r = tagger.tag("Moody's downgrades BDC's senior unsecured to Baa3")
    assert "rating_action" in r.tags
    assert r.severity == "high"


def test_upgrade(tagger):
    r = tagger.tag("S&P upgrades issuer credit rating to BBB", "outlook stable")
    assert "rating_action" in r.tags


def test_rating_jp(tagger):
    r = tagger.tag("S&Pが格下げを発表", "見通しはネガティブ")
    assert "rating_action" in r.tags


# ------------------------------------------------------------------ regulatory
def test_sec_rule(tagger):
    r = tagger.tag("SEC proposal targets BDC disclosure rules")
    assert "regulatory" in r.tags


def test_fsoc(tagger):
    r = tagger.tag("FSOC flags private credit risk in annual report")
    assert "regulatory" in r.tags


def test_regulator_jp(tagger):
    r = tagger.tag("金融庁、プライベートクレジット規制を検討")
    assert "regulatory" in r.tags


# ------------------------------------------------------------------ personnel
def test_ceo_departure(tagger):
    r = tagger.tag("BDC CEO departure announced", "CFO will serve as interim")
    assert "personnel" in r.tags


def test_cfo_appointment(tagger):
    r = tagger.tag("Manager appoints new CFO from JP Morgan")
    assert "personnel" in r.tags


def test_step_down(tagger):
    r = tagger.tag("Long-time CEO to step down at year end", "succession underway")
    assert "personnel" in r.tags


# ----------------------------------------------------------- portfolio_company
def test_amend_and_extend(tagger):
    r = tagger.tag("Portfolio company completes amend and extend on term loan")
    assert "portfolio_company" in r.tags


def test_chapter_11(tagger):
    r = tagger.tag("Portfolio company files for Chapter 11 bankruptcy")
    assert "portfolio_company" in r.tags


def test_covenant_lite(tagger):
    r = tagger.tag("Covenant lite loan to portfolio company restructured")
    assert "portfolio_company" in r.tags


# ---------------------------------------------------- multi-label & no-match
def test_no_match_returns_empty_tags(tagger):
    r = tagger.tag("Weather forecast for Tokyo this weekend")
    assert r.tags == []
    assert r.severity is None
    assert r.confidence == 0.0


def test_multi_label_dividend_and_capital(tagger):
    r = tagger.tag(
        "ARCC raises dividend and announces secondary offering of 5M shares"
    )
    assert "dividend_action" in r.tags
    assert "capital_action" in r.tags
    assert "dividend_raise" in r.sub_tags
    assert "secondary_offering" in r.sub_tags


def test_severity_picks_highest(tagger):
    # earnings (medium) + non_accrual (high) -> severity should be "high"
    r = tagger.tag("Quarterly results show non-accrual rate ticking up")
    assert "earnings" in r.tags
    assert "non_accrual" in r.tags
    assert r.severity == "high"
