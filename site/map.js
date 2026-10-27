"use strict";

const $ = (id) => document.getElementById(id);

// 色阶分档：家数下限
const STEPS = [1, 25, 50, 100, 200, 500];
const OUTSIDE = new Set(["台湾省", "香港特别行政区", "澳门特别行政区"]);

let chart;
let summary = new Map(); // 省份 -> 概况
let ranked = [];

const provinceUrl = (p) => "province.html?p=" + encodeURIComponent(p);

function summarize(all) {
  const by = new Map();
  for (const c of all) if (c.province) (by.get(c.province) || by.set(c.province, []).get(c.province)).push(c);
  ranked = [...by].map(([name, list]) => ({
    name,
    total: list.length,
    business: list.filter((c) => c.type === "企业").length,
    listed: list.filter((c) => c.listed).length,
    dissolved: list.filter((c) => c.dissolved != null).length,
    cities: countBy(list, (c) => c.city).slice(0, 3),
    industries: countBy(list, (c) => c.industry).slice(0, 3),
  })).sort((a, b) => b.total - a.total);
  ranked.forEach((s, i) => { s.rank = i + 1; summary.set(s.name, s); });
}

function tooltip(params) {
  const name = params.name;
  if (!name) return "";
  if (OUTSIDE.has(name)) return `<b>${esc(name)}</b><br><span class="tt-muted">不在收录范围（仅收录中国大陆企业）</span>`;
  const s = summary.get(name);
  if (!s) return `<b>${esc(name)}</b><br><span class="tt-muted">暂无收录</span>`;
  const list = (pairs) => pairs.map(([k, n]) => `${esc(k)} ${n}`).join("、") || "—";
  return `<div class="tt"><b>${esc(name)}</b> <span class="tt-muted">全国第 ${s.rank}</span>` +
    `<div class="tt-big">${s.total.toLocaleString()} <small>家</small></div>` +
    `<div>企业 ${s.business} · 上市 ${s.listed} · 已解散 ${s.dissolved}</div>` +
    `<div><span class="tt-muted">主要城市</span> ${list(s.cities)}</div>` +
    `<div><span class="tt-muted">热门行业</span> ${list(s.industries)}</div>` +
    `<div class="tt-cta">点击查看分析 →</div></div>`;
}

function renderMap() {
  const t = themeColors();
  const pieces = STEPS.map((min, i) => ({
    min, max: STEPS[i + 1] ? STEPS[i + 1] - 1 : undefined,
    label: STEPS[i + 1] ? `${min}–${STEPS[i + 1] - 1}` : `${min}+`,
    color: mix(t.soft, t.accent, (i + 1) / STEPS.length),
  }));
  chart.setOption({
    tooltip: {
      trigger: "item", formatter: tooltip, confine: true,
      backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text, fontSize: 13 },
      extraCssText: "box-shadow:0 6px 24px rgba(0,0,0,.12);border-radius:10px;",
    },
    visualMap: {
      type: "piecewise", pieces, left: 8, bottom: 8, itemWidth: 14, itemHeight: 10, itemGap: 4,
      textStyle: { color: t.muted, fontSize: 11 }, outOfRange: { color: t.chip },
    },
    series: [{
      type: "map", map: "china", roam: false, selectedMode: false,
      layoutCenter: ["50%", "50%"], layoutSize: "100%",
      itemStyle: { areaColor: t.chip, borderColor: t.surface, borderWidth: 0.8 },
      emphasis: { label: { show: true, color: t.text, fontWeight: 600 }, itemStyle: { areaColor: t.accent, shadowBlur: 8, shadowColor: "rgba(0,0,0,.25)" } },
      label: { show: false },
      data: ranked.map((s) => ({ name: s.name, value: s.total })),
    }],
  }, true);
}

function renderRank() {
  const max = ranked[0]?.total || 1;
  $("rank").innerHTML = ranked.map((s) =>
    `<li data-name="${esc(s.name)}"><a href="${provinceUrl(s.name)}">` +
    `<span class="r-name">${esc(shortProvince(s.name))}</span>` +
    `<span class="r-bar"><i style="width:${(s.total / max * 100).toFixed(1)}%"></i></span>` +
    `<span class="r-num">${s.total}</span></a></li>`).join("");
  // 悬停排行时在地图上高亮对应省份
  $("rank").addEventListener("mouseover", (e) => {
    const li = e.target.closest("li");
    if (!li) return;
    chart.dispatchAction({ type: "downplay" });
    chart.dispatchAction({ type: "highlight", name: li.dataset.name });
    chart.dispatchAction({ type: "showTip", seriesIndex: 0, name: li.dataset.name });
  });
  $("rank").addEventListener("mouseleave", () => {
    chart.dispatchAction({ type: "downplay" });
    chart.dispatchAction({ type: "hideTip" });
  });
}

async function init() {
  try {
    const [data, geo] = await Promise.all([loadData(), fetch("geo/china.json").then((r) => r.json())]);
    const all = data.companies;
    summarize(all);
    const located = ranked.reduce((n, s) => n + s.total, 0);
    $("stats").innerHTML = `收录 <b>${all.length.toLocaleString()}</b> 家，其中 <b>${located.toLocaleString()}</b> 家可定位到省份 · 覆盖 <b>${ranked.length}</b> 个省级行政区`;
    $("generated").textContent = data.generated ? new Date(data.generated).toLocaleDateString("zh-CN") : "—";
    if (!located) $("hint").textContent = "当前数据还没有省份字段，等下次数据刷新后即可显示。";

    echarts.registerMap("china", geo);
    chart = echarts.init($("map"));
    renderMap();
    renderRank();

    // 触屏没有悬停：第一次点按显示概况，再点同一省份才进入
    const touch = matchMedia("(hover: none)").matches;
    let armed = null;
    chart.on("click", (p) => {
      if (!summary.has(p.name)) return;
      if (touch && armed !== p.name) { armed = p.name; return; }
      location.href = provinceUrl(p.name);
    });
    addEventListener("resize", () => chart.resize());
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderMap);
  } catch (e) {
    $("stats").textContent = "数据加载失败：" + e.message;
  }
}

init();
