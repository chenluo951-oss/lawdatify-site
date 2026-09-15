#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prune_low_value.py —— 资讯条目「每周清理」执行器（**已停用 · 仅作历史留档**）。

⛔ 停用说明（2026-09-15，用户决定）
----------------------------------
用户原话：「**如果不占用负载，那就别删了**」。实测资讯 HTML 有 gzip、线上实际传输量很小
（台账页 2.04MB → 257KB），**资讯条目不占负载**；体积 9 成来自 `kb/std/` 的标准 PDF。
故**不再清理任何内容**，本脚本**不要执行**（每周日的清理自动化任务已删除）。
当前 `pruned` 标记数为 **0**，`sources/news/pruned_blacklist.json` 不存在，
全站无一条内容因清理机制缺席——即本次撤销**无需回滚**。

以后若要动容量，方向是「大件 PDF 外部化 / 按需加载」，**不是删内容**。

以下为停用前的原始说明（留档备查）
----------------------------------
一句话：把「行业政策性、与合规关联不大」的资讯条目**从站点内容里摘掉**，
而「监管专项 / 处罚通报 / 司法案例 / 专业分析 / 法律法规 / 标准文件 / 指引指南」
这类合规导向、知识积累的内容**一条都不动**。

判定口径全部在 `prune_policy.py`（单一事实来源），本脚本只负责落盘与报告。

安全性
------
- **不物理删除**：只在 `sources/news/items.jsonl` 对应行加 `pruned: true` + `prune_reason`
  + `pruned_at`，随时 `--restore-all` 一键回滚。
- **不碰依据类内容**：法律法规 / 标准 / 指引指南存放在 sources/standards、kb/std、
  sources/library、kb/wx，本脚本完全不涉及。
- **拿不准就保留**（`prune_policy.classify`）：必须命中行业政策性信号且完全没有合规锚点。
- **新条目保护期**（默认 30 天）：近期入库的一律不动。
- 清理结果同时写入 `sources/news/pruned_blacklist.json`，采集器据此拒收，防止次日复活。

用法
----
    python3 tools/prune_low_value.py                    # 预览（只报告，不改任何文件）
    python3 tools/prune_low_value.py --apply            # 执行清理（打标记 + 写黑名单）
    python3 tools/prune_low_value.py --apply --min-age-days 14
    python3 tools/prune_low_value.py --list             # 看当前已清理条目
    python3 tools/prune_low_value.py --restore "论坛"    # 按标题片段恢复
    python3 tools/prune_low_value.py --restore-all      # 全部恢复（清空黑名单）
"""
import argparse
import collections
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import prune_policy as PP  # noqa: E402

STORE = os.path.join(ROOT, "sources", "news", "items.jsonl")


def load_rows():
    if not os.path.exists(STORE):
        return []
    out = []
    with open(STORE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def save_rows(rows):
    """整表回写（保持顺序与全部字段；仅受影响的行多出 pruned 相关字段）。"""
    with open(STORE, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def do_restore(pat="", all_=False):
    rows = load_rows()
    bl = PP.load_blacklist()
    n = 0
    for r in rows:
        if not r.get("pruned"):
            continue
        t = r.get("title") or ""
        if all_ or (pat and pat in t):
            r.pop("pruned", None)
            r.pop("prune_reason", None)
            r.pop("pruned_at", None)
            bl["titles"].pop(PP.norm_title(t), None)
            n += 1
    save_rows(rows)
    PP.save_blacklist(bl)
    print(f"已恢复 {n} 条（黑名单剩余 {len(bl['titles'])} 条）")


def do_list():
    rows = load_rows()
    pr = [r for r in rows if r.get("pruned")]
    if not pr:
        print("当前无已清理条目。")
        return
    print(f"当前已清理 {len(pr)} 条：")
    for r in pr:
        print(f"  [{r.get('domain','?')}] {r.get('date','?')} {r.get('title','')[:64]}")
        print(f"        原因：{r.get('prune_reason','')}  （{r.get('pruned_at','')}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行清理（缺省只预览）")
    ap.add_argument("--list", action="store_true", help="列出当前已清理条目")
    ap.add_argument("--restore", default="", help="按标题片段恢复")
    ap.add_argument("--restore-all", action="store_true", help="全部恢复")
    ap.add_argument("--min-age-days", type=int, default=PP.DEFAULT_MIN_AGE_DAYS,
                    help=f"新条目保护期（默认 {PP.DEFAULT_MIN_AGE_DAYS} 天）")
    ap.add_argument("--show", type=int, default=25, help="预览时最多打印多少条明细（默认 25）")
    a = ap.parse_args()

    if a.restore_all:
        do_restore(all_=True)
        return
    if a.restore:
        do_restore(a.restore)
        return
    if a.list:
        do_list()
        return

    rows = load_rows()
    today = date.today()
    decisions = []
    for r in rows:
        action, reason, score = PP.classify(r, today=today, min_age_days=a.min_age_days)
        decisions.append((r, action, reason, score))

    prune = [(r, reason) for r, act, reason, _ in decisions if act == "prune"]
    keep = [(r, reason) for r, act, reason, _ in decisions if act == "keep"]

    print(f"资讯条目 {len(rows)} 条 → 保留 {len(keep)} / 命中清理 {len(prune)}"
          f"（保护期 {a.min_age_days} 天）\n")
    print("── 保留原因分布 ──")
    for reason, c in collections.Counter(
            reason if len(reason) <= 34 else reason[:34] + "…"
            for _, reason in keep).most_common():
        print(f"  {c:>4}  {reason}")

    if prune:
        print("\n── 命中清理（行业政策性、无合规锚点）──")
        for r, reason in prune[:max(0, a.show)]:
            print(f"  [{r.get('domain','?')}] {r.get('date','?')} {(r.get('title') or '')[:58]}")
            print(f"        {reason}")
        if len(prune) > a.show:
            print(f"  …另有 {len(prune) - a.show} 条，用 --show N 调整")
    else:
        print("\n本次无条目命中清理规则（说明规则保守，或内容均属合规导向）。")

    applied = 0
    if prune and a.apply:
        bl = PP.load_blacklist()
        for r, reason in prune:
            r["pruned"] = True
            r["prune_reason"] = reason
            r["pruned_at"] = today.isoformat()
            bl["titles"][PP.norm_title(r.get("title"))] = {
                "title": r.get("title", ""), "url": r.get("url", ""),
                "domain": r.get("domain", ""), "reason": reason,
                "pruned_at": today.isoformat(),
            }
            applied += 1
        save_rows(rows)
        PP.save_blacklist(bl)
        print(f"\n已清理 {applied} 条（打标记，未删数据）；黑名单共 {len(bl['titles'])} 条。"
              f"\n回滚：python3 tools/prune_low_value.py --restore-all")
    elif prune:
        print("\n（预览模式，未改动任何文件；加 --apply 生效）")

    print("__SUMMARY__" + json.dumps({
        "total": len(rows), "keep": len(keep), "prune": len(prune), "applied": applied,
        "min_age_days": a.min_age_days,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
