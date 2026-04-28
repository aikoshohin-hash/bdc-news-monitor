/* BDC News Monitor — static dashboard */
(() => {
  const state = {
    daily: [],
    monthly: [],
    articles: [],
    prices: { series: {} },
    entities: [],
    quarterly: { series: {} },
    meta: {},
    articleCursor: 50,
    activeTicker: null,
    watchlist: new Set(),
    wlFilterActive: false,
  };

  const plotlyConfig = { displayModeBar: false, responsive: true };
  const plotlyLayoutBase = {
    paper_bgcolor: "#161b22",
    plot_bgcolor: "#161b22",
    font: { color: "#e6edf3", size: 11 },
    margin: { l: 48, r: 32, t: 24, b: 40 },
    xaxis: { gridcolor: "#222a33" },
    yaxis: { gridcolor: "#222a33" },
    legend: { orientation: "h", y: -0.18 },
  };

  // ------------------------------------------------------------ init / load
  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    loadWatchlist();
    wireTabs();
    wireControls();
    wireWatchlist();
    try {
      await Promise.all([
        loadJSON("data/daily_index.json").then((d) => (state.daily = (d && d.items) || [])),
        loadJSON("data/monthly_index.json").then((d) => (state.monthly = (d && d.items) || [])),
        loadJSON("data/articles.json").then((d) => (state.articles = (d && d.items) || [])),
        loadJSON("data/prices.json").then((d) => (state.prices = d || { series: {} })),
        loadJSON("data/by_entity.json").then((d) => (state.entities = (d && d.items) || [])),
        loadJSON("data/quarterly_metrics.json").then(
          (d) => (state.quarterly = d || { series: {} })
        ),
        loadJSON("data/meta.json").then((d) => (state.meta = d || {})),
      ]);
    } catch (e) {
      console.warn("Some data failed to load:", e);
    }
    renderHeader();
    populatePriceSymbols();
    populateEventOptions();
    renderAll();
    wireRouter();
    handleRoute();
  }

  async function loadJSON(url) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) throw new Error(`${url} -> ${r.status}`);
      return await r.json();
    } catch (e) {
      console.warn("fetch failed", url, e);
      return null;
    }
  }

  // --------------------------------------------------------- UI wire-ups
  function wireTabs() {
    document.querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (location.hash) {
          location.hash = "";
        }
        const id = btn.dataset.tab;
        document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(`tab-${id}`).classList.add("active");
        if (id === "entities") renderEntities();
        if (id === "articles") renderArticles();
        if (id === "heatmap") renderHeatmap();
      });
    });
  }

  function wireControls() {
    ["range-select", "region-select", "freq-select", "sent-mode"].forEach((id) =>
      document.getElementById(id).addEventListener("change", renderOverviewCharts)
    );
    ["price-symbol", "news-metric", "rebase-chk"].forEach((id) =>
      document.getElementById(id).addEventListener("change", renderOverlayChart)
    );
    ["article-search", "article-label", "article-region"].forEach((id) =>
      document.getElementById(id).addEventListener("input", () => {
        state.articleCursor = 50;
        renderArticles();
      })
    );
    document.getElementById("article-events").addEventListener("change", () => {
      state.articleCursor = 50;
      renderArticles();
    });
    document.getElementById("load-more").addEventListener("click", () => {
      state.articleCursor += 50;
      renderArticles();
    });
    document.getElementById("entity-wl-only").addEventListener("change", renderEntities);
    // Heatmap controls
    document.getElementById("heatmap-range").addEventListener("change", renderHeatmap);
    document.getElementById("heatmap-mode").addEventListener("change", renderHeatmap);
    document.getElementById("heatmap-export").addEventListener("click", () => {
      Plotly.downloadImage("chart-heatmap", { format: "png", width: 1400, height: 600, filename: "bdc_heatmap" });
    });
  }

  // =========================================================================
  // Issue #5 — Watchlist (localStorage)
  // =========================================================================
  const WL_KEY = "bdc_watchlist";

  function loadWatchlist() {
    try {
      const raw = localStorage.getItem(WL_KEY);
      if (raw) {
        const arr = JSON.parse(raw);
        if (Array.isArray(arr)) arr.forEach((s) => state.watchlist.add(s));
      }
    } catch (_) { /* ignore */ }
  }

  function saveWatchlist() {
    localStorage.setItem(WL_KEY, JSON.stringify([...state.watchlist]));
  }

  function wireWatchlist() {
    const btn = document.getElementById("watchlist-btn");
    const modal = document.getElementById("watchlist-modal");
    const closeBtn = document.getElementById("watchlist-close");
    btn.addEventListener("click", () => {
      renderWatchlistGrid();
      modal.hidden = false;
    });
    closeBtn.addEventListener("click", () => (modal.hidden = true));
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.hidden = true;
    });
    document.getElementById("wl-export").addEventListener("click", exportWatchlist);
    document.getElementById("wl-import").addEventListener("click", importWatchlist);
    document.getElementById("wl-filter-chk").addEventListener("change", (e) => {
      state.wlFilterActive = e.target.checked;
      renderAll();
    });
  }

  function renderWatchlistGrid() {
    const grid = document.getElementById("watchlist-grid");
    const tickers = state.entities.map((e) => e.symbol).sort();
    if (!tickers.length) {
      grid.innerHTML = '<span style="color:var(--muted);font-size:12px">エンティティデータ未読み込み</span>';
      return;
    }
    grid.innerHTML = tickers
      .map((t) => {
        const sel = state.watchlist.has(t) ? "selected" : "";
        return `<div class="wl-chip ${sel}" data-sym="${t}">${t}</div>`;
      })
      .join("");
    grid.querySelectorAll(".wl-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const sym = chip.dataset.sym;
        if (state.watchlist.has(sym)) {
          state.watchlist.delete(sym);
          chip.classList.remove("selected");
        } else {
          state.watchlist.add(sym);
          chip.classList.add("selected");
        }
        saveWatchlist();
      });
    });
  }

  function exportWatchlist() {
    const blob = new Blob([JSON.stringify([...state.watchlist], null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "bdc_watchlist.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function importWatchlist() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.addEventListener("change", () => {
      const file = input.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const arr = JSON.parse(reader.result);
          if (Array.isArray(arr)) {
            state.watchlist.clear();
            arr.forEach((s) => state.watchlist.add(String(s)));
            saveWatchlist();
            renderWatchlistGrid();
          }
        } catch (_) {
          alert("JSONの読み込みに失敗しました");
        }
      };
      reader.readAsText(file);
    });
    input.click();
  }

  function isInWatchlist(ticker) {
    return state.watchlist.size === 0 || !state.wlFilterActive || state.watchlist.has(ticker);
  }

  // ----------------------------------------------------------------- header
  function renderHeader() {
    const updated = state.meta.generated_at
      ? new Date(state.meta.generated_at).toLocaleString()
      : "—";
    document.getElementById("updated").textContent = `更新日時: ${updated}`;
    const total = state.articles.length;
    document.getElementById("article-count").textContent = `関連記事: ${total}件`;
  }

  function populatePriceSymbols() {
    const sel = document.getElementById("price-symbol");
    const syms = Object.keys(state.prices.series || {}).sort();
    sel.innerHTML = "";
    syms.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      if (s === "BIZD") opt.selected = true;
      sel.appendChild(opt);
    });
    if (!syms.length) {
      const opt = document.createElement("option");
      opt.textContent = "(株価データ未生成)";
      opt.disabled = true;
      sel.appendChild(opt);
    }
  }

  function populateEventOptions() {
    const sel = document.getElementById("article-events");
    if (!sel) return;
    const counts = new Map();
    for (const a of state.articles) {
      for (const t of a.event_tags || []) {
        counts.set(t, (counts.get(t) || 0) + 1);
      }
    }
    const tags = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    sel.innerHTML = "";
    if (!tags.length) {
      const opt = document.createElement("option");
      opt.textContent = "(イベントタグ未生成)";
      opt.disabled = true;
      sel.appendChild(opt);
      return;
    }
    for (const [tag, n] of tags) {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = `${tag} (${n})`;
      sel.appendChild(opt);
    }
  }

  // --------------------------------------------------------- rendering all
  function renderAll() {
    renderOverviewCharts();
    renderOverlayChart();
  }

  // =========================================================================
  // Issue #8 — Peer-relative sentiment (z-score)
  // =========================================================================
  function computePeerRelative(dailyRows) {
    const byDate = new Map();
    for (const r of state.daily) {
      if (r.region !== "all") continue;
      const key = r.date;
      if (!byDate.has(key)) byDate.set(key, []);
      byDate.get(key).push(r);
    }
    return dailyRows.map((r) => {
      const peers = byDate.get(r.date) || [];
      if (peers.length < 2) return { ...r, sent_weighted: 0 };
      const vals = peers.map((p) => p.sent_weighted || 0);
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      const std = Math.sqrt(vals.reduce((a, v) => a + (v - mean) ** 2, 0) / vals.length) || 1;
      return { ...r, sent_weighted: (r.sent_weighted - mean) / std };
    });
  }

  function computeEntityPeerRelative(articles, ticker) {
    const bdcTickers = state.entities.map((e) => e.symbol);
    const byDate = new Map();
    for (const a of state.articles) {
      if (a.sentiment == null || !a.published_at) continue;
      const d = a.published_at.slice(0, 10);
      for (const t of bdcTickers) {
        if (!mentionsTicker(a, t)) continue;
        if (!byDate.has(d)) byDate.set(d, new Map());
        const dm = byDate.get(d);
        if (!dm.has(t)) dm.set(t, { sum: 0, n: 0 });
        const b = dm.get(t);
        b.sum += a.sentiment;
        b.n += 1;
      }
    }
    const result = [];
    for (const [date, dm] of byDate) {
      if (!dm.has(ticker)) continue;
      const vals = [...dm.values()].filter((v) => v.n > 0).map((v) => v.sum / v.n);
      if (vals.length < 2) continue;
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      const std = Math.sqrt(vals.reduce((a, v) => a + (v - mean) ** 2, 0) / vals.length) || 1;
      const tickerMean = dm.get(ticker).sum / dm.get(ticker).n;
      result.push({ date, sent: (tickerMean - mean) / std });
    }
    return result.sort((a, b) => a.date.localeCompare(b.date));
  }

  function ma(arr, window) {
    const out = [];
    for (let i = 0; i < arr.length; i++) {
      const start = Math.max(0, i - window + 1);
      const slice = arr.slice(start, i + 1);
      out.push(slice.reduce((a, b) => a + b, 0) / slice.length);
    }
    return out;
  }

  // ------------------------------------------------------- filter helpers
  function filteredDaily() {
    const range = document.getElementById("range-select").value;
    const region = document.getElementById("region-select").value;
    const freq = document.getElementById("freq-select").value;
    const cutoff = rangeCutoff(range);
    let rows = state.daily.filter((r) => r.region === region);
    if (cutoff) rows = rows.filter((r) => r.date >= cutoff);
    rows.sort((a, b) => a.date.localeCompare(b.date));
    if (freq !== "D") rows = rollup(rows, freq);
    const mode = document.getElementById("sent-mode").value;
    if (mode === "peer_relative") rows = computePeerRelative(rows);
    return rows;
  }

  function rangeCutoff(range) {
    if (range === "ALL") return null;
    const d = new Date();
    if (range.endsWith("M")) d.setMonth(d.getMonth() - parseInt(range));
    if (range.endsWith("Y")) d.setFullYear(d.getFullYear() - parseInt(range));
    return d.toISOString().slice(0, 10);
  }

  function rollup(rows, freq) {
    const bucket = new Map();
    const keyFn = (d) => (freq === "W" ? weekKey(d) : d.slice(0, 7));
    for (const r of rows) {
      const k = keyFn(r.date);
      if (!bucket.has(k))
        bucket.set(k, { date: k, n_articles: 0, sum_s_w: 0, w: 0, pos: 0, neg: 0, heat: 0 });
      const b = bucket.get(k);
      b.n_articles += r.n_articles;
      b.sum_s_w += (r.sent_weighted || 0) * r.n_articles;
      b.w += r.n_articles;
      b.pos += (r.pos_ratio || 0) * r.n_articles;
      b.neg += (r.neg_ratio || 0) * r.n_articles;
      b.heat += (r.heat_index || 0) * r.n_articles;
    }
    return [...bucket.values()]
      .map((b) => ({
        date: b.date,
        region: rows[0] ? rows[0].region : "all",
        n_articles: b.n_articles,
        sent_weighted: b.w ? b.sum_s_w / b.w : 0,
        pos_ratio: b.w ? b.pos / b.w : 0,
        neg_ratio: b.w ? b.neg / b.w : 0,
        heat_index: b.w ? b.heat / b.w : 0,
      }))
      .sort((a, b) => a.date.localeCompare(b.date));
  }

  function weekKey(dateStr) {
    const d = new Date(dateStr);
    const day = (d.getUTCDay() + 6) % 7;
    d.setUTCDate(d.getUTCDate() - day);
    return d.toISOString().slice(0, 10);
  }

  // --------------------------------------------------------- overview charts
  function renderOverviewCharts() {
    const rows = filteredDaily();
    const x = rows.map((r) => r.date);
    const isPeerRel = document.getElementById("sent-mode").value === "peer_relative";
    Plotly.newPlot(
      "chart-counts",
      [
        {
          x,
          y: rows.map((r) => r.n_articles),
          type: "bar",
          marker: { color: "#58a6ff" },
          name: "件数",
        },
      ],
      {
        ...plotlyLayoutBase,
        yaxis: { ...plotlyLayoutBase.yaxis, title: "件数" },
      },
      plotlyConfig
    );

    Plotly.newPlot(
      "chart-sentiment",
      [
        {
          x,
          y: isPeerRel ? ma(rows.map((r) => r.sent_weighted), 30) : rows.map((r) => r.sent_weighted),
          type: "scatter",
          mode: "lines+markers",
          line: { color: "#e6edf3", width: 2 },
          marker: { size: 4 },
          name: isPeerRel ? "z-score (30d MA)" : "センチメント指数",
        },
      ],
      {
        ...plotlyLayoutBase,
        yaxis: {
          ...plotlyLayoutBase.yaxis,
          title: isPeerRel ? "z-score" : "index",
          range: isPeerRel ? [-3, 3] : [-1, 1],
          zeroline: true,
          zerolinecolor: "#444",
        },
      },
      plotlyConfig
    );

    Plotly.newPlot(
      "chart-posneg",
      [
        {
          x,
          y: rows.map((r) => r.pos_ratio),
          name: "positive",
          type: "scatter",
          stackgroup: "one",
          line: { color: "#3fb950" },
        },
        {
          x,
          y: rows.map((r) => 1 - r.pos_ratio - r.neg_ratio),
          name: "neutral",
          type: "scatter",
          stackgroup: "one",
          line: { color: "#8b949e" },
        },
        {
          x,
          y: rows.map((r) => r.neg_ratio),
          name: "negative",
          type: "scatter",
          stackgroup: "one",
          line: { color: "#f85149" },
        },
      ],
      {
        ...plotlyLayoutBase,
        yaxis: { ...plotlyLayoutBase.yaxis, title: "ratio", range: [0, 1] },
      },
      plotlyConfig
    );

    renderOverlayChart();
  }

  // ---------------------------------------------------------- overlay chart
  function renderOverlayChart() {
    const rows = filteredDaily();
    const metric = document.getElementById("news-metric").value;
    const rebase = document.getElementById("rebase-chk").checked;
    const symSel = document.getElementById("price-symbol");
    const selected = [...symSel.selectedOptions].map((o) => o.value).filter(Boolean);

    const traces = [];
    traces.push({
      x: rows.map((r) => r.date),
      y: rows.map((r) => r[metric]),
      name: `news: ${metric}`,
      yaxis: "y",
      type: "scatter",
      mode: "lines",
      line: { color: "#58a6ff", width: 2 },
    });

    for (const sym of selected) {
      const series = (state.prices.series || {})[sym] || [];
      if (!series.length) continue;
      const cutoff = rangeCutoff(document.getElementById("range-select").value);
      let rows2 = cutoff ? series.filter((p) => p.date >= cutoff) : series.slice();
      if (rebase && rows2.length) {
        const base = rows2[0].close;
        rows2 = rows2.map((p) => ({ date: p.date, close: (p.close / base) * 100 }));
      }
      traces.push({
        x: rows2.map((p) => p.date),
        y: rows2.map((p) => p.close),
        name: sym,
        yaxis: "y2",
        type: "scatter",
        mode: "lines",
        line: { width: 1.5 },
      });
    }

    const layout = {
      ...plotlyLayoutBase,
      xaxis: { ...plotlyLayoutBase.xaxis },
      yaxis: { ...plotlyLayoutBase.yaxis, title: metric },
      yaxis2: {
        title: rebase ? "price (2024-01-01 = 100)" : "price",
        overlaying: "y",
        side: "right",
        gridcolor: "#222a33",
      },
      legend: { orientation: "h", y: -0.2 },
    };
    Plotly.newPlot("chart-overlay", traces, layout, plotlyConfig);
  }

  // =========================================================================
  // Issue #7 — Heatmap (BDC × date sentiment matrix)
  // =========================================================================
  function renderHeatmap() {
    const rangeDays = parseInt(document.getElementById("heatmap-range").value) || 180;
    const mode = document.getElementById("heatmap-mode").value;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - rangeDays);
    const cutoffStr = cutoff.toISOString().slice(0, 10);

    const bdcTickers = state.entities
      .filter((e) => e.n > 0)
      .sort((a, b) => b.n - a.n)
      .map((e) => e.symbol);
    if (!bdcTickers.length) {
      document.getElementById("chart-heatmap").innerHTML =
        '<p style="padding:24px;color:var(--muted);font-size:12px">エンティティデータなし</p>';
      return;
    }

    const byTickerDate = new Map();
    for (const a of state.articles) {
      if (!a.published_at || a.sentiment == null) continue;
      const d = a.published_at.slice(0, 10);
      if (d < cutoffStr) continue;
      for (const t of bdcTickers) {
        if (!mentionsTicker(a, t)) continue;
        const key = `${t}|${d}`;
        if (!byTickerDate.has(key)) byTickerDate.set(key, { sum: 0, n: 0 });
        const b = byTickerDate.get(key);
        b.sum += a.sentiment;
        b.n += 1;
      }
    }

    const dates = [...new Set([...byTickerDate.keys()].map((k) => k.split("|")[1]))].sort();
    const z = [];
    for (const ticker of bdcTickers) {
      const row = dates.map((d) => {
        const b = byTickerDate.get(`${ticker}|${d}`);
        return b ? b.sum / b.n : null;
      });
      z.push(row);
    }

    if (mode === "peer_relative") {
      for (let j = 0; j < dates.length; j++) {
        const col = z.map((row) => row[j]).filter((v) => v !== null);
        if (col.length < 2) continue;
        const mean = col.reduce((a, b) => a + b, 0) / col.length;
        const std = Math.sqrt(col.reduce((a, v) => a + (v - mean) ** 2, 0) / col.length) || 1;
        for (let i = 0; i < z.length; i++) {
          if (z[i][j] !== null) z[i][j] = (z[i][j] - mean) / std;
        }
      }
    }

    const zmin = mode === "peer_relative" ? -2.5 : -1;
    const zmax = mode === "peer_relative" ? 2.5 : 1;

    Plotly.newPlot(
      "chart-heatmap",
      [
        {
          type: "heatmap",
          x: dates,
          y: bdcTickers,
          z,
          zmin,
          zmax,
          colorscale: [
            [0, "#d73027"],
            [0.25, "#fc8d59"],
            [0.5, "#ffffbf"],
            [0.75, "#91bfdb"],
            [1, "#4575b4"],
          ],
          colorbar: {
            title: mode === "peer_relative" ? "z-score" : "sentiment",
            titleside: "right",
          },
          hoverongaps: false,
          hovertemplate: "%{y} | %{x}<br>%{z:.3f}<extra></extra>",
        },
      ],
      {
        ...plotlyLayoutBase,
        yaxis: { ...plotlyLayoutBase.yaxis, autorange: "reversed", automargin: true },
        margin: { l: 64, r: 24, t: 12, b: 48 },
      },
      plotlyConfig
    );
  }

  // -------------------------------------------------------------- entities
  function renderEntities() {
    const host = document.getElementById("entities-table");
    const wlOnly = document.getElementById("entity-wl-only").checked;
    let ents = state.entities.slice();
    if (wlOnly && state.watchlist.size > 0) {
      ents = ents.filter((e) => state.watchlist.has(e.symbol));
    }
    if (!ents.length) {
      host.innerHTML = "<p>エンティティデータが未生成です。</p>";
      Plotly.purge("entities-chart");
      return;
    }
    const rows = ents
      .map(
        (e) => `
        <tr>
          <td><a class="entity-link" href="#/entity/${e.symbol}"><b>${e.symbol}</b></a></td><td>${e.name}</td>
          <td>${e.n}</td><td>${e.pos}</td><td>${e.neg}</td>
          <td>${e.sent_mean.toFixed(3)}</td>
        </tr>`
      )
      .join("");
    host.innerHTML = `
      <table>
        <thead><tr>
          <th>Symbol</th><th>Name</th><th>件数</th>
          <th>Pos</th><th>Neg</th><th>平均Sent</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;

    const top = ents.slice(0, 12);
    const months = [
      ...new Set(top.flatMap((e) => e.by_month.map((m) => m.month))),
    ].sort();
    const z = top.map((e) =>
      months.map((m) => {
        const found = e.by_month.find((x) => x.month === m);
        return found ? found.n : 0;
      })
    );
    Plotly.newPlot(
      "entities-chart",
      [
        {
          type: "heatmap",
          x: months,
          y: top.map((e) => e.symbol),
          z,
          colorscale: [
            [0, "#161b22"],
            [0.3, "#1f6feb"],
            [1, "#58a6ff"],
          ],
          showscale: true,
        },
      ],
      {
        ...plotlyLayoutBase,
        yaxis: { ...plotlyLayoutBase.yaxis, autorange: "reversed" },
        margin: { l: 64, r: 32, t: 24, b: 48 },
      },
      plotlyConfig
    );
  }

  // -------------------------------------------------------------- articles
  function renderArticles() {
    const q = (document.getElementById("article-search").value || "").toLowerCase();
    const label = document.getElementById("article-label").value;
    const region = document.getElementById("article-region").value;
    const eventSel = document.getElementById("article-events");
    const selectedEvents = eventSel
      ? [...eventSel.selectedOptions].map((o) => o.value).filter(Boolean)
      : [];
    let rows = state.articles.slice();
    if (q) rows = rows.filter((r) => (r.title + " " + (r.snippet || "")).toLowerCase().includes(q));
    if (label) rows = rows.filter((r) => r.label === label);
    if (region) rows = rows.filter((r) => r.region === region);
    if (selectedEvents.length) {
      rows = rows.filter((r) => {
        const tags = r.event_tags || [];
        return selectedEvents.some((t) => tags.includes(t));
      });
    }
    const slice = rows.slice(0, state.articleCursor);
    const tbody = document.querySelector("#article-table tbody");
    tbody.innerHTML = slice
      .map(
        (a) => `
        <tr>
          <td>${(a.published_at || "").slice(0, 10)}</td>
          <td>${a.source || ""}</td>
          <td>${a.region || ""}</td>
          <td><a href="${a.url}" target="_blank" rel="noopener">${escapeHTML(a.title)}</a></td>
          <td>${renderEventBadges(a)}</td>
          <td>${a.label ? `<span class="label-pill ${a.label}">${a.label}</span>` : "—"}</td>
          <td>${a.sentiment == null ? "—" : a.sentiment.toFixed(3)}</td>
        </tr>`
      )
      .join("");
    document.getElementById("load-more").style.display =
      rows.length > state.articleCursor ? "" : "none";
  }

  function renderEventBadges(a) {
    const tags = a.event_tags || [];
    if (!tags.length) return "—";
    const sev = a.event_severity || "";
    return tags
      .map(
        (t) =>
          `<span class="event-badge sev-${escapeHTML(sev)}" title="${escapeHTML(t)}">${escapeHTML(
            t
          )}</span>`
      )
      .join(" ");
  }

  function escapeHTML(s) {
    return (s || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  // =========================================================================
  // Issue #3 — per-entity drilldown
  // =========================================================================
  function wireRouter() {
    window.addEventListener("hashchange", handleRoute);
    const back = document.getElementById("entity-back");
    if (back) {
      back.addEventListener("click", (e) => {
        e.preventDefault();
        location.hash = "";
      });
    }
  }

  function handleRoute() {
    const m = (location.hash || "").match(/^#\/entity\/([A-Za-z0-9._-]+)/);
    if (!m) {
      showOverview();
      return;
    }
    const ticker = m[1].toUpperCase();
    state.activeTicker = ticker;
    showEntity(ticker);
  }

  function showOverview() {
    document.getElementById("entity-detail").hidden = true;
    document.querySelector("main").hidden = false;
    document.querySelector(".tabs").hidden = false;
  }

  function showEntity(ticker) {
    const detail = document.getElementById("entity-detail");
    detail.hidden = false;
    document.querySelector("main").hidden = true;
    document.querySelector(".tabs").hidden = true;

    const entityRow = state.entities.find((e) => e.symbol === ticker);
    const fullName = entityRow ? entityRow.name : ticker;
    document.getElementById("entity-title").textContent = ticker;
    document.getElementById("entity-name").textContent = fullName;

    renderEntityPriceMeta(ticker);
    renderEntityKPIs(ticker);
    renderEntityOverlay(ticker);
    renderEntityEventTimeline(ticker);
    renderEntityMetricsTable(ticker);
    renderEntityArticles(ticker);
    renderEntityPeers(ticker);
    window.scrollTo({ top: 0 });
  }

  function renderEntityPriceMeta(ticker) {
    const series = (state.prices.series || {})[ticker] || [];
    const priceEl = document.getElementById("entity-price");
    const chgEl = document.getElementById("entity-change");
    if (series.length < 2) {
      priceEl.textContent = "";
      chgEl.textContent = "";
      return;
    }
    const last = series[series.length - 1];
    const prev = series[series.length - 2];
    const chg = last.close - prev.close;
    const chgPct = (chg / prev.close) * 100;
    priceEl.textContent = `$${last.close.toFixed(2)} (${last.date})`;
    chgEl.textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${chgPct.toFixed(2)}%)`;
    chgEl.className = chg >= 0 ? "pos" : "neg";
  }

  function renderEntityKPIs(ticker) {
    const series = ((state.quarterly.series || {})[ticker] || []).slice();
    series.sort((a, b) => (a.fiscal_period > b.fiscal_period ? 1 : -1));
    const last = series[series.length - 1] || null;
    const prev = series[series.length - 2] || null;

    setKPI("kpi-nav", "kpi-nav-d", last && last.nav_per_share, prev && prev.nav_per_share, "$");
    setKPI(
      "kpi-nii", "kpi-nii-d",
      last && last.net_investment_income_per_share,
      prev && prev.net_investment_income_per_share,
      "$"
    );
    setKPI(
      "kpi-cov", "kpi-cov-d",
      last && last.asset_coverage_ratio,
      prev && prev.asset_coverage_ratio,
      "",
      "x"
    );
  }

  function setKPI(valId, deltaId, cur, prev, prefix = "", suffix = "") {
    const v = document.getElementById(valId);
    const d = document.getElementById(deltaId);
    if (cur == null) {
      v.textContent = "—";
      d.textContent = "";
      d.className = "kpi-delta";
      return;
    }
    v.textContent = `${prefix}${Number(cur).toFixed(2)}${suffix}`;
    if (prev == null) {
      d.textContent = "前期データなし";
      d.className = "kpi-delta";
      return;
    }
    const diff = cur - prev;
    const pct = prev !== 0 ? (diff / prev) * 100 : 0;
    d.textContent = `${diff >= 0 ? "+" : ""}${diff.toFixed(2)} (${pct.toFixed(1)}%)`;
    d.className = "kpi-delta " + (diff >= 0 ? "pos" : "neg");
  }

  function renderEntityOverlay(ticker) {
    const priceSeries = (state.prices.series || {})[ticker] || [];
    const articleHits = state.articles.filter((a) => mentionsTicker(a, ticker));
    const byDate = new Map();
    for (const a of articleHits) {
      if (!a.published_at || a.sentiment == null) continue;
      const d = a.published_at.slice(0, 10);
      if (!byDate.has(d)) byDate.set(d, { sum: 0, n: 0 });
      const b = byDate.get(d);
      b.sum += a.sentiment;
      b.n += 1;
    }
    const sentRows = [...byDate.entries()]
      .map(([date, b]) => ({ date, sent: b.sum / b.n }))
      .sort((a, b) => a.date.localeCompare(b.date));

    const traces = [];
    if (sentRows.length) {
      traces.push({
        x: sentRows.map((r) => r.date),
        y: sentRows.map((r) => r.sent),
        name: "sentiment (daily mean)",
        yaxis: "y",
        type: "scatter",
        mode: "markers",
        marker: { color: "#58a6ff", size: 5 },
      });
    }
    if (priceSeries.length) {
      traces.push({
        x: priceSeries.map((p) => p.date),
        y: priceSeries.map((p) => p.close),
        name: `${ticker} close`,
        yaxis: "y2",
        type: "scatter",
        mode: "lines",
        line: { color: "#3fb950", width: 1.5 },
      });
    }
    const layout = {
      ...plotlyLayoutBase,
      xaxis: { ...plotlyLayoutBase.xaxis },
      yaxis: { ...plotlyLayoutBase.yaxis, title: "sentiment", range: [-1, 1], zeroline: true, zerolinecolor: "#444" },
      yaxis2: { title: "price ($)", overlaying: "y", side: "right", gridcolor: "#222a33" },
      legend: { orientation: "h", y: -0.2 },
    };
    Plotly.newPlot("entity-chart-overlay", traces, layout, plotlyConfig);
  }

  function renderEntityEventTimeline(ticker) {
    const hits = state.articles.filter((a) => mentionsTicker(a, ticker) && (a.event_tags || []).length);
    if (!hits.length) {
      Plotly.purge("entity-chart-events");
      const el = document.getElementById("entity-chart-events");
      el.innerHTML = '<div style="padding:24px;color:var(--muted);font-size:12px">イベントタグ付き記事なし</div>';
      return;
    }
    document.getElementById("entity-chart-events").innerHTML = "";
    const sevColor = { high: "#f85149", medium: "#d29922", low: "#8b949e" };
    const points = [];
    for (const a of hits) {
      if (!a.published_at) continue;
      const d = a.published_at.slice(0, 10);
      for (const t of a.event_tags) {
        points.push({
          x: d,
          y: t,
          color: sevColor[a.event_severity] || "#58a6ff",
          text: `${(a.title || "").slice(0, 80)}<br>${a.source || ""}`,
        });
      }
    }
    const traces = [
      {
        x: points.map((p) => p.x),
        y: points.map((p) => p.y),
        text: points.map((p) => p.text),
        hovertemplate: "%{x}<br>%{y}<br>%{text}<extra></extra>",
        type: "scatter",
        mode: "markers",
        marker: { color: points.map((p) => p.color), size: 9, line: { width: 0.5, color: "#0f1419" } },
      },
    ];
    Plotly.newPlot(
      "entity-chart-events",
      traces,
      {
        ...plotlyLayoutBase,
        yaxis: { ...plotlyLayoutBase.yaxis, automargin: true, tickfont: { size: 10 } },
        margin: { l: 140, r: 32, t: 12, b: 32 },
      },
      plotlyConfig
    );
  }

  function renderEntityMetricsTable(ticker) {
    const series = ((state.quarterly.series || {})[ticker] || []).slice();
    if (!series.length) {
      document.getElementById("entity-metrics-table").innerHTML =
        '<p style="color:var(--muted);font-size:12px">XBRLメトリクス未取得（CIキャッシュ生成後に表示）</p>';
      return;
    }
    series.sort((a, b) => (a.fiscal_period > b.fiscal_period ? -1 : 1));
    const fmt = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
    const fmtBig = (v) => (v == null ? "—" : `$${(v / 1e9).toFixed(2)}B`);
    const rows = series
      .map(
        (r) => `
        <tr>
          <td>${escapeHTML(r.fiscal_period)}</td>
          <td>${escapeHTML(r.form_type || "")}</td>
          <td>${escapeHTML(r.filing_date || "")}</td>
          <td>${fmt(r.nav_per_share, 4)}</td>
          <td>${fmt(r.net_investment_income_per_share, 4)}</td>
          <td>${fmt(r.distribution_per_share, 4)}</td>
          <td>${fmtBig(r.total_investments_at_fair_value)}</td>
          <td>${fmt(r.asset_coverage_ratio)}</td>
        </tr>`
      )
      .join("");
    document.getElementById("entity-metrics-table").innerHTML = `
      <table>
        <thead><tr>
          <th>期</th><th>Form</th><th>提出日</th>
          <th>NAV/株</th><th>NII/株</th><th>配当/株</th>
          <th>投資額(時価)</th><th>Asset Cov.</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function renderEntityArticles(ticker) {
    const hits = state.articles
      .filter((a) => mentionsTicker(a, ticker))
      .slice()
      .sort((a, b) => (b.published_at || "").localeCompare(a.published_at || ""))
      .slice(0, 25);
    if (!hits.length) {
      document.getElementById("entity-articles").innerHTML =
        '<p style="color:var(--muted);font-size:12px">該当記事なし</p>';
      return;
    }
    const rows = hits
      .map(
        (a) => `
        <tr>
          <td>${(a.published_at || "").slice(0, 10)}</td>
          <td>${escapeHTML(a.source || "")}</td>
          <td><a href="${a.url}" target="_blank" rel="noopener">${escapeHTML(a.title)}</a></td>
          <td>${renderEventBadges(a)}</td>
          <td>${a.label ? `<span class="label-pill ${a.label}">${a.label}</span>` : "—"}</td>
        </tr>`
      )
      .join("");
    document.getElementById("entity-articles").innerHTML = `
      <table>
        <thead><tr><th>日付</th><th>媒体</th><th>タイトル</th><th>イベント</th><th>ラベル</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function renderEntityPeers(ticker) {
    const sortedPeers = state.entities.slice().sort((a, b) => b.n - a.n);
    const focus = state.entities.find((e) => e.symbol === ticker);
    const top5 = sortedPeers.filter((e) => e.symbol !== ticker).slice(0, 5);
    const rows = (focus ? [focus, ...top5] : top5)
      .map((e) => {
        const q = ((state.quarterly.series || {})[e.symbol] || []).slice();
        q.sort((a, b) => (a.fiscal_period > b.fiscal_period ? 1 : -1));
        const last = q[q.length - 1] || {};
        const isFocus = e.symbol === ticker;
        const fmt = (v, dp = 2) => (v == null ? "—" : Number(v).toFixed(dp));
        return `
          <tr>
            <td>${isFocus ? "<b>" + e.symbol + "</b>" : `<a class="entity-link" href="#/entity/${e.symbol}">${e.symbol}</a>`}</td>
            <td>${escapeHTML(e.name)}</td>
            <td>${e.n}</td>
            <td>${fmt(e.sent_mean, 3)}</td>
            <td>${fmt(last.nav_per_share, 4)}</td>
            <td>${fmt(last.net_investment_income_per_share, 4)}</td>
            <td>${fmt(last.asset_coverage_ratio)}</td>
          </tr>`;
      })
      .join("");
    document.getElementById("entity-peers").innerHTML = `
      <table>
        <thead><tr>
          <th>Symbol</th><th>Name</th><th>記事数</th><th>平均Sent</th>
          <th>NAV/株</th><th>NII/株</th><th>Asset Cov.</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function mentionsTicker(article, ticker) {
    const blob = `${article.title || ""} ${article.snippet || ""}`.toLowerCase();
    if (blob.includes(ticker.toLowerCase())) return true;
    const entity = state.entities.find((e) => e.symbol === ticker);
    if (entity && entity.name && blob.includes(entity.name.toLowerCase())) return true;
    return false;
  }
})();
