"""Near-duplicate article detection and clustering.

Uses character n-gram Jaccard similarity on titles within a ±1 day
window.  No external libraries required — runs in milliseconds for
hundreds of articles.

Pipeline step:  bdc-news dedup
Runs after ``collect`` (and optionally after ``classify``).
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select, update

from bdc_news.storage.models import Article, get_session

log = logging.getLogger(__name__)

# ── tunables ──
SIM_THRESHOLD = 0.45   # Jaccard ≥ this → same news
DATE_WINDOW_DAYS = 1   # articles must be within ±N days
NGRAM_SIZE = 3          # character trigrams


# ================================================================ text sim
_STRIP_RE = re.compile(r"[^\w]", re.UNICODE)


def _ngrams(text: str, n: int = NGRAM_SIZE) -> set[str]:
    """Extract character-level n-grams from normalised text."""
    t = _STRIP_RE.sub("", text.lower())
    if len(t) < n:
        return {t} if t else set()
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_similarity(t1: str, t2: str) -> float:
    """Compute title similarity via character trigram Jaccard."""
    return jaccard(_ngrams(t1), _ngrams(t2))


# ============================================================ clustering

def _pick_representative(articles: list[Article]) -> Article:
    """Choose the best representative from a cluster of similar articles.

    Priority: longest snippet → earliest published date → first collected.
    """
    def _score(a: Article) -> tuple:
        snippet_len = len(a.snippet or "")
        title_len = len(a.title or "")
        # prefer articles with more content, then earlier published
        return (snippet_len + title_len, -(a.published_at.timestamp() if a.published_at else 0))
    return max(articles, key=_score)


def run_dedup(*, only_unclustered: bool = True) -> dict[str, int]:
    """Cluster similar relevant articles and mark duplicates.

    Returns stats dict with keys: total, clusters, duplicates, singletons.
    """
    with get_session() as s:
        stmt = select(Article).where(Article.is_relevant == 1)
        if only_unclustered:
            stmt = stmt.where(Article.cluster_id.is_(None))
        articles: list[Article] = list(s.execute(stmt).scalars())

    if not articles:
        return {"total": 0, "clusters": 0, "duplicates": 0, "singletons": 0}

    log.info("Dedup: processing %d articles", len(articles))

    # Group by date bucket (to narrow pairwise comparisons)
    by_date: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        if a.published_at:
            d = a.published_at.strftime("%Y-%m-%d")
        else:
            d = "unknown"
        by_date[d].append(a)

    # Pre-compute trigram sets
    ngram_cache: dict[str, set[str]] = {}
    for a in articles:
        ngram_cache[a.id] = _ngrams(a.title or "")

    # Union-Find for clustering
    parent: dict[str, str] = {a.id: a.id for a in articles}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Compare articles within ±DATE_WINDOW_DAYS
    date_keys = sorted(by_date.keys())
    for i, dk in enumerate(date_keys):
        # Collect articles from adjacent date buckets
        candidates = list(by_date[dk])
        for j in range(max(0, i - DATE_WINDOW_DAYS), min(len(date_keys), i + DATE_WINDOW_DAYS + 1)):
            if j != i:
                candidates.extend(by_date[date_keys[j]])

        local_articles = by_date[dk]
        for ai, a in enumerate(local_articles):
            ng_a = ngram_cache[a.id]
            for b in candidates:
                if a.id >= b.id:
                    continue  # avoid double comparison
                if find(a.id) == find(b.id):
                    continue  # already clustered
                sim = jaccard(ng_a, ngram_cache[b.id])
                if sim >= SIM_THRESHOLD:
                    union(a.id, b.id)

    # Build clusters
    clusters: dict[str, list[Article]] = defaultdict(list)
    article_map = {a.id: a for a in articles}
    for a in articles:
        root = find(a.id)
        clusters[root].append(a)

    n_clusters = 0
    n_dupes = 0
    n_singletons = 0

    with get_session() as s:
        for root, members in clusters.items():
            if len(members) == 1:
                # Singleton — mark as its own cluster representative
                art = s.get(Article, members[0].id)
                if art:
                    art.cluster_id = members[0].id
                    art.is_cluster_rep = 1
                    art.cluster_size = 1
                n_singletons += 1
                continue

            n_clusters += 1
            cluster_id = str(uuid.uuid4())
            rep = _pick_representative(members)

            for m in members:
                art = s.get(Article, m.id)
                if art is None:
                    continue
                art.cluster_id = cluster_id
                art.cluster_size = len(members)
                if m.id == rep.id:
                    art.is_cluster_rep = 1
                else:
                    art.is_cluster_rep = 0
                    n_dupes += 1

    stats = {
        "total": len(articles),
        "clusters": n_clusters,
        "duplicates": n_dupes,
        "singletons": n_singletons,
    }
    log.info("Dedup complete: %s", stats)
    return stats
