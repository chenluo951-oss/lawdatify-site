#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建 `news/app-violations.html` —— 移动应用违规治理专项页
================================================================================
【这一页回答什么问题】
  不是「我们收集了多少数据」，而是**监管怎么在管、我们该盯什么**：
    谁在管 → 管得勤不勤 → 管到哪一步 → 重复被点名的是谁、隔多久、加重了没有。
  因此分析维度的顺序是治理决策链的顺序，而不是数据表的顺序。

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
  sources/special/registry.json   发布主体全景登记表（人工维护）
================================================================================
"""
import os

from spec_common import (APPV, REG, COMMON_CSS, bars, esc, f2, kpi, link,
                         load, mx_cell, num, page, registry_group, sec)


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


def build_appviol():
    d = load(os.path.join(APPV, "docs.json"))
    docs = d.get("docs") or []
    meta = d.get("meta") or {}
    an = load(os.path.join(APPV, "analytics.json"))
    da = load(os.path.join(APPV, "date_audit.json"))
    reg = load(REG).get("app") or {"groups": []}

    if not docs or not an:
        return page("移动应用违规治理专项", "移动应用违规治理专项通报历史库",
                    "移动应用违规治理", "移动应用违规治理专项",
                    "数据正在采集。", '<div class="sp-note">数据文件尚未生成。</div>',
                    COMMON_CSS)

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

    # ============================================================ KPI
    kpis = [
        ("通报文书", num(meta.get("documents", len(docs))),
         "发布机关官网原文页，按 URL 去重"),
        ("去重涉及应用", num(est.get("apps", 0)),
         "实体消解后（应用名 + 运营者），对外引用用这个"),
        ("重复被通报", num(est.get("apps_repeat", 0)),
         f'≥2 次通报表彰，占 {round(est.get("apps_repeat",0)/max(est.get("apps",1),1)*100)}%'),
        ("其中被两次以上通报", num(est.get("apps_repeat_notice", 0)),
         "剔除同链条的复核与下架后，仍被两轮点名"),
        ("跨机构通报", num(est.get("apps_multi_org", 0)),
         "被两家以上发布机关分别点名"),
        ("发布主体", f'{num(len(org_rows))} 家',
         f'{esc(years[0]) if years else "—"}—{esc(cur_year)} 共 {len(years)} 个年度'),
    ]

    body = [kpi(kpis)]

    # ============================================================ 口径声明
    note = [
        '<div class="sp-note sp-warn"><b>口径声明 —— 本页所有数字怎么算出来的</b>',
        "<ul>",
        f"<li><b>① 去重不只看应用名。</b>先做实体消解：仅"
        f"「空格 / 全半角 / 标点 / 装饰后缀（APP·安卓版·手机版）」差异、或名称微差但"
        f"<b>运营者主干相同</b>的，合并为一款；<b>同名但运营者主干不同</b>的"
        f"<b>不合并</b>（这类共 {num(est.get('apps_name_collision',0))} 项，单列在下方"
        f"「同名不同主体」），中英文署名并存的 {num(est.get('apps_cross_lang',0))} 项"
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
        f"这一点与算法备案侧不同，因此本页年度计数不存在年度汇总造成的重复。"
        f"但「整改复核 + 下架处置」占全部文书 "
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
        "<b>秘书局是它的发文机构，不是另一个发布主体</b>。按署名拆成三家会把同一个机关的"
        "通报量摊薄，矩阵读起来像三个小机构在管。地方网信办（如浙江省、海南省"
        "互联网信息办公室）按其属地单独计，不并入国家层面；联合通报按发布机关拆分等分计数。"
        f"另剔除 {num(meta.get('excluded_non_notice',0))} 份<b>非通报类文书</b>"
        "（挂在监管站上的个人署名文章 / 行业观察），不计入通报量。</li>",
        "<li><b>⑧ 国家网信办序列的「应用清单」完整度偏低，如实披露。</b>该序列把问题清单"
        "放在<b>名单图</b>里发布，站点改版后部分页面正文已不含名单（实测一份 33 款通报的"
        "HTML 内零表格，名单全在图里），而名单图的宽表版式 OCR 尚不能可靠还原列结构 —— "
        "本库的处理原则是<b>宁可留空，也不塞进错误的名单</b>。故这一序列的文书数与通报量"
        "完整，但<b>「涉及应用」计数明显偏低</b>，引用时请以文书数为准。</li>",
        "</ul></div>",
    ]
    body.append("".join(note))

    # ============================================================ 来源全景
    body.append(sec("谁在通报 —— 发布主体全景",
                    "先把发布主体摸清楚，统计口径才立得住。下表按「国家监管 / 国家协会机构 / "
                    "地方监管」三层列出，并标注本库是否已接入。",
                    registry_group("app", reg.get("groups") or [])))

    # ============================================================ 机构 × 年份
    mxx = max((max((r["by_year"].get(y, 0) for y in years), default=0)
               for r in org_rows), default=1) or 1
    rows = []
    for r in org_rows[:40]:
        t = r["total"]
        rows.append(
            "<tr>"
            f'<td class="lft"><b style="color:var(--ink)">{esc(r["org"])}</b>'
            + ('<span class="sp-pill on">新</span>' if r["first"] == cur_year else "")
            + f'<div class="sp-src">{esc(r["scope"])}'
              + (f'　{esc(r["provinces"][0])}' if r.get("provinces") else "")
              + f'　{esc(r["first"])} 起</div></td>'
            + "".join(mx_cell(r["by_year"].get(y, 0), mxx) for y in years)
            + f'<td class="tt">{f2(t)}</td>'
            + "</tr>")
        rows.append(
            f'<tr><td class="lft" style="padding-top:0;font-size:12px;color:var(--faint)">'
            f'　涉及应用 {num(r["apps"])} 款　明细 {num(r["entries"])} 条　'
            f'文书均 {f2(r["avg_entries"])} 条</td>'
            + '<td colspan="%d" style="background:#fbfcfe"></td>' % (len(years) + 1) + "</tr>")
    body.append(sec(
        f"谁在管 —— 发布主体 × 年度 通报量矩阵",
        "行是发布主体，列是年度，格内为该主体当年发布的通报表文书数（联合通报按发布机关拆分"
        "后等分计数）。底色越深表示当年通报越密集，灰点表示当年无通报。"
        "「新」标记指该主体首次发布通报就是在最近这个年度 —— 监管在扩围的信号。"
        "每行下方一行小字给出该主体的累计产出与单份文书的平均点名条数（通报风格："
        "是「多批次少条目」还是「少批次多条目」）。",
        '<div class="sp-wrap sp-lim"><table class="sp-mx"><thead><tr>'
        + _years_head(years) + "</tr></thead><tbody>" + "".join(rows)
        + "</tbody></table></div>"
        + '<div class="sp-legend"><span><i style="background:rgba(44,111,178,0.10)"></i>少量</span>'
          '<span><i style="background:rgba(44,111,178,0.22)"></i>中等</span>'
          '<span><i style="background:rgba(44,111,178,0.37)"></i>密集</span>'
          '<span><i style="background:#fff;border:1px solid var(--line)"></i>无通报</span></div>'))

    # ============================================================ 年度总览
    yrows = []
    for y in ys:
        kk = y["kinds"]
        yrows.append(
            "<tr>"
            f'<td class="lft"><b>{esc(y["year"])}</b></td>'
            f'<td><b>{num(y["docs"])}</b></td>'
            f'<td>{num(y["orgs"])}'
            + (f'<span class="sp-pill on">+{y["new_orgs"]}</span>' if y["new_orgs"] else "")
            + "</td>"
            f'<td>{num(y["entries"])}</td>'
            f'<td>{num(kk.get("批次通报",0))}</td>'
            f'<td>{num(kk.get("整改复核",0))}</td>'
            f'<td>{num(kk.get("下架处置",0))}</td>'
            f'<td class="lft"><span class="sp-src">{esc("、".join(y["new_org_names"][:3]) or "—")}'
            + ("…" if len(y["new_org_names"]) > 3 else "") + "</span></td>"
            "</tr>")
    body.append(sec(
        "年度总览 —— 通报量、参与主体与首次进场者",
        f"「新进主体」指该年度首次出现在本库中的发布机关（历史年度以库内最早记录为准）。"
        f"当年新进主体越多，说明监管覆盖面在扩围；{esc(last_full)}→{esc(cur_year)} 的变化"
        f"还需考虑 {esc(cur_year)} 年为不完整年度。",
        '<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
        "<th>年度</th><th>通报文书</th><th>发布主体</th><th>明细条目</th>"
        "<th>批次通报</th><th>整改复核</th><th>下架处置</th><th>当年新进主体</th>"
        "</tr></thead><tbody>" + "".join(yrows) + "</tbody></table></div>"))

    # ============================================================ 治理动作 × 年度
    cards = []
    for k in kinds:
        cards.append(
            f'<div class="sp-card"><h4>{esc(k["kind"])}　'
            f'<span class="sp-src">{num(k["total"])} 份 / {num(k["entries"])} 条</span></h4>'
            + bars(sorted(k["by_year"].items()), 20)
            + '<p class="sp-src" style="margin-top:10px">'
            + {"批次通报": "发现问题的第一道关口，按批次滚动发布。",
               "整改复核": "对已点名应用复查是否整改到位，名单与前批次重合。",
               "下架处置": "复核仍未整改的，走到应用商店下架这一步 —— 处置刚性最强。",
               "年度汇总": "重列全年清单，统计时须排除。",
               }.get(k["kind"], "")
            + "</p></div>")
    body.append(sec(
        "治理动作 × 年度 —— 监管走到哪一步了",
        "同一个应用在监管链条上会经历「批次通报 → 整改复核 → 下架处置」。把三类分开看年度构成，"
        "可以看出通报是在「广撒网点名」还是已经进入「强制处置」阶段。",
        '<div class="sp-2col">' + "".join(cards) + "</div>"))

    # ============================================================ 渠道 × 年度
    cmx = max((max((c["by_year"].get(y, 0) for y in years), default=0) for c in carriers),
              default=1) or 1
    crows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">{esc(c["label"])}</b>'
        f'<div class="sp-src">{num(c["total"])} 份　明细 {num(c["entries"])} 条</div></td>'
        + "".join(mx_cell(c["by_year"].get(y, 0), cmx) for y in years)
        + f'<td class="tt">{num(c["total"])}</td></tr>'
        for c in carriers)
    body.append(sec(
        "名单挂在什么载体上 —— 渠道 × 年度",
        "发布机关把名单放在什么形态的载体里，直接决定监测成本与漏检风险："
        "页面 HTML 表格可直接解析；部委附件 PDF 需下载解析（且续表容易丢行）；"
        "名单图只能靠 OCR（最容易漏）；正文内嵌《应用名》最零散。"
        "这一列是「我们的监测手段能不能覆盖」的直接依据。",
        '<div class="sp-wrap"><table class="sp-mx"><thead><tr>'
        + _years_head(years, "名单载体") + "</tr></thead><tbody>" + crows
        + "</tbody></table></div>"
        + '<p class="sp-src" style="margin-top:10px">'
          "image-ocr / inline-text 两类虽份数少，但恰是最难自动化的部分 —— "
          "本库已把网信办内嵌名单图按 y 坐标聚类还原成表行，把正文内嵌名单按"
          "《应用名》(版本, 来源) 的写法抽取。</p>"
        + f'<p class="sp-src" style="margin-top:6px">'
          f'全库 {num(meta.get("documents", 0))} 份文书中，'
          f'{num(meta.get("docs_with_entries", 0))} 份已结构化出应用明细；'
          f'其余 {num(meta.get("documents", 0) - meta.get("docs_with_entries", 0))} 份为'
          f'「批次级」——正文未列结构化名单，或以图片 / 外链形式给出。'
          f'这些文书仍计入机构 × 年度通报量（它们确实是监管动作），'
          f'但不贡献应用明细，故「涉及应用数」不受其影响。</p>'))

    # ============================================================ 再犯分析
    gb = rep.get("gap_buckets") or {}
    rep_kpi = [
        ("重复出现", num(rep.get("apps", 0)), "≥2 个通报事件"),
        ("其中同一轮链条内", num(rep.get("chain_apps", 0)),
         "间隔 ≤90 天：通报→复核→下架 的跟进"),
        ("跨年度再犯", num(rep.get("cross_year_apps", 0)),
         f'整改周期走完后再次违规 ★重点（其中 {num(rep.get("cross_year_exact",0))} 款'
         f'由精确间隔判定）'),
        ("跨机构被通报", num(rep.get("apps_multi_org", 0)), "被两家以上机关分别点名"),
        ("升级到下架", num(rep.get("apps_escalated", 0)), "由点名通报一路走到商店下架"),
        ("再次通报时出现新问题", num(rep.get("apps_new_prob", 0)), "老问题未改又添新问题"),
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
        return (
            "<tr>"
            f'<td><b style="color:var(--ink)">{esc(a["app"])}</b>{badge}</td>'
            f'<td><span class="sp-src">{esc((a.get("dev") or "—")[:30])}</span></td>'
            f'<td><b style="color:var(--accent)">{num(a.get("n_incidents", 0))}</b>'
            f'<div class="sp-src">通报 {num(a.get("n_notice", 0))}</div></td>'
            f'<td>{timeline(dict(a, _gap=g))}</td>'
            f'<td><span class="sp-src">{esc(" / ".join(a.get("orgs", []))[:52])}</span></td>'
            f'<td>{tags}'
            + (f'<div style="margin-top:3px"><span class="sp-tag w">新增 {len(newp)}</span>'
               f'<span class="sp-src">{esc("、".join(newp[:2]))}</span></div>' if newp else "")
            + "</td></tr>")

    trows = "".join(rep_row(a) for a in (rep.get("top") or []))
    body.append(sec(
        "重复被通报的应用 —— 谁在被反复点名，隔多久，加重了没有",
        "这是本页最有治理价值的一段，也是**最容易被误读的一段**：同一个应用在一轮治理里会"
        "先后出现在「批次通报 → 整改复核 → 下架处置」三步中，看上去像被通报了三次，"
        "实际是监管在跟进同一件事。实测相邻事件的间隔中位数只有 "
        f"{num(rep.get('gap_median',0))} 天，"
        f"{num(rep.get('apps',0))} 款重复出现的应用里有 {num(rep.get('chain_apps',0))} 款"
        f"属于这种同轮链条内跟进，"
        f"**真正跨年度再次违规的有 {num(rep.get('cross_year_apps',0))} 款** —— "
        "后者才是需要重点盯的对象。时间线中方块颜色区分环节（浅蓝＝批次通报，"
        "黄＝整改复核，红＝下架处置）。",
        kpi(rep_kpi)
        + '<div class="sp-2col" style="margin-top:16px">'
        + f'<div class="sp-card"><h4>相邻两次事件的间隔分布</h4>'
          f'<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
          f"<th>间隔</th><th>次数</th><th></th></tr></thead><tbody>{gaprows}</tbody></table></div>"
          f'<p class="sp-src" style="margin-top:10px">「≤3 个月」这一档绝大多数是同一轮治理链条'
          f"里的复核与下架，不能算作再犯；「1 年以上」才是整改周期走完之后再次违规。</p></div>"
        + '<div class="sp-card"><h4>重复事件的次数分布</h4>'
        + bars([(f'{k} 次', v) for k, v in sorted((rep.get("by_incidents") or {}).items(),
                                                 key=lambda kv: int(kv[0]))], 12)
        + '<p class="sp-src" style="margin-top:10px">被通报 2 次的是绝大多数；'
          '次数越高，说明整改越不彻底。</p></div>'
        + "</div>"
        + '<h4 style="margin:22px 0 8px;font-size:15px;color:var(--ink)">'
          f'按「轮次通报次数」排序（前 {len(rep.get("top") or [])} 款）</h4>'
        + '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
          "<th>应用</th><th>运营者</th><th>事件数</th><th>通报时间线</th><th>涉及发布主体</th>"
          "<th>问题类型</th></tr></thead><tbody>" + trows + "</tbody></table></div>"))

    # 跨年度再犯（治理重点）
    cy = rep.get("cross_year") or []
    if cy:
        body.append(sec(
            "跨年度再犯 —— 整改周期走完之后又被点名",
            "把「同一轮链条内跟进」剔除后剩下的这一档：同一款应用在间隔一年以上再次被"
            "监管点名，说明上一轮整改没有形成长效机制。这一档数量不大但治理价值最高，"
            "建议作为内部自查的优先样本 —— 它们在「整改—复检—再点名」里循环了整年。",
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>应用</th><th>运营者</th><th>事件数</th><th>通报时间线</th><th>发布主体</th>"
            "<th>问题类型</th></tr></thead><tbody>"
            + "".join(rep_row(a, show_cls=False) for a in cy)
            + "</tbody></table></div>"))

    # ============================================================ 实体消解边界
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
            "实体消解的边界情况 —— 为什么「同名」不等于「同一款」",
            "本页的去重不按应用名一刀切，代价是必须处理两类边界情况，"
            "而这两类恰好都是治理情报："
            "<b>同名不同主体</b>指同一个应用名在通报里对应了两家以上互不相同的运营者 —— "
            "可能是山寨蹭名，也可能是通报方署名不统一，无论哪种都不能把两家的风险算到一家头上；"
            "<b>中英署名并存</b>指同一款应用在不同通报里分别用中文名与英文名署名，"
            "字面无法确认是否同一主体，本页不强行合并、并列展示。"
            "两组数据在实体消解阶段就已分开计数，不是事后按名称补充判断。",
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>应用名（同名）</th><th>主体数</th><th>各自运营者署名 / 被通报次数</th>"
            "</tr></thead><tbody>" + ent_rows(col, True) + "</tbody></table></div>"
            + (f'<h4 style="margin:22px 0 8px;font-size:15px;color:var(--ink)">'
               f'中英署名并存（{len(xl)} 组）</h4>'
               '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
               "<th>应用名</th><th>署名数</th><th>运营者署名</th>"
               "</tr></thead><tbody>" + ent_rows(xl, False) + "</tbody></table></div>"
               if xl else "")))

    # 被不同机构分别点名
    morows = "".join(
        "<tr>"
        f'<td><b style="color:var(--ink)">{esc(a["app"])}</b></td>'
        f'<td><span class="sp-src">{esc((a.get("dev") or "—")[:32])}</span></td>'
        f'<td><b>{len(a.get("orgs", []))}</b></td>'
        f'<td><span class="sp-src">{esc(" / ".join(a.get("orgs", [])))}</span></td>'
        f'<td>{num(a.get("n", 0))}</td>'
        "</tr>" for a in (rep.get("multi_org") or []))
    if morows:
        body.append(sec(
            "被不同机构分别点名 —— 跨机构通报",
            "同一款应用被两家以上发布机关独立点名，说明问题跨属地或在国家与地方两级同时暴露。"
            "这类应用是风险最高的一档：单点整改无法闭环，需要按最高标准统一整改。",
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>应用</th><th>运营者</th><th>机构数</th><th>发布主体</th><th>事件数</th>"
            "</tr></thead><tbody>" + morows + "</tbody></table></div>"))

    # ============================================================ 执法强度
    irows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">{esc(r["org"])}</b>'
        f'<div class="sp-src">{esc(r["scope"])}　活跃 {r["active_years"]} 个年度</div></td>'
        f'<td>{num(r["docs"])}</td><td>{num(r["entries"])}</td><td>{num(r["apps"])}</td>'
        f'<td>{f2(r["avg_entries"])}</td>'
        f'<td>{f2(r["remove_ratio"])}%</td>'
        f'<td><span class="sp-src">'
        + "".join(f'{y}:{f2(r["by_year"].get(y,0))}　' for y in years[-3:])
        + "</span></td></tr>" for r in inten[:26])
    body.append(sec(
        "发布主体的产出与风格 —— 执法强度",
        "「条文均」＝该主体每份文书平均点名多少款应用：数值高说明一次通报就列一大批"
        "（多见于国家层面的集中通报），数值低说明是分批小步推进（多见于省局）。"
        "「下架比」＝该主体文书中下架处置类所占比例，反映处置刚性。",
        '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
        "<th>发布主体</th><th>文书</th><th>明细条目</th><th>涉及应用</th><th>条文均</th>"
        f"<th>下架比</th><th>近三年（{' / '.join(years[-3:])}）</th>"
        "</tr></thead><tbody>" + irows + "</tbody></table></div>"))

    # ============================================================ 问题 × 年度
    py = prob_year.get("rows") or []
    pmx = max((max((r["by_year"].get(y, 0) for y in years), default=0) for r in py),
              default=1) or 1
    prows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">{esc(r["prob"])}</b></td>'
        + "".join(mx_cell(r["by_year"].get(y, 0), pmx) for y in years)
        + f'<td class="tt">{num(r["total"])}</td></tr>' for r in py[:22])
    body.append(sec(
        "问题类型 × 年度 —— 监管关注点在怎么变",
        "按《App 违法违规收集使用个人信息行为认定方法》的认定行为归并后统计（一项应用可涉及"
        "多个类型，故合计大于应用数）。看某一列的颜色分布就能读出当年监管在集中打什么："
        "近两年「强制频繁过度索取权限」「信息窗口弹窗跳转」类明显变深，"
        "与「开屏广告 / 弹窗骚扰」被纳入整治的口径一致。",
        '<div class="sp-wrap sp-lim"><table class="sp-mx"><thead><tr>'
        + _years_head(years, "问题类型") + "</tr></thead><tbody>" + prows
        + "</tbody></table></div>"))

    # ============================================================ 属地 × 年度
    vmx = max((max((r["by_year"].get(y, 0) for y in years), default=0) for r in prov_year),
              default=1) or 1
    vrows = "".join(
        "<tr>"
        f'<td class="lft"><b style="color:var(--ink)">{esc(r["province"])}</b></td>'
        + "".join(mx_cell(r["by_year"].get(y, 0), vmx) for y in years)
        + f'<td class="tt">{num(r["total"])}</td></tr>' for r in prov_year[:28])
    body.append(sec(
        "属地方向 × 年度 —— 各地监管的活跃度与节奏",
        "省级通信管理局只查属地应用，其序列与国家序列互不重叠，构成通报库体量的主体。"
        "吉林、上海、新疆、西藏四地未检出属地 App 通报序列；河北、海南无独立通信管理局子站，"
        "业务并入部里。颜色越深说明该地当年通报越密集，可用来判断某地业务面临的"
        "属地监管压力。",
        '<div class="sp-wrap sp-lim"><table class="sp-mx"><thead><tr>'
        + _years_head(years, "属地 / 层级") + "</tr></thead><tbody>" + vrows
        + "</tbody></table></div>"))

    # ============================================================ 文书索引
    drows = []
    for x in sorted(docs, key=lambda z: (z.get("date") or ""), reverse=True)[:300]:
        bk = ""
        if x.get("total_batch"):
            bk = f'总第{x["total_batch"]}批'
        elif x.get("batch_seq"):
            bk = f'{x.get("batch_year") or ""}年第{x["batch_seq"]}批'
        elif x.get("quarter"):
            bk = f'第{x["quarter"]}季度'
        prec = ("" if x.get("date_precision") == "day"
                else '<span class="sp-pill">仅到年</span>')
        drows.append(
            "<tr>"
            f'<td style="white-space:nowrap">{esc((x.get("date") or "")[:10])}{prec}</td>'
            f'<td><b style="color:var(--ink)">{esc(x["org"])}</b>'
            f'<div class="sp-src">{esc(x["title"][:78])}</div></td>'
            f'<td><span class="sp-tag">{esc(x["notice_kind"])}</span>'
            + (f'<div class="sp-src" style="margin-top:3px">{esc(bk)}</div>' if bk else "")
            + "</td>"
            f'<td>{num(x.get("declared") or x.get("n_entries") or 0)}</td>'
            f'<td><span class="sp-src">{esc(x.get("province") or x.get("scope") or "")}</span></td>'
            f'<td>{link(x["url"], "原文")}</td></tr>')
    body.append(sec(
        "通报文书索引（最近 300 份）",
        f"全库共 {num(len(docs))} 份，此处列最近 300 份；每份均链接至发布机关官网原文页。"
        "「涉及款数」优先取通报正文宣称数，无则用已结构化明细条数；批次号取自标题"
        "（省局多用「YYYY年第N批」，部委用「总第N批」）。",
        '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
        "<th>日期</th><th>发布主体 / 标题</th><th>类型 / 批次</th><th>涉及款数</th>"
        "<th>属地</th><th>原文</th></tr></thead><tbody>" + "".join(drows)
        + "</tbody></table></div>"))

    return page(
        "移动应用违规治理专项",
        "移动应用违规治理专项：汇总国家与地方监管部门、协会机构的 App 违规通报，"
        "按「应用名 + 运营者」做实体消解、按机构与批次做事件去重，给出发布主体 × 年度"
        "通报量矩阵、治理动作年度构成、重复被通报应用时间线与跨机构通报分析。",
        "移动应用违规治理", "移动应用违规治理专项",
        "汇总工信部、中央网信办、公安部网安局、国家计算机病毒应急处理中心，以及省级"
        "通信管理局的 App 违规通报原文，形成可溯源的违规通报历史库。去重不只看应用名："
        "按「应用名 + 运营者」做实体消解，再按（机构 · 年份 · 批次）做事件去重，"
        "把批次通报、整改复核、下架处置分类计数。",
        "".join(body), COMMON_CSS)
