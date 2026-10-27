"use strict";

const PAGE = 60;
const $ = (id) => document.getElementById(id);
const els = {
  q: $("q"), status: $("status"), type: $("type"), prov: $("prov"), industry: $("industry"), sort: $("sort"),
  listed: $("listed"), hasSite: $("hasSite"), hasEn: $("hasEn"), hmt: $("hmt"),
  list: $("list"), count: $("count"), more: $("more"), stats: $("stats"), generated: $("generated"),
};

let all = [];
let filtered = [];
let shown = 0;

function prepare(c) {
  c._name = c.zh || c.en || c.id;
  c._hay = [c.zh, c.en, c.hq, c.province, c.city, ...(c.industry || [])].filter(Boolean).join(" ").toLowerCase();
  return c;
}

// 下拉框选项随「含港澳台」开关重建，保留当前选择（若选项已不存在则回到「全部」）
function fillSelect(el, pairs) {
  const keep = el.value;
  el.innerHTML = el.options[0].outerHTML +
    pairs.map(([v, n]) => `<option value="${esc(v)}">${esc(v)}（${n.toLocaleString()}）</option>`).join("");
  el.value = keep;
  if (el.value !== keep) el.value = "";
}

function fillOptions() {
  const pool = visible(all);
  fillSelect(els.type, countBy(pool, (c) => c.type));
  fillSelect(els.prov, countBy(pool, (c) => c.province));
  fillSelect(els.industry, countBy(pool, (c) => c.industry).filter(([, n]) => n >= 5).slice(0, 80));
}

function readState() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.has("hmt")) setHmt(true);
  els.hmt.checked = hmtOn();
  fillOptions();
  els.q.value = p.get("q") || "";
  els.status.value = p.get("status") || "active";
  els.type.value = p.get("type") || "";
  els.prov.value = p.get("prov") || "";
  els.industry.value = p.get("industry") || "";
  els.sort.value = p.get("sort") || "name";
  els.listed.checked = p.has("listed");
  els.hasSite.checked = p.has("site");
  els.hasEn.checked = p.has("en");
}

function writeState() {
  const p = new URLSearchParams();
  if (els.q.value.trim()) p.set("q", els.q.value.trim());
  if (els.status.value !== "active") p.set("status", els.status.value);
  if (els.type.value) p.set("type", els.type.value);
  if (els.prov.value) p.set("prov", els.prov.value);
  if (els.industry.value) p.set("industry", els.industry.value);
  if (els.sort.value !== "name") p.set("sort", els.sort.value);
  if (els.listed.checked) p.set("listed", "");
  if (els.hasSite.checked) p.set("site", "");
  if (els.hasEn.checked) p.set("en", "");
  if (els.hmt.checked) p.set("hmt", "");
  const h = p.toString();
  history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
}

function apply() {
  const terms = els.q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const status = els.status.value;
  const ind = els.industry.value;
  const type = els.type.value;
  const prov = els.prov.value;
  filtered = visible(all).filter((c) =>
    (status === "all" || (status === "active") === (c.dissolved == null)) &&
    (!type || c.type === type) &&
    (!prov || c.province === prov) &&
    (!ind || (c.industry || []).includes(ind)) &&
    (!els.listed.checked || c.listed) &&
    (!els.hasSite.checked || c.website) &&
    (!els.hasEn.checked || c.enwiki) &&
    terms.every((t) => c._hay.includes(t)));

  const s = els.sort.value;
  if (s !== "name") {
    const dir = s === "founded" ? 1 : -1;
    filtered = filtered.slice().sort((a, b) =>
      (a.founded == null) - (b.founded == null) || dir * ((a.founded || 0) - (b.founded || 0)));
  }

  writeState();
  els.list.innerHTML = "";
  shown = 0;
  renderMore();
}

function renderMore() {
  const next = filtered.slice(shown, shown + PAGE);
  els.list.insertAdjacentHTML("beforeend", next.map(row).join(""));
  shown += next.length;
  els.count.textContent = `共 ${filtered.length.toLocaleString()} 家` + (filtered.length > shown ? `，已显示 ${shown}` : "");
  els.more.hidden = shown >= filtered.length;
  if (!filtered.length) els.list.innerHTML = `<li class="empty">没有符合条件的企业</li>`;
}

function renderStats() {
  const pool = visible(all);
  const n = (f) => pool.filter(f).length.toLocaleString();
  els.stats.innerHTML =
    `收录 <b>${pool.length.toLocaleString()}</b> 家 · 企业 <b>${n((c) => c.type === "企业")}</b> · 存续 <b>${n((c) => c.dissolved == null)}</b> · ` +
    `有官网 <b>${n((c) => c.website)}</b> · 上市 <b>${n((c) => c.listed)}</b> · 有英文维基 <b>${n((c) => c.enwiki)}</b>` +
    (hmtOn() ? ` · 其中港澳台 <b>${n((c) => c.hmt)}</b>` : "");
}

function renderGenerated(data) {
  els.generated.textContent = data.generated ? new Date(data.generated).toLocaleDateString("zh-CN") : "—";
}

async function init() {
  try {
    const data = await loadData();
    all = data.companies.map(prepare).sort((a, b) => a._name.localeCompare(b._name, "zh-CN"));
    renderGenerated(data);
    readState();
    renderStats();
    apply();
  } catch (e) {
    els.stats.textContent = "数据加载失败：" + e.message;
  }

  let t;
  els.q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(apply, 150); });
  for (const el of [els.status, els.type, els.prov, els.industry, els.sort, els.listed, els.hasSite, els.hasEn]) el.addEventListener("change", apply);
  els.more.addEventListener("click", renderMore);
  els.hmt.addEventListener("change", () => {
    setHmt(els.hmt.checked);
    fillOptions();
    renderStats();
    apply();
  });
}

init();
