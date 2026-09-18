#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建 `analysis/app-violations.html` —— 移动应用违规治理专项看板
================================================================================
【这一页回答什么问题】
  不是「我们收集了多少数据」，而是**监管怎么在管、我们该盯什么**：
    谁在管 → 管得勤不勤 → 管到哪一步 → 重复被点名的是谁、隔多久、加重了没有。
  因此分析维度的顺序是治理决策链的顺序，而不是数据表的顺序。

【监管层级（2026-09-18 用户口径，本页结构由它决定）】
  顶层监管部门只有三个：**网信办 / 公安部 / 工业和信息化部**。
  国家互联网应急中心、国家计算机病毒应急处理中心、公安部第三研究所检测中心
  都是这三个部门的**技术支撑 / 检测单位**，不是与三部并列的监管主体。
  旧版把五者平铺成一层「国家层面 · 监管部门」，正是用户指出的「分不清」。
  新结构：第 1 节按三层呈现（顶层部门 → 技术支撑单位 / 地方监管层 / 行业组织），
  每张顶层部门卡直接挂「本体系已入库多少份文书」——体量落到体系上，而不是落到机构清单上。

【数字可点击（2026-09-18 用户要求「驾驶舱所有数字应该可以点击」）】
  凡数字即入口，落点是**同一页的文书明细表**并按该维度过滤：
    矩阵单元格 → org + year 条件；年度 / 类型 / 载体 / 问题 / 属地同理。
  交互层在 assets/dash.js（hash 驱动，可分享、可后退）；明细行带 data-* 供其过滤。
  ⚠️ 只把「文书数口径」的数字做成过滤入口；「明细条目数」「涉及应用数」是另外两种口径，
     点进去会对不上，故仍为纯读数（悬停有 title 说明）。

【去重口径（本页最容易被误读的地方，必须显式声明）】
  不按应用名简单去重。两层：
    ① 实体层：归一化应用名 + 运营者主干。仅空格/全半角/标点/装饰后缀差异、
       名称微差但同一运营者 → 合并；**同名但运营者主干不同 → 不合并**（同名不同
       主体，另行列出）；中英文署名并存 → 不强行合并，标记后并列展示。
    ② 事件层：一次通报 = 一个事件，键为 (机构, 年份, 批次)。同一机构同一批次把
       同一应用列两遍只计一次；保留跨机构、跨批次、跨时间的再次通报 —— 那才是
       「重复上榜」，是治理信号而不是噪声。
  再往上一层把事件按文书类型拆开：批次通报 / 整改复核 / 下架处置分开计数，
  避免把同一次治理链条的三个环节算成三次独立通报。

【数据来源】
  sources/appviol/docs.json       通报文书 + 明细（tools/harvest_app_violations.py）
  sources/appviol/analytics.json  治理导向聚合（tools/appviol_analytics.py）
  sources/appviol/date_audit.json 发布日期回填质量（tools/backfill_appviol_dates.py）
  sources/special/registry.json   发布主体层级登记表（人工维护，谁在通报）
================================================================================
"""
import os
import re
from urllib.parse import quote

from spec_common import (APPV, REG, COMMON_CSS, bars, esc, f2, kpi, link,
                         load, num, num_a, page, registry_tiers, sec, system_of)


def _flt(**kw):
    """过滤条件串（与 assets/dash.js 的 FIELDS 对齐）。"""
    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in kw.items() if v)


def _years_head(years, first_col="发布主体"):
    th = f'<th class="lft">{esc(first_col)}</th>'
    th += "".join(f"<th>{esc(y)}</th>" for y in years)
    th += '<th class="lft">合计</th>'
    return th


def timeline(a):
    """再犯时间线：一次通报一个方块，颜色区分处置类型（红块＝已走到下架）。"""
    kk = {"批次通报": "", "整改复核": "f", "下架处置": "c"}
    out = []
    for inc in a.get("incidents", [])[:14]:
        cls = kk.get(inc.get("kind") or "", "")
        d = (inc.get("date") or "")[:10] or "日期未载"
        out.append(f'<i class="{cls}" title="{esc(d)}　{esc(inc.get("org",""))}　'
                   f'{esc(inc.get("kind",""))}"></i>')
    span = ""
    if a.get("first"):
        span = (f'<em>{esc(a["first"][:10])} → {esc((a.get("last") or "")[:10])}'
                f'　均间隔 {a.get("_gap") or "—"} 天</em>')
    return '<div class="sp-tk">' + "".join(out) + span + "</div>"


def _junk_app(name):
    """明显不是应用名的解析残渣：附表标题被当成应用（如「附件1」「附表2」）。

    ⚠️ 只在这两张「点名榜」上滤掉显示，**不动库里的数据** —— 全库 4,592 款里这类
    残渣不足 10 条，若在实体消解层删会造成口径漂移；在榜上显示则直接损害可信度。
    """
    return bool(re.match(r"^(附件|附表|名单|序号|表)\s*\d*$", (name or "").strip()))


def build_appviol():
    d = load(os.path.join(APPV, "docs.json"))
    docs = d.get("docs") or []
    meta = d.get("meta") or {}
    an = load(os.path.join(APPV, "analytics.json"))
    da = load(os.path.join(APPV, "date_audit.json"))
    reg = load(REG).get("app") or {"tiers": []}

    if not docs or not an:
        return page("移动应用违规治理专项", "移动应用违规治理专项通报历史库",
                    "移动应用看板", "移动应用违规治理专项",
                    "数据正在采集。", '<div class="sp-note">数据文件尚未生成。</div>',
                    COMMON_CSS, parent="法律分析")

    est = an.get("entity") or {}
    ys = an.get("year_summary") or []
    years = (an.get("meta") or {}).get("years") or []
    rep = an.get("repeat") or {}
    org_rows = (an.get("org_year") or {}).get("rows") or []
    carriers = an.get("carrier_year") or []
    kinds = an.get("kind_year") or []
    inten = an.get("intensity") or []
    prob_year = an.get("prob_year") or {}
    prov_year = an.get("province_year") or []
    cur_year = years[-1] if years else ""
    last_full = years[-2] if len(years) > 1 else ""

    # ---------------------------------------------------------------- 体系口径
    # 每个顶层部门「本体系已入库多少份文书」—— 由发布主体名归属，不靠关键词扫正文。
    sys_docs, sys_orgs = {}, set()
    for x in docs:
        s = system_of(x.get("org") or "")
        sys_docs[s] = sys_docs.get(s, 0) + 1
        if s != "其他":
            sys_orgs.add(x.get("org"))
    per_org = {}
    for x in docs:
        per_org[x.get("org")] = per_org.get(x.get("org"), 0) + 1

    def cover(org, nd=None):
        """给层级树上的节点挂「已入库 N 份」。"""
        if org in ("国家互联网信息办公室", "国家网信办"):
            return sys_docs.get("网信办", 0), True
        if org == "公安部":
            return sys_docs.get("公安部", 0), True
        if org == "工业和信息化部":
            return sys_docs.get("工信部", 0), True
        n = per_org.get(org)
        return (n if n is not None else 0), True

    # ============================================================ KPI（全部可点）
    kpis = [
        (num(meta.get("documents", len(docs))), "通报文书",
         "发布机关官网原文页，按 URL 去重", "#sec-docs"),
        (num(est.get("apps", 0)), "去重涉及应用",
         "实体消解后，对外引用用这个", "#sec-repeat"),
        (num(est.get("apps_repeat", 0)), "重复被通报",
         f'占 {round(est.get("apps_repeat",0)/max(est.get("apps",1),1)*100)}%',
         "#sec-repeat"),
        (num(rep.get("cross_year_apps", 0)), "跨年度再犯",
         "整改周期走完后再次违规 ★重点", "#sec-crossyear"),
        (f'{num(len(org_rows))} 家', "发布主体",
         f'{esc(years[0]) if years else "—"}—{esc(cur_year)}', "#sec-reg"),
        (num(sys_docs.get("公安部", 0)), "公安部体系已入库",
         "技术支撑单位对外通报，本站已接入", "#sec-reg"),
    ]
    body = ['<div class="sp-kpi">' + "".join(
        f'<a class="sp-k" href="{u}"><b>{v}</b><span>{l}</span>'
        f'<em>{esc(e)}</em></a>' for v, l, e, u in kpis) + "</div>",
        '<p class="sp-src" style="margin:6px 0 0">本页带虚线下划线的数字均可点击 —— '
        '落点是页末「通报文书索引」并按该维度过滤。'
        '<a href="#sec-method">口径声明（8 条）</a></p>']

    # ============================================================ 1 监管体系
    cards = []
    for key, zh, ds in (("网信办", "国家网信办体系", "统筹协调 · 牵头专项治理"),
                        ("公安部", "公安部体系", "网安局 + 技术支撑 / 检测单位"),
                        ("工信部", "工业和信息化部体系", "行业管理 · 体量最大")):
        cards.append(
            '<div class="sp-k" style="--x:0">'
            f'<b>{num(sys_docs.get(key,0))}</b><span>{esc(zh)}</span>'
            f'<em>{esc(ds)}</em></div>')
    body.append(sec(
        "谁在管 —— 三个顶层部门与它们的技术支撑单位",
        "顶层监管部门只有三个；病毒中心、应急中心、三所检测中心分别是它们的技术支撑 / "
        "检测单位，不与之并列。每张卡下方列出该体系已接入的发布序列。",
        '<div class="sp-kpi" style="margin:0 0 4px">' + "".join(cards) + "</div>"
        + registry_tiers(reg.get("tiers") or [], cover),
        sid="sec-reg"))

    # ============================================================ 2 主体 × 年度
    mxx = max((max((r["by_year"].get(y, 0) for y in years), default=0)
               for r in org_rows), default=1) or 1
    rows = []
    for r in org_rows[:40]:
        org = r["org"]
        t = r["total"]
        f1 = _flt(org=org)
        cells = "".join(
            _cell(r["by_year"].get(y, 0), mxx, _flt(org=org, y=y),
                  f'{org} · {y} 年') for y in years)
        rows.append(
            "<tr>"
            f'<td class="lft"><b style="color:var(--ink)">'
            f'{num_a(org, flt=f1, title=f"筛出 {org} 的通报文书")}</b>'
            + ('<span class="sp-pill on">新</span>' if r["first"] == cur_year else "")
            + f'<div class="sp-src">{esc(r["scope"])}'
              + (f'　{esc(r["provinces"][0])}' if r.get("provinces") else "")
              + f'　{esc(r["first"])} 起　体系 {esc(system_of(org))}</div></td>'
            + cells
            + f'<td class="tt">{num_a(f2(t), flt=f1, title="该主体全部文书")}</td>'
            + "</tr>")
        rows.append(
            f'<tr><td class="lft" style="padding-top:0;font-size:12px;color:var(--faint)">'
            f'　涉及应用 {num(r["apps"])} 款　明细 {num(r["entries"])} 条　'
            f'文书均 {f2(r["avg_entries"])} 条</td>'
            + '<td colspan="%d" style="background:#fbfcfe"></td>' % (len(years) + 1) + "</tr>")
    body.append(sec(
        "发布主体 × 年度 —— 谁在管得勤",
        "格内为该主体当年发布的通报表文书数（联合通报按发布机关拆分后等分计数）。"
        "底色越深＝当年通报越密集，灰点＝当年无通报。「新」＝首次发布即在最近年度。",
        '<div class="sp-wrap sp-lim"><table class="sp-mx"><thead><tr>'
        + _years_head(years) + "</tr></thead><tbody>" + "".join(rows)
        + "</tbody></table></div>"
        + '<div class="sp-legend">'
          '<span><i style="background:rgba(44,111,178,0.10)"></i>少量</span>'
          '<span><i style="background:rgba(44,111,178,0.22)"></i>中等</span>'
          '<span><i style="background:rgba(44,111,178,0.37)"></i>密集</span>'
          '<span><i style="background:#fff;border:1px solid var(--line)"></i>无通报</span>'
          '<span>点任意数字 → 下方明细按「主体 + 年度」过滤</span></div>',
        sid="sec-orgyear"))

    # ============================================================ 3 年度总览
    yrows = []
    for y in ys:
        kk = y["kinds"]
        yy = y["year"]
        fy = _flt(y=yy)
        yrows.append(
            "<tr>"
            f'<td class="lft"><b>{num_a(yy, flt=fy, title=f"筛出 {yy} 年全部文书")}</b></td>'
            f'<td><b>{num_a(num(y["docs"]), flt=fy, title="该年度文书数")}</b></td>'
            f'<td>{num(y["orgs"])}'
            + (f'<span class="sp-pill on">+{y["new_orgs"]}</span>' if y["new_orgs"] else "")
            + "</td>"
            f'<td>{num(y["entries"])}</td>'
            f'<td>{num_a(num(kk.get("批次通报", 0)), flt=_flt(y=yy, k="批次通报"))}</td>'
            f'<td>{num_a(num(kk.get("整改复核", 0)), flt=_flt(y=yy, k="整改复核"))}</td>'
            f'<td>{num_a(num(kk.get("下架处置", 0)), flt=_flt(y=yy, k="下架处置"))}</td>'
            f'<td class="lft">'
            + "、".join(num_a(nm, flt=_flt(org=nm)) for nm in y["new_org_names"][:3])
            + ('<span class="sp-src">…</span>' if len(y["new_org_names"]) > 3 else "")
            + "</td></tr>")
    body.append(sec(
        "年度总览 —— 通报量、参与主体与首次进场者",
        f"「新进主体」＝该年度首次出现在本库中的发布机关；{esc(cur_year)} 年为不完整年度。"
        f"⚠️「明细条目」是条目口径（一份文书点 N 次名），与文书数不是一回事，故不做过滤入口。",
        '<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
        "<th>年度</th><th>通报文书</th><th>发布主体</th><th>明细条目</th>"
        "<th>批次通报</th><th>整改复核</th><th>下架处置</th><th>当年新进主体</th>"
        "</tr></thead><tbody>" + "".join(yrows) + "</tbody></table></div>",
        sid="sec-year"))

    # ============================================================ 4 治理动作
    cards = []
    for k in kinds:
        kn = k["kind"]
        rowsb = sorted(k["by_year"].items())
        cards.append(
            f'<div class="sp-card"><h4>{esc(kn)}　'
            f'<span class="sp-src">{num_a(num(k["total"]), flt=_flt(k=kn), title="筛出该类型全部文书")}'
            f' 份 / {num(k["entries"])} 条</span></h4>'
            + _bars_click(rowsb, kn)
            + '<p class="sp-src" style="margin-top:10px">'
            + {"批次通报": "发现问题的第一道关口，按批次滚动发布。",
               "整改复核": "对已点名应用复查是否整改到位，名单与前批次重合。",
               "下架处置": "复核仍未整改的，走到应用商店下架这一步 —— 处置刚性最强。",
               }.get(kn, "")
            + "</p></div>")
    body.append(sec(
        "治理动作 × 年度 —— 监管走到哪一步了",
        "同一应用在监管链条上依次经历「批次通报 → 整改复核 → 下架处置」。"
        "分开看三类年度构成，可以判断通报是在广撒网点名，还是已进入强制处置。",
        '<div class="sp-2col">' + "".join(cards) + "</div>", sid="sec-kind"))

    # ============================================================ 5 渠道 × 年度
    cmx = max((max((c["by_year"].get(y, 0) for y in years), default=0) for c in carriers),
              default=1) or 1
    crows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">'
        f'{num_a(c["label"], flt=_flt(c=c["carrier"]), title=f"筛出载体为「{c['label']}」的文书")}'
        f'</b><div class="sp-src">{num(c["total"])} 份　明细 {num(c["entries"])} 条</div></td>'
        + "".join(_cell(c["by_year"].get(y, 0), cmx, _flt(c=c["carrier"], y=y),
                        f'{c["label"]} · {y}') for y in years)
        + f'<td class="tt">{num_a(num(c["total"]), flt=_flt(c=c["carrier"]))}</td></tr>'
        for c in carriers)
    body.append(sec(
        "名单挂在什么载体上 —— 渠道 × 年度",
        "载体决定监测成本：HTML 表格可直接解析；部委附件 PDF 要下载且续表易丢行；"
        "名单图只能 OCR（最易漏）；正文内嵌最零散。这是「我们的监测手段能不能覆盖」的直接依据。",
        '<div class="sp-wrap"><table class="sp-mx"><thead><tr>'
        + _years_head(years, "名单载体") + "</tr></thead><tbody>" + crows
        + "</tbody></table></div>"
        + f'<p class="sp-src" style="margin-top:10px">'
          f'全库 {num(meta.get("documents", 0))} 份中 '
          f'{num(meta.get("docs_with_entries", 0))} 份已结构化出应用明细；'
          f'其余 {num(meta.get("documents", 0) - meta.get("docs_with_entries", 0))} 份为'
          f'「批次级」（正文未列结构化名单，或以图片 / 外链给出）—— 仍计入主体通报量，'
          f'但不贡献应用明细。</p>',
        sid="sec-carrier"))

    # ============================================================ 6 重复被通报
    gb = rep.get("gap_buckets") or {}
    rep_kpi = [
        (num(rep.get("apps", 0)), "重复出现", "≥2 个通报事件"),
        (num(rep.get("chain_apps", 0)), "同一轮链条内", "间隔 ≤90 天：通报→复核→下架"),
        (num(rep.get("cross_year_apps", 0)), "跨年度再犯", "★重点"),
        (num(rep.get("apps_multi_org", 0)), "跨机构被通报", "两家以上机关分别点名"),
        (num(rep.get("apps_escalated", 0)), "升级到下架", "点名通报一路走到商店下架"),
        (num(rep.get("apps_new_prob", 0)), "再通报时添新问题", "老问题未改又添新问题"),
    ]
    gbmax = max(gb.values()) if gb else 1
    gaprows = "".join(
        f'<tr><td class="lft">{esc(k)}</td><td><b>{num(v)}</b></td>'
        f'<td><span class="sp-tk"><i style="width:{max(2, round(v/gbmax*100))}px'
        f';height:11px"></i></span></td></tr>' for k, v in gb.items())

    def rep_row(a, show_cls=True):
        gaps = a.get("gaps") or []
        g = (sum(gaps) // len(gaps)) if gaps else 0
        prob = a.get("probs") or []
        tags = "".join(f'<span class="sp-tag">{esc(p)}</span>' for p in prob[:3]) \
            or '<span class="sp-src">—</span>'
        newp = a.get("new_probs") or []
        cls = a.get("cls") or ""
        badge = {"cross_year": '<span class="sp-tag r">跨年度再犯</span>',
                 "cross_year_year": '<span class="sp-tag r">跨年（按年判定）</span>',
                 "half": '<span class="sp-tag w">半年以上</span>',
                 "months": '<span class="sp-tag w">3—6 个月</span>',
                 "chain": '<span class="sp-tag">同轮链条</span>'}.get(cls, "") if show_cls else ""
        orgs = a.get("orgs") or []
        return (
            "<tr>"
            f'<td><b style="color:var(--ink)">{esc(a["app"])}</b>{badge}</td>'
            f'<td><span class="sp-src">{esc((a.get("dev") or "—")[:30])}</span></td>'
            f'<td><b style="color:var(--accent)">{num(a.get("n", 0))}</b>'
            f'<div class="sp-src">通报 {num(a.get("n_notice", 0))}</div></td>'
            f'<td>{timeline(dict(a, _gap=g))}</td>'
            f'<td><span class="sp-src">'
            + "、".join(num_a(o, flt=_flt(org=o), title=f"筛出 {o} 的文书")
                        for o in orgs[:2])
            + (f' 等 {len(orgs)} 家' if len(orgs) > 2 else "")
            + "</span></td>"
            f'<td>{tags}'
            + (f'<div style="margin-top:3px"><span class="sp-tag w">新增 {len(newp)}</span>'
               f'<span class="sp-src">{esc("、".join(newp[:2]))}</span></div>' if newp else "")
            + "</td></tr>")

    trows = "".join(rep_row(a) for a in (rep.get("top") or [])
                     if not _junk_app(a.get("app")))
    cy_clean = [a for a in (rep.get("cross_year") or [])
                if not _junk_app(a.get("app"))]
    body.append(sec(
        f"重复被通报的应用 —— 谁在被反复点名（{num(rep.get('apps', 0))} 款）",
        f"同一应用在一轮治理里会先后出现在「批次通报 → 整改复核 → 下架处置」三步中，"
        f"看上去像被通报三次，实际是监管在跟进同一件事 —— 相邻事件间隔中位数仅 "
        f"{num(rep.get('gap_median', 0))} 天。真正需要重点盯的是"
        f"<b>跨年度再次违规的 {num(rep.get('cross_year_apps', 0))} 款</b>（下一节）。"
        f"时间线方块：浅蓝＝批次通报，黄＝整改复核，红＝下架处置。",
        kpi(rep_kpi)
        + '<div class="sp-2col" style="margin-top:16px">'
        + f'<div class="sp-card"><h4>相邻两次事件的间隔分布</h4>'
          f'<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
          f"<th>间隔</th><th>次数</th><th></th></tr></thead><tbody>{gaprows}</tbody></table></div>"
          f'<p class="sp-src" style="margin-top:10px">「≤3 个月」绝大多数是同一轮链条里的'
          f"复核与下架，不算再犯；「1 年以上」才是整改周期走完后再次违规。</p></div>"
        + '<div class="sp-card"><h4>重复事件的次数分布</h4>'
        + bars([(f'{k} 次', v) for k, v in sorted((rep.get("by_incidents") or {}).items(),
                                                 key=lambda kv: int(kv[0]))], 12)
        + '<p class="sp-src" style="margin-top:10px">被通报 2 次的是绝大多数；'
          '次数越高，说明整改越不彻底。</p></div>'
        + "</div>"
        + f'<h4 style="margin:22px 0 8px;font-size:15px;color:var(--ink)">'
          f'按「轮次通报次数」排序（前 {len(rep.get("top") or [])} 款）</h4>'
        + '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
          "<th>应用</th><th>运营者</th><th>事件数</th><th>通报时间线</th><th>涉及发布主体</th>"
          "<th>问题类型</th></tr></thead><tbody>" + trows + "</tbody></table></div>",
        sid="sec-repeat"))

    # 跨年度再犯
    cy = cy_clean
    if cy:
        body.append(sec(
            "跨年度再犯 —— 整改周期走完之后又被点名",
            "剔除「同一轮链条内跟进」后剩下的这一档：间隔一年以上再次被点名，"
            "说明上一轮整改没有形成长效机制。数量不大但治理价值最高，"
            "建议作为内部自查的优先样本。",
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>应用</th><th>运营者</th><th>事件数</th><th>通报时间线</th><th>发布主体</th>"
            "<th>问题类型</th></tr></thead><tbody>"
            + "".join(rep_row(a, show_cls=False) for a in cy)
            + "</tbody></table></div>",
            sid="sec-crossyear"))

    # ============================================================ 7 实体消解边界
    col = an.get("collisions") or []
    xl = an.get("cross_lang") or []
    if col or xl:
        def ent_rows(groups, with_probs):
            out = []
            for g in groups:
                mem = g["group"]
                who = []
                for m in mem:
                    extra = ""
                    if with_probs and m.get("probs"):
                        extra = ('<span class="sp-src">　'
                                 + esc("、".join(m["probs"][:2])) + "</span>")
                    who.append(f'<div>· {esc(m.get("dev") or "（通报未载运营者）")}'
                               f'<span class="sp-src">　{m.get("n", 0)} 次</span>{extra}</div>')
                out.append(
                    "<tr>"
                    f'<td><b style="color:var(--ink)">{esc(mem[0].get("app") or g["key"])}</b></td>'
                    f'<td><b>{len(mem)}</b></td>'
                    f'<td>{"".join(who)}</td>'
                    "</tr>")
            return "".join(out)

        body.append(sec(
            "实体消解的边界 —— 为什么「同名」不等于「同一款」",
            "<b>同名不同主体</b>＝同一应用名对应两家以上互不相同的运营者（山寨蹭名，"
            "或通报方署名不统一），不能把两家的风险算到一家头上；"
            "<b>中英署名并存</b>＝同一款应用在不同通报里分别用中文名与英文名署名，"
            "字面无法确认是否同一主体，不强行合并、并列展示。",
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>应用名（同名）</th><th>主体数</th><th>各自运营者署名 / 被通报次数</th>"
            "</tr></thead><tbody>" + ent_rows(col, True) + "</tbody></table></div>"
            + (f'<h4 style="margin:22px 0 8px;font-size:15px;color:var(--ink)">'
               f'中英署名并存（{len(xl)} 组）</h4>'
               '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
               "<th>应用名</th><th>署名数</th><th>运营者署名</th>"
               "</tr></thead><tbody>" + ent_rows(xl, False) + "</tbody></table></div>"
               if xl else ""),
            sid="sec-ent"))

    # 被不同机构分别点名
    morows = "".join(
        "<tr>"
        f'<td><b style="color:var(--ink)">{esc(a["app"])}</b></td>'
        f'<td><span class="sp-src">{esc((a.get("dev") or "—")[:32])}</span></td>'
        f'<td><b>{len(a.get("orgs", []))}</b></td>'
        f'<td><span class="sp-src">'
        + "、".join(num_a(o, flt=_flt(org=o)) for o in (a.get("orgs") or []))
        + "</span></td>"
        f'<td>{num(a.get("n", 0))}</td>'
        "</tr>" for a in (rep.get("multi_org") or [])
        if not _junk_app(a.get("app")))
    if morows:
        body.append(sec(
            "跨机构通报 —— 被不同机构分别点名",
            "同一款应用被两家以上发布机关独立点名，说明问题跨属地或在国家与地方两级同时"
            "暴露。单点整改无法闭环，需按最高标准统一整改。",
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>应用</th><th>运营者</th><th>机构数</th><th>发布主体</th><th>事件数</th>"
            "</tr></thead><tbody>" + morows + "</tbody></table></div>",
            sid="sec-multi"))

    # ============================================================ 8 执法强度
    irows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">'
        f'{num_a(r["org"], flt=_flt(org=r["org"]))}</b>'
        f'<div class="sp-src">{esc(r["scope"])}　活跃 {r["active_years"]} 个年度　'
        f'体系 {esc(system_of(r["org"]))}</div></td>'
        f'<td>{num_a(num(r["docs"]), flt=_flt(org=r["org"]))}</td>'
        f'<td>{num(r["entries"])}</td><td>{num(r["apps"])}</td>'
        f'<td>{f2(r["avg_entries"])}</td>'
        f'<td>{f2(r["remove_ratio"])}%</td>'
        f'<td><span class="sp-src">'
        + "".join(f'{y}:{f2(r["by_year"].get(y,0))}　' for y in years[-3:])
        + "</span></td></tr>" for r in inten[:26])
    body.append(sec(
        "发布主体的产出与风格 —— 执法强度",
        "「条文均」＝每份文书平均点名多少款应用：高＝一次列一大批（多见于国家层面），"
        "低＝分批小步推进（多见于省局）。「下架比」＝下架处置类占比，反映处置刚性。",
        '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
        "<th>发布主体</th><th>文书</th><th>明细条目</th><th>涉及应用</th><th>条文均</th>"
        f"<th>下架比</th><th>近三年（{' / '.join(years[-3:])}）</th>"
        "</tr></thead><tbody>" + irows + "</tbody></table></div>",
        sid="sec-inten"))

    # ============================================================ 9 问题 × 年度
    py = [r for r in (prob_year.get("rows") or []) if r["total"] >= 5][:18]
    pmx = max((max((r["by_year"].get(y, 0) for y in years), default=0) for r in py),
              default=1) or 1
    prows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">'
        f'{num_a(r["prob"], flt=_flt(prob=r["prob"]), title=f"筛出涉及「{r['prob']}」的文书")}'
        f'</b></td>'
        + "".join(_cell(r["by_year"].get(y, 0), pmx, _flt(prob=r["prob"], y=y),
                        f'{r["prob"]} · {y}') for y in years)
        + f'<td class="tt">{num_a(num(r["total"]), flt=_flt(prob=r["prob"]))}</td></tr>'
        for r in py)
    body.append(sec(
        "问题类型 × 年度 —— 监管关注点在怎么变",
        "按《App 违法违规收集使用个人信息行为认定方法》的认定行为归并（一项应用可涉及多个"
        "类型，故合计大于应用数）。看某一列的颜色分布就能读出当年在集中打什么。",
        '<div class="sp-wrap sp-lim"><table class="sp-mx"><thead><tr>'
        + _years_head(years, "问题类型") + "</tr></thead><tbody>" + prows
        + "</tbody></table></div>"
        + '<p class="sp-src" style="margin-top:8px">仅列累计 ≥5 次的类型；'
          '未归并到标准类目的零散表述不在此列。</p>',
        sid="sec-prob"))

    # ============================================================ 10 属地 × 年度
    vmx = max((max((r["by_year"].get(y, 0) for y in years), default=0) for r in prov_year),
              default=1) or 1
    vrows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">'
        f'{num_a(r["province"], flt=_flt(p=r["province"]), title=f"筛出属地 {r['province']} 的文书")}'
        f'</b></td>'
        + "".join(_cell(r["by_year"].get(y, 0), vmx, _flt(p=r["province"], y=y),
                        f'{r["province"]} · {y}') for y in years)
        + f'<td class="tt">{num_a(num(r["total"]), flt=_flt(p=r["province"]))}</td></tr>'
        for r in prov_year[:28])
    body.append(sec(
        "属地方向 × 年度 —— 各地监管的活跃度",
        "省级通信管理局只查属地应用，其序列与国家序列互不重叠，构成通报库体量的主体。"
        "颜色越深说明该地当年通报越密集 —— 可用来判断某地业务面临的属地监管压力。",
        '<div class="sp-wrap sp-lim"><table class="sp-mx"><thead><tr>'
        + _years_head(years, "属地 / 层级") + "</tr></thead><tbody>" + vrows
        + "</tbody></table></div>",
        sid="sec-prov"))

    # ============================================================ 11 文书索引
    drows = []
    for x in sorted(docs, key=lambda z: (z.get("date") or ""), reverse=True):
        bk = ""
        if x.get("total_batch"):
            bk = f'总第{x["total_batch"]}批'
        elif x.get("batch_seq"):
            bk = f'{x.get("batch_year") or ""}年第{x["batch_seq"]}批'
        elif x.get("quarter"):
            bk = f'第{x["quarter"]}季度'
        prec = ("" if x.get("date_precision") == "day"
                else '<span class="sp-pill">仅到年</span>')
        probs = " ".join(sorted({p for e in (x.get("entries") or [])
                                 for p in (e.get("probs") or []) if p}))
        prov = x.get("province") or ("国家层面" if x.get("scope") == "国家" else "")
        drows.append(
            "<tr data-docrow"
            f' data-org="{esc(x.get("org") or "")}"'
            f' data-y="{(x.get("date") or "")[:4]}"'
            f' data-k="{esc(x.get("notice_kind") or "")}"'
            f' data-p="{esc(prov)}"'
            f' data-c="{esc(x.get("carrier") or "")}"'
            f' data-prob="{esc(probs)}">'
            f'<td style="white-space:nowrap">{esc((x.get("date") or "")[:10])}{prec}</td>'
            f'<td><b style="color:var(--ink)">{esc(x["org"])}</b>'
            f'<div class="sp-src">{esc(x["title"][:90])}</div></td>'
            f'<td><span class="sp-tag">{esc(x["notice_kind"])}</span>'
            + (f'<div class="sp-src" style="margin-top:3px">{esc(bk)}</div>' if bk else "")
            + "</td>"
            f'<td>{num(x.get("declared") or x.get("n_entries") or 0)}</td>'
            f'<td><span class="sp-src">{esc(prov)}</span></td>'
            f'<td>{link(x["url"], "原文")}</td></tr>')
    body.append(sec(
        "通报文书索引（全库）",
        f"全库 {num(len(docs))} 份，逐份链至发布机关官网原文页。"
        "上方的矩阵 / 柱条数字点下来即在此过滤。",
        f'<p class="sp-src" style="margin:0 0 6px">当前命中 '
        f'<b id="docCnt">{num(len(docs))}</b> 份</p>'
        '<div class="sp-wrap" style="max-height:min(78vh,900px)">'
        '<table class="sp-tbl" id="docTbl"><thead><tr>'
        "<th>日期</th><th>发布主体 / 标题</th><th>类型 / 批次</th><th>涉及款数</th>"
        "<th>属地</th><th>原文</th></tr></thead><tbody>" + "".join(drows)
        + '</tbody></table></div><p id="docEmpty" hidden class="sp-src"'
          ' style="margin-top:8px">当前条件下没有匹配文书。</p>',
        sid="sec-docs"))

    # ============================================================ 口径声明（附录）
    note = [
        '<details class="sp-note sp-warn sp-fold" id="sec-method"><summary>'
        '<b>口径声明 —— 本页所有数字怎么算出来的</b>（8 条，点击展开）</summary>',
        f'<p class="sp-fold-tldr">对外只引用「<b>去重涉及应用 '
        f'{num(est.get("apps", 0))} 款</b>」这一个数：文书数 '
        f'{num(meta.get("documents", 0))} 份与明细条目 {num(est.get("rows_raw", 0))} 条'
        f'是过程量，<b>不可与非本页出处混用</b>。'
        f'带虚线下划线的数字均可点击，落点为页末文书明细。</p>',
        "<ul>",
        f"<li><b>① 去重不只看应用名。</b>先做实体消解：仅"
        f"「空格 / 全半角 / 标点 / 装饰后缀（APP·安卓版·手机版）」差异、或名称微差但"
        f"<b>运营者主干相同</b>的，合并为一款；<b>同名但运营者主干不同</b>的"
        f"<b>不合并</b>（这类共 {num(est.get('apps_name_collision',0))} 项，单列在"
        f"「实体消解的边界」），中英文署名并存的 {num(est.get('apps_cross_lang',0))} 项"
        f"并列展示不强行合并。实测仅靠应用名归并会把不同公司的同名产品并成一款，"
        f"也会因 PDF 提取插入的空格（「有限公 司」）把同一家拆成两个主体。</li>",
        f"<li><b>② 三层口径。</b>文书 {num(meta.get('documents',0))} 份（发生了什么）→ "
        f"明细条目 {num(est.get('rows_raw',0))} 条（点了多少次名）→ "
        f"<b>去重涉及应用 {num(est.get('apps',0))} 款</b>（到底涉及多少款）。"
        f"<b>对外只引用最后一个。</b></li>",
        f"<li><b>③ 事件层再拆一层。</b>一次通报记一个事件，键为（机构 · 年份 · 批次），"
        f"同机构同批次重复出现只计一次。全库 {num(est.get('incidents',0))} 个事件 = "
        f"批次通报类 {num(est.get('incidents_notice',0))} + 整改复核类 "
        f"{num(est.get('incidents_fix',0))} + 下架处置类 {num(est.get('incidents_close',0))}。"
        f"<b>「重复上榜」指的是后两类之外的再次通报</b>，不是把复核、下架也算成新的通报。</li>",
        f"<li><b>④ 本库不含「年度汇总」类文书。</b>App 侧通报表实测只有批次通报、"
        f"整改复核、下架处置三类，<b>没有</b>把全年清单重列一遍的年度汇总公告 —— "
        f"这一点与算法备案侧不同。但「整改复核 + 下架处置」占全部文书 "
        f"{round((est.get('incidents_fix',0)+est.get('incidents_close',0))/max(est.get('incidents',1),1)*100)}%，"
        f"这类文书会重列前批次已点名的应用，<b>所以此前按文书数统计必然重复</b>。</li>",
        f"<li><b>⑤ 日期回填质量如实披露。</b>省局站点的列表接口不返回发布日期，"
        f"本库从页面 <code>PubDate</code> 元数据回填：{num(da.get('exact_day',0))} 份精确到日，"
        f"{num(da.get('year_only',0))} 份只能到年（年度统计可用、月度统计不可用）。"
        f"其中 {num(len(da.get('migrate_days') or {}))} 个站点检出「批量迁移日」"
        f"（多份不同批次的通报被刷成同一天），这些文书的日期已降级为标题所载年份。</li>",
        f"<li><b>⑥「重复出现」有两种含义，不能混为一谈。</b>同一轮治理链条里监管会先"
        f"批次通报、再整改复核、再下架处置，同一款应用因此出现 2—3 次 —— 实测相邻事件的"
        f"间隔中位数只有 <b>{num(rep.get('gap_median',0))} 天</b>，这类「重复」占绝大多数。"
        f"本页把 {num(rep.get('apps',0))} 款重复出现的应用按最长间隔分层："
        f"<b>{num(rep.get('chain_apps',0))} 款属同一轮链条内跟进</b>（间隔 ≤90 天，不算再犯），"
        f"<b>{num(rep.get('cross_year_apps',0))} 款存在跨年间隔</b>（整改周期走完后再次违规，"
        f"单列一节）。</li>",
        "<li><b>⑦ 机构按「一个机关一块牌子」归一，不按署名分家。</b>全国层面的网信办"
        "只立 <b>国家网信办</b> 一个主体：中央网信办（中央网络安全和信息化委员会办公室）"
        "与国家互联网信息办公室是<b>同一机构</b>的两块牌子，通报表常以"
        "「中央网信办秘书局」「国家互联网信息办公室秘书局」署名 —— "
        "<b>秘书局是它的发文机构，不是另一个发布主体</b>。地方网信办按其属地单独计；"
        "联合通报按发布机关拆分等分计数。另剔除 "
        f"{num(meta.get('excluded_non_notice',0))} 份<b>非通报类文书</b>"
        "（挂在监管站上的个人署名文章 / 行业观察），不计入通报量。</li>",
        "<li><b>⑧ 各序列的完整度不一致，如实披露。</b>"
        f"①②③ 三个体系的体量相差极大：工信部体系 {num(sys_docs.get('工信部',0))} 份、"
        f"网信办体系 {num(sys_docs.get('网信办',0))} 份、公安部体系 "
        f"{num(sys_docs.get('公安部',0))} 份。<b>体量差 ≠ 监管强度差</b> —— "
        "工信部体系含 28 个省级通信管理局，是「属地广覆盖」；公安部的技术支撑单位"
        "（三所检测中心）2026 年才开始对外通报，站点只挂出近三期；"
        "病毒中心、公安部网安局、应急中心目前均无稳定可自动采集的 PC 列表页，"
        "本库只登记、不虚报。国家网信办序列的名单以图片发布，OCR 不能可靠还原宽表时"
        "宁可留空 —— 该序列「涉及应用」计数偏低，引用时以文书数为准。</li>",
        "</ul></details>",
    ]
    body.append("".join(note))

    return page(
        "移动应用违规治理专项",
        "移动应用违规治理专项：三个顶层监管部门（网信办 / 公安部 / 工信部）及其技术支撑单位"
        "与省级通信管理局的 App 违规通报汇总。按「应用名 + 运营者」实体消解、按机构与批次"
        "事件去重，给出发布主体 × 年度矩阵、治理动作年度构成、重复被通报时间线与跨机构分析；"
        "矩阵与柱条的每个数字均可点击并落到对应文书明细。",
        "移动应用看板", "移动应用违规治理专项",
        "三个顶层监管部门（网信办 / 公安部 / 工信部）及其技术支撑 / 检测单位与 28 个省级"
        "通信管理局的 App 违规通报原文。去重不只看应用名：按「应用名 + 运营者」实体消解，"
        "再按（机构 · 年份 · 批次）事件去重，把批次通报、整改复核、下架处置分类计数。",
        "".join(body), COMMON_CSS, parent="法律分析")


def _cell(v, mxv, flt="", title=""):
    """热力矩阵单元格：有值即可点击（点它 = 按该主体 / 年度 / 类型过滤明细）。"""
    if not v:
        return '<td class="z">·</td>'
    t = min(1.0, v / mxv) if mxv else 0
    bg = f"rgba(44,111,178,{0.05 + 0.32 * t:.2f})"
    return (f'<td data-flt="{esc(flt)}" title="{esc(title)}" '
            f'style="background:{bg}">{f2(v)}</td>')


def _bars_click(rows, kind):
    """治理动作柱条：每条都是「该类型 + 该年度」的过滤入口。"""
    if not rows:
        return ""
    mx = max(v for _, v in rows) or 1
    out = []
    for lb, v in rows:
        w = max(2, round(v / mx * 100))
        out.append(
            f'<div class="sp-bar" data-flt="{esc(_flt(k=kind, y=lb))}"'
            f' style="cursor:pointer" title="筛出 {esc(kind)} · {esc(lb)} 年的文书">'
            f'<span class="lb">{esc(lb)}</span>'
            f'<span class="tr"><span class="fl" style="width:{w}%"></span></span>'
            f'<span class="vv">{num(v)}</span></div>')
    return "".join(out)
