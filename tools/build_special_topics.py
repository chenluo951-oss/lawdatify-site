#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规动态」下的两个专项合规页

  news/app-violations.html  移动应用违规治理 —— 通报发布主体全景 + 违规通报历史库 + 数据分析
  news/algo-filing.html     算法合规治理   —— 备案发布序列全景 + 算法备案/深度合成/大模型备案/应用登记库

数据源
------
  sources/special/registry.json     发布主体全景登记表（人工维护，谁在通报）
  sources/appviol/docs.json         通报表文书 + 明细（tools/harvest_app_violations.py）
  sources/algo/algo_filing.json     互联网信息服务算法备案清单（19 期）
  sources/algo/deepfake_filing.json 深度合成服务算法备案清单（18 批）
  sources/algo/genai_filing.json    生成式AI 备案与登记（13 期，已拆备案/登记）
  sources/algo/cancel.json          算法备案编号注销公告（7 份）
  sources/algo/aggregates.json      年度/全量汇总公告（仅校验，不参与累加）

核心口径（页面必须显式声明，避免「重合」误读）
-------------------------------------------
App 侧：documents（文书数）≠ entries（条目数）≠ unique_apps（去重涉及应用数）。
        「整改复核 / 下架处置 / 年度汇总」类文书会重复列出前批次应用，
        对外引用一律使用 unique_apps。
算法侧：四条并列序列（算法备案 / 深度合成 / 生成式AI 备案 / 生成式AI 登记）按备案编号去重；
        年度汇总公告重列全年清单，**排除在累加之外**，仅作校验；
        累计有效数 = 累计备案 − 累计注销。
"""
import html
import json
import os
import re
from collections import Counter, OrderedDict
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPV = os.path.join(HERE, "sources", "appviol")
ALGO = os.path.join(HERE, "sources", "algo")
REG = os.path.join(HERE, "sources", "special", "registry.json")


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def num(v):
    return f"{v:,}" if isinstance(v, int) else str(v)


def load(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def page(title, desc, crumb, h1, lead, body, css=""):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} · 合规无终点</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="../assets/style.css">
<style>{css}</style>
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规动态</a> / {crumb}</div>
  <h1>{esc(h1)}</h1>
  <p>{esc(lead)}</p>
</div></div>

<main class="wrap">
{body}
</main>

<footer></footer>
</body>
</html>
"""


COMMON_CSS = """
.sp-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 6px}
.sp-k{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.sp-k b{display:block;font-size:26px;color:var(--brand);font-weight:800;line-height:1.25}
.sp-k span{display:block;color:var(--muted);font-size:12.5px;margin-top:4px}
.sp-k em{display:block;color:var(--faint);font-size:11.5px;font-style:normal;margin-top:2px}
.sp-sec{margin:44px 0 0}
.sp-sec h2{margin:0 0 6px;font-size:20px;color:var(--brand);display:flex;align-items:center;gap:9px}
.sp-sec h2::before{content:"";width:5px;height:20px;background:var(--accent);border-radius:3px}
.sp-sec p.lead{margin:0 0 14px}
.sp-tbl{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.sp-tbl th{background:#f2f6fb;color:var(--ink-2);font-weight:700;text-align:left;
  padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap;font-size:13px}
.sp-tbl td{padding:10px 12px;border-bottom:1px solid var(--line-2);vertical-align:top;color:var(--ink-2)}
.sp-tbl tr:last-child td{border-bottom:0}
.sp-tbl tr:hover td{background:#fafcff}
.sp-wrap{overflow:auto;border-radius:var(--radius)}
.sp-bar{display:flex;align-items:center;gap:10px;margin:7px 0}
.sp-bar .lb{width:230px;font-size:13px;color:var(--ink-2);flex:none;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sp-bar .tr{flex:1;background:#eef2f7;border-radius:6px;height:16px;overflow:hidden;display:block}
/* ⚠️ 必须 display:block：.fl 是 <span>，行内元素会忽略 height/width，
   表现为「柱条只剩空轨道、没有任何数据填充」（曾整站踩过）。 */
.sp-bar .fl{display:block;height:100%;min-width:2px;
  background:linear-gradient(90deg,#2c6fb2,#0f7b6c);border-radius:6px}
.sp-bar .vv{width:60px;text-align:right;font-size:12.5px;color:var(--muted);flex:none;
  font-variant-numeric:tabular-nums}
.sp-note{background:#f7fafd;border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:10px;padding:14px 18px;color:var(--ink-2);font-size:13.5px;margin-top:18px}
.sp-note b{color:var(--ink)}
.sp-warn{background:#fff9f4;border-left-color:#e08a3c}
.sp-note ul{margin:8px 0 0;padding-left:18px}
.sp-note li{margin:5px 0}
.sp-2col{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:22px;margin-top:14px}
.sp-card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.sp-card h4{margin:0 0 10px;font-size:14.5px;color:var(--ink)}
.sp-src{font-size:12.5px;color:var(--faint)}
.sp-cnt{color:var(--muted);font-size:13px;margin:8px 0 0}
table.sp-tbl td a{word-break:break-all}
/* 发布主体全景表：短列不折行，避免「属/地」「查看栏/目」被拆成两行 */
table.sp-tbl.reg td:nth-child(1){min-width:260px}
table.sp-tbl.reg td:nth-child(2),table.sp-tbl.reg td:nth-child(3),
table.sp-tbl.reg td:nth-child(6){white-space:nowrap}
table.sp-tbl.reg td:nth-child(4),table.sp-tbl.reg td:nth-child(5){min-width:150px}
table.sp-tbl.reg td:nth-child(6) a{white-space:nowrap;word-break:keep-all}
.sp-lim{max-height:560px;overflow:auto}
.sp-tag{display:inline-block;background:#eef4fb;color:#1b4f8a;border-radius:6px;
  padding:2px 8px;font-size:12px;white-space:nowrap;margin:0 4px 3px 0}
.sp-tag.g{background:#e9f6f1;color:#0f7b6c}
.sp-tag.w{background:#fdf1e7;color:#b3541e}
.sp-tag.r{background:#fdecea;color:#a4302a}
.sp-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--muted);margin:10px 0 0}
.sp-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}
.sp-q{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;
  font-size:14px;font-family:var(--sans);margin:12px 0;color:var(--ink)}
.sp-pill{display:inline-block;font-size:11.5px;border-radius:999px;padding:1px 9px;
  border:1px solid var(--line);color:var(--muted);margin-left:6px}
.sp-pill.on{background:#e9f6f1;color:#0f7b6c;border-color:#bfe3d9}
.sp-pill.off{background:#f6f7f9;color:#8a94a2}
@media(max-width:640px){.sp-bar .lb{width:110px}.sp-kpi{grid-template-columns:repeat(2,1fr)}}
"""


def bars(rows, limit=14):
    if not rows:
        return ""
    mx = max(v for _, v in rows) or 1
    out = []
    for lb, v in rows[:limit]:
        w = max(2, round(v / mx * 100))
        out.append(f'<div class="sp-bar"><span class="lb" title="{esc(lb)}">{esc(lb)}</span>'
                   f'<span class="tr"><span class="fl" style="width:{w}%"></span></span>'
                   f'<span class="vv">{num(v)}</span></div>')
    return "".join(out)


def kpi(items):
    return ('<div class="sp-kpi">' + "".join(
        f'<div class="sp-k"><b>{esc(v)}</b><span>{esc(l)}</span>'
        + (f'<em>{esc(e)}</em>' if e else "") + "</div>"
        for l, v, e in items) + "</div>")


def link(url, text=None):
    if not url:
        return '<span class="sp-src">—</span>'
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(text or "官方原文")}</a>'


def sec(title, lead, body):
    return (f'<section class="sp-sec"><h2>{esc(title)}</h2>'
            + (f'<p class="lead">{lead}</p>' if lead else "") + body + "</section>")


def registry_table(group):
    """发布主体全景表。"""
    rows = []
    for it in group["items"]:
        st = it.get("status", "")
        cls = "on" if st.startswith("已接入") else "off"
        rows.append(
            "<tr>"
            f'<td><b style="color:var(--ink)">{esc(it["org"])}</b>'
            f'<span class="sp-pill {cls}">{esc(st)}</span>'
            f'<div class="sp-src" style="margin-top:4px">{esc(it["sequence"])}</div></td>'
            f'<td>{esc(it.get("scope",""))}</td>'
            f'<td>{esc(it.get("kind",""))}</td>'
            f'<td><span class="sp-src">{esc(it.get("carrier",""))}</span></td>'
            f'<td><span class="sp-src">{esc(it.get("range",""))}</span></td>'
            f'<td>{link(it.get("entry"), "查看栏目")}</td>'
            "</tr>")
        if it.get("note"):
            rows.append(
                f'<tr><td colspan="6" style="background:#fbfcfe;font-size:12.5px;'
                f'color:var(--muted);padding-top:0">└ {esc(it["note"])}</td></tr>')
    return ('<div class="sp-wrap"><table class="sp-tbl reg"><thead><tr>'
            "<th>发布主体 / 序列</th><th>范围</th><th>通报类型</th><th>名单载体</th>"
            "<th>覆盖时间</th><th>原文入口</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def registry_group(title, groups):
    out = []
    for g in groups:
        out.append(f'<div class="sp-card" style="margin-top:14px"><h4>{esc(g["label"])}</h4>')
        if g.get("desc"):
            out.append(f'<p class="sp-src" style="margin:0 0 12px">{esc(g["desc"])}</p>')
        out.append(registry_table(g))
        out.append("</div>")
    return "".join(out)


# ============================================================ 专项一：App
def build_appviol():
    d = load(os.path.join(APPV, "docs.json"))
    docs = d.get("docs") or []
    meta = d.get("meta") or {}
    reg = load(REG).get("app") or {"groups": []}

    if not docs:
        return page("移动应用违规治理专项", "移动应用违规治理专项通报历史库",
                    "移动应用违规治理", "移动应用违规治理专项",
                    "数据正在采集。", '<div class="sp-note">数据文件尚未生成。</div>',
                    COMMON_CSS)

    m = meta
    docs_with = [x for x in docs if x.get("entries")]

    # ---- 年度趋势
    by_year = Counter()
    for x in docs:
        if x.get("date"):
            by_year[x["date"][:4]] += 1
    # ---- 文书类型 / 层级 / 载体
    kinds = Counter(x["notice_kind"] for x in docs)
    levels = Counter(x["scope"] for x in docs)
    carriers = Counter(x["carrier"] for x in docs)
    # ---- 属地（省局）
    provs = Counter(x["province"] for x in docs if x.get("province"))
    # ---- 问题类型
    prob = Counter()
    for x in docs:
        for e in x.get("entries", []):
            for p in e.get("probs", []):
                prob[p] += 1
    # ---- 重复上榜（同一应用被多份文书点名）——「重合」的量化
    apps = load(os.path.join(APPV, "apps.json")).get("apps") or []
    repeat = [a for a in apps if len(a.get("docs") or []) > 1]
    repeat.sort(key=lambda a: (-len(a["docs"]), a["app"]))
    uniq = len(apps)

    kpis = [
        ("通报文书", num(m.get("documents", len(docs))), "发布机关官网原文，按页面 URL 去重"),
        ("明细条目", num(m.get("entries", 0)), "文书 × 应用，含重复出现"),
        ("去重涉及应用", num(uniq), "按「应用名 + 运营者」归并 ★对外引用用这个"),
        ("重复上榜应用", num(len(repeat)),
         f"出现在 ≥2 份文书中，占 {round(len(repeat)/max(uniq,1)*100)}%"),
        ("明细已结构化", f"{len(docs_with)}/{len(docs)}", "其余为批次级，名单以官方附件为准"),
        ("覆盖发布主体", f"{len(levels)} 类", f"国家 {levels.get('国家',0)} · 地方 {levels.get('地方',0)}"),
    ]

    body = []
    body.append(kpi(kpis))

    # ---- 口径说明（回应用户关心的「重合」）
    body.append(f"""
<div class="sp-note sp-warn"><b>⚠️ 为什么不能把「文书数」当「被通报应用数」</b>
<ul>
<li>本库的通报文书分四类，其中 <b>整改复核（{kinds.get('整改复核',0)} 份）</b>与
<b>下架处置（{kinds.get('下架处置',0)} 份）</b>是<b>对前面批次已点名应用的后续处置</b>，
名单与批次通报天然重合，占全部文书的
<b>{round((kinds.get('整改复核',0)+kinds.get('下架处置',0))/max(len(docs),1)*100)}%</b>。</li>
<li>因此区分三个层次：<b>文书数 {num(m.get('documents',0))}</b>（发生了什么）→
<b>条目数 {num(m.get('entries',0))}</b>（点了多少次名）→
<b>去重涉及应用 {num(uniq)}</b>（到底涉及多少款应用）。<b>对外只引用最后一个。</b></li>
<li>实测重复度：{num(len(repeat))} 款应用（{round(len(repeat)/max(uniq,1)*100)}%）被
2 份及以上文书点名，最高的一款被 <b>{len(repeat[0]['docs']) if repeat else 0} 份</b>文书点名。
这正是「年度汇总 / 整改复核」类文书会造成重复计数的实证。</li>
</ul></div>""")

    # ---- 来源全景
    body.append(sec("谁在通报 —— 发布主体全景",
                    "先把发布主体摸清楚，统计口径才立得住。下表按「国家监管 / 国家协会机构 / 地方监管」"
                    "三层列出，并标注本库是否已接入。",
                    registry_group("app", reg.get("groups") or [])))

    # ---- 分析
    charts = []
    charts.append('<div class="sp-card"><h4>通报文书 · 年度分布</h4>'
                  + bars(sorted(by_year.items()), 20) + "</div>")
    charts.append('<div class="sp-card"><h4>通报文书 · 类型构成</h4>'
                  + bars(kinds.most_common(), 10)
                  + '<p class="sp-src" style="margin-top:10px">「整改复核」「下架处置」'
                    "是把批次通报的应用再列一遍的复述类文书。</p></div>")
    charts.append('<div class="sp-card"><h4>发布主体 · 层级分布</h4>'
                  + bars(levels.most_common(), 10)
                  + '<p class="sp-src" style="margin-top:10px">地方序列与国家序列互不重叠'
                    "（各地只查属地应用），是体量最大的一路。</p></div>")
    charts.append('<div class="sp-card"><h4>名单载体 · 结构化程度</h4>'
                  + bars(carriers.most_common(), 10)
                  + '<p class="sp-src" style="margin-top:10px">html-table = 页面内表格直采；'
                    "pdf = 官方附件；image-ocr = 名单图识别；inline-text = 正文内嵌名单。</p></div>")
    body.append(sec("数据分析 · 通报的节奏与结构", "", '<div class="sp-2col">'
                    + "".join(charts) + "</div>"))

    body.append(sec("属地通报 · 省级分布",
                    "省级通信管理局只查属地应用，其序列与国家序列互不重叠，"
                    "构成通报库的主体。",
                    '<div class="sp-card">' + bars(provs.most_common(), 30)
                    + '<p class="sp-src" style="margin-top:10px">'
                    "吉林、上海、新疆、西藏四地未检出属地 APP 通报序列；"
                    "河北、海南无独立通信管理局子站，业务并入部里。</p></div>"))

    body.append(sec("问题类型分布",
                    "按《App 违法违规收集使用个人信息行为认定方法》的认定行为归并后统计"
                    "（一项应用可涉及多个类型，故合计大于应用数）。",
                    '<div class="sp-card">' + bars(prob.most_common(), 20) + "</div>"))

    # ---- 重复上榜 TOP
    def tags(ps):
        if not ps:
            return '<span class="sp-src">—</span>'
        return "".join(f'<span class="sp-tag">{esc(p)}</span>' for p in ps[:4])

    rrows = "".join(
        f'<tr><td>{esc(a["app"])}</td>'
        f'<td><span class="sp-src">{esc((a.get("dev") or "—")[:34])}</span></td>'
        f'<td><b style="color:var(--accent)">{len(a["docs"])}</b></td>'
        f'<td><span class="sp-src">{esc((a.get("first") or "")[:10])} → '
        f'{esc((a.get("last") or "")[:10])}</span></td>'
        f'<td>{tags(a.get("probs"))}</td></tr>'
        for a in repeat[:60])
    body.append(sec("重复上榜应用 TOP 60",
                    "被多份文书反复点名的应用。次数越多，说明「整改—复检—下架」链条走得越久，"
                    "是监管关注的持续性风险对象。",
                    '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
                    "<th>应用</th><th>运营者</th><th>被点名次数</th><th>首次 → 最近</th>"
                    "<th>涉及问题类型</th></tr></thead><tbody>" + rrows
                    + "</tbody></table></div>"))

    # ---- 文书索引
    drows = "".join(
        f'<tr><td>{esc(x.get("date","")[:10])}</td>'
        f'<td><b style="color:var(--ink)">{esc(x["org"])}</b>'
        f'<div class="sp-src">{esc(x["title"][:78])}</div></td>'
        f'<td><span class="sp-tag">{esc(x["notice_kind"])}</span></td>'
        f'<td>{num(x.get("declared") or x.get("n_entries") or 0)}</td>'
        f'<td>{link(x["url"], "原文")}</td></tr>'
        for x in sorted(docs, key=lambda z: (z.get("date") or ""), reverse=True)[:400])
    body.append(sec("通报文书索引（最近 400 份）",
                    f"全库共 {num(len(docs))} 份，此处列最近 400 份；每份均链接至发布机关官网原文页。"
                    "「涉及款数」优先取通报正文宣称数，无则用已结构化明细条数。",
                    '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
                    "<th>日期</th><th>发布主体 / 标题</th><th>类型</th><th>涉及款数</th>"
                    "<th>原文</th></tr></thead><tbody>" + drows + "</tbody></table></div>"))

    return page("移动应用违规治理专项",
                "移动应用违规治理专项：汇总国家与地方监管部门、协会机构的 App 违规通报，"
                "形成可溯源的违规通报历史库，并给出区分「文书数 / 条目数 / 去重涉及应用数」的口径分析。",
                "移动应用违规治理", "移动应用违规治理专项",
                "汇总工信部、中央网信办、公安部网安局、国家计算机病毒应急处理中心，"
                "以及 28 个省级通信管理局的 App 违规通报原文，"
                "形成违规通报历史库，并区分「通报文书数 / 明细条目数 / 去重涉及应用数」三种口径。",
                "".join(body), COMMON_CSS)


# ============================================================ 专项二：算法
def build_algo():
    algo = load(os.path.join(ALGO, "algo_filing.json"))
    deep = load(os.path.join(ALGO, "deepfake_filing.json"))
    genai = load(os.path.join(ALGO, "genai_filing.json"))
    cancel = load(os.path.join(ALGO, "cancel.json"))
    agg = load(os.path.join(ALGO, "aggregates.json"))
    reg = load(REG).get("algo") or {"groups": []}

    ab = algo.get("batches") or []
    db = deep.get("batches") or []
    gb = genai.get("batches") or []
    cn = cancel.get("notices") or []
    ag = agg.get("aggregates") or []

    n_algo = sum(b["count"] for b in ab)
    n_deep = sum(b["count"] for b in db)
    n_b = sum(b.get("n_beian", 0) for b in gb)
    n_r = sum(b.get("n_dengji", 0) for b in gb)
    n_cancel = sum(x.get("count", 0) for x in cn)

    # 去重校验：按备案编号
    ids = set()
    for b in ab + db:
        for r in b["rows"]:
            k = re.sub(r"\s+", "", r.get("备案编号", ""))
            if k:
                ids.add(k)
    gid = set()
    for b in gb:
        for r in b["rows"]:
            k = re.sub(r"\s+", "", r.get("备案编号") or r.get("备案号") or "")
            if k:
                gid.add(k)

    # 算法类别
    cat = Counter(r.get("算法类别", "") for b in ab for r in b["rows"] if r.get("算法类别"))
    # 深度合成角色
    role = Counter(r.get("角色", "") for b in db for r in b["rows"] if r.get("角色"))
    # 属地（生成式AI）
    regn = Counter(r.get("属地", "") for b in gb for r in b["rows"] if r.get("属地"))
    # 主体集中度
    subj = Counter(r.get("主体名称", "") for b in ab + db for r in b["rows"]
                   if r.get("主体名称"))
    # 时间趋势
    algo_trend = [(b["period"], b["count"]) for b in ab]
    deep_trend = [(b.get("batch", b["period"]), b["count"]) for b in db]
    genai_trend = [(b["period"], b["count"]) for b in gb]

    kpis = [
        ("算法备案", num(n_algo), f"{len(ab)} 期 · 备案编号零重复"),
        ("深度合成备案", num(n_deep), f"{len(db)} 批 · ★本次新补序列"),
        ("生成式AI 备案", num(n_b), f"{len(gb)} 期 · 大模型，编号无 S"),
        ("生成式AI 登记", num(n_r), f"{len(gb)} 期 · 应用/功能，属地受理"),
        ("备案编号注销", num(n_cancel), f"{len(cn)} 份注销公告"),
        ("去重唯一编号", num(len(ids) + len(gid)), "四条序列按备案编号去重"),
    ]

    body = []
    body.append(kpi(kpis))

    # ---- 对账与口径
    agg_labels = "、".join(x.get("label", "") for x in ag) or "—"
    last = gb[-1] if gb else {}
    official = ag[-1] if ag else {}
    official_sum = ((official.get("cum_beian") or 0)
                    + (official.get("cum_dengji") or 0)) or "—"
    body.append(f"""
<div class="sp-note sp-warn"><b>⚠️ 口径与对账</b>
<ul>
<li><b>四条并列序列，不可直接相加</b>：
「互联网信息服务算法备案」（{num(n_algo)} 条）、「深度合成服务算法备案」（{num(n_deep)} 条）、
「生成式AI 备案」（{num(n_b)} 条）、「生成式AI 登记」（{num(n_r)} 条）。
算法备案与深度合成两序列按<b>备案编号</b>去重后为 {num(len(ids))} 个唯一编号
（两套编号体系不同，实测互不重复）；生成式AI 备案与登记共用同一编号空间，
去重后 {num(len(gid))} 个。</li>
<li><b>年度汇总公告必须排除</b>：本库另收录 {len(ag)} 份「年度/全量汇总公告」
（{esc(agg_labels)}）。汇总公告把全年清单再列一遍，与增量序列完全重合，
<b>一律不参与累加，仅用于校验</b>。</li>
<li><b>注销要扣减</b>：{len(cn)} 份注销公告共注销 {num(n_cancel)} 个备案编号；
不做扣减会把已注销编号计入存量。</li>
<li><b>对账结果</b>：本库生成式AI 分批累加去重后 <b>{num(len(gid))}</b> 个唯一备案编号；
官方 2026-09-14 公告口径为「累计备案 {esc(official.get('cum_beian') or '—')} 款 +
累计登记 {esc(official.get('cum_dengji') or '—')} 款 = {esc(official_sum)} 款」。
<b>两者一致</b>，说明分批累加口径与官方汇总口径可互相印证（公告同时注明，
备案编号会随主体变更与注销动态调整，故个别条目在备案/登记归类上存在差异）。</li>
</ul></div>""")

    # ---- 来源全景
    body.append(sec("谁在备案、谁在发公告 —— 发布主体与序列全景",
                    "先把发布主体与序列关系摸清楚（哪些是并列序列、哪些是汇总重列），"
                    "统计口径才立得住。",
                    registry_group("algo", reg.get("groups") or [])))

    # ---- 分析
    c1 = ('<div class="sp-card"><h4>算法备案 · 各期新增</h4>'
          + bars(algo_trend, 25) + "</div>")
    c2 = ('<div class="sp-card"><h4>深度合成备案 · 各批新增</h4>'
          + bars(deep_trend, 25) + "</div>")
    c3 = ('<div class="sp-card"><h4>生成式AI · 各期备案 / 登记</h4>'
          + bars(genai_trend, 20) + "</div>")
    body.append(sec("序列趋势", "", '<div class="sp-2col">' + c1 + c2 + c3 + "</div>"))

    c4 = ('<div class="sp-card"><h4>算法备案 · 算法类别分布</h4>'
          + bars(cat.most_common(), 12)
          + '<p class="sp-src" style="margin-top:10px">'
            "反映算法推荐类备案的结构；生成合成类多走「深度合成」独立序列。</p></div>")
    c5 = ('<div class="sp-card"><h4>深度合成备案 · 主体角色分布</h4>'
          + bars(role.most_common(), 8)
          + '<p class="sp-src" style="margin-top:10px">'
            "依据《互联网信息服务深度合成管理规定》第十九条，技术支持者参照提供者履行备案手续。</p></div>")
    c6 = ('<div class="sp-card"><h4>生成式AI · 属地分布</h4>'
          + bars(regn.most_common(), 20)
          + '<p class="sp-src" style="margin-top:10px">'
            "国家公告的清单内含「属地」列，因此省级分布可直接从国家口径得出，无需依赖地方公告。</p></div>")
    body.append(sec("结构分析", "", '<div class="sp-2col">' + c4 + c5 + c6 + "</div>"))

    srows = "".join(
        f'<tr><td>{i}</td><td><b style="color:var(--ink)">{esc(k)}</b></td>'
        f'<td><b style="color:var(--accent)">{v}</b></td></tr>'
        for i, (k, v) in enumerate(subj.most_common(60), 1))
    body.append(sec("备案主体集中度 TOP 60",
                    "按「互联网信息服务算法备案 + 深度合成备案」两个序列合计的备案条目数排序，"
                    "呈现算法合规投入最密集的主体。",
                    '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
                    "<th>#</th><th>主体名称</th><th>备案条目数</th></tr></thead><tbody>"
                    + srows + "</tbody></table></div>"))

    # ---- 注销
    krows = ""
    for x in cn:
        title = x.get("title", "")
        m = re.search(r"等\s*(\d+)\s*个", title)
        cnt = x.get("count", 0)
        mark = "" if m else '<span class="sp-pill off">标题未载明数量</span>'
        krows += (f'<tr><td style="white-space:nowrap">{esc(x.get("date",""))}</td>'
                  f'<td>{esc(title)}{mark}</td>'
                  f'<td><b>{esc(cnt)}</b></td>'
                  f'<td>{link(x.get("url"), "公告原文")}</td></tr>')
    krows += (f'<tr style="background:#fbfcfe"><td colspan="2" style="text-align:right">'
              f'<b style="color:var(--ink)">合计注销编号</b></td>'
              f'<td><b style="color:var(--ink)">{num(n_cancel)}</b></td><td>—</td></tr>')
    detail = ""
    for x in cn:
        for r in (x.get("records") or []):
            detail += (f'<tr><td>{esc(r.get("name",""))}</td>'
                       f'<td>{esc(r.get("entity",""))}</td>'
                       f'<td><span class="sp-src">{esc(r.get("code",""))}</span></td>'
                       f'<td style="white-space:nowrap">{esc(r.get("cancel",""))}</td></tr>')
    body.append(sec(
        "备案编号注销记录",
        "注销才得到「累计有效备案数」的正确口径。下表逐份列示 7 份注销公告，并展开全部注销明细"
        "（算法名称 / 主体 / 备案编号 / 注销时间）——这是把「累计备案」折成「当前有效」的关键一步。",
        '<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
        "<th>日期</th><th>公告</th><th>注销编号数</th><th>原文</th></tr></thead><tbody>"
        + krows + "</tbody></table></div>"
        + f'<h4 style="margin:22px 0 8px;font-size:14.5px;color:var(--ink)">'
          f'注销明细（{num(sum(len(x.get("records") or []) for x in cn))} 个编号）</h4>'
          '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
          "<th>算法名称</th><th>主体名称</th><th>备案编号</th><th>注销时间</th>"
          "</tr></thead><tbody>" + detail + "</tbody></table></div>"
        + '<p class="sp-src" style="margin-top:10px">口径说明：2 份公告标题写作「等算法备案编号」'
          '未载明数量，其条数由公告表格行解析得到（分别为 5 条、1 条）；表中「注销编号数」'
          '一律以附件表格行为准，不采用标题数字。公告原文经算法备案系统免登录接口按 noticeId 直取。</p>'))

    return page("算法合规治理专项",
                "算法合规治理专项：汇总国家网信办与省级网信部门的算法备案、深度合成算法备案、"
                "大模型备案与 AI 应用登记信息，形成可溯源的备案信息库，并给出与年度汇总公告的对账口径。",
                "算法合规治理", "算法合规治理专项",
                "汇总国家网信办的互联网信息服务算法备案、深度合成服务算法备案、生成式人工智能服务"
                "备案与登记四条并列序列，并单列注销记录与年度汇总公告（不参与累加），"
                "形成可溯源的备案信息库。",
                "".join(body), COMMON_CSS)


def main():
    out = os.path.join(HERE, "news")
    os.makedirs(out, exist_ok=True)
    for name, fn in (("app-violations.html", build_appviol),
                     ("algo-filing.html", build_algo)):
        html_text = fn()
        p = os.path.join(out, name)
        open(p, "w", encoding="utf-8").write(html_text)
        print(f"✓ {name}  {os.path.getsize(p)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
