#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「法条竞合与抗辩」挂到最相关的合规义务上。

匹配原则：只认义务标题（t 字段），不认同描述文本——描述里出现「食品」
「个人信息」太普遍，按描述匹配会把 220 条义务里的 150 条都挂上，反而失去指向性。
标题级匹配后仍逐条打印，便于人工复核。

用法：
    python3 tools/link_duties_compete.py            # 写入 duties.json
    python3 tools/link_duties_compete.py --dry      # 只打印，不写
"""
import os
import re
import sys
import json
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DUTIES = os.path.join(ROOT, "sources", "standards", "duties.json")
COMPETE = os.path.join(ROOT, "sources", "standards", "compete_law.json")

RULES = [
    ("false-ad", re.compile(r"宣传|广告|宣称|广告标识")),
    ("absolute-terms", re.compile(r"绝对化")),
    ("price-fraud", re.compile(r"价格|标价|促销|折扣|划线价|原价|续费")),
    ("food-liability", re.compile(r"保质期|进货查验|索证索票|临期|召回|快检|温控")),
    ("pi-liability", re.compile(r"最小必要|单独同意|告知同意|注销|删除|撤回")),
]


def main():
    dry = "--dry" in sys.argv
    duties = json.load(open(DUTIES, encoding="utf-8"))
    keys = {x["key"] for x in json.load(open(COMPETE, encoding="utf-8"))["items"]}
    stat = collections.Counter()
    n = 0
    for cat in duties["categories"]:
        for sc in cat["scenes"]:
            for du in sc["duties"]:
                ks = [k for k, rx in RULES if k in keys and rx.search(du.get("t", ""))]
                if ks:
                    n += 1
                    for k in ks:
                        stat[k] += 1
                    if not dry:
                        du["compete"] = ks
                elif not dry:
                    du.pop("compete", None)

    if not dry:
        duties.setdefault("_meta", {})["compete_note"] = (
            "compete 字段为「法条竞合与抗辩」分组键，定义见 sources/standards/compete_law.json")
        json.dump(duties, open(DUTIES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    total = sum(len(s["duties"]) for c in duties["categories"] for s in c["scenes"])
    print("义务 %d 条，其中 %d 条挂载了竞合分析%s" % (total, n, "（dry-run 未写入）" if dry else ""))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-16s %d 条" % (k, v))


if __name__ == "__main__":
    main()
