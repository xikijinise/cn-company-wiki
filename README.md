# 中国企业维基索引

收录**维基百科有条目**的中国大陆企业，附官网、中文维基、英文维基链接。

- 网站：https://xikijinise.github.io/cn-company-wiki/
- 数据来源：[Wikidata](https://www.wikidata.org/)（CC0）

## 收录条件

- 是「企业」(Q4830453) 或其任意子类的实例。Wikidata 的这棵分类树也包含学校、图书馆等机构，一并收录，并按类型（企业 / 教育机构 / 图书馆 / …）标注，网页上可筛选
- 国家 (P17) 为中华人民共和国；总部 (P159) **全部**在香港、澳门的排除，同时登记了大陆总部的（如「北京 + 香港」）保留
- 有中文或英文维基百科条目
- 已解散的保留并标注

数据通过 [QLever](https://qlever.dev) 的 Wikidata SPARQL 端点查询（官方 query.wikidata.org 端点 60 秒超时，跑不完全量遍历），全量抓取约 1 分钟。

## 结构

| 路径 | 说明 |
|---|---|
| `scripts/fetch_companies.py` | 从 Wikidata（经 QLever）抓取，输出 `data/companies.json` |
| `data/companies.json` | 数据文件（每周由 GitHub Actions 自动刷新并提交） |
| `site/` | 纯静态前端，无构建步骤：列表页、省份地图（`map.html`）、省份分析（`province.html`） |
| `.github/workflows/deploy.yml` | 每周一抓取数据并部署到 GitHub Pages |

## 本地运行

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_companies.py
python -m http.server 8000
# 打开 http://localhost:8000/site/
```

## 纠错

数据直接来自 Wikidata。发现信息有误，请在对应的 Wikidata 条目上修改，下次每周同步时会自动更新。
