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
from wx_sources import build_queries as _build_wx_queries  # 来源注册表（单一事实来源）

CST = timezone(timedelta(hours=8))
CUTOFF = datetime(2025, 9, 14, tzinfo=CST).timestamp()   # 近一年起算（放宽历史窗口，冲量）
WX_DIR = os.path.join(HERE, "sources", "wx")
PUBLISH_STATE = os.path.join(WX_DIR, ".publish_count")
PUBLISH_EVERY = int(os.environ.get("WX_PUBLISH_EVERY", "100"))

# 合规来源池 = 工具/wx_sources.py 的「单一事实来源」全量注册表：
#   八类监管主体（网信办 / 公安 / 市场监管 / 工信 / 法院 / 检察 / 发改 / 人大司法）
#   的国家级 + 31 省 + 重点城市账号（含多账号如公安部网安局 / 网安通报 / 网警），
#   加行业协会 / 标准组织 / 学术机构 / 同行专业号。
#
# 【为什么不收敛来源 · 用户 2026-09-15 明确要求】
#   上一版为迁就单日抓取量，做了「按星期几取 1/7 硬切片」，并在来源层砍掉了
#   大量省份与词组合 —— 那是**错误决策**。限流只能在**调度层**解决：
#
#   改为「每日预算制」——每天固定跑 WX_DAILY_BUDGET 条，指针按「年内天数 × 预算」
#   连续推进，**轮转周期 = ceil(池子总数 ÷ 日预算)**，随来源池扩容自动延长。
#   于是：来源层只增不减（新增省份 / 城市 / 账号自动进入池子），单日负载恒定。
#
#   env WX_DAILY_BUDGET 调日预算（默认 500）；WX_ALL=1 或 --all 强制全量；
#   --dry 只打印当日切片与周期。
FULL_QUERIES = _build_wx_queries()


def _daily_budget():
    try:
        return int(os.environ.get("WX_DAILY_BUDGET", "500"))
    except ValueError:
        return 500


def _daily_queries():
    if "--all" in sys.argv or os.environ.get("WX_ALL"):
        return FULL_QUERIES
    total = len(FULL_QUERIES)
    budget = _daily_budget()
    if budget <= 0 or budget >= total:
        return FULL_QUERIES
    # 用「年内天数 × 预算」连续推进，保证每天不重不漏地往后走；
    # 周期 = ceil(total / budget)，跨轮后指针自然回到起点。
    day = datetime.now(CST).timetuple().tm_yday
    start = (day * budget) % total
    out = FULL_QUERIES[start:start + budget]
    if len(out) < budget:                     # 收尾跨尾回头，保证每日条数恒定
        out += FULL_QUERIES[:budget - len(out)]
    return out


def _cycle_days():
    """轮转周期（天）：池子越大周期越长，来源层无需收敛。"""
    total, budget = len(FULL_QUERIES), _daily_budget()
    if budget <= 0 or budget >= total:
        return 1
    return -(-total // budget)


QUERIES = _daily_queries()

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
        if "反爬" in err:
            # 取链级反爬：IP 被夹击，长冷却让出口恢复，避免连环轰炸反被封
            time.sleep(random.uniform(*ANTISPIDER_COOLDOWN))
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


def maybe_publish(new_total, do_publish, force=False):
    """攒够 PUBLISH_EVERY 篇 → 重建全站并推送；force=True 时无视阈值（超 2h 兜底发布）。"""
    base = last_published()
    if not do_publish:
        print(f"\n[发布] 跳过（--no-publish）。当前存档 {new_total} 篇，上次发布基线 {base}。")
        return
    if not force and new_total - base < PUBLISH_EVERY:
        print(f"\n[发布] 距下次自动发布还差 {PUBLISH_EVERY - (new_total - base)} 篇"
              f"（当前 {new_total}，基线 {base}）。")
        return
    why = "超 2 小时兜底" if force else f"达阈值（基线 {base}，新增 {new_total - base} ≥ {PUBLISH_EVERY}）"
    print(f"\n[发布] {why}，已达 {new_total} 篇，重建全站并推送…")
    py = "/Users/luochen/.workbuddy/binaries/python/envs/default/bin/python"
    # 0) 已抓到的原文回填到「主题摘要」条目（摘要 → 站内原文存档，来源自动升级）
    subprocess.run([py, "tools/wx_backfill_pending.py"], cwd=HERE)
    # 1) 新存档补进资讯流条目库（去重）
    subprocess.run([py, "tools/wx_to_feed.py"], cwd=HERE)
    # 2) 重建全站（含 build_wx_archive 刷新 kb/wx.html 与 replaces.json）
    subprocess.run([py, "tools/daily_build.py", "--no-network"], cwd=HERE)
    # 2.5) 暂存全部变更（push_via_api 以 git 索引为准，必须先把工作区变更纳入索引，
    #      否则它比对 index==远端 会判定「已最新」而静默跳过）
    subprocess.run(["git", "add", "-A"], cwd=HERE)
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

    mode = ("全量(--all)" if ("--all" in sys.argv or os.environ.get("WX_ALL"))
            else f"当日预算 {_daily_budget()}/天")
    print(f"公众号来源检索（限流+反爬绕过）  CUTOFF={datetime.fromtimestamp(CUTOFF,CST):%Y-%m-%d} 起算  "
          f"全量来源={len(FULL_QUERIES)}  本次{mode}={len(QUERIES)}  "
          f"轮转周期={_cycle_days()} 天  每来源最多 {MAX_PER_QUERY} 篇  发布阈值={PUBLISH_EVERY}\n")
    if dry:
        for q, o in QUERIES:
            print(f"  · {o or '（账号名推断）':<14}  {q}")
        return

    archived, skipped, antispider = 0, 0, 0
    START = time.time()
    LAST_FORCE = START
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

        # 超 2 小时兜底：即便还没攒到 PUBLISH_EVERY 篇，也先把已抓到的推送上线、继续爬。
        # 每 2 小时至多强制发布一次；且只有本轮确有新增存档时才发布（避免空推）。
        now = time.time()
        if now - START >= 7200 and now - LAST_FORCE >= 7200:
            tot = count_archives()
            if tot > last_published():
                maybe_publish(tot, do_publish, force=True)
                LAST_FORCE = now

    total = count_archives()
    print(f"\n本轮检索完成：存档 {archived} 篇 / 无近三月候选 {skipped} 个来源 / 命中反爬 {antispider} 次")
    print(f"公众号原文存档累计 {total} 篇。")
    maybe_publish(total, do_publish)


if __name__ == "__main__":
    main()
