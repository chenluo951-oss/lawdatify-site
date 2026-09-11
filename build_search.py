#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_search.py — 生成全站检索索引 assets/search-index.json

索引覆盖（可被真实搜到的内容，而非只有几个页面）：
  law    法规与标准      sources/standards/library.json（1000+ 条，含编号/发布机构/状态）
  duty   合规义务        sources/standards/duties.json（143 项，含条款原文与出处）
  news   监管动态        news/index.html 已发布条目（含领域/机构/日期/要点）
  action 监管行动        sources/radar/actions.json
  cal    立法节点        sources/radar/calendar.json
  dra    草案征求意见     sources/library/drafts.json
  art    专题分析        sources/analysis/registry.json
  page   站内页面        固定清单

输出字段（紧凑，便于前端即时检索）：
  t 标题 / d 摘要 / c 分类 / u 链接 / s 副信息 / k 检索关键词串
"""
import os
import re
import json
import html

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "search-index.json")

CATS = [
    ("law", "法规标准"),
    ("duty", "合规义务"),
    ("news", "监管动态"),
    ("action", "监管行动"),
    ("cal", "立法节点"),
    ("dra", "草案征求意见"),
    ("art", "专题分析"),
    ("page", "页面"),
]


def jload(p, default=None):
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def clean(s, n=170):
    s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(s or "")))).strip()
    return s[:n]


def main():
    items = []

    # ---------- 1. 法规与标准 ----------
    lib = jload(os.path.join(HERE, "sources", "standards", "library.json"), {})
    for it in lib.get("items", []):
        if it.get("hidden"):
            continue
        name = (it.get("name") or "").strip()
        code = (it.get("code") or "").strip()
        if not name:
            continue
        title = f"{code} {name}".strip() if code and code not in name else name
        bits = [it.get("level") or "", it.get("status") or "",
                it.get("issuer") or "", it.get("topic") or ""]
        if it.get("impl"):
            bits.append(f"实施 {it['impl']}")
        sub = " · ".join([b for b in bits if b])
        duties = "、".join(it.get("duty") or [])
        items.append({
            "t": title, "c": "law", "u": it.get("url") or "kb/index.html",
            "s": sub,
            "d": clean(it.get("point") or (("对应义务：" + duties) if duties else name)),
            "k": " ".join([name, code, it.get("issuer") or "", it.get("topic") or "",
                           it.get("level") or "", duties]).strip(),
        })

    # ---------- 2. 合规义务（含条款原文） ----------
    du = jload(os.path.join(HERE, "sources", "standards", "duties.json"), {})
    for c in du.get("categories", []):
        for si, s in enumerate(c.get("scenes", [])):
            for di, d in enumerate(s.get("duties", [])):
                quotes = []
                arts = []
                for a in (d.get("articles") or []):
                    if a.get("quote"):
                        quotes.append(f'【{a.get("src")} {a.get("art") or ""}】{a["quote"]}')
                    if a.get("src"):
                        arts.append(a["src"])
                desc = d.get("d") or ""
                if quotes:
                    desc = desc + " ‖ " + " ".join(quotes)
                items.append({
                    "t": d.get("t") or "",
                    "c": "duty",
                    "u": f'kb/standards.html#d-{c["id"]}-{si}-{di}',
                    "s": f'{c["name"]} › {s["name"]}' + (f' · 风险{d["risk"]}' if d.get("risk") else ""),
                    "d": clean(desc, 420),
                    "k": " ".join([d.get("t") or "", d.get("d") or "", c["name"], s["name"],
                                   " ".join(d.get("refs") or []), " ".join(arts),
                                   " ".join(quotes)]).strip(),
                })

    # ---------- 3. 监管动态（解析已发布资讯页） ----------
    news_html = os.path.join(HERE, "news", "index.html")
    if os.path.exists(news_html):
        s = open(news_html, encoding="utf-8").read()
        for m in re.finditer(
                r'<article class="ni"[^>]*data-domain="([^"]*)"[^>]*>(.*?)</article>', s, re.S):
            dom, blk = m.group(1), m.group(2)
            tm = re.search(r'class="ni-title">(.*?)</h4>', blk, re.S)
            if not tm:
                continue
            title = clean(tm.group(1), 120)
            pm = re.search(r'class="ni-pt">(.*?)</p>', blk, re.S)
            dm = re.search(r'class="ni-date">([^<]*)<', blk)
            om = re.search(r'class="ni-org">([^<]*)<', blk)
            km = re.search(r'class="ni-kind">([^<]*)<', blk)
            um = re.search(r'<a class="src" href="([^"]+)"', blk)
            items.append({
                "t": title, "c": "news",
                "u": um.group(1) if um else "news/index.html",
                "s": " · ".join([x for x in [dom, om.group(1) if om else "",
                                             dm.group(1) if dm else "",
                                             km.group(1) if km else ""] if x]),
                "d": clean(pm.group(1), 200) if pm else "",
                "k": " ".join([title, dom, om.group(1) if om else "",
                               clean(pm.group(1), 400) if pm else ""]).strip(),
            })

    # ---------- 4. 监管行动 ----------
    acts = jload(os.path.join(HERE, "sources", "radar", "actions.json"), {})
    for a in (acts.get("items") if isinstance(acts, dict) else acts) or []:
        items.append({
            "t": a.get("name") or "", "c": "action", "u": "radar/actions.html",
            "s": " · ".join([x for x in [a.get("issuer"), a.get("region"),
                                         a.get("status"), a.get("period")] if x]),
            "d": clean(a.get("focus") or a.get("desc") or "", 260),
            "k": " ".join([a.get("name") or "", a.get("issuer") or "", a.get("series") or "",
                           a.get("domain") or "", a.get("focus") or "",
                           " ".join(a.get("targets") or [])]).strip(),
        })

    # ---------- 5. 立法节点 ----------
    cal = jload(os.path.join(HERE, "sources", "radar", "calendar.json"), {})
    for e in (cal.get("items") if isinstance(cal, dict) else cal) or []:
        items.append({
            "t": e.get("title") or e.get("name") or "", "c": "cal",
            "u": "radar/calendar.html",
            "s": " · ".join([x for x in [e.get("date"), e.get("type"), e.get("region")] if x]),
            "d": clean(e.get("note") or e.get("desc") or "", 200),
            "k": " ".join([e.get("title") or e.get("name") or "", e.get("type") or "",
                           e.get("region") or "", e.get("note") or ""]).strip(),
        })

    # ---------- 6. 草案征求意见 ----------
    dr = jload(os.path.join(HERE, "sources", "library", "drafts.json"), [])
    for d in (dr if isinstance(dr, list) else dr.get("items", [])):
        items.append({
            "t": d.get("name") or d.get("title") or "", "c": "dra",
            "u": d.get("url") or "kb/drafts.html",
            "s": " · ".join([x for x in [d.get("issuer"), d.get("deadline"), d.get("status")] if x]),
            "d": clean(d.get("desc") or d.get("note") or "", 200),
            "k": " ".join([d.get("name") or d.get("title") or "", d.get("issuer") or "",
                           d.get("desc") or ""]).strip(),
        })

    # ---------- 7. 专题分析 ----------
    reg = jload(os.path.join(HERE, "sources", "analysis", "registry.json"), {})
    for a in (reg.get("items") if isinstance(reg, dict) else reg) or []:
        items.append({
            "t": a.get("title") or "", "c": "art",
            "u": a.get("file") or "analysis/index.html",
            "s": " · ".join([x for x in [a.get("date"), "专题研究"] if x]),
            "d": clean(a.get("summary") or "", 260),
            "k": " ".join([a.get("title") or "", a.get("summary") or "",
                           " ".join(a.get("tags") or [])]).strip(),
        })

    # ---------- 8. 站内页面 ----------
    pages = [
        ("今日更新", "updates/index.html", "法规标准增量、生效倒计时、立法节点与草案截止"),
        ("监管雷达", "radar/index.html", "何时生效、何地监管、何种行动：立法日历与监管动向"),
        ("立法日历", "radar/calendar.html", "法律法规与标准的生效、实施、过渡期节点"),
        ("监管动向", "radar/actions.html", "进行中与已结束的专项整治、执法行动"),
        ("全球监管地图", "radar/map.html", "按地域查看监管动态分布"),
        ("合规资讯", "news/index.html", "六大领域监管动态流，逐条附官方深链"),
        ("应对建议", "news/actions.html", "按领域给出的整改与落地建议"),
        ("简报归档", "news/briefs.html", "日报 / 周报 / 月报全期次归档"),
        ("合规知识库", "kb/index.html", "资料库、义务清单与草案跟踪"),
        ("合规义务清单", "kb/standards.html", "10 大类 47 场景 143 项义务，矩阵总览 + 逐条明细，配条款原文与标杆做法"),
        ("专题分析", "analysis/index.html", "深度专题研究，结论先行、附官方深链"),
        ("关于本站", "about.html", "站点定位、数据来源与维护方式"),
    ]
    for t, u, d in pages:
        items.append({"t": t, "c": "page", "u": u, "s": "站内页面", "d": d, "k": f"{t} {d}"})

    # 去重 + 清洗
    seen = set()
    out = []
    for it in items:
        t = (it.get("t") or "").strip()
        if not t:
            continue
        key = (it["c"], t, it.get("u", ""))
        if key in seen:
            continue
        seen.add(key)
        it["t"] = t
        out.append(it)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({
        "cats": CATS,
        "count": len(out),
        "items": out,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    from collections import Counter
    cc = Counter(i["c"] for i in out)
    print(f"索引条目 {len(out)}：" + " · ".join(f"{c} {n}" for c, n in cc.most_common()))
    print(f"输出 {OUT}（{os.path.getsize(OUT)//1024} KB）")


if __name__ == "__main__":
    main()
