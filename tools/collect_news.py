#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站点直采资讯入库器 —— 让「合规资讯」与本地日报彻底解耦。

背景
----
站点资讯流过去只解析 news/reports/*.html（本地合规简报的网页版），
于是「本地日报没有产出 → 站点当天就没有新内容」。用户 2026-09-14 明确要求：
**站点必须每天独立更新全部内容，与本地日报是否更新无关，两者是相互独立的数据与资讯来源。**

本脚本给站点内置一条独立于简报的资讯来源：

    sources/news/items.jsonl        （逐行 JSON，append-only，进仓库）

每日由自动化任务检索官方来源（网信中国 / 网安局 / 工信部 / 市场监管总局 / 最高法 /
各地监管机构官网等）得到候选条目，交给本脚本过五道闸门后落盘：

    1. 领域归一化 —— 必须落在 build_topics.DOMAINS 之内，否则拒收；
    2. 引源分级   —— sources_tier.tier_of()；`other`（商业媒体 / 二手转载）默认拒收
                     （立法·标准·专项行动·处罚案例只认官方原文；资讯可放宽到官方媒体与专业机构）；
    3. 深链闸门   —— 拒收官网首页根域名；curl 实测须为 200 / 403 / 429；
    4. 去重       —— 按 URL 与标题（去标点、转小写）双向去重，跨天也不重复入库；
    5. 落盘       —— 追加写 items.jsonl，并打印本轮入库 / 拒收明细与机器可读汇总。

用法
----
    python3 tools/collect_news.py --file /tmp/candidates.json          # 预览（不落盘）
    python3 tools/collect_news.py --file /tmp/candidates.json --apply  # 落盘
    python3 tools/collect_news.py --list                               # 看已入库条目标题
    python3 tools/collect_news.py --stats                              # 按领域/日期统计
    python3 tools/collect_news.py --file x.json --apply --allow-other  # 放宽二手转载（慎用）

候选条目 JSON（数组）：
    [{
      "domain":   "数据合规",     # 必需，须命中 DOMAINS
      "title":    "…",            # 必需，≥6 字
      "url":      "https://…",    # 必需，官方具体页面（禁官网首页根域名）
      "date":     "2026-09-14",   # 可选，默认今天
      "org":      "国家网信办",    # 可选，发布机构
      "kind":     "监管动态",      # 可选：新规发布/监管动态/处罚案例/专项行动/标准动态/立法进程
      "points":   "…",            # 可选，要点
      "analysis": "…",            # 可选，朴朴视角解读
      "risk":     "中高"           # 可选：高/中高/中/低
    }]

落盘后由 build_topics.py 合并进资讯流 / 首页 FEED / 应对建议，
故本脚本只负责数据质量，**不生成页面**。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from build_topics import DOMAIN_KEYS, normalize_domain, guess_domain, is_root_url  # noqa: E402
from sources_tier import tier_of, TIER_LABEL  # noqa: E402

STORE = os.path.join(ROOT, "sources", "news", "items.jsonl")
OK_CODES = {"200", "403", "429"}
KINDS = ["新规发布", "监管动态", "处罚案例", "专项行动", "标准动态", "立法进程",
         "司法动态", "国际动态"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------ 存储
def load_store():
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


def append_store(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "a", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n")


# ------------------------------------------------------------------ 工具
def norm_title(t):
    """标题归一化：只留中日韩文字、字母数字，用于判重。"""
    return re.sub(r"[\W_]+", "", (t or "").lower(), flags=re.UNICODE)


def host_of(url):
    return re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]


def probe(url, timeout=12):
    """curl 实测可达性（python urllib 在沙箱会被代理全拦，故用 curl）。"""
    try:
        r = subprocess.run(
            ["curl", "-sL", "-o", "/dev/null", "--max-time", str(timeout),
             "-A", "Mozilla/5.0", "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 8,
        )
        code = (r.stdout or "").strip()[-3:]
        return code if code.isdigit() else "000"
    except Exception:
        return "000"


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--file", help="候选条目 JSON 文件（数组）；缺省从 stdin 读")
    ap.add_argument("--apply", action="store_true", help="真正落盘（缺省只预览）")
    ap.add_argument("--date", help="候选条目缺省日期，默认今天")
    ap.add_argument("--no-verify", action="store_true", help="跳过 curl 可达性实测")
    ap.add_argument("--allow-other", action="store_true", help="允许二手转载入库（默认拒收）")
    ap.add_argument("--list", action="store_true", help="列出已入库条目")
    ap.add_argument("--stats", action="store_true", help="按领域与日期统计")
    a = ap.parse_args()

    today = a.date or date.today().isoformat()
    store = load_store()

    if a.list or a.stats:
        if not store:
            print("· 站点直采库为空（sources/news/items.jsonl）")
            return
        if a.list:
            for it in sorted(store, key=lambda x: (x.get("date", ""), x.get("domain", "")), reverse=True):
                print(f"  [{it.get('domain','?')}] {it.get('date','?')} {it.get('title','')[:70]}")
        if a.stats:
            print(f"\n合计 {len(store)} 条")
            by_d = {}
            by_t = {}
            for it in store:
                by_d[it.get("domain", "?")] = by_d.get(it.get("domain", "?"), 0) + 1
                by_t[it.get("collected", "?")] = by_t.get(it.get("collected", "?"), 0) + 1
            print("  领域：" + " / ".join(f"{k} {v}" for k, v in sorted(by_d.items(), key=lambda x: -x[1])))
            print("  入库日：" + " / ".join(f"{k} {v}" for k, v in sorted(by_t.items(), reverse=True)))
        return

    raw = ""
    if a.file:
        raw = open(a.file, encoding="utf-8").read()
    else:
        raw = sys.stdin.read()
    try:
        cand = json.loads(raw)
    except ValueError as e:
        print(f"× 候选 JSON 解析失败：{e}")
        sys.exit(2)
    if isinstance(cand, dict):
        cand = cand.get("items") or []

    seen_url = {it.get("url") for it in store if it.get("url")}
    seen_title = {norm_title(it.get("title")) for it in store}
    accepted, rejected, dup = [], [], []

    for c in cand:
        title = (c.get("title") or "").strip()
        url = (c.get("url") or "").strip()
        domain = normalize_domain(c.get("domain") or "")
        if domain not in DOMAIN_KEYS:
            domain = guess_domain(title + " " + (c.get("points") or ""))
        why = None
        if len(title) < 6:
            why = "标题过短"
        elif not domain or domain not in DOMAIN_KEYS:
            why = f"领域无法归一（{c.get('domain')}）"
        elif not url.startswith("http"):
            why = "缺少 http 链接"
        elif is_root_url(url):
            why = "链接是官网首页根域名，不可溯源"
        if why:
            rejected.append((title, why))
            continue

        if url in seen_url or norm_title(title) in seen_title:
            dup.append(title)
            continue

        tier = tier_of(url)
        if tier == "other" and not a.allow_other:
            rejected.append((title, f"来源属二手转载（{host_of(url)}），需换官方原文"))
            continue

        d = (c.get("date") or today).strip()
        if not DATE_RE.match(d):
            d = today
        kind = (c.get("kind") or "监管动态").strip()
        if kind not in KINDS:
            kind = "监管动态"

        accepted.append({
            "domain": domain,
            "title": title,
            "url": url,
            "date": d,
            "org": (c.get("org") or "").strip(),
            "kind": kind,
            "points": (c.get("points") or "").strip(),
            "analysis": (c.get("analysis") or "").strip(),
            "risk": (c.get("risk") or "").strip(),
            "tier": tier,
            "collected": today,
        })

    # 可达性实测（403/429 视为 WAF 拦脚本 UA，浏览器可正常打开）
    dead = []
    if accepted and not a.no_verify:
        print(f"curl 实测 {len(accepted)} 条官方深链…")
        keep = []
        for it in accepted:
            code = probe(it["url"])
            if code in OK_CODES:
                it["http"] = code
                keep.append(it)
            else:
                dead.append((it["title"], it["url"], code))
        accepted = keep

    print(f"\n候选 {len(cand)} 条 → 可入库 {len(accepted)} / 重复 {len(dup)} / 拒收 {len(rejected)} / 实测失效 {len(dead)}")
    for t, w in rejected:
        print(f"  ✗ {t[:60]}  —— {w}")
    for t, u, c in dead:
        print(f"  ✗ [{c}] {t[:56]}  {u[:70]}")
    for t in dup:
        print(f"  = 已存在：{t[:60]}")
    for it in accepted:
        print(f"  ✓ [{it['domain']}] {it['date']} {TIER_LABEL.get(it['tier'], it['tier'])} {it['title'][:52]}")

    if accepted:
        if a.apply:
            append_store(accepted)
            print(f"\n已写入 {STORE}（+{len(accepted)}，合计 {len(store) + len(accepted)} 条）")
        else:
            print("\n（预览模式，未落盘；加 --apply 生效）")

    print("__SUMMARY__" + json.dumps({
        "candidates": len(cand), "accepted": len(accepted), "dup": len(dup),
        "rejected": len(rejected), "dead": len(dead),
        "applied": bool(a.apply and accepted),
        "total": len(store) + (len(accepted) if a.apply else 0),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
