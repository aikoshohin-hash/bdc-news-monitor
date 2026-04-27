# BDC / Private Credit News Monitor — 改善提案仕様書

> **対象リポジトリ**: `aikoshohin-hash/bdc-news-monitor`
> **対象URL**: https://aikoshohin-hash.github.io/bdc-news-monitor/
> **作成目的**: Claude Code でのIssue化・実装着手を前提とした、優先度付き改善仕様
> **想定読者**: Claude Code（および本リポジトリのメンテナ）

---

## 0. プロジェクト前提（Claude Codeへの引き継ぎ事項）

| 項目 | 現状 | 制約 |
|---|---|---|
| **配信** | GitHub Pages（静的サイト） | サーバーサイド実行不可。データ更新はGitHub Actions |
| **データ更新頻度** | 毎日 07:00 JST | バッチ処理前提。リアルタイム化は別途検討 |
| **センチメント** | 完全オフライン（L-M辞書 + oseti） | 外部API課金不可の方針を維持 |
| **データソース** | Google News RSS / GDELT 2.0 / SEC EDGAR / 任意RSS | キーワード設定: `config/keywords.yaml` / ソース設定: `config/sources.yaml` |
| **対象銘柄** | BIZD構成上位12社 + ベンチマーク（BIZD, ^GSPC, HYG） | 株価は yfinance |
| **言語** | 英語 + 日本語混在 | UIは日本語ベース |

**設計原則（維持すべき）**
1. 完全オフライン処理（外部API課金なし）
2. 静的サイトでホスティング（GitHub Pagesで完結）
3. 一次情報リンク経由での参照（記事本文は再配信しない）
4. データ・コード・辞書すべての再現性

---

## 1. ロードマップ概観

```
Phase 1（P0）: シグナル品質の地殻変動 ─ 2-3週間
  ├─ Issue #1  BDC固有イベント・タグ抽出
  ├─ Issue #2  10-Q/10-K構造化メトリクス抽出（NAV, non-accruals, NII）
  ├─ Issue #3  銘柄別ドリルダウン・ページ
  └─ Issue #4  BDCドメイン辞書オーバーレイ

Phase 2（P1）: 能動利用への転換 ─ 2-3週間
  ├─ Issue #5  ウォッチリスト機能（クライアントサイドlocalStorage）
  ├─ Issue #6  アラート・パイプライン（GitHub Actions → Slack/Telegram/Email）
  ├─ Issue #7  ヒートマップ・ビュー（BDC × 日付）
  └─ Issue #8  ピア相対センチメント・スコア

Phase 3（P2）: 文脈と拡張性 ─ 任意
  ├─ Issue #9   マクロ・オーバーレイ（HYG OAS, LSTA, CCC default rate）
  ├─ Issue #10  トピックモデリング・テーマ検出
  ├─ Issue #11  ダークモード／モバイル対応
  ├─ Issue #12  データ品質ゲート（重複検出・スキーマ検証）
  └─ Issue #13  ユニバース拡張（BIZD外、interval funds等）
```

---

## 2. Phase 1（P0）詳細仕様

---

### Issue #1: BDC固有イベント・タグ抽出

#### 背景
現状はL-M極性スコアによる「方向」のみ。BDCのクレジット品質評価で実際に効くのは**離散的な事象**（non-accrual計上、配当変更、二次募集等）であり、これをタグ化しないと信号として使えない。

#### 要件
記事タイトル＋スニペットに対して、以下のイベント・タグを多ラベルで付与する。

```yaml
# config/event_taxonomy.yaml
events:
  earnings:
    description: "決算発表（NII, NAV, distribution coverage等の言及）"
    keywords_en: ["reports Q", "earnings", "net investment income", "NII", "NAV per share"]
    keywords_jp: ["決算", "純投資利益", "1株あたり純資産"]

  non_accrual:
    description: "non-accrual計上（クレジットイベントの先行指標）"
    keywords_en: ["non-accrual", "nonaccrual", "placed on non-accrual", "non-performing"]
    keywords_jp: []
    severity: high

  nav_decline:
    description: "NAV悪化"
    keywords_en: ["NAV declined", "NAV decreased", "writedown", "write-down", "mark down"]
    severity: high

  dividend_action:
    description: "配当アクション（増配/減配/特別配当）"
    sub_types:
      - dividend_raise
      - dividend_cut
      - special_dividend
      - dividend_maintained
    keywords_en: ["raises dividend", "cuts dividend", "special dividend", "supplemental distribution"]

  capital_action:
    description: "資本性アクション"
    sub_types:
      - secondary_offering
      - share_repurchase
      - convertible_issuance
      - debt_issuance
    keywords_en: ["secondary offering", "ATM program", "share repurchase", "buyback", "notes offering"]

  m_and_a:
    description: "M&A・統合"
    keywords_en: ["merger", "acquisition", "to acquire", "combination"]

  rating_action:
    description: "格付変更"
    keywords_en: ["S&P", "Moody's", "Fitch", "downgrade", "upgrade", "outlook"]

  regulatory:
    description: "規制関連"
    keywords_en: ["SEC", "FSOC", "OCC", "Federal Reserve", "private credit risk", "BDC rules"]
    keywords_jp: ["金融庁", "プライベートクレジット", "規制"]

  personnel:
    description: "経営陣変更"
    keywords_en: ["CEO", "CFO", "departure", "resigns", "appoints"]

  portfolio_company:
    description: "ポートフォリオ企業のイベント"
    keywords_en: ["portfolio company", "amend and extend", "restructuring", "covenant"]
```

#### 実装方針
- **第一段階（ルールベース）**: 上記YAMLによるキーワード・マッチング。`src/extractors/event_tagger.py` に実装。
- **第二段階（軽量分類器）**: 第一段階で得られた弱ラベルを訓練データとし、`fasttext` または `scikit-learn` の `LogisticRegression(TF-IDF)` で多ラベル分類器を学習。完全オフラインで動作。
- 既存の sentiment スコアと**併存**させる（置き換えではない）

#### データスキーマ追加
```python
# articles.parquet（既存）に追加カラム
{
    "event_tags": list[str],         # ["earnings", "dividend_raise"]
    "event_severity": str,           # "high" / "medium" / "low" / null
    "event_confidence": float,       # 0.0 - 1.0
}
```

#### 受け入れ基準
- [ ] `config/event_taxonomy.yaml` が定義され、上記10カテゴリーをカバー
- [ ] `src/extractors/event_tagger.py` がCLIから単独実行可能
- [ ] ユニットテスト（`tests/test_event_tagger.py`）でカテゴリーごと最低3ケース
- [ ] 既存の articles データに対してバッチ実行し、再現可能なoutputを生成
- [ ] UIの記事テーブルに `event_tags` カラム（バッジ表示）が追加される
- [ ] フィルターUIに「イベントタイプ」マルチセレクトが追加される

---

### Issue #2: 10-Q/10-K 構造化メトリクス抽出

#### 背景
EDGAR Full-Text Searchをすでに利用しているのに、BDC評価の中核メトリクス（NAV/share, NII, non-accruals %, asset coverage ratio, PIK income比率）が抽出されていない。これらは10-Q/10-K本文に含まれており、定型ハーベスト可能。

#### 要件
四半期ごとに以下メトリクスを抽出し、`data/financials/{ticker}_quarterly.parquet` に保存。

```python
# 抽出対象メトリクス
{
    "ticker": str,
    "filing_date": date,
    "fiscal_period": str,              # "2025Q3"
    "nav_per_share": float,
    "total_investments_at_fair_value": float,  # USD
    "net_investment_income_per_share": float,
    "distribution_per_share": float,
    "non_accruals_pct_at_cost": float,         # %
    "non_accruals_pct_at_fair_value": float,   # %
    "pik_income_pct_of_total_income": float,   # %
    "asset_coverage_ratio": float,             # 倍
    "weighted_avg_yield_debt_investments": float,  # %
    "first_lien_pct": float,
    "second_lien_pct": float,
    "filing_url": str,
}
```

#### 実装方針
- **ライブラリ候補**: `python-edgar`, `sec-api`, または `requests` で直接取得
- 構造化抽出は3段階:
  1. **XBRL**: 標準タグがある項目（asset coverage等）を取得
  2. **テーブル抽出**: `pdfplumber` または `unstructured` でNon-accruals tableを抽出
  3. **正規表現フォールバック**: テキストから "NAV per share of $X.XX" 等を拾う
- BDCごとの記載差異（ARCC vs MAIN vs OBDC）に対応する `parsers/{ticker}.py` を必要に応じて用意

#### 受け入れ基準
- [ ] BIZD上位12社全社で過去8四半期のメトリクス抽出に成功
- [ ] 抽出失敗時は `null` を入れて続行（パイプラインを止めない）
- [ ] 銘柄別ドリルダウン（Issue #3）で時系列チャート描画
- [ ] CIで月次に再実行され、新規10-Q公開を自動取得

#### 注意事項
- **優先順位**: ARCC, OBDC, MAIN, FSK, BXSL, GBDC（時価総額上位）から順次対応
- 抽出ロジックの**正解値検証**として、各社IR資料・Press Releaseとのクロスチェックをユニットテストに含める

---

### Issue #3: 銘柄別ドリルダウン・ページ

#### 背景
現状はアグリゲート・ビュー中心。Marcus（PM）の指摘通り、銘柄ごとの統合ビューが基本ナビゲーションの中心であるべき。

#### 要件
URL: `/#/entity/{ticker}` （SPAルーティング）

レイアウト（上から）:
1. **ヘッダー**: ティッカー、フルネーム、最新終値、前日比、時価総額
2. **KPI カード（3列）**:
   - NAV/share（最新四半期、前期比）
   - NII/share（TTM、配当カバー率）
   - Non-accrual %（fair value基準、前期比）
3. **価格 × ニュース指標チャート**（既存の重ね描きの個別銘柄版）
4. **イベント・タイムライン**（横軸: 時間、縦軸: イベントカテゴリ別レーン）
5. **直近記事リスト**（Heat scoreでソート）
6. **直近フィリング**（10-Q/10-K/8-K/N-2、EDGARリンク付き）
7. **ピア比較表**: 同社 + 上位5社のKPIテーブル

#### 実装方針
- 既存のフロントエンド（おそらくvanilla JS / Chart.js想定）に**ハッシュルーティング**を導入
- データは `data/entities/{ticker}.json` として事前ビルド時に生成
- ナビゲーションは「By Entity」タブからティッカー一覧 → 個別ページ

#### 受け入れ基準
- [ ] BIZD上位12社全社で個別ページが生成される
- [ ] 直リンク（`/#/entity/ARCC`）でアクセス可能
- [ ] モバイル幅（375px）でレイアウト崩れなし
- [ ] 「By Entity」タブで銘柄カード一覧 → クリックで遷移
- [ ] パンくず or 戻るボタンで Overview に戻れる

---

### Issue #4: BDCドメイン辞書オーバーレイ

#### 背景
L-M辞書は強力だがBDC固有用語に対して中立扱いが多い。例: "amend and extend"（弱含み兆候だがL-Mでは中立）、"covenant lite"（リスク要因）、"second lien"（中立だが文脈次第）。

#### 要件
`config/sentiment_overrides_bdc.yaml` を新設し、L-M結果に対するオーバーレイ・ルールとして適用。

```yaml
# config/sentiment_overrides_bdc.yaml
overrides:
  # フレーズ単位（既存のフレーズ単位ドメイン・オーバーライドの拡張）
  - pattern: "amend and extend"
    polarity: -0.3
    rationale: "債務再編シグナル。一時的延命だが構造改善ではない"

  - pattern: "covenant lite"
    polarity: -0.2
    rationale: "投資家保護薄弱"

  - pattern: "first lien"
    polarity: +0.1
    rationale: "回収順位優位"

  - pattern: "second lien"
    polarity: -0.1
    rationale: "回収順位劣後"

  - pattern: "PIK income"
    polarity: -0.15
    rationale: "現金収入劣後、長期では信用劣化シグナル"
    context_required: ["increased", "rose", "growing", "高まる"]

  - pattern: "non-accrual"
    polarity: -0.5
    rationale: "明確な信用劣化"

  - pattern: "supplemental distribution"
    polarity: +0.3
    rationale: "余剰収益還元"

  - pattern: "rights offering"
    polarity: -0.4
    rationale: "希薄化、資本不足の可能性"

  - pattern: "ATM program"
    polarity: -0.1
    rationale: "希薄化のフロー、ただし規律ある場合は中立"

  - pattern: "asset coverage ratio"
    contextual: true  # 数値が必要
    rationale: "1.5x未満は要注意、2.0x超は健全"

  # 日本語
  - pattern: "プライベートクレジット"
    polarity: 0.0
    rationale: "中立タグ用"

  - pattern: "格付け引き下げ"
    polarity: -0.5
```

#### 実装方針
- センチメント計算パイプラインの**最終段**でこのオーバーレイを適用
- 既存スコアに対する加算（cap/floor: -1.0 / +1.0）
- `tests/test_sentiment_overrides.py` で各パターンの単体テスト
- README に辞書の出典・更新ポリシーを明記（既存のL-M / oseti の出典明記と同様）

#### 受け入れ基準
- [ ] 30以上のBDC固有パターンを定義
- [ ] 既存のL-M / oseti結果と並行して保存（オーバーレイ前後を両方記録）
- [ ] About / Methodology ページに辞書の存在と仕組みを明記
- [ ] 退行テスト: 既存記事でセンチメント分布の比較レポート生成

---

## 3. Phase 2（P1）詳細仕様

---

### Issue #5: ウォッチリスト機能

#### 要件
- ヘッダーに「★ Watchlist」ボタン → モーダルでBDC選択
- 選択した銘柄は `localStorage` に保存（サーバー不要）
- Overview ページで「Watchlist のみ表示」トグル
- ピア比較表の表示優先度をWatchlist銘柄に上げる

#### 受け入れ基準
- [ ] localStorage キー: `bdc_monitor_watchlist`（JSON配列）
- [ ] 別端末への同期は明示的にスコープ外（インポート/エクスポートで対応）
- [ ] エクスポート: クリップボードにJSONコピー、インポート: ペースト

---

### Issue #6: アラート・パイプライン

#### 背景
能動的に「通知が来る」モニターへ。

#### 要件
GitHub Actions で日次バッチの最後に以下のチェックを行い、条件合致時に通知:

```python
# alerts/rules.yaml
rules:
  - name: "Heat指数急騰"
    condition: "heat_index > heat_index_p95_30d"
    targets: ["watchlist"]  # or ["all"]
    channels: ["slack"]
    cooldown_hours: 24

  - name: "新規8-K"
    condition: "new_filing AND filing_type == '8-K'"
    targets: ["watchlist"]
    channels: ["slack", "email"]

  - name: "センチメント急落"
    condition: "sentiment_z_score_5d < -2.0"
    targets: ["all"]
    channels: ["slack"]

  - name: "Non-accrual言及記事"
    condition: "'non_accrual' in event_tags"
    targets: ["all"]
    channels: ["slack", "email"]
    severity: high
```

#### 実装方針
- **Webhook送信**: `WEBHOOK_SLACK_URL` 等を GitHub Secrets に格納
- **Email**: SMTPは GitHub Actions の `dawidd6/action-send-mail@v3` 等を利用
- **Telegram**（オプション）: Bot APIで送信
- アラート履歴は `data/alerts_log.parquet` に永続化（重複抑制用）

#### 受け入れ基準
- [ ] Slack webhook での送信が動作（テスト用チャンネルで確認）
- [ ] cooldownロジックで24時間以内の重複通知を抑制
- [ ] アラート設定YAMLのバリデーション（CIで実行）
- [ ] 通知メッセージにダッシュボードへのディープリンク

---

### Issue #7: ヒートマップ・ビュー

#### 要件
新規タブ「Heatmap」を追加。
- **行**: BIZD上位12社
- **列**: 日付（過去90日 / 180日 / 365日 切替）
- **セル色**: その日のセンチメント・スコア（赤-灰-緑のdiverging）
- **セル上ホバー**: 当日記事リスト（最大5件）のツールチップ
- **クリック**: 当該銘柄・当該日付フィルターで Articles ページへ

#### 実装方針
- `d3.js` または `Chart.js` のmatrix chartプラグイン
- 描画パフォーマンス: 12 × 365 = 4,380 セルなのでcanvas推奨

#### 受け入れ基準
- [ ] 過去90/180/365日切替動作
- [ ] スコアレンジ: -1.0 ～ +1.0、色は colorblind-safe palette
- [ ] エクスポート: PNG画像保存ボタン

---

### Issue #8: ピア相対センチメント・スコア

#### 要件
個別BDCのセンチメントが「絶対値」で良くても、業界全体が良いと意味がない。**ピア相対化**が必要。

```python
# 計算式
relative_sentiment[ticker, date] = (
    sentiment[ticker, date] - mean(sentiment[peers, date])
) / std(sentiment[peers, date])
```

- ピア集合は BIZD 上位12社
- 30日移動平均で平滑化
- Overview と銘柄ドリルダウンで切替表示（「絶対」 vs 「ピア相対」）

#### 受け入れ基準
- [ ] 切替トグルがOverview / Entity ページに存在
- [ ] zスコアの定義をAbout / Methodologyに明記
- [ ] バックテスト用ノートブックで「相対センチメントが価格を予測するか」の検証コードを `notebooks/peer_relative_validation.ipynb` に格納

---

## 4. Phase 3（P2）詳細仕様（要約）

### Issue #9: マクロ・オーバーレイ
- HYG OAS（FRED: BAMLH0A0HYM2）, LSTA（プロキシ）, CCC default rate, BBB OAS をyfinance/FREDで取得
- Overviewのチャートに左軸/右軸切替で重ね描き

### Issue #10: トピックモデリング
- BERTopic（オフラインで `sentence-transformers/all-MiniLM-L6-v2` 使用）でテーマ自動抽出
- 「直近2週間で増えているテーマ」サイドパネル

### Issue #11: ダークモード／モバイル対応
- CSS Variables ベースのトークン化
- `prefers-color-scheme` 自動検出 + 手動切替
- モバイル: 375px～768pxでチャート1列レイアウト

### Issue #12: データ品質ゲート
- pandera / pydantic でスキーマ検証
- 同記事のsyndicated copy検出（タイトルfuzzy match + 公開時刻近接）
- CIで品質メトリクス（欠損率、重複率）を出力

### Issue #13: ユニバース拡張
- BIZD外: PSEC, TSLX, FDUS, OCSL等
- Interval funds（CION, OFS等）
- `config/universe.yaml` で管理

---

## 5. Claude Code向け作業ガイダンス

### 着手順
1. **Issue #1（イベント抽出）から始める** — 他のIssueの基礎データになる
2. **Issue #2（EDGAR構造化）と並行** — データ依存がない
3. **Issue #3（ドリルダウン）はIssue #1, #2の出力を消費** — 後続
4. **Phase 2は並列着手可能** — 互いに依存少ない

### コミット粒度
- 1 Issue = 複数 PR を許容（特にIssue #2は銘柄別パーサで分割）
- データスキーマ変更は**必ず先行PR**で型定義を入れる

### 確認ポイント（PR前のセルフチェック）
- [ ] `make test` がパス（既存テスト + 新規）
- [ ] `pre-commit` の linting が通る
- [ ] スキーマ変更時は `data/schema_version.txt` を更新
- [ ] README の機能リスト更新
- [ ] About / Methodology ページの記述更新

### 設計判断で迷ったら
- **オフライン原則を最優先**: 外部API依存が必要に見える機能は、オフライン代替を検討
- **再現性 > 利便性**: ランダム要素は seed固定
- **静的サイト互換性**: ビルド時に確定するデータでUIを駆動

---

## 6. 議論された除外事項（採用しない選択肢）

| 案 | 却下理由 |
|---|---|
| FinBERT等の大規模モデル導入 | オフライン原則と GitHub Actions の実行時間制約 |
| リアルタイム化（WebSocket） | 静的サイト前提との不整合、運用負荷 |
| ユーザー認証 | 個人ツールとしての位置付け、複雑化を避ける |
| 投資助言・推奨ロジック | コンプライアンス・リスク（免責スコープ外） |
| クローリング自前実装 | RSS / GDELT / EDGARの公式チャネルで十分、ToS遵守を優先 |

---

## 7. 専門家パネルからの最終コメント

> **田中（クレジットアナリスト）**: 「Issue #1, #2が入れば、現在のサイトは _BDC専門アナリスト向けの実用的モニター_ に化ける。特にnon-accrual言及の自動検知は、運用会社の月次クレジットレビューで時短効果が大きい」

> **Sarah Chen（NLP）**: 「ピア相対センチメント（Issue #8）は単純だが効く。絶対センチメントだけ見ているうちは方向性しか取れない」

> **Marcus Weber（PM）**: 「ウォッチリスト + アラートが入れば、毎朝Slackを見るルーチンに組み込める。Issue #5, #6 を P1 から P0 に上げてもいいくらい」

> **佐藤（規制）**: 「FSOC・OCCのプライベートクレジット言及は2024-2025年で急増している。マクロオーバーレイは早めに」

> **Elena Vasquez（UX）**: 「ダークモードは _trivial だが効果絶大_。Phase 3に置いたが、隙間時間で先行実装してもいい」

> **Raj Patel（アーキテクト）**: 「Issue #12のデータ品質ゲートは _保険_ として早めに入れたほうが、後続Issueで生じる障害を減らす」

---

## 付録A: 既存ファイル構成への追加（推定）

```
bdc-news-monitor/
├── config/
│   ├── keywords.yaml                    [既存]
│   ├── sources.yaml                     [既存]
│   ├── event_taxonomy.yaml              [Issue #1 で新規]
│   ├── sentiment_overrides_bdc.yaml     [Issue #4 で新規]
│   ├── universe.yaml                    [Issue #13 で新規]
│   └── alerts_rules.yaml                [Issue #6 で新規]
├── src/
│   ├── extractors/
│   │   ├── event_tagger.py              [Issue #1 で新規]
│   │   └── edgar_metrics.py             [Issue #2 で新規]
│   ├── sentiment/
│   │   └── overrides.py                 [Issue #4 で新規]
│   ├── analytics/
│   │   └── peer_relative.py             [Issue #8 で新規]
│   └── alerts/
│       ├── evaluator.py                 [Issue #6 で新規]
│       └── notifier.py                  [Issue #6 で新規]
├── data/
│   ├── articles.parquet                 [既存、スキーマ拡張]
│   ├── financials/
│   │   └── {ticker}_quarterly.parquet   [Issue #2 で新規]
│   ├── entities/
│   │   └── {ticker}.json                [Issue #3 で新規]
│   └── alerts_log.parquet               [Issue #6 で新規]
├── web/
│   ├── pages/
│   │   ├── overview.html                [既存]
│   │   ├── entity.html                  [Issue #3 で新規]
│   │   └── heatmap.html                 [Issue #7 で新規]
│   └── js/
│       ├── watchlist.js                 [Issue #5 で新規]
│       └── router.js                    [Issue #3 で新規]
└── tests/
    ├── test_event_tagger.py             [Issue #1 で新規]
    ├── test_edgar_metrics.py            [Issue #2 で新規]
    └── test_sentiment_overrides.py      [Issue #4 で新規]
```

---

## 付録B: KPI（このロードマップが成功した場合）

| メトリクス | 現状 | Phase 1 完了後目標 | Phase 2 完了後目標 |
|---|---|---|---|
| 銘柄別ドリルダウンの存在 | ❌ | ✅ 12社全カバー | ✅ 18社+ |
| イベント・タグの粒度 | 0種 | 10カテゴリー | 10カテゴリー＋階層 |
| 構造化財務メトリクス | 0項目 | 10項目 × 12社 × 8期 | 同左 |
| 通知チャネル | 無 | 無 | Slack + Email + Telegram |
| ピア相対化 | 無 | 無 | ✅ |
| 期待される利用頻度 | 週次 | 隔日 | 毎営業日 |

---

*以上、Claude Codeでの実装着手時はこのドキュメントを `docs/improvement_spec.md` として配置することを推奨。各Issueは GitHub Issues に切り出し、ラベル `phase-1` / `phase-2` / `phase-3` で管理する想定。*
