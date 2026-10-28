"use strict";

// 列表页、地图页、省份页共用的小工具

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "官网"; } };
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);

// Deployed site serves data/ next to index.html; local preview of site/ reads ../data/.
async function loadData() {
  for (const path of ["data/companies.json", "../data/companies.json"]) {
    try {
      const r = await fetch(path);
      if (r.ok) return await r.json();
    } catch { /* try next */ }
  }
  throw new Error("无法加载数据");
}

// 省份名去掉「省 / 市 / 自治区 / 特别行政区」等后缀，用于紧凑显示
const shortProvince = (p) => p.replace(/(壮族|回族|维吾尔)?自治区$|特别行政区$|省$|市$/, "");

// 「含港澳台」「含教育机构」开关：默认关闭，各页共用，记在本浏览器里（存不了也不影响当前页使用）
const SCOPES = { hmt: (c) => c.hmt, edu: (c) => c.type === "教育机构" };
const scope = {};
for (const k in SCOPES) scope[k] = (() => { try { return localStorage.getItem("cnwiki." + k) === "1"; } catch { return false; } })();
function setScope(k, on) {
  scope[k] = on;
  try { on ? localStorage.setItem("cnwiki." + k, "1") : localStorage.removeItem("cnwiki." + k); } catch { /* 隐私模式等 */ }
}
// ignore：不受哪些开关限制（如直接打开港澳台的省份页）
const inScope = (c, ignore = []) => Object.keys(SCOPES).every((k) => scope[k] || ignore.includes(k) || !SCOPES[k](c));
const visible = (list) => list.filter((c) => inScope(c));

function row(c) {
  const name = c.zh || c.en || c.id;
  const en = c.zh && c.en ? `<span class="en">${esc(c.en)}</span>` : "";
  const tags = (c.type && c.type !== "企业" ? `<span class="tag kind">${esc(c.type)}</span>` : "") +
    (c.hmt && c.province ? `<span class="tag kind">${esc(shortProvince(c.province))}</span>` : "") +
    (c.listed ? `<span class="tag listed">上市</span>` : "") +
    (c.dissolved != null ? `<span class="tag gone">已解散 ${c.dissolved}</span>` : "");
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
    `<a href="https://www.wikidata.org/wiki/${esc(c.id)}" target="_blank" rel="noopener" title="在 Wikidata 查看或修正">WD</a>`,
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
