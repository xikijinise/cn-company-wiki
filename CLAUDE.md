# CLAUDE.md

中国企业维基索引：收录维基百科有条目的中国大陆企业（及学校等机构），附官网 / 中文维基 / 英文维基链接。
线上：https://xikijinise.github.io/cn-company-wiki/

## 结构

- `scripts/fetch_companies.py` — 从 Wikidata 抓取（QLever 偶尔输出未转义控制字符，故用 `json.loads(strict=False)`），写 `data/companies.json`。只依赖 `requests`。
- `data/companies.json` — 数据文件，提交在仓库里；每周由 Actions 刷新并以 `github-actions[bot]` 身份提交回来（改代码前先 `git pull`）。
- `site/` — 纯静态前端，无构建。`index.html`+`app.js` 列表页；`map.html`+`map.js` 省份地图；`province.html`+`province.js` 省份分析（`?p=广东省`）；`common.js` 三页共用（esc / loadData / row / 配色）。地图和图表用 ECharts（jsDelivr CDN，钉死 5.5.1），省界 GeoJSON 在 `site/geo/china.json`，各省地级市边界在 `site/geo/<adcode>.json`（直辖市没有；均来自 DataV.GeoAtlas，坐标保留 3 位小数），名称与数据的 `province` / `city` 字段一致（city 取简体标签，否则对不上）。部署时 `data/` 被复制到站点根目录下，本地预览时 app.js 会回退读取 `../data/`。
- `.github/workflows/deploy.yml` — push 到 main 时直接部署；每周一 03:17 UTC 或手动触发（`refresh`）时先重新抓取再部署。在非 main 分支手动触发只抓取并把数据提交回该分支，不部署（`gh workflow run deploy.yml --ref <分支> -f refresh=true`），适合改了抓取脚本后试跑。

## 常用命令

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_companies.py          # 约 1 分钟
python -m http.server 8000                 # 打开 http://localhost:8000/site/
gh workflow run deploy.yml -f refresh=true # 在 CI 上重新抓取并部署
```

## 已定下的决策（别轻易推翻）

- **用 QLever 端点**（`https://qlever.dev/api/wikidata`）。官方 `query.wikidata.org` 有 60 秒超时，`wdt:P31/wdt:P279*` 全量遍历跑不完，分批方案也被 502/504/429 拖到一小时以上。QLever 偶尔返回 429 "Operation timed out"，脚本已带重试。
- **收录范围**：`P31/P279*` 属于企业 Q4830453、`P17` ∈ {Q148 中国, Q865 台湾, Q8646 香港, Q14773 澳门}、有 zh 或 en 维基条目。没填 `P17` 的，看总部（P159）/ 所在行政区（P131）的 `P17` 是否在上述范围（新建条目常只填了总部，约多出 700 条）；港澳台判定里也用它代替国家。
- **学校等机构也收录**（用户明确要求），不剔除，用 `type` 字段标注（教育机构 / 图书馆 / 品牌 …），前端可按类型筛选。**教育机构默认不显示**（用户要求），由「含教育机构」开关控制，与「含港澳台」同一套机制（`common.js` 的 `SCOPES`，localStorage `cnwiki.edu`，列表页 hash `edu`），列表 / 地图 / 省份页共用。直接标为公司 / 企业等核心类的条目一律归为「企业」，即使同时是「网站」「品牌」（如晋江文学城）。
- **港澳台**：可选，**默认关闭**（用户要求）。数据里带 `"hmt": true` 标记，前端列表页 / 地图页的「含港澳台」开关控制显示，状态存 localStorage（`cnwiki.hmt`），列表页 hash 里也有 `hmt`。判定：`P17` 不含 Q148 的（台湾等）算港澳台；否则有总部（P159）看总部、没总部看所在行政区（P131），**全部**在香港 / 澳门才算；两者都没填的看国家（P17）是否含港澳（香港公共图书馆等就是这样漏进大陆的）。同时登记了大陆总部的（如「北京市 / 香港」）算大陆。港澳台条目的 `province` 为 香港特别行政区 / 澳门特别行政区 / 台湾省（先看总部 / 所在地，没有则按 P17），`city` 恒为 null。分部 / 分公司一般没有独立条目，有独立条目的作为独立企业收录。
- **不是机构的名词**（如「沙县小吃」这种小吃 / 菜系、街道）剔除：`NOT_ORG` 里的类经 P31/P279* 命中即排除，直接标为公司等核心类的不受影响。被剔除的条目会打印在抓取日志里，发现误伤 / 漏网就调整 `NOT_ORG`。
- **官网挑选**：从 `p:P856` 取全部非弃用值，按「未结束（无 P582）> 不是存档 / 社交平台 > 中文（P407）> 不像英文版（`english.`、`/en/`）> 首选等级 > https > 短」挑一个；粘连的坏网址只取第一个。Wikidata 没填官网、或挑出来的仍是英文版的，读中文、再读英文维基百科信息框的 website / 网站参数兜底（英文版只在原本空着时才用）。
- **保护阈值**：大陆条目少于 3000 条时脚本以非零码退出且不覆盖已有数据，CI 沿用上一版数据。
- 数据错误应在 Wikidata 上修正，不在本仓库手工修补数据。

## 数据格式（前端依赖，改字段要同步改 site/app.js）

```json
{"generated": "ISO8601", "count": 8800, "companies": [
  {"id": "Q860580", "type": "企业", "zh": "华为", "en": "Huawei",
   "zhwiki": "url|null", "enwiki": "url|null", "website": "url|null",
   "hq": "深圳市 | 北京市 / 香港 | null", "province": "广东省 | null", "city": "深圳市 | null",
   "industry": ["…"],
   "founded": 1987, "dissolved": null, "listed": false, "hmt": true /* 仅港澳台条目有此键 */}
]}
```

## 已知数据问题（来自 Wikidata 本身）

- `province` / `city` 由总部 P159（没有则用 P131）沿 P131* 上溯到 31 个省级行政区 / 地级行政区得出。地级行政区认 `CITY_CLASSES` 里的类（地级市、副省级市、自治州、地区、盟、省直辖县级行政区）——只认地级市时哈尔滨、长春（副省级市）和自治州下的城市都会变成「未知」。约一半条目两者都没填，不进地图。直辖市的 city 即自身。新疆兵团新设的新星市、草湖市不在 DataV 边界里，城市地图上不着色。

- 约 150 条无中文标签。
- 部分条目总部同时填了区和市（「北京市 / 西城区」），或填了无意义的值（「中华人民共和国」「街道地址」）。

## 约定

- 提交身份用 `Claude <noreply@anthropic.com>`（用户选定；云端环境的检查要求提交者邮箱为此，否则 GitHub 显示 Unverified），不要用个人邮箱。该配置只存在本地 `.git/config`，新克隆的环境需要重新设置。早期提交用的是 `xikijinise` 的 noreply 邮箱，不必改写。
- 云端环境如果限制外网，抓取脚本需要能访问 `qlever.dev`；访问不了时不要动 `data/companies.json`，改用 `gh workflow run deploy.yml -f refresh=true` 在 CI 上刷新。
- 前端文案用简体中文。
