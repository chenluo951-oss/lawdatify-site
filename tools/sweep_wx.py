#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sweep_wx.py —— 近三个月公众号官方来源「逐来源」检索补齐（限流版）。

背景
----
用户要求：把近三个月（2026-06-14 ~ 今天）**所有相关监管机关官方公众号**发布的
合规原文都检索一遍，补足网站内容。来源是「只在公众号发布、PC 官网无对应页」的
执法通报 / 典型案例 / 专项行动 / App 通报等，属官方原文（一等来源）。

与 fetch_wechat.py 的关系
--------------------------
本脚本只是**编排器**：复用 fetch_wechat 的检索/取链/解析/落盘函数，
在其之上加三件事（fetch_wechat 本身没有的）：
  ① 按合规六大方向给出「来源清单」(QUERIES)，每个查询对应一类监管机关；
  ② 日期闸门：只收发布时间 >= CUTOFF（近三个月）的原文；
  ③ 限流 + 反爬自保护：串行、随机休眠、命中 antispider 即长休眠后跳到下一条，
     绝不重试轰炸（否则连 IP 一起封，反而补不齐）。

落盘
----
sources/wx/<id>.json（与 fetch_wechat 同格式）；org 字段按 QUERIES 的 org_hint 写入，
build_wx_archive.py 渲染时即显示为发布机关。

限流原则（来自 wechat-official-source-harvest skill 的踩坑）
-------------------------------------------------------
  · 搜狗微信有反爬：一次任务别超过十来次检索；命中验证码/antispider 立刻停。
  · 只走 curl（fetch_wechat 已封装）；本机 urllib 会被沙箱代理拦。
  · 临时链有效期短，取链失败重跑一次即可，不要连环重试。

用法
----
  python3 tools/sweep_wx.py              # 跑全部来源（限流，约 15~40 分钟）
  python3 tools/sweep_wx.py --dry        # 只打印将检索的来源清单，不实际抓取
  python3 tools/sweep_wx.py --max-per 1  # 每个来源只取最新 1 篇
"""
import os
import re
import sys
import time
import random
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import fetch_wechat as fw   # 复用检索/取链/解析/落盘

CST = timezone(timedelta(hours=8))
CUTOFF = datetime(2026, 6, 14, tzinfo=CST).timestamp()   # 近三个月起算

# 合规六大方向 → 核心监管机关公众号来源。每个 (查询词, 发布机关名)。
# org 写进存档 JSON，build_wx_archive 渲染时即显示为机构；空字符串则交由账号名推断。
QUERIES = [
    # 数据 / 个人信息 / 算法 / AI（网信）
    ("网信中国 个人信息保护",            "中央网信办"),
    ("网信中国 算法 治理",              "中央网信办"),
    ("网信浙江 个人信息",              "浙江省网信办"),
    ("网信广东 数据安全",              "广东省网信办"),
    # 食安 / 价格 / 广告 / 反法（市场监管）
    ("市场监管 食品安全 典型案例",       "市场监管总局"),
    ("市场监管 价格 违法 告诫",          "市场监管总局"),
    ("市场监管 反不正当竞争 案例",       "市场监管总局"),
    ("食品安全 行政处罚 典型案例",       ""),
    # 网安 / 数据安全（公安）
    ("公安网安 数据安全",               "公安部网络安全保卫局"),
    ("网络安全 监督检查 典型案例",       "公安部网络安全保卫局"),
    # App / 个人信息（工信部 / 通管局）
    ("工信部 个人信息 App",            "工业和信息化部"),
    ("通信管理局 App 通报",            ""),
    # 消保 / 广告 / 司法
    ("市场监管 广告 违法 案例",          "市场监管总局"),
    ("消费者协会 典型案例",            "中国消费者协会"),
    ("法院 数据 典型案例",             "人民法院"),
    ("检察院 个人信息 典型案例",         "人民检察院"),
]

MAX_PER_QUERY = int(os.environ.get("WX_MAX_PER", "2"))
SLEEP_BETWEEN_SEARCH = (11, 19)     # 两次检索之间随机休眠（秒）
SLEEP_BETWEEN_GRAB = (6, 11)       # 同一来源取多篇之间
ANTI_SPIDER_SLEEP = (90, 150)       # 命中反爬后长休眠


def pick_recent(rows, max_n):
    """从候选里挑近三个月、且去重标题的条目。"""
    out, seen = [], set()
    for r in rows:
        if not r.get("ts"):
            continue
        if r["ts"] < CUTOFF:
            continue
        key = (r.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= max_n:
            break
    return out


def archive(row, query, org_hint):
    body_html, target, err = fw.resolve(row["relay"])
    if err:
        return None, f"取链失败：{err}"
    art = fw.parse_article(body_html)
    if not art["body"]:
        return None, "未解析到正文（临时链可能已过期，重跑一次即可）"
    rec_account = row.get("account") or art.get("author") or ""
    fw.record_account(art, target, rec_account)
    path, rec = fw.save_article(art, target, query=query, account_hint=rec_account)
    # 写发布机关：org_hint 优先；空则交给 build_wx_archive 按账号名推断
    if org_hint:
        d = __import__("json").load(open(path, encoding="utf-8"))
        d["org"] = org_hint
        __import__("json").dump(d, open(path, "w", encoding="utf-8"),
                                ensure_ascii=False, indent=1)
    pub = rec.get("pub") or "?"
    return rec.get("id"), f"{pub} / {rec.get('chars')} 字 / {rec.get('title','')[:40]}"


def main():
    dry = "--dry" in sys.argv
    if "--max-per" in sys.argv:
        i = sys.argv.index("--max-per")
        global MAX_PER_QUERY
        MAX_PER_QUERY = max(1, int(sys.argv[i + 1]))

    print(f"近三个月公众号来源检索（限流版）  CUTOFF={datetime.fromtimestamp(CUTOFF,CST):%Y-%m-%d}  "
          f"来源数={len(QUERIES)}  每来源最多 {MAX_PER_QUERY} 篇\n")
    if dry:
        for q, o in QUERIES:
            print(f"  · {o or '（账号名推断）':<14}  {q}")
        return

    archived, skipped, antispider = 0, 0, 0
    for qi, (query, org) in enumerate(QUERIES, 1):
        print(f"[{qi}/{len(QUERIES)}] 检索「{query}」…", flush=True)
        rows, err = fw.sogou_search(query)
        if err:
            print(f"    ⚠ 反爬/异常：{err[:60]} —— 长休眠后跳下一条")
            antispider += 1
            time.sleep(random.uniform(*ANTI_SPIDER_SLEEP))
            continue
        recent = pick_recent(rows, MAX_PER_QUERY)
        if not recent:
            print(f"    近三个月无候选（共 {len(rows)} 条，均早于 CUTOFF 或无日期）")
            skipped += 1
            time.sleep(random.uniform(*SLEEP_BETWEEN_SEARCH))
            continue
        print(f"    候选 {len(rows)} 条 → 近三个月 {len(recent)} 篇可存档")
        for row in recent:
            aid, msg = archive(row, query, org)
            if aid:
                archived += 1
                print(f"    ✓ #{aid}  {msg}")
            else:
                print(f"    · 跳过：{msg}")
            time.sleep(random.uniform(*SLEEP_BETWEEN_GRAB))
        time.sleep(random.uniform(*SLEEP_BETWEEN_SEARCH))

    print(f"\n检索完成：存档 {archived} 篇 / 无近三月候选 {skipped} 个来源 / 命中反爬 {antispider} 次")
    print("下一步：python3 tools/build_wx_archive.py  →  daily_build  →  push_via_api")


if __name__ == "__main__":
    main()
