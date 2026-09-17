#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重取被「页面壳」污染 / 被旧上限截断的案例正文，并重算「处罚事由」与「处罚」。

## 背景一：页面壳（2026-09-16）

`parse_case()` 的老版本用 `re.sub(r"来源：.{0,40}", " ")` 清「信息来源」标签。
`.{0,40}` 贪婪且不限字符类，把标签后面的**正文**一起吃掉：

    信息来源：市场监管总局 市场监管部门针对电动自行车生产、销售领域违法违 → （没了）

实测 376 条同时带两种伤：① 面包屑 + 元信息栏原样留在摘要里；② 正文被吃掉几十字。

## 背景二：260 字旧上限（2026-09-17）

旧上限 260 字让 334 条记录写满即止。后果：
- 案例库新加的「被处罚主体」字段取不到值（企业名常在 260 字之后）；
- 用户点名的「处罚事由」列里，汇编类记录显示的是**通稿导语**（行动背景），
  因为案情在被截掉的后半段。

## 背景三：事由与处罚要**从全文**抽，不能只从 900 字里抽（2026-09-17）

「罚款/吊销营业执照」这类结论写在决定书**末尾**（`…给予当事人以下行政处罚：处…罚款`），
900 字的正文窗口根本到不了那里。所以本脚本在重取时**保留全文**到本机缓存
（`_qa/case_full.jsonl`，不入仓），并用全文重算：

    c["reason"] = 违法事实（为什么处罚）
    c["pen"]    = 处罚种类 + 幅度（罚款 / 吊销营业执照 / 没收违法所得 / 停业整顿…）

页面侧直接用这两个字段，`fact` 仍只用于「被处罚主体」与兜底显示。

用法：
    python tools/refresh_case_text.py --dry             # 只看命中多少条
    python tools/refresh_case_text.py                   # 实跑（联网重取）
    python tools/refresh_case_text.py --limit 50        # 先试一小批
    python tools/refresh_case_text.py --re-extract      # 零联网：按本机全文缓存重算事由/处罚
"""

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from case_reason import derive_fields                            # noqa: E402
from case_text_clean import clean_fact, is_shell                 # noqa: E402
from harvest_cases import _dedupe_title, curl, parse_case, textify  # noqa: E402

CASES = os.path.join(HERE, "sources", "cases", "cases.json")
CACHE = os.path.join(HERE, "_qa", "case_full.jsonl")
MAX_REASON = 1500

# 旧解析留下的「断裂」痕迹：清掉标签后残留的孤立词，或正文被吃掉后的拼接
SCARRED = re.compile(
    r"你的位置|您现在的位置|当前位置\s*[:：]|发布时间\s*[:：]|信息来源\s*[:：]|"
    r"第\s*\d+\s*页\s*[,，]?\s*共\s*\d+\s*页"
)


def suspects(cases):
    """需要重取的记录：带页面壳、正文被吃掉，或**撞上 260 字旧上限被截断**。

    第三条是「主体 / 事由取不到」的根因：撞顶的记录结尾不是句末标点。
    """
    from case_subject import extract_subject
    out = []
    for c in cases:
        if c.get("reason_done"):
            continue
        f = c.get("fact") or ""
        if SCARRED.search(f):
            out.append(c)
            continue
        if re.search(r"信息\s*[、，,。]|\s信息\s+[\u4e00-\u9fa5]{1,3}(?:部门|局|委)", f):
            out.append(c)
            continue
        if len(f) >= 240 and not re.search(r"[。！？；：”\"）)]$", f):
            out.append(c)
            continue
        if f and not extract_subject(f, c.get("title"))[0]:
            out.append(c)
            continue
        # 事由/处罚字段还没算过 → 也要过一遍（拿全文重算）
        if not c.get("reason") and f:
            out.append(c)
    return out


def _derive(c, full, fines):
    """从**全文**算事由与处罚，写回记录（口径统一在 case_reason.derive_fields）。"""
    if fines:
        c["fines"] = fines
    derive_fields(c, full)
    r = {"mode": c.get("reason_mode") or "", "n": c.get("reason_n") or 0,
         "text": c.get("reason") or ""}
    p = {"text": c.get("pen") or ""}
    return r, p


def _load_cache():
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = json.loads(ln)
                except Exception:                       # noqa: BLE001
                    continue
                if o.get("url"):
                    cache[o["url"]] = o.get("full") or ""
    return cache


def _dump_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for u, full in cache.items():
            f.write(json.dumps({"url": u, "full": full}, ensure_ascii=False) + "\n")
    os.replace(tmp, CACHE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--re-extract", action="store_true",
                    help="零联网：按本机全文缓存重算事由/处罚（改完抽取规则用这个）")
    a = ap.parse_args()

    data = json.load(open(CASES, encoding="utf-8"))
    cases = data["cases"]

    # ── 零联网重算 ────────────────────────────────────────────────
    if a.re_extract:
        cache = _load_cache()
        print(f"本机全文缓存 {len(cache)} 条")
        n = 0
        from collections import Counter
        mc = Counter()
        for c in cases:
            full = cache.get(c.get("url") or "")
            if not full:
                continue
            r, _p = _derive(c, full, c.get("fines"))
            mc[r["mode"]] += 1
            n += 1
        json.dump(data, open(CASES, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"✓ 按全文重算 {n} 条　模式分布 {mc.most_common()}")
        return

    todo = suspects(cases)
    if a.limit:
        todo = todo[:a.limit]
    print(f"案例库 {len(cases)} 条，需重取 {len(todo)} 条")
    if a.dry:
        for c in todo[:12]:
            print("  ·", c.get("org"), "|", (c.get("fact") or "")[:70])
        return

    cache = _load_cache()
    fixed = failed = shell_left = 0
    done_rows = 0
    for i, c in enumerate(todo, 1):
        url = c.get("url") or ""
        if not url.startswith("http"):
            failed += 1
            continue
        html = curl(url)
        if not html or len(html) < 400:
            failed += 1
            time.sleep(a.delay * 2)
            continue
        old = c.get("fact") or ""
        title = c.get("title") or ""
        try:
            new = parse_case(html, title, url, c.get("org") or "")
        except Exception as e:                       # noqa: BLE001
            failed += 1
            print(f"  ! {i} 解析异常 {e}")
            continue
        nf = new.get("fact") or ""
        # 只在「变干净了」时替换：不是更短就更好，得先确认壳没了
        if nf and not is_shell(nf) and len(nf) >= 30:
            c["fact"] = nf[:900]
            if not c.get("fines") and new.get("fines"):
                c["fines"] = new["fines"]
            if not c.get("laws") and new.get("laws"):
                c["laws"] = new["laws"]
            fixed += 1
        else:
            cl = clean_fact(old, title)
            if cl and cl != old:
                c["fact"] = cl[:900]
                fixed += 1
            else:
                shell_left += 1

        # ── 全文（不截断）→ 本机缓存 → 重算事由/处罚 ───────────────
        try:
            full = clean_fact(_dedupe_title(textify(html), title), title)
        except Exception:                            # noqa: BLE001
            full = ""
        if len(full) < 30:
            full = c.get("fact") or ""
        if full:
            cache[url] = full[:12000]
            _derive(c, full, c.get("fines"))
            done_rows += 1
        else:
            # 页面本身没正文（App 通报等）→ 也要打「已办」标，否则每轮都来重取一次
            c["reason_done"] = 1

        if i % 25 == 0:
            print(f"  … {i}/{len(todo)}  修文本 {fixed}  重算 {done_rows}  失败 {failed}",
                  flush=True)
            # ⚠️ 每 25 条就落一次盘：长跑会被环境回收（实测跑死过一次，
            # 全部结果丢失）。落盘后重跑会自动跳过已完成的记录。
            _dump_cache(cache)
            json.dump(data, open(CASES, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        time.sleep(a.delay)

    data["meta"] = data.get("meta") or {}
    data["meta"]["text_cleaned"] = "2026-09-17"
    data["meta"]["reason_extracted"] = len(cache)
    json.dump(data, open(CASES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    _dump_cache(cache)
    print(f"\n✓ 重取完成：修文本 {fixed}，重算事由/处罚 {done_rows}，失败 {failed}，"
          f"仍带壳 {shell_left}")
    print(f"✓ 本机全文缓存：{len(cache)} 条 → {os.path.relpath(CACHE, HERE)}")
    left = [c for c in data["cases"] if is_shell(c.get("fact") or "")]
    print(f"✓ 全库仍带页面壳：{len(left)} / {len(data['cases'])}")
    for c in left[:8]:
        print("   ·", c.get("org"), "|", (c.get("fact") or "")[:80])


if __name__ == "__main__":
    main()
