/* BDC News Monitor — static dashboard */
(() => {
  const state = {
    daily: [],
    monthly: [],
    articles: [],
    prices: { series: {} },
    entities: [],
    meta: {},
    articleCursor: 50,
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
    wireTabs();
    wireControls();
    try {
      await Promise.all([
        loadJSON("data/daily_index.json").then((d) => (state.daily = (d && d.items) || [])),
        loadJSON("data/monthly_index.json").then((d) => (state.monthly = (d && d.items) || [])),
        loadJSON("data/articles.json").then((d) => (state.articles = (d && d.items) || [])),
        loadJSON("data/prices.json").then((d) => (state.prices = d || { series: {} })),
        loadJSON("data/by_entity.json").then((d) => (state.entities = (d && d.items) || [])),
        loadJSON("data/meta.json").then((d) => (state.meta = d || {})),
      ]);
    } catch (e) {
      console.warn("Some data failed to load:", e);
    }
    renderHeader();
    populatePriceSymbols();
    renderAll();
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
        const id = btn.dataset.tab;
        document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(`tab-${id}`).classList.add("active");
        if (id === "entities") renderEntities();
        if (id === "articles") renderArticles();
      });
    });
  }

  function wireControls() {
    ["range-select", "region-select", "freq-select"].forEach((id) =>
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
    document.getElementById("load-more").addEventListener("click", () => {
      state.articleCursor += 50;
      renderArticles();
    });
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

  // --------------------------------------------------------- rendering all
  function renderAll() {
    renderOverviewCharts();
    renderOverlayChart();
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
    if (freq === "D") return rows;
    return rollup(rows, freq);
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
    // ISO week Monday
    const day = (d.getUTCDay() + 6) % 7;
    d.setUTCDate(d.getUTCDate() - day);
    return d.toISOString().slice(0, 10);
  }

  // --------------------------------------------------------- overview charts
  function renderOverviewCharts() {
    const rows = filteredDaily();
    const x = rows.map((r) => r.date);
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
          y: rows.map((r) => r.sent_weighted),
          type: "scatter",
          mode: "lines+markers",
          line: { color: "#e6edf3", width: 2 },
          marker: { size: 4 },
          name: "センチメント指数",
        },
      ],
      {
        ...plotlyLayoutBase,
        yaxis: { ...plotlyLayoutBase.yaxis, title: "index", range: [-1, 1], zeroline: true, zerolinecolor: "#444" },
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

  // -------------------------------------------------------------- entities
  function renderEntities() {
    const host = document.getElementById("entities-table");
    if (!state.entities.length) {
      host.innerHTML = "<p>エンティティデータが未生成です。</p>";
      Plotly.purge("entities-chart");
      return;
    }
    const rows = state.entities
      .map(
        (e) => `
        <tr>
          <td><b>${e.symbol}</b></td><td>${e.name}</td>
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

    // Monthly heatmap for top N entities
    const top = state.entities.slice(0, 12);
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
    let rows = state.articles.slice();
    if (q) rows = rows.filter((r) => (r.title + " " + (r.snippet || "")).toLowerCase().includes(q));
    if (label) rows = rows.filter((r) => r.label === label);
    if (region) rows = rows.filter((r) => r.region === region);
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
          <td>${a.label ? `<span class="label-pill ${a.label}">${a.label}</span>` : "—"}</td>
          <td>${a.sentiment == null ? "—" : a.sentiment.toFixed(3)}</td>
        </tr>`
      )
      .join("");
    document.getElementById("load-more").style.display =
      rows.length > state.articleCursor ? "" : "none";
  }

  function escapeHTML(s) {
    return (s || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }
})();
