#!/usr/bin/env python3
"""Re-score all articles in docs/data/articles.json using updated lexicons,
then run dedup (title-similarity clustering) directly on the JSON data.

Also exports a deduplicated CSV for external validation.

Usage:
    python scripts/rescore_and_dedup.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Add src to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bdc_news.pipeline.sentiment import SentimentScorer
from bdc_news.pipeline.dedup import _ngrams, jaccard, title_similarity

# ── Config ──
ARTICLES_JSON = ROOT / "docs" / "data" / "articles.json"
DAILY_JSON = ROOT / "docs" / "data" / "daily_index.json"
MONTHLY_JSON = ROOT / "docs" / "data" / "monthly_index.json"
ENTITY_JSON = ROOT / "docs" / "data" / "by_entity.json"
CSV_OUTPUT = ROOT / "docs" / "data" / "articles_deduped.csv"
SIM_THRESHOLD = 0.45
DATE_WINDOW_DAYS = 1


def load_articles() -> tuple[dict, list[dict]]:
    with ARTICLES_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data, data["items"]


def rescore(articles: list[dict], scorer: SentimentScorer) -> dict:
    """Re-score all articles. Returns stats."""
    changes = {"rescored": 0, "label_changed": 0}
    for a in articles:
        text = f"{a.get('title', '')}\n{a.get('snippet', '')}"
        lang = a.get("language", "en") or "en"
        sc = scorer.score(text, lang)
        old_label = a.get("label")
        a["sentiment"] = sc.sentiment
        a["label"] = sc.label
        a["confidence"] = sc.confidence
        changes["rescored"] += 1
        if old_label != sc.label:
            changes["label_changed"] += 1
    return changes


def strip_source_suffix(title: str) -> str:
    """Remove trailing ' - SourceName' from title for better dedup."""
    # Common patterns: " - 奈良新聞", " - Investing.com", "（Bloomberg）", "(Bloomberg)"
    t = re.sub(r"\s*[\-–—]\s*[^-–—]+$", "", title)
    t = re.sub(r"\s*[（(][^)）]+[)）]\s*$", "", t)
    t = re.sub(r"\s*フォトギャラリー.*$", "", t)
    t = re.sub(r"\s*執筆\s*$", "", t)
    return t.strip()


def run_dedup(articles: list[dict]) -> dict:
    """Cluster similar articles using Union-Find on title trigram Jaccard."""
    # Pre-compute: strip source suffixes for similarity comparison
    clean_titles = {}
    ngram_cache = {}
    for i, a in enumerate(articles):
        ct = strip_source_suffix(a.get("title", ""))
        clean_titles[i] = ct
        ngram_cache[i] = _ngrams(ct)

    # Group by date for ±1 day window
    by_date: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(articles):
        d = (a.get("published_at") or "")[:10]
        by_date[d or "unknown"].append(i)

    # Union-Find
    parent = list(range(len(articles)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Compare within date windows
    date_keys = sorted(by_date.keys())
    for i, dk in enumerate(date_keys):
        candidates = list(by_date[dk])
        for j in range(max(0, i - DATE_WINDOW_DAYS), min(len(date_keys), i + DATE_WINDOW_DAYS + 1)):
            if j != i:
                candidates.extend(by_date[date_keys[j]])

        for idx_a in by_date[dk]:
            ng_a = ngram_cache[idx_a]
            for idx_b in candidates:
                if idx_a >= idx_b:
                    continue
                if find(idx_a) == find(idx_b):
                    continue
                sim = jaccard(ng_a, ngram_cache[idx_b])
                if sim >= SIM_THRESHOLD:
                    union(idx_a, idx_b)

    # Build clusters
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(articles)):
        clusters[find(i)].append(i)

    # Pick representatives (longest title+snippet, earliest date)
    kept = []
    removed = 0
    for root, members in clusters.items():
        cluster_id = str(uuid.uuid4()) if len(members) > 1 else articles[members[0]].get("id", str(members[0]))

        def score_art(idx):
            a = articles[idx]
            content_len = len(a.get("title", "")) + len(a.get("snippet", ""))
            # Earlier is better (negative timestamp = earlier wins in max)
            try:
                ts = datetime.fromisoformat(a.get("published_at", "2000-01-01")).timestamp()
            except Exception:
                ts = 0
            return (content_len, -ts)

        best_idx = max(members, key=score_art)
        rep = articles[best_idx].copy()
        rep["cluster_id"] = cluster_id
        rep["cluster_size"] = len(members)
        rep["is_cluster_rep"] = True
        kept.append(rep)
        removed += len(members) - 1

    # Sort by date descending
    kept.sort(key=lambda a: a.get("published_at", ""), reverse=True)

    stats = {
        "total_before": len(articles),
        "total_after": len(kept),
        "removed": removed,
        "clusters_multi": sum(1 for m in clusters.values() if len(m) > 1),
    }
    return kept, stats


def rebuild_indices(articles: list[dict]) -> None:
    """Rebuild daily_index.json, monthly_index.json, by_entity.json from deduped articles."""
    # ── daily index ──
    daily: dict[str, dict[str, list]] = {}  # region -> date -> scores
    for a in articles:
        d = (a.get("published_at") or "")[:10]
        if not d:
            continue
        region = a.get("region", "global")
        for r in [region, "all"]:
            daily.setdefault(r, {}).setdefault(d, []).append(a)

    daily_out = {}
    for region, dates in daily.items():
        rows = []
        for d in sorted(dates.keys()):
            arts = dates[d]
            sents = [a["sentiment"] for a in arts]
            labels = Counter(a["label"] for a in arts)
            n = len(arts)
            rows.append({
                "date": d,
                "n_articles": n,
                "sent_mean": round(sum(sents) / n, 4) if n else 0,
                "sent_median": round(sorted(sents)[n // 2], 4) if n else 0,
                "n_positive": labels.get("positive", 0),
                "n_neutral": labels.get("neutral", 0),
                "n_negative": labels.get("negative", 0),
                "pos_ratio": round(labels.get("positive", 0) / n, 4) if n else 0,
                "neg_ratio": round(labels.get("negative", 0) / n, 4) if n else 0,
            })
        daily_out[region] = rows

    with DAILY_JSON.open("w", encoding="utf-8") as f:
        json.dump(daily_out, f, ensure_ascii=False, indent=1)

    # ── monthly index ──
    monthly: dict[str, dict[str, list]] = {}
    for a in articles:
        d = (a.get("published_at") or "")[:7]  # YYYY-MM
        if not d:
            continue
        region = a.get("region", "global")
        for r in [region, "all"]:
            monthly.setdefault(r, {}).setdefault(d, []).append(a)

    monthly_out = {}
    for region, months in monthly.items():
        rows = []
        for m in sorted(months.keys()):
            arts = months[m]
            sents = [a["sentiment"] for a in arts]
            labels = Counter(a["label"] for a in arts)
            n = len(arts)
            rows.append({
                "month": m,
                "n_articles": n,
                "sent_mean": round(sum(sents) / n, 4) if n else 0,
                "n_positive": labels.get("positive", 0),
                "n_neutral": labels.get("neutral", 0),
                "n_negative": labels.get("negative", 0),
            })
        monthly_out[region] = rows

    with MONTHLY_JSON.open("w", encoding="utf-8") as f:
        json.dump(monthly_out, f, ensure_ascii=False, indent=1)

    # ── by entity ──
    # Extract ticker mentions from event_tags
    entity_data: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        tags = a.get("event_tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        # Use source-based entity detection
        title = (a.get("title") or "").upper()
        # Common BDC tickers
        tickers = [
            "ARCC", "MAIN", "BXSL", "OBDC", "GBDC", "GSBD", "TPVG",
            "PSEC", "FSK", "HTGC", "ORCC", "OCSL", "BLUE OWL", "OWL",
            "BIZD", "CCAP", "KBDC"
        ]
        for tk in tickers:
            if tk in title:
                entity_data[tk].append(a)

    entity_out = {}
    for ticker, arts in entity_data.items():
        sents = [a["sentiment"] for a in arts]
        labels = Counter(a["label"] for a in arts)
        n = len(arts)
        entity_out[ticker] = {
            "n_articles": n,
            "sent_mean": round(sum(sents) / n, 4) if n else 0,
            "n_positive": labels.get("positive", 0),
            "n_neutral": labels.get("neutral", 0),
            "n_negative": labels.get("negative", 0),
            "articles": [{"date": a.get("published_at", "")[:10], "title": a.get("title", ""), "sentiment": a["sentiment"]} for a in arts[:50]],
        }

    with ENTITY_JSON.open("w", encoding="utf-8") as f:
        json.dump(entity_out, f, ensure_ascii=False, indent=1)


def export_csv(articles: list[dict]) -> None:
    """Export deduplicated articles as CSV."""
    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "published_at", "source", "language", "region",
            "title", "sentiment", "label", "confidence",
            "event_tags", "cluster_size", "url",
        ])
        for a in articles:
            tags = a.get("event_tags") or []
            if isinstance(tags, list):
                tags = ", ".join(tags)
            writer.writerow([
                a.get("published_at", ""),
                a.get("source", ""),
                a.get("language", ""),
                a.get("region", ""),
                a.get("title", ""),
                a.get("sentiment", 0),
                a.get("label", ""),
                a.get("confidence", 0),
                tags,
                a.get("cluster_size", 1),
                a.get("url", ""),
            ])
    print(f"  CSV exported: {CSV_OUTPUT} ({len(articles)} rows)")


def main():
    print("=" * 60)
    print("Re-score + Dedup Pipeline")
    print("=" * 60)

    # 1. Load
    data, articles = load_articles()
    print(f"\n[1/5] Loaded {len(articles)} articles")
    old_labels = Counter(a.get("label") for a in articles)
    print(f"  Before: {dict(old_labels)}")

    # 2. Re-score with updated lexicons
    scorer = SentimentScorer()
    stats = rescore(articles, scorer)
    new_labels = Counter(a.get("label") for a in articles)
    print(f"\n[2/5] Re-scored: {stats['rescored']} articles, {stats['label_changed']} label changes")
    print(f"  After:  {dict(new_labels)}")

    # 3. Dedup
    deduped, dedup_stats = run_dedup(articles)
    print(f"\n[3/5] Dedup: {dedup_stats['total_before']} → {dedup_stats['total_after']} articles")
    print(f"  Removed: {dedup_stats['removed']} duplicates in {dedup_stats['clusters_multi']} clusters")
    dedup_labels = Counter(a.get("label") for a in deduped)
    print(f"  Distribution: {dict(dedup_labels)}")

    # 4. Save articles JSON
    data["items"] = deduped
    data["generated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with ARTICLES_JSON.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\n[4/5] Saved articles.json ({len(deduped)} articles)")

    # 5. Rebuild indices
    rebuild_indices(deduped)
    print(f"  Rebuilt daily_index.json, monthly_index.json, by_entity.json")

    # 6. Export CSV
    export_csv(deduped)
    print(f"\n[5/5] Done!")


if __name__ == "__main__":
    main()
