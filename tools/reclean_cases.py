#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对已入库的案例正文做一次就地重清洗（不重新联网）。

## 为什么需要

`case_text_clean.clean_fact()` 是**随时可加规则**的（页面壳五花八门，每次接入新
站点都会发现新噪声）。但已入库的 699 条 `fact` 是旧规则洗出来的，重启采集才会
带上新规则——而重采要跑全站，代价大且受跨站频控限制。

于是这里做一次「零联网」的批量重洗：拿现成的 `fact` 再走一遍 `clean_fact()`。
清洗是幂等的（清完再清结果不变），所以重复跑无害。

## 本次新增的三类噪声（2026-09）

| 噪声 | 命中条数 | 例 |
|---|---|---|
| 字号切换控件 | 176 | `【 中 小 】 --> 9月7日，江苏省苏州市…` |
| 附件名列表 | 143 | `.docx 青岛市…告知书(青黄市监罚告〔2026〕4437-4461号).docx 附件：…` |
| 页脚标识/备案号 | 18 | `政府网站标识码：3702000003 鲁ICP备05041000号` |

用法：
    python tools/reclean_cases.py --dry     # 只看会改动多少条
    python tools/reclean_cases.py           # 实跑（先备份 cases.json）
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from case_text_clean import clean_fact  # noqa: E402

CASES = os.path.join(HERE, "sources", "cases", "cases.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    data = json.load(open(CASES, encoding="utf-8"))
    cases = data.get("cases") or []
    changed = emptied = shrunk = 0
    samples = []
    for c in cases:
        old = c.get("fact") or ""
        if not old:
            continue
        new = clean_fact(old, c.get("title") or "")
        if new == old:
            continue
        changed += 1
        if not new:
            emptied += 1
        elif len(new) < len(old):
            shrunk += 1
        if len(samples) < 12:
            samples.append((old, new))
        if not a.dry:
            c["fact"] = new

    print(f"案例 {len(cases)} 条，需重洗 {changed} 条"
          f"（清空 {emptied} / 缩短 {shrunk}）")
    for old, new in samples:
        print("-" * 74)
        print("  旧:", old[:110])
        print("  新:", (new or "（清空 → 页面无正文）")[:110])

    if a.dry:
        return
    if changed:
        bak = CASES + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(CASES, bak)
        json.dump(data, open(CASES, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"✓ 已写回 {CASES}\n  备份 {os.path.basename(bak)}")
    else:
        print("· 无改动")


if __name__ == "__main__":
    raise SystemExit(main())
