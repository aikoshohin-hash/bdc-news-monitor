"""Export DB snapshots to docs/data/*.json for GitHub Pages."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from bdc_news.paths import DOCS_DATA_DIR
from bdc_news.pipeline.aggregator import compute_daily_index, _region_of, _domain_of
from bdc_news.storage.models import (
    Article,
    ArticleScore,
    BdcQuarterlyMetric,
    Price,
    get_session,
)

log = logging.getLogger(__name__)


def _jsonable(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"not serializable: {type(o)}")


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, default=_jsonable, separators=(",", ":")),
        encoding="utf-8",
    )


def export_articles() -> int:
    items: list[dict] = []
    with get_session() as s:
        # Only export cluster representatives (is_cluster_rep=1) or
        # articles that haven't been clustered yet (cluster_id IS NULL).
        # This eliminates near-duplicate articles from the dashboard.
        rows = s.execute(
            select(Article, ArticleScore)
            .outerjoin(ArticleScore, ArticleScore.article_id == Article.id)
            .where(Article.is_relevant == 1)
            .where(
                (Article.is_cluster_rep == 1) | (Article.cluster_id.is_(None))
            )
            .order_by(Article.published_at.desc())
        ).all()
        for art, sc in rows:
            items.append(
                {
                    "id": art.id,
                    "url": art.url_canonical,
                    "title": art.title,
                    "snippet": art.snippet or "",
                    "source": art.source_name or _domain_of(art.url_canonical or ""),
                    "language": art.language or "en",
                    "region": _region_of(art),
                    "published_at": art.published_at.isoformat() if art.published_at else None,
                    "sentiment": float(sc.sentiment) if sc and sc.sentiment is not None else None,
                    "label": (sc.label if sc else None),
                    "confidence": float(sc.confidence) if sc and sc.confidence is not None else None,
                    "event_tags": _decode_tag_list(sc.event_tags if sc else None),
                    "event_sub_tags": _decode_tag_list(sc.event_sub_tags if sc else None),
                    "event_severity": (sc.event_severity if sc else None),
                    "cluster_size": art.cluster_size or 1,
                }
            )
    _write(DOCS_DATA_DIR / "articles.json", {"generated_at": _now(), "items": items})
    return len(items)


def _decode_tag_list(raw) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def export_daily_index() -> int:
    rows = compute_daily_index()
    out = [
        {
            "date": r["date"].isoformat(),
            "region": r["region"],
            "n_articles": r["n_articles"],
            "sent_mean": r["sent_mean"],
            "sent_weighted": r["sent_weighted"],
            "pos_ratio": r["pos_ratio"],
            "neg_ratio": r["neg_ratio"],
            "heat_index": r["heat_index"],
        }
        for r in rows
    ]
    _write(DOCS_DATA_DIR / "daily_index.json", {"generated_at": _now(), "items": out})
    return len(out)


def export_monthly_index() -> int:
    # Aggregate daily_index by month + region
    rows = compute_daily_index()
    agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"n": 0, "sum_s_w": 0.0, "w_count": 0, "pos": 0, "neg": 0}
    )
    for r in rows:
        key = (r["date"].strftime("%Y-%m"), r["region"])
        b = agg[key]
        b["n"] += r["n_articles"]
        # weight each day's mean by its article count (simple roll-up)
        b["sum_s_w"] += r["sent_weighted"] * r["n_articles"]
        b["w_count"] += r["n_articles"]
        b["pos"] += int(r["pos_ratio"] * r["n_articles"])
        b["neg"] += int(r["neg_ratio"] * r["n_articles"])
    items = []
    for (month, region), b in sorted(agg.items()):
        if b["w_count"] == 0:
            continue
        items.append(
            {
                "month": month,
                "region": region,
                "n_articles": b["n"],
                "sent_weighted": round(b["sum_s_w"] / b["w_count"], 4),
                "pos_ratio": round(b["pos"] / max(b["w_count"], 1), 4),
                "neg_ratio": round(b["neg"] / max(b["w_count"], 1), 4),
            }
        )
    _write(DOCS_DATA_DIR / "monthly_index.json", {"generated_at": _now(), "items": items})
    return len(items)


def export_prices() -> int:
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    with get_session() as s:
        rows = s.execute(
            select(Price).order_by(Price.symbol, Price.date)
        ).scalars().all()
        for p in rows:
            by_symbol[p.symbol].append({"date": p.date.isoformat(), "close": p.close})
    _write(
        DOCS_DATA_DIR / "prices.json",
        {"generated_at": _now(), "series": by_symbol},
    )
    return sum(len(v) for v in by_symbol.values())


def export_by_entity() -> int:
    """Count relevant articles per ticker by matching ticker/manager mentions
    in title+snippet. Lightweight — just to power the By Entity tab."""
    import yaml
    from bdc_news.paths import CONFIG_DIR
    data = yaml.safe_load((CONFIG_DIR / "tickers.yaml").read_text(encoding="utf-8")) or {}
    tickers = data.get("active_tickers", []) or []
    # Only BDCs for entity counting
    bdc_tickers = [t for t in tickers if t.get("group") == "bdc"]

    counts: dict[str, dict] = {
        t["symbol"]: {
            "symbol": t["symbol"],
            "name": t["name"],
            "n": 0,
            "pos": 0,
            "neg": 0,
            "sent_sum": 0.0,
            "sent_n": 0,
            "by_month": defaultdict(lambda: {"n": 0, "sent_sum": 0.0, "sent_n": 0}),
        }
        for t in bdc_tickers
    }

    def mentions(text: str, t: dict) -> bool:
        if not text:
            return False
        low = text.lower()
        if t["symbol"].lower() in low:
            return True
        if t["name"].lower() in low:
            return True
        return False

    with get_session() as s:
        rows = s.execute(
            select(Article, ArticleScore)
            .outerjoin(ArticleScore, ArticleScore.article_id == Article.id)
            .where(Article.is_relevant == 1)
        ).all()
        for art, sc in rows:
            blob = f"{art.title or ''} {art.snippet or ''}"
            for t in bdc_tickers:
                if mentions(blob, t):
                    c = counts[t["symbol"]]
                    c["n"] += 1
                    month = art.published_at.strftime("%Y-%m") if art.published_at else "unknown"
                    bm = c["by_month"][month]
                    bm["n"] += 1
                    if sc is not None and sc.sentiment is not None and (sc.confidence or 0) > 0:
                        c["sent_sum"] += sc.sentiment
                        c["sent_n"] += 1
                        bm["sent_sum"] += sc.sentiment
                        bm["sent_n"] += 1
                        if sc.sentiment > 0.2:
                            c["pos"] += 1
                        elif sc.sentiment < -0.2:
                            c["neg"] += 1
    items = []
    for sym, c in counts.items():
        mean = (c["sent_sum"] / c["sent_n"]) if c["sent_n"] else 0.0
        by_month = [
            {
                "month": m,
                "n": v["n"],
                "sent_mean": round(v["sent_sum"] / v["sent_n"], 4) if v["sent_n"] else 0.0,
            }
            for m, v in sorted(c["by_month"].items())
        ]
        items.append(
            {
                "symbol": c["symbol"],
                "name": c["name"],
                "n": c["n"],
                "pos": c["pos"],
                "neg": c["neg"],
                "sent_mean": round(mean, 4),
                "by_month": by_month,
            }
        )
    items.sort(key=lambda x: -x["n"])
    _write(DOCS_DATA_DIR / "by_entity.json", {"generated_at": _now(), "items": items})
    return len(items)


def export_quarterly_metrics() -> int:
    """Issue #2: dump bdc_quarterly_metrics grouped by ticker."""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    with get_session() as s:
        rows = s.execute(
            select(BdcQuarterlyMetric).order_by(
                BdcQuarterlyMetric.ticker, BdcQuarterlyMetric.fiscal_period
            )
        ).scalars().all()
        for r in rows:
            by_ticker[r.ticker].append(
                {
                    "fiscal_period": r.fiscal_period,
                    "fiscal_year": r.fiscal_year,
                    "fiscal_quarter": r.fiscal_quarter,
                    "form_type": r.form_type,
                    "filing_date": r.filing_date.isoformat() if r.filing_date else None,
                    "nav_per_share": r.nav_per_share,
                    "total_investments_at_fair_value": r.total_investments_at_fair_value,
                    "net_investment_income_per_share": r.net_investment_income_per_share,
                    "distribution_per_share": r.distribution_per_share,
                    "non_accruals_pct_at_cost": r.non_accruals_pct_at_cost,
                    "non_accruals_pct_at_fair_value": r.non_accruals_pct_at_fair_value,
                    "pik_income_pct_of_total_income": r.pik_income_pct_of_total_income,
                    "asset_coverage_ratio": r.asset_coverage_ratio,
                    "weighted_avg_yield_debt_investments": r.weighted_avg_yield_debt_investments,
                    "first_lien_pct": r.first_lien_pct,
                    "second_lien_pct": r.second_lien_pct,
                    "filing_url": r.filing_url,
                    "extraction_source": r.extraction_source,
                }
            )
    _write(
        DOCS_DATA_DIR / "quarterly_metrics.json",
        {"generated_at": _now(), "series": by_ticker},
    )
    return sum(len(v) for v in by_ticker.values())


def export_meta(extra: dict | None = None) -> None:
    meta = {
        "generated_at": _now(),
        "version": "0.1.0",
        "methodology": "Offline Loughran-McDonald subset (EN) + hand-curated JP finance polarity + domain overrides. No external API.",
    }
    if extra:
        meta.update(extra)
    _write(DOCS_DATA_DIR / "meta.json", meta)


def export_all() -> dict:
    n_articles = export_articles()
    n_daily = export_daily_index()
    n_monthly = export_monthly_index()
    n_prices = export_prices()
    n_entities = export_by_entity()
    n_metrics = export_quarterly_metrics()
    export_meta(
        {
            "counts": {
                "articles": n_articles,
                "daily_rows": n_daily,
                "monthly_rows": n_monthly,
                "price_points": n_prices,
                "entities": n_entities,
                "quarterly_metrics": n_metrics,
            }
        }
    )
    return {
        "articles": n_articles,
        "daily": n_daily,
        "monthly": n_monthly,
        "prices": n_prices,
        "entities": n_entities,
        "quarterly_metrics": n_metrics,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
