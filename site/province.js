"use strict";

const PAGE = 60;
const $ = (id) => document.getElementById(id);
const FILTER_LABEL = { city: "城市", type: "类型", industry: "行业", decade: "成立年代" };

let items = [];    // 本省全部条目
let filtered = [];
let shown = 0;
let filter = null; // { kind, value }
const charts = {};

const decade = (y) => (y == null ? null : y < 1900 ? "1900 前" : `${Math.floor(y / 10) * 10}s`);
const matches = (c, f) => !f ||
  (f.kind === "city" ? (c.city || "未知") === f.value :
    f.kind === "type" ? c.type === f.value :
      f.kind === "industry" ? (c.industry || []).includes(f.value) :
        decade(c.founded) === f.value);

function renderKpis(rank) {
  const n = items.length;
  const k = (label, v, sub) => `<div class="kpi"><div class="k-label">${label}</div>` +
    `<div class="k-num">${v.toLocaleString()}</div><div class="k-sub">${sub}</div></div>`;
  const pct = (v) => (n ? `${Math.round(v / n * 100)}%` : "—");
  const cnt = (f) => items.filter(f).length;
  const listed = cnt((c) => c.listed), active = cnt((c) => c.dissolved == null);
  const site = cnt((c) => c.website), en = cnt((c) => c.enwiki);
  $("kpis").innerHTML =
    k("收录", n, `全国第 ${rank}`) +
    k("企业", cnt((c) => c.type === "企业"), "其余为学校等机构") +
    k("上市", listed, `占 ${pct(listed)}`) +
    k("存续", active, `占 ${pct(active)}`) +
    k("有官网", site, `占 ${pct(site)}`) +
    k("有英文维基", en, `占 ${pct(en)}`);
}

function base(t) {
  return {
    textStyle: { fontFamily: getComputedStyle(document.body).fontFamily },
    tooltip: {
      backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
      extraCssText: "box-shadow:0 6px 24px rgba(0,0,0,.12);border-radius:8px;",
    },
    grid: { left: 8, right: 36, top: 8, bottom: 8, containLabel: true },
  };
}

// 横向条形图：pairs 为 [名称, 数量]，按数量降序
function hbar(pairs, kind, t) {
  const data = pairs.slice().reverse();
  charts[kind].setOption({
    ...base(t),
    tooltip: { ...base(t).tooltip, trigger: "item", formatter: (p) => `${esc(p.name)}：${p.value} 家` },
    xAxis: { type: "value", show: false },
    yAxis: {
      type: "category", data: data.map((d) => d[0]),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: t.text, width: 110, overflow: "truncate" },
    },
    series: [{
      type: "bar", data: data.map((d) => ({ value: d[1], name: d[0], itemStyle: { color: isActive(kind, d[0]) ? t.accent : mix(t.soft, t.accent, 0.55) } })),
      barMaxWidth: 16, itemStyle: { borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: t.muted, fontSize: 11 },
    }],
  }, true);
}

const isActive = (kind, value) => filter && filter.kind === kind && filter.value === value;

function renderCharts() {
  const t = themeColors();
  const top = (pairs, n) => pairs.slice(0, n);

  hbar(top(countBy(items, (c) => c.city || "未知"), 12), "city", t);
  hbar(top(countBy(items, (c) => c.industry), 12), "industry", t);

  const types = countBy(items, (c) => c.type);
  const palette = [t.accent, "#d99a3e", "#5b8db8", "#6fa36f", "#9a7bbf", "#c4677f", "#4fa3a0", "#8c8a84"];
  const shades = types.map((_, i) => palette[i % palette.length]);
  charts.type.setOption({
    ...base(t),
    tooltip: { ...base(t).tooltip, trigger: "item", formatter: (p) => `${esc(p.name)}：${p.value} 家（${p.percent}%）` },
    legend: { type: "scroll", orient: "vertical", right: 0, top: "middle", textStyle: { color: t.text }, itemWidth: 10, itemHeight: 10 },
    series: [{
      type: "pie", radius: ["45%", "72%"], center: ["35%", "50%"], avoidLabelOverlap: true,
      label: { show: false }, itemStyle: { borderColor: t.surface, borderWidth: 2 },
      data: types.map(([name, value], i) => ({ name, value, itemStyle: { color: shades[i] },
        selected: isActive("type", name) })),
      selectedOffset: 8,
    }],
  }, true);

  // 成立年代：1900 年前合并，按时间顺序
  const counts = new Map(countBy(items, (c) => decade(c.founded)));
  const decades = [...counts.keys()].sort((a, b) => (a === "1900 前" ? -1 : b === "1900 前" ? 1 : a.localeCompare(b)));
  const unknown = items.filter((c) => c.founded == null).length;
  charts.decade.setOption({
    ...base(t),
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    title: unknown ? { text: `另有 ${unknown} 家成立年份未知`, right: 0, top: 0, textStyle: { color: t.muted, fontSize: 11, fontWeight: 400 } } : undefined,
    tooltip: { ...base(t).tooltip, trigger: "item", formatter: (p) => `${esc(p.name)}：${p.value} 家` },
    xAxis: { type: "category", data: decades, axisLabel: { color: t.muted, fontSize: 11 }, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted, fontSize: 11 } },
    series: [{
      type: "bar", barMaxWidth: 28, itemStyle: { borderRadius: [4, 4, 0, 0] },
      data: decades.map((d) => ({ value: counts.get(d), name: d, itemStyle: { color: isActive("decade", d) ? t.accent : mix(t.soft, t.accent, 0.55) } })),
    }],
  }, true);
}

function apply() {
  filtered = items.filter((c) => matches(c, filter));
  $("filter").innerHTML = filter
    ? `<button class="chip-filter" id="clear" title="清除筛选">${FILTER_LABEL[filter.kind]}：${esc(filter.value)} ✕</button>` : "";
  if (filter) $("clear").addEventListener("click", () => setFilter(null));
  $("list").innerHTML = "";
  shown = 0;
  renderMore();
}

function renderMore() {
  const next = filtered.slice(shown, shown + PAGE);
  $("list").insertAdjacentHTML("beforeend", next.map(row).join(""));
  shown += next.length;
  $("count").textContent = `共 ${filtered.length.toLocaleString()} 家` + (filtered.length > shown ? `，已显示 ${shown}` : "");
  $("more").hidden = shown >= filtered.length;
  if (!filtered.length) $("list").innerHTML = `<li class="empty">没有符合条件的条目</li>`;
}

function setFilter(f) {
  filter = f && isActive(f.kind, f.value) ? null : f; // 再点一次同一项即取消
  renderCharts();
  apply();
}

async function init() {
  const name = new URLSearchParams(location.search).get("p") || "";
  try {
    const data = await loadData();
    $("generated").textContent = data.generated ? new Date(data.generated).toLocaleDateString("zh-CN") : "—";
    const all = data.companies.map((c) => ({ ...c, _name: c.zh || c.en || c.id }));
    const provinces = countBy(all, (c) => c.province);
    $("pick").innerHTML = `<option value="">选择省份…</option>` + provinces
      .map(([p, n]) => `<option value="${esc(p)}"${p === name ? " selected" : ""}>${esc(p)}（${n}）</option>`).join("");
    $("pick").addEventListener("change", (e) => { if (e.target.value) location.search = "?p=" + encodeURIComponent(e.target.value); });

    items = all.filter((c) => c.province === name)
      .sort((a, b) => b.listed - a.listed || a._name.localeCompare(b._name, "zh-CN"));
    if (!items.length) {
      $("title").textContent = name || "省份分析";
      $("lede").innerHTML = name ? "该省份暂无收录条目。" : "请从地图或上方下拉框选择一个省份。";
      document.querySelector("main").hidden = true;
      return;
    }

    document.title = `${name} · 中国企业维基索引`;
    $("title").textContent = name;
    const rank = provinces.findIndex(([p]) => p === name) + 1;
    const cities = countBy(items, (c) => c.city).slice(0, 3).map(([c]) => c).join("、");
    $("lede").textContent = `维基百科有条目的企业与机构 ${items.length.toLocaleString()} 家` + (cities ? `，主要集中在${cities}` : "");
    $("toList").href = "./#" + new URLSearchParams({ prov: name, status: "all" });
    renderKpis(rank);

    charts.city = echarts.init($("c-city"));
    charts.type = echarts.init($("c-type"));
    charts.industry = echarts.init($("c-ind"));
    charts.decade = echarts.init($("c-year"));
    charts.city.on("click", (p) => setFilter({ kind: "city", value: p.name }));
    charts.type.on("click", (p) => setFilter({ kind: "type", value: p.name }));
    charts.industry.on("click", (p) => setFilter({ kind: "industry", value: p.name }));
    charts.decade.on("click", (p) => setFilter({ kind: "decade", value: p.name }));
    renderCharts();
    apply();

    $("more").addEventListener("click", renderMore);
    addEventListener("resize", () => Object.values(charts).forEach((c) => c.resize()));
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderCharts);
  } catch (e) {
    $("lede").textContent = "数据加载失败：" + e.message;
  }
}

init();
