"""Typer CLI entrypoint.

Typical daily usage:

    bdc-news collect
    bdc-news classify
    bdc-news score
    bdc-news prices
    bdc-news export

Or all in one:

    bdc-news run-all
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
import yaml

from bdc_news.paths import CONFIG_DIR, LOGS_DIR
from bdc_news.storage.models import init_db
from bdc_news.storage import repo

app = typer.Typer(add_completion=False, help="BDC NEWS pipeline CLI (offline, no API)")


def _setup_logging() -> None:
    log_path = LOGS_DIR / "bdc_news.log"
    fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
    )


def _load_sources_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8")) or {}


@app.command()
def collect(
    google: bool = typer.Option(True, help="Enable Google News RSS"),
    rss: bool = typer.Option(True, help="Enable plain RSS feeds"),
    gdelt: bool = typer.Option(True, help="Enable GDELT DOC API"),
    sec: bool = typer.Option(True, help="Enable SEC EDGAR full-text search"),
) -> None:
    """Fetch new items from configured sources and upsert into SQLite."""
    _setup_logging()
    init_db()
    from bdc_news.collectors import (
        GoogleNewsCollector,
        RSSCollector,
        GdeltCollector,
        SecEdgarCollector,
    )
    from bdc_news.pipeline.normalizer import canonical_url, detect_language, compute_hash

    cfg = _load_sources_config()
    n_new = n_seen = 0
    sources = []
    if google:
        gn_cfg = cfg.get("google_news", {}) or {}
        sources.append(
            GoogleNewsCollector(
                queries_en=gn_cfg.get("queries_en", []) or [],
                queries_ja=gn_cfg.get("queries_ja", []) or [],
            )
        )
    if rss:
        feeds = cfg.get("rss", []) or []
        if feeds:
            sources.append(RSSCollector(feeds=feeds))
    if gdelt:
        gd_cfg = cfg.get("gdelt", {}) or {}
        if gd_cfg.get("enabled"):
            sources.append(
                GdeltCollector(
                    queries=gd_cfg.get("queries", []) or [],
                    maxrecords=int(gd_cfg.get("maxrecords", 100)),
                    timespan=str(gd_cfg.get("timespan", "24h")),
                )
            )
    if sec:
        sec_cfg = cfg.get("sec_edgar", {}) or {}
        if sec_cfg.get("enabled"):
            sources.append(SecEdgarCollector(forms=sec_cfg.get("forms")))

    for c in sources:
        for item in c.collect():
            url = canonical_url(item.url)
            if not url:
                continue
            lang = item.language or detect_language(f"{item.title} {item.snippet}")
            chash = compute_hash(item.title, item.snippet[:200] if item.snippet else "")
            _, created = repo.upsert_article(
                url_canonical=url,
                title=item.title or "",
                snippet=item.snippet or "",
                source_name=item.source_name,
                source_id=item.source_id,
                language=lang,
                published_at=item.published_at,
                content_hash=chash,
            )
            if created:
                n_new += 1
            else:
                n_seen += 1
    typer.echo(f"collect done: {n_new} new, {n_seen} existing")


@app.command()
def classify(batch: int = typer.Option(0, help="Max rows to classify; 0 = all")) -> None:
    """Run relevance classifier on all unclassified articles."""
    _setup_logging()
    init_db()
    from bdc_news.pipeline.classifier import Classifier
    clf = Classifier.from_yaml()
    todo = repo.iter_unclassified_articles(limit=batch or None)
    total = 0
    relevant = 0
    for art in todo:
        is_rel, rule = clf.classify(art.title or "", art.snippet or "", art.language)
        repo.mark_relevance(art.id, is_rel, rule)
        total += 1
        if is_rel:
            relevant += 1
    typer.echo(f"classify done: total={total} relevant={relevant}")


@app.command()
def score(batch: int = typer.Option(0, help="Max rows to score; 0 = all")) -> None:
    """Run offline sentiment scorer on relevant articles that lack a score."""
    _setup_logging()
    init_db()
    from bdc_news.pipeline.sentiment import SentimentScorer
    scorer = SentimentScorer()
    todo = repo.iter_unscored_relevant_articles(limit=batch or None)
    scored = 0
    for art in todo:
        text = f"{art.title or ''}\n{art.snippet or ''}"
        sc = scorer.score(text, language=art.language)
        repo.save_score(
            article_id=art.id,
            sentiment=sc.sentiment,
            label=sc.label,
            confidence=sc.confidence,
            model=sc.model + ("+override" if sc.override_applied else ""),
            pos_hits=sc.pos_hits,
            neg_hits=sc.neg_hits,
        )
        scored += 1
    typer.echo(f"score done: {scored} articles scored")


@app.command("tag-events")
def tag_events(
    batch: int = typer.Option(0, help="Max rows to process; 0 = all"),
    retag_all: bool = typer.Option(False, help="Re-tag every relevant article (ignore existing tags)"),
) -> None:
    """Apply BDC event taxonomy tags (Issue #1) to relevant articles."""
    _setup_logging()
    init_db()
    from bdc_news.extractors import EventTagger
    tagger = EventTagger.from_yaml()
    todo = repo.iter_relevant_articles_for_tagging(
        limit=batch or None, only_untagged=not retag_all
    )
    n_tagged = 0
    n_with_tags = 0
    for art in todo:
        result = tagger.tag(art.title or "", art.snippet or "")
        repo.save_event_tags(
            article_id=art.id,
            tags=result.tags,
            sub_tags=result.sub_tags,
            severity=result.severity,
            confidence=result.confidence,
        )
        n_tagged += 1
        if result.tags:
            n_with_tags += 1
    typer.echo(f"tag-events done: processed={n_tagged} with_tags={n_with_tags}")


@app.command("edgar-metrics")
def edgar_metrics(
    ticker: str = typer.Option(None, help="Single ticker (default: all in config/edgar_ciks.yaml)"),
    max_periods: int = typer.Option(12, help="Max recent periods per ticker (8 quarters + 2 FY = 10)"),
    offline: bool = typer.Option(False, help="Use only cached data (no network)"),
) -> None:
    """Issue #2: extract quarterly metrics from SEC EDGAR XBRL companyfacts.

    Pulls structured financial concepts (NAV/share, total investments at FV,
    NII/share, distributions, asset coverage) from the free companyfacts
    API and upserts ``bdc_quarterly_metrics`` rows. Failures per-ticker are
    logged and skipped — pipeline keeps going (per spec).
    """
    _setup_logging()
    init_db()
    from bdc_news.extractors import EdgarClient, EdgarMetricsExtractor
    extractor = EdgarMetricsExtractor(client=EdgarClient(offline=offline))
    tickers: list[str]
    if ticker:
        tickers = [ticker]
    else:
        tickers = list(extractor.cik_map.keys())
    n_total = 0
    n_failed = 0
    for t in tickers:
        try:
            records = extractor.extract_for_ticker(t, max_periods=max_periods)
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning("edgar-metrics %s failed: %s", t, e)
            n_failed += 1
            continue
        for rec in records:
            repo.upsert_quarterly_metric(rec.to_db_kwargs())
        n_total += len(records)
    typer.echo(
        f"edgar-metrics done: tickers={len(tickers)} rows={n_total} failed={n_failed}"
    )


@app.command()
def prices(start: str = typer.Option(None, help="YYYY-MM-DD; defaults to config")) -> None:
    """Fetch daily close prices for configured tickers via yfinance."""
    _setup_logging()
    init_db()
    from bdc_news.pipeline.prices import fetch_prices
    n = fetch_prices(start=start)
    typer.echo(f"prices done: {n} rows written")


@app.command()
def export() -> None:
    """Write docs/data/*.json for the static dashboard."""
    _setup_logging()
    init_db()
    from bdc_news.export import export_all
    stats = export_all()
    typer.echo(f"export done: {stats}")


@app.command("run-all")
def run_all() -> None:
    """Collect → classify → score → tag-events → edgar-metrics → prices → export."""
    collect()
    classify()
    score()
    tag_events()
    edgar_metrics()
    prices()
    export()


@app.command("update-lexicon-lm")
def update_lexicon_lm(path: str = typer.Argument(..., help="Path to official LM master dictionary CSV")) -> None:
    """Rebuild lexicons/lm_financial_en.csv from the official Loughran-McDonald file."""
    import csv
    from bdc_news.paths import LEXICON_DIR
    src = Path(path)
    if not src.exists():
        typer.echo(f"not found: {src}")
        raise typer.Exit(code=1)
    out_rows: list[tuple[str, str]] = []
    with src.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            w = (row.get("Word") or "").strip().lower()
            if not w:
                continue
            if int(row.get("Positive") or 0) > 0:
                out_rows.append((w, "positive"))
            elif int(row.get("Negative") or 0) > 0:
                out_rows.append((w, "negative"))
            elif int(row.get("Uncertainty") or 0) > 0:
                out_rows.append((w, "uncertainty"))
    target = LEXICON_DIR / "lm_financial_en.csv"
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["word", "polarity"])
        writer.writerows(out_rows)
    typer.echo(f"wrote {len(out_rows)} rows to {target}")


if __name__ == "__main__":
    app()
