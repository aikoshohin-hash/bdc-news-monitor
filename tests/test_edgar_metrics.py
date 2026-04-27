"""Tests for the EDGAR XBRL metrics extractor (Issue #2).

Uses a synthetic companyfacts fixture so tests run fully offline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bdc_news.extractors import EdgarClient, EdgarMetricsExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "edgar"


@pytest.fixture(scope="module")
def offline_client() -> EdgarClient:
    return EdgarClient(cache_dir=FIXTURE_DIR, offline=True)


@pytest.fixture(scope="module")
def extractor(offline_client) -> EdgarMetricsExtractor:
    return EdgarMetricsExtractor(
        client=offline_client,
        cik_map={"ARCC": "0001287750"},
    )


# ----------------------------------------------- basic extraction
def test_extract_returns_periods(extractor):
    rows = extractor.extract_for_ticker("ARCC")
    # Fixture has 4 periods
    assert len(rows) == 4
    fps = {r.fiscal_period for r in rows}
    assert fps == {"2025Q3", "2025Q2", "2025Q1", "2024FY"}


def test_total_investments_at_fair_value(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    assert rows["2025Q3"].total_investments_at_fair_value == 28_200_000_000
    assert rows["2024FY"].total_investments_at_fair_value == 26_900_000_000


def test_nav_per_share_computed_from_equity_and_shares(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    # 12.8B / 660M = 19.3939...
    assert rows["2025Q3"].nav_per_share == pytest.approx(19.3939, abs=0.001)
    # FY: 11.9B / 645M = 18.4496
    assert rows["2024FY"].nav_per_share == pytest.approx(18.4496, abs=0.001)


def test_nii_per_share_uses_weighted_average_shares(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    # 395M / 658M wavg = 0.60
    assert rows["2025Q3"].net_investment_income_per_share == pytest.approx(0.60, abs=0.005)


def test_distribution_per_share_pulled_from_xbrl(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    assert rows["2025Q3"].distribution_per_share == pytest.approx(0.48)


# ----------------------------------------------- metadata
def test_form_type_recorded(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    assert rows["2025Q3"].form_type == "10-Q"
    assert rows["2024FY"].form_type == "10-K"


def test_fiscal_quarter_present_for_quarters_only(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    assert rows["2025Q3"].fiscal_quarter == 3
    assert rows["2024FY"].fiscal_quarter is None


def test_filing_date_extracted(extractor):
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    assert rows["2025Q3"].filing_date is not None
    assert rows["2025Q3"].filing_date.isoformat() == "2025-10-29"


def test_unfilled_metrics_remain_null(extractor):
    """Spec: pipeline must not fail when an extractor cannot find a metric."""
    rows = {r.fiscal_period: r for r in extractor.extract_for_ticker("ARCC")}
    r = rows["2025Q3"]
    # Fixture intentionally omits these — they must come back as None.
    assert r.non_accruals_pct_at_cost is None
    assert r.pik_income_pct_of_total_income is None
    assert r.first_lien_pct is None


# ----------------------------------------------- robustness
def test_unknown_ticker_returns_empty(extractor):
    assert extractor.extract_for_ticker("ZZZZ") == []


def test_offline_mode_without_cache_returns_empty():
    client = EdgarClient(cache_dir=FIXTURE_DIR, offline=True)
    extractor = EdgarMetricsExtractor(client=client, cik_map={"NOPE": "0000000099"})
    assert extractor.extract_for_ticker("NOPE") == []


def test_max_periods_respected(extractor):
    rows = extractor.extract_for_ticker("ARCC", max_periods=2)
    assert len(rows) == 2


# ----------------------------------------------- to_db_kwargs
def test_to_db_kwargs_excludes_notes(extractor):
    rows = extractor.extract_for_ticker("ARCC")
    kw = rows[0].to_db_kwargs()
    assert "notes" not in kw
    assert "ticker" in kw and kw["ticker"] == "ARCC"
    assert "fiscal_period" in kw
