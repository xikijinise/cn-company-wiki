# CLAUDE.md

中国企业维基索引：收录维基百科有条目的中国大陆企业（及学校等机构），附官网 / 中文维基 / 英文维基链接。
线上：https://xikijinise.github.io/cn-company-wiki/

## 结构

- `scripts/fetch_companies.py` — 从 Wikidata 抓取，写 `data/companies.json`。只依赖 `requests`。
- `data/companies.json` — 数据文件，提交在仓库里；每周由 Actions 刷新并以 `github-actions[bot]` 身份提交回来（改代码前先 `git pull`）。
- `site/` — 纯静态前端（index.html / app.js / style.css），无构建、无框架。部署时 `data/` 被复制到站点根目录下，本地预览时 app.js 会回退读取 `../data/`。
- `.github/workflows/deploy.yml` — push 到 main 时直接部署；每周一 03:17 UTC 或手动触发（`refresh`）时先重新抓取再部署。

## 常用命令

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_companies.py          # 约 1 分钟
python -m http.server 8000                 # 打开 http://localhost:8000/site/
gh workflow run deploy.yml -f refresh=true # 在 CI 上重新抓取并部署
```

## 已定下的决策（别轻易推翻）

- **用 QLever 端点**（`https://qlever.dev/api/wikidata`）。官方 `query.wikidata.org` 有 60 秒超时，`wdt:P31/wdt:P279*` 全量遍历跑不完，分批方案也被 502/504/429 拖到一小时以上。QLever 偶尔返回 429 "Operation timed out"，脚本已带重试。
- **收录范围**：`P31/P279*` 属于企业 Q4830453、`P17` = Q148、有 zh 或 en 维基条目。
- **学校等机构也收录**（用户明确要求），不剔除，用 `type` 字段标注（教育机构 / 图书馆 / 品牌 …），前端可按类型筛选。直接标为公司 / 企业等核心类的条目一律归为「企业」，即使同时是「网站」「品牌」（如晋江文学城）。
- **港澳**：只有总部（P159）**全部**在香港 / 澳门才排除；同时登记了大陆总部的（如「北京市 / 香港」）保留。分部 / 分公司一般没有独立条目，有独立条目的作为独立企业收录。
- **保护阈值**：结果少于 3000 条时脚本以非零码退出且不覆盖已有数据，CI 沿用上一版数据。
- 数据错误应在 Wikidata 上修正，不在本仓库手工修补数据。

## 数据格式（前端依赖，改字段要同步改 site/app.js）

```json
{"generated": "ISO8601", "count": 8800, "companies": [
  {"id": "Q860580", "type": "企业", "zh": "华为", "en": "Huawei",
   "zhwiki": "url|null", "enwiki": "url|null", "website": "url|null",
   "hq": "深圳市 | 北京市 / 香港 | null", "industry": ["…"],
   "founded": 1987, "dissolved": null, "listed": false}
]}
```

## 已知数据问题（来自 Wikidata 本身）

- 约 150 条无中文标签。
- 部分条目总部同时填了区和市（「北京市 / 西城区」），或填了无意义的值（「中华人民共和国」「街道地址」）。

## 约定

- 提交身份用 `xikijinise` + GitHub noreply 邮箱（`<用户 id>+xikijinise@users.noreply.github.com`，id 可用 `gh api user -q .id` 查），不要用个人邮箱。该配置只存在本地 `.git/config`，新克隆的环境需要重新设置。
- 云端环境如果限制外网，抓取脚本需要能访问 `qlever.dev`；访问不了时不要动 `data/companies.json`，改用 `gh workflow run deploy.yml -f refresh=true` 在 CI 上刷新。
- 前端文案用简体中文。
