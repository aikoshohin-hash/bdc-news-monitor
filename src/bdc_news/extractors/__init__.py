"""Event / metric extractors over collected articles (Issue #1+)."""
from bdc_news.extractors.event_tagger import EventTagger, TagResult
from bdc_news.extractors.edgar_client import EdgarClient
from bdc_news.extractors.edgar_metrics import EdgarMetricsExtractor, QuarterlyMetric

__all__ = [
    "EventTagger",
    "TagResult",
    "EdgarClient",
    "EdgarMetricsExtractor",
    "QuarterlyMetric",
]
