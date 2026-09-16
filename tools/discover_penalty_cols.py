#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discover_penalty_cols.py —— 批量探测「行政处罚公示」栏目页（通用，不限市监）

为什么要有它
------------
`harvest_local_amr.py` 的 SITES 是**手工维护**的：每加一个站都要先知道「列表页在哪、
怎么翻页」。全国 31 省 + 几百个地市，靠人肉一个个点不现实。这个脚本把「找栏目」这一步
自动化：拿一份机构首页清单，两跳探测出真正在公示处罚案件的栏目页。

两跳法（与 skill `local-amr-disclosure-harvest` 一致）
------------------------------------------------------
① 抓首页 → 找导航里含「处罚 / 双公示 / 双随机 / 案件 / 曝光 / 执法公示」的链接；
② 抓这些候选页 → 数里面有多少「详情页形态」的链接
   （`content/post_\\d+`、`/20\\d\\d[-/]\\d\\d[-/]\\d\\d/…`、`/c/20\\d\\d-…`、`t20\\d{6}_\\d+.shtml` 等）。
   详情链接 ≥3 条才算「像栏目页」，否则是政策解读或办事指南。

切分口径：站点**只当线索**，最终是否接入仍由人看过一眼（`--show` 打印标题样本），
因为「栏目名像」不等于「内容真是处罚决定」（常见同名栏目实为「行政执法工作动态」）。

用法：
  python3 tools/discover_penalty_cols.py                 # 跑内置清单
  python3 tools/discover_penalty_cols.py --seeds extra.json
  python3 tools/discover_penalty_cols.py --only 四川,湖北
  python3 tools/discover_penalty_cols.py --workers 6
产出：sources/references/penalty_cols_probe.json
"""
import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "sources", "references", "penalty_cols_probe.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 导航里出现这些词，才是「处罚公示」类栏目候选
NAV_KW = re.compile(r"行政处罚|处罚公示|处罚信息|处罚结果|双公示|双随机|执法公示|"
                    r"案件公开|案件信息|曝光台|案件|以案释法")

# 「详情页」链接形态。
# ⚠️ 不能只认固定模板 —— 实测各省 CMS 差异极大：
#   四川 `/scsjgj/c104591/2026/9/1/<32位hex>.shtml`（月/日**不补零**）、
#   浙江 `/col/col1228969897/index.html`（省政府门户 col 体系）、
#   泸州 `content_12345.html`、无锡 `/doc/2025/09/28/123.shtml`。
# 统一判据：**链接比栏目页深**（路径段多）+ 带长数字/日期段 + 是 html/shtml。
DETAIL_PAT = re.compile(
    r"(content[/_]?(post)?_?\d+|/c/\d{4}-\d{2}-\d{2}/"
    r"|/t20\d{6}_\d+|/\d{6}/t20\d{6}_\d+"
    r"|/\d{4}/\d{1,2}/\d{1,2}/[^\"']{6,}\.s?html?"
    r"|/art/\d{4}/\d{1,2}/\d{1,2}/art_\d+"
    r"|/detail[_/]?\d+|show\?id=\d+|\?id=\d+&?)")


def is_detail(href):
    """一个链接像不像「内容详情页」（而不是栏目页/首页/锚点）。

    ⚠️ 早期版本把「路径含 6 位数字」当详情页，结果四川局的导航页
    `/scsjgj/c104524/znwd.shtml`（智能问答）、`/jigou.shtml` 全被算成内容页，
    栏目评分虚高 → 满屏假候选。
    改为看**文件名本身**：必须带长数字串（≥4 位连号）或 16+ 位 hex
    （门户 CMS 的内容文件名普遍是 32 位 hash）。
    """
    h = href.split("#")[0].split("?")[0]
    if not re.search(r"\.s?html?$", h, re.I):
        return False
    segs = [s for s in h.split("/")[3:] if s]
    if len(segs) < 2:
        return False
    stem = re.sub(r"\.s?html?$", "", segs[-1], flags=re.I)
    if re.search(r"\d{16,}|[0-9a-f]{16,}", stem, re.I):   # 门户 hash 文件名
        return True
    if re.search(r"t20\d{6}_\d+", stem):                  # 政府门户 t日期_id
        return True
    if re.search(r"content[_/]?(post_)?\d+", stem, re.I):
        return True
    if re.search(r"\d{4,}", stem):                        # 12345.html / art_1234
        return True
    # 日期路径 + 短文件名（无锡 `/doc/2025/09/28/123.shtml` 的 id 只有 3 位）
    if re.search(r"/20\d{2}/\d{1,2}/\d{1,2}/", h):
        return True
    return False


# 详情标题像「处罚案件」才加分（用来把「政策解读」「抽检通告」栏目排下去）
PENALTY_TXT = re.compile(r"处罚|罚〔|罚\[|违法|决定书|案件|没收|罚款|责令")


# 明显不是处罚公示的栏目（政策法规、办事指南、解读…）
BAD_KW = re.compile(r"政策法规|法律法规|办事指南|办事服务|政策解读|知识|科普|"
                    r"投诉举报|消费提示|征求意见|招标|采购|人事|党建|"
                    r"权责清单|执法依据|裁量基准|文书式样|预决算|建议提案|"
                    r"年报|年报|办件|统计|价格监测|抽检|召回|消费警示")

# 「枢纽页」关键词：进了这些目录，才有机会在两跳内摸到处罚栏目
# ⚠️ 不要把「监管」「执法」「信用」放进来：它们会命中首页上**每一条新闻标题**
# （「省市场监管局召开…」），把队列挤满，真正的栏目链接反而进不来（实测四川
# 的「公示公告」就是这么被挤掉的）。
HUB_KW = re.compile(r"政务公开|信息公开|公示公告|公告公示|通知公告|双公示|"
                    r"数据公开|数据发布|重点领域|专栏|专题|双随机|曝光")


def curl(url, timeout=18):
    try:
        p = subprocess.run(["curl", "-sS", "-L", "-m", str(timeout),
                            "-A", UA, "--compressed", url],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore")
        return p.stdout or ""
    except Exception:
        return ""


MAX_PAGES = 11       # 每个机构最多抓多少页（含首页）
MIN_DETAIL = 3       # 详情链接至少这么多条才算「栏目页」


def norm(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", "", html.unescape(s)).strip()


def links(page, base):
    out = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]{1,160}?)</a>',
                         page or "", re.I):
        href, txt = m.group(1).strip(), norm(m.group(2))
        if not txt or href.startswith(("javascript:", "#", "mailto:")):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "/".join(base.split("/")[:3]) + href
        elif not href.startswith("http"):
            continue
        out.append((txt, href))
    return out


def probe_one(seed):
    """一个机构 → 候选栏目列表（广度优先两跳）。

    只用首页直连找不到东西：实测四川局首页导航里**根本没有「处罚」二字**，
    处罚公示藏在「政务公开 → 公示公告」（`/scsjgj/c104492/list.shtml`）之下；
    浙江省局用的是省门户 col 体系（`/col/col1228969897/index.html`）。
    所以必须：首页 → 枢纽页（政务公开/公示公告/双公示…）→ 处罚栏目。
    """
    name, home = seed["name"], seed["home"]
    host = "/".join(home.split("/")[:3])
    page0 = curl(home)
    if not page0:
        return {"name": name, "home": home, "status": "unreachable", "cols": []}

    seen, queue, found, pages = set(), [(home, 0)], [], 0
    while queue and pages < MAX_PAGES:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        pages += 1
        p = curl(url)
        if not p:
            continue
        L = links(p, url)
        det = [h for _t, h in L if is_detail(h)]
        if depth > 0 and len(set(det)) >= MIN_DETAIL:
            heads, pk, dhs = [], 0, []
            for t, h in L:
                if is_detail(h):
                    dhs.append(h)
                    if len(t) >= 6:
                        heads.append(t[:70])
                        if PENALTY_TXT.search(t):
                            pk += 1
                    if len(heads) >= 5:
                        break
            found.append({"text": _title_of(p, url) or url, "url": url,
                          "detail_links": len(set(det)), "penalty_titles": pk,
                          "samples": heads, "depth": depth,
                          "link_re": shape_regex(dhs),
                          "page2": page2_of(url, p),
                          "titlehit": ""})
        # 继续下潜
        if depth < 2:
            n_enq = 0
            for t, h in L:
                if h in seen or not h.startswith(host):
                    continue
                if len(t) > 30 or BAD_KW.search(t) or is_detail(h):
                    continue
                if not (NAV_KW.search(t) or HUB_KW.search(t)):
                    continue
                queue.append((h, depth + 1))
                n_enq += 1
                if n_enq >= (14 if depth == 0 else 8):
                    break
    found.sort(key=lambda c: -c["detail_links"])
    return {"name": name, "home": home,
            "status": "ok" if found else "no_column",
            "pages": pages, "cols": found[:4]}


def _title_of(page, url):
    m = re.search(r"<title>([^<]{2,120})</title>", page, re.I)
    if not m:
        return ""
    t = norm(re.split(r"[|_\-—]", m.group(1))[0])
    return t if 2 <= len(t) <= 30 else t[:30]


# ---------------------------------------------------------------- 自动配置
def shape_regex(hrefs):
    """把一批详情链接的「形状」变成一条正则（给采集器当 link 过滤器用）。

    例：`/art/2026/9/16/art_10146_1738093.html` / `…_1738092.html`
        → `/art/\\d{4}/\\d{1,2}/\\d{1,2}/art_\\d+_\\d+\\.html`
    做法：数字串统一换成占位符后取出现次数最多的形状，再把占位符还原成数字正则。
    ⚠️ 长度 ≥4 的数字段用 `\\d{n,}` 而不是 `\\d{n}`：日期里的月/日是 1—2 位，
    固定位数会把它们筛掉。
    """
    if not hrefs:
        return ""
    from collections import Counter
    cnt = Counter(re.sub(r"\d+", "\x00", h) for h in hrefs)
    shape = cnt.most_common(1)[0][0]
    parts = re.split(r"(\x00+)", shape)
    out = []
    for s in parts:
        if s.startswith("\x00"):
            n = len(s)
            out.append(r"\d{%d,}" % n if n > 1 else r"\d+")
        else:
            out.append(re.escape(s))
    return "".join(out)


def page2_of(col, page):
    """在栏目页里找「下一页 / 2」的链接，用来反推翻页模板。"""
    for t, h in links(page, col):
        if t in ("下一页", "下页", "2", "02") or re.match(r"^[>»]\s*$", t):
            return h
    for t, h in links(page, col):
        if re.fullmatch(r"\d{1,3}", t) and t == "2":
            return h
    return ""


def tpl_from(col, p2):
    """由「第 1 页 URL」与「第 2 页 URL」反推翻页模板（把值为 2 的那段数字换成 %d）。"""
    if not p2 or p2 == col:
        return None
    for m in re.finditer(r"\d+", p2):
        if m.group(0) != "2":
            continue
        # 该位置在 col 里对应的是别的数字（值不是 2），才认定它是页码
        a, b = m.start(), m.end()
        seg = col[a:b] if a < len(col) else ""
        if seg.isdigit() and seg != "2":
            return p2[:a] + "%d" + p2[b:]
        if not seg:
            return p2[:a] + "%d" + p2[b:]
    return None


def emit_sites(res, path, min_detail=6, min_penalty=1):
    """把探测结果写成采集器可直接吃的站点配置。

    准入（宁可少收，不可错收）：
      · 详情链接 ≥ min_detail；
      · 详情标题里像处罚案件的 ≥ min_penalty（「处罚/罚〔/违法/决定书/案件/没收/责令」）；
      · 栏目名或样本标题不能是纯目录页（政务公开/信息公开制度/指南）。
    """
    out = []
    for r in res:
        for c in r.get("cols", []):
            if c["detail_links"] < min_detail or c["penalty_titles"] < min_penalty:
                continue
            if re.search(r"信息公开(制度|指南|年报)|主动公开基本目录|预决算|机构职能",
                         c["text"] + " ".join(c["samples"])):
                continue
            p2 = c.get("page2") or ""
            key = re.sub(r"[^a-z0-9]", "", re.sub(r"^https?://", "", c["url"]).lower())[:22]
            out.append({
                "key": key or ("auto" + str(len(out))),
                "name": r["name"], "agency": r["name"].split("-", 1)[-1],
                "kind": "single", "col": c["url"],
                "page2": p2, "maxpage": 8,
                "link": c.get("link_re") or "", "titlehit": c.get("titlehit") or "",
            })
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✓ 自动配置 {len(out)} 个站点 → {path}")
    for s in out:
        print(f"   {s['name']:<14} {s['kind']:<6} {s['col'][:70]}")
    return out


# ---------------------------------------------------------------- 内置清单
PROV = [
    ("北京", "https://scjgj.beijing.gov.cn/"),
    ("天津", "https://scjg.tj.gov.cn/"),
    ("河北", "https://scjg.hebei.gov.cn/"),
    ("山西", "https://scjgj.shanxi.gov.cn/"),
    ("内蒙古", "https://amr.nmg.gov.cn/"),
    ("辽宁", "https://scjg.ln.gov.cn/"),
    ("吉林", "https://scjg.jl.gov.cn/"),
    ("黑龙江", "https://amr.hlj.gov.cn/"),
    ("上海", "https://scjgj.sh.gov.cn/"),
    ("江苏", "https://amr.jiangsu.gov.cn/"),
    ("浙江", "https://zjamr.zj.gov.cn/"),
    ("安徽", "https://amr.ah.gov.cn/"),
    ("福建", "https://scjgj.fujian.gov.cn/"),
    ("江西", "https://amr.jiangxi.gov.cn/"),
    ("山东", "https://amr.shandong.gov.cn/"),
    ("河南", "https://scjg.henan.gov.cn/"),
    ("湖北", "https://scjg.hubei.gov.cn/"),
    ("湖南", "https://amr.hunan.gov.cn/"),
    ("广西", "https://scjdglj.gxzf.gov.cn/"),
    ("海南", "https://amr.hainan.gov.cn/"),
    ("重庆", "https://scjgj.cq.gov.cn/"),
    ("四川", "https://scjgj.sc.gov.cn/"),
    ("贵州", "https://amr.guizhou.gov.cn/"),
    ("云南", "https://amr.yn.gov.cn/"),
    ("西藏", "https://amr.xizang.gov.cn/"),
    ("陕西", "https://scjgj.shaanxi.gov.cn/"),
    ("甘肃", "https://scjg.gansu.gov.cn/"),
    ("青海", "https://scjgj.qinghai.gov.cn/"),
    ("宁夏", "https://scjg.nx.gov.cn/"),
    ("新疆", "https://scjgj.xinjiang.gov.cn/"),
]

CITY = [
    ("石家庄", "https://scjgj.sjz.gov.cn/"),
    ("太原", "https://scjgj.taiyuan.gov.cn/"),
    ("呼和浩特", "https://scjgj.huhhot.gov.cn/"),
    ("沈阳", "https://scj.shenyang.gov.cn/"),
    ("大连", "https://scjgj.dl.gov.cn/"),
    ("长春", "https://scjgj.changchun.gov.cn/"),
    ("哈尔滨", "https://scjgj.harbin.gov.cn/"),
    ("南京", "https://scjgj.nanjing.gov.cn/"),
    ("苏州", "https://scjgj.suzhou.gov.cn/"),
    ("杭州", "https://scjgj.hangzhou.gov.cn/"),
    ("宁波", "https://scjgj.ningbo.gov.cn/"),
    ("合肥", "https://amr.hefei.gov.cn/"),
    ("福州", "https://scjgj.fuzhou.gov.cn/"),
    ("厦门", "https://scjgj.xm.gov.cn/"),
    ("南昌", "https://scjgj.nc.gov.cn/"),
    ("济南", "https://scjgj.jinan.gov.cn/"),
    ("郑州", "https://scjgj.zhengzhou.gov.cn/"),
    ("武汉", "https://scjgj.wuhan.gov.cn/"),
    ("长沙", "https://amr.changsha.gov.cn/"),
    ("广州", "https://scjgj.gz.gov.cn/"),
    ("珠海", "https://scjgj.zhuhai.gov.cn/"),
    ("佛山", "https://fsamr.foshan.gov.cn/"),
    ("东莞", "https://scjgj.dg.gov.cn/"),
    ("南宁", "https://scjgj.nanning.gov.cn/"),
    ("海口", "https://scjgj.haikou.gov.cn/"),
    ("成都", "https://scjgj.chengdu.gov.cn/"),
    ("贵阳", "https://scjgj.guiyang.gov.cn/"),
    ("西安", "https://scjgj.xa.gov.cn/"),
    ("兰州", "https://scjgj.lanzhou.gov.cn/"),
    ("西宁", "https://scjgj.xining.gov.cn/"),
    ("银川", "https://scjgj.yinchuan.gov.cn/"),
    ("乌鲁木齐", "https://scjgj.urumqi.gov.cn/"),
    ("唐山", "https://scjgj.tangshan.gov.cn/"),
    ("徐州", "https://scjgj.xz.gov.cn/"),
    ("常州", "https://scjgj.changzhou.gov.cn/"),
    ("南通", "https://scjgj.nantong.gov.cn/"),
    ("温州", "https://wzmsa.wenzhou.gov.cn/"),
    ("金华", "https://scjgj.jinhua.gov.cn/"),
    ("绍兴", "https://scjgj.sx.gov.cn/"),
    ("泉州", "https://scjgj.quanzhou.gov.cn/"),
    ("潍坊", "https://scjgj.weifang.gov.cn/"),
    ("烟台", "https://scjgj.yantai.gov.cn/"),
    ("临沂", "https://scjgj.linyi.gov.cn/"),
    ("洛阳", "https://scjgj.ly.gov.cn/"),
]

# 第二批：地级市（域名多为 scjgj.<拼音>.gov.cn，猜错的会被记为 unreachable，无副作用）
CITY2 = [
    ("保定", "https://scjgj.baoding.gov.cn/"),
    ("邯郸", "https://scjgj.hd.gov.cn/"),
    ("廊坊", "https://scjgj.lf.gov.cn/"),
    ("沧州", "https://scjgj.cangzhou.gov.cn/"),
    ("大同", "https://scjgj.dt.gov.cn/"),
    ("包头", "https://scjgj.baotou.gov.cn/"),
    ("鄂尔多斯", "https://scjgj.ordos.gov.cn/"),
    ("鞍山", "https://scjgj.anshan.gov.cn/"),
    ("锦州", "https://scjgj.jz.gov.cn/"),
    ("营口", "https://scjgj.yingkou.gov.cn/"),
    ("吉林市", "https://scjgj.jlcity.gov.cn/"),
    ("齐齐哈尔", "https://scjgj.qqhr.gov.cn/"),
    ("大庆", "https://scjgj.daqing.gov.cn/"),
    ("扬州", "https://scjgj.yangzhou.gov.cn/"),
    ("镇江", "https://scjgj.zhenjiang.gov.cn/"),
    ("盐城", "https://scjgj.yancheng.gov.cn/"),
    ("泰州", "https://scjgj.taizhou.gov.cn/"),
    ("淮安", "https://scjgj.huaian.gov.cn/"),
    ("连云港", "https://scjgj.lyg.gov.cn/"),
    ("宿迁", "https://scjgj.suqian.gov.cn/"),
    ("嘉兴", "https://scjgj.jiaxing.gov.cn/"),
    ("湖州", "https://scjgj.huzhou.gov.cn/"),
    ("台州", "https://scjgj.taizhou.gov.cn/"),
    ("衢州", "https://scjgj.quzhou.gov.cn/"),
    ("舟山", "https://scjgj.zhoushan.gov.cn/"),
    ("丽水", "https://scjgj.lishui.gov.cn/"),
    ("芜湖", "https://amr.wuhu.gov.cn/"),
    ("蚌埠", "https://amr.bengbu.gov.cn/"),
    ("马鞍山", "https://amr.mas.gov.cn/"),
    ("安庆", "https://amr.anqing.gov.cn/"),
    ("阜阳", "https://amr.fy.gov.cn/"),
    ("滁州", "https://amr.chuzhou.gov.cn/"),
    ("漳州", "https://scjgj.zhangzhou.gov.cn/"),
    ("莆田", "https://scjgj.putian.gov.cn/"),
    ("三明", "https://scjgj.sm.gov.cn/"),
    ("泉州", "https://scjgj.quanzhou.gov.cn/"),
    ("龙岩", "https://scjgj.longyan.gov.cn/"),
    ("宁德", "https://scjgj.ningde.gov.cn/"),
    ("赣州", "https://scjgj.ganzhou.gov.cn/"),
    ("九江", "https://scjgj.jiujiang.gov.cn/"),
    ("宜春", "https://scjgj.yichun.gov.cn/"),
    ("上饶", "https://scjgj.shangrao.gov.cn/"),
    ("淄博", "https://scjgj.zibo.gov.cn/"),
    ("济宁", "https://scjgj.jining.gov.cn/"),
    ("泰安", "https://scjgj.taian.gov.cn/"),
    ("威海", "https://scjgj.weihai.gov.cn/"),
    ("日照", "https://scjgj.rizhao.gov.cn/"),
    ("德州", "https://scjgj.dezhou.gov.cn/"),
    ("聊城", "https://scjgj.liaocheng.gov.cn/"),
    ("滨州", "https://scjgj.binzhou.gov.cn/"),
    ("菏泽", "https://scjgj.heze.gov.cn/"),
    ("开封", "https://scjgj.kaifeng.gov.cn/"),
    ("新乡", "https://scjgj.xinxiang.gov.cn/"),
    ("安阳", "https://scjgj.anyang.gov.cn/"),
    ("许昌", "https://scjgj.xuchang.gov.cn/"),
    ("南阳", "https://scjgj.nanyang.gov.cn/"),
    ("商丘", "https://scjgj.shangqiu.gov.cn/"),
    ("信阳", "https://scjgj.xinyang.gov.cn/"),
    ("宜昌", "https://scjgj.yichang.gov.cn/"),
    ("襄阳", "https://scjgj.xiangyang.gov.cn/"),
    ("十堰", "https://scjgj.shiyan.gov.cn/"),
    ("荆州", "https://scjgj.jingzhou.gov.cn/"),
    ("株洲", "https://amr.zhuzhou.gov.cn/"),
    ("湘潭", "https://amr.xiangtan.gov.cn/"),
    ("衡阳", "https://amr.hengyang.gov.cn/"),
    ("岳阳", "https://amr.yueyang.gov.cn/"),
    ("常德", "https://amr.changde.gov.cn/"),
    ("汕头", "https://stamr.shantou.gov.cn/"),
    ("惠州", "https://hzamr.huizhou.gov.cn/"),
    ("中山", "https://www.zs.gov.cn/scjgj/"),
    ("湛江", "https://scjgj.zhanjiang.gov.cn/"),
    ("茂名", "https://scjgj.maoming.gov.cn/"),
    ("肇庆", "https://scjgj.zhaoqing.gov.cn/"),
    ("清远", "https://scjgj.gdqy.gov.cn/"),
    ("柳州", "https://scjgj.liuzhou.gov.cn/"),
    ("桂林", "https://scjgj.guilin.gov.cn/"),
    ("北海", "https://scjgj.beihai.gov.cn/"),
    ("绵阳", "https://scjgj.mianyang.gov.cn/"),
    ("德阳", "https://scjgj.deyang.gov.cn/"),
    ("宜宾", "https://scjgj.yibin.gov.cn/"),
    ("南充", "https://scjgj.nanchong.gov.cn/"),
    ("达州", "https://scjgj.dazhou.gov.cn/"),
    ("乐山", "https://scjgj.leshan.gov.cn/"),
    ("遵义", "https://amr.zunyi.gov.cn/"),
    ("曲靖", "https://scjgj.qujing.gov.cn/"),
    ("玉溪", "https://scjgj.yuxi.gov.cn/"),
    ("宝鸡", "https://scjgj.baoji.gov.cn/"),
    ("咸阳", "https://scjgj.xianyang.gov.cn/"),
    ("渭南", "https://scjgj.weinan.gov.cn/"),
    ("榆林", "https://scjgj.yl.gov.cn/"),
    ("汉中", "https://scjgj.hanzhong.gov.cn/"),
    ("天水", "https://scjgj.tianshui.gov.cn/"),
    ("昌吉", "https://scjgj.cj.gov.cn/"),
]

# 非市监领域：其他执法部门的处罚公示（任务②）
OTHER = [
    ("生态环境部", "https://www.mee.gov.cn/"),
    ("交通运输部", "https://www.mot.gov.cn/"),
    ("应急管理部", "https://www.mem.gov.cn/"),
    ("国家卫生健康委", "https://www.nhc.gov.cn/"),
    ("国家药监局", "https://www.nmpa.gov.cn/"),
    ("海关总署", "https://www.customs.gov.cn/"),
    ("国家税务总局", "https://www.chinatax.gov.cn/"),
    ("文化和旅游部", "https://www.mct.gov.cn/"),
    ("农业农村部", "https://www.moa.gov.cn/"),
    ("国家邮政局", "https://www.spb.gov.cn/"),
    ("中国民航局", "https://www.caac.gov.cn/"),
    ("住房和城乡建设部", "https://www.mohurd.gov.cn/"),
    ("水利部", "https://www.mwr.gov.cn/"),
    ("国家林业和草原局", "https://www.forestry.gov.cn/"),
    ("国家金融监督管理总局", "https://www.nfra.gov.cn/"),
    ("中国证监会", "https://www.csrc.gov.cn/"),
    ("中国人民银行", "https://www.pbc.gov.cn/"),
    ("国家能源局", "https://www.nea.gov.cn/"),
    ("国家烟草专卖局", "https://www.tobacco.gov.cn/"),
    ("国家粮食和物资储备局", "https://www.lswz.gov.cn/"),
    ("国家矿山安全监察局", "https://www.chinamine-safety.gov.cn/"),
    ("国家铁路局", "https://www.nra.gov.cn/"),
    ("国家外汇管理局", "https://www.safe.gov.cn/"),
    ("国家疾病预防控制局", "https://www.ndcpa.gov.cn/"),
    ("自然资源部", "https://www.mnr.gov.cn/"),
    ("国家统计局", "https://www.stats.gov.cn/"),
    ("国家体育总局", "https://www.sport.gov.cn/"),
    ("国家文物局", "https://www.ncha.gov.cn/"),
    ("国家中医药管理局", "https://www.natcm.gov.cn/"),
    ("国家档案局", "https://www.saac.gov.cn/"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", help="额外种子 JSON：[{name,home},…]")
    ap.add_argument("--only", default="", help="只跑名称含这些词的种子（逗号分隔）")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=OUT,
                    help="结果 JSON 路径（⚠️ 并发跑多组时必须分开，否则互相覆盖）")
    ap.add_argument("--group", default="all", choices=["all", "prov", "city", "other"])
    ap.add_argument("--emit", default="", help="把合格结果写成采集器站点配置（路径）")
    ap.add_argument("--min-detail", type=int, default=6)
    ap.add_argument("--min-penalty", type=int, default=1)
    a = ap.parse_args()

    seeds = []
    if a.group in ("all", "prov"):
        seeds += [{"name": "省-" + n, "home": u} for n, u in PROV]
    if a.group in ("all", "city"):
        seeds += [{"name": "市-" + n, "home": u} for n, u in CITY]
        seeds += [{"name": "市-" + n, "home": u} for n, u in CITY2]
    if a.group in ("all", "other"):
        seeds += [{"name": "部-" + n, "home": u} for n, u in OTHER]
    if a.seeds:
        seeds += json.load(open(a.seeds, encoding="utf-8"))
    if a.only:
        keys = [k.strip() for k in a.only.split(",") if k.strip()]
        seeds = [s for s in seeds if any(k in s["name"] for k in keys)]

    print(f"探测 {len(seeds)} 个机构（并发 {a.workers}）\n")
    res = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe_one, s): s for s in seeds}
        for i, fu in enumerate(cf.as_completed(futs), 1):
            try:
                r = fu.result()
            except Exception as e:                       # noqa: BLE001
                s = futs[fu]
                r = {"name": s["name"], "home": s["home"],
                     "status": "error: %s" % e, "cols": []}
            res.append(r)
            mark = "✓" if r["cols"] else ("×" if r["status"] != "unreachable" else "✗")
            n = r["cols"][0]["detail_links"] if r["cols"] else 0
            print(f"[{i}/{len(seeds)}] {mark} {r['name']:<14} {r['status']:<12} 候选栏目 {len(r['cols'])}（最多 {n} 条详情）   ", flush=True)

    res.sort(key=lambda r: (-len(r["cols"]), r["name"]))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n✓ 写出 {a.out}")
    print("\n=== 有候选栏目的机构 ===")
    for r in res:
        if not r["cols"]:
            continue
        print(f"\n【{r['name']}】{r['home']}")
        for c in r["cols"][:3]:
            print(f"   ▸ {c['text']}  ({c['detail_links']} 条详情)  {c['url']}")
            for s in c["samples"][:2]:
                print(f"       · {s}")
    if a.emit:
        emit_sites(res, a.emit, a.min_detail, a.min_penalty)


if __name__ == "__main__":
    main()
