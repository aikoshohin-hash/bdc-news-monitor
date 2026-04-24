# BDC News Monitor

プライベートクレジット／BDC（Business Development Company）関連ニュースの**流量**と**ポジ・ネガ評価**を、国内外横断でモニタリングする静的 Web アプリです。

- **完全オフライン評価**: 外部 API を一切使用しません（Loughran–McDonald + 日本語極性辞書 + ドメイン語彙オーバーライド）
- **メタデータのみ**: 記事タイトル／スニペットのみを保持、全文は転載しません
- **静的サイト**: GitHub Pages + GitHub Actions cron で日次更新（月額コスト 0 円）
- **対象期間**: 2024-01-01 〜

---

## 🚀 Quick start

### ローカルで動かす

```bash
# 依存インストール
python -m pip install -e .
python -m pip install pytest  # テスト実行する場合

# ワンショット実行（収集 → 判別 → スコアリング → 株価 → エクスポート）
bdc-news run-all

# ブラウザで docs/index.html を開く（または python -m http.server 8000 --directory docs）
```

### GitHub Pages で公開する

1. **Public** リポジトリを作成して push
2. Settings → Pages → Source: `main` branch, folder: `/docs`
3. Settings → Actions → Workflow permissions: **Read and write**
4. 数分後に `https://<user>.github.io/<repo>/` でアクセス可能
5. `.github/workflows/daily.yml` が毎日 22:00 UTC（07:00 JST）に自動更新

詳しい初期設定は [TODO_CONFIRM.md](TODO_CONFIRM.md) を参照してください。

---

## 🧭 Architecture

```
┌────────────────────────┐
│  Collectors (offline)  │  Google News / RSS / GDELT / SEC EDGAR
└──────────┬─────────────┘
           │  metadata only (url, title, snippet, date, lang)
           ▼
┌────────────────────────┐
│   Classifier           │  MUST / SHOULD / EXCLUDE keyword gates (EN+JA)
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│   Sentiment Scorer     │  Loughran-McDonald + JA lex + phrase overrides
│   (fully offline)      │  Negation-aware, domain-aware
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐   ┌────────────────────┐
│   Aggregator           │   │   Price Fetcher    │  yfinance
│   daily / monthly      │   │   (12 BDCs + 3 bench) │
└──────────┬─────────────┘   └──────────┬─────────┘
           │                             │
           ▼                             ▼
┌──────────────────────────────────────────────┐
│   Static JSON export → docs/data/*.json      │
│   Plotly.js frontend → docs/index.html       │
└──────────────────────────────────────────────┘
```

---

## 📋 CLI reference

```bash
bdc-news collect              # Google News + RSS + GDELT + SEC EDGAR を収集
bdc-news classify             # 関連性判定（MUST/SHOULD/EXCLUDE）
bdc-news score                # 極性スコア計算
bdc-news prices               # yfinance から 12 BDC + 3 indices を取得
bdc-news export               # docs/data/*.json を更新
bdc-news run-all              # 上記すべてを順に実行
bdc-news update-lexicon-lm    # Loughran-McDonald 正式版辞書をダウンロードして置換
```

---

## 🧠 Methodology — Sentiment

### English
- **Base lexicon**: Loughran–McDonald Financial Sentiment Dictionary (positive / negative / uncertainty 列)
- **Negation window**: 直前 3 トークン以内に `not / no / never / without / nor / neither / none` があれば極性反転
- **Phrase override**: `lexicons/domain_override.csv` に「default rate rises」「NAV increase」等を±3加点

### Japanese
- **Base lexicon**: `lexicons/ja_financial_polarity.csv`（増配／減配／ノンアクルーアル等 ~132語）
- **Optional boost**: oseti + 日本語評価極性辞書（インストール時のみ有効化）
- **Negation**: 「〜ない／ず／なし／ぬ」接尾でフリップ
- **Phrase override**: 「スプレッドの拡大」「信用悪化」等

### Score formula
```
raw        = (pos_hits - neg_hits) / max(pos_hits + neg_hits, 1)
sentiment  = clamp(raw, -1.0, +1.0)
label      = positive  if sent > 0.2
             negative  if sent < -0.2
             neutral   otherwise
confidence = 0.0 if density < 0.01 else min(1.0, density * 10)
```

### 日次指標
```
heat_index     = log1p(n_articles) × |sent_weighted|
pos_ratio      = positive 記事数 / n_articles
sent_weighted  = Σ(sentiment × source_weight) / Σ(source_weight)
```

---

## 📊 Universe

**12 BDCs** (BIZD top constituents, 2026-04 snapshot):
ARCC, FSK, BXSL, OBDC, MAIN, HTGC, GBDC, BBDC, PSEC, TSLX, NMFC, CGBD

**Benchmarks**: BIZD, ^GSPC (S&P 500), HYG (iShares High Yield)

構成は四半期に一度見直し推奨（[TODO_CONFIRM.md](TODO_CONFIRM.md) §6 参照）。

---

## 📁 Repository layout

```
BDC NEWS/
├── SPEC.md                       # 仕様書 v1.1
├── TODO_CONFIRM.md               # ユーザー確認事項
├── pyproject.toml
├── config/
│   ├── keywords.yaml             # MUST / SHOULD / EXCLUDE
│   ├── sources.yaml              # RSS / Google News / GDELT / SEC EDGAR
│   ├── tickers.yaml              # 12 BDCs + benchmarks
│   └── weights.yaml              # Source credibility
├── lexicons/
│   ├── lm_financial_en.csv       # Loughran-McDonald (subset)
│   ├── ja_financial_polarity.csv # JP finance polarity
│   └── domain_override.csv       # Phrase-level rules
├── src/bdc_news/
│   ├── cli.py                    # Typer entry point
│   ├── collectors/               # google_news / rss / gdelt / sec_edgar
│   ├── pipeline/                 # normalizer / classifier / sentiment / aggregator / prices
│   ├── storage/                  # SQLAlchemy models + repo
│   └── export/                   # to_static_json.py
├── tests/                        # pytest suite (20 tests)
├── docs/                         # GitHub Pages root
│   ├── index.html
│   ├── assets/{style.css, app.js}
│   └── data/*.json               # Generated artifacts
└── .github/workflows/daily.yml   # Daily cron
```

---

## 📄 License & Attribution

- コード: MIT License を想定（`LICENSE` は後ほど追加ください）
- **Loughran–McDonald Dictionary**: Notre Dame SRAF, 非商用研究目的での使用を想定。商用利用される場合は原典ライセンスを再確認のこと
- **日本語評価極性辞書**（oseti 経由で使用）: 東工大 高村・乾研究室, 研究目的
- 記事メタデータ: 各メディアの著作物。本プロジェクトは**タイトル・スニペット・URL** のみ保持し、本文は再配布しません

---

## 🔗 Further reading

- [SPEC.md](SPEC.md) — 完全仕様（スコープ／キーワード／ソース／データモデル／配信方式）
- [TODO_CONFIRM.md](TODO_CONFIRM.md) — デプロイ前後のユーザー確認事項
