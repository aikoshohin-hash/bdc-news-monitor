from __future__ import annotations

from bdc_news.pipeline.classifier import Classifier


def test_en_must_hit():
    clf = Classifier.from_yaml()
    ok, rule = clf.classify(
        "Ares Capital reports strong direct lending volumes",
        "The BDC deployed capital across middle market credits.",
        "en",
    )
    assert ok and rule == "must"


def test_exclude_drops():
    clf = Classifier.from_yaml()
    ok, rule = clf.classify(
        "British Dental Council announces new BDC guidance",
        "The dental council statement clarified registration rules.",
        "en",
    )
    assert not ok
    assert rule == "excluded"


def test_no_match():
    clf = Classifier.from_yaml()
    ok, rule = clf.classify("Tech stocks rally", "Semiconductors lifted the Nasdaq.", "en")
    assert not ok
    assert rule == "no_match"


def test_ja_must_hit():
    clf = Classifier.from_yaml()
    ok, rule = clf.classify(
        "プライベートクレジット市場の拡大続く",
        "国内投資家の関心が高まっている。",
        "ja",
    )
    assert ok and rule == "must"


def test_normalizer_imports():
    from bdc_news.pipeline.normalizer import canonical_url, detect_language, compute_hash
    assert canonical_url("https://www.example.com/a/?utm_source=x") == "https://example.com/a"
    assert detect_language("これはテストです") == "ja"
    assert len(compute_hash("a", "b")) == 16
