"""Daily aggregation of article counts + sentiment into indices."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from sqlalchemy import select

from bdc_news.paths import CONFIG_DIR
from bdc_news.storage.models import Article, ArticleScore, get_session


REGION_JP = "jp"
REGION_US = "us"
REGION_GLOBAL = "global"
REGION_ALL = "all"


def _load_weights() -> tuple[dict[str, float], float]:
    path = CONFIG_DIR / "weights.yaml"
    if not path.exists():
        return {}, 0.5
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("sources", {}) or {}, float(data.get("default", 0.5))


def _domain_of(url: str) -> str:
    try:
        host = urlsplit(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return ""


def _region_of(article: Article) -> str:
    if (article.language or "").startswith("ja"):
        return REGION_JP
    d = _domain_of(article.url_canonical or "")
    if d.endswith(".jp"):
        return REGION_JP
    return REGION_GLOBAL


def compute_daily_index() -> list[dict]:
    """Compute per-day x per-region rows. Only relevant+scored articles are counted
    for sentiment; article counts also include relevant-but-unscored items."""
    weights, default_w = _load_weights()

    # Collect raw facts
    by_region: dict[tuple[date, str], dict] = defaultdict(
        lambda: {"n": 0, "sum_w_s": 0.0, "sum_w": 0.0, "pos": 0, "neg": 0, "scored": 0}
    )
    by_all: dict[date, dict] = defaultdict(
        lambda: {"n": 0, "sum_w_s": 0.0, "sum_w": 0.0, "pos": 0, "neg": 0, "scored": 0}
    )

    with get_session() as s:
        rows = s.execute(
            select(Article, ArticleScore)
            .outerjoin(ArticleScore, ArticleScore.article_id == Article.id)
            .where(Article.is_relevant == 1)
        ).all()
        for art, sc in rows:
            if not art.published_at:
                continue
            d = art.published_at.date() if isinstance(art.published_at, datetime) else art.published_at
            region = _region_of(art)
            domain = _domain_of(art.url_canonical or "")
            w = weights.get(domain, default_w)
            for bucket in (by_region[(d, region)], by_all[d]):
                bucket["n"] += 1
            if sc is not None and sc.confidence and sc.confidence > 0.0:
                for bucket in (by_region[(d, region)], by_all[d]):
                    bucket["sum_w_s"] += w * (sc.sentiment or 0.0)
                    bucket["sum_w"] += w
                    bucket["scored"] += 1
                    if (sc.sentiment or 0.0) > 0.2:
                        bucket["pos"] += 1
                    elif (sc.sentiment or 0.0) < -0.2:
                        bucket["neg"] += 1

    rows: list[dict] = []
    for (d, region), b in by_region.items():
        rows.append(_bucket_to_row(d, region, b))
    for d, b in by_all.items():
        rows.append(_bucket_to_row(d, REGION_ALL, b))
    rows.sort(key=lambda r: (r["date"], r["region"]))
    return rows


def _bucket_to_row(d: date, region: str, b: dict) -> dict:
    n = b["n"]
    scored = b["scored"]
    mean = (b["sum_w_s"] / b["sum_w"]) if b["sum_w"] > 0 else 0.0
    pos_ratio = (b["pos"] / scored) if scored > 0 else 0.0
    neg_ratio = (b["neg"] / scored) if scored > 0 else 0.0
    flow = math.log1p(n)
    heat = flow * abs(mean)
    return {
        "date": d,
        "region": region,
        "n_articles": n,
        "sent_mean": round(mean, 4),
        "sent_weighted": round(mean, 4),
        "pos_ratio": round(pos_ratio, 4),
        "neg_ratio": round(neg_ratio, 4),
        "heat_index": round(heat, 4),
    }
