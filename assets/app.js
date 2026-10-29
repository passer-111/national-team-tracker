/* A股国家队持仓跟踪 —— 静态看板（无外部依赖，图表为原生 SVG） */

const state = {
  meta: null,
  holdings: null,
  etf: null,
  group: "all",
  flow: "all",
  period: null,
  sortKey: "latest_value",
  sortDir: -1,
  keyword: "",
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- 格式化
const fmtYi = (v) => (v == null ? "—" : (v / 1e8).toFixed(1) + " 亿");
const fmtWan = (v) => (v == null ? "—" : (v / 1e4).toFixed(1) + " 万");
const fmtShares = (v) => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + " 亿股";
  return (v / 1e4).toFixed(1) + " 万股";
};
const fmtPct = (v, digits = 2) =>
  v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(digits) + "%";
const fmtDate = (p) => (p ? `${p.slice(0, 4)}-${p.slice(4, 6)}-${p.slice(6)}` : "—");
const cls = (v) => (v == null || v === 0 ? "zero" : v > 0 ? "up" : "down");

// ---------------------------------------------------------------- 数据加载
async function loadData() {
  $("loading").hidden = false;
  $("error").hidden = true;
  try {
    const [meta, holdings, etf] = await Promise.all([
      fetch("data/meta.json").then((r) => r.json()),
      fetch("data/holdings.json").then((r) => r.json()),
      fetch("data/etf.json").then((r) => r.json()),
    ]);
    state.meta = meta;
    state.holdings = holdings;
    state.etf = etf;
    const cov = holdings.coverage || {};
    const settled = holdings.periods.filter((p) => (cov[p] == null ? 1 : cov[p]) >= 0.9);
    state.period = (settled.length ? settled[settled.length - 1]
      : holdings.periods[holdings.periods.length - 1]);
    $("loading").hidden = true;
    initControls();
    renderAll();
  } catch (err) {
    $("loading").hidden = true;
    const box = $("error");
    box.hidden = false;
    box.innerHTML =
      `数据加载失败：${err.message}<br>若直接用 file:// 打开会被浏览器跨域策略拦截，` +
      `请在项目根目录执行 <code>python -m http.server 8000</code> 后访问 ` +
      `<code>http://localhost:8000</code>。`;
  }
}

function initControls() {
  const h = state.holdings;
  $("updated-at").textContent = "数据更新：" + (state.meta.updated_at || h.updated_at);
  const pool = h.universe_mode === "all" ? "全 A 股" : h.index_pools.join(" / ");
  $("scope-line").textContent =
    `口径：${h.scope} ｜ 候选池 ${pool} ${h.universe_size} 只`;

  const sel = $("period-filter");
  sel.innerHTML = h.periods
    .slice()
    .reverse()
    .map((p) => {
      const c = (h.coverage || {})[p];
      const tag = c == null ? "" : `（披露 ${(c * 100).toFixed(0)}%）`;
      return `<option value="${p}">${fmtDate(p)}${tag}</option>`;
    })
    .join("");
  sel.value = state.period;
  sel.onchange = () => {
    state.period = sel.value;
    renderOverview();
  };
  $("group-filter").onchange = (e) => {
    state.group = e.target.value;
    renderOverview();
  };
  $("stock-group").onchange = (e) => {
    state.group = e.target.value;
    renderStocks();
  };
  $("stock-search").oninput = (e) => {
    state.keyword = e.target.value.trim();
    renderStocks();
  };
  $("flow-filter").onchange = (e) => {
    state.flow = e.target.value;
    renderStocks();
  };
  $("btn-reload").onclick = loadData;
}

function renderAll() {
  renderOverview();
  renderStocks();
  renderEtf();
  renderTimeline();
  renderAbout();
}

// ---------------------------------------------------------------- 口径取值
function pick(rec, group) {
  if (!rec) return null;
  if (group === "all") {
    return { shares: rec.shares, ratio: rec.ratio, change: rec.change, value: rec.value };
  }
  const sh = (rec.by_group || {})[group] || 0;
  return {
    shares: sh,
    ratio: rec.shares ? (rec.ratio * sh) / rec.shares : null,
    change: rec.change,
    value: rec.close ? sh * rec.close : null,
  };
}

// ---------------------------------------------------------------- 总览
function renderOverview() {
  const h = state.holdings;
  const p = state.period;
  const sum = h.summary.find((s) => s.period === p) || {};
  const idx = h.summary.findIndex((s) => s.period === p);
  const prev = idx > 0 ? h.summary[idx - 1] : null;
  const g = state.group;

  let count = sum.stock_count || 0;
  let value = sum.total_value || 0;
  let prevValue = prev ? prev.total_value : null;
  if (g !== "all") {
    const cur = (sum.by_group || {})[g] || { stock_count: 0, value: 0 };
    count = cur.stock_count;
    value = cur.value;
    const pv = prev ? (prev.by_group || {})[g] : null;
    prevValue = pv ? pv.value : null;
  }

  const diff = prevValue != null ? value - prevValue : null;
  const diffPct = prevValue ? (value / prevValue - 1) * 100 : null;

  $("kpis").innerHTML = [
    kpi("持仓只数", count, `报告期 ${fmtDate(p)}`),
    kpi("持股市值（期末价估算）", fmtYi(value),
      diff == null ? "—" : `环比 ${diff >= 0 ? "+" : ""}${fmtYi(diff)}` +
        (diffPct != null ? `（${fmtPct(diffPct, 1)}）` : "")),
    kpi("新进 / 退出", `${sum.new || 0} / ${sum.exit || 0}`, "较上一报告期"),
    kpi("增持 / 减持 / 不变", `${sum.add || 0} / ${sum.cut || 0} / ${sum.flat || 0}`, "按披露变动数统计"),
  ].join("");

  const cov = (h.coverage || {})[p];
  const covTxt =
    cov == null
      ? ""
      : `　该期披露覆盖率 ${(cov * 100).toFixed(0)}%` +
        (cov < 0.95 ? "（尚未披露完毕，跨期可比性受限）" : "");
  $("overview-note").textContent =
    "持股市值 = 持股数 × 报告期末（或之前最近交易日）收盘价，为估算值；" +
    "增持/减持依据定期报告披露的“变动”字段，未披露变动的计入“不变”。" + covTxt;

  // 市值柱状图（分组）
  const groups = ["中央汇金投资", "中央汇金资管"];
  const series = groups.map((name, i) => ({
    name,
    color: i === 0 ? "#2f6fb5" : "#e08a1e",
    values: h.summary.map((s) => ((s.by_group || {})[name] || {}).value || 0),
  }));
  drawBars($("chart-value"), h.summary.map((s) => fmtDate(s.period)), series, "亿元");

  // 只数 / 新进 / 退出
  drawBars($("chart-count"), h.summary.map((s) => fmtDate(s.period)), [
    { name: "持仓只数", color: "#2f6fb5", values: h.summary.map((s) => s.stock_count || 0) },
    { name: "新进", color: "#2f9e6f", values: h.summary.map((s) => s.new || 0) },
    { name: "退出", color: "#c0392b", values: h.summary.map((s) => s.exit || 0) },
  ], "只");
  $("legend-value").innerHTML = series
    .map((s) => `<span class="lg" style="--c:${s.color}">${s.name}</span>`)
    .join("");

  // 变动榜
  const flow = (h.flows || {})[p] || {};
  $("tbl-add").innerHTML = flowTable(flow.add || [], "change");
  $("tbl-cut").innerHTML = flowTable(flow.cut || [], "change");
  $("tbl-new").innerHTML = flowTable(flow.new || [], "value");
  $("tbl-exit").innerHTML = flowTable(flow.exit || [], "value");
}

const kpi = (k, v, d) =>
  `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d || ""}</div></div>`;

function flowTable(rows, key) {
  if (!rows.length) return '<p class="note">无</p>';
  const head = `<table><thead><tr><th>代码</th><th>名称</th><th>持股数</th><th>${key === "change" ? "变动" : "市值"}</th></tr></thead><tbody>`;
  const body = rows
    .map((r) => `<tr><td>${r.code}</td><td>${r.name}</td><td>${fmtShares(r.shares)}</td>
      <td class="${cls(r[key])}">${key === "change" ? fmtShares(r[key]) : fmtYi(r[key])}</td></tr>`)
    .join("");
  return head + body + "</tbody></table>";
}

// ---------------------------------------------------------------- 个股明细
const COLUMNS = [
  { key: "code", label: "代码", type: "s" },
  { key: "name", label: "名称", type: "s" },
  { key: "entry_period", label: "入场期", type: "s" },
  { key: "shares", label: "持股数", type: "n" },
  { key: "ratio", label: "占比", type: "n" },
  { key: "change", label: "环比变动", type: "n" },
  { key: "value", label: "期末市值", type: "n" },
  { key: "latest_value", label: "最新市值", type: "n" },
  { key: "periods_held", label: "持有期数", type: "n" },
  { key: "pnl_since_entry", label: "入场以来", type: "n" },
];

function stockRows() {
  const h = state.holdings;
  const g = state.group;
  const flowCodes =
    state.flow === "all"
      ? null
      : new Set(((((h.flows || {})[state.period] || {})[state.flow]) || []).map((r) => r.code));
  const rows = [];
  for (const s of h.stocks) {
    const rec = s.history[state.period];
    if (!rec) continue;   // 该报告期已退出则不展示
    if (flowCodes && !flowCodes.has(s.code)) continue;
    const v = pick(rec, g);
    if (g !== "all" && !(v.shares > 0)) continue;
    if (state.keyword &&
        !(`${s.code}${s.name}`.includes(state.keyword))) continue;
    rows.push({
      code: s.code,
      name: s.name,
      market: s.market,
      entry_period: s.entry_period,
      entry_truncated: s.entry_truncated,
      pnl_since_entry: s.pnl_since_entry,
      shares: v.shares,
      ratio: v.ratio,
      change: v.change,
      value: v.value,
      latest_value: s.latest_value,
      periods_held: s.periods_held,
      holders: (rec.holders || []).join("、"),
      _s: s,
    });
  }
  const { sortKey, sortDir } = state;
  rows.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (typeof x === "string") return sortDir * x.localeCompare(y);
    const xn = x == null ? -Infinity : x;
    const yn = y == null ? -Infinity : y;
    return sortDir * (xn - yn);
  });
  return rows;
}

function renderStocks() {
  const rows = stockRows();
  const head =
    "<thead><tr>" +
    COLUMNS.map(
      (c) =>
        `<th data-key="${c.key}" class="sortable">${c.label}${
          state.sortKey === c.key ? (state.sortDir === -1 ? " ↓" : " ↑") : ""
        }</th>`
    ).join("") +
    "</tr></thead>";

  const body = rows
    .map((r) => {
      const entry = fmtDate(r.entry_period) + (r.entry_truncated ? " *" : "");
      const main = `<tr data-code="${r.code}"><td>${r.code}</td><td>${r.name}${
        r.market === "sh" ? '<span class="tag">沪</span>' : '<span class="tag">深</span>'
      }</td><td>${entry}</td><td>${fmtShares(r.shares)}</td><td>${
        r.ratio == null ? "—" : r.ratio.toFixed(2) + "%"
      }</td>
      <td class="${cls(r.change)}">${r.change == null ? "—" : fmtShares(r.change)}</td>
      <td>${fmtYi(r.value)}</td><td>${fmtYi(r.latest_value)}</td><td>${r.periods_held}</td>
      <td class="${cls(r.pnl_since_entry)}">${
        r.pnl_since_entry == null ? "—" : fmtPct(r.pnl_since_entry, 1)
      }</td></tr>`;
      const hist = Object.entries(r._s.history)
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([p, rec]) => {
          const v = pick(rec, state.group);
          const ev = rec.event === "entry" ? '<span class="tag hot">入场</span>' : "";
          return `<span style="margin-right:14px">${fmtDate(p)}：${fmtShares(v.shares)}` +
            (v.change != null ? `（<span class="${cls(v.change)}">${fmtShares(v.change)}</span>）` : "") +
            (rec.flag ? `<span class="tag">${rec.flag}</span>` : "") + ev + "</span>";
        })
        .join("");
      return (
        main +
        `<tr class="detail-row" data-detail="${r.code}" hidden><td colspan="10">
          <div>持有主体：${r.holders || "—"}</div><div style="margin-top:4px">${hist}</div></td></tr>`
      );
    })
    .join("");

  const table = $("tbl-stocks");
  table.innerHTML = head + "<tbody>" + body + "</tbody>";
  table.querySelectorAll("th.sortable").forEach((th) => {
    th.style.cursor = "pointer";
    th.onclick = () => {
      const key = th.dataset.key;
      if (state.sortKey === key) state.sortDir *= -1;
      else {
        state.sortKey = key;
        state.sortDir = -1;
      }
      renderStocks();
    };
  });
  table.querySelectorAll("tr[data-code]").forEach((tr) => {
    tr.style.cursor = "pointer";
    tr.onclick = () => {
      const d = table.querySelector(`tr[data-detail="${tr.dataset.code}"]`);
      if (d) d.hidden = !d.hidden;
    };
  });
}

// ---------------------------------------------------------------- ETF
function renderEtf() {
  const e = state.etf;
  const agg = e.aggregate || [];
  const last = agg[agg.length - 1] || {};
  const key = e.etfs.filter((x) => x.state_owned);
  const shareChg = key
    .map((x) => x.latest.share_chg_5d)
    .filter((v) => v != null);
  const avgChg = shareChg.length
    ? shareChg.reduce((a, b) => a + b, 0) / shareChg.length
    : null;

  $("etf-kpis").innerHTML = [
    kpi("重点 ETF 合计成交额", fmtYi(last.amount), last.date || ""),
    kpi("相对 20 日均额", last.ratio == null ? "—" : last.ratio.toFixed(2) + " 倍", "放量倍数"),
    kpi("5 日份额变化（均值）", fmtPct(avgChg, 2), "仅沪市 ETF 有份额数据"),
    kpi("重点 ETF 数量", `${key.length} / ${e.etfs.length}`, "公开报道中汇金曾现身持有人名单"),
  ].join("");

  const dates = agg.map((r) => r.d.slice(5));
  drawCombo($("chart-etf"), dates,
    agg.map((r) => r.amount / 1e8),
    agg.map((r) => (r.amount_ma20 ? r.amount_ma20 / 1e8 : null)));

  $("etf-note").textContent = e.share_scope || "";

  const head =
    "<thead><tr><th>代码</th><th>名称</th><th>收盘</th><th>成交额</th><th>放量倍数</th>" +
    "<th>份额(亿份)</th><th>5日份额</th><th>20日份额</th></tr></thead>";
  const body = e.etfs
    .map((x) => {
      const l = x.latest;
      return `<tr><td>${x.code}${x.state_owned ? '<span class="tag hot">汇金</span>' : ""}</td>
        <td>${x.name}</td><td>${l.close == null ? "—" : l.close.toFixed(3)}</td>
        <td>${fmtYi(l.amount)}</td>
        <td class="${l.amount_ratio >= 1.5 ? "up" : ""}">${l.amount_ratio == null ? "—" : l.amount_ratio.toFixed(2)}</td>
        <td>${l.share == null ? "—" : (l.share / 1e8).toFixed(2)}</td>
        <td class="${cls(l.share_chg_5d)}">${fmtPct(l.share_chg_5d)}</td>
        <td class="${cls(l.share_chg_20d)}">${fmtPct(l.share_chg_20d)}</td></tr>`;
    })
    .join("");
  $("tbl-etf").innerHTML = head + "<tbody>" + body + "</tbody>";
}

// ---------------------------------------------------------------- 入场时间线
function renderTimeline() {
  const e = state.etf;
  const h = state.holdings;
  const dates = e.dates || [];
  const events = (e.events || []).slice(0, 120);
  const start = dates[Math.max(0, dates.length - 60)] || "—";
  const end = dates[dates.length - 1] || "—";
  const totalNet = events.reduce((a, b) => a + b.net_amount, 0);
  const byEtf = {};
  events.forEach((ev) => {
    byEtf[ev.name] = (byEtf[ev.name] || 0) + ev.net_amount;
  });
  const topEntry = Object.entries(byEtf).sort((a, b) => b[1] - a[1])[0];

  $("timeline-kpis").innerHTML = [
    kpi("份额突增事件", events.length, `${start} ~ ${end}`),
    kpi("累计估算净申购", fmtYi(totalNet), "突增日净申购额合计"),
    kpi("净申购最多", topEntry ? topEntry[0] : "—", topEntry ? fmtYi(topEntry[1]) : ""),
    kpi("最近一次", events.length ? events[0].date : "—",
      events.length ? `${events[0].name} +${events[0].pct}%` : ""),
  ].join("");

  const evHead =
    "<thead><tr><th>日期</th><th>ETF</th><th>份额环比</th><th>估算净申购</th><th>当日成交额</th></tr></thead>";
  const evBody = events
    .map(
      (x) => `<tr><td>${x.date}</td>
      <td style="text-align:left">${x.code} ${x.name}${
        x.state_owned ? '<span class="tag hot">汇金</span>' : ""
      }</td>
      <td class="up">+${x.pct.toFixed(2)}%</td>
      <td>${fmtYi(x.net_amount)}</td>
      <td>${fmtYi(x.amount)}</td></tr>`
    )
    .join("");
  $("tbl-events").innerHTML =
    evHead +
    "<tbody>" +
    (evBody || '<tr><td colspan="5">近 60 个交易日无份额突增</td></tr>') +
    "</tbody>";

  const pfHead =
    "<thead><tr><th>报告期</th><th>持仓只数</th><th>新进</th><th>退出</th><th>增持</th><th>减持</th>" +
    "<th>新进个股</th><th>退出个股</th></tr></thead>";
  const pfBody = h.summary
    .map((s) => {
      const f = (h.flows || {})[s.period] || {};
      return `<tr><td>${fmtDate(s.period)}</td><td>${s.stock_count}</td>
        <td class="up">${s.new}</td><td class="down">${s.exit}</td><td>${s.add}</td><td>${s.cut}</td>
        <td style="text-align:left">${(f.new || []).map((r) => r.name).join("、") || "—"}</td>
        <td style="text-align:left">${(f.exit || []).map((r) => r.name).join("、") || "—"}</td></tr>`;
    })
    .join("");
  $("tbl-periodflow").innerHTML = pfHead + "<tbody>" + pfBody + "</tbody>";
}

// ---------------------------------------------------------------- 说明
function renderAbout() {
  const m = state.meta || {};
  const h = state.holdings;
  $("about-body").innerHTML = `
    <p><b>国家队口径</b>：${h.scope}。识别方式为在十大流通股东名单中匹配
      “${(m.keyword || []).join("”“")}”。</p>
    <p><b>股票候选池</b>：${h.index_pools.join("、")} 指数成分股，共 ${h.universe_size} 只；
      扫描策略为先用最近两个报告期全池筛选，再对命中股票回溯历史报告期。</p>
    <p><b>报告期</b>：${h.periods.map(fmtDate).join("、")}。
      一季报/三季报的股东披露完整性弱于年报与半年报，跨期比较建议以年报、半年报为准；
      页面默认停在“披露覆盖率 ≥ 90%”的最新报告期。</p>
    <p><b>数据来源</b>：${(m.sources || []).map((s) => `<br>· ${s}`).join("")}</p>
    <p><b>ETF 观察池</b>：${(m.etf_watch || []).join("、")}</p>
    <p><b>注意事项</b>：${m.disclaimer || ""}</p>
    <p><b>更新方式</b>：本地执行 <code>python scripts/run_all.py</code> 重新抓取，
      提交 <code>data/</code> 目录后推送到 GitHub，Pages 页面即随之更新。</p>`;
}

// ---------------------------------------------------------------- SVG 图表
function drawBars(el, labels, series, unit) {
  const w = Math.max(560, labels.length * 52);
  const h = 260;
  const pad = { l: 54, r: 12, t: 14, b: 42 };
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const gw = iw / labels.length;
  const bw = (gw - 8) / series.length;
  const y = (v) => pad.t + ih - (v / max) * ih;

  let svg = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`;
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    svg += `<line x1="${pad.l}" y1="${y(v)}" x2="${w - pad.r}" y2="${y(v)}" stroke="#eceff3"/>
      <text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end" font-size="10" fill="#8b95a3">${
      unit === "亿元" ? (v / 1e8).toFixed(0) : Math.round(v)
    }</text>`;
  }
  labels.forEach((lb, i) => {
    series.forEach((s, j) => {
      const val = s.values[i] || 0;
      const x = pad.l + i * gw + 4 + j * bw;
      svg += `<rect x="${x}" y="${y(val)}" width="${Math.max(1, bw - 2)}" height="${Math.max(
        0,
        pad.t + ih - y(val)
      )}" fill="${s.color}" opacity="0.9"><title>${lb} ${s.name} ${val.toFixed(0)}</title></rect>`;
    });
    svg += `<text x="${pad.l + i * gw + gw / 2}" y="${h - pad.b + 16}" text-anchor="middle" font-size="10" fill="#6b7684">${lb}</text>`;
  });
  svg += `<text x="${pad.l - 44}" y="${pad.t + 4}" font-size="10" fill="#8b95a3">${unit}</text>`;
  svg += "</svg>";
  el.innerHTML = svg;
}

function drawCombo(el, labels, bars, line) {
  const n = labels.length;
  const w = Math.max(560, n * 12);
  const h = 260;
  const pad = { l: 54, r: 12, t: 14, b: 42 };
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const max = Math.max(1, ...bars, ...line.filter((v) => v != null));
  const y = (v) => pad.t + ih - (v / max) * ih;
  const bw = Math.max(1, iw / n - 2);

  let svg = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`;
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    svg += `<line x1="${pad.l}" y1="${y(v)}" x2="${w - pad.r}" y2="${y(v)}" stroke="#eceff3"/>
      <text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end" font-size="10" fill="#8b95a3">${v.toFixed(0)}</text>`;
  }
  bars.forEach((v, i) => {
    const x = pad.l + (i * iw) / n;
    svg += `<rect x="${x}" y="${y(v)}" width="${bw}" height="${Math.max(0, pad.t + ih - y(v))}" fill="#2f6fb5" opacity="0.75"><title>${labels[i]} ${v.toFixed(1)}</title></rect>`;
  });
  let d = "";
  line.forEach((v, i) => {
    if (v == null) return;
    const x = pad.l + (i * iw) / n + bw / 2;
    d += (d ? "L" : "M") + x + "," + y(v);
  });
  svg += `<path d="${d}" fill="none" stroke="#e08a1e" stroke-width="1.6"/>`;
  const step = Math.ceil(n / 12);
  labels.forEach((lb, i) => {
    if (i % step) return;
    svg += `<text x="${pad.l + (i * iw) / n}" y="${h - pad.b + 16}" text-anchor="middle" font-size="10" fill="#6b7684">${lb}</text>`;
  });
  svg += `<text x="${pad.l - 44}" y="${pad.t + 4}" font-size="10" fill="#8b95a3">亿元</text></svg>`;
  el.innerHTML = svg;
}

// ---------------------------------------------------------------- 视图切换
document.getElementById("tabs").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === btn));
  document.querySelectorAll(".view").forEach((v) => {
    v.hidden = v.id !== `view-${btn.dataset.view}`;
  });
});

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("view-overview").hidden = false;
  loadData();
});
