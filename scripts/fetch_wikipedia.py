#!/usr/bin/env python3
"""从维基百科（中文 + 英文 MediaWiki API）抓取中国（含港澳台，带 hmt 标记）企业，输出 data/companies-wp.json。

纯 Wikipedia API 方案（不查询 Wikidata / QLever）：
1. 递归遍历中英文维基百科的中国 / 港澳台公司分类树，记录每篇条目的所属分类；
2. 批量拉取条目导言（rvsection=0）与 langlinks / pageprops(wikibase_item)，对齐中英文条目；
3. 解析信息框（Infobox company / 公司信息框等）与地域分类，输出与 data/companies.json 相同结构。
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import urllib3.util.connection

# 部分云端环境无 IPv6 路由，禁用 IPv6 避免间歇性 Network is unreachable
urllib3.util.connection.HAS_IPV6 = False

_TLS = threading.local()


def get_session() -> requests.Session:
    s = getattr(_TLS, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        _TLS.session = s
    return s


USER_AGENT = "cn-company-wiki/1.0 (https://github.com/xikijinise/cn-company-wiki)"
ROOT = Path(__file__).resolve().parent.parent
GEO_DIR = ROOT / "site" / "geo"
OUT_PATH = ROOT / "data" / "companies-wp.json"
MIN_COUNT = 1000  # 少于此数视为抓取异常，不覆盖已有数据

# 分类树起点：(语言, 分类名, 最大深度, 默认港澳台省份或 None)
SEEDS = [
    # 中国大陆企业（中文维基）
    ("zh", "Category:中华人民共和国公司", 2, None),
    ("zh", "Category:中国各省公司", 2, None),
    ("zh", "Category:中国各城市公司", 2, None),
    ("zh", "Category:中华人民共和国企业", 2, None),
    ("zh", "Category:中华人民共和国已结业公司", 2, None),
    # 中国大陆机构：高校、图书馆、医院、博物馆（与 Wikidata 保持同一收录口径）
    ("zh", "Category:中国高等院校", 2, None),
    ("zh", "Category:中国图书馆", 2, None),
    ("zh", "Category:中国医院", 2, None),
    ("zh", "Category:中国博物馆", 2, None),
    # 港澳台（中文维基）
    ("zh", "Category:香港公司", 2, "香港特别行政区"),
    ("zh", "Category:澳門公司", 1, "澳门特别行政区"),
    ("zh", "Category:台灣公司", 2, "台湾省"),
    ("zh", "Category:香港大專院校", 1, "香港特别行政区"),
    ("zh", "Category:台灣大專院校", 2, "台湾省"),
    # 中国大陆（英文维基）
    ("en", "Category:Companies of China by province", 2, None),
    ("en", "Category:Companies of China by city", 2, None),
    ("en", "Category:Companies of China by industry", 2, None),
    ("en", "Category:Companies of China", 1, None),
    ("en", "Category:Defunct companies of China", 1, None),
    ("en", "Category:Universities and colleges in China", 2, None),
    ("en", "Category:Libraries in China", 1, None),
    ("en", "Category:Hospitals in China", 1, None),
    ("en", "Category:Museums in China", 1, None),
    # 港澳台（英文维基）
    ("en", "Category:Companies of Hong Kong", 2, "香港特别行政区"),
    ("en", "Category:Companies of Macau", 1, "澳门特别行政区"),
    ("en", "Category:Companies of Taiwan", 2, "台湾省"),
]

# 排除会漂移到人物、产品、事件、历史朝代、按年份重复、列表、模板的子分类
SKIP_CAT_ZH = re.compile(
    r"(人物|列表|模板|小作品|命名的分[类類]|[历歷]史|[债債][务務]|事件|[争爭][议議]|[诉訴][讼訟]|"
    r"作品|[电電]影|[游遊][戏戲]|[软軟]件|[产產]品|[车車]型|各朝代|清朝|民[国國]|明朝|宋朝|唐朝|"
    r"[财財][阀閥]|建筑|建築|大[厦廈]|[标標][志誌]|[广廣]告|文化|事故|[丑醜][闻聞]|品牌|商[标標]|"
    r"雇[员員]|[员員]工|董事|高管|创始人|創辦人|CEO|总裁|總裁|企[业業]家|吉祥物|总部大楼|總部大樓|"
    r"在[华華]外[资資]|外[资資]在[华華]|外国公司|外國公司|殖民地|"
    r"各年|年成立|年[结結][业業]|各世[纪紀]|各年代|年代成立)"
)
SKIP_CAT_EN = re.compile(
    r"(People by company|Lists of |stubs|categories named after|History of |Templates|"
    r"Buildings|Products|Vehicles|Video games|Films|Software|Characters|Employees|"
    r"Executives|Founders|Controversies|Disasters|Scandals|Brands|Logos|Mascots|"
    r"Qing dynasty|Republic of China \(1912|Imperial China|foreign companies|"
    r"by year|established in|disestablished in|century)",
    re.I,
)

# 排除明显不是企业的条目标题
SKIP_TITLE_ZH = re.compile(r"(列表|一览|一覽|名单|名單|排行|榜单|榜單|历史|歷史|事件|案$|丑闻|醜聞)$")
SKIP_TITLE_EN = re.compile(r"^(List of |Lists of |History of |Economy of |Index of |Outline of )", re.I)

# 省级行政区代码（与 site/geo/<adcode>.json 对应）
ADCODE = {
    "河北省": 130000, "山西省": 140000, "内蒙古自治区": 150000, "辽宁省": 210000, "吉林省": 220000,
    "黑龙江省": 230000, "江苏省": 320000, "浙江省": 330000, "安徽省": 340000, "福建省": 350000,
    "江西省": 360000, "山东省": 370000, "河南省": 410000, "湖北省": 420000, "湖南省": 430000,
    "广东省": 440000, "广西壮族自治区": 450000, "海南省": 460000, "四川省": 510000, "贵州省": 520000,
    "云南省": 530000, "西藏自治区": 540000, "陕西省": 610000, "甘肃省": 620000, "青海省": 630000,
    "宁夏回族自治区": 640000, "新疆维吾尔自治区": 650000,
}
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
HMT_PROVINCES = {"香港特别行政区", "澳门特别行政区", "台湾省"}

# 常见繁体 -> 简体地名替换（用于解析繁体信息框和分类名）
T2S_MAP = str.maketrans(
    "廣東陝遼黑龍蘇廈鄭瀋濟青長哈爾濱重慶貴蘭烏魯木齊銀東無寧溫臺灣澳門區縣華國鐵電銀證網業產總部處場際廠團訊車機醫藥險開實聯創貿遊樂體衛郵儲農設裝軟衛",
    "广东陕辽黑龙苏厦郑沈济青长哈尔滨重庆贵兰乌鲁木齐银东无宁温台湾澳门区县华国铁电银证网业产总部处场际厂团讯车机医药险开实联创贸游乐体卫邮储农设装软卫",
)

# 英文省 / 主要城市 -> (标准省名, 标准市名或 None)
EN_LOC_MAP: dict[str, tuple[str, str | None]] = {
    "beijing": ("北京市", "北京市"), "peking": ("北京市", "北京市"),
    "shanghai": ("上海市", "上海市"),
    "tianjin": ("天津市", "天津市"),
    "chongqing": ("重庆市", "重庆市"),
    "hong kong": ("香港特别行政区", None),
    "macau": ("澳门特别行政区", None), "macao": ("澳门特别行政区", None),
    "taiwan": ("台湾省", None), "taipei": ("台湾省", None), "new taipei": ("台湾省", None),
    "taichung": ("台湾省", None), "kaohsiung": ("台湾省", None), "tainan": ("台湾省", None), "hsinchu": ("台湾省", None),
    "guangdong": ("广东省", None), "shenzhen": ("广东省", "深圳市"), "guangzhou": ("广东省", "广州市"),
    "dongguan": ("广东省", "东莞市"), "foshan": ("广东省", "佛山市"), "zhuhai": ("广东省", "珠海市"),
    "zhongshan": ("广东省", "中山市"), "huizhou": ("广东省", "惠州市"), "shantou": ("广东省", "汕头市"),
    "zhejiang": ("浙江省", None), "hangzhou": ("浙江省", "杭州市"), "ningbo": ("浙江省", "宁波市"),
    "wenzhou": ("浙江省", "温州市"), "shaoxing": ("浙江省", "绍兴市"), "jiaxing": ("浙江省", "嘉兴市"),
    "jiangsu": ("江苏省", None), "nanjing": ("江苏省", "南京市"), "suzhou": ("江苏省", "苏州市"),
    "wuxi": ("江苏省", "无锡市"), "changzhou": ("江苏省", "常州市"), "nantong": ("江苏省", "南通市"),
    "xuzhou": ("江苏省", "徐州市"), "yangzhou": ("江苏省", "扬州市"),
    "shandong": ("山东省", None), "jinan": ("山东省", "济南市"), "qingdao": ("山东省", "青岛市"),
    "yantai": ("山东省", "烟台市"), "weifang": ("山东省", "潍坊市"),
    "fujian": ("福建省", None), "fuzhou": ("福建省", "福州市"), "xiamen": ("福建省", "厦门市"),
    "quanzhou": ("福建省", "泉州市"), "ningde": ("福建省", "宁德市"),
    "sichuan": ("四川省", None), "chengdu": ("四川省", "成都市"), "mianyang": ("四川省", "绵阳市"),
    "hubei": ("湖北省", None), "wuhan": ("湖北省", "武汉市"), "yichang": ("湖北省", "宜昌市"),
    "hunan": ("湖南省", None), "changsha": ("湖南省", "长沙市"), "zhuzhou": ("湖南省", "株洲市"),
    "henan": ("河南省", None), "zhengzhou": ("河南省", "郑州市"), "luoyang": ("河南省", "洛阳市"),
    "hebei": ("河北省", None), "shijiazhuang": ("河北省", "石家庄市"), "tangshan": ("河北省", "唐山市"),
    "baoding": ("河北省", "保定市"),
    "anhui": ("安徽省", None), "hefei": ("安徽省", "合肥市"), "wuhu": ("安徽省", "芜湖市"),
    "liaoning": ("辽宁省", None), "shenyang": ("辽宁省", "沈阳市"), "dalian": ("辽宁省", "大连市"),
    "jilin": ("吉林省", None), "changchun": ("吉林省", "长春市"),
    "heilongjiang": ("黑龙江省", None), "harbin": ("黑龙江省", "哈尔滨市"), "daqing": ("黑龙江省", "大庆市"),
    "shaanxi": ("陕西省", None), "xi'an": ("陕西省", "西安市"), "xian": ("陕西省", "西安市"),
    "shanxi": ("山西省", None), "taiyuan": ("山西省", "太原市"),
    "jiangxi": ("江西省", None), "nanchang": ("江西省", "南昌市"),
    "guangxi": ("广西壮族自治区", None), "nanning": ("广西壮族自治区", "南宁市"), "liuzhou": ("广西壮族自治区", "柳州市"),
    "yunnan": ("云南省", None), "kunming": ("云南省", "昆明市"),
    "guizhou": ("贵州省", None), "guiyang": ("贵州省", "贵阳市"), "zunyi": ("贵州省", "遵义市"),
    "hainan": ("海南省", None), "haikou": ("海南省", "海口市"), "sanya": ("海南省", "三亚市"),
    "gansu": ("甘肃省", None), "lanzhou": ("甘肃省", "兰州市"),
    "inner mongolia": ("内蒙古自治区", None), "hohhot": ("内蒙古自治区", "呼和浩特市"), "baotou": ("内蒙古自治区", "包头市"),
    "xinjiang": ("新疆维吾尔自治区", None), "ürümqi": ("新疆维吾尔自治区", "乌鲁木齐市"), "urumqi": ("新疆维吾尔自治区", "乌鲁木齐市"),
    "ningxia": ("宁夏回族自治区", None), "yinchuan": ("宁夏回族自治区", "银川市"),
    "qinghai": ("青海省", None), "xining": ("青海省", "西宁市"),
    "tibet": ("西藏自治区", None), "lhasa": ("西藏自治区", "拉萨市"),
}


def load_geo_index() -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """从 site/geo/*.json 加载省、地级市标准名称，返回 (省别名列表, 市别名列表)，按长度降序。"""
    china = json.loads((GEO_DIR / "china.json").read_text(encoding="utf-8"))
    prov_aliases: dict[str, str] = {}
    for feat in china["features"]:
        name = feat["properties"]["name"]
        prov_aliases[name] = name
        short = re.sub(r"(壮族|回族|维吾尔)?自治区$|特别行政区$|省$|市$", "", name)
        if len(short) >= 2:
            prov_aliases[short] = name
    # 台湾主要城市也归到台湾省
    for tw in ("台北", "新北", "台中", "高雄", "台南", "新竹", "桃园", "基隆", "彰化"):
        prov_aliases[tw] = "台湾省"

    city_aliases: dict[str, tuple[str, str]] = {}
    for m in MUNICIPALITIES:
        city_aliases[m] = (m, m)
        city_aliases[m[:-1]] = (m, m)
    for prov, code in ADCODE.items():
        p = GEO_DIR / f"{code}.json"
        if not p.exists():
            continue
        geo = json.loads(p.read_text(encoding="utf-8"))
        for feat in geo["features"]:
            cname = feat["properties"]["name"]
            city_aliases[cname] = (prov, cname)
            short = re.sub(r"(市|地区|盟|林区|自治州)$", "", cname)
            if len(short) >= 2 and short not in prov_aliases:
                city_aliases.setdefault(short, (prov, cname))

    provs = sorted(prov_aliases.items(), key=lambda x: -len(x[0]))
    cities = sorted([(k, v[0], v[1]) for k, v in city_aliases.items()], key=lambda x: -len(x[0]))
    return provs, cities


PROV_ALIASES, CITY_ALIASES = load_geo_index()
EN_LOC_KEYS = sorted(EN_LOC_MAP.keys(), key=len, reverse=True)
EN_LOC_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in EN_LOC_KEYS) + r")\b", re.I)


def match_location(text: str, allow_hmt: bool = True) -> tuple[str | None, str | None]:
    """从中文或英文文本中识别 (province, city)。"""
    if not text:
        return None, None
    s = text.translate(T2S_MAP)
    # 先匹配城市（精度更高）
    for alias, prov, city in CITY_ALIASES:
        if not allow_hmt and prov in HMT_PROVINCES:
            continue
        if alias in s:
            return prov, (None if prov in HMT_PROVINCES else city)
    # 再匹配省份
    for alias, prov in PROV_ALIASES:
        if not allow_hmt and prov in HMT_PROVINCES:
            continue
        if alias in s:
            city = prov if prov in MUNICIPALITIES else None
            return prov, city
    # 最后匹配英文地名
    for m in EN_LOC_RE.finditer(text):
        prov, city = EN_LOC_MAP[m.group(1).lower()]
        if not allow_hmt and prov in HMT_PROVINCES:
            continue
        return prov, city
    return None, None


def api_get(session: requests.Session, lang: str, params: dict) -> dict | None:
    url = f"https://{lang}.wikipedia.org/w/api.php"
    base = {"format": "json", "formatversion": "2"}
    for attempt in range(5):
        try:
            r = session.get(url, params={**base, **params}, headers={"User-Agent": USER_AGENT}, timeout=45)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "") or 0) or 3 * (attempt + 1)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [{lang}] API error: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return None


def fetch_cat_members(lang: str, cat: str, want_subcats: bool) -> list[dict]:
    session = get_session()
    members: list[dict] = []
    cont: dict = {}
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": cat,
            "cmtype": "page|subcat" if want_subcats else "page",
            "cmlimit": "500",
            **cont,
        }
        data = api_get(session, lang, params)
        if not data:
            break
        members.extend(data.get("query", {}).get("categorymembers", []))
        if "continue" not in data:
            break
        cont = data["continue"]
    return members


def crawl_categories(lang: str, seeds: list[tuple[str, int, str | None]]) -> dict[str, dict]:
    """按层并发 BFS 遍历分类树，返回 title -> {cats: set[str], hmt_hints: set[str], mainland_hint: bool}。"""
    pages: dict[str, dict] = {}
    visited_cats: set[str] = set()
    wave: list[tuple[str, int, str | None]] = []
    for cat, depth, hmt_prov in seeds:
        if cat not in visited_cats:
            visited_cats.add(cat)
            wave.append((cat, depth, hmt_prov))

    skip_cat = SKIP_CAT_ZH if lang == "zh" else SKIP_CAT_EN
    skip_title = SKIP_TITLE_ZH if lang == "zh" else SKIP_TITLE_EN

    while wave:
        next_wave: list[tuple[str, int, str | None]] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(fetch_cat_members, lang, cat, depth > 0): (cat, depth, hmt_prov)
                    for cat, depth, hmt_prov in wave}
            for fut in as_completed(futs):
                cat, depth, hmt_prov = futs[fut]
                for m in fut.result():
                    ns = m["ns"]
                    title = m["title"]
                    if ns == 14 and depth > 0:
                        if title not in visited_cats and not skip_cat.search(title):
                            visited_cats.add(title)
                            sub_hmt = hmt_prov
                            if sub_hmt is None:
                                s_norm = title.translate(T2S_MAP)
                                if "香港" in s_norm or "Hong Kong" in title:
                                    sub_hmt = "香港特别行政区"
                                elif "澳门" in s_norm or "Macau" in title or "Macao" in title:
                                    sub_hmt = "澳门特别行政区"
                                elif "台湾" in s_norm or "Taiwan" in title:
                                    sub_hmt = "台湾省"
                            next_wave.append((title, depth - 1, sub_hmt))
                    elif ns == 0:
                        if skip_title.search(title):
                            continue
                        slot = pages.setdefault(title, {"cats": set(), "hmt_hints": set(), "mainland_hint": False})
                        slot["cats"].add(cat)
                        if hmt_prov:
                            slot["hmt_hints"].add(hmt_prov)
                        else:
                            slot["mainland_hint"] = True
        print(f"  [{lang}] wave done: {len(visited_cats)} cats, {len(pages)} pages (next wave: {len(next_wave)})",
              file=sys.stderr, flush=True)
        wave = next_wave
    return pages


def fetch_batch(lang: str, titles: list[str]) -> list[dict]:
    """批量拉取 50 篇条目的导言（section 0）、跨语言链接和 wikibase_item。"""
    session = get_session()
    other = "en" if lang == "zh" else "zh"
    params = {
        "action": "query",
        "titles": "|".join(titles),
        "prop": "revisions|langlinks|pageprops",
        "rvprop": "content",
        "rvslots": "main",
        "rvsection": "0",
        "lllang": other,
        "lllimit": "50",
        "ppprop": "wikibase_item",
        "redirects": "1",
    }
    if lang == "zh":
        params["variant"] = "zh-cn"

    results: dict[str, dict] = {}
    alias: dict[str, str] = {}
    cont: dict = {}
    while True:
        data = api_get(session, lang, {**params, **cont})
        if not data:
            break
        q = data.get("query", {})
        for k in ("normalized", "converted", "redirects"):
            for x in q.get(k, []):
                alias[x["to"]] = alias.get(x["from"], x["from"])
        for p in q.get("pages", []):
            if p.get("missing"):
                continue
            t = p["title"]
            cur = results.setdefault(t, {"title": t, "orig": alias.get(t, t), "wikitext": "", "other": None, "qid": None})
            revs = p.get("revisions")
            if revs and not cur["wikitext"]:
                cur["wikitext"] = revs[0].get("slots", {}).get("main", {}).get("content", "")
            lls = p.get("langlinks")
            if lls and not cur["other"]:
                cur["other"] = lls[0].get("title")
            qid = p.get("pageprops", {}).get("wikibase_item")
            if qid:
                cur["qid"] = qid
        if "continue" not in data:
            break
        cont = data["continue"]
    return list(results.values())


def fetch_all_pages(lang: str, titles: list[str]) -> dict[str, dict]:
    """并发批量拉取全部条目导言与元数据。"""
    batches = [titles[i:i + 50] for i in range(0, len(titles), 50)]
    out: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fetch_batch, lang, b): b for b in batches}
        for fut in as_completed(futs):
            for item in fut.result():
                out[item["orig"]] = item
                out[item["title"]] = item
            done += 1
            if done % 40 == 0 or done == len(batches):
                print(f"  [{lang}] fetched {done}/{len(batches)} batches ({len(out)} entries)", file=sys.stderr)
    return out


# ---------------- Wikitext 信息框解析 ----------------

NOT_OFFICIAL = re.compile(
    r"(^|\.)(archive\.org|archive\.today|archive\.ph|weibo\.com|weibo\.cn|douban\.com|facebook\.com|twitter\.com|x\.com"
    r"|instagram\.com|youtube\.com|linkedin\.com|baike\.baidu\.com|wikipedia\.org|worlduc\.com|mp\.weixin\.qq\.com)$"
)


def clean_url(u: str) -> str | None:
    u = u.strip().strip("<>\"'")
    m = re.match(r"(https?://.+?)(?=(?<![/=])https?://|$)", u, re.I)
    if m:
        u = m.group(1)
    elif re.match(r"(www\.)?[\w-]+(\.[\w-]+)+(/|$)", u):
        u = "http://" + u
    else:
        return None
    host = urlparse(u).hostname
    return u if host and "." in host else None


def extract_infobox(wikitext: str) -> tuple[str, dict[str, str]]:
    """提取第一个信息框模板，返回 (模板名, {小写参数名: 原始值})。"""
    text = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    m = re.search(r"\{\{\s*(Infobox[^|}\n]*|[^|}\n]*信息框[^|}\n]*|[^|}\n]*資訊框[^|}\n]*|公司\s*(?:\n|\|))", text, re.I)
    if not m:
        return "", {}
    start = m.start()
    depth = 0
    i = start
    end = len(text)
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                end = i
                break
            continue
        i += 1
    block = text[start + 2:end - 2]
    # 顶层按 | 切分（忽略嵌套 {{...}} 和 [[...]] 内部的 |）
    parts: list[str] = []
    buf: list[str] = []
    b_depth = 0
    l_depth = 0
    j = 0
    while j < len(block):
        two = block[j:j + 2]
        if two == "{{":
            b_depth += 1
            buf.append(two)
            j += 2
        elif two == "}}" and b_depth > 0:
            b_depth -= 1
            buf.append(two)
            j += 2
        elif two == "[[":
            l_depth += 1
            buf.append(two)
            j += 2
        elif two == "]]" and l_depth > 0:
            l_depth -= 1
            buf.append(two)
            j += 2
        elif block[j] == "|" and b_depth == 0 and l_depth == 0:
            parts.append("".join(buf))
            buf = []
            j += 1
        else:
            buf.append(block[j])
            j += 1
    if buf:
        parts.append("".join(buf))

    tmpl_name = parts[0].strip() if parts else ""
    params: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            key = k.strip().lower()
            val = v.strip()
            if key and val:
                params[key] = val
    return tmpl_name, params


def strip_wikitext(val: str) -> str:
    """将 wikitext 片段清洗为可读纯文本。"""
    s = re.sub(r"<ref[^>/]*/>|<ref.*?</ref>", "", val, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    # 展开简单列表模板：{{ubl|a|b}} / {{hlist|a|b}} / {{plainlist|...}} / {{flatlist|...}} / {{Start date|1987|...}}
    s = re.sub(r"\{\{\s*(?:ubl|unbulleted list|hlist|flatlist|plainlist|collapsible list)\s*\|([^{}]+)\}\}", r"\1", s, flags=re.I)
    s = re.sub(r"\{\{\s*(?:flag|flagicon|flagcountry|CHN|PRC|HKG|MAC|TWN|ROC)(?:\|[^}]*)?\}\}", "", s, flags=re.I)
    s = re.sub(r"\{\{\s*(?:start date|end date|start date and age|founded)[^|}]*\|(\d{4})[^}]*\}\}", r"\1", s, flags=re.I)
    s = re.sub(r"\{\{\s*lang(?:-[a-z-]+)?\s*\|(?:[^|{}]+\|)?([^{}]+)\}\}", r"\1", s, flags=re.I)
    s = re.sub(r"\{\{\s*link-[a-z-]+\s*\|([^|{}]+)(?:\|[^{}]*)?\}\}", r"\1", s, flags=re.I)
    s = re.sub(r"\{\{\s*tsl\s*\|[^|{}]+\|[^|{}]+\|([^|{}]+)(?:\|[^{}]*)?\}\}", r"\1", s, flags=re.I)
    # 去掉剩余模板
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", " ", s)
    # [[目标|显示]] -> 显示；[[目标]] -> 目标
    s = re.sub(r"\[\[(?:File|Image|文件|檔案):[^\]]+\]\]", "", s, flags=re.I)
    s = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"\s+", " ", s).strip(" /·•,;，；、|*•")
    return s


def pick_param(params: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if k in params and params[k].strip():
            return params[k]
    return None


def parse_year(val: str | None) -> int | None:
    if not val:
        return None
    m = re.search(r"\b(1[6-9]\d{2}|20[0-2]\d)\b", val)
    return int(m.group(1)) if m else None


def parse_website(params: dict[str, str], wikitext: str) -> str | None:
    candidates: list[str] = []
    for k in ("website", "homepage", "url", "网站", "網站", "网址", "網址", "官方网站", "官方網站", "官网", "官網", "主页", "主頁"):
        if k in params:
            candidates.append(params[k])
    for m in re.finditer(r"\{\{\s*(?:official website|official site|官方网站|官方網站|官网)\s*\|\s*(?:1=|url=)?([^|}]+)", wikitext, re.I):
        candidates.append(m.group(1))
    for v in candidates:
        m = (re.search(r"\{\{\s*url\s*\|\s*(?:1=)?\s*([^|}\s]+)", v, re.I)
             or re.search(r"(https?://[^\s|\]}<]+)", v, re.I)
             or re.match(r"\s*((?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/[^\s|\]}<]*)?)\s*$", v))
        if m:
            u = clean_url(m.group(1))
            if u and not NOT_OFFICIAL.search((urlparse(u).hostname or "").lower()):
                return u
    return None


def parse_industries(val: str | None) -> list[str]:
    if not val:
        return []
    raw = re.sub(r"<ref[^>/]*/>|<ref.*?</ref>", "", val, flags=re.S | re.I)
    raw = re.sub(r"<br\s*/?>|\n|\*", "|", raw, flags=re.I)
    text = strip_wikitext(raw)
    out: list[str] = []
    for part in re.split(r"[/、,，;；•|]+", text):
        p = part.strip(" ·•-–—()（）")
        if 1 <= len(p) <= 24 and not re.match(r"^\d+$", p) and p not in out:
            out.append(p)
        if len(out) >= 3:
            break
    return out


def parse_successor(val: str | None) -> str | None:
    if not val:
        return None
    s = strip_wikitext(val)
    # 取第一个实体名
    first = re.split(r"[/、,，;；]", s)[0].strip()
    return first if 1 <= len(first) <= 40 else None


def clean_title(title: str) -> str:
    return re.sub(r"\s*[（(][^）)]+[）)]$", "", title).strip()


def wiki_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='/:()')}"


def classify_type(tmpl: str, cats: set[str], title: str) -> str:
    cat_str = " ".join(cats).translate(T2S_MAP)
    t_low = tmpl.lower()
    if any(k in t_low for k in ("university", "school", "college", "大学", "学校", "学院")) or re.search(r"(大学|学院|院校|中学|小学|学校|Universities|colleges)", cat_str, re.I):
        return "教育机构"
    if "library" in t_low or re.search(r"(图书馆|Libraries)", cat_str, re.I):
        return "图书馆"
    if "hospital" in t_low or re.search(r"(医院|Hospitals)", cat_str, re.I):
        return "医院"
    if "museum" in t_low or re.search(r"(博物馆|Museums)", cat_str, re.I):
        return "博物馆"
    if "website" in t_low and "company" not in t_low and "公司" not in cat_str:
        return "网站"
    return "企业"


LISTED_CAT_RE = re.compile(r"(上市公司|股票|交易所|上交所|深交所|北交所|港交所|纳斯达克|纽交所|S股|A股|H股|listed on|Companies listed)", re.I)
DEFUNCT_CAT_RE = re.compile(r"(已结业|已結業|已解散|已倒闭|已倒閉|已消失|Defunct companies|Former companies)", re.I)


def build_record(key: str, zh_item: dict | None, en_item: dict | None, zh_meta: dict, en_meta: dict) -> dict | None:
    zh_wt = zh_item["wikitext"] if zh_item else ""
    en_wt = en_item["wikitext"] if en_item else ""
    zh_tmpl, zh_p = extract_infobox(zh_wt) if zh_wt else ("", {})
    en_tmpl, en_p = extract_infobox(en_wt) if en_wt else ("", {})

    # 如果两边都没有任何信息框且标题不在明确的公司/机构分类中，跳过明显的非机构条目（如概念/人物）
    all_cats = zh_meta.get("cats", set()) | en_meta.get("cats", set())
    if not zh_p and not en_p:
        if not any(re.search(r"(公司|企业|企業|院校|大学|大學|图书馆|圖書館|医院|醫院|博物馆|博物館|Companies of |Universities|Libraries|Hospitals|Museums)", c, re.I) for c in all_cats):
            return None

    # 排除人物信息框（误入公司分类的创始人等）
    for tmpl in (zh_tmpl, en_tmpl):
        if re.search(r"(person|biography|officeholder|人物|艺人|藝人|政治人物)", tmpl, re.I):
            return None

    zh_title = zh_item["title"] if zh_item else (en_item["other"] if en_item and en_item.get("other") else None)
    en_title = en_item["title"] if en_item else (zh_item["other"] if zh_item and zh_item.get("other") else None)

    zh_name = clean_title(zh_title) if zh_title else None
    en_name = clean_title(en_title) if en_title else None
    if not zh_name and not en_name:
        return None

    # 官网：优先中文信息框，再英文信息框
    website = parse_website(zh_p, zh_wt) or parse_website(en_p, en_wt)

    # 成立 / 结业年份
    founded = (parse_year(pick_param(zh_p, ("foundation", "founded", "成立", "成立时间", "成立時間", "创立", "創立", "建立")))
               or parse_year(pick_param(en_p, ("foundation", "founded"))))
    dissolved = (parse_year(pick_param(zh_p, ("defunct", "dissolved", "结业", "結業", "结束", "結束", "解散", "倒闭", "倒閉")))
                 or parse_year(pick_param(en_p, ("defunct", "dissolved"))))

    # 总部文本
    hq_zh_raw = pick_param(zh_p, ("hq_location", "hq_location_city", "headquarters", "location", "location_city",
                                  "总部", "總部", "总部地点", "總部地點", "总社", "總社", "所在地"))
    hq_en_raw = pick_param(en_p, ("hq_location", "hq_location_city", "headquarters", "location", "location_city"))
    hq_zh = strip_wikitext(hq_zh_raw) if hq_zh_raw else None
    hq_en = strip_wikitext(hq_en_raw) if hq_en_raw else None
    hq = (hq_zh or hq_en or "")[:80] or None

    # 港澳台判定：有明确大陆分类且无港澳台分类 -> 大陆；只有港澳台分类 -> 港澳台
    hmt_hints = zh_meta.get("hmt_hints", set()) | en_meta.get("hmt_hints", set())
    mainland_hint = zh_meta.get("mainland_hint", False) or en_meta.get("mainland_hint", False)
    is_hmt = bool(hmt_hints) and not mainland_hint

    # 省市识别：先看信息框总部，再看分类名，再兜底港澳台标记
    province = city = None
    for text in (hq_zh, hq_en):
        if text:
            p, c = match_location(text, allow_hmt=True)
            if p:
                if p in HMT_PROVINCES and not mainland_hint:
                    is_hmt = True
                if (is_hmt and p in HMT_PROVINCES) or (not is_hmt and p not in HMT_PROVINCES):
                    province, city = p, c
                    break
    if not province:
        for cat in sorted(all_cats):
            p, c = match_location(cat, allow_hmt=is_hmt)
            if p:
                province, city = p, c
                break
    if is_hmt and not province and hmt_hints:
        province = sorted(hmt_hints)[0]
    if is_hmt:
        city = None

    # 行业
    ind_raw = pick_param(zh_p, ("industry", "产业", "產業", "行业", "行業")) or pick_param(en_p, ("industry",))
    industry = parse_industries(ind_raw)

    # 上市
    traded = (pick_param(zh_p, ("traded_as", "股票代号", "股票代碼", "股票代码", "上市"))
              or pick_param(en_p, ("traded_as",)))
    listed = bool(traded and strip_wikitext(traded)) or any(LISTED_CAT_RE.search(c) for c in all_cats)

    # 后继 / 并入
    succ_raw = (pick_param(zh_p, ("successor", "后继", "後繼", "后续", "後續", "fate", "命运", "命運"))
                or pick_param(en_p, ("successor",)))
    succ_name = parse_successor(succ_raw) if succ_raw else None
    is_defunct_cat = any(DEFUNCT_CAT_RE.search(c) for c in all_cats)
    if dissolved is None and not succ_name and is_defunct_cat:
        # 明确在已结业分类里但未解析出年份时，不捏造年份，保持 null
        pass

    rec: dict = {
        "id": key,
        "type": classify_type(zh_tmpl or en_tmpl, all_cats, zh_name or en_name or ""),
        "zh": zh_name,
        "en": en_name if (en_name or zh_name) else key,
        "zhwiki": wiki_url("zh", zh_title) if zh_title else None,
        "enwiki": wiki_url("en", en_title) if en_title else None,
        "website": website,
        "hq": hq,
        "province": province,
        "city": city,
        "industry": industry,
        "founded": founded,
        "dissolved": dissolved,
        "listed": listed,
    }
    if succ_name:
        kind = "merged" if (succ_raw and re.search(r"(并入|併入|合并|合併|收购|收購|merg|acquir)", succ_raw, re.I)) else "replaced"
        rec["successor"] = {"id": succ_name, "name": succ_name, "kind": kind, "here": False}
    if is_hmt:
        rec["hmt"] = True
    return rec


def main() -> int:
    t0 = time.time()
    print("Crawling Wikipedia company categories…", file=sys.stderr)
    zh_seeds = [(c, d, h) for lang, c, d, h in SEEDS if lang == "zh"]
    en_seeds = [(c, d, h) for lang, c, d, h in SEEDS if lang == "en"]
    zh_pages = crawl_categories("zh", zh_seeds)
    en_pages = crawl_categories("en", en_seeds)

    print("Fetching zhwiki lead sections…", file=sys.stderr)
    zh_data = fetch_all_pages("zh", sorted(zh_pages))
    print("Fetching enwiki lead sections…", file=sys.stderr)
    en_data = fetch_all_pages("en", sorted(en_pages))

    # 按 wikibase_item（若存在）或跨语言链接合并中英文条目
    groups: dict[str, dict] = {}
    en_to_key: dict[str, str] = {}

    for orig, meta in zh_pages.items():
        item = zh_data.get(orig)
        if not item:
            continue
        key = item["qid"] or f"zh:{item['title']}"
        g = groups.setdefault(key, {"zh": None, "en": None, "zh_meta": {"cats": set(), "hmt_hints": set(), "mainland_hint": False},
                                    "en_meta": {"cats": set(), "hmt_hints": set(), "mainland_hint": False}})
        g["zh"] = item
        g["zh_meta"]["cats"] |= meta["cats"]
        g["zh_meta"]["hmt_hints"] |= meta["hmt_hints"]
        g["zh_meta"]["mainland_hint"] = g["zh_meta"]["mainland_hint"] or meta["mainland_hint"]
        if item.get("other"):
            en_to_key[item["other"]] = key

    for orig, meta in en_pages.items():
        item = en_data.get(orig)
        if not item:
            continue
        key = item["qid"] or en_to_key.get(item["title"]) or en_to_key.get(orig) or f"en:{item['title']}"
        g = groups.setdefault(key, {"zh": None, "en": None, "zh_meta": {"cats": set(), "hmt_hints": set(), "mainland_hint": False},
                                    "en_meta": {"cats": set(), "hmt_hints": set(), "mainland_hint": False}})
        g["en"] = item
        g["en_meta"]["cats"] |= meta["cats"]
        g["en_meta"]["hmt_hints"] |= meta["hmt_hints"]
        g["en_meta"]["mainland_hint"] = g["en_meta"]["mainland_hint"] or meta["mainland_hint"]

    companies: list[dict] = []
    for key, g in groups.items():
        rec = build_record(key, g["zh"], g["en"], g["zh_meta"], g["en_meta"])
        if rec:
            companies.append(rec)

    companies.sort(key=lambda x: (x["zh"] or x["en"] or x["id"], x["id"]))
    names = {x["zh"] for x in companies if x["zh"]} | {x["en"] for x in companies if x["en"]}
    for x in companies:
        if "successor" in x:
            x["successor"]["here"] = x["successor"]["name"] in names

    stats = {
        "total": len(companies),
        "mainland": sum(1 for x in companies if not x.get("hmt")),
        "hmt": sum(1 for x in companies if x.get("hmt")),
        "zhwiki": sum(1 for x in companies if x["zhwiki"]),
        "enwiki": sum(1 for x in companies if x["enwiki"]),
        "website": sum(1 for x in companies if x["website"]),
        "province": sum(1 for x in companies if x["province"]),
        "city": sum(1 for x in companies if x["city"]),
        "listed": sum(1 for x in companies if x["listed"]),
        "dissolved": sum(1 for x in companies if x["dissolved"] is not None),
    }
    print("Stats: " + ", ".join(f"{k}={v}" for k, v in stats.items()), file=sys.stderr)

    if stats["mainland"] < MIN_COUNT:
        print(f"Only {stats['mainland']} mainland companies (< {MIN_COUNT}); keeping existing {OUT_PATH.name}", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "wikipedia",
        "count": len(companies),
        "companies": companies,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT_PATH} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
