"""Alert rule evaluator — checks conditions against latest pipeline data."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from bdc_news.paths import CONFIG_DIR, DATA_DIR

log = logging.getLogger(__name__)

COOLDOWN_STATE_PATH = DATA_DIR / "alert_cooldowns.json"


@dataclass
class Alert:
    rule_id: str
    description: str
    severity: str
    ticker: str
    value: float
    message: str
    channels: list[str] = field(default_factory=list)


@dataclass
class RuleConfig:
    id: str
    description: str
    condition: str
    severity: str
    channels: list[str]
    threshold: float | None = None
    multiplier: float | None = None
    baseline_days: int = 30
    window_days: int = 1
    scope: str = "active_tickers"
    event_types: list[str] | None = None


def load_rules(path: Path | None = None) -> tuple[list[RuleConfig], int]:
    p = path or (CONFIG_DIR / "alert_rules.yaml")
    if not p.exists():
        return [], 24
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cooldown = raw.get("cooldown_hours", 24)
    rules = []
    for r in raw.get("rules", []):
        rules.append(RuleConfig(
            id=r["id"],
            description=r.get("description", ""),
            condition=r["condition"],
            severity=r.get("severity", "medium"),
            channels=r.get("channels", ["slack"]),
            threshold=r.get("threshold"),
            multiplier=r.get("multiplier"),
            baseline_days=r.get("baseline_days", 30),
            window_days=r.get("window_days", 1),
            scope=r.get("scope", "active_tickers"),
            event_types=r.get("event_types"),
        ))
    return rules, cooldown


def _load_cooldowns() -> dict[str, str]:
    if not COOLDOWN_STATE_PATH.exists():
        return {}
    try:
        with COOLDOWN_STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cooldowns(state: dict[str, str]) -> None:
    COOLDOWN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COOLDOWN_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f)


def _in_cooldown(rule_id: str, ticker: str, cooldown_hours: int, cooldowns: dict) -> bool:
    key = f"{rule_id}:{ticker}"
    last = cooldowns.get(key)
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last)
        return datetime.utcnow() - last_dt < timedelta(hours=cooldown_hours)
    except Exception:
        return False


def _mark_fired(rule_id: str, ticker: str, cooldowns: dict) -> None:
    cooldowns[f"{rule_id}:{ticker}"] = datetime.utcnow().isoformat()


def _active_tickers() -> list[str]:
    p = CONFIG_DIR / "tickers.yaml"
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return [t["symbol"] for t in raw.get("active_tickers", []) if t.get("group") == "bdc"]


def _load_daily_index() -> list[dict]:
    p = DATA_DIR / "export" / "daily_index.json"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except Exception:
        return []


def _load_articles() -> list[dict]:
    p = DATA_DIR / "export" / "articles.json"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except Exception:
        return []


def _load_entities() -> list[dict]:
    p = DATA_DIR / "export" / "by_entity.json"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except Exception:
        return []


def evaluate(rules_path: Path | None = None) -> list[Alert]:
    rules, cooldown_hours = load_rules(rules_path)
    if not rules:
        log.info("No alert rules configured")
        return []

    cooldowns = _load_cooldowns()
    tickers = _active_tickers()
    daily = _load_daily_index()
    articles = _load_articles()
    entities = _load_entities()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    alerts: list[Alert] = []

    for rule in rules:
        scope_tickers = tickers if rule.scope == "active_tickers" else tickers
        for ticker in scope_tickers:
            if _in_cooldown(rule.id, ticker, cooldown_hours, cooldowns):
                continue

            alert = _check_rule(rule, ticker, today, daily, articles, entities)
            if alert:
                _mark_fired(rule.id, ticker, cooldowns)
                alerts.append(alert)

    _save_cooldowns(cooldowns)
    log.info("Alert evaluation complete: %d alerts fired", len(alerts))
    return alerts


def _check_rule(
    rule: RuleConfig,
    ticker: str,
    today: str,
    daily: list[dict],
    articles: list[dict],
    entities: list[dict],
) -> Alert | None:
    if rule.condition == "sent_below":
        return _check_sent_threshold(rule, ticker, today, articles, below=True)
    if rule.condition == "sent_above":
        return _check_sent_threshold(rule, ticker, today, articles, below=False)
    if rule.condition == "article_spike":
        return _check_article_spike(rule, ticker, today, articles)
    if rule.condition == "event_match":
        return _check_event_match(rule, ticker, today, articles)
    if rule.condition in ("zscore_below", "zscore_above"):
        return _check_zscore(rule, ticker, today, articles, entities)
    return None


def _mentions_ticker(article: dict, ticker: str) -> bool:
    blob = f"{article.get('title', '')} {article.get('snippet', '')}".lower()
    return ticker.lower() in blob


def _check_sent_threshold(
    rule: RuleConfig, ticker: str, today: str, articles: list[dict], *, below: bool
) -> Alert | None:
    window_start = (datetime.utcnow() - timedelta(days=rule.window_days)).strftime("%Y-%m-%d")
    hits = [
        a for a in articles
        if _mentions_ticker(a, ticker)
        and a.get("sentiment") is not None
        and (a.get("published_at") or "")[:10] >= window_start
    ]
    if not hits:
        return None
    mean_sent = sum(a["sentiment"] for a in hits) / len(hits)
    threshold = rule.threshold or 0
    if below and mean_sent < threshold:
        return Alert(
            rule_id=rule.id, description=rule.description, severity=rule.severity,
            ticker=ticker, value=round(mean_sent, 4), channels=rule.channels,
            message=f"{ticker}: sentiment={mean_sent:.3f} < {threshold} ({len(hits)} articles, {rule.window_days}d)",
        )
    if not below and mean_sent > threshold:
        return Alert(
            rule_id=rule.id, description=rule.description, severity=rule.severity,
            ticker=ticker, value=round(mean_sent, 4), channels=rule.channels,
            message=f"{ticker}: sentiment={mean_sent:.3f} > {threshold} ({len(hits)} articles, {rule.window_days}d)",
        )
    return None


def _check_article_spike(
    rule: RuleConfig, ticker: str, today: str, articles: list[dict]
) -> Alert | None:
    window_start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    baseline_start = (datetime.utcnow() - timedelta(days=rule.baseline_days)).strftime("%Y-%m-%d")
    recent = [a for a in articles if _mentions_ticker(a, ticker) and (a.get("published_at") or "")[:10] >= window_start]
    baseline = [a for a in articles if _mentions_ticker(a, ticker) and baseline_start <= (a.get("published_at") or "")[:10] < window_start]
    if not baseline:
        return None
    days = max(1, rule.baseline_days - 1)
    daily_avg = len(baseline) / days
    if daily_avg <= 0:
        return None
    ratio = len(recent) / daily_avg
    multiplier = rule.multiplier or 3.0
    if ratio >= multiplier:
        return Alert(
            rule_id=rule.id, description=rule.description, severity=rule.severity,
            ticker=ticker, value=round(ratio, 2), channels=rule.channels,
            message=f"{ticker}: {len(recent)} articles today vs {daily_avg:.1f}/day avg ({ratio:.1f}×)",
        )
    return None


def _check_event_match(
    rule: RuleConfig, ticker: str, today: str, articles: list[dict]
) -> Alert | None:
    window_start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    event_types = set(rule.event_types or [])
    hits = [
        a for a in articles
        if _mentions_ticker(a, ticker)
        and (a.get("published_at") or "")[:10] >= window_start
        and event_types.intersection(a.get("event_tags") or [])
    ]
    if not hits:
        return None
    matched = event_types.intersection(t for a in hits for t in (a.get("event_tags") or []))
    return Alert(
        rule_id=rule.id, description=rule.description, severity=rule.severity,
        ticker=ticker, value=len(hits), channels=rule.channels,
        message=f"{ticker}: {len(hits)} articles with events {sorted(matched)}",
    )


def _check_zscore(
    rule: RuleConfig, ticker: str, today: str, articles: list[dict], entities: list[dict]
) -> Alert | None:
    window_start = (datetime.utcnow() - timedelta(days=rule.window_days)).strftime("%Y-%m-%d")
    bdc_tickers = [e["symbol"] for e in entities if e.get("n", 0) > 0]
    if ticker not in bdc_tickers or len(bdc_tickers) < 3:
        return None

    ticker_sents: dict[str, list[float]] = {t: [] for t in bdc_tickers}
    for a in articles:
        if a.get("sentiment") is None or not a.get("published_at"):
            continue
        if (a["published_at"] or "")[:10] < window_start:
            continue
        for t in bdc_tickers:
            if _mentions_ticker(a, t):
                ticker_sents[t].append(a["sentiment"])

    means = {}
    for t, vals in ticker_sents.items():
        if vals:
            means[t] = sum(vals) / len(vals)
    if ticker not in means or len(means) < 3:
        return None

    all_means = list(means.values())
    peer_mean = sum(all_means) / len(all_means)
    peer_std = math.sqrt(sum((v - peer_mean) ** 2 for v in all_means) / len(all_means)) or 1
    z = (means[ticker] - peer_mean) / peer_std
    threshold = rule.threshold or 0

    if rule.condition == "zscore_below" and z < threshold:
        return Alert(
            rule_id=rule.id, description=rule.description, severity=rule.severity,
            ticker=ticker, value=round(z, 3), channels=rule.channels,
            message=f"{ticker}: z-score={z:.2f} < {threshold} (peer mean={peer_mean:.3f})",
        )
    if rule.condition == "zscore_above" and z > threshold:
        return Alert(
            rule_id=rule.id, description=rule.description, severity=rule.severity,
            ticker=ticker, value=round(z, 3), channels=rule.channels,
            message=f"{ticker}: z-score={z:.2f} > {threshold} (peer mean={peer_mean:.3f})",
        )
    return None
