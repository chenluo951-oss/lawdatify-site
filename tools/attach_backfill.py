#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「文书附件」的正文回填进案例库。

问题（2026-09-17 用户反馈）
-------------------------
「处罚公示下面都带那种 word 或 pdf 的文书附件，这些附件你有没有阅读分析到表格里？」
—— 没有。此前采集只读网页正文，而相当多的公示页是**空壳**：网页上只有标题 +
附件下载链接，处罚事实 / 依据 / 罚款全在 .docx / .pdf 里。结果案例库表格里这些行
出现「处罚事由：见原文」「被处罚主体：—」。

实测（2026-09-17）：
  · 青岛市局「处罚文书送达公告」→ 网页正文 0 字，内容在 3 个 .docx/.xls 里
  · 泸州市局「行政处罚决定书」  → 网页正文只有案由一句，决定书在 .pdf 里（含当事人、
    统一社会信用代码、住所、法定代表人、完整违法事实与依据）

本脚本做三件事
------------
1. 找出「正文很短但页面上挂了附件」的记录（含正文为空的）；
2. 回原页：抓网页正文 + 解析全部附件正文，按主体名把附件与记录配对（一页多案时不串味）；
3. 只更新 fact / fines / laws / attach 四个字段，其余字段不动（避免回归）。

⚠️ **单线程**跑，站与站之间自然有间隔；403/412 是政务站反爬，等冷却即可，不要改解析规则。
⚠️ 同 URL 的多条记录共享一次页面抓取与一份附件缓存，不会重复下载。

用法：
    python tools/attach_backfill.py --dry           # 只看有多少条待回填
    python tools/attach_backfill.py --limit 20      # 先试一小批
    python tools/attach_backfill.py                 # 全跑
    python tools/attach_backfill.py --site qingdao  # 只跑某站（按 URL 关键字匹配）
"""

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from case_attach import attach_text, attach_links, clean_attach_text  # noqa: E402
from case_gate import classify                     # noqa: E402
from case_subject import extract_subject           # noqa: E402
from case_text_clean import clean_fact, is_shell   # noqa: E402
from harvest_cases import curl, parse_case         # noqa: E402

CASES = os.path.join(HERE, "sources", "cases", "cases.json")

# 正文短于这个字数就认为「页面壳」/ 内容不完整，值得回原页看附件
SHORT = 150


def needs_attach(c):
    """要不要回原页。① 正文短；② 正文是壳；③ 正文里没有可判读的处罚信息。"""
    f = (c.get("fact") or "").strip()
    if not f or len(f) < SHORT:
        return True
    if is_shell(f):
        return True
    # 正文虽长但没有「当事人 / 违法事实」要素的，也值得看一眼附件
    if not re.search(r"当事人|被处罚|违法|违反了|依据|罚款|没收|责令", f):
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--site", default="")
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--force", action="store_true",
                    help="忽略现有正文长度，只要页面挂附件就重算（用于覆盖上一次错误回填）")
    a = ap.parse_args()

    data = json.load(open(CASES, encoding="utf-8"))
    cases = data["cases"]
    todo = [c for c in cases
            if classify(c.get("title"), c.get("fact"), c.get("kind"))[0]
            and (a.force or needs_attach(c))
            and (c.get("url") or "").startswith("http")
            and (not a.site or a.site in (c.get("url") or ""))]
    if a.limit:
        todo = todo[:a.limit]
    print(f"案例库 {len(cases)} 条，待回填 {len(todo)} 条")
    if a.dry:
        for c in todo[:15]:
            print(f"  · [{len(c.get('fact') or ''):>3}字] {c.get('agency') or ''} | {(c.get('title') or '')[:52]}")
        return

    by_url = {}
    for c in todo:
        by_url.setdefault(c["url"], []).append(c)

    page_cache, att_cache = {}, {}
    fixed = no_attach = failed = 0
    for i, (url, group) in enumerate(by_url.items(), 1):
        html = page_cache.get(url)
        if html is None:
            html = curl(url)
            page_cache[url] = html or ""
        if not html or len(html) < 400:
            failed += 1
            time.sleep(a.delay * 2)
            continue
        # 该页有没有附件？没有就不必再解析正文（那是 refresh_case_text 的活）
        if not attach_links(html, url):
            no_attach += 1
            if i % 20 == 0:
                print(f"  … {i}/{len(by_url)}  回填 {fixed}  无附件 {no_attach}  失败 {failed}")
            time.sleep(a.delay * 0.4)
            continue

        for c in group:
            title = c.get("title") or ""
            hint = extract_subject(c.get("fact") or "", title)[0] or ""
            if not hint:
                # 主体取不到就用标题前 4 字兜底（附件名常含案由关键词）
                hint = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", title)[:4]
            try:
                att = attach_text(html, url, hint=hint, cache=att_cache)
            except Exception as e:                      # noqa: BLE001
                failed += 1
                print(f"  ! 附件解析异常 {type(e).__name__} {url[:70]}")
                continue
            if att.get("links"):
                c["attach"] = att["links"]
            ex = clean_attach_text(att["text"]) if att.get("text") else ""
            if not ex:
                continue
            # 网页正文一律**从原页重算**（不用库里的 c["fact"]）：库里那份可能已经被
            # 上一次错误回填污染过，拿它拼接只会把错的内容固化下来。
            try:
                page_fact = clean_fact(
                    parse_case(html, title, url, c.get("org") or "").get("fact") or "", title)
            except Exception:                            # noqa: BLE001
                page_fact = ""
            if len(page_fact) >= SHORT and not is_shell(page_fact):
                # 页面正文已经完整（附件多半是「决定书扫描件」一类的冗余件）→ 不动正文
                continue
            c["fact"] = ((page_fact + " " + ex).strip() if page_fact else ex)[:900]
            try:
                parsed = parse_case(html, title, url, c.get("org") or "")
                if not c.get("fines") and parsed.get("fines"):
                    c["fines"] = parsed["fines"]
                if not c.get("laws") and parsed.get("laws"):
                    c["laws"] = parsed["laws"]
            except Exception:                            # noqa: BLE001
                pass
            fixed += 1
        if i % 20 == 0:
            print(f"  … {i}/{len(by_url)}  回填 {fixed}  无附件 {no_attach}  失败 {failed}")
        time.sleep(a.delay)

    data["meta"] = data.get("meta") or {}
    data["meta"]["attach_backfilled"] = time.strftime("%Y-%m-%d")
    json.dump(data, open(CASES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✓ 附件回填：更新 {fixed} 条 / 无附件 {no_attach} 条 / 失败 {failed} 条")
    still = [c for c in data["cases"] if classify(c.get("title"), c.get("fact"), c.get("kind"))[0]
             and not (c.get("fact") or "").strip()]
    print(f"✓ 全库仍无正文：{len(still)} 条")


if __name__ == "__main__":
    main()
