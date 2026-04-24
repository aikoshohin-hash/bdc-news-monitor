# プライベートクレジット／BDC ニュースフロー監視・センチメント評価システム 仕様書

- バージョン: v1.1
- 作成日: 2026-04-24
- ステータス: 確定（実装着手可、未決事項ゼロ）

---

## 0. 決定事項サマリ（v1.1 で確定した方針）

| # | 項目 | 決定内容 |
|---|---|---|
| 1 | 本文取得 | **メタデータのみ**（タイトル・リード／スニペット・媒体・公開日・URL）。本文はユーザーがブラウザで原典に遷移して閲覧 |
| 2 | センチメント評価 | **外部 API は一切使用しない**。ローカルの金融特化極性辞書（英語: **Loughran-McDonald**、日本語: **oseti ／金融極性辞書**）で完全オフライン評価。GitHub Actions 上で数秒で完了、ランニングコストはゼロ |
| 3 | 配信形態 | **GitHub Pages の静的 Web アプリ（Public リポジトリ）**。ローカル Python パイプラインが集計結果を JSON で生成し、Git にコミット／GitHub Actions でスケジュール更新（毎日 22:00 UTC / 07:00 JST）。カスタムドメインなし |
| 4 | データ期間 | **2024-01-01〜現在（ローリング）**。件数推移・ポジ／ネガ比率推移に加え、**BDC インデックス（BIZD）構成上位 12 社**＋ベンチマーク指数を同一ダッシュボード上に重ねて可視化 |

---

## 1. 目的・ゴール

プライベートクレジット（Private Credit / Private Debt / Direct Lending）および BDC（Business Development Company）に関する国内外のニュース・情報フローを継続的に監視し、以下 3 点を静的 Web ダッシュボードで提供する。

1. **フロー量の可視化**: 日次／週次／月次の記事件数トレンド
2. **センチメントの可視化**: ポジ／ネガ比率、日次センチメント指数の推移
3. **市場との相関可視化**: 主要 BDC 株価・関連インデックスとの重ね描き

---

## 2. スコープ

### 2.1 対象テーマ（キーワード群）

`config/keywords.yaml` に MUST / SHOULD / EXCLUDE の 3 層で管理。

| カテゴリ | 英語（例） | 日本語（例） |
|---|---|---|
| アセットクラス | private credit, private debt, direct lending, middle market lending, leveraged loan, broadly syndicated loan, CLO, senior secured | プライベートクレジット、プライベートデット、ダイレクトレンディング、直接融資、ミドルマーケット |
| ビークル | BDC, business development company, non-traded BDC, perpetual BDC, interval fund | BDC、ビジネス・デベロップメント・カンパニー |
| 主要運用者／BDC（12 社＋周辺） | Ares (ARCC), FS KKR (FSK), Blackstone (BXSL/BCRED), Blue Owl (OBDC/OBDE), Main Street (MAIN), Hercules (HTGC), Golub (GBDC), Barings (BBDC), Prospect (PSEC), Sixth Street (TSLX), New Mountain (NMFC), Carlyle Secured Lending (CGBD)、加えて非構成の Apollo / Oaktree (OCSL) / HPS / Antares / Owl Rock | 各社の日本語表記 |
| 市場・信用指標 | non-accrual, PIK income, NAV discount, default rate, recovery rate, covenant-lite, dividend coverage, spread widening | デフォルト率、NAV、配当カバレッジ、スプレッド |
| 規制・政策 | 1940 Act, SEC rule, Basel III endgame, interval fund | 金融庁、規制、バーゼル |

### 2.2 地理

- **国内（日本語）**: 日経電子版、ロイター日本、Bloomberg 日本版、QUICK、ダイヤモンド、東洋経済、金融庁プレス、主要運用会社の日本法人 IR
- **海外（英語中心）**: Google News / GDELT 経由で Bloomberg, Reuters, FT, WSJ, Barron's, S&P Global, Moody's, Fitch, Private Debt Investor, Creditflux, 9fin, Debtwire, PitchBook, SEC EDGAR
- **第二段階**: 中国語・独語等への拡張余地を残す

### 2.3 期間

- **収集開始**: 2024-01-01
- **更新**: 日次（GitHub Actions）もしくはローカル手動実行
- **保持**: 全期間保持（JSON 圧縮）

### 2.4 対象外

- 無関係な "BDC" 略語（別用途の略称）
- コンシューマー与信（BNPL 等）
- 個別株の投資助言的記事は保持するが、ダッシュボード上は「運用者別」タブに限定表示

---

## 3. 主要ユースケース／KPI

### 3.1 ダッシュボード画面で達成したいこと

- U1: 2024 年以降の「プライベートクレジット／BDC 話題量」の月次・週次トレンドを一瞥で把握
- U2: 同期間のポジ／ネガ比率とセンチメント指数を確認
- U3: 主要 BDC（ARCC, BXSL, OBDC, FSK, MAIN, BIZD ETF）の株価・インデックスとニュースフローを重ねて相関を目視確認
- U4: 急増日・センチメント急変日を識別し、当日の記事一覧（タイトル＋媒体＋原典リンク）に辿れる
- U5: 運用者別／地域別（JP vs Global）のドリルダウン

### 3.2 パイプライン KPI

| 指標 | 目標（MVP） | 目標（v1.0） |
|---|---|---|
| 日次収集記事数（重複排除後） | 50–200 | 200–600 |
| 関連性判定 Precision | ≥ 0.85 | ≥ 0.90 |
| 関連性判定 Recall | ≥ 0.80 | ≥ 0.85 |
| センチメント評価コスト | N/A | ≤ USD 5／月（Haiku 4.5） |
| ダッシュボード初期読み込み | ≤ 3 秒 | ≤ 2 秒 |

---

## 4. システム全体構成

```
┌────────────────────────────────────────────────────────────────┐
│ ローカル Python パイプライン（または GitHub Actions 上で実行） │
│                                                                 │
│  ①Collectors  →  ②Normalizer  →  ③Classifier               │
│  (RSS/GoogleNews/GDELT/SEC)    (URL正規化・重複排除)    (ルール) │
│                                                                 │
│           →  ④Sentiment(LLMバッチ, キャッシュ前提)            │
│           →  ⑤Aggregator  →  ⑥StaticExporter                 │
│                                          │                      │
│                                          ▼                      │
│                            docs/data/*.json（静的データ）       │
│                            docs/index.html ほか                 │
└────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────┐
│ GitHub Pages（静的配信）                                        │
│   HTML + JS + Plotly.js                                         │
│   JSON を fetch してチャート描画                                 │
└────────────────────────────────────────────────────────────────┘
```

### 4.1 データ更新方式

2 方式を併用可能に設計する。

| 方式 | 実行環境 | 頻度 | 用途 |
|---|---|---|---|
| ローカル実行 | Windows Task Scheduler + Python | 任意 | 開発時・バックフィル |
| GitHub Actions | GitHub クラウド | cron（例: 毎日 22:00 UTC） | 本番定期更新 |

いずれも最終成果物は `docs/data/*.json` への書き出しで、Git コミット＆プッシュで GitHub Pages が自動再デプロイされる。

---

## 5. データソース（メタデータ取得）

取得する項目は **タイトル・スニペット（リード 2–3 文）・媒体名・公開日・正規化 URL・言語** のみ。**本文は保存しない**。

| 種別 | ソース | 方法 | 備考 |
|---|---|---|---|
| 集約 | Google News RSS（キーワードクエリ別） | feedparser | 多言語、広範 |
| 集約 | GDELT 2.0 DOC API | REST/JSON | 海外広範、無料、スニペット取得可 |
| 専門 | Private Debt Investor / Creditflux / 9fin / Debtwire | RSS（公開分のみ） | 有料記事はタイトル＋要約のみ |
| 開示 | SEC EDGAR Full-Text Search | REST | 8-K, 10-K, 10-Q, N-2 |
| 国内 | ロイター日本、Bloomberg 日本版 | RSS | |
| 国内 | 日経電子版 | RSS（公開範囲） | 有料本文は取得しない |
| IR | 主要 BDC IR プレス | 軽量スクレイピング | PR タイトルのみ |

**ガイドライン**

- `robots.txt` 尊重、`User-Agent` 明示、1 ソースあたり最低 2 秒の間隔
- 再配信・転載は一切行わない。ダッシュボードはタイトル・スニペット・原典リンクのみ表示
- 有料サイト本文は取得しない（フェアユース／契約違反の回避）

---

## 6. 株価・インデックスデータ

### 6.1 対象ティッカー

VanEck BDC Income ETF（BIZD、MVIS US Business Development Companies Index 連動）の構成上位 12 社を中心に、ベンチマークを加えた計 15 本を取得する。**構成比は四半期ごとに変動するため、BIZD の月次リバランス後に `config/tickers.yaml` を見直す運用**とする。

| 区分 | ティッカー | 名称 |
|---|---|---|
| BDC 上位 12 社 | ARCC | Ares Capital |
| | FSK | FS KKR Capital |
| | BXSL | Blackstone Secured Lending |
| | OBDC | Blue Owl Capital Corp |
| | MAIN | Main Street Capital |
| | HTGC | Hercules Capital |
| | GBDC | Golub Capital BDC |
| | BBDC | Barings BDC |
| | PSEC | Prospect Capital |
| | TSLX | Sixth Street Specialty Lending |
| | NMFC | New Mountain Finance |
| | CGBD | Carlyle Secured Lending |
| ベンチマーク | BIZD | VanEck BDC Income ETF（業界プロキシ） |
| | ^SPX | S&P 500（株式全体） |
| | HYG | iShares iBoxx HY Corp Bond ETF（クレジット参考） |

※ 2026 年 4 月時点の BIZD 上位構成を参考にした初期リスト。リバランス後に上位から外れた銘柄は `legacy_tickers` として履歴保持、新規組入銘柄は `active_tickers` に追加する。

### 6.2 取得方法

- **ライブラリ**: `yfinance`（無料、Yahoo Finance 経由）
- **補助**: `stooq`（フォールバック）
- **頻度**: 日次終値のみ。日中データは扱わない
- **期間**: 2024-01-01〜現在
- **保存**: `docs/data/prices.json`（ティッカー × 日付 × 終値）

### 6.3 重ね描き時の処理

- 基準日（2024-01-01）を 100 とする**指数化**オプション
- 移動平均（20d, 60d）オーバーレイ
- ニュース件数は二軸（左: 株価指数、右: 件数）

---

## 7. モジュール構成

```
bdc-news/
├── pyproject.toml
├── .github/workflows/daily.yml       # GitHub Actions
├── config/
│   ├── keywords.yaml                 # MUST/SHOULD/EXCLUDE
│   ├── sources.yaml                  # RSS / 検索クエリ / レート
│   ├── weights.yaml                  # 媒体重み
│   └── tickers.yaml                  # 株価・指数対象
├── src/bdc_news/
│   ├── collectors/
│   │   ├── base.py
│   │   ├── google_news.py
│   │   ├── gdelt.py
│   │   ├── rss.py
│   │   └── sec_edgar.py
│   ├── pipeline/
│   │   ├── normalizer.py             # URL 正規化・言語判定
│   │   ├── dedupe.py                 # SimHash
│   │   ├── classifier.py             # キーワードゲート＋ルール
│   │   ├── sentiment.py              # LLM バッチ評価＋キャッシュ
│   │   ├── aggregator.py             # 日次集計
│   │   └── prices.py                 # yfinance 取得
│   ├── storage/
│   │   ├── models.py                 # SQLAlchemy（ローカル SQLite）
│   │   └── repo.py
│   ├── export/
│   │   └── to_static_json.py         # docs/data/*.json 書き出し
│   └── cli.py                        # Typer CLI
├── docs/                             # GitHub Pages ルート
│   ├── index.html
│   ├── assets/
│   │   ├── app.js
│   │   └── style.css
│   └── data/                         # 生成物（Git 管理）
│       ├── articles.json             # 全記事メタ（圧縮可）
│       ├── daily_index.json          # 日次指数
│       ├── monthly_index.json        # 月次集計
│       ├── by_entity.json            # BDC／運用者別集計
│       └── prices.json               # 株価・指数
├── data/
│   └── bdc_news.sqlite               # ローカル作業用 DB（Git 管理外）
├── lexicons/                         # 極性辞書（Git 管理）
│   ├── LoughranMcDonald_MasterDictionary.csv
│   └── ja_financial_polarity.csv
├── tests/
└── README.md
```

---

## 8. データモデル

### 8.1 SQLite（ローカル作業用）

#### `articles`

| カラム | 型 | 説明 |
|---|---|---|
| `id` | TEXT (UUID) | 主キー |
| `url_canonical` | TEXT UNIQUE | 正規化 URL |
| `source_name` | TEXT | 媒体名 |
| `source_id` | TEXT | `sources.yaml` キー |
| `title` | TEXT | |
| `snippet` | TEXT | リード 2–3 文のみ |
| `language` | CHAR(2) | `ja`/`en`/… |
| `published_at` | TIMESTAMP | |
| `collected_at` | TIMESTAMP | |
| `content_hash` | CHAR(16) | SimHash（タイトル＋スニペット）|
| `is_relevant` | INT | 0/1 |
| `relevance_rule` | TEXT | 判定に効いたルール名 |

#### `article_scores`

| カラム | 型 | 説明 |
|---|---|---|
| `article_id` | TEXT FK | |
| `sentiment` | REAL | −1.0〜+1.0 |
| `label` | TEXT | positive/neutral/negative |
| `confidence` | REAL | 0.0〜1.0 |
| `target` | TEXT | `industry`（既定）/ `issuer` / `manager` |
| `model` | TEXT | `lm-dict-v1` (英) / `oseti-v1` (日) |
| `pos_hits` | INT | 辞書一致したポジ語数 |
| `neg_hits` | INT | 辞書一致したネガ語数 |
| `scored_at` | TIMESTAMP | |

#### `article_entities`

| カラム | 型 | 説明 |
|---|---|---|
| `article_id` | TEXT FK | |
| `entity_type` | TEXT | `manager` / `bdc` / `regulator` |
| `entity_name` | TEXT | 正規化済み名 |
| `ticker` | TEXT NULL | |

#### `daily_index`

| カラム | 型 | 説明 |
|---|---|---|
| `date` | DATE | |
| `region` | TEXT | `jp` / `global` / `us` / `all` |
| `n_articles` | INT | |
| `sent_mean` | REAL | 単純平均 |
| `sent_weighted` | REAL | 媒体重み付き |
| `pos_ratio` | REAL | sentiment > +0.2 の割合 |
| `neg_ratio` | REAL | sentiment < −0.2 の割合 |
| `heat_index` | REAL | log(1+n) × |sent_weighted| |

### 8.2 静的 JSON（GitHub Pages 用）

- `articles.json`: 記事メタ（タイトル・スニペット・URL・媒体・日付・sentiment・label・entities）。サイズが大きくなる場合は月次分割
- `daily_index.json`: 日次集計（上記 `daily_index` 相当）
- `monthly_index.json`: 月次集計
- `by_entity.json`: BDC／運用者別の件数とセンチメント推移
- `prices.json`: ティッカー × 日付 × 終値

すべて UTF-8 / `Content-Type: application/json` / ブラウザで直接 fetch 可能。

---

## 9. 関連性判定

**本文がない前提**でタイトル＋スニペットのみから判定。

1. **Stage 1 キーワードゲート**: MUST キーワードを 1 つ以上含む AND EXCLUDE を含まない
2. **Stage 2 ルール**: 正規化した主要エンティティ名（BDC ティッカー、運用者名）の辞書マッチ
3. **Stage 3（任意）軽量分類器**: 運用後に誤検知を減らすため、ラベル付与 500 件でロジスティック回帰を追加
4. グレーゾーン記事もルール側（SHOULD キーワードの組み合わせ重み、エンティティ近接）で判定し、**外部 API には一切依存しない**。運用後の誤検知は人手ラベル 200〜500 件を元にロジスティック回帰で自動学習（§10.4 と共用特徴量）。

---

## 10. センチメント評価（完全オフライン・極性辞書ベース）

### 10.1 方針（決定事項 #2 の具体化）

**外部 API は使用しない**。GitHub Actions 無料枠内で完結するよう、金融テキスト向けの公開極性辞書でカウントベース評価を行う。モデルダウンロードも不要。

| 言語 | 辞書 | 出典 | ライセンス |
|---|---|---|---|
| 英語 | **Loughran-McDonald Master Dictionary (2020+)** | Notre Dame University（Tim Loughran & Bill McDonald） | 学術・業務利用可（出典明記） |
| 日本語 | **oseti** ライブラリ（日本語評価極性辞書 "PN Table" / 単語感情極性値対応表ベース） | 東工大・東北大 | CC BY-SA 4.0（出典明記） |
| 日本語（金融特化強化） | 金融ドメイン語の手動追加辞書（`ja_financial_polarity.csv`） | 自作（`covenant-lite`、`ノンアクルーアル` 等の訳語・専門語を Pos/Neg でタグ付け） | プロジェクト内包 |

いずれも辞書ファイルを `lexicons/` 配下に Git 管理し、**ネットワーク不要・決定論的・完全再現可能**。

### 10.2 スコアリングアルゴリズム

1. テキスト前処理: 小文字化（英）／MeCab 分かち書き（日）、URL・数字・記号除去
2. トークン化後、`pos_hits` / `neg_hits` を辞書突き合わせでカウント
3. **否定反転**: 英語は `not/no/never/without` が直前 3 トークン以内にあれば極性反転。日本語は「〜ない／〜ず／〜無し」を簡易検出
4. 不確実性語（`uncertain`, `risk`, `doubt`、"懸念" 等）は `uncertainty_hits` として別集計（スコアには加味せず、信頼度に影響）
5. スコア計算:

   ```
   raw = (pos_hits − neg_hits) / max(pos_hits + neg_hits, 1)
   score = clamp(raw, -1.0, +1.0)
   label = positive if score > +0.2
         = negative if score < -0.2
         = neutral  otherwise
   confidence = (pos_hits + neg_hits) / max(token_count, 1)
              ただし 0.05 未満は confidence=0（評価不能扱い）
   ```

6. `confidence = 0` の記事はセンチメント集計から除外するが、件数カウントには含める

### 10.3 評価対象の解釈

辞書はあくまで「テキストのトーン」を測るため、**「BDC／プライベートクレジット業界にとってのポジ／ネガ」へ揃えるためのドメイン補正**を入れる:

- 「デフォルト率上昇」「スプレッド拡大」「ノンアクルーアル増加」は業界にとってネガ → 該当フレーズを `lexicons/domain_override.csv` に登録し、辞書カウント後に符号調整
- 「新規組成」「AUM 増加」「ディストリビューション増配」は業界ポジ → 同様にオーバーライド
- オーバーライドは段階的に育てる（Phase 3 で最低 50 フレーズ、Phase 7 で 200 フレーズを目標）

### 10.4 品質担保

- `tests/test_sentiment.py`: 30 件の既知ラベル付きサンプル（記事タイトル＋snippet の人手ラベル）でリグレッション
- ダッシュボードの「About」ページに精度指標（精度・Cohen's kappa）を掲載
- 誤判定の多いパターンを月次で `domain_override.csv` に追加

### 10.5 将来拡張（任意、v2.0 以降）

- **ローカル ML**: FinBERT（`ProsusAI/finbert`）を `torch` CPU 推論で追加。ただしモデル ≈ 438MB の取り扱いは GitHub Actions キャッシュ運用が必要
- **日本語**: `izumi-lab/bert-small-japanese-fin`（≈ 110MB）

これらも **API 不使用の範疇**で実装可能。v1.1 では採用しない。

---

## 11. 指数設計

| 指標 | 定義 |
|---|---|
| 日次件数 | 当日に `published_at` がある関連記事の数 |
| 日次センチメント指数 | `Σ(score_i × source_weight_i × recency_weight_i) / Σweights`（既定 recency=1.0） |
| ポジ比率 | `score > +0.2` の記事比率 |
| ネガ比率 | `score < −0.2` の記事比率 |
| モメンタム | 直近 7 日平均 − その前 7 日平均 |
| フロー指数 | `log(1 + n_articles)` |
| ヒート指数 | `flow_index × |sentiment_index|`（話題性×方向性） |

集計粒度は日次・週次・月次。地域は `jp` / `global` / `us` / `all`、エンティティ別（BDC・運用者）も並走で算出。

---

## 12. フロントエンド仕様（GitHub Pages 静的サイト）

### 12.1 技術

- **HTML + Vanilla JS（またはごく軽量な Alpine.js）**
- **Plotly.js** もしくは **ECharts**（どちらも CDN 経由、ビルド不要）
- ビルドステップなし（`docs/` 直下をそのまま配信）

### 12.2 画面構成

#### ① トップ（Overview）

- ヘッダー: タイトル、最終更新日時、期間セレクタ（2024-01-01〜最新、1M/3M/6M/1Y/All プリセット）
- **パネル A: 件数推移**（棒または面グラフ、日次／週次切替）
- **パネル B: センチメント指数推移**（線、ゼロライン強調）
- **パネル C: ポジ／ネガ比率**（積み上げエリア）
- **パネル D: ヒート指数 × 株価重ね描き**
    - 左軸: ヒート指数（またはセンチメント指数・件数を切替）、右軸: 株価
    - ティッカーを複数選択可（既定: BIZD）。対象は BDC 上位 12 社＋ベンチマーク 3 本（ARCC / FSK / BXSL / OBDC / MAIN / HTGC / GBDC / BBDC / PSEC / TSLX / NMFC / CGBD / BIZD / ^SPX / HYG）
    - 2024-01-01 を 100 とした指数化トグル
    - 移動平均（20d / 60d）オーバーレイ

#### ② エンティティ別（By Entity）

- BDC・運用者ごとの件数とセンチメント
- ヒートマップ（行：エンティティ × 列：月）

#### ③ 記事リスト（Articles）

- 日付・媒体・タイトル・ラベル（色分け）・sentiment・原典リンク
- 検索ボックス、媒体フィルタ、日付フィルタ

#### ④ メソドロジー（About）

- キーワード一覧、媒体重み、評価モデル、免責事項（個別投資助言ではない旨）

### 12.3 アクセシビリティ・その他

- レスポンシブ（スマホで閲覧可）
- ダーク／ライトモード（任意）
- 全 JSON は CORS 不要（同一オリジン）

---

## 13. 運用・スケジューリング

### 13.1 GitHub Actions（推奨本番）

`.github/workflows/daily.yml` で cron スケジュール。

- 実行: 毎日 22:00 UTC（= 翌 07:00 JST）
- ステップ:
    1. Python セットアップ、依存インストール（pip cache 利用）
    2. `python -m bdc_news.cli collect` → RSS/GDELT/SEC 取得
    3. `python -m bdc_news.cli classify`
    4. `python -m bdc_news.cli score` → ローカル極性辞書で評価
    5. `python -m bdc_news.cli prices` → yfinance 更新
    6. `python -m bdc_news.cli export` → `docs/data/*.json` 書き出し
    7. 差分を自動コミット＆プッシュ（`github-actions[bot]`）
- **シークレット不要**（外部 API を使用しないため）。`GITHUB_TOKEN` は Actions 既定のもので充足

### 13.2 ローカル実行

```
python -m bdc_news.cli collect --since 2024-01-01
python -m bdc_news.cli classify
python -m bdc_news.cli score --batch 20
python -m bdc_news.cli prices --since 2024-01-01
python -m bdc_news.cli export
```

Windows Task Scheduler で毎日実行も可。

### 13.3 ログ／監視

- 構造化 JSON Lines ログを `logs/YYYY-MM-DD.jsonl` に出力
- GitHub Actions の失敗はメール通知（標準機能）
- ジョブ末尾で処理件数・辞書ヒット率・未分類記事数をサマリ表示

---

## 14. 技術スタック

- Python 3.11+
- `httpx`（async）, `feedparser`, `beautifulsoup4`
- `langdetect`, `simhash`
- `sqlalchemy`, SQLite
- **センチメント（外部 API なし）**: 英語は Loughran-McDonald CSV を `pandas` で読み込み自前実装、日本語は `oseti` + `mecab-python3`（または `fugashi`＋`unidic-lite` の Pure Python 組み合わせ）
- `yfinance`（株価）
- `typer`（CLI）
- `pytest`
- フロント: HTML / Vanilla JS / **Plotly.js**（CDN、ビルド不要）
- CI: GitHub Actions（シークレット不要）
- 配信: GitHub Pages（Public リポジトリ、`docs/` ディレクトリ方式）

---

## 15. リポジトリ／デプロイ

- **リポジトリ種別**: **Public**（確定）
- GitHub リポジトリ名（例）: `bdc-news-monitor`
- ブランチ: `main`（保護）、作業は feature ブランチ → PR
- GitHub Pages 設定: `Settings → Pages → Source: main branch, /docs folder`
- URL: `https://<user>.github.io/bdc-news-monitor/`（**カスタムドメインなし**）
- ライセンス: コードは MIT、辞書・データの再配布は各出典元のライセンスに従う旨を README に明記（Loughran-McDonald: 出典明記で利用可／oseti: CC BY-SA 4.0）

---

## 16. 実装フェーズ

| Phase | 期間目安 | 成果物 |
|---|---|---|
| **Phase 1: 収集 + 件数 MVP** | 1–2 週 | Google News RSS + GDELT + SEC、SQLite、日次件数 JSON、`docs/index.html` に件数グラフのみ |
| **Phase 2: 関連性判定** | 1 週 | キーワード＋ルール、ラベル 200–500 件で誤検知率測定 |
| **Phase 3: 極性辞書センチメント** | 1–2 週 | Loughran-McDonald + oseti 実装、ドメインオーバーライド辞書 50 語、日次指数、ポジネガ比率グラフ |
| **Phase 4: 株価重ね描き（12 社）** | 0.5–1 週 | yfinance で 12 BDC + ベンチマーク 3 本、`prices.json`、二軸チャート、指数化トグル |
| **Phase 5: エンティティ別／記事リスト／About** | 1 週 | By Entity タブ（12 社）、Articles 一覧、Methodology／辞書出典ページ |
| **Phase 6: GitHub Actions 自動化** | 0.5 週 | cron ワークフロー、差分コミット（シークレット不要） |
| **Phase 7: 改善** | 継続 | 国内媒体追加、軽量分類器、日英別ビュー、アラート、必要に応じ FinBERT ローカル推論追加 |

---

## 17. 免責・コンプライアンス

- 本ツールの出力は個別銘柄の投資助言を構成しない
- 収集したニュース本文は保存・再配信せず、タイトル・スニペット・原典リンクのみ表示
- 株価データは Yahoo Finance 由来、遅延あり・正確性無保証
- `robots.txt` および各媒体の利用規約を尊重
- 有料媒体本文は取得しない

---

## 18. 未決事項

**v1.1 時点で未決事項なし**（v1.0 から持ち越された A–E はすべて確定）。

| # | 項目 | 確定内容 |
|---|---|---|
| A | リポジトリ公開範囲 | **Public** |
| B | GitHub Actions スケジュール | **毎日 22:00 UTC（07:00 JST）** |
| C | 外部 API 利用 | **使用しない**（Loughran-McDonald + oseti によるオフライン評価） |
| D | カスタムドメイン | **不要**（`github.io` サブドメイン） |
| E | エンティティ辞書 | **BIZD 構成上位 12 社（ARCC/FSK/BXSL/OBDC/MAIN/HTGC/GBDC/BBDC/PSEC/TSLX/NMFC/CGBD）＋ベンチマーク 3 本** |

---

## 19. 次アクション

1. GitHub リポジトリ `bdc-news-monitor` を Public で作成
2. `config/keywords.yaml` / `sources.yaml` / `tickers.yaml`（12 社）の初版作成
3. `lexicons/LoughranMcDonald_MasterDictionary.csv` の取得・同梱、`lexicons/ja_financial_polarity.csv` の初期 50 語作成
4. **Phase 1 実装**: Google News RSS Collector → SQLite → `daily_index.json` → Plotly で件数棒グラフ → GitHub Pages 公開
5. Phase 2 以降を順次追加（関連性判定 → 極性辞書センチメント → 株価重ね描き → Actions 自動化）
