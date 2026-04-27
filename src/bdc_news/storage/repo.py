"""CRUD helpers for the articles / scores / prices tables."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, date
from typing import Iterable

from sqlalchemy import select

from bdc_news.storage.models import (
    Article,
    ArticleScore,
    BdcQuarterlyMetric,
    DailyIndex,
    Price,
    get_session,
)


def upsert_article(
    *,
    url_canonical: str,
    title: str,
    snippet: str = "",
    source_name: str | None = None,
    source_id: str | None = None,
    language: str | None = None,
    published_at: datetime | None = None,
    content_hash: str | None = None,
) -> tuple[str, bool]:
    """Insert or skip if a row with the same url_canonical already exists.

    Returns (article_id, was_created).
    """
    with get_session() as s:
        existing = s.execute(
            select(Article).where(Article.url_canonical == url_canonical)
        ).scalar_one_or_none()
        if existing:
            return existing.id, False
        aid = str(uuid.uuid4())
        art = Article(
            id=aid,
            url_canonical=url_canonical,
            title=title,
            snippet=snippet or "",
            source_name=source_name,
            source_id=source_id,
            language=language,
            published_at=published_at,
            content_hash=content_hash,
            is_relevant=0,
        )
        s.add(art)
        return aid, True


def mark_relevance(article_id: str, is_relevant: bool, rule: str | None = None) -> None:
    with get_session() as s:
        art = s.get(Article, article_id)
        if art is None:
            return
        art.is_relevant = 1 if is_relevant else 0
        art.relevance_rule = rule


def save_score(
    *,
    article_id: str,
    sentiment: float,
    label: str,
    confidence: float,
    model: str,
    pos_hits: int,
    neg_hits: int,
    target: str = "industry",
) -> None:
    with get_session() as s:
        s.query(ArticleScore).filter(ArticleScore.article_id == article_id).delete()
        s.add(
            ArticleScore(
                article_id=article_id,
                sentiment=sentiment,
                label=label,
                confidence=confidence,
                model=model,
                pos_hits=pos_hits,
                neg_hits=neg_hits,
                target=target,
            )
        )


def iter_unscored_relevant_articles(limit: int | None = None) -> list[Article]:
    with get_session() as s:
        stmt = (
            select(Article)
            .where(Article.is_relevant == 1)
            .where(~Article.scores.any())
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(s.execute(stmt).scalars())


def iter_relevant_articles_for_tagging(limit: int | None = None, only_untagged: bool = True) -> list[Article]:
    """Iterate relevant articles that need event tagging.

    If ``only_untagged`` is True (default), restricts to articles whose
    ``ArticleScore.event_tags`` is null/empty. Pass False to re-tag all
    relevant articles (e.g. after taxonomy changes).
    """
    with get_session() as s:
        stmt = select(Article).where(Article.is_relevant == 1)
        if only_untagged:
            stmt = stmt.where(
                Article.scores.any(
                    (ArticleScore.event_tags.is_(None)) | (ArticleScore.event_tags == "")
                )
            )
        if limit:
            stmt = stmt.limit(limit)
        return list(s.execute(stmt).scalars())


def save_event_tags(
    *,
    article_id: str,
    tags: list[str],
    sub_tags: list[str],
    severity: str | None,
    confidence: float,
) -> None:
    """Persist event tags onto the latest ArticleScore row for an article.

    Creates a placeholder ArticleScore if none exists yet (rare — usually
    sentiment scoring runs first). Tags are JSON-encoded so the column stays
    a single TEXT field.
    """
    with get_session() as s:
        sc = (
            s.execute(
                select(ArticleScore).where(ArticleScore.article_id == article_id)
            ).scalar_one_or_none()
        )
        if sc is None:
            sc = ArticleScore(article_id=article_id, model="event-tagger")
            s.add(sc)
        sc.event_tags = json.dumps(tags, ensure_ascii=False)
        sc.event_sub_tags = json.dumps(sub_tags, ensure_ascii=False)
        sc.event_severity = severity
        sc.event_confidence = confidence


def iter_unclassified_articles(limit: int | None = None) -> list[Article]:
    with get_session() as s:
        stmt = select(Article).where(Article.relevance_rule.is_(None))
        if limit:
            stmt = stmt.limit(limit)
        return list(s.execute(stmt).scalars())


def upsert_price(symbol: str, d: date, close: float, volume: float | None = None) -> None:
    with get_session() as s:
        existing = s.execute(
            select(Price).where(Price.symbol == symbol, Price.date == d)
        ).scalar_one_or_none()
        if existing:
            existing.close = close
            existing.volume = volume
        else:
            s.add(Price(symbol=symbol, date=d, close=close, volume=volume))


def upsert_quarterly_metric(row: dict) -> None:
    """Insert or update a BdcQuarterlyMetric row keyed by (ticker, fiscal_period).

    Pass a dict produced by ``QuarterlyMetric.to_db_kwargs()``. None values
    are written as-is (the spec allows nulls when an extractor cannot find
    a metric).
    """
    with get_session() as s:
        existing = s.execute(
            select(BdcQuarterlyMetric).where(
                BdcQuarterlyMetric.ticker == row["ticker"],
                BdcQuarterlyMetric.fiscal_period == row["fiscal_period"],
            )
        ).scalar_one_or_none()
        if existing:
            for k, v in row.items():
                setattr(existing, k, v)
        else:
            s.add(BdcQuarterlyMetric(**row))


def iter_quarterly_metrics(ticker: str | None = None) -> list[BdcQuarterlyMetric]:
    with get_session() as s:
        stmt = select(BdcQuarterlyMetric).order_by(
            BdcQuarterlyMetric.ticker, BdcQuarterlyMetric.fiscal_period
        )
        if ticker:
            stmt = stmt.where(BdcQuarterlyMetric.ticker == ticker)
        return list(s.execute(stmt).scalars())


def upsert_daily_index(row: dict) -> None:
    with get_session() as s:
        existing = s.execute(
            select(DailyIndex).where(
                DailyIndex.date == row["date"], DailyIndex.region == row["region"]
            )
        ).scalar_one_or_none()
        if existing:
            for k, v in row.items():
                setattr(existing, k, v)
        else:
            s.add(DailyIndex(**row))
