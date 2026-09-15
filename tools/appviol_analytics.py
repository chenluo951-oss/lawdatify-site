#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App 违规通报库 —— 治理导向分析
================================================================================
【设计出发点：合规治理需要看什么，就统计什么】
  旧分析是「有什么数据画什么图」——文书类型、层级、问题分布，全是描述性计数，
  看不出监管趋势，也回答不了「我们该盯谁、盯什么、什么时候会被下架」。
  本模块按治理决策链重组：**谁在管 → 管得勤不勤 → 管到哪一步 → 我这款会不会被管。**

  ① 机构 × 年份 通报量矩阵      谁在管、监管何时扩围（某年首次出现的机构）、
                                哪几家在加码（近三年斜率）
  ② 渠道 × 年份                 名单挂在什么载体上（省局官网表格 / 部委附件 PDF /
                                网信办名单图 / 正文内嵌）→ 决定监测成本与漏检风险
  ③ 治理动作 × 年份             通报 → 整改复核 → 下架处置 的年度构成，
                                看监管是否从「点名」走向「下架」（处置刚性上升）
  ④ 再犯分析                    重复通报的应用：两次间隔中位数、跨机构比例、
                                升级下架比例、再次通报时新增的问题类目
  ⑤ 执法强度                    每机构文书数 / 覆盖应用数 / 文书均条目数，
                                识别「高产出机构」与「单份点名多款」的通报风格
  ⑥ 问题类型 × 年份             问题类目的年度演变（哪类问题是新增热点）
  ⑦ 属地方向 × 年份             省级通报的活跃度与年度分布

【口径纪律】
  · 文书数 ≠ 涉及应用数：分 kind 统计，不把「整改复核」「下架处置」混入「批次通报」；
  · 同一款应用在同一机构同一批次里只计一次（事件层已去重）；
  · 仅精确到年的日期（省局 jjaas 无发布日期）不参与月度统计，只参与年度统计，
    并在 meta 里披露 `date_year_only` 份数。
================================================================================
"""
import json, os, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from appviol_entity import resolve, app_key  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(HERE, "sources", "appviol")


def yr(d):
    return (d.get("date") or "")[:4]


def median(xs):
    if not xs:
        return 0
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


def pct(a, b):
    return round(a * 100.0 / b, 1) if b else 0.0


# ------------------------------------------------------------------ 主体归一
# 同一机构在不同文书里会写成「内蒙古通信管理局」/「内蒙古自治区通信管理局」、
# 「四川省通信管理局」/「四川省通信管理局、重庆市通信管理局」（联合通报）——
# 联合通报要拆成两个机构分别计数，否则省局的通报量会被合并项吃掉。
SPLIT = ["、", "，", ",", "与"]


def orgs_of(d):
    """把「四川省通信管理局、重庆市通信管理局」拆成两家，各计 0.5 份文书。"""
    o = (d.get("org") or "").strip()
    if not o:
        return []
    parts = [o]
    for s in SPLIT:
        if s in o:
            parts = [p.strip() for p in o.split(s) if p.strip()]
            break
    return parts or [o]


ALIAS = {
    "内蒙古通信管理局": "内蒙古自治区通信管理局",
    "广西通信管理局": "广西壮族自治区通信管理局",
    "西藏通信管理局": "西藏自治区通信管理局",
    "宁夏通信管理局": "宁夏回族自治区通信管理局",
    "新疆通信管理局": "新疆维吾尔自治区通信管理局",
    "工业和信息化部": "工业和信息化部 · 信息通信管理局",
    "中央网信办": "中央网信办 · 秘书局",
    "未知主体": "（未能识别发布主体）",
}
# 4 部门联合发布的专项行动公告，归到国家层面的「联合专项」
JOINT = {"中央网信办 · 秘书局", "工业和信息化部 · 信息通信管理局",
         "公安部 · 网络安全保卫局", "国家市场监督管理总局"}


def norm_org(o):
    o = ALIAS.get(o.strip(), o.strip())
    return o


def main():
    argv = sys.argv[1:]
    dpath = os.path.join(OUTDIR, "docs.json")
    if "--docs" in argv:
        dpath = argv[argv.index("--docs") + 1]
    docs = json.load(open(dpath, encoding="utf-8"))["docs"]
    apps, est = resolve(docs)

    years = sorted({yr(d) for d in docs if yr(d)})
    # ---------- ① 机构 × 年份 ----------
    oy = defaultdict(lambda: defaultdict(float))     # org → year → 文书数（联合计 0.5）
    oe = defaultdict(int)                            # org → 明细条目
    ok = defaultdict(Counter)                        # org → kind
    oc = defaultdict(Counter)                        # org → carrier
    oa = defaultdict(set)                            # org → 涉及应用（按事件）
    oscope, ofirst, olast, oprov = {}, {}, {}, defaultdict(set)
    odocs = defaultdict(int)
    for d in docs:
        parts = [norm_org(x) for x in orgs_of(d)]
        if not parts:
            continue
        w = 1.0 / len(parts)
        y = yr(d) or "未知"
        n = d.get("n_entries") or 0
        for o in parts:
            oy[o][y] += w
            odocs[o] += 1
            oe[o] += int(n * w)
            ok[o][d.get("notice_kind") or "未分类"] += 1
            oc[o][d.get("carrier") or "?"] += 1
            for e in d.get("entries") or []:
                if e.get("app"):
                    oa[o].add(app_key(e["app"]))
            oscope.setdefault(o, d.get("scope") or "其他")
            if d.get("province"):
                oprov[o].add(d["province"])
            if y != "未知":
                if not ofirst.get(o) or y < ofirst[o]:
                    ofirst[o] = y
                if not olast.get(o) or y > olast[o]:
                    olast[o] = y

    org_rows = []
    for o, byy in oy.items():
        tot = sum(byy.values())
        recent = sum(byy.get(y, 0) for y in years[-3:])
        hist = sum(byy.get(y, 0) for y in years[:-3])
        org_rows.append({
            "org": o, "scope": oscope.get(o, "其他"),
            "docs": odocs[o], "total": round(tot, 1),
            "entries": oe[o], "apps": len(oa[o]),
            "by_year": {y: round(byy.get(y, 0), 1) for y in years},
            "kinds": dict(ok[o]), "carriers": dict(oc[o]),
            "first": ofirst.get(o, ""), "last": olast.get(o, ""),
            "provinces": sorted(oprov[o]),
            "avg_entries": round(oe[o] / odocs[o], 1) if odocs[o] else 0,
            "trend": round(recent / (len(years[-3:]) or 1), 1),
            "hist_avg": round(hist / max(1, len(years[:-3])), 1),
        })
    org_rows.sort(key=lambda r: -r["docs"])

    # ---------- ② 年度总览 ----------
    KINDS = ["批次通报", "整改复核", "下架处置", "年度汇总", "专项行动", "测评评议"]
    year_summary = []
    seen_orgs = set()
    for y in years:
        ds = [d for d in docs if yr(d) == y]
        if not ds:
            continue
        cur = set()
        for d in ds:
            for o in orgs_of(d):
                cur.add(norm_org(o))
        new_orgs = sorted(cur - seen_orgs)
        seen_orgs |= cur
        kc = Counter(d.get("notice_kind") or "未分类" for d in ds)
        cc = Counter(d.get("carrier") or "?" for d in ds)
        year_summary.append({
            "year": y, "docs": len(ds),
            "orgs": len(cur), "new_orgs": len(new_orgs),
            "new_org_names": new_orgs[:12],
            "entries": sum(d.get("n_entries") or 0 for d in ds),
            "kinds": {k: kc.get(k, 0) for k in KINDS if kc.get(k)},
            "carriers": dict(cc),
            "scope": dict(Counter(d.get("scope") or "其他" for d in ds)),
            "monthly": dict(Counter((d.get("date") or "")[5:7]
                                    for d in ds if d.get("date_precision") == "day")),
            "exact_date": sum(1 for d in ds if d.get("date_precision") == "day"),
        })

    # ---------- ③ 渠道 × 年份 ----------
    CARR = {"html-table": "省局官网 HTML 表格", "pdf": "部委附件 PDF",
            "inline-text": "正文内嵌《应用名》", "image-ocr": "名单图 OCR",
            "text": "正文纯文本"}
    carrier_year = []
    for c, label in CARR.items():
        byy = Counter(yr(d) for d in docs if d.get("carrier") == c and yr(d))
        if byy:
            carrier_year.append({"carrier": c, "label": label,
                                 "total": sum(byy.values()),
                                 "by_year": {y: byy.get(y, 0) for y in years},
                                 "entries": sum(d.get("n_entries") or 0
                                                for d in docs if d.get("carrier") == c)})
    carrier_year.sort(key=lambda r: -r["total"])

    # ---------- ④ 治理动作 × 年份 ----------
    kind_year = []
    for k in KINDS:
        byy = Counter(yr(d) for d in docs if (d.get("notice_kind") or "") == k and yr(d))
        if byy:
            ent = sum(d.get("n_entries") or 0 for d in docs if (d.get("notice_kind") or "") == k)
            kind_year.append({"kind": k, "total": sum(byy.values()), "entries": ent,
                              "by_year": {y: byy.get(y, 0) for y in years}})

    # ---------- ⑤ 再犯分析 ----------
    # ⚠️ 关键口径：「重复出现」不等于「再犯」。同一轮治理链条里，监管先「批次通报」，
    # 十几天后出「整改复核」，再「下架处置」—— 同一款应用会在三步里各出现一次。
    # 实测相邻两次间隔的中位数只有 10 天，说明绝大多数「重复」是链条内跟进。
    # 因此按最大间隔给每个应用分层，把真正跨年度反复违规的挑出来：
    #   chain      仅在同一轮链条内重复（间隔 ≤90 天）
    #   months     最远间隔 91—180 天
    #   half       最远间隔 181—365 天
    #   cross_year 存在跨年间隔（>365 天）—— 这才是「整改后再次违规」
    def relapse_class(a):
        inc = a.get("incidents") or []
        ys = sorted({int(x["year"]) for x in inc
                     if (x.get("year") or "").isdigit() and int(x["year"]) > 1990})
        span_y = (ys[-1] - ys[0]) if len(ys) >= 2 else 0
        g = a.get("relapse_gaps") or []
        if g:
            mx = max(g)
            if mx > 365:
                return "cross_year"
            if mx > 180:
                return "half"
            if mx > 90:
                return "months"
            return "chain"
        # 没有精确到日的间隔（两端文书只能定位到年）→ 退回年份跨度判据：
        # 只要跨了一个年度，就足以说明不是同一轮链条内的跟进。
        if span_y >= 1:
            return "cross_year_year"
        # 事件有多个但同年且无精确日期 → 单列，不混入任何一档
        return "unknown"

    rep = [a for a in apps if a["n_incidents"] > 1]
    for a in apps:
        a["_rc"] = relapse_class(a)
    cls_cnt = Counter(a["_rc"] for a in rep)
    gaps = [g for a in apps for g in a["relapse_gaps"]]
    buckets = Counter()
    for g in gaps:
        if g <= 90:
            buckets["≤3 个月（同一轮链条内）"] += 1
        elif g <= 180:
            buckets["3—6 个月"] += 1
        elif g <= 365:
            buckets["6—12 个月"] += 1
        else:
            buckets["1 年以上（跨年度再犯）"] += 1

    def row(a):
        return {"app": a["app"], "dev": a["dev"], "n": a["n_incidents"],
                "n_notice": a["n_notice"], "n_orgs": a["n_orgs"], "orgs": a["orgs"],
                "first": a["first"], "last": a["last"],
                "gaps": a["relapse_gaps"], "escalated": a["escalated"],
                "new_probs": a["new_probs"], "probs": a["probs"],
                "docs": a["docs"], "cls": a["_rc"],
                "span": a["span_days"]}

    cross_year = [a for a in rep if a["_rc"] in ("cross_year", "cross_year_year")]
    repeat = {
        "apps": len(rep), "apps_multi_org": sum(1 for a in rep if a["n_orgs"] > 1),
        "apps_escalated": sum(1 for a in rep if a["escalated"]),
        "apps_new_prob": sum(1 for a in rep if a["new_probs"]),
        "gap_median": median(gaps), "gap_buckets": dict(buckets),
        "by_class": dict(cls_cnt),
        "chain_apps": cls_cnt.get("chain", 0),
        "unknown_apps": cls_cnt.get("unknown", 0),
        "cross_year_apps": len(cross_year),
        "cross_year_exact": cls_cnt.get("cross_year", 0),
        "cross_year_year": cls_cnt.get("cross_year_year", 0),
        "cross_half_apps": cls_cnt.get("half", 0) + cls_cnt.get("months", 0),
        "max_incidents": max((a["n_incidents"] for a in apps), default=0),
        "by_incidents": dict(sorted(Counter(a["n_incidents"] for a in rep).items())),
        "top": [row(a) for a in sorted(
            rep, key=lambda x: (-x["n_notice"], -x["n_incidents"], x["app"]))[:60]],
        # 真正值得盯的一档：跨年度再次违规
        "cross_year": [row(a) for a in sorted(
            cross_year, key=lambda x: (-x["span_days"], x["app"]))[:40]],
        "multi_org": [{"app": a["app"], "dev": a["dev"], "orgs": a["orgs"],
                       "n": a["n_incidents"], "probs": a["probs"], "cls": a["_rc"],
                       "first": a["first"], "last": a["last"]}
                      for a in sorted(rep, key=lambda x: (-x["n_orgs"], -x["n_incidents"]))
                      if a["n_orgs"] > 1][:40],
    }
    for a in apps:
        a.pop("_rc", None)

    # ---------- ⑥ 实体消解的边界情况（治理情报） ----------
    # 这两组恰恰是「不能只按应用名去重」的证据：同名不同主体如果被合并，
    # 会把两家公司的风险算到一家头上；中英署名并存如果被当成两款，
    # 又会把同一家的整改情况拆散。
    col = defaultdict(list)
    xlang = defaultdict(list)
    for a in apps:
        if a.get("name_collision"):
            col[a["ak"]].append({"app": a["app"], "dev": a["dev"],
                                 "n": a["n_incidents"], "first": a["first"],
                                 "probs": a["probs"][:3]})
        if a.get("cross_lang"):
            xlang[a["ak"]].append({"app": a["app"], "dev": a["dev"],
                                   "n": a["n_incidents"], "first": a["first"]})
    collisions = [{"key": k, "group": v} for k, v in
                  sorted(col.items(), key=lambda kv: (-len(kv[1]), kv[0]))
                  if len(v) >= 2][:40]
    cross_lang = [{"key": k, "group": v} for k, v in
                  sorted(xlang.items(), key=lambda kv: (-len(kv[1]), kv[0]))
                  if len(v) >= 2][:30]

    # ---------- ⑦ 执法强度 ----------
    intensity = []
    for r in org_rows:
        if not r["docs"]:
            continue
        intensity.append({
            "org": r["org"], "scope": r["scope"], "docs": r["docs"],
            "entries": r["entries"], "apps": r["apps"],
            "avg_entries": round(r["entries"] / r["docs"], 1),
            "remove_ratio": pct(r["kinds"].get("下架处置", 0), r["docs"]),
            "active_years": len([1 for y in years if r["by_year"].get(y)]),
            "by_year": r["by_year"],
        })
    intensity.sort(key=lambda x: -x["docs"])

    # ---------- ⑦ 问题类型 × 年份 ----------
    prob_year = defaultdict(Counter)
    prob_total = Counter()
    for a in apps:
        for inc in a["incidents"]:
            y = (inc.get("date") or "")[:4] or "未知"
            for p in inc["probs"]:
                prob_year[p][y] += 1
                prob_total[p] += 1
    prob_rows = []
    for p, c in prob_total.most_common():
        prob_rows.append({"prob": p, "total": c,
                          "by_year": {y: prob_year[p].get(y, 0) for y in years}})

    # ---------- ⑧ 属地方向 × 年份 ----------
    prov_year = []
    pv = defaultdict(Counter)
    for d in docs:
        p = d.get("province") or ("国家层面" if d.get("scope") == "国家" else "未标注")
        if yr(d):
            pv[p][yr(d)] += 1
    for p, c in sorted(pv.items(), key=lambda kv: -sum(kv[1].values())):
        prov_year.append({"province": p, "total": sum(c.values()),
                          "by_year": {y: c.get(y, 0) for y in years}})

    out = {
        "meta": {
            "updated": json.load(open(os.path.join(OUTDIR, "date_audit.json"),
                                      encoding="utf-8"))["updated"]
            if os.path.exists(os.path.join(OUTDIR, "date_audit.json"))
            else "",
            "documents": len(docs),
            "years": years,
            "orgs": len(org_rows),
            "date_year_only": sum(1 for d in docs if d.get("date_precision") == "year"),
            "date_exact": sum(1 for d in docs if d.get("date_precision") == "day"),
            "note": "机构维度已把联合通报按发布机关拆分并等分计数；"
                    "文书类型分列，未把「整改复核 / 下架处置」并入「批次通报」。",
        },
        "entity": est,
        "year_summary": year_summary,
        "org_year": {"years": years, "rows": org_rows[:60]},
        "carrier_year": carrier_year,
        "kind_year": kind_year,
        "repeat": repeat,
        "collisions": collisions,
        "cross_lang": cross_lang,
        "intensity": intensity[:40],
        "prob_year": {"years": years, "rows": prob_rows[:24]},
        "province_year": prov_year[:40],
    }
    p = os.path.join(OUTDIR, "analytics.json")
    if "--out" in argv:
        p = argv[argv.index("--out") + 1]
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"✓ 写入 {p}　{os.path.getsize(p)//1024} KB")
    print(f"  年份 {years}")
    print(f"  机构 {len(org_rows)} 家　文书 {len(docs)}")
    print(f"  实体：{est['apps']} 款（重复出现 {est['apps_repeat']}，"
          f"其中纯通报≥2次 {est['apps_repeat_notice']}，跨机构 {est['apps_multi_org']}）")
    print(f"  重复分层 {repeat['by_class']}　跨年度再犯 {repeat['cross_year_apps']} 款")
    print(f"  相邻事件间隔中位 {repeat['gap_median']} 天　分布 {repeat['gap_buckets']}")
    print(f"  同名不同主体 {len(collisions)} 组　中英署名并存 {len(cross_lang)} 组")
    print(f"  治理动作 {[(k['kind'], k['total']) for k in kind_year]}")
    print(f"  文书类型年度（{years[-4:]} 示例）")
    for y in year_summary[-4:]:
        print(f"    {y['year']}  文书{y['docs']:>4}  机构{y['orgs']:>3}(新{y['new_orgs']:>2})"
              f"  条目{y['entries']:>5}  {y['kinds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
