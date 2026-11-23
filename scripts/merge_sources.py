#!/usr/bin/env python3
"""合并 Wikidata（data/companies.json）与 Wikipedia（data/companies-wp.json）双源数据，
输出 data/companies-merged.json。

合并规则：
1. 按 QID、zhwiki URL、enwiki URL 去重对齐；
2. 结构化字段（website / founded / dissolved / successor / city / hq / type）优先取 Wikidata，缺失时用 Wikipedia 补齐；
3. province 优先取 Wikidata，缺失时用 Wikipedia 地域分类/信息框补齐；
4. industry 取两者并集（最多 3 个）；listed 取逻辑或；
5. 同时保留两个数据源的独有条目，最大化中国企业覆盖率。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
WD_PATH = ROOT / "data" / "companies.json"
WP_PATH = ROOT / "data" / "companies-wp.json"
OUT_PATH = ROOT / "data" / "companies-merged.json"


def norm_url(u: str | None) -> str | None:
    if not u:
        return None
    return unquote(u).rstrip("/")


def merge_pair(wd: dict, wp: dict) -> dict:
    industry: list[str] = []
    for ind in (wd.get("industry") or []) + (wp.get("industry") or []):
        if ind and ind not in industry:
            industry.append(ind)
        if len(industry) >= 3:
            break

    is_hmt = bool(wd.get("hmt"))
    province = wd.get("province") or wp.get("province")
    city = None if is_hmt else (wd.get("city") or wp.get("city"))

    rec: dict = {
        "id": wd["id"],
        "type": wd.get("type") or wp.get("type") or "企业",
        "zh": wd.get("zh") or wp.get("zh"),
        "en": wd.get("en") or wp.get("en"),
        "zhwiki": wd.get("zhwiki") or wp.get("zhwiki"),
        "enwiki": wd.get("enwiki") or wp.get("enwiki"),
        "website": wd.get("website") or wp.get("website"),
        "hq": wd.get("hq") or wp.get("hq"),
        "province": province,
        "city": city,
        "industry": industry,
        "founded": wd.get("founded") if wd.get("founded") is not None else wp.get("founded"),
        "dissolved": wd.get("dissolved") if wd.get("dissolved") is not None else wp.get("dissolved"),
        "listed": bool(wd.get("listed") or wp.get("listed")),
    }
    succ = wd.get("successor") or wp.get("successor")
    if succ:
        rec["successor"] = dict(succ)
    if is_hmt:
        rec["hmt"] = True
    return rec


def main() -> int:
    if not WD_PATH.exists() or not WP_PATH.exists():
        print("Need both data/companies.json and data/companies-wp.json to merge.", file=sys.stderr)
        return 1

    wd_payload = json.loads(WD_PATH.read_text(encoding="utf-8"))
    wp_payload = json.loads(WP_PATH.read_text(encoding="utf-8"))
    wd_list = wd_payload["companies"]
    wp_list = wp_payload["companies"]

    merged: list[dict] = [dict(c) for c in wd_list]
    by_qid: dict[str, int] = {}
    by_zh: dict[str, int] = {}
    by_en: dict[str, int] = {}

    for idx, c in enumerate(merged):
        if c["id"].startswith("Q"):
            by_qid[c["id"]] = idx
        zh_u = norm_url(c.get("zhwiki"))
        en_u = norm_url(c.get("enwiki"))
        if zh_u:
            by_zh[zh_u] = idx
        if en_u:
            by_en[en_u] = idx

    matched = 0
    added = 0
    for wp in wp_list:
        idx = None
        if wp["id"].startswith("Q") and wp["id"] in by_qid:
            idx = by_qid[wp["id"]]
        else:
            zh_u = norm_url(wp.get("zhwiki"))
            en_u = norm_url(wp.get("enwiki"))
            if zh_u and zh_u in by_zh:
                idx = by_zh[zh_u]
            elif en_u and en_u in by_en:
                idx = by_en[en_u]

        if idx is not None:
            merged[idx] = merge_pair(merged[idx], wp)
            matched += 1
        else:
            rec = dict(wp)
            if "successor" in rec:
                rec["successor"] = dict(rec["successor"])
            new_idx = len(merged)
            merged.append(rec)
            if rec["id"].startswith("Q"):
                by_qid[rec["id"]] = new_idx
            zh_u = norm_url(rec.get("zhwiki"))
            en_u = norm_url(rec.get("enwiki"))
            if zh_u:
                by_zh[zh_u] = new_idx
            if en_u:
                by_en[en_u] = new_idx
            added += 1

    merged.sort(key=lambda x: (x.get("zh") or x.get("en") or x["id"], x["id"]))

    ids = {x["id"] for x in merged}
    names = {x["zh"] for x in merged if x.get("zh")} | {x["en"] for x in merged if x.get("en")}
    for x in merged:
        if "successor" in x:
            s = x["successor"]
            s["here"] = s["id"] in ids or s["name"] in names

    gen = max(wd_payload.get("generated", ""), wp_payload.get("generated", "")) or \
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated": gen,
        "source": "merged",
        "count": len(merged),
        "companies": merged,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Merged: wd={len(wd_list)}, wp={len(wp_list)}, matched={matched}, wp_only_added={added} -> total={len(merged)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
