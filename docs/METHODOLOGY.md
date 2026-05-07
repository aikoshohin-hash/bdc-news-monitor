# BDC News Monitor — Sentiment Scoring Methodology

## Overview

This document describes the sentiment scoring pipeline used by the BDC / Private Credit News Monitor. All scoring is **fully offline** — no external API calls (including LLMs) are used. The system is deterministic and runs in milliseconds.

## Architecture

```
Article text
  │
  ├─ [Layer 1] Base Lexicon Scoring
  │    ├── English: Loughran-McDonald financial polarity dictionary
  │    └── Japanese: Hand-curated financial polarity dictionary + oseti
  │
  ├─ [Layer 2] Domain Override Phrases
  │    └── Phrase-level polarity (e.g., "cuts dividend" → negative)
  │
  └─ [Layer 3] BDC Domain Overlay
       └── Final-stage delta adjustments (config/sentiment_overrides_bdc.yaml)
```

## Scoring Formula

### Base Score Calculation

```
raw = (pos - effective_neg) / tokens
sentiment = tanh(raw × SCALE)
```

Where:
- `pos` = number of positive lexicon hits
- `neg` = number of negative lexicon hits
- `unc` = number of uncertainty lexicon hits
- `effective_neg = neg + unc × UNC_NEG_WEIGHT`
- `tokens` = word count (EN) or `len(text) // 2` (JA)
- `SCALE = 8.0` — controls sensitivity of the S-curve
- `UNC_NEG_WEIGHT = 0.5` — uncertainty words carry 50% negative bias

The `tanh` function produces a smooth S-curve in [-1.0, +1.0], avoiding the discrete jumps of simple ratio-based scoring.

### Label Assignment (Asymmetric Thresholds)

```python
if sentiment > 0.15:   → "positive"
if sentiment < -0.10:  → "negative"
else:                  → "neutral"
```

The negative threshold is lower (more sensitive) than positive because financial journalism phrases criticism indirectly — cautionary language should tip negative rather than stay neutral.

### Confidence Score

```
conf_density = total_polar_hits / tokens
confidence = min(1.0, conf_density × 10)
```

Articles with very few polar words get low confidence, signaling that the score may be unreliable.

## Layer 1: Base Lexicons

### English — Loughran-McDonald (Extended)

- **Source**: Loughran-McDonald Master Dictionary (Notre Dame SRAF), extended with BDC-specific terms
- **Entries**: ~1,471 words with polarity (positive / negative / uncertainty)
- **Negation handling**: 3-token lookback window for English negators (not, no, never, without, nor, neither, none)
- **File**: `lexicons/lm_financial_en.csv`

Key additions beyond standard L-M:
- Missing common negative words: cut, cuts, risk, risks, slump, sink, crash, dip, trouble, strain, peril, slash, trim, halve, erode, headwind, exodus, redemption, downgrade, bubble, opaque, illiquid, squeeze, etc.
- "despite" reclassified from positive → uncertainty (it appears in hedging headlines)

### Japanese — Custom Financial Polarity

- **Entries**: ~330+ words
- **Negation handling**: Suffix-based (ない, なし, ず, 無し, ぬ) with 4-character lookahead
- **Optional boost**: oseti library (sentence-level, blended 50/50 with lexicon counts)
- **File**: `lexicons/ja_financial_polarity.csv`

Key categories:
- Regulatory/oversight: 監視, 監視強化, 提言, 勧告, 要請, 是正, 精査, 厳格化, 実態調査, 実態把握
- Market stress: 冷ややか, 取り付け騒ぎ, 引き出し制限, 正念場, 苦渋, 緊張, 亀裂, 不穏, 揺れる, 揺らぐ
- Credit quality: 評価損, 含み損, デフォルト, 貸倒, 不良債権, 焦げ付き, 延滞
- Structural risk: 過熱, バブル, 膨張, 歪み, 脆弱, 流動性リスク, 利益相反

Design principle: **uncertainty terms (リスク, 不透明, 不確実) are classified as negative**, not uncertainty, because in financial journalism they consistently indicate negative tone.

## Layer 2: Domain Override Phrases

- **Entries**: ~400+ phrases
- **Mechanism**: Phrase-level matching (case-insensitive for EN, exact for JA)
- **Weight**: Each match adds 3 to the pos/neg hit count (stronger than single-word hits)
- **File**: `lexicons/domain_override.csv`

Examples:
| Phrase | Polarity | Lang |
|--------|----------|------|
| cuts dividend | negative | en |
| NAV decline | negative | en |
| 監視強化を提言 | negative | ja |
| 反応冷ややか | negative | ja |
| 取り付け騒ぎ | negative | ja |
| 本格参入 | positive | ja |
| 活況を呈する | positive | ja |

## Layer 3: BDC Domain Overlay

Applied as the **final stage** after Layers 1-2. Adds a delta to the base sentiment score (clamped to [-1.0, +1.0]).

- **File**: `config/sentiment_overrides_bdc.yaml`
- **Features**:
  - Context gating: Some rules only fire when specific context words also appear
  - Transparency: `sentiment_pre_bdc`, `bdc_override_delta`, and `bdc_overrides_applied` are stored alongside the final score

Examples:
| Pattern | Delta | Context Required | Rationale |
|---------|-------|------------------|-----------|
| amend and extend | -0.30 | — | Debt restructuring signal |
| placed on non-accrual | -0.50 | — | Explicit credit event |
| 監視強化 | -0.35 | — | Regulatory concern |
| 取り付け騒ぎ | -0.50 | — | Liquidity crisis |
| 提言 | -0.20 | FSB, 金融庁, 当局... | Regulatory recommendation |

## Deduplication

Near-duplicate articles are clustered using **character trigram Jaccard similarity**:

1. **Normalization**: Remove source suffixes ("- 奈良新聞", "(Bloomberg)" etc.)
2. **Trigrams**: Extract character-level 3-grams from normalized title
3. **Similarity**: Jaccard coefficient = |A ∩ B| / |A ∪ B|
4. **Threshold**: ≥ 0.45 within ±1 day → same news
5. **Clustering**: Union-Find algorithm groups transitively similar articles
6. **Representative selection**: Longest content + earliest date wins

Only cluster representatives appear in the dashboard. The `cluster_size` badge shows how many source articles were merged.

## Validation

### Expert Review Process

1. Downloaded all articles and manually reviewed a sample of 30+ articles
2. Identified systematic misclassifications (false positives, false neutrals)
3. Traced root causes through all 3 dictionary layers
4. Updated lexicons to fix identified gaps
5. Re-scored all articles and verified accuracy

### Known Limitations

- **Title-only scoring**: Many articles only have titles (no body text), so scoring relies on headline vocabulary
- **Short text sensitivity**: Very short titles may not contain enough polar words for reliable scoring
- **Context-free**: The lexicon approach cannot capture sarcasm, conditional statements, or complex argumentation
- **JP particle effects**: Japanese dedup uses character trigrams which are affected by particles (は, が, の, を) — threshold is set lower (0.45) to account for this

## Files Reference

| File | Description |
|------|-------------|
| `src/bdc_news/pipeline/sentiment.py` | Core scoring engine |
| `src/bdc_news/pipeline/bdc_overrides.py` | BDC overlay loader and applier |
| `src/bdc_news/pipeline/dedup.py` | Deduplication engine |
| `lexicons/lm_financial_en.csv` | English polarity dictionary |
| `lexicons/ja_financial_polarity.csv` | Japanese polarity dictionary |
| `lexicons/domain_override.csv` | Phrase-level overrides |
| `config/sentiment_overrides_bdc.yaml` | BDC domain overlay rules |
| `config/keywords.yaml` | Relevance keywords (MUST/SHOULD/EXCLUDE) |
| `scripts/rescore_and_dedup.py` | Batch re-scoring and dedup script |

## Change Log

| Date | Change |
|------|--------|
| 2026-05-07 | Major JP lexicon expansion: +70 words, +80 domain phrases, +30 BDC overlay rules. Dedup implemented. Distribution shift: positive 12.9%, neutral 45.2%, negative 41.9% |
| 2026-05-06 | Expert review and scoring overhaul: SCALE 6→8, UNC_NEG_WEIGHT 0.3→0.5, L-M dictionary +142 words, asymmetric thresholds |
| 2026-05-05 | Initial scoring system with L-M dictionary and basic JP lexicon |
