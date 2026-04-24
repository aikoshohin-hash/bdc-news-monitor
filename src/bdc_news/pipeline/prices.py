"""Price collection via yfinance (no API key)."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from bdc_news.paths import CONFIG_DIR
from bdc_news.storage.repo import upsert_price

log = logging.getLogger(__name__)


def _load_tickers() -> tuple[list[dict], str]:
    path = CONFIG_DIR / "tickers.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("active_tickers", []) or [], data.get("start_date", "2024-01-01")


def fetch_prices(start: str | None = None, end: str | None = None) -> int:
    """Download daily closes for all active tickers; upsert into SQLite.

    Returns number of (symbol, date) pairs written.
    """
    import yfinance as yf

    tickers, default_start = _load_tickers()
    if not tickers:
        return 0
    start = start or default_start
    written = 0
    for t in tickers:
        symbol = t["symbol"]
        log.info("yfinance fetch: %s", symbol)
        try:
            df = yf.download(
                symbol,
                start=start,
                end=end,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("yfinance failed for %s: %s", symbol, e)
            continue
        if df is None or df.empty:
            log.warning("yfinance empty for %s", symbol)
            continue
        # Handle multi-index columns that yfinance may return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.reset_index()
        date_col = "Date" if "Date" in df.columns else "index"
        for _, row in df.iterrows():
            d = row[date_col]
            if hasattr(d, "date"):
                d = d.date()
            close = float(row.get("Close", float("nan")))
            vol = float(row.get("Volume", 0.0)) if "Volume" in df.columns else None
            if pd.isna(close):
                continue
            upsert_price(symbol, d, close, vol)
            written += 1
    return written
