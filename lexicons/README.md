# Lexicons

Offline financial sentiment lexicons used by `bdc_news.pipeline.sentiment`.

## Files

| File | Language | Source / License |
|---|---|---|
| `lm_financial_en.csv` | English | Subset derived from **Loughran-McDonald Master Dictionary** (Notre Dame). Free for academic/commercial use with attribution. Full dictionary at https://sraf.nd.edu/loughranmcdonald-master-dictionary/ |
| `ja_financial_polarity.csv` | Japanese | Hand-curated finance-domain polarity table. Extend freely. |
| `domain_override.csv` | EN + JA | Phrase-level overrides that pin a final polarity regardless of lexicon counts (e.g., "default rate rises" → negative even if "rises" is positive). |

## Format

All files are UTF-8 CSV with header `word,polarity` (domain_override uses `phrase,polarity,lang`).
`polarity` is one of `positive`, `negative`, `uncertainty`.

## Updating to the full LM dictionary

1. Download `Loughran-McDonald_MasterDictionary_YYYY.csv` from Notre Dame SRAF
2. Place it in this folder
3. Run `python -m bdc_news.cli update-lexicon-lm --path lexicons/Loughran-McDonald_MasterDictionary_YYYY.csv`
   This rewrites `lm_financial_en.csv` with the full positive/negative/uncertainty word sets.

The initial subset here is ~400 words — enough for MVP but less granular than the ~5,000-word full dictionary.
