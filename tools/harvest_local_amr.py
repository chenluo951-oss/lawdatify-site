#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地市监局官网「行政处罚公示」采集（案例库的官方一手来源）

为什么要有它
------------
`harvest_cases.py` 的处罚案例主要来自总局曝光台、App 违规通报批次与站点资讯流，
**地方市监局的处罚决定书基本没进来** —— 而地方才是处罚公示的主力：绝大多数一般
程序处罚由市县两级作出，且官网会逐案（或按期）公示决定书全文，含文号、当事人、
违法事实、法律依据、罚款额、作出机关与日期。这些字段正是合规判断最有用的部分。

已打通的两种公示形态（都是「静态列表 + 静态详情页」，不需要 JS 渲染）
----------------------------------------------------------------------
① **单案决定书**：一条公告 = 一份决定书，标题即文号。
   例：广东省市场监管局 `/zwgk/sgs/xzcf/index_{N}.html` → `content/post_*.html`
② **案件信息公开表**：一条公告 = 一张表 = N 个案件（延安、江门、芜湖、泸州、
   马鞍山、章丘等都是这一形态）。**价值密度最高**：一页拆出十几到几十个结构化案件，
   字段齐整（文号 / 案由 / 当事人 / 主要违法事实 / 种类和依据 / 机关和日期）。
   本站对每个案件生成 `<详情页URL>#c<序号>` 的锚点链接，仍然**直达机关官网原文**。
   ⚠️ 只收**带「案由」或「主要违法事实」列**的表。同栏目下还有一类**名单式送达公告**
   （如「吊销营业执照决定书送达公告」，表里只有当事人/统一社会信用代码/文号，
   几十行同类企业、零违法事实），收进来只会把案例库冲成一堆公司名 —— 已按此规则排除。

配置化设计
----------
每个站只需描述「列表页在哪里、怎么翻页、怎么认详情链接、是什么形态」；
分类与机关校正一律复用 `harvest_cases.py` 的规则表（**单一事实来源**，不另起一套）。

⚠️ 已验证但**暂不可用**的源（别浪费时间重试）
- `cfws.samr.gov.cn`（总局处罚文书公示系统）：与 gsxt 同源，查询要 `/dologin` 登录门。
- `amr.ah.gov.cn/zwfw/xzcf/`：页头写着 ColumnType=**办事服务**，其实没有处罚清单。
- `amr.hunan.gov.cn/.../xzzfx/`：是「行政执法」工作动态栏目，不是决定书清单。
- `amr.sz.gov.cn/outer/doublePublic/list.html`、`scjgj.luzhou.gov.cn` 列表：JS 渲染。
  ⚠️ 无头 Chrome **走不通**：本机 Chrome 不经过沙箱代理，访问 gov.cn 站点报
  `ERR_CONNECTION_CLOSED`（curl 能通是因为 curl 走了代理）。JS 站只能去找它的 XHR 接口。
- `scjg.yanan.gov.cn` / `amr.wuhu.gov.cn`：直连超时（站点存在，属反爬/线路问题）。

用法：
  python3 tools/harvest_local_amr.py                 # 增量（只补新链接）
  python3 tools/harvest_local_amr.py --full          # 重新遍历全部页面（结果与已有记录取并集）
  python3 tools/harvest_local_amr.py --reset         # 清空重采（仅在确认站点规则大改时用）
  python3 tools/harvest_local_amr.py --refresh --site gd
                                              # 连已收录链接也重新解析（改了解析规则后用）
  python3 tools/harvest_local_amr.py --pages 20      # 覆盖每个站的翻页上限
  python3 tools/harvest_local_amr.py --site gd       # 只跑某个站
  python3 tools/harvest_local_amr.py --dry           # 只看结果不落盘
"""
import html
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, HERE)

from harvest_cases import (CASE_TYPES, LAW_RE, MONEY_RE, curl,  # noqa: E402
                           guess_type, textify)
from case_text_clean import clean_fact  # noqa: E402
from case_attach import attach_text, clean_attach_text  # noqa: E402
from case_reason import derive_fields  # noqa: E402

OUT = os.path.join(HERE, "sources", "cases", "local_amr.jsonl")

# 是否解析详情页的文书附件（.docx/.pdf/.xls）。默认开：
# 相当多地市局的处罚公示页正文是空壳，处罚内容只在附件里（见 case_attach.py 注释）。
# 关掉可以用 `--no-attach`（跑全量、只想要速度时）。
ATTACH = True

# org 沿用案例库既有的「机构分类桶」口径（页面的机关分布图、机关筛选都按它聚合），
# 精确机关名另存 `agency` —— 混着放会让统计图同一条曲线里既有分类又有机构名。
ORG_CAT = "地方市场监管局"

# 政府站对同 IP 的连续请求很敏感：单站几十次快速请求会被直接 403（实测泸州在
# 一轮全量抓取后即被封）。慢一点没关系，抓断才要重来。
PAGE_DELAY = 0.8     # 翻页间隔
DETAIL_DELAY = 0.6   # 详情页间隔

# ⚠️ 连续跑多个站会触发**跨站**频控：出口 IP 是同一个，前一个站打满额度后，
# 后面几个站会集体返回空页（实测一轮全量跑下来，泸州/昆明/江门/无锡同时 0 命中，
# 而隔几分钟单独跑同一个站却完全正常）。所以：
#   ① 空页必须重试多轮（指数退避）再判定到底；
#   ② 站与站之间留冷却时间；
#   ③ 补数据用 `--site <key>` 逐站跑，别指望一次全量跑完。
EMPTY_TRIES = 3      # 空页重试轮数（含首次）
SITE_GAP = 12.0      # 站间冷却（秒）

# ---------------------------------------------------------------- 站点配置
# kind: single = 一页一案；table = 一页多案（信息公开表）
# page: 翻页模板（%d 为页码）；None = 不分页
SITES = [
    {
        "key": "gd", "name": "广东省市场监督管理局",
        "agency": "广东省市场监督管理局", "kind": "single",
        "col": "https://amr.gd.gov.cn/zwgk/sgs/xzcf/index.html",
        "page": "index_%d.html", "maxpage": 8,
        "link": r'content/post_\d+\.html',
    },
    {
        "key": "qd", "name": "青岛市市场监督管理局",
        "agency": "青岛市市场监督管理局", "kind": "single",
        "col": "https://amr.qingdao.gov.cn/zwgk/gggs/xzcfgs/",
        "page": None, "maxpage": 1,
        "link": r'/\d{6}/t\d{8}_\d+\.shtml',
        # 这个栏目是「公告公示 > 行政处罚公示」，收的是**行政处罚告知送达公告**
        # （拟处罚：含案由、违法事实、依据、拟处罚内容），不是最终决定书 —— 如实标 kind。
        "kind_label": "行政处罚告知送达公告",
    },
    {
        "key": "lz", "name": "泸州市市场监督管理局",
        "agency": "泸州市市场监督管理局", "kind": "table",
        "col": "https://scjgj.luzhou.gov.cn/hzzfgs/qtzfxxgs/",
        # 该 CMS 的翻页是 list_<N>.html（不是 index_<N>.html），每页 10 条、ID 严格递减
        "page": "list_%d.html", "maxpage": 30,
        "link": r'/hzzfgs/qtzfxxgs/content_\d+',
        "titlehit": r"行政处罚案件信息公开|行政处罚信息公开|行政处罚决定书",
    },
    {
        "key": "wx", "name": "无锡市市场监督管理局",
        "agency": "无锡市市场监督管理局", "kind": "single",
        "col": "https://scjgj.wuxi.gov.cn/zfxxgk/xxgkml/qzjjgxx/xzcfajxx/index.shtml",
        "page": "index_%d.shtml", "maxpage": 8,
        "link": r'/doc/\d{4}/\d{2}/\d{2}/\d+\.shtml',
        "titlehit": r"行政处罚|处罚决定|典型案例|违法案例|通报",
    },
    {
        "key": "km", "name": "昆明市市场监督管理局",
        "agency": "昆明市市场监督管理局", "kind": "single",
        "col": "https://scjgj.km.gov.cn/zfxxgkpt/fdzdgknr/zdlyxxgk/scjdglxx/spypaq/xzcfxx/",
        "page": "index_%d.shtml", "maxpage": 8,
        "link": r'/c/\d{4}-\d{2}-\d{2}/\d+\.shtml',
        "titlehit": r"行政处罚|处罚决定|决定书|典型案例",
    },
    {
        "key": "jm", "name": "江门市市场监督管理局",
        "agency": "江门市市场监督管理局", "kind": "table",
        "col": "https://www.jiangmen.gov.cn/bmpd/jmsscjdglj/zwdt/tzgg/",
        "page": "index_%d.html", "maxpage": 80,
        "link": r'content/post_\d+\.html',
        # 该栏目混杂采购公告/抽检通告，只收处罚类。翻页按原始条目判空，
        # 标题筛选放到翻完之后 —— 处罚公示只是零星夹在别的公告之间。
        "titlehit": r"行政处罚.*公开|行政处罚决定书|行政处罚案件",
    },
    # ---------------------------------------------------------------- 第二轮扩展
    # ⚠️ 省级局基本不公开**逐案**处罚决定书（走的是国家企业信用信息公示系统／双公示
    # 平台），所以第二轮的产出仍集中在**地市局**；非市监部门单列在下面。
    # ⚠️ 已试跑后移除：沧州市局「行政处罚公示」的详情页**只有标题、没有正文**
    # （决定书正文不在网页上，只在省双公示系统里），抓进来每条的「违法事实」都是
    # 页面导航壳（市人民政府网站｜无障碍…市发展和改革委员会…）。宁缺毋滥，撤站。
    {
        "key": "fs", "name": "佛山市市场监督管理局",
        "agency": "佛山市市场监督管理局", "kind": "table",
        # 知识产权行政处罚公示：逐年一份「专利侵权纠纷处理案件信息公开表」
        "col": "https://fsamr.foshan.gov.cn/zwgk/zdlyxxgk/zscqxzcfgs/",
        "page": "index_%d.html", "maxpage": 6,
        "link": r"zwgk/zdlyxxgk/zscqxzcfgs/content/post_\d+\.html",
        # 这批是**专利侵权纠纷行政裁决**案件信息（维权裁决，不是行政处罚），如实标注
        "kind_label": "专利侵权纠纷行政裁决",
    },
    {
        "key": "ah", "name": "安徽省市场监督管理局",
        "agency": "安徽省市场监督管理局", "kind": "single",
        # 「铁拳」行动典型案例曝光台：每期一篇通稿，内含若干完整案例
        "col": "https://amr.ah.gov.cn/xwdt/ztzl/tqxddxalpgt/index.html",
        "page": "index_%d.html", "maxpage": 6,
        "link": r"/xwdt/ztzl/tqxddxalpgt/(dxal|gzxx)/\d+\.html",
        "titlehit": r"典型案例|铁拳|曝光",
    },
    {
        # 非市监领域：自然资源部行政执法公示（执法查处类）里的挂牌督办案件通报
        "key": "mnr", "name": "自然资源部",
        "agency": "自然资源部", "org": "自然资源部", "kind": "single",
        "col": "https://www.mnr.gov.cn/zt/zh/xzzfgs/",
        "page": "index_%d.html", "maxpage": 5,
        "link": r"gi\.mnr\.gov\.cn/\d{6}/t\d{8}_\d+\.html",
        "titlehit": r"挂牌督办|调查处理结果的通报|违法案件通报",
        "kind_label": "行政执法查处通报",
    },
    {
        "key": "gz", "name": "贵州省市场监督管理局",
        "agency": "贵州省市场监督管理局", "kind": "single",
        # 省局里少见的「省本级行政处罚决定书」全文栏（带文号，如 黔市监价处〔2024〕3号）。
        # ⚠️ 该栏目杂着「询问通知书公告」「送达公告」等程序性文书，靠 titlehit 只留处罚类。
        "col": "https://amr.guizhou.gov.cn/zwgk/xxgkml/jcxxgk/xzcf/",
        "page": "index_%d.html", "maxpage": 5,
        "link": r"zwgk/xxgkml/jcxxgk/xzcf/\d{6}/t\d{8}_\d+\.html",
        "titlehit": r"行政处罚",
    },
]

# 表格表头关键词 → 标准字段
HDR = {    "caseno": r"决定书文号|文书文号|处罚文号",
    "case": r"案件名称|案由",
    "party": r"违法企业|当事人|自然人姓名|被处罚",
    "fact": r"主要违法事实|违法事实|案情",
    "basis": r"种类和依据|处罚依据|法律依据|依据",
    "org": r"作出处罚的机关|处罚机关|执法机关",
    "date": r"机关名称和日期|机关和日期|处罚日期|作出日期",
    "money": r"罚款金额|罚没款|处罚金额",
}


def norm(s):
    """单元格/标题文本归一：去标签、反转义、压空白。"""
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", "", html.unescape(s)).strip()


# 决定书正文里成对出现的书名号有一半不是法律依据，而是**证据材料名**与**广告文案**：
# 「《营业执照》」「《专利代理机构执业许可证》」「《询问笔录》」「《线索转送函》」，
# 甚至市场监督管理局处罚决定书里会把违法广告文案原文加书名号。直接采信会把
# 「高频法条 / 法律依据」污染掉，因此过一道白名单式门禁。
LAW_NOISE = re.compile(r"营业执照|许可证|执业许可|笔录|说明|申请书|申请表|报告|凭证|"
                       r"清单|照片|截图|邮件|聊天记录|合同|发票|缴款|送达|回证|卷宗")
LAW_TAIL = re.compile(r"(法|条例|规定|办法|细则|规则|标准|准则|决定|意见|通知|解释|"
                      r"批复|指南|目录|清单|公告)$")


def is_law(x):
    """《…》里的内容是不是一部法规 / 标准（而不是证据材料）。"""
    x = x.strip()
    if not (2 <= len(x) <= 30):
        return False
    if LAW_NOISE.search(x):
        return False
    return bool(LAW_TAIL.search(x)) or x.startswith("中华人民共和国")


# 决定书标题在官网只有文号（「行政处罚决定书（粤市监处罚〔2026〕14号）」），
# 直接入库会得到几十条零信息量标题 —— 从正文抽一句话案由补上。
CAUSE_PATS = (
    r"构成([^。；，]{4,40}?)(?:的)?(?:违法行为|行为)",
    r"属于[“\"']?([^”。；，]{4,40}?)[”\"']?(?:的)?(?:情形|行为)",
    r"因(?:当事人)?(?:涉嫌)?([^。；，]{4,40}?)(?:，|。)(?:本局|我局|经查)",
)


def cause_of(body):
    for pat in CAUSE_PATS:
        m = re.search(pat, body)
        if m:
            c = m.group(1).strip()
            # 匹配可能从词中间起算：正文「当事人实施了混淆行为」会被切成「了实施混淆」，
            # 拼出来的标题读不通且丢信息（曾出现「了实施混淆案」「哄抬价格案」）。
            # 这类半截结果直接弃用，上层会退回列表标题。
            if len(c) < 6 or re.match(r"^[了的着之与和或在对于是等被]", c):
                continue
            if len(c) <= 40:
                return c
    return ""


def list_page(url, link_re):
    """列表页 → [(title, url)]（保持页面次序，**不做标题筛选**）。

    ⚠️ 标题筛选必须放在翻页循环之外做：像江门「通知公告」这种杂栏目，处罚类条目
    只是零星夹在采购公告里，某一页 0 命中完全正常。若在翻页时按「0 命中」中断，
    后面几十页的处罚公示会被静默漏掉（实测第 3 页起就连不上）。
    """
    h = curl(url)
    if not h:
        return []
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]{2,160}?)</a>', h):
        a, t = m.group(1).strip(), norm(m.group(2))
        if not re.search(link_re, a) or len(t) < 6 or t in seen:
            continue
        seen.add(t)
        if a.startswith("//"):
            a = "https:" + a
        elif a.startswith("/"):
            a = "/".join(url.split("/")[:3]) + a
        elif not a.startswith("http"):
            # ⚠️ 相对链接必须补全：安徽「铁拳」曝光台写成 `./dxal/150590161.html`，
            # 早期版本直接 `continue` 丢掉 → 整站「列表命中 0 条」。
            a = urljoin(url, a)
        out.append((t, a))
    return out


def page_url(col, tpl, n):
    if n <= 1 or not tpl:
        return col
    return col.replace("index.html", tpl % n) if "index.html" in col else \
        col.rstrip("/") + "/" + (tpl % n)


def ok_name(s):
    """候选标题是否像「案件名称」。

    公开表的「当事人」列常被拆成两行（企业名 + 统一社会信用代码），合并单元格时
    只剩「统一社会信用代码：9144070439********」——它会被当成案件标题上站，
    读起来是纯粹的噪声。必须有足够的中文才认，纯代码/证照号一律不算。
    """
    if not s:
        return False
    if re.match(r"^(统一社会信用代码|注册号|营业执照|[0-9A-Z]{15,})", s):
        return False
    return len(re.sub(r"[^\u4e00-\u9fa5]", "", s)) >= 4


def _clip_fact(s, n=30):
    """「案件名称」列缺失时，用违法事实首句兜底当标题 —— 但**必须卡在标点上**。

    ⚠️ 直接 `fact[:30]` 会把词切断：江门一条记录的标题被切成
    「当事人购进陈皮时未如实记录该批陈皮的名称、规格、数量、生产日」（少一个「期」），
    表格里看着像数据坏了。改为回退到最近的「、，。」，没有标点才加省略号。
    """
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"^当事人", "", s)
    if len(s) <= n:
        return s
    cut = max(s.rfind("，", 0, n), s.rfind("、", 0, n), s.rfind("。", 0, n),
              s.rfind("；", 0, n))
    if cut >= 12:
        return s[:cut]
    return s[:n - 1] + "…"


def case_from_row(cells, hmap, title, url, date, agency, org=ORG_CAT,
                  kind="行政处罚信息公开表"):
    """公开表的一行 → 一条案例；抽不出像样的案件名称则返回 None（该行丢弃）。"""
    def cell(k):
        i = hmap.get(k)
        return cells[i] if (i is not None and i < len(cells)) else ""

    name = next((x for x in (cell("case"), cell("party"),
                             _clip_fact(cell("fact")), title)
                 if ok_name(x)), "")
    if not name:
        return None
    caseno = cell("caseno")
    # 公开表的「案件名称」列不带文号，而文号是回溯原文最关键的一条线索 —— 补进标题，
    # 使页面上每条案例都能直接被拿去检索（GIF 与广东单案决定书的标题形态也就一致了）。
    if caseno and "〔" not in name:
        name = f"{name}（{caseno}）"
    blob = " ".join(cells)
    laws = []
    for x in LAW_RE.findall(cell("basis") + " " + cell("fact") + " " + name):
        x = x.strip()
        if is_law(x) and x not in laws:
            laws.append(x)
    fines = ["".join(x.split()) for x in MONEY_RE.findall(blob)[:4]]
    if not fines:  # 表里常写作「处罚款33102.1元」
        fines = ["".join(x.split()) for x in
                 re.findall(r"(?:处罚款|罚款)[^\d]{0,4}([\d,，.]+\s*(?:万)?元)", blob)[:4]]
    # 事实摘要：主要违法事实 → 退回「种类和依据」
    fact = cell("fact") or cell("basis")
    d = date
    m = re.search(r"20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}", cell("date") or "")
    if m:
        g = re.findall(r"\d+", m.group(0))
        d = f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
    return {
        "title": name,
        "url": url,
        "date": d or "",
        "org": org,
        "agency": agency,
        "type": guess_type(name, cell("fact"), cell("basis")),
        "laws": laws[:6],
        "fines": fines,
        "fact": re.sub(r"\s+", " ", fact)[:900],
        "caseno": caseno,
        "kind": kind,
        # 来源标记：下游 harvest_cases.py 靠它做镜像删除（比按 org 名判断稳，
        # 因为非市监领域的站点 org 各不相同）
        "src": "local_amr",
    }


def parse_table(html_text, url, list_title, date, agency, org=ORG_CAT,
                kind="行政处罚信息公开表"):
    """详情页里的公开表 → [case, …]。"""
    tables = re.findall(r"<table[\s\S]*?</table>", html_text)
    best, best_rows = None, 0
    for t in tables:
        rows = re.findall(r"<tr[\s\S]*?</tr>", t)
        if len(rows) > best_rows:
            best, best_rows = t, len(rows)
    if not best or best_rows < 2:
        return []
    rows = re.findall(r"<tr[\s\S]*?</tr>", best)
    grid = []
    for r in rows:
        cs = [norm(c) for c in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", r)]
        # 合并单元格会撑不出等长列，去掉尾部空列后继续
        while cs and not cs[-1]:
            cs.pop()
        if cs:
            grid.append(cs)
    if not grid:
        return []
    # 找表头行：命中「文号 / 案件名称 / 当事人」任意两个
    hmap, hdr_i = {}, 0
    for i, cs in enumerate(grid[:3]):
        hit = {k: j for k, pat in HDR.items()
               for j, c in enumerate(cs) if re.search(pat, c or "")}
        if len(hit) >= 2:
            hmap, hdr_i = hit, i
            break
    if not hmap:
        return []
    # ⚠️ 必须带「案由」或「主要违法事实」列，否则这不是案件信息公开表，而是
    # **名单式送达公告**（例：江门「吊销营业执照决定书送达公告」的表只有
    # 当事人 / 统一社会信用代码 / 文号 三列，42 行同类企业、零违法事实）。
    # 收进来的话，案例库会被几十行「某公司」同质记录冲淡，而每条都问答不了
    # 「因何事被罚、依据哪条」——案例库的核心价值恰恰在这两点。
    if not ({"case", "fact"} & set(hmap)):
        return []
    out = []
    for n, cs in enumerate(grid[hdr_i + 1:], 1):
        if not any(cs):
            continue
        c = case_from_row(cs, hmap, list_title, f"{url}#c{n}", date, agency, org,
                          kind)
        # 没有文号也没有案由的行 = 表尾说明行，丢掉
        if not c or (not c["caseno"] and not c["title"]):
            continue
        out.append(c)
    return out


def real_title(html_text, fallback):
    """从详情页取真实标题。

    列表页的标题经常被 CMS 截断成「…（青黄市监罚送...」——**省略号是页面自带**，
    不是我们抓漏了。优先用正文里「发布日期：」这个锚点回抽（正文结构是
    「首页 > 政务公开 > 公告公示 > 行政处罚公示 <标题> 发布日期：…」），
    再退回 <title>（注意很多站点的 <title> 只有站名，不能直接用）。
    """
    body = textify(html_text)
    m = re.search(r"([^\n]{6,200}?)\s*发布日期\s*[：:]", body)
    if m:
        seg = re.split(r"[>＞]", m.group(1))[-1].strip()
        seg = re.sub(r"^(行政处罚公示|公示公告|通知公告|正文|首页|政务公开|信息公开)\s*", "", seg)
        # CMS 的 <title> 会拼上站名：「…案_沧州市市场监督管理局」→ 去掉尾缀
        seg = re.split(r"\s*[_|｜]\s*", seg)[0]
        seg = norm(seg)
        if len(seg) >= 8:
            return seg
    for pat in (r'<meta[^>]+name="ArticleTitle"[^>]+content="([^"]+)"',
                r'<meta[^>]+name="ArticleTitle"[^>]+content=\'([^\']+)\'',
                r"<title>([^<]+)</title>"):
        m = re.search(pat, html_text, re.I)
        if m:
            t = norm(re.split(r"[|_\-—]", m.group(1))[0])
            if len(t) >= 8:
                return t
    return fallback


def is_junk(r):
    """记录级质量闸门：标题与事实都立不住的记录不上站。

    实测的三类垃圾（都是解析器早期版本的产物）：
      ① 标题是「统一社会信用代码：9144…」（当事人列被拆成两行）；
      ② 标题是「江门市市场监督管理局行政处罚信息公开表」——整表页被当成单案，
         没拆出任何一个案件；
      ③ 事实为空或只有几个字的壳。
    """
    t = (r.get("title") or "").strip()
    if len(t) < 6 or not ok_name(t):
        return True
    # 半截案由（「了销售不符合保障人体健康…的产品案」）—— cause_of 已加护栏，
    # 这里再挡一道，防止历史存量靠 --refresh 之外的理由漏过。
    if re.match(r"^[了的着之与和或在对于是等被《]", t):
        return True
    if not r.get("caseno") and re.search(r"(行政处罚|执法)信息(公开|公示)表", t):
        return True
    # 「…作废公告」是证照作废程序性文书，不是处罚案件（青岛「强制注销公司营业执照作废公告」）
    if re.search(r"作废公告", t):
        return True
    # ⚠️ 标题被页面壳污染：政府站的 footer 导航会被 textify 当成正文
    # （实测沧州：「市人民政府网站｜无障碍…市发展和改革委员会…」）。
    # ⚠️ 只能查**标题**与事实的**开头**，且要用足够特别的词：首版把「人民政府网站」
    # 也列进去，结果整批昆明/青岛记录的事实里只要提到「昆明市人民政府网站」就被误杀
    # （一次 refresh 掉了 50 条）。判据宁可窄。
    if re.search(r"打印页面|关闭页面|无障碍浏览|政府组成部门|友情链接|网站地图", t):
        return True
    f0 = (r.get("fact") or "")[:120]
    if re.search(r"无障碍|打印页面|政府组成部门|友情链接|网站地图", f0):
        return True
    # 规范性文件不是案件：正文以「各省、自治区、直辖市…」开头的是发文，不是处罚
    if (r.get("fact") or "").lstrip().startswith("各省、自治区"):
        return True
    # ⚠️ 事实长度阈值要按来源分开：公开表的「主要违法事实」列本身就极其精简
    # （泸州实测中位 14 字，如「生产虚假标注生产日期的食品」），用单案文书的
    # 20 字门槛会把整批公开表案例误杀。公开表有案由+文号已足够定位，只要求非空。
    f = (r.get("fact") or "").strip()
    if r.get("kind") == "行政处罚信息公开表":
        return not f
    return len(f) < 20


def trim_chrome(s):
    """剥掉正文前的导航壳。

    政府站的详情页正文前面永远拖着一段导航（网站首页 / 无障碍浏览 / 长者模式 /
    发布时间 / 浏览次数 / 字号：[ 大 中 小 ]…）。用「标题定位」的办法在这类站上
    会失手 —— 列表标题与正文大标题常有细微空格差异，`rfind` 找不到就退回页面开头，
    于是导航串被当成违法事实收进库（昆明实测：一串「长者模式 无障碍浏览」）。
    这里做两道兜底：① 从已知尾部锚点（字号/浏览次数/分享）之后起算；
    ② 再向前找「当事人 / 经调查」等正文起点。
    """
    if not s:
        return s
    anchors = ("字号：[ 大 中 小 ]", "字号：[大 中 小]", "浏览次数：", "打印本页",
               "关闭窗口", "分享到：", "扫一扫在手机打开当前页", "字体：", "索引号：")
    head, cut = s[:900], -1
    for a in anchors:
        i = head.find(a)
        if i >= 0:
            cut = max(cut, i + len(a))
    if cut > 0:
        s = s[cut:]
    for kw in ("当事人：", "当事人", "经调查", "经查", "本局于"):
        i = s.find(kw)
        if 0 <= i <= 220:
            s = s[i:]
            break
    return re.sub(r"\s+", " ", s).strip()


def parse_single(html_text, url, title, date, agency, kind="行政处罚决定书", org=ORG_CAT):
    """一页一案 → 一条案例。"""
    if re.search(r"\.{3}|…", title):
        title = real_title(html_text, title)
    body = textify(html_text)
    laws = []
    for x in LAW_RE.findall(body[:5000]):
        x = x.strip()
        if is_law(x) and x not in laws:
            laws.append(x)
    fines = ["".join(x.split()) for x in MONEY_RE.findall(body)[:4]]
    d = date
    m = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})", body)
    if m:
        d = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 事实摘要：**从正文标题之后开始截**。此前用「找『当事人』」的办法，遇到
    # 「行政处罚决定履行催告书」这类没有「当事人」字样的文书就会退到页面开头，
    # 把导航栏（网站首页 / 政府信息公开 / 无障碍浏览…）当成违法事实收进库。
    # 正文标题在页面里出现两次（面包屑 + 正文大标题），取**最后一次**出现即为正文起点。
    fact = ""
    for key in (re.sub(r"\s+", "", title), title):
        if not key:
            continue
        j = body.rfind(key)
        if j >= 0:
            fact = body[j + len(key):]
            break
    if not fact:
        i = body.find("当事人")
        if i < 0:
            i = body.find("经调查")
        fact = body[i:] if i > 0 else body
    fact = re.sub(r"^(行政处罚信息|正文|信息来源|来源|发布时间|发布日期)[：:][^\s]{0,30}", " ", fact)
    fact = trim_chrome(fact)
    # 兜底：面包屑 / 元信息栏 / PDF 页码（口径见 tools/case_text_clean.py）
    fact = clean_fact(fact, title)
    # ── 文书附件（Word / PDF / Excel）────────────────────────────
    # ⚠️ 相当多的地市局「处罚公示」详情页是**空壳页**：网页上只有标题和附件下载链接，
    # 违法事实/依据/罚款全在 .docx / .pdf 里。不读附件，这类记录的「处罚事由」必然
    # 是空的（页面上就出现「见原文」）。实测青岛市局送达公告正文 0 字、
    # 泸州市局决定书正文只有案由一句，附件里才是完整的当事人+事实+依据。
    att = {"text": "", "links": [], "files": []}
    if ATTACH and html_text:
        try:
            att = attach_text(html_text, url)
        except Exception:  # noqa: BLE001
            att = {"text": "", "links": [], "files": []}
    # ⚠️ 附件正文用 clean_attach_text（轻量），**不能**用 clean_fact ——
    # 后者是为网页壳设计的，会把本地文书正文当噪声删掉（详见 case_attach.py）。
    ex = clean_attach_text(att["text"]) if att.get("text") else ""
    if ex:
        if len(re.sub(r"\s", "", fact)) < 120:
            fact = (fact + " " + ex).strip() if fact else ex
        # 页面正文已经够长就不再拼附件，避免同一条记录里正文重复两遍
    caseno = ""
    mc = re.search(r"([\u4e00-\u9fa5]{1,8}市监[\u4e00-\u9fa5]{0,6}〔20\d{2}〕[\d\-～~、]+号)", body + " " + ex)
    if mc:
        caseno = mc.group(1)
    else:
        # 列表标题括号里可能是文号，也可能只是「（第一批）」——必须带〔年〕号才算
        w = re.search(r"[（(]([^（()）]*〔\d{4}〕[^（()）]*)[）)]", title)
        if w:
            caseno = w.group(1)
    # 昆明等站把文书名和文号连排（「行政处罚决定书云市监昆处罚〔2025〕1144号」），
    # 正则会连文书名一起吞进来 —— 剥掉前缀，只留文号本体。
    caseno = re.sub(r"^(行政处罚决定书|行政处罚决定|行政处罚|决定书|公告)+", "", caseno).strip()
    # 官网标题只有文号时，用正文抽出的一句话案由重写标题（文号保留在括号里）。
    # ⚠️ 案由本身可能已以「案」结尾（如「出具不实、虚假检验检测报告案」），
    #    直接再拼一个「案」会得到「…案案」——先剥掉尾部再拼。
    cause = re.sub(r"案$", "", cause_of(body)).strip()
    # 案由可能从书名号中间起算（正文「…违反《专利代理条例》…」被切成「《规范申请专利」），
    # 标题带个孤零零的开括号很难看 —— 去掉开头的标点/引号残片。
    cause = re.sub(r"^[《〈「【“‘\"'、，,。；;：:]+", "", cause).strip()
    shown = f"{cause}案（{caseno}）" if (cause and caseno) else (
        f"{cause}案" if cause else title)
    rec = {
        "title": shown, "url": url, "date": d or "", "org": org, "agency": agency,
        "type": guess_type(shown, cause, fact[:400]), "laws": laws[:6], "fines": fines,
        "fact": fact[:900], "caseno": caseno, "kind": kind,
        "src": "local_amr",
        # 文书附件（Word/PDF/Excel）的原始链接 —— 页面「原文」列旁边可以多给一个
        # 「文书附件」入口，用户能直接下到决定书原件。
        "attach": att.get("links") or [],
    }
    # 事由/处罚按**未截断**正文抽（口径同 harvest_cases.parse_case）
    return derive_fields(rec, fact)


def load_existing():
    rows = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def main():
    global ATTACH
    a = sys.argv[1:]
    only = a[a.index("--site") + 1] if "--site" in a else None
    full = "--full" in a
    pages_ovr = int(a[a.index("--pages") + 1]) if "--pages" in a else None
    # --refresh：连已收录的链接也重新解析一遍。解析规则改进后（标题/事实抽法变了），
    # 存量记录的标题是旧规则的结果，只靠增量永远修不到 —— 这时用它整体刷一遍。
    refresh = "--refresh" in a
    # 附件解析要点网络（每条详情页多 1～3 次下载）。跑全量嫌慢时可关。
    if "--no-attach" in a:
        ATTACH = False

    old = load_existing()
    if "--reset" in a:
        old = []
    # ⚠️ --full 的语义是「重新遍历全部页面」，**不是清空重建**：政府站会瞬时限流，
    # 「先清空再重采」一旦撞上限流就会把已有记录整段丢掉（实测泸州 53 条被判成 0 条）。
    # 因此无论哪种模式，写出时都按 url 与已有记录做并集，新采到的覆盖旧的。
    have = set() if full else {r["url"] for r in old}
    known = {r.get("caseno") for r in old if r.get("caseno")}
    new, stat = [], []
    print(f"已有地市监案例 {len(old)} 条\n")

    for si, s in enumerate(SITES):
        if only and s["key"] != only:
            continue
        if si:
            time.sleep(SITE_GAP)   # 站间冷却，避免跨站频控
        maxp = pages_ovr or s["maxpage"]
        raw, pages_used, empty_streak = [], 0, 0
        for p in range(1, maxp + 1):
            u = page_url(s["col"], s["page"], p)
            # 空页要重试多轮（指数退避）才判定「列表到底」。政府站会瞬时限流，
            # 一页假空就中断会让后面几十页整段丢失（泸州/昆明都这么丢过）。
            rows = []
            for k in range(EMPTY_TRIES):
                rows = list_page(u, s["link"])
                if rows:
                    break
                time.sleep(2.0 * (3 ** k))
            pages_used += 1
            if not rows:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                continue
            empty_streak = 0
            raw += rows
            time.sleep(PAGE_DELAY)
        # 先跨页去重，再按标题筛（同一条目可能同时出现在列表与右侧推荐位）
        seen, uniq = set(), []
        for t, u in raw:
            if u in seen:
                continue
            seen.add(u)
            uniq.append((t, u))
        if s.get("titlehit"):
            uniq = [(t, u) for t, u in uniq if re.search(s["titlehit"], t)]

        fresh = uniq if refresh else [(t, u) for t, u in uniq if u not in have]
        got = 0
        for t, u in fresh:
            h = curl(u)
            if not h:
                continue
            if s["kind"] == "table":
                cases = parse_table(h, u, t, "", s["agency"], s.get("org", ORG_CAT),
                                    s.get("kind_label", "行政处罚信息公开表"))
                # 同一份公开表可能分多期，文号天然唯一 —— 用它再挡一次重复
                cases = [c for c in cases if not (c["caseno"] and c["caseno"] in known)]
                for c in cases:
                    if c["caseno"]:
                        known.add(c["caseno"])
            else:
                # 同一栏目常混着两种形态（例：无锡「行政处罚案件」既有典型案例通稿，
                # 也有「行政处罚信息公示表」整表页）——先试按表格拆，拆不出来再当单案文书。
                cases = parse_table(h, u, t, "", s["agency"], s.get("org", ORG_CAT),
                                    s.get("kind_label", "行政处罚信息公开表"))
                if not cases:
                    cases = [parse_single(h, u, t, "", s["agency"],
                                          s.get("kind_label", "行政处罚决定书"),
                                          s.get("org", ORG_CAT))]
            for c in cases:
                new.append(c)
            got += len(cases)
            have.add(u)
            time.sleep(DETAIL_DELAY)
        stat.append((s["name"], pages_used, len(uniq), len(fresh), got))
        print(f"▸ {s['name']}：翻 {pages_used} 页｜列表命中 {len(uniq)} 条｜新链接 "
              f"{len(fresh)} 条｜拆出案例 {got} 条")

    if "--dry" in a:
        print(f"\n[dry] 合计新增 {len(new)} 条，未写盘")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    merged = {r["url"]: r for r in old if r.get("url")}
    added = 0
    for r in new:
        if r.get("url") and r["url"] not in merged:
            added += 1
        if r.get("url"):
            merged[r["url"]] = r
    rows = list(merged.values())
    # 质量闸门：早几轮的解析缺陷会留下「标题=统一社会信用代码」「标题=页面栏目名」
    # 这类记录，它们不会因为换了解析规则而自动消失（url 不同的旧记录一直在文件里）。
    # 写出前统一过滤一遍，等于每次运行都自愈。
    before = len(rows)
    rows = [r for r in rows if not is_junk(r)]
    if before != len(rows):
        print(f"① 质量闸门剔除 {before - len(rows)} 条（标题/事实不合格）")
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n✓ 写入 {OUT}：{len(rows)} 条（本轮新增 {added}，覆盖更新 {len(new) - added}）")
    if rows:
        from collections import Counter
        print("  机关：", Counter(r.get("agency") or r.get("org") for r in rows).most_common(10))
        print("  类型：", Counter(r.get("type") for r in rows).most_common(10))


if __name__ == "__main__":
    main()
