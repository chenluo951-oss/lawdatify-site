#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已抓到的公众号原文存档回填到「主题摘要」条目上。

为什么需要它
------------
公众号是封闭生态（搜狗只有带签名的临时链、mp.weixin.qq.com 对脚本一律 200），
官方协会号 / 学术号 / 同行专业号的文章常常一时抓不到原文。此时
tools/collect_news.py 允许先以「来源署名 + 主题要点」入库上站
（该条目带 `pending_raw: true` 与 `src_label`），保证内容当天可见。

原文由每日抓取任务（tools/sweep_wx.py）陆续补齐到 sources/wx/<id>.json。
本脚本按**标题归一化匹配**把 wx_id 回填进这些条目，站点上的来源随即从
「XX 公众号（原文待补）」自动升级为「站内原文存档」，无需人工干预。

幂等：已回填的不再处理；本次匹配不上就留待下次。

用法
----
  python3 tools/wx_backfill_pending.py          # 回填
  python3 tools/wx_backfill_pending.py --dry    # 只报告将回填几条
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = os.path.join(HERE, "sources", "news", "items.jsonl")
WX_DIR = os.path.join(HERE, "sources", "wx")
SKIP = {"accounts.json", "replaces.json"}


def norm(t):
    """标题归一化：只留中日韩文字与字母数字，用于跨来源匹配。"""
    return re.sub(r"[\W_]+", "", (t or "").lower(), flags=re.UNICODE)


def load_archives():
    """标题归一化 → 存档记录（同标题只取一条）。"""
    out = {}
    if not os.path.isdir(WX_DIR):
        return out
    for f in sorted(os.listdir(WX_DIR)):
        if f in SKIP or not f.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(WX_DIR, f), encoding="utf-8"))
        except Exception:
            continue
        k = norm(d.get("title"))
        if k and k not in out:
            out[k] = d
    return out


def main():
    dry = "--dry" in sys.argv
    if not os.path.exists(ITEMS):
        print("· 资讯库不存在，无需回填")
        return 0
    rows = []
    for line in open(ITEMS, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue

    arch = load_archives()
    n = 0
    for r in rows:
        if not r.get("pending_raw") or r.get("wx_id"):
            continue
        d = arch.get(norm(r.get("title")))
        if not d:
            continue
        r["wx_id"] = d.get("id")
        if d.get("org"):
            r["org"] = d["org"]
        r.pop("pending_raw", None)
        r.pop("src_label", None)   # 已升级为站内原文存档，不再需要署名兜底
        n += 1
        print(f"  回填 {d.get('id')}  {(r.get('title') or '')[:46]}")

    if n and not dry:
        with open(ITEMS, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{'将回填' if dry else '已回填'} {n} 条（主题摘要 → 站内原文存档）")
    return n


if __name__ == "__main__":
    main()
