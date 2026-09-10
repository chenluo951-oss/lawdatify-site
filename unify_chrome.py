#!/usr/bin/env python3
"""统一全站导航与页脚。

对外分享场景下，各页面的导航文案、页脚信息必须一致：
- 导航：首页 / 合规资讯 / 法律分析 / 合规知识库 / 关于（PRM 工具入口放页脚，不占主导航）
- 页脚：站点定位一句话 + 工具入口 + 数据更新时间（UPDATED 区块）+ 免责提示

幂等：整块替换 <nav class="topnav">…</nav> 与 <footer>…</footer>，
可安全重复运行。UPDATED 区块由 build_topics.py 在每次同步后刷新。

用法：
    python3 unify_chrome.py            # 写入
    python3 unify_chrome.py --check    # 只报告差异
"""

import glob
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))

PAGES = [
    "index.html",
    "updates/index.html",
    "search.html",
    "about.html",
    "news/index.html",
    "news/briefs.html",
    "news/actions.html",
    "analysis/index.html",
    "analysis/pi-audit.html",
    "analysis/ai-label.html",
    "analysis/food-label.html",
    "kb/index.html",
    "kb/standards.html",
    "kb/benchmarks.html",
    "radar/index.html",
    "radar/calendar.html",
    "radar/actions.html",
    "radar/map.html",
]

# 导航项：(相对站点根路径, 文案)。PRM 与搜索是工具页，不进主导航。
# 监管雷达三子页（立法日历 / 监管动向 / 全球监管地图）在雷达总览页内互链，不占主导航。
NAV_ITEMS = [
    ("index.html", "首页"),
    ("updates/index.html", "今日更新"),
    ("radar/index.html", "监管雷达"),
    ("news/index.html", "合规资讯"),
    ("analysis/index.html", "法律分析"),
    ("kb/index.html", "合规知识库"),
    ("about.html", "关于"),
    ("search.html", "搜索"),
]

TODAY = date.today().strftime("%Y-%m-%d")


def esc(s):
    return s.replace("&", "&amp;").replace('"', "&quot;")


def build_nav(rel: str) -> str:
    p = "../" * rel.count("/")
    cur = rel.replace(os.sep, "/")
    links = []
    for target, label in NAV_ITEMS:
        active = ' class="active"' if target == cur else ""
        links.append(f'    <a href="{p}{target}"{active}>{label}</a>')
    return (
        '<nav class="topnav"><div class="inner">\n'
        f'  <a class="brand" href="{p}index.html">合规<span>无终点</span></a>\n'
        '  <div class="navlinks">\n' + "\n".join(links) + "\n  </div>\n"
        '</div></nav>'
    )


def build_footer(rel: str) -> str:
    p = "../" * rel.count("/")
    return (
        '<footer><div class="inner">\n'
        '  <div class="foot-brand">合规<span>无终点</span> · 即时零售合规知识库</div>\n'
        '  <div class="foot-desc">由法务团队维护 · 内容基于监管机构官网公开信息整理，逐条附原文深链</div>\n'
        '  <div class="foot-links">\n'
        f'    <a href="{p}updates/index.html">今日更新</a>·\n'
        f'    <a href="{p}news/index.html">合规资讯</a>·\n'
        f'    <a href="{p}kb/index.html">知识库</a>·\n'
        f'    <a href="{p}analysis/index.html">法律分析</a>·\n'
        f'    <a href="{p}news/briefs.html">简报归档</a>·\n'
        f'    <a href="{p}search.html">搜索</a>·\n'
        f'    <a href="{p}about.html">关于本站</a>\n'
        '  </div>\n'
        '  <div class="foot-meta">数据更新至 <span class="upd"><!-- UPDATED:START -->'
        f'{TODAY}<!-- UPDATED:END --></span>'
        ' · 本站内容不构成法律意见 · © 2026 合规无终点</div>\n'
        '</div></footer>'
    )


NAV_RE = re.compile(r'<nav class="topnav">.*?</nav>', re.S)
# footer 标签可能带任意属性（CMS 导出的 data-page-node-id 等），必须 [^>]*
# 且要处理「页面里出现多个 footer」的情况（只保留一个，其余删除）
FOOT_RE = re.compile(r'<footer[^>]*>.*?</footer>', re.S)
UPD_RE = re.compile(r'(<!-- UPDATED:START -->).*?(<!-- UPDATED:END -->)', re.S)

# 样式表缓存治理：给 style.css 链接附加 mtime 版本号，改名/改样式后浏览器立即拉新。
STYLE_RE = re.compile(r'href="((?:\.\./)?assets/style\.css)(?:\?[^"]*)?"')


def _style_v():
    try:
        return str(int(os.path.getmtime(os.path.join(HERE, "assets", "style.css"))))
    except OSError:
        return "1"


def process(rel: str, do_write: bool) -> str:
    path = os.path.join(HERE, rel)
    if not os.path.exists(path):
        return f"  {rel:<24} 跳过（不存在）"
    s = open(path, encoding="utf-8").read()
    new = NAV_RE.sub(lambda _: build_nav(rel), s, count=1)
    if FOOT_RE.search(new):
        first = [True]

        def _repl(_):
            if first[0]:
                first[0] = False
                return build_footer(rel)
            return ""  # 多余的 footer 直接删除，避免重复

        new = FOOT_RE.sub(_repl, new)
    else:
        # 没有 footer 的页面（理论上没有）：补在 </body> 前
        new = new.replace("</body>", build_footer(rel) + "\n</body>", 1)
    new = STYLE_RE.sub(lambda m: f'href="{m.group(1)}?v={_style_v()}"', new)
    if new == s:
        return f"  {rel:<24} 无变化"
    if do_write:
        open(path, "w", encoding="utf-8").write(new)
    return f"  {rel:<24} 已统一 ✓"


def refresh_updated(stamp: str, do_write=True):
    """供 build_topics.py 调用：刷新全站「数据更新至」时间戳。"""
    n = 0
    for rel in PAGES:
        path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            continue
        s = open(path, encoding="utf-8").read()
        new = UPD_RE.sub(lambda m: m.group(1) + stamp + m.group(2), s)
        if new != s and do_write:
            open(path, "w", encoding="utf-8").write(new)
            n += 1
    return n


def all_pages():
    """主导航页 + news/reports/ 下的报告页（动态生成，数量不固定）。"""
    extra = sorted(
        os.path.relpath(p, HERE).replace(os.sep, "/")
        for p in glob.glob(os.path.join(HERE, "news", "reports", "*.html"))
    )
    return PAGES + [p for p in extra if p not in PAGES]


def main():
    do_write = "--check" not in sys.argv
    for rel in all_pages():
        print(process(rel, do_write))


if __name__ == "__main__":
    main()
