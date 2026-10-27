#!/usr/bin/env python3
"""从 Wikidata 抓取中国大陆、且有中文或英文维基百科条目的企业，输出 data/companies.json。

查询走 QLever（https://qlever.dev）的 Wikidata 端点：它能在几十秒内跑完
P31/P279* 全量遍历，而官方 query.wikidata.org 端点 60 秒就会超时。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ENDPOINTS = ["https://qlever.dev/api/wikidata"]
USER_AGENT = "cn-company-wiki/1.0 (https://github.com/xikijinise/cn-company-wiki)"
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "companies.json"
MIN_COUNT = 3000  # 少于此数视为抓取异常，不覆盖已有数据

PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
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
SELECT ?c ?label ?zhwiki ?enwiki ?site ?hq ?hqLabel ?inception ?dissolved ?ind ?indLabel ?exch WHERE {
  { %s }
  OPTIONAL { ?zhwiki schema:about ?c ; schema:isPartOf <https://zh.wikipedia.org/> }
  OPTIONAL { ?enwiki schema:about ?c ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?c rdfs:label ?label FILTER(LANG(?label) IN ("zh-cn", "zh-hans", "zh", "en")) }
  OPTIONAL { ?c wdt:P856 ?site }
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

# 所有总部都在港澳才排除；同时登记了大陆总部（如「北京 + 香港」）的保留
EXCLUDED = PREFIXES + """
SELECT DISTINCT ?c WHERE {
  { %s }
  ?c wdt:P159/wdt:P131* ?sar . VALUES ?sar { wd:Q8646 wd:Q14773 }
  FILTER NOT EXISTS {
    ?c wdt:P159 ?hq2 .
    FILTER NOT EXISTS { ?hq2 wdt:P131* ?sar2 . VALUES ?sar2 { wd:Q8646 wd:Q14773 } }
  }
}""" % COMPANIES

ZH_ORDER = ("zh-cn", "zh-hans", "zh")


def sparql(query: str) -> list[dict]:
    headers = {"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT}
    for attempt in range(5):
        for ep in ENDPOINTS:
            try:
                r = requests.post(ep, data={"query": query}, headers=headers, timeout=300)
                if r.status_code == 200:
                    return r.json()["results"]["bindings"]
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


def pick_site(sites: set[str]) -> str | None:
    if not sites:
        return None
    return sorted(sites, key=lambda u: (not u.startswith("https://"), len(u), u))[0]


def main() -> int:
    t0 = time.time()
    print("Querying company details…", file=sys.stderr)
    rows = sparql(DETAILS)
    print(f"  {len(rows)} rows in {time.time() - t0:.0f}s", file=sys.stderr)

    print("Querying exclusions (HK/Macau HQ)…", file=sys.stderr)
    excluded = {qid(r["c"]["value"]) for r in sparql(EXCLUDED)}
    print(f"  {len(excluded)} excluded", file=sys.stderr)

    print("Querying categories…", file=sys.stderr)
    priority = list(CATEGORIES)
    cats: dict[str, str] = {}
    for r in sparql(CATEGORY):
        c, cat = qid(r["c"]["value"]), qid(r["cat"]["value"])
        if c not in cats or priority.index(cat) < priority.index(cats[c]):
            cats[c] = cat

    acc: dict[str, dict] = {}
    for r in rows:
        g = lambda k: r.get(k, {}).get("value")
        lang = lambda k: r.get(k, {}).get("xml:lang")
        c = qid(g("c"))
        if c in excluded:
            continue
        d = acc.setdefault(c, {"labels": {}, "sites": set(), "hq": {}, "ind": {}, "zhwiki": None,
                               "enwiki": None, "inception": None, "dissolved": None, "listed": False})
        if g("label"):
            d["labels"].setdefault(lang("label"), g("label"))
        if g("hqLabel"):
            d["hq"].setdefault(qid(g("hq")), {}).setdefault(lang("hqLabel"), g("hqLabel"))
        if g("indLabel"):
            d["ind"].setdefault(qid(g("ind")), {}).setdefault(lang("indLabel"), g("indLabel"))
        for k in ("zhwiki", "enwiki"):
            d[k] = d[k] or g(k)
        if g("site"):
            d["sites"].add(g("site"))
        for k in ("inception", "dissolved"):
            y = year(g(k))
            if y is not None and (d[k] is None or y < d[k]):
                d[k] = y
        if g("exch"):
            d["listed"] = True

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
        companies.append({
            "id": c,
            "type": CATEGORIES[cats[c]] if c in cats else "企业",
            "zh": zh,
            "en": en if (en or zh) else c,
            "zhwiki": d["zhwiki"],
            "enwiki": d["enwiki"],
            "website": pick_site(d["sites"]),
            # 多个总部（如「北京市 / 香港」）合并显示，最多两个
            "hq": " / ".join(sorted(hqs)[:2]) or None,
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
