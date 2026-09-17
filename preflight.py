#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py —— 站点构建前的护栏自检（务必排在任何 build_* 之前）

背景（2026-09-14 实战教训）
    1. `present_files` 等预览器会给页面 DOM 打上 `data-page-node-id="..."` 元素锚点。
       这是**内部工具痕迹**，曾随一次提交把 about.html 的 38 处发布到线上。
    2. 成品页面扫描不足以发现「官网首页根域名」：来源 URL 在数据模块里，
       同一条 URL 还可能只以纯文本形式出现在页面中（不是 href）。

本脚本共五项，全部只读 + 就地清理：
    A. 清除所有 HTML 的 `data-page-node-id` 属性（就地改写，打印命中清单）
    B. 扫描官网首页根域名链接并报告（默认放行 beian.cac.gov.cn）
    C. 外链性质：栏目页 / 首页（非深链，只报告不阻断）
    D. SVG 内混入 HTML 内联标签（阻断 —— 解析器会跳出 SVG 上下文）
    E. 逐页提取内联 <script> 用 node --check 校验语法（阻断 —— 防「整页 JS 被截断」）

用法
    python3 preflight.py            # 清理 + 报告；有根域名时以退出码 1 结束
    python3 preflight.py --quiet    # 只清理，不打印明细
    python3 preflight.py --check    # 只检查不修改
"""
import argparse
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

NODE_ATTR = re.compile(r'\s+data-page-node-id="[^"]*"')

# 官网首页根域名：http(s)://<主机>/ 或 /index.html，无任何更深路径
ROOT_HREF = re.compile(
    r'href="(https?://(?:www\.)?[a-z0-9\-\.]+\.(?:gov\.cn|com\.cn|cn|com|org|net)/?)"',
    re.I,
)
ROOT_ANY = re.compile(
    r'(?<![\w/])(https?://(?:www\.)?[a-z0-9\-\.]+\.(?:gov\.cn|com\.cn|cn|com|org|net)/)(?![\w\-/])',
    re.I,
)
ROOT_ALLOW = ("beian.cac.gov.cn",)   # 算法备案查询系统，用户明确允许

SKIP_DIRS = {".git", "_private", "node_modules", ".cache", "_quarantine", "sources"}


def html_files():
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".html", ".htm")):
                yield os.path.join(root, f)


# SVG 的 <text> 里**不能**用 HTML 内联标签。按 HTML5「foreign content」规则，
# 解析器遇到 <b>/<i>/<span>/<em>/<strong>… 会直接弹出 SVG 上下文，
# 之后剩下的 <text>/<rect> 全被当成普通 HTML 元素 —— 图示会被撑高、文字溢出、
# 连 <figcaption> 都会被塞进一个游离的 <rect> 里。
# （2026-09-17 实测：analysis/food-label.html 图 1 因此从 345px 变成 654px。）
SVG_BLOCK = re.compile(r"<svg\b.*?</svg>", re.S | re.I)
SVG_HTML_TAG = re.compile(r"</?(b|i|em|strong|span|small|u|sup|sub|code|p|div)\b", re.I)


def scan_svg_html_tags():
    hits = []
    for p in html_files():
        t = open(p, encoding="utf-8", errors="ignore").read()
        n, sample = 0, ""
        for m in SVG_BLOCK.finditer(t):
            for tag in SVG_HTML_TAG.finditer(m.group(0)):
                n += 1
                if not sample:
                    i = max(0, tag.start() - 40)
                    sample = m.group(0)[i:tag.end() + 30].replace("\n", " ")
        if n:
            hits.append((os.path.relpath(p, HERE), n, sample))
    return hits


def strip_node_ids(check):
    hits = []
    for p in html_files():
        t = open(p, encoding="utf-8", errors="ignore").read()
        n = len(NODE_ATTR.findall(t))
        if not n:
            continue
        hits.append((os.path.relpath(p, HERE), n))
        if not check:
            open(p, "w", encoding="utf-8").write(NODE_ATTR.sub("", t))
    return hits


def scan_roots():
    href_hits, text_hits = {}, {}
    for p in html_files():
        rel = os.path.relpath(p, HERE)
        t = open(p, encoding="utf-8", errors="ignore").read()
        for u in ROOT_HREF.findall(t):
            if any(a in u for a in ROOT_ALLOW):
                continue
            href_hits.setdefault(u, []).append(rel)
        for u in ROOT_ANY.findall(t):
            if any(a in u for a in ROOT_ALLOW):
                continue
            text_hits.setdefault(u, []).append(rel)
    # href 是硬违规；纯文本出现多为数据模块里的来源串，同样需替换
    return href_hits, text_hits


def scan_depth():
    """C. 外链性质：区分「直达具体条目」与「机构栏目页/首页」。

    读者反馈里最多的一类「链接有问题」不是 404，而是链接落在机构的栏目页上——
    点得开，但翻不到对应条目。这里在构建前把清单打出来，便于逐条回溯深链。
    """
    try:
        sys.path.insert(0, HERE)
        from sources_tier import link_depth, tier_of
    except Exception:
        return None
    bad = {}
    for p in html_files():
        rel = os.path.relpath(p, HERE)
        t = open(p, encoding="utf-8", errors="ignore").read()
        for u in set(re.findall(r'href="(https?://[^"#]+)"', t)):
            d = link_depth(u)
            if d != "deep":
                bad.setdefault(u, {"depth": d, "tier": tier_of(u), "pages": []})
                bad[u]["pages"].append(rel)
    return bad


def scan_inline_js():
    """页内联脚本语法自检（委托 tools/js_syntax_check.py，用 node --check）。

    为什么放进门禁：2026-09-17 原文库 / 合规审计两页的整段 JS 被
    unify_chrome 的「插在第一个 </body> 前」误伤（第一个 </body> 落在 JS 字符串里），
    页面 HTTP 200、HTML 结构完整、A—D 四项全过，但脚本从中间断裂 ——
    表现是「列表空白、点按钮没反应」。这类故障只有真解析一遍 JS 才看得见。
    返回 [(页面, 错误块数, 说明)]；工具缺失或 node 不可用时返回 None（跳过，不阻断）。
    """
    tool = os.path.join(HERE, "tools", "js_syntax_check.py")
    if not os.path.exists(tool):
        return None
    try:
        spec = importlib.util.spec_from_file_location("jsck", tool)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    except Exception:
        return None
    if not os.path.exists(m.NODE):
        return None
    try:
        rels = m.pages()
    except Exception:
        return None
    out = []
    for rel in rels:
        r = m.check_page(rel)
        if not r:
            continue
        _blocks, bad = r
        if bad:
            out.append((rel, len(bad), bad[0][2][:110]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--check", action="store_true", help="只检查不修改")
    a = ap.parse_args()

    exit_code = 0

    print("== A. 编辑器属性 data-page-node-id ==")
    if a.check:
        print("   （--check 模式，不修改）")
    hits = strip_node_ids(a.check)
    if hits:
        for rel, n in hits:
            print(f"   {'发现' if a.check else '已清除'} {rel} ×{n}")
    else:
        print("   0 ✓")

    print("== B. 官网首页根域名 ==")
    href_hits, text_hits = scan_roots()
    if href_hits:
        exit_code = 1
        print("   ✗ href 硬违规：")
        for u, ps in sorted(href_hits.items()):
            print(f"     {u}  ← {sorted(set(ps))}")
    if text_hits:
        print("   △ 以文本出现的来源串（同样应换成具体深链）：")
        for u, ps in sorted(text_hits.items()):
            print(f"     {u}  ← {sorted(set(ps))[:3]}（{len(ps)} 处）")
    if not href_hits and not text_hits:
        print("   0 ✓（beian.cac.gov.cn 为允许项）")

    print("== C. 外链性质（栏目页 / 首页） ==")
    bad = scan_depth()
    if bad is None:
        print("   （sources_tier 不可用，跳过）")
    elif not bad:
        print("   全部直达具体内容页 ✓")
    else:
        for u, v in sorted(bad.items()):
            mark = "△" if v["depth"] == "list" else "○"
            print(f'   {mark} [{v["depth"]}] {u[:100]}')
            print(f'       ← {sorted(set(v["pages"]))[:2]}')
        print(f"   合计 {len(bad)} 条非深链（不阻断构建，建议逐条回溯官方具体页）")

    print("== D. SVG 内混入 HTML 内联标签 ==")
    hits = scan_svg_html_tags()
    if not hits:
        print("   0 ✓")
    else:
        exit_code = 1
        print("   ✗ 阻断：HTML 解析器遇到 SVG 里的 <b>/<i>/<span> 会**跳出 SVG 上下文**，")
        print("     后半段图示会被当成普通 HTML 解析 —— 表现为图示变高、内容溢出、图注被吞。")
        print("     改法：写成 <tspan font-weight=\"700\">…</tspan> / <tspan font-style=\"italic\">…</tspan>。")
        for p, n, sample in hits:
            print(f'     {p}  {n} 处  例：{sample}')

    print("== E. 页内联脚本语法（node --check） ==")
    print("   （防的是「整页 JS 被截断」这类致命错误：页面 200、结构正常、A—D 全过，")
    print("     但脚本从中间断了，列表空白、按钮全没反应）")
    js_bad = scan_inline_js()
    if js_bad is None:
        print("   （node 不可用或检测脚本缺失，跳过）")
    elif not js_bad:
        print("   0 ✓")
    else:
        exit_code = 1
        print("   ✗ 阻断：")
        for p, n, msg in js_bad:
            print(f"     {p}  {n} 处：{msg}")

    print("== 完成 ==")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
