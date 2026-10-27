# 中国企业维基索引

收录**维基百科有条目**的中国大陆企业，附官网、中文维基、英文维基链接。

- 网站：https://xikijinise.github.io/cn-company-wiki/
- 数据来源：[Wikidata](https://www.wikidata.org/)（CC0）

## 收录条件

- 是「企业」(Q4830453) 或其任意子类的实例
- 国家 (P17) 为中华人民共和国，且总部 (P159) 不在香港、澳门
- 有中文或英文维基百科条目
- 已解散的企业保留并标注

## 结构

| 路径 | 说明 |
|---|---|
| `scripts/fetch_companies.py` | 从 Wikidata SPARQL 分批抓取，输出 `data/companies.json` |
| `data/companies.json` | 数据文件（每周由 GitHub Actions 自动刷新并提交） |
| `site/` | 纯静态前端，无构建步骤 |
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
