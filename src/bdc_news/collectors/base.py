"""Base types for collectors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol


@dataclass
class CollectedItem:
    url: str
    title: str
    snippet: str
    source_name: str | None
    source_id: str | None
    published_at: datetime | None
    language: str | None = None


class Collector(Protocol):
    id: str

    def collect(self) -> Iterable[CollectedItem]: ...


USER_AGENT = (
    "bdc-news-monitor/0.1 (+https://github.com/bdc-news-monitor) "
    "offline research; respects robots.txt"
)

DEFAULT_TIMEOUT = 20.0
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*"}
