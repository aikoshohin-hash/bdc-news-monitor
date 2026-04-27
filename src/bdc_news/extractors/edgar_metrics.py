"""Issue #2 — Quarterly structured metric extractor for BDC 10-Q/10-K.

Strategy (per spec):
1. **XBRL** (companyfacts API): pull standard us-gaap concepts that map to
   our target metrics — total investments at fair value, weighted-avg
   shares, net assets, NII, distributions, asset coverage.
2. **Compute**: NAV/share = NetAssets / WeightedAvgShares (fallback to
   period-end shares outstanding) when no direct concept exists.
3. **Regex / table fallback**: not yet implemented for the harder fields
   (non-accruals %, PIK %, lien composition). Those fields are left null;
   the spec explicitly allows null on extraction failure.

The extractor returns a list of ``QuarterlyMetric`` records ready to be
upserted into the ``bdc_quarterly_metrics`` table.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from bdc_news.extractors.edgar_client import EdgarClient
from bdc_news.paths import CONFIG_DIR

log = logging.getLogger(__name__)


# us-gaap concepts we consult, in priority order. BDCs sometimes file with
# entity-specific tags too — those would extend the lists below.
CONCEPTS_TOTAL_INVESTMENTS_FV = [
    "InvestmentsFairValueDisclosure",
    "Investments",
    "InvestmentOwnedAtFairValue",
]
CONCEPTS_NET_ASSETS = [
    "StockholdersEquity",
    "NetAssetsOfInvestmentCompany",
    "Equity",
]
CONCEPTS_SHARES_PERIOD_END = [
    "CommonStockSharesOutstanding",
    "EntityCommonStockSharesOutstanding",
]
CONCEPTS_SHARES_WEIGHTED = [
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
]
CONCEPTS_NII = [
    "InvestmentIncomeNet",
    "NetInvestmentIncomeLoss",
]
CONCEPTS_DISTRIBUTIONS_PER_SHARE = [
    "CommonStockDividendsPerShareDeclared",
    "CommonStockDividendsPerShareCashPaid",
    "DistributionsPerShareDeclared",
]
CONCEPTS_NAV_PER_SHARE = [
    "NetAssetValuePerShare",
]
CONCEPTS_ASSET_COVERAGE = [
    "InvestmentCompanyAssetCoverageRatio",
]


@dataclass
class QuarterlyMetric:
    ticker: str
    cik: str
    fiscal_period: str  # e.g. "2025Q3" or "2025FY"
    fiscal_year: int
    fiscal_quarter: int | None  # 1-4 or None for FY/10-K
    form_type: str  # "10-Q" / "10-K" / unknown
    filing_date: date | None
    nav_per_share: float | None = None
    total_investments_at_fair_value: float | None = None
    net_investment_income_per_share: float | None = None
    distribution_per_share: float | None = None
    non_accruals_pct_at_cost: float | None = None
    non_accruals_pct_at_fair_value: float | None = None
    pik_income_pct_of_total_income: float | None = None
    asset_coverage_ratio: float | None = None
    weighted_avg_yield_debt_investments: float | None = None
    first_lien_pct: float | None = None
    second_lien_pct: float | None = None
    filing_url: str | None = None
    extraction_source: str = "xbrl"
    notes: list[str] = field(default_factory=list)

    def to_db_kwargs(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("notes", None)
        return d


class EdgarMetricsExtractor:
    """Extract quarterly metrics for a list of BDC tickers from EDGAR XBRL."""

    def __init__(
        self,
        client: EdgarClient | None = None,
        cik_map: dict[str, str] | None = None,
    ) -> None:
        self.client = client or EdgarClient()
        self.cik_map = cik_map or self._load_cik_map()

    @staticmethod
    def _load_cik_map() -> dict[str, str]:
        path = CONFIG_DIR / "edgar_ciks.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("ciks", {}) or {}

    def extract_for_ticker(
        self, ticker: str, cik: str | None = None, max_periods: int = 12
    ) -> list[QuarterlyMetric]:
        cik = cik or self.cik_map.get(ticker)
        if not cik:
            log.warning("no CIK mapping for %s; skipping", ticker)
            return []
        try:
            facts = self.client.companyfacts(cik)
        except Exception as e:  # noqa: BLE001
            log.warning("companyfacts fetch failed for %s (CIK %s): %s", ticker, cik, e)
            return []
        units = ((facts.get("facts") or {}).get("us-gaap") or {})

        # Build per-period buckets keyed by (fy, fp).
        buckets: dict[tuple[int, str], dict[str, Any]] = {}

        # 1. Investments at fair value (USD, instant)
        self._pull_instant_concept(
            units, CONCEPTS_TOTAL_INVESTMENTS_FV, buckets, "total_investments_at_fair_value"
        )
        # 2. Net assets / equity (USD, instant)
        self._pull_instant_concept(units, CONCEPTS_NET_ASSETS, buckets, "_net_assets")
        # 3. Period-end shares (instant)
        self._pull_instant_concept(units, CONCEPTS_SHARES_PERIOD_END, buckets, "_shares_eop")
        # 4. Weighted-average shares (duration)
        self._pull_duration_concept(units, CONCEPTS_SHARES_WEIGHTED, buckets, "_shares_wavg")
        # 5. NII (duration, USD)
        self._pull_duration_concept(units, CONCEPTS_NII, buckets, "_nii_total")
        # 6. Distributions per share (duration, USD/shares)
        self._pull_duration_concept(
            units, CONCEPTS_DISTRIBUTIONS_PER_SHARE, buckets, "distribution_per_share"
        )
        # 7. NAV per share when directly tagged (instant, USD/shares)
        self._pull_instant_concept(units, CONCEPTS_NAV_PER_SHARE, buckets, "nav_per_share")
        # 8. Asset coverage ratio (instant, pure)
        self._pull_instant_concept(units, CONCEPTS_ASSET_COVERAGE, buckets, "asset_coverage_ratio")

        # Compose QuarterlyMetric rows, computing NAV/share & NII/share where possible.
        records: list[QuarterlyMetric] = []
        for (fy, fp), b in sorted(buckets.items(), reverse=True):
            shares = b.get("_shares_eop") or b.get("_shares_wavg")
            if b.get("nav_per_share") is None and b.get("_net_assets") and shares:
                b["nav_per_share"] = round(b["_net_assets"] / shares, 4)
            wavg = b.get("_shares_wavg") or shares
            if b.get("_nii_total") and wavg:
                b["net_investment_income_per_share"] = round(b["_nii_total"] / wavg, 4)
            fq = _quarter_num(fp)
            records.append(
                QuarterlyMetric(
                    ticker=ticker,
                    cik=cik,
                    fiscal_period=f"{fy}{fp}",
                    fiscal_year=fy,
                    fiscal_quarter=fq,
                    form_type=b.get("_form") or ("10-K" if fp == "FY" else "10-Q"),
                    filing_date=b.get("_filed"),
                    nav_per_share=b.get("nav_per_share"),
                    total_investments_at_fair_value=b.get("total_investments_at_fair_value"),
                    net_investment_income_per_share=b.get("net_investment_income_per_share"),
                    distribution_per_share=b.get("distribution_per_share"),
                    asset_coverage_ratio=b.get("asset_coverage_ratio"),
                    filing_url=b.get("_filing_url"),
                    extraction_source="xbrl",
                )
            )
            if len(records) >= max_periods:
                break
        return records

    # ---------------------------- concept pullers --------------------------
    def _pull_instant_concept(
        self,
        units: dict,
        concepts: list[str],
        buckets: dict[tuple[int, str], dict[str, Any]],
        key: str,
    ) -> None:
        for concept in concepts:
            cdata = units.get(concept)
            if not cdata:
                continue
            for unit_name, items in (cdata.get("units") or {}).items():
                for item in items:
                    fy, fp = _period_keys(item)
                    if fy is None:
                        continue
                    b = buckets.setdefault((fy, fp), {})
                    if key not in b:
                        b[key] = item.get("val")
                        _stamp_meta(b, item)

    def _pull_duration_concept(
        self,
        units: dict,
        concepts: list[str],
        buckets: dict[tuple[int, str], dict[str, Any]],
        key: str,
    ) -> None:
        # Duration concepts: prefer the smallest reporting window matching fp.
        for concept in concepts:
            cdata = units.get(concept)
            if not cdata:
                continue
            for unit_name, items in (cdata.get("units") or {}).items():
                for item in items:
                    fy, fp = _period_keys(item)
                    if fy is None:
                        continue
                    if not _is_window_match(item, fp):
                        continue
                    b = buckets.setdefault((fy, fp), {})
                    if key not in b:
                        b[key] = item.get("val")
                        _stamp_meta(b, item)


# --------------------------- helper functions ------------------------------
def _period_keys(item: dict) -> tuple[int | None, str]:
    fy = item.get("fy")
    fp = (item.get("fp") or "").upper()
    if fy is None or fp not in {"Q1", "Q2", "Q3", "Q4", "FY"}:
        return None, ""
    return int(fy), fp


def _is_window_match(item: dict, fp: str) -> bool:
    """For duration items, accept Q1/Q2/Q3 = 3-month, FY/Q4 = 12-month."""
    start = item.get("start")
    end = item.get("end")
    if not start or not end:
        return False
    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return False
    days = (e - s).days
    if fp in {"Q1", "Q2", "Q3"}:
        return 80 <= days <= 100
    if fp in {"FY", "Q4"}:
        return 350 <= days <= 380
    return False


def _stamp_meta(b: dict, item: dict) -> None:
    if "_filed" not in b and item.get("filed"):
        try:
            b["_filed"] = datetime.strptime(item["filed"], "%Y-%m-%d").date()
        except ValueError:
            pass
    if "_form" not in b and item.get("form"):
        b["_form"] = item.get("form")
    if "_accn" not in b and item.get("accn"):
        b["_accn"] = item["accn"]
        accn = item["accn"].replace("-", "")
        # filing index URL — no CIK at hand here, leave as None; CLI can attach.


def _quarter_num(fp: str) -> int | None:
    if fp.startswith("Q") and len(fp) == 2 and fp[1].isdigit():
        return int(fp[1])
    return None
