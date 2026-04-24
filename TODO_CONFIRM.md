# TODO_CONFIRM — あとで確認したい事項

本プロジェクトは席を外されている間に責任判断でエンドツーエンド実装を進めました。
以下は戻られてから**ご確認・ご判断いただきたい論点**です。優先度の高い順に並べています。

---

## 🔴 High — 動かす前に必要な作業

### 1. GitHub リポジトリの作成と Push
このワークスペースはまだ git 管理下にありません（`/Is a git repository: false`）。以下は**ユーザー操作が必要**です：

1. GitHub で **Public** リポジトリを作成（推奨名: `bdc-news-monitor`）
2. ローカルで初期化・push：
   ```bash
   cd "C:/Users/DFLDXPT/Claude code/BDC NEWS"
   git init
   git add .
   git commit -m "Initial commit: BDC news monitor v0.1"
   git branch -M main
   git remote add origin https://github.com/<your-user>/bdc-news-monitor.git
   git push -u origin main
   ```
3. Settings → Pages → **Deploy from a branch** → `main` / `/docs`
4. 数分後に `https://<your-user>.github.io/bdc-news-monitor/` でアクセス可能

### 2. GitHub Actions の有効化確認
`.github/workflows/daily.yml` は **22:00 UTC（07:00 JST）** の cron を設定済みです。
- リポジトリ Settings → Actions → General → Workflow permissions を
  「**Read and write permissions**」に変更（auto-commit のため必須）
- 初回は手動で `workflow_dispatch` から run して smoke test してください

### 3. Loughran–McDonald 辞書は "サブセット版"
`lexicons/lm_financial_en.csv` は 1,329 語の**部分版**です。
公式配布（Bill McDonald 教授サイト）から正式版を落とす CLI を入れてあります：
```bash
python -m bdc_news.cli update-lexicon-lm
```
ライセンス上の帰属表記が必要かも確認ください（Notre Dame SRAF, non-commercial use の注記あり）。

---

## 🟡 Medium — 運用開始後に見直したい項目

### 4. oseti ライブラリはローカルで未インストール
日本語感情スコアリングの拡張 (oseti + 日本語評価極性辞書) は GitHub Actions 側では pip install で入りますが、**ローカル環境では入っていません**（`oseti=False` がログに出る）。
- ローカルでも JP sentiment を検証したい場合：
  ```bash
  pip install oseti "fugashi[unidic-lite]"
  ```
- oseti なしでも `lexicons/ja_financial_polarity.csv` (~132語) + `domain_override.csv` でベース評価は動きます。

### 5. SEC EDGAR のクエリは初期値ベース
`config/sources.yaml` の `sec_edgar.queries` は BDC / business development company / private credit / direct lending の 4 クエリ。
- ヒット件数が多すぎる・少なすぎる場合は q の絞り込み（`"type=10-K"` 等）が必要
- form 種別（N-2, 10-K, 10-Q, 8-K）は BDC らしく選んでいますが、プロキシ・株主通信まで含めるかは要判断

### 6. BIZD 上位12銘柄の組入比率ドリフト
`config/tickers.yaml` の 12 社は 2026-04 時点の想定構成です。
- BIZD は四半期リバランスあり → **3ヶ月に一度**構成確認推奨
- 次回チェック目安: **2026-07 末**
- 入れ替え時は `tickers.yaml` を編集するだけで良い（コード変更不要）

### 7. RSS フィード URL の妥当性
`config/sources.yaml` の RSS は代表例を入れてあります：
- Seeking Alpha 個別銘柄 RSS: フォーマット変わりやすい
- Reuters: 最新の RSS エンドポイント要確認
- **Private Debt Investor (PDI)**: 公開 RSS があるか未確認、ダミー URL の可能性あり → 初回ジョブで 4xx/5xx 出たら外してください

### 8. 日本語金融極性辞書は 132 語
`lexicons/ja_financial_polarity.csv` は手書きの最小版です。
- 運用しながら誤分類をログで見つけ次第、追記してください
- 「プライベートデット」「ミドルマーケット」「メザニン」等、BDC 固有の和訳揺れは `domain_override.csv` 側で phrase 登録した方が誤爆しにくい

---

## 🟢 Low — 余裕があれば

### 9. 株価レンジ基準化（rebase）の UI
フロントエンドでは 2024-01-01 = 100 に rebase するトグルを実装済み。
- デフォルト OFF（生の価格表示）/ ON で指数化
- BIZD と個別 BDC を比べるなら rebase ON 推奨

### 10. `by_entity` 集計は "タイトル＋スニペット" マッチング
`docs/data/by_entity.json` は記事タイトル・スニペット文字列中のティッカー／社名出現数でカウント。
- 本文メタデータ (author, tags) は使っていません
- 誤カウント（他社向けプレスで言及されただけ等）は残る可能性あり

### 11. ダークテーマのみ
`docs/assets/style.css` はダークモード固定。ライト切替は未実装。

### 12. 記事テーブルのページネーション
`docs/index.html` Articles タブは 50件/ページ。件数が数千超になったら仮想スクロール導入を検討。

---

## 📋 実装サマリ（参考）

- **Spec**: [SPEC.md](SPEC.md) v1.1 確定版（未決事項なし）
- **Python**: 3.11+ / SQLAlchemy 2 / Typer CLI / httpx / yfinance
- **Frontend**: 単体 HTML + Plotly.js CDN（ビルド不要）
- **Sentiment**: Loughran-McDonald (EN 1329 語) + JP 極性 132 語 + Domain override 84 句
- **Tests**: pytest 20/20 passed
- **Smoke test**: 4 synth articles → 3 classified → 3 scored → exported OK

最終判断をユーザー側で必要とする箇所は以上です。優先度🔴の 1〜3 を済ませれば自動運用に入れます。
