"""Fully offline sentiment scoring via financial polarity lexicons.

- English: Loughran-McDonald subset (lexicons/lm_financial_en.csv)
- Japanese: hand-curated finance polarity (lexicons/ja_financial_polarity.csv)
- Phrase-level overrides for both (lexicons/domain_override.csv)

No external API calls. Deterministic. Runs in milliseconds.

== P0 improvements (2026-05-07 expert panel feedback) ==
- Negation scope: expanded from 3-token lookback to 5-token with skip-
  articles, compound negators ("does not", "is not"), and contracted
  forms ("isn't", "don't", "won't").
- Direction-aware scoring: words like "down", "rise", "surge" are
  classified as *directional* rather than unconditionally polar.
  When preceded by a negative-polarity word (defaults, losses, risks),
  the direction is inverted (e.g., "defaults down" → positive).
- Confidence redesign: two-component (signal strength × decision
  margin) instead of raw polar density.
- JP: negation scope extended with broader suffix detection.
"""
from __future__ import annotations

import csv
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

from bdc_news.paths import LEXICON_DIR
from bdc_news.pipeline.bdc_overrides import BdcOverrideOverlay

log = logging.getLogger(__name__)


@dataclass
class Score:
    sentiment: float  # -1.0 .. +1.0 (after BDC overlay)
    label: str  # positive / neutral / negative
    confidence: float  # 0.0 .. 1.0
    pos_hits: int
    neg_hits: int
    unc_hits: int
    override_applied: bool
    model: str
    # Issue #4: BDC domain overlay — base score before adjustment, the
    # delta the overlay added, and which rules fired. Stored alongside
    # the final score for transparency and back-testing.
    sentiment_pre_bdc: float | None = None
    bdc_override_delta: float = 0.0
    bdc_overrides_applied: tuple[str, ...] = ()


POS = {"positive"}
NEG = {"negative"}
UNC = {"uncertainty", "uncertain"}

_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-']+")

# ── Negation handling (EN) ──────────────────────────────────────────
# Single-word negators
_NEGATORS_EN = {"not", "no", "never", "without", "nor", "neither", "none",
                "cannot", "can't", "isn't", "aren't", "wasn't", "weren't",
                "doesn't", "don't", "didn't", "won't", "wouldn't", "shouldn't",
                "couldn't", "hasn't", "haven't", "hadn't"}

# Auxiliary verbs that form compound negation with "not" (detected as pairs)
_AUX_BEFORE_NOT = {"does", "do", "did", "is", "are", "was", "were",
                    "has", "have", "had", "will", "would", "should", "could"}

# Articles/determiners/prepositions to skip when counting negation distance
_SKIP_TOKENS = {"a", "an", "the", "any", "its", "their", "our", "his", "her",
                "of", "in", "for", "to", "as", "at", "by", "on", "with", "from"}

# Negation scope: up to this many *content* tokens (skipping articles)
_NEG_WINDOW = 5

# ── Direction-aware words ───────────────────────────────────────────
# These words' polarity depends on what they modify:
#   "earnings rise" = positive (good thing going up)
#   "defaults rise" = negative (bad thing going up)
#   "defaults down" = positive (bad thing going down)
#   "shares down"   = negative (good thing going down)
_DIRECTION_UP = {"rise", "rises", "rising", "rose", "surge", "surges",
                 "surged", "surging", "jump", "jumped", "jumping", "jumps",
                 "soar", "soared", "soaring", "spike", "spiked", "spiking",
                 "climb", "climbed", "climbing", "increase", "increased",
                 "increasing", "up", "higher", "high", "record"}
_DIRECTION_DOWN = {"down", "fall", "falls", "falling", "fell",
                   "decline", "declined", "declining", "declines",
                   "drop", "dropped", "dropping", "drops",
                   "sink", "sinks", "sinking", "sank", "sunk",
                   "lower", "low", "dip", "dipped", "dipping"}

# Words whose meaning determines how direction words are interpreted:
# If a "bad" word precedes a direction word, the direction flips
_BAD_SUBJECTS = {"default", "defaults", "loss", "losses", "deficit", "deficits",
                 "risk", "risks", "cost", "costs", "debt", "delinquency",
                 "delinquencies", "non-accrual", "nonaccrual", "non-accruals",
                 "nonaccruals", "failure", "failures", "bankruptcy",
                 "bankruptcies", "charge-off", "charge-offs", "writedown",
                 "writedowns", "write-down", "write-downs", "impairment",
                 "impairments", "outflows", "redemptions", "volatility",
                 "spread", "spreads", "vacancy", "vacancies", "unemployment",
                 "inflation", "leverage"}

_GOOD_SUBJECTS = {"earnings", "revenue", "profit", "profits", "income",
                  "dividend", "dividends", "nav", "coverage", "aum",
                  "deployment", "origination", "originations", "yield",
                  "recovery", "book", "shares", "stock", "price", "prices",
                  "value", "values", "return", "returns", "margin", "margins",
                  "growth", "asset", "assets", "inflows"}


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
        # Track which words are directional (loaded from lexicon but
        # handled via context-aware logic, not simple polar counting)
        self._direction_up_lex: set[str] = set()
        self._direction_down_lex: set[str] = set()
        for row in _load_csv(base / "lm_financial_en.csv"):
            w = (row.get("word") or "").strip().lower()
            pol = (row.get("polarity") or "").strip().lower()
            if w and pol:
                # Classify direction-ambiguous words separately
                if w in _DIRECTION_UP:
                    self._direction_up_lex.add(w)
                elif w in _DIRECTION_DOWN:
                    self._direction_down_lex.add(w)
                else:
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
        # Issue #4: BDC domain overlay (final-stage polarity adjustment)
        self.bdc_overlay = BdcOverrideOverlay.from_yaml()
        log.info(
            "SentimentScorer loaded: EN=%d (+%d dir_up, +%d dir_down), "
            "JA=%d, overrides=%d, oseti=%s, bdc_overlay=%d",
            len(self.en_lex),
            len(self._direction_up_lex),
            len(self._direction_down_lex),
            len(self.ja_lex),
            len(self.overrides),
            bool(self._oseti),
            len(self.bdc_overlay.rules),
        )

    # ----------------------------------------------------------------- English

    def _score_en(self, text: str) -> Score:
        tokens = [t.lower() for t in _EN_TOKEN.findall(text or "")]
        pos = neg = unc = 0

        # ── Pass 1: Direction-aware scoring ──
        # For direction words (up/down/rise/fall/surge etc.), determine
        # polarity from the subject they modify (look back for context).
        for i, tok in enumerate(tokens):
            is_dir_up = tok in self._direction_up_lex
            is_dir_down = tok in self._direction_down_lex
            if is_dir_up or is_dir_down:
                # Look backward up to 4 tokens for subject context
                context_tokens = tokens[max(0, i - 4) : i]
                context_set = set(context_tokens)

                # Check: is negated?
                negated = self._is_negated_en(tokens, i)

                has_bad_subject = bool(context_set & _BAD_SUBJECTS)
                has_good_subject = bool(context_set & _GOOD_SUBJECTS)

                if has_bad_subject and not has_good_subject:
                    # Bad thing going up = negative; bad thing going down = positive
                    if is_dir_up:
                        if negated:
                            pos += 1
                        else:
                            neg += 1
                    else:  # dir_down
                        if negated:
                            neg += 1
                        else:
                            pos += 1
                elif has_good_subject and not has_bad_subject:
                    # Good thing going up = positive; good thing going down = negative
                    if is_dir_up:
                        if negated:
                            neg += 1
                        else:
                            pos += 1
                    else:  # dir_down
                        if negated:
                            pos += 1
                        else:
                            neg += 1
                else:
                    # Ambiguous context — use default polarity
                    # Direction-up words default to positive, down to negative
                    if is_dir_up:
                        if negated:
                            neg += 1
                        else:
                            pos += 1
                    else:
                        if negated:
                            pos += 1
                        else:
                            neg += 1
                continue  # don't re-process in pass 2

        # ── Pass 2: Standard lexicon scoring with improved negation ──
        for i, tok in enumerate(tokens):
            # Skip direction words (already handled in pass 1)
            if tok in self._direction_up_lex or tok in self._direction_down_lex:
                continue

            pol = self.en_lex.get(tok)
            if pol is None:
                continue

            negated = self._is_negated_en(tokens, i)

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

        return self._to_score(text, tokens_n=len(tokens), pos=pos, neg=neg, unc=unc, model="lm-dict-v2")

    @staticmethod
    def _is_negated_en(tokens: list[str], idx: int) -> bool:
        """Check if token at `idx` is within negation scope.

        Improvements over the original 3-token window:
        1. Window expanded to 5 content tokens (articles/determiners skipped)
        2. Compound negators: "does not", "is not", "has not" detected
        3. Contracted negators: "isn't", "don't", "won't" etc.
        """
        # Scan backward up to _NEG_WINDOW content tokens
        content_distance = 0
        j = idx - 1
        while j >= 0 and content_distance < _NEG_WINDOW:
            w = tokens[j]
            if w in _SKIP_TOKENS:
                j -= 1
                continue  # don't count articles toward distance
            if w in _NEGATORS_EN:
                return True
            if w == "not":
                return True
            # Check for compound negation: "does/is/has" + "not"
            if w in _AUX_BEFORE_NOT and j + 1 < len(tokens) and tokens[j + 1] == "not":
                return True
            content_distance += 1
            j -= 1
        return False

    # ---------------------------------------------------------------- Japanese

    def _score_ja(self, text: str) -> Score:
        pos = neg = unc = 0

        # Japanese negation suffixes — extended set
        _JP_NEG_SUFFIXES = ("ない", "なし", "ず", "無し", "ぬ", "ません",
                            "せず", "ずに", "なく", "なかった")
        _JP_NEG_LOOKAHEAD = max(len(s) for s in _JP_NEG_SUFFIXES) + 2  # chars

        for word, pol in self.ja_lex.items():
            # count non-overlapping occurrences
            n = text.count(word) if word else 0
            if n <= 0:
                continue
            # Negation detection: check for negation suffix after the word
            flipped_n = 0
            idx = 0
            while True:
                idx = text.find(word, idx)
                if idx < 0:
                    break
                nxt = text[idx + len(word) : idx + len(word) + _JP_NEG_LOOKAHEAD]
                if any(neg_suffix in nxt for neg_suffix in _JP_NEG_SUFFIXES):
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
        return self._to_score(text, tokens_n=token_est, pos=pos, neg=neg, unc=unc, model="ja-lex-v2")

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

        # Issue #4: BDC domain overlay (final-stage polarity adjustment).
        overlay = self.bdc_overlay.apply(sc.sentiment, text, language=lang)
        if overlay.fired:
            sc = Score(
                sentiment=overlay.new_sentiment,
                label=_label_for(overlay.new_sentiment, sc.pos_hits + sc.neg_hits),
                confidence=sc.confidence,
                pos_hits=sc.pos_hits,
                neg_hits=sc.neg_hits,
                unc_hits=sc.unc_hits,
                override_applied=sc.override_applied,
                model=sc.model + "+bdc",
                sentiment_pre_bdc=sc.sentiment,
                bdc_override_delta=overlay.delta,
                bdc_overrides_applied=tuple(overlay.fired),
            )
        else:
            sc.sentiment_pre_bdc = sc.sentiment
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
        # --- tanh-smoothed scoring ---
        SCALE = 8.0
        # Uncertainty words carry negative bias (0.5× each)
        UNC_NEG_WEIGHT = 0.5
        effective_neg = neg + unc * UNC_NEG_WEIGHT
        total_pol = pos + neg + unc
        if total_pol == 0:
            sentiment = 0.0
        else:
            raw = (pos - effective_neg) / max(tokens_n, 1)
            sentiment = math.tanh(raw * SCALE)
        label = _label_for(sentiment, total_pol)

        # ── Confidence: signal strength × decision clarity ──
        # Component 1: Signal density (do we have enough polar words?)
        if total_pol == 0:
            conf_signal = 0.0
        else:
            conf_signal = min(1.0, total_pol / max(tokens_n, 1) * 8)

        # Component 2: Decision margin (how clearly does score fall
        # into its label? Higher when far from label boundary.)
        if label == "positive":
            # Distance from positive threshold (0.15) to max (1.0)
            conf_margin = min(1.0, max(0.0, (sentiment - 0.15) / 0.85))
        elif label == "negative":
            # Distance from negative threshold (-0.10) to min (-1.0)
            conf_margin = min(1.0, max(0.0, (-0.10 - sentiment) / 0.90))
        else:
            # For neutral: confident when close to center, less at edges
            if total_pol == 0:
                conf_margin = 0.5  # No signal → moderate (we just don't know)
            else:
                # Balanced polar words → genuinely neutral → higher margin
                conf_margin = max(0.0, 1.0 - abs(sentiment) / 0.15)

        confidence = conf_signal * (0.3 + 0.7 * conf_margin)

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


def _label_for(sentiment: float, total_hits: int) -> str:
    if total_hits == 0 and abs(sentiment) <= 0.001:
        return "neutral"
    # Asymmetric thresholds: lower bar for negative to catch
    # cautionary / critical tone that raw scoring tends to under-weight.
    if sentiment > 0.15:
        return "positive"
    if sentiment < -0.10:
        return "negative"
    return "neutral"
