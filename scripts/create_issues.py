"""One-shot helper to bootstrap GitHub Issues for the improvement spec.

Reads token from env var GH_TOKEN. Creates three phase labels and 13 issues
matching docs/BDC_Monitor_Improvement_Spec.md.

Idempotent: skips labels/issues that already exist (matched by name/title).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

OWNER = "aikoshohin-hash"
REPO = "bdc-news-monitor"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"


def gh(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    token = os.environ["GH_TOKEN"]
    req = urllib.request.Request(
        f"{API}{path}" if path.startswith("/") else path,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "bdc-news-monitor-bootstrap",
        },
        data=json.dumps(body).encode("utf-8") if body else None,
    )
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


LABELS = [
    {"name": "phase-1", "color": "d73a4a", "description": "P0 — シグナル品質の地殻変動"},
    {"name": "phase-2", "color": "fbca04", "description": "P1 — 能動利用への転換"},
    {"name": "phase-3", "color": "0e8a16", "description": "P2 — 文脈と拡張性（任意）"},
]


def ensure_labels() -> None:
    status, existing = gh("GET", "/labels?per_page=100")
    existing_names = {x["name"] for x in existing} if isinstance(existing, list) else set()
    for label in LABELS:
        if label["name"] in existing_names:
            print(f"  · label exists: {label['name']}")
            continue
        code, resp = gh("POST", "/labels", label)
        if code in (200, 201):
            print(f"  ✓ label created: {label['name']}")
        else:
            print(f"  ✗ label failed: {label['name']} → {code} {resp}")


def spec_link(section: str) -> str:
    return (
        "## 参照\n"
        "[docs/BDC_Monitor_Improvement_Spec.md]"
        "(../blob/main/docs/BDC_Monitor_Improvement_Spec.md) "
        f"§ {section}"
    )


ISSUES = [
    {
        "title": "[Phase1] #1 BDC固有イベント・タグ抽出",
        "labels": ["phase-1"],
        "body": (
            "## 背景\n"
            "現状はL-M極性スコアによる「方向」のみ。BDCのクレジット品質評価で実際に効くのは"
            "離散的な事象（non-accrual計上、配当変更、二次募集等）であり、これをタグ化しないと信号として使えない。\n\n"
            "## 要件\n"
            "記事タイトル＋スニペットに対して、以下10カテゴリーのイベント・タグを多ラベル付与する。\n"
            "- earnings / non_accrual / nav_decline / dividend_action / capital_action / "
            "m_and_a / rating_action / regulatory / personnel / portfolio_company\n\n"
            "## 実装方針\n"
            "- 第一段階（ルールベース）: `config/event_taxonomy.yaml` + キーワード/正規表現マッチ → "
            "`src/bdc_news/extractors/event_tagger.py`\n"
            "- 第二段階（軽量分類器）: 弱ラベルから fasttext / TF-IDF + LogReg。**別 PR で対応**\n"
            "- 既存 sentiment と**併存**（置き換えではない）\n\n"
            "## データスキーマ追加\n"
            "`ArticleScore.event_tags` (JSON配列), `event_severity`, `event_confidence`\n\n"
            "## 受け入れ基準\n"
            "- [ ] `config/event_taxonomy.yaml` で10カテゴリーをカバー\n"
            "- [ ] `event_tagger.py` がCLIから単独実行可能（`bdc-news tag-events`）\n"
            "- [ ] `tests/test_event_tagger.py` でカテゴリーごと最低3ケース\n"
            "- [ ] 既存記事に対してバッチ実行し再現可能なoutput\n"
            "- [ ] UIの記事テーブルに `event_tags` カラム（バッジ表示）\n"
            "- [ ] フィルターUIに「イベントタイプ」マルチセレクト追加\n\n"
            + spec_link("2 Issue #1")
        ),
    },
    {
        "title": "[Phase1] #2 10-Q/10-K 構造化メトリクス抽出",
        "labels": ["phase-1"],
        "body": (
            "## 背景\n"
            "EDGAR Full-Text Search を既に利用しているのに、BDC評価の中核メトリクス"
            "（NAV/share, NII, non-accruals %, asset coverage, PIK income比率）が抽出されていない。\n\n"
            "## 要件\n"
            "四半期ごとに以下を抽出し、`data/financials/{ticker}_quarterly.parquet` に保存：\n"
            "ticker / filing_date / fiscal_period / nav_per_share / "
            "total_investments_at_fair_value / net_investment_income_per_share / "
            "distribution_per_share / non_accruals_pct_at_cost / non_accruals_pct_at_fair_value / "
            "pik_income_pct_of_total_income / asset_coverage_ratio / weighted_avg_yield / "
            "first_lien_pct / second_lien_pct / filing_url\n\n"
            "## 実装方針\n"
            "1. **XBRL** で標準タグ（asset coverage 等）を取得\n"
            "2. **テーブル抽出** で Non-accruals table を抽出（`pdfplumber`/`unstructured`）\n"
            "3. **正規表現フォールバック** でテキストから拾う\n"
            "BDCごとの記載差異に対応する `parsers/{ticker}.py` を必要に応じて用意\n\n"
            "## 受け入れ基準\n"
            "- [ ] BIZD上位12社全社で過去8四半期の抽出に成功\n"
            "- [ ] 抽出失敗時は null で続行（パイプラインを止めない）\n"
            "- [ ] Issue #3 の銘柄ドリルダウンで時系列チャート描画\n"
            "- [ ] CIで月次に再実行、新規10-Q公開を自動取得\n\n"
            "## 注意事項\n"
            "優先順位: ARCC, OBDC, MAIN, FSK, BXSL, GBDC（時価総額上位）から順次対応\n\n"
            + spec_link("2 Issue #2")
        ),
    },
    {
        "title": "[Phase1] #3 銘柄別ドリルダウン・ページ",
        "labels": ["phase-1"],
        "body": (
            "## 背景\n"
            "現状はアグリゲート・ビュー中心。銘柄ごとの統合ビューが基本ナビゲーションの中心であるべき。\n\n"
            "## 要件\n"
            "URL: `/#/entity/{ticker}` （SPA ハッシュルーティング）\n"
            "レイアウト: ヘッダー / KPIカード3列 / 価格×ニュース指標 / イベントタイムライン / "
            "直近記事 / 直近フィリング / ピア比較表\n\n"
            "## 実装方針\n"
            "- 既存フロントに **ハッシュルーティング** 導入\n"
            "- データは `data/entities/{ticker}.json` として事前ビルド時生成\n"
            "- 「By Entity」タブから銘柄カード一覧 → 個別ページ\n\n"
            "## 受け入れ基準\n"
            "- [ ] BIZD上位12社全社で個別ページ生成\n"
            "- [ ] 直リンク（`/#/entity/ARCC`）でアクセス可能\n"
            "- [ ] モバイル幅(375px)でレイアウト崩れなし\n"
            "- [ ] パンくず or 戻るボタンで Overview に戻れる\n\n"
            + spec_link("2 Issue #3")
        ),
    },
    {
        "title": "[Phase1] #4 BDCドメイン辞書オーバーレイ",
        "labels": ["phase-1"],
        "body": (
            "## 背景\n"
            "L-M辞書は強力だがBDC固有用語（amend and extend, covenant lite, second lien 等）に対して中立扱いが多い。\n\n"
            "## 要件\n"
            "`config/sentiment_overrides_bdc.yaml` を新設し、L-M結果へのオーバーレイ・ルールとして適用。\n"
            "30以上のBDC固有パターンを定義（amend and extend / covenant lite / first lien / "
            "second lien / PIK income / non-accrual / supplemental distribution / rights offering / ATM program / 等）\n\n"
            "## 実装方針\n"
            "- センチメント計算パイプラインの**最終段**で適用\n"
            "- 既存スコアへの加算（cap/floor: -1.0 / +1.0）\n"
            "- L-M / oseti 結果と並行保存（オーバーレイ前後を両方記録）\n\n"
            "## 受け入れ基準\n"
            "- [ ] 30以上のBDC固有パターンを定義\n"
            "- [ ] オーバーレイ前後を両方記録\n"
            "- [ ] About / Methodology に辞書の存在と仕組みを明記\n"
            "- [ ] 退行テスト: 既存記事でセンチメント分布の比較レポート\n\n"
            + spec_link("2 Issue #4")
        ),
    },
    {
        "title": "[Phase2] #5 ウォッチリスト機能",
        "labels": ["phase-2"],
        "body": (
            "## 要件\n"
            "- ヘッダーに「★ Watchlist」ボタン → モーダルでBDC選択\n"
            "- 選択銘柄は `localStorage` に保存（サーバー不要）\n"
            "- Overview で「Watchlist のみ表示」トグル\n"
            "- ピア比較表の表示優先度を Watchlist 銘柄に上げる\n\n"
            "## 受け入れ基準\n"
            "- [ ] localStorage キー: `bdc_monitor_watchlist`（JSON配列）\n"
            "- [ ] 別端末への同期は明示的にスコープ外\n"
            "- [ ] エクスポート: クリップボードに JSON コピー、インポート: ペースト\n\n"
            + spec_link("3 Issue #5")
        ),
    },
    {
        "title": "[Phase2] #6 アラート・パイプライン",
        "labels": ["phase-2"],
        "body": (
            "## 要件\n"
            "GitHub Actions の日次バッチ最後にチェックを行い、条件合致時に通知。\n"
            "- Heat指数急騰 / 新規8-K / センチメント急落 / Non-accrual言及記事\n"
            "- 通知チャネル: Slack / Email / Telegram (optional)\n\n"
            "## 実装方針\n"
            "- Webhook送信: `WEBHOOK_SLACK_URL` 等を GitHub Secrets に\n"
            "- Email: `dawidd6/action-send-mail@v3`\n"
            "- アラート履歴は `data/alerts_log.parquet` で永続化（重複抑制用）\n\n"
            "## 受け入れ基準\n"
            "- [ ] Slack webhook 送信が動作（テスト用チャンネル）\n"
            "- [ ] cooldown ロジックで24時間以内の重複通知抑制\n"
            "- [ ] アラート設定 YAML のバリデーション（CI）\n"
            "- [ ] 通知メッセージにダッシュボードへのディープリンク\n\n"
            + spec_link("3 Issue #6")
        ),
    },
    {
        "title": "[Phase2] #7 ヒートマップ・ビュー",
        "labels": ["phase-2"],
        "body": (
            "## 要件\n"
            "新規タブ「Heatmap」を追加。\n"
            "- 行: BIZD上位12社 / 列: 日付（90/180/365日切替）\n"
            "- セル色: 当日センチメント（赤-灰-緑 diverging）\n"
            "- ホバー: 当日記事リスト（最大5件）\n"
            "- クリック: 当該銘柄・当該日付フィルターで Articles ページへ\n\n"
            "## 実装方針\n"
            "- `d3.js` または Chart.js matrix プラグイン\n"
            "- 描画パフォーマンス: 12 × 365 = 4,380 セルなので canvas 推奨\n\n"
            "## 受け入れ基準\n"
            "- [ ] 過去 90/180/365 日切替動作\n"
            "- [ ] スコアレンジ: -1.0 〜 +1.0、colorblind-safe palette\n"
            "- [ ] エクスポート: PNG画像保存ボタン\n\n"
            + spec_link("3 Issue #7")
        ),
    },
    {
        "title": "[Phase2] #8 ピア相対センチメント・スコア",
        "labels": ["phase-2"],
        "body": (
            "## 背景\n"
            "個別BDCのセンチメントが「絶対値」で良くても、業界全体が良いと意味がない。**ピア相対化**が必要。\n\n"
            "## 計算式\n"
            "```\n"
            "relative_sentiment[t, d] = "
            "(sentiment[t, d] - mean(sentiment[peers, d])) / std(sentiment[peers, d])\n"
            "```\n\n"
            "- ピア集合: BIZD上位12社\n"
            "- 30日移動平均で平滑化\n"
            "- Overview / 銘柄ドリルダウンで切替（「絶対」 vs 「ピア相対」）\n\n"
            "## 受け入れ基準\n"
            "- [ ] 切替トグルが Overview / Entity ページに存在\n"
            "- [ ] z スコアの定義を About / Methodology に明記\n"
            "- [ ] バックテスト用ノートブック `notebooks/peer_relative_validation.ipynb`\n\n"
            + spec_link("3 Issue #8")
        ),
    },
    {
        "title": "[Phase3] #9 マクロ・オーバーレイ",
        "labels": ["phase-3"],
        "body": (
            "## 要件\n"
            "- HYG OAS（FRED: BAMLH0A0HYM2）, LSTA（プロキシ）, CCC default rate, BBB OAS を yfinance/FRED で取得\n"
            "- Overview のチャートに左軸/右軸切替で重ね描き\n\n"
            + spec_link("4 Issue #9")
        ),
    },
    {
        "title": "[Phase3] #10 トピックモデリング",
        "labels": ["phase-3"],
        "body": (
            "## 要件\n"
            "- BERTopic（オフラインで `sentence-transformers/all-MiniLM-L6-v2` 使用）でテーマ自動抽出\n"
            "- 「直近2週間で増えているテーマ」サイドパネル\n\n"
            + spec_link("4 Issue #10")
        ),
    },
    {
        "title": "[Phase3] #11 ダークモード／モバイル対応",
        "labels": ["phase-3"],
        "body": (
            "## 要件\n"
            "- CSS Variables ベースのトークン化\n"
            "- `prefers-color-scheme` 自動検出 + 手動切替\n"
            "- モバイル: 375px〜768px でチャート1列レイアウト\n\n"
            + spec_link("4 Issue #11")
        ),
    },
    {
        "title": "[Phase3] #12 データ品質ゲート",
        "labels": ["phase-3"],
        "body": (
            "## 要件\n"
            "- pandera / pydantic でスキーマ検証\n"
            "- syndicated copy 検出（タイトル fuzzy match + 公開時刻近接）\n"
            "- CIで品質メトリクス（欠損率、重複率）を出力\n\n"
            + spec_link("4 Issue #12")
        ),
    },
    {
        "title": "[Phase3] #13 ユニバース拡張",
        "labels": ["phase-3"],
        "body": (
            "## 要件\n"
            "- BIZD外: PSEC, TSLX, FDUS, OCSL 等\n"
            "- Interval funds（CION, OFS 等）\n"
            "- `config/universe.yaml` で管理\n\n"
            + spec_link("4 Issue #13")
        ),
    },
]


def ensure_issues() -> None:
    status, existing = gh("GET", "/issues?state=all&per_page=100")
    existing_titles = (
        {x["title"] for x in existing} if isinstance(existing, list) else set()
    )
    created = 0
    skipped = 0
    for spec in ISSUES:
        if spec["title"] in existing_titles:
            print(f"  · issue exists: {spec['title']}")
            skipped += 1
            continue
        code, resp = gh("POST", "/issues", spec)
        if code in (200, 201):
            print(f"  ✓ #{resp['number']:>2} {spec['title']}")
            created += 1
        else:
            print(f"  ✗ failed: {spec['title']} → {code} {resp.get('message', '')}")
    print(f"\nIssues: {created} created, {skipped} skipped")


def main() -> int:
    if "GH_TOKEN" not in os.environ:
        print("ERROR: GH_TOKEN env var not set", file=sys.stderr)
        return 1
    print("== Labels ==")
    ensure_labels()
    print("\n== Issues ==")
    ensure_issues()
    return 0


if __name__ == "__main__":
    sys.exit(main())
