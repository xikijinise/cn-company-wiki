#!/usr/bin/env python3
"""从 Wikidata 抓取中国大陆、且有中文或英文维基百科条目的企业，输出 data/companies.json。

查询走 QLever（https://qlever.dev）的 Wikidata 端点：它能在几十秒内跑完
P31/P279* 全量遍历，而官方 query.wikidata.org 端点 60 秒就会超时。
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

ENDPOINTS = ["https://qlever.dev/api/wikidata"]
USER_AGENT = "cn-company-wiki/1.0 (https://github.com/xikijinise/cn-company-wiki)"
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "companies.json"
MIN_COUNT = 3000  # 少于此数视为抓取异常，不覆盖已有数据

PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

# 企业 (Q4830453) 子类树在 Wikidata 里也包含学校、图书馆等机构，全部收录，按实例类型归类。
# 顺序即优先级：同时属于多个类时取靠前的。都不属于则归为「企业」。
CATEGORIES = {
    "Q2385804": "教育机构",
    "Q7075": "图书馆",
    "Q31855": "研究机构",
    "Q4671277": "研究机构",
    "Q16917": "医院",
    "Q33506": "博物馆",
    "Q327333": "政府机构",
    "Q56061": "政府机构",
    "Q210272": "文化遗产",
    "Q358": "文化遗产",
    "Q35127": "网站",
    "Q431289": "品牌",
}

COMPANIES = """
SELECT DISTINCT ?c WHERE {
  ?c wdt:P17 wd:Q148 ; wdt:P31/wdt:P279* wd:Q4830453 .
  ?a schema:about ?c ; schema:isPartOf ?w .
  VALUES ?w { <https://zh.wikipedia.org/> <https://en.wikipedia.org/> }
}"""

DETAILS = PREFIXES + """
SELECT ?c ?label ?zhwiki ?enwiki ?hq ?hqLabel ?inception ?dissolved ?ind ?indLabel ?exch WHERE {
  { %s }
  OPTIONAL { ?zhwiki schema:about ?c ; schema:isPartOf <https://zh.wikipedia.org/> }
  OPTIONAL { ?enwiki schema:about ?c ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?c rdfs:label ?label FILTER(LANG(?label) IN ("zh-cn", "zh-hans", "zh", "en")) }
  OPTIONAL { ?c wdt:P159 ?hq . ?hq rdfs:label ?hqLabel FILTER(LANG(?hqLabel) IN ("zh-cn", "zh-hans", "zh", "en")) }
  OPTIONAL { ?c wdt:P571 ?inception }
  OPTIONAL { ?c wdt:P576 ?dissolved }
  OPTIONAL { ?c wdt:P452 ?ind . ?ind rdfs:label ?indLabel FILTER(LANG(?indLabel) IN ("zh-cn", "zh-hans", "zh", "en")) }
  OPTIONAL { ?c wdt:P414 ?exch }
}""" % COMPANIES

# 直接标为这些类型的条目即使同时属于上面的类（如「网站」「品牌」）也归为「企业」，例如晋江文学城
CORE_CLASSES = {
    "Q4830453": "企业",
    "Q783794": "公司",
    "Q891723": "上市公司",
    "Q6881511": "工商企业",
    "Q270791": "国有企业",
    "Q124343324": "中国国有企业",
    "Q6566978": "中央企业",
    "Q219577": "控股公司",
    "Q658255": "子公司",
    "Q97174998": "有限责任公司",
    "Q1589009": "私人公司",
}

CATEGORY = PREFIXES + """
SELECT DISTINCT ?c ?cat WHERE {
  { %s }
  VALUES ?cat { %s }
  ?c wdt:P31/wdt:P279* ?cat .
  FILTER NOT EXISTS { VALUES ?core { %s } ?c wdt:P31 ?core }
}""" % (COMPANIES, " ".join("wd:" + q for q in CATEGORIES), " ".join("wd:" + q for q in CORE_CLASSES))

# 只是一个名词、不是机构的条目：小吃 / 菜系（如沙县小吃）、街道等。
# 别加「地理特征」「建筑」这类宽泛的类：酒店、大学、图书馆都会被误伤。
# 直接标为公司等核心类（CORE_CLASSES）的条目不受影响。
NOT_ORG = {
    "Q2095": "食物",
    "Q19861951": "食品种类",  # 沙县小吃同时是「连锁餐厅」和「食品种类」，按后者剔除
    "Q746549": "菜肴",
    "Q1778821": "菜系",
    "Q79007": "街道",
}

NONORG = PREFIXES + """
SELECT DISTINCT ?c ?cls WHERE {
  { %s }
  VALUES ?cls { %s }
  ?c wdt:P31/wdt:P279* ?cls .
  FILTER NOT EXISTS { VALUES ?core { %s } ?c wdt:P31 ?core }
}""" % (COMPANIES, " ".join("wd:" + q for q in NOT_ORG), " ".join("wd:" + q for q in CORE_CLASSES))

# 官网（P856）连同等级和限定符一起取：同一条目常有中英文多个官网，需按语言挑选
WEBSITES = PREFIXES + """
SELECT ?c ?site ?rank ?lang ?end WHERE {
  { %s }
  ?c p:P856 ?st . ?st ps:P856 ?site ; wikibase:rank ?rank .
  FILTER(?rank != wikibase:DeprecatedRank)
  OPTIONAL { ?st pq:P407 ?lang }
  OPTIONAL { ?st pq:P582 ?end }
}""" % COMPANIES

# 港澳判定用到的位置：总部 P159、所在行政区 P131、国家 P17，以及其中位于港澳的那些
SAR = {"Q8646", "Q14773"}
PLACES = PREFIXES + """
SELECT DISTINCT ?c ?src ?loc ?sar WHERE {
  { %s }
  { ?c wdt:P159 ?loc BIND("hq" AS ?src) } UNION { ?c wdt:P131 ?loc BIND("in" AS ?src) }
  UNION { ?c wdt:P17 ?loc BIND("country" AS ?src) }
  OPTIONAL { ?loc wdt:P131* ?sar . VALUES ?sar { wd:Q8646 wd:Q14773 } }
}""" % COMPANIES

# 省级行政区（大陆 31 个），名称与前端地图 GeoJSON 的 name 一致
PROVINCES = {
    "Q956": "北京市", "Q11736": "天津市", "Q21208": "河北省", "Q46913": "山西省", "Q41079": "内蒙古自治区",
    "Q43934": "辽宁省", "Q45208": "吉林省", "Q19206": "黑龙江省", "Q8686": "上海市", "Q16963": "江苏省",
    "Q16967": "浙江省", "Q40956": "安徽省", "Q41705": "福建省", "Q57052": "江西省", "Q43407": "山东省",
    "Q43684": "河南省", "Q46862": "湖北省", "Q45761": "湖南省", "Q15175": "广东省", "Q15176": "广西壮族自治区",
    "Q42200": "海南省", "Q11725": "重庆市", "Q19770": "四川省", "Q47097": "贵州省", "Q43194": "云南省",
    "Q17269": "西藏自治区", "Q47974": "陕西省", "Q42392": "甘肃省", "Q45833": "青海省", "Q57448": "宁夏回族自治区",
    "Q34800": "新疆维吾尔自治区",
}
MUNICIPALITIES = {"Q956", "Q11736", "Q8686", "Q11725"}

# 由总部（P159）沿 P131* 上溯到省级和地级市（Q748149）；没填总部的退而用条目自身的 P131
LOCATION = PREFIXES + """
SELECT DISTINCT ?c ?src ?loc ?prov ?city ?cityLabel WHERE {
  { %s }
  { ?c wdt:P159 ?loc BIND("hq" AS ?src) } UNION { ?c wdt:P131 ?loc BIND("in" AS ?src) }
  VALUES ?prov { %s }
  ?loc wdt:P131* ?prov .
  OPTIONAL {
    ?loc wdt:P131* ?city . ?city wdt:P31 wd:Q748149 .
    ?city rdfs:label ?cityLabel FILTER(LANG(?cityLabel) IN ("zh-cn", "zh-hans", "zh"))
  }
}""" % (COMPANIES, " ".join("wd:" + q for q in PROVINCES))

ZH_ORDER = ("zh-cn", "zh-hans", "zh")


def sparql(query: str) -> list[dict]:
    headers = {"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT}
    for attempt in range(5):
        for ep in ENDPOINTS:
            try:
                r = requests.post(ep, data={"query": query}, headers=headers, timeout=300)
                if r.status_code == 200:
                    # QLever 偶尔在字符串里输出未转义的控制字符，strict=False 容忍之
                    return json.loads(r.text, strict=False)["results"]["bindings"]
                print(f"  {ep} -> HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
            except (requests.RequestException, ValueError) as e:
                print(f"  {ep} -> {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("all SPARQL attempts failed")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def year(v: str | None) -> int | None:
    # xsd:dateTime 形如 "1987-09-15T00:00:00Z"，公元前为 "-0500-..."
    if not v:
        return None
    try:
        return int(v[:5]) if v.startswith("-") else int(v[:4])
    except ValueError:
        return None


def pick_label(labels: dict[str, str], zh: bool) -> str | None:
    for lang in (ZH_ORDER if zh else ("en",)):
        if lang in labels:
            return labels[lang]
    return None


def pick_any(labels: dict[str, str]) -> str | None:
    return pick_label(labels, True) or labels.get("en")


# P407 作品语言：中文 / 标准汉语 / 简体 / 繁体 / 普通话
ZH_LANGS = {"Q7850", "Q727694", "Q13414913", "Q18130932", "Q9192"}
# 存档、社交平台、百科、学校建站平台等不是真正的官网，仅在没有别的选择时使用
NOT_OFFICIAL = re.compile(
    r"(^|\.)(archive\.org|archive\.today|archive\.ph|weibo\.com|weibo\.cn|douban\.com|facebook\.com|twitter\.com|x\.com"
    r"|instagram\.com|youtube\.com|linkedin\.com|baike\.baidu\.com|wikipedia\.org|worlduc\.com|mp\.weixin\.qq\.com)$")
# 英文版官网：english.xxx / en.xxx 子域名，或 /en、/english、english.htm 之类的路径
ENGLISH = re.compile(r"(^|[./_-])(en|eng|english)([./_-]|$)", re.I)


def clean_url(u: str) -> str | None:
    u = u.strip()
    # 偶有两个网址粘在一起（"http://a.com/?x=1https://b.com/"），取第一个
    m = re.match(r"(https?://.+?)(?=(?<![/=])https?://|$)", u, re.I)
    if m:
        u = m.group(1)
    elif re.match(r"(www\.)?[\w-]+(\.[\w-]+)+(/|$)", u):
        u = "http://" + u
    else:
        return None
    host = urlparse(u).hostname
    return u if host and "." in host else None


def site_key(u: str, preferred: bool = False, langs: frozenset[str] = frozenset(), ended: bool = False) -> tuple:
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    lang = 0 if langs & ZH_LANGS else (2 if langs else 1)
    english = bool(ENGLISH.search(host.split(".", 1)[0]) or ENGLISH.search(parsed.path + "?" + parsed.query))
    return (ended, bool(NOT_OFFICIAL.search(host)), lang, english, not preferred,
            not u.startswith("https://"), len(u), u)


def pick_site(sites: dict[str, tuple]) -> str | None:
    """sites: url -> site_key 参数 (preferred, langs, ended)。未结束 > 正式官网 > 中文 > 首选等级 > https > 短。"""
    if not sites:
        return None
    return min(sites, key=lambda u: site_key(u, *sites[u]))


# 维基百科信息框里的官网参数（只看导言部分，避免把参考文献的 url= 当成官网）
WIKI_SITE_PARAM = re.compile(
    r"^\s*\|\s*(?:website|homepage|网站|網站|网址|網址|官方网站|官方網站|官网|官網|主页|主頁)\s*=\s*(.*)$",
    re.I | re.M)
WIKI_SITE_TEMPLATE = re.compile(r"\{\{\s*(?:official website|official site|官方网站|官方網站|官网)\s*\|\s*(?:1=|url=)?([^|}]+)", re.I)


def wikitext_site(text: str) -> str | None:
    text = re.sub(r"<!--.*?-->|<ref[^>/]*/>|<ref.*?</ref>", "", text, flags=re.S)
    lead = re.split(r"\n==[^=]", text, maxsplit=1)[0]
    candidates = [m.group(1) for m in WIKI_SITE_PARAM.finditer(lead)]
    candidates += [m.group(1) for m in WIKI_SITE_TEMPLATE.finditer(text)]
    for v in candidates:
        # {{URL|x}}、[http://x 名称]、裸网址；{{Official URL}} 之类从 Wikidata 取值的模板没有网址，跳过
        m = (re.search(r"\{\{\s*url\s*\|\s*(?:1=)?\s*([^|}\s]+)", v, re.I)
             or re.search(r"(https?://[^\s|\]}<]+)", v, re.I)
             or re.match(r"\s*((?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/[^\s|\]}<]*)?)\s*$", v))
        if m:
            u = clean_url(m.group(1))
            if u and not NOT_OFFICIAL.search((urlparse(u).hostname or "").lower()):
                return u
    return None


def wiki_sites(urls: dict[str, str]) -> dict[str, str]:
    """urls: 条目 id -> 维基百科文章网址（同一语言）。返回从信息框读到的官网。失败时尽量返回已拿到的部分。"""
    if not urls:
        return {}
    api = urlparse(next(iter(urls.values())))._replace(path="/w/api.php", query="").geturl()
    by_title = {unquote(urlparse(u).path.split("/wiki/", 1)[1]).replace("_", " "): c for c, u in urls.items()}
    titles, found = list(by_title), {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        params = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                  "format": "json", "formatversion": "2", "redirects": "1", "titles": "|".join(batch)}
        cont: dict = {}
        while True:
            data = None
            for attempt in range(5):
                try:
                    r = requests.get(api, params={**params, **cont}, headers={"User-Agent": USER_AGENT}, timeout=60)
                    if r.status_code == 429:  # 限流：按 Retry-After 等待后重试
                        time.sleep(int(r.headers.get("Retry-After", "") or 0) or 5 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    data = r.json()
                    break
                except (requests.RequestException, ValueError) as e:
                    print(f"  {api} -> {type(e).__name__}: {e}", file=sys.stderr)
                    time.sleep(5 * (attempt + 1))
            if data is None:
                break
            q = data.get("query", {})
            # 标题归一化 / 重定向后要映射回原标题
            alias = {}
            for k in ("normalized", "redirects"):
                for x in q.get(k, []):
                    alias[x["to"]] = alias.get(x["from"], x["from"])
            for page in q.get("pages", []):
                revs = page.get("revisions")
                if not revs:
                    continue
                c = by_title.get(alias.get(page["title"], page["title"]))
                site = wikitext_site(revs[0].get("slots", {}).get("main", {}).get("content", ""))
                if c and site:
                    found[c] = site
            if "continue" not in data:
                break
            cont = data["continue"]
            time.sleep(1)
        time.sleep(1)
    return found


def main() -> int:
    t0 = time.time()
    print("Querying company details…", file=sys.stderr)
    rows = sparql(DETAILS)
    print(f"  {len(rows)} rows in {time.time() - t0:.0f}s", file=sys.stderr)

    print("Querying places (HK/Macau exclusion)…", file=sys.stderr)
    # places[c][src][loc] = 是否位于港澳
    places: dict[str, dict[str, dict[str, bool]]] = {}
    for r in sparql(PLACES):
        slot = places.setdefault(qid(r["c"]["value"]), {}).setdefault(r["src"]["value"], {})
        loc = qid(r["loc"]["value"])
        slot[loc] = slot.get(loc, False) or "sar" in r
    # 有总部看总部，没总部看所在行政区：全部在港澳才排除（同时登记了大陆总部的保留）；都没填则看国家是否含港澳
    excluded = set()
    for c, srcs in places.items():
        for src in ("hq", "in"):
            if srcs.get(src):
                if all(srcs[src].values()):
                    excluded.add(c)
                break
        else:
            if any(srcs.get("country", {}).values()):
                excluded.add(c)
    print(f"  {len(excluded)} excluded", file=sys.stderr)

    print("Querying non-organisations…", file=sys.stderr)
    not_org: dict[str, set[str]] = {}
    for r in sparql(NONORG):
        not_org.setdefault(qid(r["c"]["value"]), set()).add(NOT_ORG[qid(r["cls"]["value"])])
    print(f"  {len(not_org)} found", file=sys.stderr)

    print("Querying websites…", file=sys.stderr)
    # sites[c][url] = (preferred, langs, ended)
    sites: dict[str, dict[str, tuple[bool, frozenset[str], bool]]] = {}
    for r in sparql(WEBSITES):
        u = clean_url(r["site"]["value"])
        if not u:
            continue
        slot = sites.setdefault(qid(r["c"]["value"]), {})
        pref, langs, ended = slot.get(u, (False, frozenset(), False))
        lang = r.get("lang", {}).get("value")
        slot[u] = (pref or r["rank"]["value"].endswith("PreferredRank"),
                   langs | {qid(lang)} if lang else langs, ended or "end" in r)

    print("Querying categories…", file=sys.stderr)
    priority = list(CATEGORIES)
    cats: dict[str, str] = {}
    for r in sparql(CATEGORY):
        c, cat = qid(r["c"]["value"]), qid(r["cat"]["value"])
        if c not in cats or priority.index(cat) < priority.index(cats[c]):
            cats[c] = cat

    print("Querying provinces/cities…", file=sys.stderr)
    # locs[c][src][loc] = (province, city)
    locs: dict[str, dict[str, dict[str, tuple[str, str | None]]]] = {}
    for r in sparql(LOCATION):
        c, src, loc, prov = qid(r["c"]["value"]), r["src"]["value"], qid(r["loc"]["value"]), qid(r["prov"]["value"])
        city = PROVINCES[prov] if prov in MUNICIPALITIES else r.get("cityLabel", {}).get("value")
        slot = locs.setdefault(c, {}).setdefault(src, {})
        if loc not in slot or (slot[loc][1] is None and city):
            slot[loc] = (PROVINCES[prov], city)

    acc: dict[str, dict] = {}
    for r in rows:
        g = lambda k: r.get(k, {}).get("value")
        lang = lambda k: r.get(k, {}).get("xml:lang")
        c = qid(g("c"))
        if c in excluded:
            continue
        d = acc.setdefault(c, {"labels": {}, "hq": {}, "ind": {}, "zhwiki": None,
                               "enwiki": None, "inception": None, "dissolved": None, "listed": False})
        if g("label"):
            d["labels"].setdefault(lang("label"), g("label"))
        if g("hqLabel"):
            d["hq"].setdefault(qid(g("hq")), {}).setdefault(lang("hqLabel"), g("hqLabel"))
        if g("indLabel"):
            d["ind"].setdefault(qid(g("ind")), {}).setdefault(lang("indLabel"), g("indLabel"))
        for k in ("zhwiki", "enwiki"):
            d[k] = d[k] or g(k)
        for k in ("inception", "dissolved"):
            y = year(g(k))
            if y is not None and (d[k] is None or y < d[k]):
                d[k] = y
        if g("exch"):
            d["listed"] = True

    for c in sorted(not_org):
        if c in acc:
            print(f"  not an organisation: {c} {pick_any(acc.pop(c)['labels'])} ({'/'.join(sorted(not_org[c]))})",
                  file=sys.stderr)

    # Wikidata 没填官网的，退而读维基百科信息框（先中文后英文）
    website = {c: pick_site(sites.get(c, {})) for c in acc}
    for wiki in ("zhwiki", "enwiki"):
        todo = {c: d[wiki] for c, d in acc.items() if not website[c] and d[wiki]}
        print(f"Reading {len(todo)} {wiki} infoboxes for missing websites…", file=sys.stderr)
        got = wiki_sites(todo)
        print(f"  {len(got)} found", file=sys.stderr)
        website.update(got)

    companies = []
    for c, d in acc.items():
        zh, en = pick_label(d["labels"], True), pick_label(d["labels"], False)
        industry, hqs = [], []
        for labels in d["ind"].values():
            name = pick_any(labels)
            if name and name not in industry:
                industry.append(name)
        for labels in d["hq"].values():
            name = pick_any(labels)
            if name and name not in hqs:
                hqs.append(name)
        # 省份取显示顺序中第一个能定位的总部，没有则用 P131
        province = city = None
        found = locs.get(c, {})
        hq_order = sorted(d["hq"], key=lambda q: pick_any(d["hq"][q]) or q)
        for src, order in (("hq", hq_order), ("in", sorted(found.get("in", {})))):
            for loc in order:
                if loc in found.get(src, {}):
                    province, city = found[src][loc]
                    break
            if province:
                break
        companies.append({
            "id": c,
            "type": CATEGORIES[cats[c]] if c in cats else "企业",
            "zh": zh,
            "en": en if (en or zh) else c,
            "zhwiki": d["zhwiki"],
            "enwiki": d["enwiki"],
            "website": website[c],
            # 多个总部（如「北京市 / 香港」）合并显示，最多两个
            "hq": " / ".join(sorted(hqs)[:2]) or None,
            "province": province,
            "city": city,
            "industry": sorted(industry)[:3],
            "founded": d["inception"],
            "dissolved": d["dissolved"],
            "listed": d["listed"],
        })
    companies.sort(key=lambda x: (x["zh"] or x["en"] or x["id"], x["id"]))

    stats = {
        "total": len(companies),
        "business": sum(1 for x in companies if x["type"] == "企业"),
        "zhwiki": sum(1 for x in companies if x["zhwiki"]),
        "enwiki": sum(1 for x in companies if x["enwiki"]),
        "website": sum(1 for x in companies if x["website"]),
        "dissolved": sum(1 for x in companies if x["dissolved"] is not None),
        "listed": sum(1 for x in companies if x["listed"]),
        "province": sum(1 for x in companies if x["province"]),
    }
    print("Stats: " + ", ".join(f"{k}={v}" for k, v in stats.items()), file=sys.stderr)

    if len(companies) < MIN_COUNT:
        print(f"Only {len(companies)} companies (< {MIN_COUNT}); keeping existing {OUT_PATH.name}", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(companies),
        "companies": companies,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT_PATH} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
