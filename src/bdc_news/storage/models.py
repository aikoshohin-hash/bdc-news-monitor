"""SQLAlchemy models for the local SQLite working store."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

from bdc_news.paths import DB_PATH

Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"

    id = Column(String(36), primary_key=True)
    url_canonical = Column(Text, unique=True, nullable=False)
    source_name = Column(String(128))
    source_id = Column(String(64))
    title = Column(Text, nullable=False)
    snippet = Column(Text, default="")
    language = Column(String(8))
    published_at = Column(DateTime, index=True)
    collected_at = Column(DateTime, default=datetime.utcnow)
    content_hash = Column(String(32), index=True)
    is_relevant = Column(Integer, default=0, index=True)
    relevance_rule = Column(String(64))

    scores = relationship("ArticleScore", back_populates="article", cascade="all, delete-orphan")
    entities = relationship("ArticleEntity", back_populates="article", cascade="all, delete-orphan")


class ArticleScore(Base):
    __tablename__ = "article_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(36), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    sentiment = Column(Float)
    label = Column(String(16))
    confidence = Column(Float)
    target = Column(String(32), default="industry")
    model = Column(String(64))
    pos_hits = Column(Integer, default=0)
    neg_hits = Column(Integer, default=0)
    scored_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="scores")


class ArticleEntity(Base):
    __tablename__ = "article_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(36), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(32))
    entity_name = Column(String(128))
    ticker = Column(String(16))

    article = relationship("Article", back_populates="entities")


class DailyIndex(Base):
    __tablename__ = "daily_index"
    __table_args__ = (UniqueConstraint("date", "region", name="uq_daily_region"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    region = Column(String(16), default="all")
    n_articles = Column(Integer, default=0)
    sent_mean = Column(Float)
    sent_weighted = Column(Float)
    pos_ratio = Column(Float)
    neg_ratio = Column(Float)
    heat_index = Column(Float)


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_symbol_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), index=True)
    date = Column(Date, index=True)
    close = Column(Float)
    volume = Column(Float)


_engine = None
_SessionLocal = None


def init_db(db_path: Path | None = None):
    global _engine, _SessionLocal
    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{target}", future=True)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


@contextmanager
def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
