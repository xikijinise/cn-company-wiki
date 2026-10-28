"use strict";

const PAGE = 60;
const $ = (id) => document.getElementById(id);
const els = {
  q: $("q"), status: $("status"), type: $("type"), prov: $("prov"), industry: $("industry"), sort: $("sort"),
  listed: $("listed"), hasSite: $("hasSite"), hasEn: $("hasEn"), hmt: $("hmt"), edu: $("edu"),
  controls: $("controls"), filters: $("filters"), filterBtn: $("filterBtn"), list: $("list"), count: $("count"), more: $("more"), stats: $("stats"), generated: $("generated"),
};

let all = [];
let filtered = [];
let shown = 0;

function prepare(c) {
  c._name = c.zh || c.en || c.id;
  c._hay = [c.zh, c.en, c.hq, c.province, c.city, ...(c.industry || [])].filter(Boolean).join(" ").toLowerCase();
  return c;
}

// 重建下拉框选项并保留当前选择：当前选中项即使已没有结果也留着（显示 0），免得筛选被悄悄清掉
function fillSelect(el, pairs) {
  const keep = el.value;
  if (keep && !pairs.some(([v]) => v === keep)) pairs = [[keep, 0], ...pairs];
  el.innerHTML = el.options[0].outerHTML +
    pairs.map(([v, n]) => `<option value="${esc(v)}">${esc(v)}（${n.toLocaleString()}）</option>`).join("");
  el.value = keep;
  if (el.value !== keep) el.value = "";
}

// 联动筛选：每个下拉框的选项和数字只算满足「其他」所有条件的条目（不算它自己，否则只剩一个选项）
function fillOptions(test = () => true) {
  const pool = visible(all);
  const facet = (skip, key) => countBy(pool.filter((c) => test(c, skip)), key);
  fillSelect(els.type, facet("type", (c) => c.type));
  fillSelect(els.prov, facet("prov", (c) => c.province));
  fillSelect(els.industry, facet("industry", (c) => c.industry).slice(0, 80));
}

function readState() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k in SCOPES) {
    if (p.has(k)) setScope(k, true);
    els[k].checked = scope[k];
  }
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
  for (const k in SCOPES) if (els[k].checked) p.set(k, "");
  const h = p.toString();
  history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
}

// 当前所有筛选条件；skip 指定跳过哪个下拉框的条件（给联动筛选算数字用）
function matcher() {
  const terms = els.q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const status = els.status.value;
  const ind = els.industry.value;
  const type = els.type.value;
  const prov = els.prov.value;
  return (c, skip) =>
    (status === "all" || (status === "active") === (c.dissolved == null)) &&
    (!type || skip === "type" || c.type === type) &&
    (!prov || skip === "prov" || c.province === prov) &&
    (!ind || skip === "industry" || (c.industry || []).includes(ind)) &&
    (!els.listed.checked || c.listed) &&
    (!els.hasSite.checked || c.website) &&
    (!els.hasEn.checked || c.enwiki) &&
    terms.every((t) => c._hay.includes(t));
}

function apply() {
  const test = matcher();
  filtered = visible(all).filter((c) => test(c));
  fillOptions(test);

  const s = els.sort.value;
  if (s !== "name") {
    const dir = s === "founded" ? 1 : -1;
    filtered = filtered.slice().sort((a, b) =>
      (a.founded == null) - (b.founded == null) || dir * ((a.founded || 0) - (b.founded || 0)));
  }

  writeState();
  renderFilterBtn();
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
    (scope.hmt ? ` · 其中港澳台 <b>${n((c) => c.hmt)}</b>` : "") +
    (scope.edu ? ` · 其中教育机构 <b>${n((c) => c.type === "教育机构")}</b>` : "");
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
  for (const k in SCOPES) els[k].addEventListener("change", () => {
    setScope(k, els[k].checked);
    renderStats();
    apply();
  });
}

// 手机上筛选项折叠在「筛选」按钮后面，按钮上显示已启用的筛选条件数
function renderFilterBtn() {
  const n = [els.status.value !== "active", els.type.value, els.prov.value, els.industry.value,
    els.sort.value !== "name", els.listed.checked, els.hasSite.checked, els.hasEn.checked, els.hmt.checked, els.edu.checked].filter(Boolean).length;
  els.filterBtn.textContent = n ? `筛选 · ${n}` : "筛选";
  els.filterBtn.classList.toggle("active", n > 0);
}

els.filterBtn.addEventListener("click", () => {
  const open = els.controls.classList.toggle("open");
  els.filterBtn.setAttribute("aria-expanded", open);
});

// 筛选栏吸顶后：往下滚收起、往上滚出现；正在输入搜索词时不收起
function autoHideControls() {
  let lastY = scrollY;
  let ticking = false;
  const update = () => {
    ticking = false;
    const y = scrollY;
    const stuck = y > els.controls.parentElement.offsetTop + els.controls.offsetHeight;
    // 只在搜索框输入时保持显示；下拉框 / 复选框操作完焦点会一直留着，不能算
    const busy = document.activeElement === els.q;
    if (!stuck || busy || y < lastY - 6) els.controls.classList.remove("tucked");
    else if (y > lastY + 6) els.controls.classList.add("tucked");
    if (Math.abs(y - lastY) > 6) lastY = y;
  };
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  els.controls.addEventListener("focusin", () => els.controls.classList.remove("tucked")); // Tab 键聚焦时也要看得见
}

autoHideControls();
init();
