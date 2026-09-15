#!/usr/bin/env python3
"""为站点页面统一注入社会化分享元数据（Open Graph / Twitter Card）与站点图标。

用法：
    python3 inject_meta.py           # 处理全部页面
    python3 inject_meta.py --check   # 只报告差异，不写入

设计说明：
- 幂等：注入内容包在 <!-- SOCIAL:START --> / <!-- SOCIAL:END --> 标记之间，
  重复运行会整体替换而不是追加，可安全反复执行。
- **SITE_URL 是本脚本唯一的域名开关**。将来站点从 GitHub Pages 切换
  到自定义域名时，改这一处常量再运行一次即可全站更新。

为什么需要它：站点要分享给公司业务领导与外部同行，分享到微信/钉钉/飞书
时的预览卡片依赖 og:title / og:description / og:image；缺失这些标签，
对方看到的就只有一个没有标题、没有摘要、没有封面的秃链接。
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# 站点根地址 —— 切换域名时只需修改这一处
# 注意 og:url / og:image 必须是绝对 URL（爬虫要求），不能用相对路径
# ------------------------------------------------------------------
SITE_URL = "https://chenluo951-oss.github.io/lawdatify-site"
OG_IMAGE = f"{SITE_URL}/assets/og-cover.png"

SITE_NAME = "合规无终点"
LOCALE = "zh_CN"


def _duty_scale():
    """义务清单规模表述。**禁止写死数字** —— 一律从 duties.json 动态统计。"""
    import json
    p = os.path.join(HERE, "sources", "standards", "duties.json")
    try:
        du = json.load(open(p, encoding="utf-8"))
        cats = du.get("categories", [])
        scenes = sum(len(c.get("scenes", [])) for c in cats)
        duties = sum(len(s.get("duties", [])) for c in cats
                     for s in c.get("scenes", []))
        if duties:
            return f"{len(cats)} 大类 {scenes} 场景 {duties} 项义务"
    except Exception:
        pass
    return "全部合规义务"


DUTY_SCALE = _duty_scale()

# 需要处理的页面（相对仓库根）。_quarantine/ 与 news/reports/ 下不入列。
PAGES = [
    "index.html",
    "search.html",
    "about.html",
    "updates/index.html",
    "news/index.html",
    "news/briefs.html",
    "news/actions.html",
    "analysis/index.html",
    "analysis/pi-audit.html",
    "analysis/ai-label.html",
    "analysis/food-label.html",
    "analysis/app-violation-pattern.html",
    "analysis/algo-filing-guide.html",
    "analysis/dark-store-license.html",
    "kb/index.html",
    "kb/standards.html",
    "kb/texts.html",
    "kb/wx.html",
    "kb/benchmarks.html",
    "news/calendar.html",
    "news/map.html",
    "news/app-violations.html",
    "news/algo-filing.html",
    "kb/cases.html",
]

# 每页的分享描述。社交卡片上显示的就是这段文字，因此按受众重写而非沿用页面 description。
OG_DESC = {
    "index.html": "面向合规实务的法规标准与合规动态库：" + DUTY_SCALE + "逐条配条款原文、标杆做法与可套用文案；"
                  "今日更新、合规动态、合规知识库逐条附官方深链。",
    "prm.html": "平台规则与协议管理中心（PRM）：面向法务的统一规则资产台账与流程标准化方案。",
    "search.html": "站内全文检索：法规、动态、知识要点一站搜。",
    "about.html": "关于本站：内容来源、选择标准、更新频率、链接核验机制与免责声明。",
    "news/index.html": "覆盖数据合规、AI 合规、算法合规、平台合规、产品合规、价格合规，"
                       "以及网络交易、餐饮、冷链仓储、配送与用工、计量、零售与消费者、绿色等各领域的"
                       "合规动态流，每条附发布机构官网原文深链与合规解读。",
    "news/actions.html": "应对建议 · 行动清单：把每条监管动态解读里的行动项逐条抽出，按紧迫度（立即动作 / 30 天内 / 持续监控）"
                      "排序，逐项标注风险等级、责任动作与监管依据，随每日合规动态自动更新。",
    "news/briefs.html": "合规简报归档：日报 / 周报 / 月报全期次网页版在线阅读。",
    "updates/index.html": "今日更新：法规标准增量、生效倒计时、立法节点与草案截止，一屏掌握今天变了什么。",
    "analysis/index.html": "法律分析：围绕合规实务场景的专题研究，结论先行、逐条附官方原文深链、配产品级合规图示。",
    "analysis/pi-audit.html": "个保合规审计：1000 万门槛、三档频次、两条触发路径与八项审计重点，含监管要求审计的执行链路图。",
    "analysis/ai-label.html": "AI 生成内容标识：四类主体义务分工、显式与隐式双标识、传播端「属于/可能为/疑似」三档判定流程。",
    "analysis/food-label.html": "食品标签新规与前置仓：拆箱称重被纳入预包装食品监管，含合规标签版面示意图与 6 个月倒计时行动表。",
    "analysis/app-violation-pattern.html": "基于 651 份 App 侵害用户权益通报的实证分析：30 家发布机关的两层结构、三段处置链条（批次通报 / 整改复核 / 下架处置）、四种名单载体与 35 天的整改窗口，含统计口径说明与行动清单。",
    "analysis/algo-filing-guide.html": "算法备案与生成式 AI 登记实务：四条并列序列为何不可相加、备案编号怎么读、「备案」与「登记」怎么判断、变更与注销必须主动办理，含备案 1014 条 / 深度合成 7764 条 / 生成式 AI 1846 条的规模对比与编号结构解析。",
    "analysis/dark-store-license.html": "前置仓的资质边界：把仓内动作拆成仓储分拣、拆箱称重分装、现场加工制售三类，逐一对照许可项目；含网络经营与平台备案的三条一致性红线、分装标签版面示意、食用农产品合格证与六种高频超范围情形。",
    "analysis/polish.html": "报告排版打磨日志：每次打磨的改动文件、前后对比、依据与 QA 验证结果。",
    "kb/index.html": "合规知识库总览：法规标准原文、" + DUTY_SCALE + "、义务矩阵、标杆做法与参考文案、公众号原文存档，逐条标注效力状态与实施日期。",
    "kb/benchmarks.html": "ESG / 法律 / 券商研报专业样本对标库，提炼可借鉴的排版与结构要点。",
    "kb/standards.html": "个人信息保护、数据安全、网络安全、算法与 AI、移动应用合规，以及网络交易、餐饮外卖、仓储冷链、即时配送、计量、消费者权益与绿色包装等领域的国家标准、法律法规与指引指南汇总，标注效力状态与实施日期，并以全部合规义务为主线组织。",
    "kb/texts.html": "法律、行政法规、部门规章与规范性文件的官方正文，可在站内直接阅读、复制与下载；标准正文受著作权保护，改由条目页给出发布机构的官方在线阅读入口。",
    "news/calendar.html": "立法日历：按倒计时排列的法律与标准施行日、征求意见截止与申报节点，覆盖中国与主要海外辖区，逐条附原文深链。",
    "news/actions.html": "合规动态应对建议：正在推进的专项治理、监督检查与安全调查，并给出按领域落地建议。",
    "news/map.html": "全球监管地图：按司法辖区查看立法、执法与规则动态，点击辖区即可下钻该地全部合规条目。",
    "news/app-violations.html": "移动应用违规治理专项：工业和信息化部与国家网信办历年 App（含小程序、SDK）侵害用户权益与个人信息收集使用问题通报的历史库与数据分析，附可对照自查的合规行动清单。",
    "news/algo-filing.html": "算法合规治理专项：国家网信办公告的互联网信息服务算法备案清单、生成式人工智能服务已备案与已登记信息结构化信息库，按算法类别、批次与属地分析。",
    "kb/cases.html": "合规案例库：监管机关官网公开的处罚决定、通报与典型案例，按违法类型、执法机关、依据法条与罚款幅度结构化索引，逐条附官方原文深链。",
}

DEFAULT_DESC = "合规动态、法律分析与合规知识库，逐条附官方深链，由个人独立维护。"

BLOCK_RE = re.compile(
    r"[ \t]*<!-- SOCIAL:START -->.*?<!-- SOCIAL:END -->\n?", re.S
)

# 首页正文里的义务规模文案也随数据动态同步（**禁止写死数字**，否则改数据必漏改）。
DUTY_SCALE_RE = re.compile(r"\d+ 个合规主题 · \d+ 个业务场景 · \d+ 项具体义务")
DUTY_MORE_RE = re.compile(r"· \d+ 项逐条含条款原文")


def _duty_parts():
    """返回 (主题数, 场景数, 义务数)，从 duties.json 动态统计。"""
    import json
    p = os.path.join(HERE, "sources", "standards", "duties.json")
    try:
        du = json.load(open(p, encoding="utf-8"))
        cats = du.get("categories", [])
        scenes = sum(len(c.get("scenes", [])) for c in cats)
        duties = sum(len(s.get("duties", [])) for c in cats for s in c.get("scenes", []))
        return len(cats), scenes, duties
    except Exception:
        return 0, 0, 0


def sync_duty_scale(html: str) -> str:
    """把首页正文中的义务规模文案同步为当前统计值。"""
    nc, ns, nd = _duty_parts()
    if not nd:
        return html
    html = DUTY_SCALE_RE.sub(f"{nc} 个合规主题 · {ns} 个业务场景 · {nd} 项具体义务", html)
    html = DUTY_MORE_RE.sub(f"· {nd} 项逐条含条款原文", html)
    return html


def page_url(rel: str) -> str:
    """把相对文件路径转成对外绝对 URL（目录页去掉 index.html）。"""
    p = "/" + rel.replace(os.sep, "/")
    if p.endswith("/index.html"):
        p = p[: -len("index.html")]
    return SITE_URL + p.rstrip("/") + "/"


def esc_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;")


def build_block(rel: str, title: str) -> str:
    desc = OG_DESC.get(rel, DEFAULT_DESC)
    t = esc_attr(title)
    d = esc_attr(desc)
    u = page_url(rel)
    # 相对路径前缀：子目录页面需要 ../ 才能指到站点根
    prefix = "../" * rel.count("/")
    return (
        "<!-- SOCIAL:START -->\n"
        f'<link rel="icon" type="image/svg+xml" href="{prefix}assets/favicon.svg">\n'
        f'<link rel="apple-touch-icon" href="{prefix}assets/favicon.svg">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:site_name" content="{esc_attr(SITE_NAME)}">\n'
        f'<meta property="og:locale" content="{LOCALE}">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:url" content="{u}">\n'
        f'<meta property="og:image" content="{OG_IMAGE}">\n'
        f'<meta property="og:image:width" content="1200">\n'
        f'<meta property="og:image:height" content="630">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{t}">\n'
        f'<meta name="twitter:description" content="{d}">\n'
        f'<meta name="twitter:image" content="{OG_IMAGE}">\n'
        "<!-- SOCIAL:END -->\n"
    )


def process(rel: str, do_write: bool) -> str:
    path = os.path.join(HERE, rel)
    if not os.path.exists(path):
        return f"  {rel:<24} 跳过（文件不存在）"

    s = open(path, encoding="utf-8").read()

    m = re.search(r"<title>(.*?)</title>", s, re.S)
    if not m:
        return f"  {rel:<24} 跳过（无 <title>）"
    title = re.sub(r"\s+", " ", m.group(1)).strip()

    block = build_block(rel, title)
    if BLOCK_RE.search(s):
        new = BLOCK_RE.sub(lambda _: block, s, count=1)
        action = "更新"
    else:
        # 未注入过：插到 </head> 之前；没有 </head> 则插到 <body> 之前
        anchor = "</head>" if "</head>" in s else "<body"
        idx = s.find(anchor)
        new = s[:idx] + block + s[idx:]
        action = "注入"

    new = sync_duty_scale(new)

    if new == s:
        return f"  {rel:<24} 无变化"
    if do_write:
        open(path, "w", encoding="utf-8").write(new)
    return f"  {rel:<24} {action} ✓"

def all_pages():
    """主导航页 + news/reports/ 下的报告页（动态生成，数量不固定）。"""
    extra = sorted(
        os.path.relpath(p, HERE).replace(os.sep, "/")
        for p in glob.glob(os.path.join(HERE, "news", "reports", "*.html"))
    )
    return PAGES + [p for p in extra if p not in PAGES]


def main():
    do_write = "--check" not in sys.argv
    pages = all_pages()
    print(("检查" if not do_write else "处理") + f" {len(pages)} 个页面（站点根 {SITE_URL}）")
    for rel in pages:
        print(process(rel, do_write))
    if not do_write:
        print("\n（--check 模式，未写入任何文件）")


if __name__ == "__main__":
    main()
