"""CRUD helpers for the articles / scores / prices tables."""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Iterable

from sqlalchemy import select

from bdc_news.storage.models import (
    Article,
    ArticleScore,
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
