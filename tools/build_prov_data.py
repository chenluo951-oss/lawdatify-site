#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合「中国 · 省市级监管态势地图」的省级条目 → sources/radar/china.json

背景（2026-09-17 用户反馈「省市的还是没更新，合规动态和案例库不是都有更新很多数据吗」）：
地图页此前读的省级条目是 `gen_china_map.py` 里 **硬编码的 PROV_ITEMS（7 条）**，
与站点的合规动态库（sources/news/items.jsonl）和案例库（sources/cases/cases.json）
完全脱钩 —— 所以数据每天都在涨，地图却一直是那 7 条。本脚本把地图接上真实数据源。

数据来源（按优先级）：
  1. sources/radar/prov_curated.json  —— 人工精选的地方监管动作（原 PROV_ITEMS，保留）
  2. sources/news/items.jsonl        —— 合规动态里能判出属地的条目
  3. sources/cases/cases.json        —— 案例库里能判出属地的处罚 / 通报 / 典型案例
  4. sources/cases/local_amr.jsonl   —— 地方市场监管机关公示（带 agency 字段，属地最准）

属地识别走 tools/prov_map.py；判不出属地的条目**不入省视图**（宁缺毋滥）。

⚠️ 本脚本**只重写 china.json 的 items / n / n_case / last 四个键**（外加 `_meta`），
几何数据（path / cx / cy / viewBox）原样保留 —— 这样零联网、幂等，也不必重跑依赖
DataV 下载件的 gen_china_map.py。

用法：
  python3 tools/build_prov_data.py            # 预览（不落盘）
  python3 tools/build_prov_data.py --apply    # 落盘
"""
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from prov_map import detect_issuer, agency_in_text  # noqa: E402

CHINA = os.path.join(HERE, "sources", "radar", "china.json")
CURATED = os.path.join(HERE, "sources", "radar", "prov_curated.json")
NEWS = os.path.join(HERE, "sources", "news", "items.jsonl")
CASES = os.path.join(HERE, "sources", "cases", "cases.json")
LOCAL = os.path.join(HERE, "sources", "cases", "local_amr.jsonl")

MAX_PER_PROV = 40      # 单省最多保留条数（地图 tooltip 与面板都不宜过长）


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def load_curated():
    """人工精选条目：结构 {省名: [item, ...]}。"""
    if not os.path.exists(CURATED):
        return {}
    try:
        d = json.load(open(CURATED, encoding="utf-8"))
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def norm_items():
    """产出 [(省名, item)]，item 字段与地图页渲染约定一致：
    date / type / domain / title / url / note / src / origin / geo。"""
    rows = []

    # ① 人工精选（最高优先，去重时先占位）
    for prov, items in load_curated().items():
        for it in items or []:
            rows.append((prov, dict(
                date=it.get("date", ""), type=it.get("type", "地方动态"),
                domain=it.get("domain", ""), title=it.get("title", ""),
                url=it.get("url", ""), note=it.get("note", ""),
                src=it.get("src", "official"), origin="curated", geo="curated")))

    # ② 合规动态：按**发布机关**判属地，标题只取前 16 字
    for it in _read_jsonl(NEWS):
        prov, geo = detect_issuer(
            org=it.get("org", ""), title=it.get("title", ""),
            body=(it.get("points") or "") + " " + (it.get("analysis") or ""),
            url=it.get("url", ""))
        if not prov:
            continue
        rows.append((prov, dict(
            date=it.get("date", ""), type=it.get("kind") or "监管动态",
            domain=it.get("domain", ""), title=it.get("title", ""),
            url=it.get("url", ""),
            note=(it.get("points") or "").strip(), src=it.get("src") or "official",
            origin="news", geo=geo)))

    # ③ 案例库：org 多为「地方市场监管局」这类抽象名，故靠标题机关名 + 域名
    try:
        cases = json.load(open(CASES, encoding="utf-8")).get("cases", [])
    except Exception:
        cases = []
    for it in cases:
        title = it.get("title", "")
        prov, geo = detect_issuer(org=it.get("org", ""), title=title,
                                  body=it.get("fact") or "",
                                  url=it.get("url", ""))
        if not prov:
            prov = agency_in_text(title)
            geo = "title-agency" if prov else ""
        if not prov:
            continue
        fine = "、".join(it.get("fines") or [])
        note = (it.get("fact") or "").strip()[:180]
        if fine:
            note = f"罚款：{fine}。" + note
        rows.append((prov, dict(
            date=it.get("date", ""), type=it.get("type") or "处罚案例",
            domain="", title=title, url=it.get("url", ""),
            note=note, src="official", origin="case", geo=geo,
            kind=it.get("kind") or "处罚案例")))

    # ④ 地方市监公示：agency 字段（「广东省市场监督管理局」）属地最准
    for it in _read_jsonl(LOCAL):
        title = it.get("title", "")
        prov, geo = detect_issuer(agency=it.get("agency", ""),
                                  org=it.get("org", ""), title=title,
                                  body=it.get("fact") or "",
                                  url=it.get("url", ""))
        if not prov:
            prov = agency_in_text(title)
            geo = "title-agency" if prov else ""
        if not prov:
            continue
        fine = "、".join(it.get("fines") or [])
        note = (it.get("fact") or "").strip()[:180]
        if fine:
            note = f"罚款：{fine}。" + note
        rows.append((prov, dict(
            date=it.get("date", ""), type=it.get("type") or "处罚案例",
            domain="", title=title, url=it.get("url", ""),
            note=note, src="official", origin="case", geo=geo,
            kind=it.get("kind") or "处罚案例")))
    return rows


def _url_year(u):
    m = re.search(r"/(\d{4})/", u or "")
    return m.group(1) if m else ""


def _better(a, b):
    """同标题的两条里该留哪条（见 merge 的说明）。"""
    da, db = (a.get("date") or "")[:4], (b.get("date") or "")[:4]
    sa, sb = _url_year(a.get("url")) == da and da != "", \
        _url_year(b.get("url")) == db and db != ""
    if sa != sb:
        return sa
    return (a.get("url") or "") < (b.get("url") or "")


def merge(rows):
    """按省聚合 + 两级去重 + 日期倒序 + 截断。

    ① **URL 全局唯一**（无 URL 用标题兜底）：跨省也不会重复收录同一条。
    ② **同省同标题只留一条**（2026-09-17 补）：市场监管总局的处罚决定书在
       栏目分页里会以 `art/2022/…` 与 `art/2023/…` 两个 **不同 URL** 各出现
       一次，标题 / 日期 / 正文完全相同 —— 只按 URL 去重会把它算成两起案件。
       实测这类重复 36 组（430 条里虚高 36 条），地图上的「省级属地条目」
       会跟着虚高，读者一点进去就发现同一个案子出现两次。
    保留顺序：URL 里的年份目录与案件日期年份一致的那条优先（总局分页按
    发布时间归档，日期年份匹配的通常是最初发布页），再退化为 URL 字典序，
    保证多次构建结果稳定。
    """
    seen_url = set()
    by = {}
    for prov, it in rows:
        key = it.get("url") or ("t:" + it.get("title", ""))
        if not key or key in seen_url:
            continue
        seen_url.add(key)
        d = by.setdefault(prov, {})
        tk = (it.get("title") or "").strip()
        if tk and tk in d:
            if _better(it, d[tk]):
                d[tk] = it
            continue
        d[tk or key] = it
    out = {}
    for prov, d in by.items():
        lst = sorted(d.values(),
                     key=lambda x: (x.get("date") or "", x.get("title") or ""),
                     reverse=True)
        out[prov] = lst[:MAX_PER_PROV]
    return out


def main():
    apply = "--apply" in sys.argv
    d = json.load(open(CHINA, encoding="utf-8"))
    provs = d["provinces"]
    names = {p["name"] for p in provs if p.get("name") and p["name"] != "南海诸岛"}

    rows = norm_items()
    by = merge(rows)

    unknown = sorted(set(p for p in by if p not in names))
    hit = {p: v for p, v in by.items() if p in names}

    total = sum(len(v) for v in hit.values())
    print(f"候选条目 {len(rows)} 条 → 判出属地 {total} 条 / "
          f"覆盖 {len(hit)} 个省级行政区")
    if unknown:
        print("⚠ 属地名不在 china.json：", unknown)
    print("分省 TOP：", Counter({k: len(v) for k, v in hit.items()}).most_common(12))
    print("来源构成：", Counter(i.get("origin") for v in hit.values() for i in v))
    print("类型构成 TOP：", Counter(i.get("type") for v in hit.values() for i in v).most_common(10))

    if not apply:
        print("\n（预览模式，未落盘；加 --apply 写入）")
        return

    n_case = {}
    last = {}
    for p in provs:
        nm = p.get("name")
        if not nm or nm == "南海诸岛":
            continue
        items = hit.get(nm, [])
        p["items"] = items
        p["n"] = len(items)
        p["n_case"] = sum(1 for i in items if i.get("origin") == "case")
        p["last"] = items[0]["date"] if items else ""
        n_case[nm] = p["n_case"]
        last[nm] = p["last"]

    d["_meta"] = {
        "desc": "中国省级监管态势地图数据源。items 由 tools/build_prov_data.py "
                "从合规动态库 + 案例库 + 地方市监公示 + 人工精选聚合，按发行机关属地归类。",
        "updated": __import__("datetime").date.today().isoformat(),
        "count": total,
    }
    json.dump(d, open(CHINA, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n✓ 已写入 {CHINA}：{total} 条 / {len(hit)} 省，_meta.updated="
          f"{d['_meta']['updated']}")


if __name__ == "__main__":
    main()
