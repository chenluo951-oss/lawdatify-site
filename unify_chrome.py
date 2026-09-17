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
    "about.html",
    "news/index.html",
    "news/today.html",
    "news/briefs.html",
    "news/actions.html",
    "analysis/index.html",
    "analysis/pi-audit.html",
    "analysis/ai-label.html",
    "analysis/food-label.html",
    "analysis/app-violation-pattern.html",
    "analysis/algo-filing-guide.html",
    "analysis/dark-store-license.html",
    "manage/index.html",
    "manage/audit.html",
    "kb/index.html",
    "kb/standards.html",
    "kb/texts.html",
    "kb/wx.html",
    "kb/citations.html",
    "news/calendar.html",
    "news/map.html",
    "analysis/app-violations.html",
    "analysis/algo-filing.html",
    "kb/cases.html",
    "search.html",
]
# ⚠️ 两个「地址搬迁」留下的跳转页（kb/audit.html、updates/index.html）**不进 PAGES**：
# 它们是单文件 meta-refresh 落地页，process() 会往 </body> 前塞统一页脚，
# 把整页样式挤坏（跳转前那一瞬用户看到的会是错位内容）。

# 导航项：(相对站点根路径, 文案)。
# 2026-09-17（用户要求）：
#   ① 「今日更新」并入「合规动态」——增量与事件流同源同批，不再占一个一级入口
#      （今日更新现为 news/today.html，在合规动态子导航内）；
#   ② 从「合规知识库」拆出「合规管理」（合规审计迁入 manage/）；
#   ③ 主导航去掉「搜索」——搜索框在首页 hero 与合规动态页内已有，导航项冗余。
NAV_ITEMS = [
    ("index.html", "首页"),
    ("news/index.html", "合规动态"),
    ("analysis/index.html", "法律分析"),
    ("manage/index.html", "合规管理"),
    ("kb/index.html", "合规知识库"),
    ("about.html", "关于"),
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
        '  <div class="foot-brand">合规<span>无终点</span> · 法规标准与合规动态库</div>\n'
        '  <div class="foot-desc">由个人独立维护 · 内容基于监管机构官网公开信息整理，逐条附原文深链</div>\n'
        '  <div class="foot-links">\n'
        f'    <a href="{p}news/index.html">合规动态</a>·\n'
        f'    <a href="{p}news/today.html">今日更新</a>·\n'
        f'    <a href="{p}analysis/index.html">法律分析</a>·\n'
        f'    <a href="{p}manage/index.html">合规管理</a>·\n'
        f'    <a href="{p}kb/index.html">知识库</a>·\n'
        f'    <a href="{p}news/briefs.html">简报归档</a>·\n'
        f'    <a href="{p}search.html">搜索</a>·\n'
        f'    <a href="{p}about.html">关于本站</a>\n'
        '  </div>\n'
        '  <div class="foot-meta">数据更新至 <span class="upd"><!-- UPDATED:START -->'
        f'{TODAY}<!-- UPDATED:END --></span>'
        ' · 本站内容不构成法律意见 · © 2026 合规无终点</div>\n'
        '</div></footer>'
    )


# nav 标签可能带任意属性（CMS 导出的 data-page-node-id 等），必须 [^>]*
# （about.html 就是这种：品牌名曾残留在 CMS 导出结构里，正则漏匹配 → 导航不统一）
NAV_RE = re.compile(r'<nav class="topnav"[^>]*>.*?</nav>', re.S)
# footer 标签可能带任意属性（CMS 导出的 data-page-node-id 等），必须 [^>]*
# 且要处理「页面里出现多个 footer」的情况（只保留一个，其余删除）
FOOT_RE = re.compile(r'<footer[^>]*>.*?</footer>', re.S)
UPD_RE = re.compile(r'(<!-- UPDATED:START -->).*?(<!-- UPDATED:END -->)', re.S)

# 样式表缓存治理：给 style.css 链接附加 mtime 版本号，改名/改样式后浏览器立即拉新。
STYLE_RE = re.compile(r'href="((?:\.\./)?assets/style\.css)(?:\?[^"]*)?"')
# 法条悬浮卡组件（P1-1）：全站注入一个 defer 脚本；数据 kb/arts.js 由组件**按需**加载
# （页面里真的出现《XX 法》第 X 条才拉，首页这类页面不白付 366 KB）。
ARTJS_RE = re.compile(r'[ \t]*<script[^>]*src="[^"]*assets/art-card\.js[^"]*"[^>]*>\s*</script>\n?')


def _mtime(name):
    try:
        return str(int(os.path.getmtime(os.path.join(HERE, "assets", name))))
    except OSError:
        return "1"


def body_end(s):
    """返回「可以安全插入脚本标签」的 </body> 位置；找不到或不安全返回 -1。

    ⚠️ 这里踩过一次造成整页 JS 全死的坑（2026-09-17）：
    原先用 `s.replace("</body>", tag + "</body>", 1)` —— 替换**第一个** </body>。
    可 kb/texts.html 与 manage/audit.html 的内联 <script> 里用 JS 字符串拼
    Word 导出模板，字符串里含 `'</body></html>'`，它出现在文档真正 </body> **之前**
    ⇒ 注入标签落进字符串中间，而注入标签自带 `</script>`，
    HTML 解析器在 JS 字符串中途就闭合了整段内联脚本 ⇒ 剩下的代码成为
    语法错误 ⇒ **原文库 / 合规审计页整页 JS 全死**（列表空白、按钮没反应）。

    所以现在：① 取**最后一个** </body>（文档真正的结束标签在最后）；
    ② 再校验该位置不在内联 <script> 内部（前缀里 <script 与 </script> 必须平衡），
    不平衡就放弃注入 —— 宁可不挂悬浮卡，也绝不能截断页面脚本。
    """
    i = s.rfind("</body>")
    if i < 0:
        return -1
    pre = s[:i]
    if (len(re.findall(r'<script', pre, re.I))
            != len(re.findall(r'</script>', pre, re.I))):
        return -1
    return i


def _mtime_arts():
    """法条索引数据 kb/arts.js 的版本号（由 tools/build_article_index.py 生成）。"""
    try:
        return str(int(os.path.getmtime(os.path.join(HERE, "kb", "arts.js"))))
    except OSError:
        return "1"


def _style_v():
    return _mtime("style.css")


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
        # 没有 footer 的页面（理论上没有）：补在 </body> 前。
        # 同样走 body_end()，避免插进内联脚本的 JS 字符串里（与悬浮卡同一个坑）。
        _i = body_end(new)
        if _i >= 0:
            new = new[:_i] + build_footer(rel) + "\n" + new[_i:]

    new = STYLE_RE.sub(lambda m: f'href="{m.group(1)}?v={_style_v()}"', new)
    # 法条悬浮卡：先清掉旧标签再补一次，保证路径与版本号随部署更新（幂等）
    # ARTJS_RE 也负责清掉历史误注入到 JS 字符串里的那份（见 body_end 的注释）。
    new = ARTJS_RE.sub("", new)
    p = "../" * rel.count("/")
    tag = (f'<script src="{p}assets/art-card.js?v={_mtime("art-card.js")}" '
           f'data-arts="{p}kb/arts.js?v={_mtime_arts()}" defer></script>')
    i = body_end(new)
    if i >= 0:
        new = new[:i] + tag + "\n" + new[i:]
    else:
        print(f"  ⚠ {rel} 找不到可安全注入的 </body>（可能落在内联脚本内），已跳过悬浮卡注入")
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
