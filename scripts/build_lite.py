#!/usr/bin/env python3
"""从 data/companies.json 生成地图页用的精简数据 data/lite.json（部署时生成，不提交）。

地图页只用到省份、城市、类型、行业和几个标记，完整数据约 5MB，精简后约 200KB。
字符串字段做字典编码；flags 位：1 上市，2 已解散 / 并入，4 港澳台。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAIRS = [
    (ROOT / "data" / "companies.json", ROOT / "data" / "lite.json"),
    (ROOT / "data" / "companies-wp.json", ROOT / "data" / "lite-wp.json"),
]


def build_one(src: Path, out: Path) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    dicts: dict[str, list[str]] = {"province": [], "city": [], "type": [], "industry": []}
    index: dict[str, dict[str, int]] = {k: {} for k in dicts}

    def code(field: str, value: str | None) -> int:
        if value is None:
            return -1
        if value not in index[field]:
            index[field][value] = len(dicts[field])
            dicts[field].append(value)
        return index[field][value]

    rows = []
    for c in data["companies"]:
        flags = (1 if c["listed"] else 0) | (2 if c["dissolved"] is not None or c.get("successor") else 0) \
            | (4 if c.get("hmt") else 0)
        rows.append([code("province", c["province"]), code("city", c["city"]), code("type", c["type"]),
                     [code("industry", i) for i in c["industry"]], flags])

    out.write_text(json.dumps({"generated": data["generated"], "dicts": dicts, "rows": rows},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB, {len(rows)} rows)", file=sys.stderr)


def main() -> int:
    for src, out in PAIRS:
        if src.exists():
            build_one(src, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
