"""Project path constants."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
LEXICON_DIR = ROOT / "lexicons"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"
LOGS_DIR = ROOT / "logs"

DB_PATH = DATA_DIR / "bdc_news.sqlite"

for p in (DATA_DIR, LOGS_DIR, DOCS_DATA_DIR):
    p.mkdir(parents=True, exist_ok=True)
