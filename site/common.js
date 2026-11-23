"use strict";

// 列表页、地图页、省份页共用的小工具

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "官网"; } };
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);

// 数据源切换：融合（默认）/ Wikidata / Wikipedia，状态存在 localStorage（也支持 URL ?src=merged|wikidata|wikipedia）
const SOURCES = {
  merged: { label: "融合", full: "companies-merged.json", lite: "lite-merged.json" },
  wikidata: { label: "Wikidata", full: "companies.json", lite: "lite.json" },
  wikipedia: { label: "Wikipedia", full: "companies-wp.json", lite: "lite-wp.json" },
};
let dataSource = (() => {
  const q = new URLSearchParams(location.search).get("src");
  if (q && SOURCES[q]) {
    try { localStorage.setItem("cnwiki.source", q); } catch { /* ignore */ }
    return q;
  }
  try {
    const saved = localStorage.getItem("cnwiki.source");
    if (saved && SOURCES[saved]) return saved;
  } catch { /* ignore */ }
  return "merged";
})();

function setDataSource(src) {
  if (!SOURCES[src] || src === dataSource) return;
  try { localStorage.setItem("cnwiki.source", src); } catch { /* ignore */ }
  const u = new URL(location.href);
  if (u.searchParams.has("src")) {
    u.searchParams.set("src", src);
    location.href = u.toString();
  } else {
    location.reload();
  }
}

function mountSourceSwitch() {
  const wrap = document.querySelector(".top .wrap");
  if (!wrap || wrap.querySelector(".src-switch")) return;
  const box = document.createElement("div");
  box.className = "src-switch";
  box.setAttribute("role", "group");
  box.setAttribute("aria-label", "切换数据源");
  box.innerHTML = `<span class="src-label">数据源</span>` + Object.entries(SOURCES).map(([k, v]) =>
    `<button type="button" data-src="${k}" aria-pressed="${k === dataSource}">${v.label}</button>`
  ).join("");
  box.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-src]");
    if (btn) setDataSource(btn.dataset.src);
  });
  wrap.prepend(box);
  if (dataSource !== "wikidata") {
    const foot = document.querySelector(".foot p");
    if (foot) {
      const gen = foot.querySelector("#generated")?.outerHTML || '<span id="generated">—</span>';
      foot.innerHTML = dataSource === "merged"
        ? `数据融合自 <a href="https://www.wikidata.org/">Wikidata</a>（CC0）与 <a href="https://zh.wikipedia.org/">维基百科</a>（CC BY-SA 4.0），双源去重互补。数据更新于 ${gen}。`
        : `数据来自 <a href="https://zh.wikipedia.org/">中文维基百科</a> 与 <a href="https://en.wikipedia.org/">English Wikipedia</a>（CC BY-SA 4.0），由公司分类树与信息框解析得出。数据更新于 ${gen}。`;
    }
  }
}
mountSourceSwitch();

// Deployed site serves data/ next to index.html; local preview of site/ reads ../data/.
async function loadData(name = "companies.json") {
  const src = SOURCES[dataSource] || SOURCES.merged;
  const file = name === "lite.json" ? src.lite : name === "companies.json" ? src.full : name;
  for (const path of ["data/" + file, "../data/" + file]) {
    try {
      const r = await fetch(path);
      if (r.ok) return await r.json();
    } catch { /* try next */ }
  }
  throw new Error(`无法加载 ${src.label} 数据（${file}）`);
}

// 省份名去掉「省 / 市 / 自治区 / 特别行政区」等后缀，用于紧凑显示
const shortProvince = (p) => p.replace(/(壮族|回族|维吾尔)?自治区$|特别行政区$|省$|市$/, "");

// 「含港澳台」「含教育机构」「含公共机构」开关：默认关闭，各页共用，记在本浏览器里
const PUB_TYPES = new Set(["医院", "博物馆", "图书馆"]);
const SCOPES = {
  hmt: (c) => c.hmt,
  edu: (c) => c.type === "教育机构",
  pub: (c) => PUB_TYPES.has(c.type),
};
const scope = {};
for (const k in SCOPES) scope[k] = (() => { try { return localStorage.getItem("cnwiki." + k) === "1"; } catch { return false; } })();
function setScope(k, on) {
  scope[k] = on;
  try { on ? localStorage.setItem("cnwiki." + k, "1") : localStorage.removeItem("cnwiki." + k); } catch { /* 隐私模式等 */ }
}
// ignore：不受哪些开关限制（如直接打开港澳台的省份页）
const inScope = (c, ignore = []) => Object.keys(SCOPES).every((k) => scope[k] || ignore.includes(k) || !SCOPES[k](c));
const visible = (list) => list.filter((c) => inScope(c));

// 已解散，或已并入 / 被取代（不少被合并的企业在 Wikidata 上没填解散时间）
const gone = (c) => c.dissolved != null || !!c.successor;
const isQid = (id) => /^Q\d+$/.test(id || "");

// 后继标签：后继也收录了就在列表页搜索它，否则打开它的 Wikidata 或维基百科页面
function successorTag(c) {
  const s = c.successor;
  const text = (s.kind === "merged" ? `已并入 ${s.name}` : `后继：${s.name}`) + (c.dissolved != null ? `（${c.dissolved}）` : "");
  if (s.here) {
    return `<a class="tag gone succ" href="${esc("./#" + new URLSearchParams({ q: s.name, status: "all" }))}" title="在列表中查看 ${esc(s.name)}">${esc(text)}</a>`;
  }
  const href = isQid(s.id)
    ? `https://www.wikidata.org/wiki/${esc(s.id)}`
    : `https://zh.wikipedia.org/wiki/${encodeURIComponent(s.name)}`;
  const tip = isQid(s.id) ? `${s.name} 未收录，在 Wikidata 查看` : `${s.name} 未收录，在维基百科查看`;
  return `<a class="tag gone succ" href="${href}" target="_blank" rel="noopener" title="${esc(tip)}">${esc(text)} ↗</a>`;
}

function row(c) {
  const name = c.zh || c.en || c.id;
  const en = c.zh && c.en ? `<span class="en">${esc(c.en)}</span>` : "";
  const tags = (c.type && c.type !== "企业" ? `<span class="tag kind">${esc(c.type)}</span>` : "") +
    (c.hmt && c.province ? `<span class="tag kind">${esc(shortProvince(c.province))}</span>` : "") +
    (c.listed ? `<span class="tag listed">上市</span>` : "") +
    (c.successor ? successorTag(c) : c.dissolved != null ? `<span class="tag gone">已解散 ${c.dissolved}</span>` : "");
  const meta = [
    c.hq && esc(c.hq),
    c.founded && `${c.founded} 年成立`,
    (c.industry || []).map((i) => `<span class="ind">${esc(i)}</span>`).join(""),
  ].filter(Boolean).join(" · ");
  const site = safeUrl(c.website);
  const links = [
    site && `<a class="site" href="${esc(site)}" target="_blank" rel="noopener" title="${esc(site)}">${esc(host(site))}</a>`,
    c.zhwiki && `<a href="${esc(c.zhwiki)}" target="_blank" rel="noopener">中文维基</a>`,
    c.enwiki && `<a href="${esc(c.enwiki)}" target="_blank" rel="noopener">English</a>`,
    isQid(c.id) && `<a href="https://www.wikidata.org/wiki/${esc(c.id)}" target="_blank" rel="noopener" title="在 Wikidata 查看或修正">WD</a>`,
  ].filter(Boolean).join("");
  return `<li class="item"><div class="name">${esc(name)}${en}${tags}</div>` +
    `<div class="links">${links}</div><div class="meta">${meta || "&nbsp;"}</div></li>`;
}

// 图表配色取自 CSS 变量，跟随浅色 / 深色模式
function themeColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (k) => s.getPropertyValue(k).trim();
  return { text: v("--text"), muted: v("--muted"), line: v("--line"), surface: v("--surface"),
    accent: v("--accent"), soft: v("--accent-soft"), chip: v("--chip") };
}

// 在两个 #rrggbb 颜色之间插值，t ∈ [0, 1]
function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

function countBy(items, key) {
  const m = new Map();
  for (const c of items) for (const k of [].concat(key(c) ?? [])) m.set(k, (m.get(k) || 0) + 1);
  return [...m].sort((a, b) => b[1] - a[1]);
}
