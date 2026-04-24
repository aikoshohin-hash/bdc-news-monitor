"""Fully offline sentiment scoring via financial polarity lexicons.

- English: Loughran-McDonald subset (lexicons/lm_financial_en.csv)
- Japanese: hand-curated finance polarity (lexicons/ja_financial_polarity.csv)
- Phrase-level overrides for both (lexicons/domain_override.csv)

No external API calls. Deterministic. Runs in milliseconds.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from bdc_news.paths import LEXICON_DIR

log = logging.getLogger(__name__)


@dataclass
class Score:
    sentiment: float  # -1.0 .. +1.0
    label: str  # positive / neutral / negative
    confidence: float  # 0.0 .. 1.0
    pos_hits: int
    neg_hits: int
    unc_hits: int
    override_applied: bool
    model: str


POS = {"positive"}
NEG = {"negative"}
UNC = {"uncertainty", "uncertain"}

_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-']+")
_NEGATORS_EN = {"not", "no", "never", "without", "nor", "neither", "none"}


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(r)
    return rows


class SentimentScorer:
    def __init__(self, lexicon_dir: Path | None = None):
        base = Path(lexicon_dir) if lexicon_dir else LEXICON_DIR
        self.en_lex: dict[str, str] = {}
        for row in _load_csv(base / "lm_financial_en.csv"):
            w = (row.get("word") or "").strip().lower()
            pol = (row.get("polarity") or "").strip().lower()
            if w and pol:
                self.en_lex[w] = pol
        self.ja_lex: dict[str, str] = {}
        for row in _load_csv(base / "ja_financial_polarity.csv"):
            w = (row.get("word") or "").strip()
            pol = (row.get("polarity") or "").strip().lower()
            if w and pol:
                self.ja_lex[w] = pol
        self.overrides: list[tuple[str, str, str]] = []  # (phrase, polarity, lang)
        for row in _load_csv(base / "domain_override.csv"):
            ph = (row.get("phrase") or "").strip()
            pol = (row.get("polarity") or "").strip().lower()
            lang = (row.get("lang") or "").strip().lower() or "en"
            if ph and pol:
                self.overrides.append((ph, pol, lang))
        # Try to import oseti for Japanese (optional; we have our own JP lexicon too)
        try:
            import oseti  # type: ignore
            self._oseti = oseti.Analyzer()
        except Exception:  # noqa: BLE001
            self._oseti = None
        log.info(
            "SentimentScorer loaded: EN=%d, JA=%d, overrides=%d, oseti=%s",
            len(self.en_lex),
            len(self.ja_lex),
            len(self.overrides),
            bool(self._oseti),
        )

    # ----------------------------------------------------------------- English

    def _score_en(self, text: str) -> Score:
        tokens = [t.lower() for t in _EN_TOKEN.findall(text or "")]
        pos = neg = unc = 0
        # Negation-aware scan over a sliding window of 3 tokens
        for i, tok in enumerate(tokens):
            pol = self.en_lex.get(tok)
            if pol is None:
                continue
            # Check 3 tokens to the left for a negator
            window = tokens[max(0, i - 3) : i]
            negated = any(w in _NEGATORS_EN for w in window)
            if pol in POS:
                if negated:
                    neg += 1
                else:
                    pos += 1
            elif pol in NEG:
                if negated:
                    pos += 1
                else:
                    neg += 1
            elif pol in UNC:
                unc += 1
        return self._to_score(text, tokens_n=len(tokens), pos=pos, neg=neg, unc=unc, model="lm-dict-v1")

    # ---------------------------------------------------------------- Japanese

    def _score_ja(self, text: str) -> Score:
        pos = neg = unc = 0
        for word, pol in self.ja_lex.items():
            # count non-overlapping occurrences
            n = text.count(word) if word else 0
            if n <= 0:
                continue
            # Simple negation for common JP patterns directly after the word
            # (e.g., "増加しない" → "増加" + "ない" → flip)
            flipped_n = 0
            idx = 0
            while True:
                idx = text.find(word, idx)
                if idx < 0:
                    break
                nxt = text[idx + len(word) : idx + len(word) + 4]
                if any(neg_suffix in nxt for neg_suffix in ("ない", "なし", "ず", "無し", "ぬ")):
                    flipped_n += 1
                idx += len(word)
            plain_n = n - flipped_n
            if pol == "positive":
                pos += plain_n
                neg += flipped_n
            elif pol == "negative":
                neg += plain_n
                pos += flipped_n
            else:
                unc += n

        # Optional boost from oseti (works token-wise at sentence level)
        if self._oseti is not None:
            try:
                scores = self._oseti.count_polarity(text) or []
                agg_pos = sum(s.get("positive", 0) for s in scores)
                agg_neg = sum(s.get("negative", 0) for s in scores)
                # Blend 50/50 with finance lexicon counts
                pos += agg_pos
                neg += agg_neg
            except Exception:  # noqa: BLE001
                pass

        # Token estimate for JP: approximate by character count / 2
        token_est = max(1, len(text) // 2)
        return self._to_score(text, tokens_n=token_est, pos=pos, neg=neg, unc=unc, model="ja-lex-v1")

    # ----------------------------------------------------------------- Combine

    def score(self, text: str, language: str | None = None) -> Score:
        text = text or ""
        lang = (language or "").lower()
        if lang.startswith("ja"):
            sc = self._score_ja(text)
        else:
            sc = self._score_en(text)

        # Apply phrase-level overrides on top
        text_low = text.lower()
        override_pos = override_neg = 0
        for phrase, pol, lg in self.overrides:
            if lg.startswith("ja"):
                if phrase in text:
                    if pol == "positive":
                        override_pos += 3
                    elif pol == "negative":
                        override_neg += 3
            else:
                if phrase.lower() in text_low:
                    if pol == "positive":
                        override_pos += 3
                    elif pol == "negative":
                        override_neg += 3
        if override_pos or override_neg:
            pos = sc.pos_hits + override_pos
            neg = sc.neg_hits + override_neg
            sc = self._to_score(
                text,
                tokens_n=max(1, _estimate_tokens(text, lang)),
                pos=pos,
                neg=neg,
                unc=sc.unc_hits,
                model=sc.model,
                override=True,
            )
        return sc

    # --------------------------------------------------------------- Internals

    @staticmethod
    def _to_score(
        text: str,
        *,
        tokens_n: int,
        pos: int,
        neg: int,
        unc: int,
        model: str,
        override: bool = False,
    ) -> Score:
        total_pol = pos + neg
        raw = (pos - neg) / total_pol if total_pol else 0.0
        sentiment = max(-1.0, min(1.0, raw))
        if total_pol == 0:
            label = "neutral"
        elif sentiment > 0.2:
            label = "positive"
        elif sentiment < -0.2:
            label = "negative"
        else:
            label = "neutral"
        conf_density = total_pol / max(tokens_n, 1)
        # Confidence penalty for very sparse hits
        confidence = 0.0 if conf_density < 0.01 else min(1.0, conf_density * 10)
        return Score(
            sentiment=round(sentiment, 4),
            label=label,
            confidence=round(confidence, 3),
            pos_hits=pos,
            neg_hits=neg,
            unc_hits=unc,
            override_applied=override,
            model=model,
        )


def _estimate_tokens(text: str, lang: str) -> int:
    if lang.startswith("ja"):
        return max(1, len(text) // 2)
    return len(_EN_TOKEN.findall(text or ""))
