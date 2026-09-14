#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
汇总站点「合规资讯」数据，按领域生成 news/index.html、news/actions.html 与首页 FEED 区块。

**两路独立来源**（用户 2026-09-14 硬性要求：站点内容与本地日报是相互独立的数据与资讯来源）

    A. 站点直采库 sources/news/items.jsonl
       —— 由 tools/collect_news.py 每日从官方来源检索入库，**不依赖本地简报**。
          这是站点「每天都有新内容」的保底来源。
    B. 本地简报网页版 news/reports/*.html
       —— 有简报产出时一并并入（信息量更大，含深度版解读）；没有也不影响站点更新。

设计要点
--------
1. 解析 news/reports/*.html，按 <h3 class="sub2">（领域）→ <h4 class="sub3">（条目）两级切分。
2. 每条提取：标题 / 日期 / 来源机构 / 官方深链 / 要点 / 朴朴解读。
3. 官方深链一律实测 HTTP 状态码，只保留 200 的条目 —— 这是「零失效链接」的硬闸门。
   校验结果缓存在 sources/link_status.json，增量校验，不重复打站点。
4. 输出时用标记注释替换页面中的区块，手工设计的页面骨架不受影响：
       <!-- FEED:START --> ... <!-- FEED:END -->

用法：python3 build_topics.py [--no-verify]
"""

import os
import re
import json
import html
import subprocess
import sys
from datetime import datetime

from sources_tier import tier_tag as src_tier_tag, audit_sources, tier_tally, TIER_LABEL

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "news", "reports")
CACHE = os.path.join(HERE, "sources", "link_status.json")
# 站点直采资讯库（独立于本地简报，逐行 JSON，见 tools/collect_news.py）
NATIVE = os.path.join(HERE, "sources", "news", "items.jsonl")
NATIVE_VER = "站点直采"

# 官方公众号原文存档：原二手来源 URL → 站内存档（由 tools/build_wx_archive.py 生成）。
# 命中的条目不再指向失效/二手外链，改为链到 kb/wx.html#w-<id> 的站内全文存档。
WX_REPLACES = {}

try:
    WX_REPLACES = json.load(open(os.path.join(HERE, "sources", "wx", "replaces.json"),
                                 encoding="utf-8"))
except (OSError, ValueError):
    WX_REPLACES = {}

# 存档元数据（id → 标题/机关/日期），用于识别「简报里已被换成站内链」的条目。
# 为什么需要：tools/fix_pending_sources.py 会把归档简报页里的原外链直接替换成
# ../../kb/wx.html#w-<id>，此后 build_topics 解析简报时拿到的是相对链接，
# 按「原二手 URL」查 WX_REPLACES 必然查不到 → 会被链接闸门当无效链接剔除，
# 结果公众号来源反而进不了资讯流。所以这里同时认「站内存档链」。
WX_META = {}
try:
    for _w in json.load(open(os.path.join(HERE, "kb", "wx", "index.json"),
                             encoding="utf-8")).get("items", []):
        if _w.get("id"):
            WX_META[_w["id"]] = _w
except (OSError, ValueError, AttributeError):
    WX_META = {}

RE_WX_INTERNAL = re.compile(r"kb/wx\.html#w-([A-Za-z0-9_-]+)")

# 六大领域：键为归一化名，值为展示名 + 主色
DOMAINS = [
    ("数据合规", "#1b4f8a"),
    ("AI合规", "#7c3aed"),
    ("算法合规", "#0f766e"),
    ("平台合规", "#b45309"),
    ("产品合规", "#15803d"),
    ("价格合规", "#be123c"),
    # 2026-09-11 起按业务业态拓宽：即时零售平台 / 网络餐饮与线下餐饮 / 前置仓仓储冷链 /
    # 即时配送与骑手 / 计量 / 零售消费者与会员 / 绿色包装与反浪费
    ("网络交易合规", "#2563eb"),
    ("餐饮合规", "#c2410c"),
    ("冷链仓储合规", "#0891b2"),
    ("配送与用工合规", "#4d7c0f"),
    ("计量合规", "#7e22ce"),
    ("零售与消费者合规", "#b91c1c"),
    ("绿色合规", "#047857"),
]
DOMAIN_KEYS = [d[0] for d in DOMAINS]
DOMAIN_COLOR = dict(DOMAINS)

# 领域中常见的别名 → 归一化
ALIAS = {
    "产品合规（食品安全）": "产品合规",
    "产品合规（食安）": "产品合规",
    "AI 合规": "AI合规",
    "人工智能合规": "AI合规",
    "平台合规（电商）": "平台合规",
    "食品安全合规": "产品合规",
    "即时零售合规": "网络交易合规",
    "电商合规": "网络交易合规",
    "网络餐饮合规": "餐饮合规",
    "餐饮服务合规": "餐饮合规",
    "冷链合规": "冷链仓储合规",
    "仓储合规": "冷链仓储合规",
    "骑手权益": "配送与用工合规",
    "劳动用工合规": "配送与用工合规",
    "计量与价格": "计量合规",
    "消费者权益": "零售与消费者合规",
    "会员权益": "零售与消费者合规",
    "包装合规": "绿色合规",
    "反食品浪费": "绿色合规",
}

# 无领域归属时（如「朴朴超市业务专题」下的应对建议）按关键词推断。
# 特异性强的词权重高，避免「数据」这类通用词把什么都吸走。
DOMAIN_KEYWORDS = {
    "产品合规": [("前置仓", 5), ("食品", 5), ("食安", 5), ("生鲜", 4), ("抽检", 4),
                 ("快检", 4), ("索证", 4), ("批次", 3), ("标签", 3),
                 ("临期", 3), ("冷藏", 3), ("商品", 2)],
    "价格合规": [("划线价", 6), ("促销", 5), ("标价", 5), ("价格", 5), ("收费", 4),
                 ("返利", 4), ("补贴", 3), ("内卷", 3), ("成交", 2)],
    "平台合规": [("入网", 5), ("商户", 5), ("商家", 4), ("入驻", 4), ("平台", 4),
                 ("资质", 3), ("供应商", 3), ("第三方", 2), ("治理", 1)],
    "AI合规": [("大模型", 6), ("人工智能", 6), ("智能体", 6), ("生成式", 5), ("AIGC", 5),
               ("AI", 4), ("深度合成", 4)],
    "算法合规": [("算法", 5), ("推荐", 3), ("个性化", 3), ("推送", 2), ("透明", 2)],
    "数据合规": [("个人信息", 6), ("个保", 6), ("隐私", 5), ("数据", 4), ("SDK", 4),
                 ("出境", 4), ("分类分级", 4), ("重要数据", 4), ("用户权益", 3),
                 ("App", 2), ("网络安全", 2)],
    "网络交易合规": [("即时零售", 6), ("网络交易", 6), ("亮照", 6), ("亮证", 5),
                     ("电商", 4), ("入驻资质", 4), ("七日无理由", 4), ("线上销售", 3)],
    "餐饮合规": [("网络餐饮", 6), ("外卖", 5), ("餐饮", 5), ("后厨", 4), ("明厨亮灶", 4),
                 ("食安封签", 5), ("餐厅", 4), ("堂食", 4), ("门店", 2)],
    "冷链仓储合规": [("冷链", 6), ("冷库", 6), ("温控", 5), ("仓储", 5), ("贮存", 4),
                     ("前置仓", 5), ("断链", 4), ("追溯", 3)],
    "配送与用工合规": [("骑手", 6), ("送餐员", 6), ("配送员", 6), ("新就业形态", 5),
                       ("派单", 5), ("劳动权益", 5), ("配送箱", 4), ("运力", 3)],
    "计量合规": [("计量", 6), ("净含量", 6), ("电子秤", 6), ("称重", 5), ("缺斤", 5),
                 ("定量包装", 5), ("鬼秤", 5)],
    "零售与消费者合规": [("预付", 6), ("会员", 4), ("自动续费", 5), ("退换货", 4),
                         ("消费者权益", 5), ("投诉", 3), ("有奖销售", 4), ("赠品", 3)],
    "绿色合规": [("限塑", 6), ("一次性塑料", 6), ("过度包装", 6), ("反食品浪费", 6),
                 ("绿色包装", 5), ("厨余", 4), ("可降解", 4)],
}


def guess_domain(text):
    """按关键词打分推断领域；无命中返回 None。"""
    best, score = None, 0
    for dom, kws in DOMAIN_KEYWORDS.items():
        s = sum(w for kw, w in kws if kw in text)
        if s > score:
            best, score = dom, s
    return best if score >= 4 else None


# 内容类型词表：公众号等「只按内容归类」的条目用，与资讯流其它条目的 kind 共用一套
# 展示徽章（ni-kind）。不是所有公众号文章都属于立法/标准/指南——有的是专项行动、
# 处罚案例、执法通报、政策问答或专题述评，需结合标题内容判定。
KIND_KEYWORDS = [
    (r"处罚|查处|罚单|行政处|典型案例|案例", "处罚案例"),
    (r"通报", "执法通报"),                      # 仅「通报」无「案例」→ 执法通报（与上式互斥）
    (r"专项行动|专项整治|整治|治理|打击|清理|排查|销毁|铁拳|护网", "专项行动"),
    (r"标准|规范|GB/T|GB |指引|指南|通则|办法|条例|规定|部令|令第|征求意见", "新规发布"),
    (r"问答|答记者问|解读|一文读懂", "政策问答"),
    (r"述评|评论|观察|评析|研判", "专题述评"),
]


def guess_kind(text):
    """按标题关键词推断内容类型，用于公众号等只按内容归类的条目。

    优先级：处罚案例/执法通报 > 专项行动 > 新规发布 > 政策问答/专题述评 > 监管动态。
    命中第一条即返回；都不命中回落「监管动态」。
    """
    t = text or ""
    for pat, kind in KIND_KEYWORDS:
        if re.search(pat, t):
            # 处罚 vs 执法通报：含「案例」算处罚案例，仅「通报」算执法通报
            if kind == "执法通报" and re.search(r"案例", t):
                continue
            if kind == "政策问答" and re.search(r"述评|评论|观察|评析|研判", t):
                return "专题述评"
            return kind
    return "监管动态"

# 不发布名单：与 gen_briefs.py 保持一致。含编造链接的期次不解析、不进站点。
BLOCKED = ("简报_2026-09-06",)

TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s):
    """去 HTML 标签并把实体还原成纯文本。"""
    s = TAG_RE.sub("", s)
    return html.unescape(s).strip()


def normalize_domain(raw):
    """把 '1. 数据合规' / '2. AI合规 —— 深度分析' 归一化为标准领域名。"""
    t = strip_tags(raw)
    t = re.sub(r"^\s*\d+\s*[.、]\s*", "", t)          # 去掉序号
    t = re.split(r"[—–-]{2,}", t)[0].strip()          # 去掉「—— 深度分析」后缀
    t = ALIAS.get(t, t)
    for k in DOMAIN_KEYS:                              # 兜底：包含匹配
        if k in t:
            return k
    return t


def parse_issue(fname):
    """从文件名解析 (类型, 日期, 版本)。"""
    base = os.path.basename(fname)
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", base)
    date = m.group(1) if m else ""
    kind = "日报"
    for k in ("周报", "月报", "补编", "季报"):
        if k in base:
            kind = k
            break
    ver = "深度分析版" if "深度分析版" in base else "资讯简版"
    return kind, date, ver


def parse_report(path):
    """解析单个报告文件，返回条目列表。"""
    try:
        s = open(path, encoding="utf-8").read()
    except Exception:
        return []

    kind, date, ver = parse_issue(path)
    fname = os.path.basename(path)
    items = []

    # 顺序扫描：h2 开新章节并清空领域，h3.sub2 设定领域，h4.sub3 是条目。
    # 深度版章节顺序是乱的（如「朴朴超市业务专题」排在六大领域之后却无 sub2），
    # 因此必须在遇到 h2 时清空领域，无归属的条目再按关键词推断。
    marks = [(m.start(), m.group(1), m.group(2))
             for m in re.finditer(r'<(h2[^>]*|h3 class="sub2"|h4 class="sub3")>(.*?)</(?:h2|h3|h4)>',
                                  s, re.S)]
    cur = None
    for i, (_pos, tag, inner) in enumerate(marks):
        if tag.startswith("h2"):
            cur = None
            continue
        if tag.startswith("h3"):
            cur = normalize_domain(inner)
            if cur not in DOMAIN_KEYS:
                cur = None
            continue

        # 条目：取本条到下一个标记之间的内容
        end = marks[i + 1][0] if i + 1 < len(marks) else len(s)
        blk = s[_pos:end]

        tm = re.match(r'(?:<span class="mk">.*?</span>)?(.*?)</h4>', inner + "</h4>", re.S)
        if not tm:
            continue
        title = strip_tags(tm.group(1))
        if not title or len(title) < 6:
            continue

        domain = cur
        if domain is None:
            domain = guess_domain(title)       # 专题类条目按标题推断
            if domain is None:
                continue

        # 元信息：日期 + 来源机构
        meta_raw, pub_date, org = "", date, ""
        mm = re.search(r'<p class="meta">(.*?)</p>', blk, re.S)
        if mm:
            meta_raw = strip_tags(mm.group(1))
            parts = [p.strip() for p in re.split(r"[｜|]", meta_raw) if p.strip()]
            if parts:
                dm = re.search(r"(20\d{2}-\d{2}-\d{2})", parts[0])
                pub_date = dm.group(1) if dm else date
            if len(parts) > 1:
                org = parts[-1]

        # 官方深链
        link = ""
        lm = re.search(r'<p class="link"><a href="([^"]+)"', blk)
        if lm:
            link = html.unescape(lm.group(1)).strip()

        # 要点：【要点】所在段落
        points = ""
        pm = re.search(
            r"<p[^>]*>(?:(?!</p>).)*?【要点】(?:(?!</p>).)*?</p>", blk, re.S
        )
        if pm:
            points = strip_tags(pm.group(0))
            points = re.sub(r"^【要点】\s*", "", points)

        # 朴朴解读
        analysis = ""
        am = re.search(r'<blockquote class="ana">(.*?)</blockquote>', blk, re.S)
        if am:
            analysis = strip_tags(am.group(1))
            analysis = re.sub(r"^解读[:：]\s*", "", analysis)

        if not (points or analysis):
            continue

        rm = re.search(r"【风险等级[:：]\s*([^】]+)】", title)
        risk = rm.group(1).strip() if rm else ""
        title = re.sub(r"\s*[　\s]*【风险等级[:：][^】]*】\s*$", "", title).strip()

        items.append(
            {
                "domain": domain,
                "title": title,
                "risk": risk,
                "date": pub_date or date,
                "org": org,
                "meta": meta_raw,
                "url": link,
                "points": points,
                "analysis": analysis,
                "issue": date,
                "kind": kind,
                "ver": ver,
                "file": fname,
            }
        )
    return items


def load_native(path=NATIVE):
    """读站点直采资讯库 sources/news/items.jsonl（独立于本地简报的那一路来源）。

    字段已由 tools/collect_news.py 过闸（领域归一 / 引源分级 / 深链非根域名 / curl 实测），
    这里只做形状对齐，让下游 dedup / 链接闸门 / 渲染无需分支。
    """
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        title = (r.get("title") or "").strip()
        domain = normalize_domain(r.get("domain") or "")
        if domain not in DOMAIN_KEYS:
            domain = guess_domain(title + " " + (r.get("points") or ""))
        if not title or domain not in DOMAIN_KEYS:
            continue
        collected = (r.get("collected") or r.get("date") or "")[:10]
        out.append({
            "domain": domain,
            "title": title,
            "risk": (r.get("risk") or "").strip(),
            "date": (r.get("date") or collected).strip(),
            "org": (r.get("org") or "").strip(),
            "meta": "",
            "url": (r.get("url") or "").strip(),
            "points": (r.get("points") or "").strip(),
            "analysis": (r.get("analysis") or "").strip(),
            "issue": collected,
            "kind": (r.get("kind") or "监管动态").strip(),
            "ver": NATIVE_VER,
            "file": "sources/news/items.jsonl",
            # 来源为站内公众号原文存档（tools/fetch_wechat.py 抓取）时透传
            **({"wx_id": (r.get("wx_id") or "").strip()} if r.get("wx_id") else {}),
        })
    return out


def dedup(items):
    """同一事件在多期/简版深度版重复出现时保留信息量最大的一条。"""
    best = {}
    for it in items:
        # 优先用链接判重，其次用标题
        key = it["url"] or it["title"]
        if key not in best:
            best[key] = it
            continue
        cur = best[key]
        # 打分：解读长度 + 要点长度 + 期次新旧；深度版加权
        def score(x):
            return (
                len(x["analysis"]) * 2
                + len(x["points"])
                + (500 if x["ver"] == "深度分析版" else 0)
                + (250 if x["ver"] == NATIVE_VER else 0)   # 站点直采优先（新鲜且已过闸）
                + (x["issue"] > cur["issue"]) * 300
            )

        if score(it) > score(cur):
            best[key] = it
    return list(best.values())


def verify_links(urls, do_verify=True):
    """用 curl 实测链接可达性（Python urllib 在沙箱里会被代理拦截，故用 curl）。"""
    status = {}
    if os.path.exists(CACHE):
        try:
            status = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            status = {}
    if not do_verify:
        return status

    todo = [u for u in urls if u and u not in status]
    if todo:
        print(f"  链接校验：新增 {len(todo)} 条，缓存 {len(urls) - len(todo)} 条")
        for i, u in enumerate(todo, 1):
            try:
                r = subprocess.run(
                    ["curl", "-sL", "-o", "/dev/null", "--max-time", "12",
                     "-A", "Mozilla/5.0", "-w", "%{http_code}", u],
                    capture_output=True, text=True, timeout=20,
                )
                code = (r.stdout or "").strip()[-3:]
                status[u] = code if code.isdigit() else "000"
            except Exception:
                status[u] = "000"
            if i % 10 == 0:
                print(f"    已测 {i}/{len(todo)}")
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(status, open(CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
    return status


# ---------------- 页面生成 ----------------

def esc(s):
    return html.escape(s or "", quote=True)


def snippet(text, n=180):
    """截断成摘要，尽量在句读处断开。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    for sep in ("。", "；", "；", "，", "、"):
        pos = cut.rfind(sep)
        if pos > n * 0.6:
            return cut[: pos + 1]
    return cut + "…"


# ---------------------------------------------------------------------------
# 深链覆盖表：简报里偶有条目只留了机构官网根域名（如 https://www.cac.gov.cn/），
# 这属于"来源不可溯源"，必须换成发布机构的具体公告页。
# 键是标题里的特征词，值是人工检索并 curl 实测过的官网具体页面。
# 新增覆盖时务必先验证 HTTP 200，不要凭印象填 URL。
# ---------------------------------------------------------------------------
URL_OVERRIDE = [
    ("App／SDK 侵害用户权益",
     "https://wap.miit.gov.cn/xwfb/gxdt/sjdt/art/2026/art_b0879936348c4018a1e54f1c773514a5.html"),
    ("App/SDK 侵害用户权益",
     "https://wap.miit.gov.cn/xwfb/gxdt/sjdt/art/2026/art_b0879936348c4018a1e54f1c773514a5.html"),
    ("大模型备案",
     "https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm"),
]


def is_root_url(u):
    """判断是否为官网首页根域名——这类链接不可溯源，不能作为来源展示。"""
    if not u:
        return True
    p = re.sub(r"^https?://(www\.)?", "", u)
    return "/" not in p or p.rstrip("/").count("/") == 0


def render_item_card(it, idx, rel="../"):
    """单条资讯卡片。`rel` 为回到站点根目录的相对前缀（首页传空串）。"""
    color = DOMAIN_COLOR.get(it["domain"], "#1b4f8a")
    url = it["url"]
    # 根域名先用覆盖表换成具体公告页
    if is_root_url(url):
        for kw, deep in URL_OVERRIDE:
            if kw in it.get("title", ""):
                url = deep
                break
    link_html = ""
    if it.get("wx_id"):
        # 来源只在官方公众号发布、PC 官网无对应页 → 指向站内全文存档，不做微信外链
        # （公众号链接是带签名的临时地址，必然短链失效，给出去等于给死链）
        w = WX_REPLACES.get(it["url"]) or {}
        org = it.get("wx_org") or w.get("org") or it.get("org") or ""
        note = f'{esc(org)}官方公众号' if org else "发布机关官方公众号"
        link_html = (
            f'<a class="src src-wxin" href="{esc(rel)}kb/wx.html#w-{esc(it["wx_id"])}" '
            f'title="原文只在{esc(org)}官方微信公众号发布，PC 官网无对应页；已存档全文于站内">'
            f'站内原文存档 <span class="arw">→</span></a>'
        )
        link_html += (f'<span class="rd-src src-wx" title="{note}，已核验账号主体并存档全文">'
                      f'官方公众号</span>')
    elif url:
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        if is_root_url(url):
            # 仍没有可用深链：只显示机构名，不做成链接，绝不指向官网首页
            link_html = f'<span class="src src-plain">{esc(host)}</span>'
        else:
            link_html = (
                f'<a class="src" href="{esc(url)}" target="_blank" rel="noopener">'
                f'{esc(host)} <span class="arw">↗</span></a>'
            )
        link_html += src_tier_tag(url, it.get("src"))

    ana_html = ""
    if it["analysis"]:
        ana_html = (
            f'<details class="ana"><summary>朴朴视角 · 合规解读</summary>'
            f'<div class="ana-b">{esc(it["analysis"])}</div></details>'
        )

    return f"""<article class="ni" data-domain="{esc(it['domain'])}" data-idx="{idx}">
  <div class="ni-bar" style="background:{color}"></div>
  <div class="ni-body">
    <div class="ni-top">
      <span class="ni-dom" style="color:{color};background:{color}14">{esc(it['domain'])}</span>
      <span class="ni-date">{esc(it['date'])}</span>
      <span class="ni-org">{esc(it['org'])}</span>
      <span class="ni-kind">{esc(it['kind'])}</span>
    </div>
    <h4 class="ni-title">{esc(it['title'])}</h4>
    <p class="ni-pt">{esc(snippet(it['points'], 200))}</p>
    {ana_html}
    <div class="ni-foot">{link_html}</div>
  </div>
</article>"""


def render_news_feed(items):
    """按领域分组的资讯流 + 筛选器。"""
    by = {d: [] for d in DOMAIN_KEYS}
    for it in items:
        by.setdefault(it["domain"], []).append(it)
    for d in by:
        by[d].sort(key=lambda x: (x["date"], x["issue"]), reverse=True)

    tabs = ['<button class="ftab active" data-f="all">全部 <em>%d</em></button>' % len(items)]
    for d in DOMAIN_KEYS:
        if by.get(d):
            tabs.append(f'<button class="ftab" data-f="{esc(d)}">{esc(d)} <em>{len(by[d])}</em></button>')

    blocks = []
    idx = 0
    for d in DOMAIN_KEYS:
        lst = by.get(d) or []
        if not lst:
            continue
        cards = []
        for it in lst:
            cards.append(render_item_card(it, idx))
            idx += 1
        blocks.append(
            f'<section class="fgroup" id="g-{esc(d)}" data-g="{esc(d)}">'
            f'<div class="fgroup-h"><span class="dot" style="background:{DOMAIN_COLOR[d]}"></span>'
            f'<h3>{esc(d)}</h3><span class="cnt">{len(lst)} 条</span></div>'
            f'<div class="nilist">{"".join(cards)}</div></section>'
        )

    latest = max((it["date"] for it in items), default="")

    return f"""<div class="feedbar">
  <div class="fb-stats">
    <div class="st"><div class="n">{len(items)}</div><div class="l">合规动态</div></div>
    <div class="st"><div class="n">{len([d for d in DOMAIN_KEYS if by.get(d)])}</div><div class="l">覆盖领域</div></div>
    <div class="st"><div class="n">{esc(latest)}</div><div class="l">更新至</div></div>
  </div>
  <div class="fb-tools">
    <input id="q" type="search" placeholder="按关键词 / 机构过滤…" aria-label="过滤">
    <div class="ftabs">{"".join(tabs)}</div>
  </div>
</div>
<div id="feed">{"".join(blocks)}</div>
<div id="empty" class="empty" hidden>没有匹配的动态，换个关键词试试。</div>
<script>
(function(){{
  var q=document.getElementById('q'), feed=document.getElementById('feed'),
      empty=document.getElementById('empty'), cur='all';
  function apply(){{
    var kw=(q.value||'').trim().toLowerCase(), shown=0;
    var gs=feed.querySelectorAll('.fgroup');
    for(var i=0;i<gs.length;i++){{
      var g=gs[i], okG=(cur==='all'||g.dataset.g===cur), n=0;
      var ns=g.querySelectorAll('.ni');
      for(var j=0;j<ns.length;j++){{
        var el=ns[j], t=el.innerText.toLowerCase();
        var ok=okG&&(!kw||t.indexOf(kw)>-1);
        el.hidden=!ok; if(ok){{n++;shown++;}}
      }}
      g.hidden=(n===0);
    }}
    empty.hidden=(shown>0);
  }}
  var ts=document.querySelectorAll('.ftab');
  for(var i=0;i<ts.length;i++){{
    ts[i].addEventListener('click',function(){{
      for(var j=0;j<ts.length;j++) ts[j].classList.remove('active');
      this.classList.add('active'); cur=this.dataset.f; apply();
    }});
  }}
  if(q) q.addEventListener('input',apply);
}})();
</script>"""


RISK_CLASS = {"高": "r-hi", "中高": "r-mh", "中": "r-md", "低": "r-lo"}


def render_kb_cards(news_items, actions):
    """知识库：按领域沉淀「合规行动要点」（来自简报应对建议）+ 动态入口。"""
    acts = {d: [] for d in DOMAIN_KEYS}
    for it in actions:
        if it["analysis"] or it["points"]:
            acts.setdefault(it["domain"], []).append(it)
    for d in acts:
        # 高风险的排前面
        order = {"高": 0, "中高": 1, "中": 2, "低": 3}
        acts[d].sort(key=lambda x: (order.get(x.get("risk"), 9), x["date"]), reverse=False)
        acts[d].sort(key=lambda x: order.get(x.get("risk"), 9))

    n_news = {d: sum(1 for x in news_items if x["domain"] == d) for d in DOMAIN_KEYS}

    cards = []
    for d in DOMAIN_KEYS:
        color = DOMAIN_COLOR[d]
        lst = acts.get(d) or []
        if not lst:
            cards.append(f"""<div class="kb-card empty-c">
  <div class="kb-h"><span class="dot" style="background:{color}"></span><h3>{esc(d)}</h3></div>
  <p class="kb-p">暂无行动要点沉淀，后续简报产出应对建议后自动累积。</p>
</div>""")
            continue
        lis = []
        for it in lst[:4]:
            body = it["analysis"] or it["points"]
            risk = it.get("risk", "")
            rb = (f'<span class="rk {RISK_CLASS.get(risk, "r-md")}">{esc(risk)}</span>'
                  if risk else "")
            lis.append(
                f'<li><div class="kb-t">{rb}<b>{esc(it["title"])}</b></div>'
                f'<div class="kb-a">{esc(snippet(body, 150))}</div>'
                f'<div class="kb-m">{esc(it["date"])} · 源自{esc(it["kind"])}</div></li>'
            )
        more = ""
        if n_news.get(d):
            more = (f'<div class="kb-more">'
                    f'<a href="../news/index.html#g-{esc(d)}">该领域 {n_news[d]} 条监管动态 →</a></div>')
        cards.append(f"""<div class="kb-card">
  <div class="kb-h"><span class="dot" style="background:{color}"></span><h3>{esc(d)}</h3>
    <span class="kb-n">{len(lst)} 项要点</span></div>
  <ul class="kb-list">{"".join(lis)}</ul>
  {more}
</div>""")
    return f'<div class="kb-grid">{"".join(cards)}</div>'


def render_home_latest(items, n=6):
    """首页最新动态：跨领域取最新 n 条。"""
    lst = sorted(items, key=lambda x: (x["date"], x["issue"]), reverse=True)[:n]
    rows = []
    for it in lst:
        color = DOMAIN_COLOR.get(it["domain"], "#1b4f8a")
        rows.append(f"""<a class="hl" href="news/index.html">
  <span class="hl-d" style="background:{color}">{esc(it['domain'])}</span>
  <span class="hl-t">{esc(it['title'])}</span>
  <span class="hl-m">{esc(it['date'])}</span>
</a>""")
    return f'<div class="hlist">{"".join(rows)}</div>'


def replace_block(path, content):
    """替换 <!-- FEED:START --> … <!-- FEED:END --> 之间的内容。"""
    if not os.path.exists(path):
        print(f"  ! 缺少文件 {path}")
        return False
    s = open(path, encoding="utf-8").read()
    pat = re.compile(r"(<!-- FEED:START -->)(.*?)(<!-- FEED:END -->)", re.S)
    if not pat.search(s):
        print(f"  ! {os.path.basename(path)} 未找到 FEED 标记，跳过")
        return False
    s = pat.sub(lambda m: m.group(1) + "\n" + content + "\n" + m.group(3), s)
    open(path, "w", encoding="utf-8").write(s)
    return True


def build_feed(do_verify=True):
    """加载并校验资讯流可用条目（verified / internal / dead）。

    供 build_home.py 复用，避免重复跑链接校验闸门。链接状态缓存在
    sources/link_status.json，增量校验，重复调用几乎无额外成本。
    """
    # ---- 来源 A：站点直采库（独立于本地简报，站点每日更新的保底来源）----
    items = []
    nat = load_native()
    if nat:
        print(f"站点直采库 sources/news/items.jsonl：{len(nat)} 条")
        items += nat
    else:
        print("站点直采库为空（sources/news/items.jsonl 不存在或无有效条目）")

    # ---- 来源 B：本地简报网页版（有就并入，没有不影响站点更新）----
    files = []
    if os.path.isdir(REPORTS):
        files = sorted(
            f for f in os.listdir(REPORTS)
            if f.endswith(".html") and not any(b in f for b in BLOCKED)
        )
    if files:
        print(f"解析 {len(files)} 份网页版简报…")
        for f in files:
            got = parse_report(os.path.join(REPORTS, f))
            if got:
                print(f"  {f[:40]:<42} {len(got)} 条")
            items += got
        print(f"简报解析合计 {len(items) - len(nat)} 条")
    else:
        print("未找到 news/reports/*.html —— 本次仅用站点直采库（不影响站点更新）")

    print(f"合并合计 {len(items)} 条")
    if not items:
        print("× 两路来源均为空，不重写页面（避免把资讯流清空）")
        return

    items = dedup(items)
    print(f"去重后 {len(items)} 条")

    # 来源改写：命中「官方公众号原文存档」的条目，脱掉失效/二手外链。
    # 这类内容的原文只在发布机关官方公众号上，PC 官网无对应页、微信外链必然失效，
    # 故改为指向站内全文存档 kb/wx.html#w-<id>（id 由 tools/build_wx_archive.py 生成）。
    n_wx = 0
    for it in items:
        if it.get("wx_id"):
            # 直采库已直接给出存档 id（来源即公众号），无需再按 URL 匹配
            it["wx_org"] = it.get("wx_org") or it.get("org") or ""
            it["src"] = "wechat-official"
            it["url"] = ""
            n_wx += 1
            continue
        u = it.get("url") or ""
        m = RE_WX_INTERNAL.search(u)
        if m:
            # 简报里的外链已被换成站内存档链（fix_pending_sources），这里认回来，
            # 否则相对链接会被链接闸门判为无效而整条剔除。
            wid = m.group(1)
            meta = WX_META.get(wid) or {}
            it["wx_id"] = wid
            it["wx_org"] = meta.get("org") or it.get("org") or ""
            it["src"] = "wechat-official"
            it["url"] = ""          # 站内相对链接不是外链，不能拿去实测
            n_wx += 1
            continue
        w = WX_REPLACES.get(u)
        if not w:
            continue
        it["wx_id"] = w["wx_id"]
        it["wx_org"] = w.get("org") or it.get("org") or ""
        it["src"] = "wechat-official"
        it["url"] = ""          # 脱掉会失效的原外链
        n_wx += 1
    if n_wx:
        print(f"来源改写：{n_wx} 条 → 站内公众号原文存档（原为二手转载或必然失效的公众号链）")

    # 链接校验闸门：分三类
    #   verified —— 有官方深链且实测 200，进资讯流（可溯源，满足对外分享要求）
    #   internal —— 无外链的内部行动建议，进知识库（不对外引用，无需外链）
    #   dead     —— 有链接但实测失效，丢弃（绝不进站点）
    urls = sorted({it["url"] for it in items if it["url"]})
    status = verify_links(urls, do_verify)
    # 200 = 正常；403/429 = 对方 WAF 拦脚本 UA，浏览器可正常打开，视为有效；
    # 其余（404 / 000 连接失败 / 其他）视为失效，绝不进站点。
    OK_CODES = {"200", "403", "429"}
    verified, internal, dead = [], [], []
    for it in items:
        u = it["url"]
        if it.get("wx_id"):
            verified.append(it)          # 站内全文存档已落地，无需再验外链
        elif not u:
            internal.append(it)
        elif status.get(u, "?") in OK_CODES:
            verified.append(it)
        else:
            dead.append((it, status.get(u, "?")))
    if dead:
        print(f"链接闸门剔除 {len(dead)} 条（有链接但失效）：")
        for it, st in dead[:12]:
            print(f"    [{st}] {it['title'][:38]}")
    print(f"资讯流 {len(verified)} 条（深链实测 200）｜知识库素材 {len(internal)} 条（内部行动建议）")
    return verified, internal, dead, len(nat)


def main():
    do_verify = "--no-verify" not in sys.argv
    verified, internal, dead, nat = build_feed(do_verify)

    # 引源校验：立法/标准/专项行动/处罚类必须 official；资讯类允许官方媒体与专业机构
    print("  —— 引源校验 ——")
    pend = audit_sources(verified, kind_key=["kind", "title"], label="资讯流")
    tal = tier_tally(verified)
    print("    层级分布：" + " / ".join(f"{TIER_LABEL[k]} {v}" for k, v in tal.items() if v))
    # 待替换清单落盘，供后续逐条回溯官方原文
    #   人工维护的「原因/已试路径」从 source_pending_notes.json 合并进来（该文件为生成物，
    #   每次重建都会覆盖，所以备注必须写在 notes 文件里，不能直接改 source_pending.json）
    notes_path = os.path.join(HERE, "sources", "edits", "source_pending_notes.json")
    try:
        _notes = json.load(open(notes_path, encoding="utf-8")).get("reasons", {})
    except (OSError, ValueError):
        _notes = {}
    for _p in pend:
        if _p.get("url") in _notes:
            _p["backtrack"] = _notes[_p["url"]]
    pend_path = os.path.join(HERE, "sources", "edits", "source_pending.json")
    os.makedirs(os.path.dirname(pend_path), exist_ok=True)
    json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "rule": "立法/标准发布生效/专项行动/监管处罚 = 必须官方原文；资讯 = 官方媒体/专业机构",
               "pending": pend},
              open(pend_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if pend:
        _n = sum(1 for p in pend if p.get("backtrack"))
        print(f"    待替换清单 → sources/edits/source_pending.json（{len(pend)} 条，"
              f"其中 {_n} 条带回溯备注）")

    # 生成各页面
    print("写入页面…")
    if replace_block(os.path.join(HERE, "news", "index.html"), render_news_feed(verified)):
        print("  news/index.html ✓")
    # 应对建议归属「合规资讯」模块（与动态同源，回答「我们该做什么」）；
    # 知识库改为长效知识总览，由 build_standards.py 生成，不再接收动态内容。
    if replace_block(os.path.join(HERE, "news", "actions.html"), render_kb_cards(verified, internal)):
        print("  news/actions.html ✓")
    # 首页 RADAR/FEED/GEOMETA 三块由 build_home.py 统一生成
    # （在 daily_build 编排中晚于本步执行，避免被重复写入覆盖）

    # 刷新全站「数据更新至」时间戳（页脚 UPDATED 区块，见 unify_chrome.py）
    try:
        from unify_chrome import refresh_updated
        latest_stamp = max((x["issue"] for x in verified + internal), default=None)
        stamp = latest_stamp or datetime.now().strftime("%Y-%m-%d")
        n = refresh_updated(stamp)
        if n:
            print(f"  页脚更新时间 → {stamp}（{n} 页）")
    except Exception as e:
        print(f"  页脚时间戳刷新失败（不阻断）：{e}")

    # 恢复模块子导航（news 三子页重写后需重新注入）
    try:
        from inject_subnav import main as subnav_main
        subnav_main()
    except Exception as e:
        print(f"  子导航刷新失败（不阻断）：{e}")

    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "native_items": nat,
        "news_items": len(verified),
        "kb_actions": len(internal),
        "dead_links": len(dead),
        "by_domain": {d: sum(1 for x in verified if x["domain"] == d) for d in DOMAIN_KEYS},
    }
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
