"""Tests for the alert evaluator (Issue #6)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from bdc_news.alerts.evaluator import (
    Alert,
    RuleConfig,
    _check_sent_threshold,
    _check_article_spike,
    _check_event_match,
    _check_zscore,
    _mentions_ticker,
    load_rules,
)


TODAY = datetime.utcnow().strftime("%Y-%m-%d")
YESTERDAY = (datetime.utcnow() - timedelta(days=0.5)).strftime("%Y-%m-%dT12:00:00")


def _art(ticker: str, sentiment: float = 0.0, event_tags=None, pub=None):
    return {
        "title": f"{ticker} quarterly results",
        "snippet": f"Article about {ticker} BDC",
        "sentiment": sentiment,
        "published_at": pub or YESTERDAY,
        "event_tags": event_tags or [],
        "source": "test",
    }


def test_mentions_ticker():
    assert _mentions_ticker({"title": "ARCC earnings", "snippet": ""}, "ARCC")
    assert not _mentions_ticker({"title": "SPY rallied", "snippet": ""}, "ARCC")


def test_load_rules_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("rules: []\n")
    rules, cd = load_rules(p)
    assert rules == []
    assert cd == 24


def test_load_rules_parses(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.dump({
        "rules": [{
            "id": "test1",
            "condition": "sent_below",
            "threshold": -0.3,
            "severity": "high",
            "channels": ["slack"],
        }],
        "cooldown_hours": 12,
    }))
    rules, cd = load_rules(p)
    assert len(rules) == 1
    assert rules[0].threshold == -0.3
    assert cd == 12


class TestSentThreshold:
    def _rule(self, threshold=-0.4):
        return RuleConfig(
            id="neg", description="test", condition="sent_below",
            severity="high", channels=["slack"], threshold=threshold, window_days=1,
        )

    def test_fires_below(self):
        articles = [_art("ARCC", -0.6), _art("ARCC", -0.5)]
        alert = _check_sent_threshold(self._rule(), "ARCC", TODAY, articles, below=True)
        assert alert is not None
        assert alert.ticker == "ARCC"
        assert alert.value < -0.4

    def test_no_fire_above(self):
        articles = [_art("ARCC", 0.3)]
        alert = _check_sent_threshold(self._rule(), "ARCC", TODAY, articles, below=True)
        assert alert is None

    def test_no_articles(self):
        alert = _check_sent_threshold(self._rule(), "ARCC", TODAY, [], below=True)
        assert alert is None


class TestArticleSpike:
    def _rule(self):
        return RuleConfig(
            id="spike", description="test", condition="article_spike",
            severity="medium", channels=["slack"], multiplier=3.0, baseline_days=30,
        )

    def test_fires_on_spike(self):
        old = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%dT12:00:00")
        baseline = [_art("ARCC", pub=old) for _ in range(3)]
        recent = [_art("ARCC", pub=YESTERDAY) for _ in range(5)]
        alert = _check_article_spike(self._rule(), "ARCC", TODAY, baseline + recent)
        assert alert is not None

    def test_no_fire_normal_volume(self):
        old = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%dT12:00:00")
        baseline = [_art("ARCC", pub=old) for _ in range(29)]
        recent = [_art("ARCC", pub=YESTERDAY)]
        alert = _check_article_spike(self._rule(), "ARCC", TODAY, baseline + recent)
        assert alert is None


class TestEventMatch:
    def _rule(self):
        return RuleConfig(
            id="ev", description="test", condition="event_match",
            severity="medium", channels=["slack"], event_types=["earnings_results"],
        )

    def test_fires_on_match(self):
        articles = [_art("ARCC", event_tags=["earnings_results"])]
        alert = _check_event_match(self._rule(), "ARCC", TODAY, articles)
        assert alert is not None

    def test_no_fire_wrong_event(self):
        articles = [_art("ARCC", event_tags=["dividend_change"])]
        alert = _check_event_match(self._rule(), "ARCC", TODAY, articles)
        assert alert is None


class TestZscore:
    def _rule(self, condition="zscore_below", threshold=-2.0):
        return RuleConfig(
            id="z", description="test", condition=condition,
            severity="high", channels=["slack"], threshold=threshold, window_days=7,
        )

    def test_fires_low_zscore(self):
        articles = []
        peer_sents = {"ARCC": -0.9, "BXSL": 0.3, "FSK": 0.35, "MAIN": 0.5, "OBDC": 0.2, "HTGC": 0.45, "GBDC": 0.25}
        for t, s in peer_sents.items():
            articles.extend([_art(t, s) for _ in range(3)])
        entities = [{"symbol": t, "n": 3} for t in peer_sents]
        alert = _check_zscore(self._rule(), "ARCC", TODAY, articles, entities)
        assert alert is not None
        assert alert.value < -2.0

    def test_no_fire_normal(self):
        articles = []
        tickers = ["ARCC", "BXSL", "FSK", "MAIN", "OBDC"]
        for t in tickers:
            articles.extend([_art(t, 0.1) for _ in range(3)])
        entities = [{"symbol": t, "n": 3} for t in tickers]
        alert = _check_zscore(self._rule(), "ARCC", TODAY, articles, entities)
        assert alert is None
