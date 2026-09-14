#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sweep_wx.py —— 公众号官方来源「逐来源」检索补齐（限流 + 反爬绕过 + 攒够即发布）。

目标：把监管机关官方公众号（只在公众号发布、PC 官网无对应页）的合规原文持续补齐到站
点。用户初步目标 1000 篇；微信生态有反爬，单靠一次任务拿不到，故设计为：
  · 可续跑：重复运行只补新文章（按标题去重、同 id 覆盖）；
  · 低频串行 + 反爬自保护（fetch_wechat 已加 UA 轮换 / cookie 预热 / 有限重试）；
  · 攒够 PUBLISH_EVERY（默认 100）篇新存档后，自动重建全站并推送上线。

反爬绕过（在 fetch_wechat 内）：每次检索前 GET 搜狗首页刷新 SNUID cookie、UA 池轮换、
命中 antispider 时刷新 cookie 并退避后有限重试（绝不连环轰炸）。仍被挡的方向会跳过，
分时段再跑或手动补即可。

用法
----
  python3 tools/sweep_wx.py                 # 跑全部来源（限流，约 15~50 分钟），攒够即发布
  python3 tools/sweep_wx.py --dry           # 只打印来源清单
  python3 tools/sweep_wx.py --max-per 3     # 每来源最多取 3 篇
  python3 tools/sweep_wx.py --no-publish    # 只 harvest，不触发重建/推送（测试用）
"""
import os
import re
import sys
import time
import random
import subprocess
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import fetch_wechat as fw   # 检索/取链/解析/落盘 + 反爬绕过

CST = timezone(timedelta(hours=8))
CUTOFF = datetime(2026, 6, 14, tzinfo=CST).timestamp()   # 近三个月起算
WX_DIR = os.path.join(HERE, "sources", "wx")
PUBLISH_STATE = os.path.join(WX_DIR, ".publish_count")
PUBLISH_EVERY = int(os.environ.get("WX_PUBLISH_EVERY", "100"))

# 合规六大方向 → 核心监管机关公众号来源。每个 (查询词, 发布机关名)。
# org 写进存档 JSON，build_wx_archive 渲染时即显示为机构；空字符串则交由账号名推断。
QUERIES = [
    # 数据 / 个人信息 / 算法 / AI（网信）
    ("网信中国 个人信息保护",            "中央网信办"),
    ("网信中国 算法 治理",              "中央网信办"),
    ("网信中国 数据安全",              "中央网信办"),
    ("网信浙江 个人信息",              "浙江省网信办"),
    ("网信广东 数据安全",              "广东省网信办"),
    ("网信上海 个人信息",              "上海市网信办"),
    ("网信北京 数据安全",              "北京市网信办"),
    ("网信江苏 个人信息",              "江苏省网信办"),
    ("网信四川 数据安全",              "四川省网信办"),
    # 食安 / 价格 / 广告 / 反法（市场监管）
    ("市场监管 食品安全 典型案例",       "市场监管总局"),
    ("市场监管 价格 违法 告诫",          "市场监管总局"),
    ("市场监管 反不正当竞争 案例",       "市场监管总局"),
    ("食品安全 行政处罚 典型案例",       ""),
    ("市场监管 广告 违法 案例",          "市场监管总局"),
    ("市场监管 消费者权益 案例",         "市场监管总局"),
    ("市场监管 网络交易 监管",           "市场监管总局"),
    ("市场监管局 网络餐饮 食品安全 案例",  ""),
    ("市场监管局 食品 典型案例",         ""),
    ("市场监管局 价格 违法 案例",         ""),
    # 网安 / 数据安全（公安）
    ("公安网安 数据安全",               "公安部网络安全保卫局"),
    ("网络安全 监督检查 典型案例",       "公安部网络安全保卫局"),
    # App / 个人信息（工信部 / 通管局）
    ("工信部 个人信息 App",            "工业和信息化部"),
    ("通信管理局 App 通报",            ""),
    ("工信部 算法 备案",              "工业和信息化部"),
    # 消保 / 司法
    ("消费者协会 典型案例",            "中国消费者协会"),
    ("最高法 人工智能 典型案例",         "人民法院"),
    ("法院 数据 典型案例",             "人民法院"),
    ("检察院 个人信息 典型案例",         "人民检察院"),
]

MAX_PER_QUERY = int(os.environ.get("WX_MAX_PER", "2"))
SLEEP_BETWEEN_SEARCH = (12, 20)     # 两次检索之间随机休眠（秒）
SLEEP_BETWEEN_GRAB = (7, 12)       # 同一来源取多篇之间
ANTISPIDER_COOLDOWN = (120, 200)   # 整批被反爬夹击后的长冷却


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
    if org_hint:
        d = json.load(open(path, encoding="utf-8"))
        d["org"] = org_hint
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    pub = rec.get("pub") or "?"
    return rec.get("id"), f"{pub} / {rec.get('chars')} 字 / {rec.get('title','')[:40]}"


def count_archives():
    if not os.path.isdir(WX_DIR):
        return 0
    return sum(1 for f in os.listdir(WX_DIR)
               if f.endswith(".json") and f not in ("accounts.json", "replaces.json"))


def last_published():
    try:
        return int(open(PUBLISH_STATE, encoding="utf-8").read().strip() or "0")
    except Exception:
        return 0


def maybe_publish(new_total, do_publish):
    """攒够 PUBLISH_EVERY 篇 → 重建全站并推送。"""
    base = last_published()
    if not do_publish:
        print(f"\n[发布] 跳过（--no-publish）。当前存档 {new_total} 篇，上次发布基线 {base}。")
        return
    if new_total - base < PUBLISH_EVERY:
        print(f"\n[发布] 距下次自动发布还差 {PUBLISH_EVERY - (new_total - base)} 篇"
              f"（当前 {new_total}，基线 {base}）。")
        return
    print(f"\n[发布] 已达 {new_total} 篇（基线 {base}，新增 {new_total - base} ≥ {PUBLISH_EVERY}），"
          f"重建全站并推送…")
    py = "/Users/luochen/.workbuddy/binaries/python/envs/default/bin/python"
    # 1) 新存档补进资讯流条目库（去重）
    subprocess.run([py, "tools/wx_to_feed.py"], cwd=HERE)
    # 2) 重建全站（含 build_wx_archive 刷新 kb/wx.html 与 replaces.json）
    subprocess.run([py, "tools/daily_build.py", "--no-network"], cwd=HERE)
    # 3) 推送
    subprocess.run([py, "push_via_api.py"], cwd=HERE)
    subprocess.run([py, "push_via_api.py", "--check"], cwd=HERE)
    open(PUBLISH_STATE, "w", encoding="utf-8").write(str(new_total))
    print(f"[发布] 已推送，发布基线更新为 {new_total}。")


def main():
    dry = "--dry" in sys.argv
    do_publish = "--no-publish" not in sys.argv
    if "--max-per" in sys.argv:
        i = sys.argv.index("--max-per")
        global MAX_PER_QUERY
        MAX_PER_QUERY = max(1, int(sys.argv[i + 1]))

    print(f"近三个月公众号来源检索（限流+反爬绕过）  CUTOFF={datetime.fromtimestamp(CUTOFF,CST):%Y-%m-%d}  "
          f"来源数={len(QUERIES)}  每来源最多 {MAX_PER_QUERY} 篇  发布阈值={PUBLISH_EVERY}\n")
    if dry:
        for q, o in QUERIES:
            print(f"  · {o or '（账号名推断）':<14}  {q}")
        return

    archived, skipped, antispider = 0, 0, 0
    for qi, (query, org) in enumerate(QUERIES, 1):
        print(f"[{qi}/{len(QUERIES)}] 检索「{query}」…", flush=True)
        rows, err = fw.sogou_search(query)
        if err:
            print(f"    ⚠ 反爬/异常：{err[:60]} —— 冷却后跳下一条")
            antispider += 1
            time.sleep(random.uniform(*ANTISPIDER_COOLDOWN))
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

    total = count_archives()
    print(f"\n本轮检索完成：存档 {archived} 篇 / 无近三月候选 {skipped} 个来源 / 命中反爬 {antispider} 次")
    print(f"公众号原文存档累计 {total} 篇。")
    maybe_publish(total, do_publish)


if __name__ == "__main__":
    main()
