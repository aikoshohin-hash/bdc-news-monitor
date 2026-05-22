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
from datetime import datetime, timezone
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
        title = a.get("title", "") or ""
        snippet = a.get("snippet", "") or ""
        # Avoid double-counting when snippet ≈ title (common with RSS feeds)
        # Strip HTML entities and compare core text
        snip_clean = re.sub(r"&\w+;", "", snippet).strip()
        title_clean = re.sub(r"\s+", "", title)
        snip_core = re.sub(r"\s+", "", snip_clean)
        if snip_core and title_clean and (snip_core in title_clean or title_clean in snip_core):
            text = title  # snippet is redundant
        else:
            text = f"{title}\n{snippet}"
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


def filter_non_news(articles: list[dict]) -> tuple[list[dict], int]:
    """Remove non-news pages (fund info, stock quote pages, etc.)."""
    # Patterns that indicate non-news content
    non_news_patterns = [
        r"：基準価格",
        r"：組入銘柄",
        r"：チャート",
        r"：時系列",
        r"：分配金実績",
        r"：掲示板",
        r"：企業情報",
        r"：株価・株式",
        r"：株価チャート",
        r"【\d{7,}】",  # Fund codes like 【02311248】
        r"FastDraft Fantasy Promo",
        r"BDC.*Launches.*LIFT",  # Non-financial BDC
        r"BDC.*아크셀러레이터",  # Korean BDC accelerator
        r"BDC.*액셀러레이터",
        r"JFA直接融資",  # Football association lending
        r"日本公庫が中小の海外子会社に直接融資",
        r"東日本銀行.*直接融資",
        r"会員海外子会社に直接融資",
    ]
    compiled = [re.compile(p) for p in non_news_patterns]
    kept = []
    removed = 0
    for a in articles:
        title = a.get("title", "")
        if any(p.search(title) for p in compiled):
            removed += 1
        else:
            kept.append(a)
    return kept, removed


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
    """Rebuild daily_index.json, monthly_index.json, by_entity.json from deduped articles.

    IMPORTANT: output format must match what app.js expects:
      daily_index:   {"generated_at": "...", "items": [{"date", "region", "n_articles", "sent_mean", "sent_weighted", "pos_ratio", "neg_ratio", "heat_index"}]}
      monthly_index: {"generated_at": "...", "items": [{"month", "region", "n_articles", "sent_weighted", "pos_ratio", "neg_ratio"}]}
      by_entity:     {"generated_at": "...", "items": [{"symbol", "name", "n", "pos", "neg", "sent_mean", "by_month": [...]}]}
    """
    now = datetime.now(timezone.utc).isoformat()

    # ── daily index ──
    # Group by (date, region) — each article contributes to its own region AND "all"
    daily_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for a in articles:
        d = (a.get("published_at") or "")[:10]
        if not d:
            continue
        region = a.get("region", "global")
        daily_bucket[(d, region)].append(a)
        daily_bucket[(d, "all")].append(a)

    daily_items = []
    for (d, region), arts in sorted(daily_bucket.items()):
        sents = [a["sentiment"] for a in arts if a.get("sentiment") is not None]
        n = len(arts)
        if n == 0:
            continue
        n_pos = sum(1 for a in arts if a.get("label") == "positive")
        n_neg = sum(1 for a in arts if a.get("label") == "negative")
        sent_mean = round(sum(sents) / len(sents), 4) if sents else 0.0
        # sent_weighted: confidence-weighted mean
        w_sum = sum(a["sentiment"] * (a.get("confidence") or 0.5) for a in arts if a.get("sentiment") is not None)
        w_total = sum((a.get("confidence") or 0.5) for a in arts if a.get("sentiment") is not None)
        sent_weighted = round(w_sum / w_total, 4) if w_total > 0 else 0.0
        pos_ratio = round(n_pos / n, 4)
        neg_ratio = round(n_neg / n, 4)
        # heat_index: simple volume × abs(sentiment) signal
        heat_index = round(n * abs(sent_weighted), 4)
        daily_items.append({
            "date": d,
            "region": region,
            "n_articles": n,
            "sent_mean": sent_mean,
            "sent_weighted": sent_weighted,
            "pos_ratio": pos_ratio,
            "neg_ratio": neg_ratio,
            "heat_index": heat_index,
        })

    _write_json(DAILY_JSON, {"generated_at": now, "items": daily_items})

    # ── monthly index ──
    monthly_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for a in articles:
        m = (a.get("published_at") or "")[:7]
        if not m:
            continue
        region = a.get("region", "global")
        monthly_bucket[(m, region)].append(a)
        monthly_bucket[(m, "all")].append(a)

    monthly_items = []
    for (m, region), arts in sorted(monthly_bucket.items()):
        n = len(arts)
        if n == 0:
            continue
        n_pos = sum(1 for a in arts if a.get("label") == "positive")
        n_neg = sum(1 for a in arts if a.get("label") == "negative")
        w_sum = sum(a["sentiment"] * (a.get("confidence") or 0.5) for a in arts if a.get("sentiment") is not None)
        w_total = sum((a.get("confidence") or 0.5) for a in arts if a.get("sentiment") is not None)
        sent_weighted = round(w_sum / w_total, 4) if w_total > 0 else 0.0
        monthly_items.append({
            "month": m,
            "region": region,
            "n_articles": n,
            "sent_weighted": sent_weighted,
            "pos_ratio": round(n_pos / n, 4),
            "neg_ratio": round(n_neg / n, 4),
        })

    _write_json(MONTHLY_JSON, {"generated_at": now, "items": monthly_items})

    # ── by entity ──
    # Load ticker config if available, otherwise use hardcoded list
    ticker_map = _load_ticker_map()

    entity_counts: dict[str, dict] = {}
    for sym, name in ticker_map.items():
        entity_counts[sym] = {
            "symbol": sym, "name": name,
            "n": 0, "pos": 0, "neg": 0,
            "sent_sum": 0.0, "sent_n": 0,
            "by_month": defaultdict(lambda: {"n": 0, "sent_sum": 0.0, "sent_n": 0}),
        }

    for a in articles:
        blob = f"{a.get('title', '')} {a.get('snippet', '')}".upper()
        for sym in ticker_map:
            if sym in blob or ticker_map[sym].upper() in blob:
                c = entity_counts[sym]
                c["n"] += 1
                m = (a.get("published_at") or "")[:7]
                bm = c["by_month"][m or "unknown"]
                bm["n"] += 1
                sent = a.get("sentiment")
                conf = a.get("confidence", 0) or 0
                if sent is not None and conf > 0:
                    c["sent_sum"] += sent
                    c["sent_n"] += 1
                    bm["sent_sum"] += sent
                    bm["sent_n"] += 1
                    if sent > 0.2:
                        c["pos"] += 1
                    elif sent < -0.2:
                        c["neg"] += 1

    entity_items = []
    for sym, c in entity_counts.items():
        mean = round(c["sent_sum"] / c["sent_n"], 4) if c["sent_n"] else 0.0
        by_month = [
            {"month": m, "n": v["n"], "sent_mean": round(v["sent_sum"] / v["sent_n"], 4) if v["sent_n"] else 0.0}
            for m, v in sorted(c["by_month"].items())
        ]
        entity_items.append({
            "symbol": c["symbol"], "name": c["name"],
            "n": c["n"], "pos": c["pos"], "neg": c["neg"],
            "sent_mean": mean, "by_month": by_month,
        })
    entity_items.sort(key=lambda x: -x["n"])

    _write_json(ENTITY_JSON, {"generated_at": now, "items": entity_items})


def _write_json(path: Path, obj) -> None:
    """Write JSON with compact separators (matches to_static_json.py format)."""
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _load_ticker_map() -> dict[str, str]:
    """Load ticker→name map from config/tickers.yaml or fall back to hardcoded."""
    try:
        import yaml
        tickers_yaml = ROOT / "config" / "tickers.yaml"
        if tickers_yaml.exists():
            data = yaml.safe_load(tickers_yaml.read_text(encoding="utf-8")) or {}
            tickers = data.get("active_tickers", []) or []
            bdc = {t["symbol"]: t["name"] for t in tickers if t.get("group") == "bdc"}
            if bdc:
                return bdc
    except Exception:
        pass
    # Fallback: BIZD top 13
    return {
        "ARCC": "Ares Capital", "BXSL": "Blackstone Secured Lending",
        "OBDC": "Blue Owl Capital", "MAIN": "Main Street Capital",
        "HTGC": "Hercules Capital", "GBDC": "Golub Capital BDC",
        "GSBD": "Goldman Sachs BDC", "FSK": "FS KKR Capital",
        "OCSL": "Oaktree Specialty Lending", "ORCC": "Owl Rock Core Income",
        "TPVG": "TriplePoint Venture Growth", "PSEC": "Prospect Capital",
        "CCAP": "Crescent Capital BDC",
    }


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
    print(f"\n[1/6] Loaded {len(articles)} articles")
    old_labels = Counter(a.get("label") for a in articles)
    print(f"  Before: {dict(old_labels)}")

    # 2. Filter non-news pages
    articles, n_filtered = filter_non_news(articles)
    print(f"\n[2/6] Filtered {n_filtered} non-news pages → {len(articles)} articles")

    # 3. Re-score with updated lexicons
    scorer = SentimentScorer()
    stats = rescore(articles, scorer)
    new_labels = Counter(a.get("label") for a in articles)
    print(f"\n[3/6] Re-scored: {stats['rescored']} articles, {stats['label_changed']} label changes")
    print(f"  After:  {dict(new_labels)}")

    # 4. Dedup
    deduped, dedup_stats = run_dedup(articles)
    print(f"\n[4/6] Dedup: {dedup_stats['total_before']} → {dedup_stats['total_after']} articles")
    print(f"  Removed: {dedup_stats['removed']} duplicates in {dedup_stats['clusters_multi']} clusters")
    dedup_labels = Counter(a.get("label") for a in deduped)
    print(f"  Distribution: {dict(dedup_labels)}")
    total = len(deduped)
    for l in ['positive', 'neutral', 'negative']:
        n = dedup_labels.get(l, 0)
        print(f"    {l:10s}: {n:4d} ({n/total*100:.1f}%)")

    # 5. Save articles JSON
    data["items"] = deduped
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(ARTICLES_JSON, data)
    print(f"\n[5/6] Saved articles.json ({len(deduped)} articles)")

    # Rebuild indices
    rebuild_indices(deduped)
    print(f"  Rebuilt daily_index.json, monthly_index.json, by_entity.json")

    # 6. Export CSV
    export_csv(deduped)
    print(f"\n[6/6] Done!")


if __name__ == "__main__":
    main()
