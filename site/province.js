"use strict";

const PAGE = 60;
const $ = (id) => document.getElementById(id);
const FILTER_LABEL = { city: "城市", type: "类型", industry: "行业", decade: "成立年代" };

let items = [];    // 本省全部条目
let filtered = [];
let shown = 0;
let filter = null; // { kind, value }
const charts = {};

// 省级行政区划代码，对应 geo/<adcode>.json（地级市边界）；直辖市下面是区县，不画城市地图
const ADCODE = {
  "河北省": 130000, "山西省": 140000, "内蒙古自治区": 150000, "辽宁省": 210000, "吉林省": 220000,
  "黑龙江省": 230000, "江苏省": 320000, "浙江省": 330000, "安徽省": 340000, "福建省": 350000,
  "江西省": 360000, "山东省": 370000, "河南省": 410000, "湖北省": 420000, "湖南省": 430000,
  "广东省": 440000, "广西壮族自治区": 450000, "海南省": 460000, "四川省": 510000, "贵州省": 520000,
  "云南省": 530000, "西藏自治区": 540000, "陕西省": 610000, "甘肃省": 620000, "青海省": 630000,
  "宁夏回族自治区": 640000, "新疆维吾尔自治区": 650000,
};
const MAP_STEPS = [1, 3, 10, 30, 100];

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
    k("企业", cnt((c) => c.type === "企业"), scope.edu ? "其余为学校等机构" : "其余为图书馆等机构") +
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
  if (!charts[kind]) return;
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

function renderCityMap(t) {
  if (!charts.map) return;
  const by = new Map();
  for (const c of items) if (c.city) (by.get(c.city) || by.set(c.city, []).get(c.city)).push(c);
  const info = new Map([...by].map(([name, list]) => [name, {
    total: list.length,
    listed: list.filter((c) => c.listed).length,
    industries: countBy(list, (c) => c.industry).slice(0, 3),
    top: list.slice(0, 3).map((c) => c._name), // items 已按上市优先排序
  }]));
  const pieces = MAP_STEPS.map((min, i) => ({
    min, max: MAP_STEPS[i + 1] ? MAP_STEPS[i + 1] - 1 : undefined,
    label: MAP_STEPS[i + 1] ? (min === MAP_STEPS[i + 1] - 1 ? `${min}` : `${min}–${MAP_STEPS[i + 1] - 1}`) : `${min}+`,
    color: mix(t.soft, t.accent, (i + 1) / MAP_STEPS.length),
  }));
  charts.map.setOption({
    tooltip: {
      ...base(t).tooltip, trigger: "item", confine: true,
      formatter: (p) => {
        const s = info.get(p.name);
        if (!s) return `<b>${esc(p.name)}</b><br><span class="tt-muted">暂无收录</span>`;
        const ind = s.industries.map(([k, n]) => `${esc(k)} ${n}`).join("、") || "—";
        return `<div class="tt"><b>${esc(p.name)}</b><div class="tt-big">${s.total} <small>家</small></div>` +
          `<div>上市 ${s.listed}</div><div><span class="tt-muted">代表</span> ${s.top.map(esc).join("、")}</div>` +
          `<div><span class="tt-muted">热门行业</span> ${ind}</div>` +
          `<div class="tt-cta">${isActive("city", p.name) ? "点击取消筛选" : "点击筛选名单 ↓"}</div></div>`;
      },
    },
    visualMap: {
      type: "piecewise", pieces, left: 0, bottom: 0, itemWidth: 14, itemHeight: 10, itemGap: 4,
      textStyle: { color: t.muted, fontSize: 11 }, outOfRange: { color: t.chip },
    },
    series: [{
      type: "map", map: "province", roam: false, selectedMode: false,
      layoutCenter: ["50%", "50%"], layoutSize: "95%",
      itemStyle: { areaColor: t.chip, borderColor: t.surface, borderWidth: 0.8 },
      // 窄屏城市名挤在一起，只在悬停时显示
      label: { show: $("c-map").clientWidth >= 600, color: t.muted, fontSize: 10, formatter: (p) => (info.has(p.name) ? p.name : "") },
      emphasis: { label: { show: true, color: t.text, fontWeight: 600 }, itemStyle: { areaColor: t.accent } },
      data: [...info].map(([name, s]) => ({
        name, value: s.total,
        // 当前筛选的城市描粗边框
        itemStyle: isActive("city", name) ? { borderColor: t.text, borderWidth: 2 } : undefined,
      })),
    }],
  }, true);
}

function renderCharts() {
  const t = themeColors();
  renderCityMap(t);
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
    // 港澳台页面直接打开时照常显示；排名、下拉框、名单跟随「含港澳台」「含教育机构」开关
    const all = data.companies.map((c) => ({ ...c, _name: c.zh || c.en || c.id }));
    const here = (c) => c.province === name && inScope(c, ["hmt"]);
    const provinces = countBy(all.filter((c) => inScope(c) || here(c)), (c) => c.province);
    $("edu").checked = scope.edu;
    $("edu").addEventListener("change", (e) => { setScope("edu", e.target.checked); location.reload(); });
    $("pick").innerHTML = `<option value="">选择省份…</option>` + provinces
      .map(([p, n]) => `<option value="${esc(p)}"${p === name ? " selected" : ""}>${esc(p)}（${n}）</option>`).join("");
    $("pick").addEventListener("change", (e) => { if (e.target.value) location.search = "?p=" + encodeURIComponent(e.target.value); });

    items = all.filter(here)
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

    const code = ADCODE[name];
    if (code) {
      try {
        const geo = await fetch(`geo/${code}.json`).then((r) => r.json());
        echarts.registerMap("province", geo);
        $("mapcard").hidden = false;
        charts.map = echarts.init($("c-map"));
        charts.map.on("click", (p) => { if (items.some((c) => c.city === p.name)) setFilter({ kind: "city", value: p.name }); });
      } catch { /* 没有边界数据就只显示图表 */ }
    }
    // 只有一个城市（直辖市）或没有城市数据（港澳台）时，城市分布图没意义
    if (new Set(items.map((c) => c.city)).size > 1) charts.city = echarts.init($("c-city"));
    else $("c-city").parentElement.hidden = true;
    charts.type = echarts.init($("c-type"));
    charts.industry = echarts.init($("c-ind"));
    charts.decade = echarts.init($("c-year"));
    charts.city?.on("click", (p) => setFilter({ kind: "city", value: p.name }));
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
