#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把新 harvest 的公众号原文存档自动补进资讯流条目库 sources/news/items.jsonl。

用途：sweep_wx.py 抓取到的存档只落在 sources/wx/<id>.json；要让它们也出现在
「合规资讯」流（而非仅「公众号原文」知识库），需要一条 items.jsonl 条目。
本脚本按 wx_id 去重，只为「还没进资讯流」的存档生成条目（org/date/domain 取自存档，
domain 用词条标题关键词归一到全站 DOMAIN_KEYS）。

幂等：重复运行只会补新增的，不会重复写入。

用法：
  python3 tools/wx_to_feed.py            # 补全部未收录的存档
  python3 tools/wx_to_feed.py --dry      # 只报告将新增几条
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from build_topics import guess_domain, DOMAIN_KEYS  # noqa: E402

WX_DIR = os.path.join(HERE, "sources", "wx")
ITEMS = os.path.join(HERE, "sources", "news", "items.jsonl")
SKIP = {"accounts.json", "replaces.json"}


def existing_wx_ids():
    if not os.path.exists(ITEMS):
        return set()
    ids = set()
    for line in open(ITEMS, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("wx_id"):
            ids.add(d["wx_id"])
    return ids


def main():
    dry = "--dry" in sys.argv
    have = existing_wx_ids()
    n = 0
    for f in sorted(os.listdir(WX_DIR)):
        if f in SKIP or not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(WX_DIR, f), encoding="utf-8"))
        wid = d.get("id")
        if not wid or wid in have:
            continue
        title = (d.get("title") or "").strip()
        if not title:
            continue
        org = (d.get("org") or d.get("account") or "").strip()
        dom = guess_domain(title)
        if dom not in DOMAIN_KEYS:
            dom = "数据合规"  # 兜底，避免被 load_native 丢弃
        entry = {
            "wx_id": wid,
            "title": title,
            "org": org,
            "date": (d.get("pub") or "")[:10],
            "domain": dom,
            "kind": d.get("kind") or "监管动态",
            "risk": "",
            "points": (d.get("body") or "")[:90].replace("\n", " "),
            "analysis": "",
            "url": "",
            "collected": (d.get("fetched") or "")[:10],
        }
        if dry:
            print(f"  将新增：{wid}  {org}  {title[:40]}")
        else:
            with open(ITEMS, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        have.add(wid)
        n += 1
    print(f"{'将新增' if dry else '已新增'} {n} 条公众号来源到资讯流条目库")
    return n


if __name__ == "__main__":
    main()
