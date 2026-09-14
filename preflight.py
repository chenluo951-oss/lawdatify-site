#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py —— 站点构建前的护栏自检（务必排在任何 build_* 之前）

背景（2026-09-14 实战教训）
    1. `present_files` 等预览器会给页面 DOM 打上 `data-page-node-id="..."` 元素锚点。
       这是**内部工具痕迹**，曾随一次提交把 about.html 的 38 处发布到线上。
    2. 成品页面扫描不足以发现「官网首页根域名」：来源 URL 在数据模块里，
       同一条 URL 还可能只以纯文本形式出现在页面中（不是 href）。

本脚本做两件事，都只读 + 就地清理：
    A. 清除所有 HTML 的 `data-page-node-id` 属性（就地改写，打印命中清单）
    B. 扫描官网首页根域名链接并报告（默认放行 beian.cac.gov.cn）

用法
    python3 preflight.py            # 清理 + 报告；有根域名时以退出码 1 结束
    python3 preflight.py --quiet    # 只清理，不打印明细
    python3 preflight.py --check    # 只检查不修改
"""
import argparse
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

    print("== 完成 ==")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
