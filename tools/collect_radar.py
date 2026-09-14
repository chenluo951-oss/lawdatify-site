#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监管雷达每日增量入库器 —— 让「立法日历 / 监管动向 / 全球地图」也能每天自动更新。

背景
----
sources/radar/{calendar,actions,global}.json 过去是**纯人工维护**的结构化数据，
所以「监管雷达」在站点上几乎不随时间变化，这也属于「站点没有每天更新」的一部分。
本脚本把每日检索到的雷达条目按同一套字段与引源规则入库，人工只需要「补条目」而不是「重写文件」。

三道闸门与 collect_news.py 一致：
    1. 字段形状 —— 必填项齐全（calendar/global 需 date+title+url；actions 需 name+url）；
    2. 深链闸门 —— 拒收官网首页根域名，curl 实测须 200 / 403 / 429；
    3. 去重     —— calendar/global 按 (date,title)，actions 按 name，跨天不重复。

用法
----
    python3 tools/collect_radar.py --file /tmp/radar.json            # 预览
    python3 tools/collect_radar.py --file /tmp/radar.json --apply    # 落盘

输入 JSON（三路都可选）：
{
  "calendar": [{"date":"2026-10-01","type":"正式施行","title":"…","url":"https://…",
                "issuer":"…","region":"CN","domain":"数据合规","note":"…"}],
  "actions":  [{"name":"…","url":"https://…","level":"national|local","region":"全国",
                "series":"清朗","issuer":"…","period":"…","status":"进行中",
                "domain":"AI合规","focus":"…","targets":["…"],"progress":"…"}],
  "global":   [{"code":"KR","date":"2026-09-11","type":"规则生效","title":"…",
                "domain":"数据合规","note":"…","url":"https://…"}]
}

落盘后由 build_radar.py 生成页面（radar/{calendar,actions,map}.html），
并由 build_updates.py 把新增条目算进「今日更新」。本脚本不生成页面。
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

from build_topics import DOMAIN_KEYS, normalize_domain, is_root_url  # noqa: E402
from build_radar import REGION_CN  # noqa: E402
from sources_tier import tier_of, TIER_LABEL  # noqa: E402

SRC = os.path.join(ROOT, "sources", "radar")
OK_CODES = {"200", "403", "429"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEVELS = {"national", "local"}


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as fh:
        return json.load(fh)


def save(name, data):
    with open(os.path.join(SRC, name), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def probe(url, timeout=12):
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


def clean(it):
    """字段裁剪 + 默认值，避免把噪声键写进数据源。"""
    out = {}
    for k, v in it.items():
        if isinstance(v, str):
            v = v.strip()
            if not v:
                continue
        elif v in (None, [], {}):
            continue
        out[k] = v
    if "domain" in out:
        d = normalize_domain(out["domain"])
        if d in DOMAIN_KEYS:
            out["domain"] = d
        else:
            out.pop("domain")
    if re.search(r"[一-鿿]", (out.get("title") or "") + (out.get("name") or "")):
        out["lang"] = "zh"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()

    cand = json.load(open(a.file, encoding="utf-8"))
    if not isinstance(cand, dict):
        print("× 输入必须是对象：{calendar:[], actions:[], global:[]}")
        sys.exit(2)

    cal, act, glo = load("calendar.json"), load("actions.json"), load("global.json")
    seen = {
        "calendar": {(i.get("date"), i.get("title")) for i in cal["items"]},
        "actions": {i.get("name") for i in act["items"]},
        "global": {(i.get("code"), i.get("date"), i.get("title")) for i in glo["items"]},
    }
    ok_codes = {c for c, _ in [(c, 0) for c in REGION_CN]}
    juris = {j["code"] for j in glo.get("jurisdictions", [])}

    added = {"calendar": [], "actions": [], "global": []}
    rejected, dup, dead = [], [], []
    today = date.today().isoformat()

    # ---------------- 日历 ----------------
    for it in cand.get("calendar") or []:
        label = (it.get("title") or "")[:52]
        if not DATE_RE.match((it.get("date") or "").strip()):
            rejected.append((label, "date 缺失或格式不是 YYYY-MM-DD"))
            continue
        it = dict(it)
        it["date"] = it["date"].strip()
        if (it["date"], it.get("title")) in seen["calendar"]:
            dup.append(label)
            continue
        if not (it.get("title") or "").strip():
            rejected.append((label or "(无标题)", "缺少 title"))
            continue
        if not (it.get("type") or "").strip():
            rejected.append((label, "缺少 type（如 正式施行 / 意见征集截止 / 立法通过）"))
            continue
        if not (it.get("url") or "").startswith("http"):
            rejected.append((label, "缺少 http 链接"))
            continue
        if is_root_url(it["url"]):
            rejected.append((label, "链接是官网首页根域名，不可溯源"))
            continue
        it.setdefault("region", "CN")
        it.setdefault("src", "official")
        added["calendar"].append(it)

    # ---------------- 行动 ----------------
    for it in cand.get("actions") or []:
        label = (it.get("name") or "")[:52]
        if not (it.get("name") or "").strip():
            rejected.append(("(无名称)", "缺少 name"))
            continue
        if it["name"] in seen["actions"]:
            dup.append(label)
            continue
        if not (it.get("url") or "").startswith("http"):
            rejected.append((label, "缺少 http 链接"))
            continue
        if is_root_url(it["url"]):
            rejected.append((label, "链接是官网首页根域名，不可溯源"))
            continue
        if (it.get("level") or "") not in LEVELS:
            rejected.append((label, "level 必须是 national 或 local"))
            continue
        it.setdefault("status", "进行中")
        it.setdefault("src", "official")
        added["actions"].append(it)

    # ---------------- 全球 ----------------
    for it in cand.get("global") or []:
        label = (it.get("title") or "")[:52]
        code = (it.get("code") or "").strip().upper()
        if code not in juris and code not in ok_codes:
            rejected.append((label, f"code={code} 不在已登记的辖区列表内"))
            continue
        if not DATE_RE.match((it.get("date") or "").strip()):
            rejected.append((label, "date 缺失或格式不是 YYYY-MM-DD"))
            continue
        it = dict(it)
        it["code"], it["date"] = code, it["date"].strip()
        if (code, it["date"], it.get("title")) in seen["global"]:
            dup.append(label)
            continue
        if not (it.get("title") or "").strip():
            rejected.append((label or "(无标题)", "缺少 title"))
            continue
        if not (it.get("url") or "").startswith("http"):
            rejected.append((label, "缺少 http 链接"))
            continue
        if is_root_url(it["url"]):
            rejected.append((label, "链接是官网首页根域名，不可溯源"))
            continue
        if not (it.get("type") or "").strip():
            rejected.append((label, "缺少 type"))
            continue
        it.setdefault("src", "official")
        added["global"].append(it)

    # ---------------- 链接实测 + 引源分级 ----------------
    if not a.no_verify:
        for grp in added:
            keep = []
            for it in added[grp]:
                u = it["url"]
                tier = tier_of(u)
                if tier == "other":
                    rejected.append(((it.get("title") or it.get("name") or "")[:52],
                                     f"来源属二手转载（{re.sub(r'^https?://(www\.)?', '', u).split('/')[0]}）"))
                    continue
                code = probe(u)
                if code not in OK_CODES:
                    dead.append(((it.get("title") or it.get("name") or "")[:52], u, code))
                    continue
                if code != "200":
                    it["src"] = it.get("src", "official")
                keep.append(it)
            added[grp] = keep

    n = {k: len(v) for k, v in added.items()}
    print(f"可入库：日历 {n['calendar']} / 行动 {n['actions']} / 全球 {n['global']}"
          f"　重复 {len(dup)}　拒收 {len(rejected)}　实测失效 {len(dead)}")
    for t, w in rejected:
        print(f"  ✗ {t} —— {w}")
    for t, u, c in dead:
        print(f"  ✗ [{c}] {t}  {u[:70]}")
    for t in dup:
        print(f"  = 已存在：{t}")
    for grp in ("calendar", "actions", "global"):
        for it in added[grp]:
            print(f"  ✓ [{grp}] {it.get('date') or it.get('code')} "
                  f"{TIER_LABEL.get(tier_of(it['url']), '?')} "
                  f"{(it.get('title') or it.get('name'))[:52]}")

    total = sum(n.values())
    if total and a.apply:
        # 只写回真有新增的那一路，避免无谓地改动其它数据源（减少 diff 噪声）
        changed_files = []
        if n["calendar"]:
            cal["items"] += [clean(x) for x in added["calendar"]]
            changed_files.append(("calendar.json", cal))
        if n["actions"]:
            act["items"] += [clean(x) for x in added["actions"]]
            changed_files.append(("actions.json", act))
        if n["global"]:
            glo["items"] += [clean(x) for x in added["global"]]
            changed_files.append(("global.json", glo))
        for name, d in changed_files:
            if isinstance(d.get("_meta"), dict):
                d["_meta"]["updated"] = today
            save(name, d)
        print(f"\n已写回 sources/radar/：{'、'.join(n_ for n_, _ in changed_files)}"
              f"（日历 {len(cal['items'])} / 行动 {len(act['items'])} / 全球 {len(glo['items'])}）")
    elif total:
        print("\n（预览模式，未落盘；加 --apply 生效）")

    print("__SUMMARY__" + json.dumps(
        {"calendar": n["calendar"], "actions": n["actions"], "global": n["global"],
         "dup": len(dup), "rejected": len(rejected), "dead": len(dead),
         "applied": bool(a.apply and total)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
