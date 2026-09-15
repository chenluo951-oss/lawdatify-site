#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规动态」下的两个专项合规页

  news/app-violations.html  移动应用违规治理 —— 违规通报历史库 + 数据分析
  news/algo-filing.html     算法合规治理   —— 算法备案 / 大模型备案 / AI 应用登记信息库

数据源
------
  sources/appviol/batches.json   工信部 APP(SDK) 通报 + 中央网信办 App 通报批次（tools/harvest_app_violations.py）
  sources/appviol/apps.json      通报名单图 OCR 抽取的 App 明细
  sources/algo/algo_filing.json  网信办《互联网信息服务算法备案信息的公告》各期清单
  sources/algo/genai_filing.json 网信办《生成式人工智能服务已备案信息的公告》各期清单

输出后由 daily_build 的 inject_subnav / unify_chrome / inject_meta 统一补导航与元数据。
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


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


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
.sp-tags{display:flex;flex-wrap:wrap;gap:6px}
.sp-tag{display:inline-block;background:#eef4fb;color:#1b4f8a;border-radius:6px;
  padding:2px 8px;font-size:12px;white-space:nowrap}
.sp-tag.g{background:#e9f6f1;color:#0f7b6c}
.sp-tag.w{background:#fdf1e7;color:#b3541e}
.sp-bar{display:flex;align-items:center;gap:10px;margin:7px 0}
.sp-bar .lb{width:230px;font-size:13px;color:var(--ink-2);flex:none;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sp-bar .tr{flex:1;background:#eef2f7;border-radius:6px;height:16px;overflow:hidden}
.sp-bar .fl{height:100%;background:linear-gradient(90deg,#2c6fb2,#0f7b6c);border-radius:6px}
.sp-bar .vv{width:56px;text-align:right;font-size:12.5px;color:var(--muted);flex:none;
  font-variant-numeric:tabular-nums}
.sp-note{background:#f7fafd;border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:10px;padding:14px 18px;color:var(--ink-2);font-size:13.5px;margin-top:18px}
.sp-note b{color:var(--ink)}
.sp-acts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:14px}
.sp-act{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.sp-act h4{margin:0 0 8px;font-size:15px;color:var(--ink)}
.sp-act ul{margin:0;padding-left:18px;color:var(--ink-2);font-size:13.5px}
.sp-act li{margin:5px 0}
.sp-q{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;
  font-size:14px;font-family:var(--sans);margin:12px 0;color:var(--ink)}
.sp-cnt{color:var(--muted);font-size:13px;margin:8px 0 0}
.sp-src{font-size:12.5px;color:var(--faint)}
.sp-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--accent);
  margin-right:6px;vertical-align:middle}
table.sp-tbl td a{word-break:break-all}
.sp-lim{max-height:520px;overflow:auto}
.sp-tl{position:relative;margin:16px 0 0;padding-left:22px;border-left:2px solid var(--line)}
.sp-tl .ev{position:relative;margin:0 0 16px}
.sp-tl .ev::before{content:"";position:absolute;left:-29px;top:6px;width:12px;height:12px;
  border-radius:50%;background:#fff;border:3px solid var(--brand)}
.sp-tl .ev .d{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.sp-tl .ev .t{font-size:14px;color:var(--ink);margin:1px 0 3px}
.sp-tl .ev .m{font-size:12.5px;color:var(--muted)}
@media(max-width:640px){.sp-bar .lb{width:120px}.sp-kpi{grid-template-columns:repeat(2,1fr)}}
"""


def bars(rows, total=None, limit=14):
    """横向条形图（纯 CSS，无依赖）。rows = [(label, value)]"""
    if not rows:
        return ""
    mx = max(v for _, v in rows) or 1
    out = []
    for lb, v in rows[:limit]:
        w = max(2, round(v / mx * 100))
        out.append(f'<div class="sp-bar"><span class="lb" title="{esc(lb)}">{esc(lb)}</span>'
                   f'<span class="tr"><span class="fl" style="width:{w}%"></span></span>'
                   f'<span class="vv">{v}</span></div>')
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


# ------------------------------------------------------------------ 专页一
def build_appviol():
    p = os.path.join(APPV, "batches.json")
    batches, apps = [], []
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        batches = d.get("batches") or []
    ap = os.path.join(APPV, "apps.json")
    if os.path.exists(ap):
        apps = json.load(open(ap, encoding="utf-8")).get("apps") or []

    if not batches:
        return None
    # 只保留确为 App 违规通报的（排除行动方案、评选、会议等）
    KEEP = re.compile(r"通报|查处")
    batches = [b for b in batches if KEEP.search(b.get("title", ""))]

    years = Counter()
    for b in batches:
        y = b.get("year") or (b.get("date") or "")[:4]
        if y:
            years[str(y)] += 1
    orgs = Counter(b.get("org") or "未标注" for b in batches)
    apps_cnt = sum(b.get("apps_count") or 0 for b in batches)
    cats = Counter()
    for b in batches:
        for c in b.get("categories") or []:
            cats[c] += 1
    cat_words = Counter()
    WORD = re.compile(r"(未公开个人信息收集使用规则|频繁索要非必要权限|未完整准确列明SDK收集"
                      r"使用个人信息情况|未提供有效账号注销功能|违规收集个人信息|"
                      r"违规使用个人信息|不合理索取用户权限|为用户账号注销设置障碍|"
                      r"强制用户使用定向推送功能|欺骗误导用户下载|超范围收集个人信息|"
                      r"私自共享给第三方|私自收集个人信息|不给权限不让用|过度索取权限|"
                      r"账号注销难|频繁申请权限|违规推送|开屏弹窗|SDK)")
    for b in batches:
        for m in WORD.findall(b.get("title", "") + " " + " ".join(b.get("categories") or [])):
            cat_words[m] += 1

    yrows = sorted(years.items(), key=lambda x: -x[1])
    ykeys = sorted(years.items())
    mx = max([v for _, v in ykeys] or [1])

    # 年度柱状（SVG，宽 680）
    def year_chart():
        if not ykeys:
            return ""
        w, h, pad = 680, 190, 34
        bw = (w - pad * 2) / max(1, len(ykeys))
        out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
               f'aria-label="App 违规通报批次年度分布">']
        for i, (y, v) in enumerate(ykeys):
            bh = (h - pad - 34) * v / mx if mx else 0
            x = pad + i * bw + bw * 0.18
            out.append(f'<rect x="{x:.1f}" y="{h - pad - bh:.1f}" width="{bw*0.64:.1f}" '
                       f'height="{bh:.1f}" rx="5" fill="#2c6fb2" opacity="0.88"/>')
            out.append(f'<text x="{x + bw*0.32:.1f}" y="{h - pad - bh - 7:.1f}" '
                       f'text-anchor="middle" font-size="12" fill="#33404f">{v}</text>')
            out.append(f'<text x="{x + bw*0.32:.1f}" y="{h - pad + 17:.1f}" '
                       f'text-anchor="middle" font-size="12" fill="#6b7a8c">{esc(y)}</text>')
        out.append(f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" '
                   f'stroke="#e6ebf2" stroke-width="1"/>')
        out.append("</svg>")
        return "".join(out)

    rows = []
    for b in sorted(batches, key=lambda x: (x.get("date") or ""), reverse=True):
        cat = "、".join(b.get("categories") or [])[:70]
        no = ""
        if b.get("batch_total"):
            no = f'总第{b["batch_total"]}批'
            if b.get("batch_in_year"):
                no = f'{b.get("year")}年第{b["batch_in_year"]}批 · ' + no
        rows.append(
            "<tr>"
            f'<td>{esc(b.get("date") or "")}</td>'
            f'<td>{esc(no or "—")}</td>'
            f'<td>{esc(b.get("org") or "")}</td>'
            f'<td>{esc(b.get("apps_count") or "—")}</td>'
            f'<td>{esc(cat) or "—"}</td>'
            f'<td>{link(b.get("url"), "通报原文")}</td>'
            "</tr>")

    app_rows = ""
    if apps:
        def sk(a):
            return -(int(a.get("date", "0")[:4] or 0) * 100 + len(a.get("problems") or []))
        for a in sorted(apps, key=sk)[:1200]:
            app_rows += ("<tr class=\"ai\">"
                         f'<td>{esc(a.get("app",""))}</td>'
                         f'<td>{esc(a.get("dev",""))}</td>'
                         f'<td>{esc(a.get("date",""))}</td>'
                         f'<td><span class="sp-tags">'
                         + "".join(f'<span class="sp-tag w">{esc(x)}</span>'
                                   for x in (a.get("problems") or [])[:4])
                         + "</span></td>"
                         f'<td>{link(a.get("url"), "通报原文")}</td></tr>')

    body = []
    body.append(kpi([
        ("通报批次", len(batches), "工信部 + 中央网信办官网原文"),
        ("覆盖年度", f'{min(years) if years else "—"}—{max(years) if years else "—"}', None),
        ("通报涉及 App", apps_cnt or "—", "通报正文标明的款数合计"),
        ("OCR 抽取明细", len(apps), "名单图逐条识别"),
    ]))
    body.append('<section class="sp-sec"><h2>监管脉络</h2>'
                '<p class="lead">移动应用违规治理是唯一从 2019 年连续编号至今、'
                '由工信部与中央网信办双线并行的常态化通报机制。看清时间线，'
                '就能判断「什么时间点、查什么类型的问题、整改窗口多长」。</p>'
                + year_chart() + "</section>")

    body.append('<section class="sp-sec"><h2>通报批次历史库</h2>'
                '<p class="lead">按发布时间倒序。批次号取自通报标题原文；'
                '「涉及」为该批次通报正文标明的 App / SDK 款数；'
                '末列直达发布机关官网的通报正文页。</p>'
                '<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
                "<th>发布日期</th><th>批次</th><th>发布机关</th><th>涉及</th>"
                "<th>主要问题</th><th>原文</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div></section>")

    if cat_words:
        body.append('<section class="sp-sec"><h2>高频违规类型</h2>'
                    '<p class="lead">按通报点名的违规情形归并统计（同一批次提及多种情形分别计入）。</p>'
                    + bars(cat_words.most_common(16)) + "</section>")
    if orgs:
        body.append('<section class="sp-sec"><h2>发布机关分布</h2>'
                    + bars(orgs.most_common(8)) + "</section>")
    body.append('<section class="sp-sec"><h2>年度分布</h2>' + bars(yrows, limit=12) + "</section>")

    if app_rows:
        body.append(
            '<section class="sp-sec"><h2>App 明细库（名单图抽取）</h2>'
            '<p class="lead">通报中的名单元数据以图片形式发布，本库用 OCR 抽取为可检索条目；'
            '识别结果可能与原图存在差异，<b>以通报原文图片为准</b>。</p>'
            '<input class="sp-q" id="aq" type="search" '
            'placeholder="搜索 App 名称 / 开发者 / 违规类型，例如：读书、权限、注销">'
            '<p class="sp-cnt" id="ac">共 %d 条</p>'
            '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
            "<th>App</th><th>开发者</th><th>通报时间</th><th>涉及问题</th><th>原文</th>"
            "</tr></thead><tbody>%s</tbody></table></div></section>" % (len(apps), app_rows))

    body.append("""<section class="sp-sec"><h2>合规行动清单</h2>
<p class="lead">把通报里的高频问题直接翻译成可执行的自查项——这些是历次通报点名最多、
也最容易被复检发现的项。</p>
<div class="sp-acts">
  <div class="sp-act"><h4>① 告知与同意</h4><ul>
    <li>首次运行弹窗要有个人信息收集使用规则，且可一键查阅完整规则</li>
    <li>规则中逐项列明收集的信息、用途、第三方 SDK 及共享对象</li>
    <li>权限在业务场景实际触发时申请，不得启动即索取、不得捆绑基本功能</li></ul></div>
  <div class="sp-act"><h4>② 账号与权利响应</h4><ul>
    <li>提供有效的注销入口，注销路径不超过 3 步、不得设置不合理条件</li>
    <li>注销后及时删除或匿名化，并同步告知第三方已共享数据</li>
    <li>提供查阅、复制、更正、删除的线上通道并留存响应记录</li></ul></div>
  <div class="sp-act"><h4>③ SDK 与第三方</h4><ul>
    <li>建立 SDK 台账：名称、提供方、采集字段、权限、回传地址</li>
    <li>上线前做 SDK 行为检测，禁止「未告知即收集」与静默自启动</li>
    <li>隐私政策中完整准确列明 SDK 收集使用个人信息情况</li></ul></div>
  <div class="sp-act"><h4>④ 推送与营销</h4><ul>
    <li>个性化推荐与定向推送提供显著的一键关闭开关</li>
    <li>不得强制用户使用定向推送功能，不得以弹窗频繁骚扰</li>
    <li>开屏弹窗可跳过、不得欺骗误导用户点击或下载</li></ul></div>
</div></section>""")

    body.append('<div class="sp-note"><b>数据说明</b>　'
                '批次信息取自工业和信息化部「APP 侵害用户权益专项整治行动」栏目与中央网信办官网'
                '《关于 N 款 App 个人信息收集使用问题的通报》原文页；全部链接可直达发布机关官网。'
                '通报名单元以图片发布，App 明细由 macOS Vision OCR 抽取，'
                '识别结果可能与原图存在差异，<b>以通报原文图片为准</b>。'
                f'本页数据更新至 {esc(batches[0].get("date") or "")}；'
                '每日构建会自动发现新批次并增量补入。</div>')

    return page(
        "移动应用违规治理",
        "汇集工业和信息化部与中央网信办历年 App（含小程序、SDK）侵害用户权益与个人信息"
        "收集使用问题的官方通报，形成可检索的违规通报历史库，并按违规类型、发布机关、"
        "年度做数据分析，附可落地的 App 合规自查行动清单。",
        "移动应用违规治理", "移动应用违规治理",
        "从工信部「APP 侵害用户权益专项整治行动」到中央网信办个人信息保护系列专项行动，"
        "移动应用违规治理是常态化、可追溯的通报机制。这一页把历年官方通报沉淀成历史库，"
        "并从中提炼出可直接对照自查的合规项。",
        "\n".join(body), COMMON_CSS)


# ------------------------------------------------------------------ 专页二
def build_algo():
    algo = genai = None
    pa = os.path.join(ALGO, "algo_filing.json")
    pg = os.path.join(ALGO, "genai_filing.json")
    if os.path.exists(pa):
        algo = json.load(open(pa, encoding="utf-8"))
    if os.path.exists(pg):
        genai = json.load(open(pg, encoding="utf-8"))
    if not algo and not genai:
        return None

    a_rows, g_rows = [], []
    a_cat, a_per, a_org, a_city = Counter(), OrderedDict(), Counter(), Counter()
    a_total = a_subj = 0
    if algo:
        for b in algo.get("batches", []):
            per = b.get("period") or ""
            a_per[per] = a_per.get(per, 0) + (b.get("count") or 0)
            for r in b.get("rows", []):
                a_total += 1
                cat = (r.get("算法类别") or "").strip()
                if cat:
                    a_cat[cat] += 1
                subj = (r.get("主体名称") or "").strip()
                if subj:
                    a_org[subj] += 1
                code = (r.get("备案编号") or "")
                m = re.search(r"网信算备(\d{6})", code)
                if m:
                    a_city[m.group(1)[:2]] += 1
                a_rows.append({
                    "name": (r.get("算法名称") or "").strip(),
                    "cat": cat,
                    "subj": subj,
                    "prod": (r.get("应用产品") or "").strip(),
                    "use": (r.get("主要用途") or "").strip()[:90],
                    "no": code,
                    "per": per,
                })
        a_subj = len({r["subj"] for r in a_rows if r["subj"]})

    g_total = g_org_n = 0
    g_per, g_area = OrderedDict(), Counter()
    if genai:
        for b in genai.get("batches", []):
            per = b.get("period") or ""
            g_per[per] = g_per.get(per, 0) + (b.get("count") or 0)
            for r in b.get("rows", []):
                g_total += 1
                area = (r.get("属地") or "").strip()
                if area:
                    g_area[area] += 1
                g_rows.append({
                    "name": (r.get("大模型名称") or r.get("模型名称") or "").strip(),
                    "org": (r.get("备案单位") or "").strip(),
                    "no": (r.get("备案编号") or r.get("备案号") or "").strip(),
                    "area": area,
                    "date": (r.get("备案时间") or "").strip(),
                    "per": per,
                })
        g_org_n = len({r["org"] for r in g_rows if r["org"]})

    # 累计曲线（备案存量随时间）
    def cum_chart(permap):
        ks = sorted(permap.keys())
        if not ks:
            return ""
        vals, run = [], 0
        for k in ks:
            run += permap[k]
            vals.append((k, run))
        w, h, pad = 680, 210, 40
        mx = vals[-1][1] or 1
        step = (w - pad * 2) / max(1, len(vals) - 1)
        pts = [(pad + i * step, h - pad - (h - pad - 30) * v / mx)
               for i, (_, v) in enumerate(vals)]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = f"{pad},{h-pad} " + poly + f" {pts[-1][0]:.1f},{h-pad}"
        out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="累计备案趋势">',
               f'<polygon points="{area}" fill="#2c6fb2" opacity="0.10"/>',
               f'<polyline points="{poly}" fill="none" stroke="#2c6fb2" stroke-width="2.2"/>']
        for i, (x, y) in enumerate(pts):
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#0f7b6c"/>')
            if i % 2 == 0 or i == len(pts) - 1:
                out.append(f'<text x="{x:.1f}" y="{h-pad+16:.1f}" text-anchor="middle" '
                           f'font-size="10.5" fill="#6b7a8c">{esc(vals[i][0])}</text>')
                out.append(f'<text x="{x:.1f}" y="{y-8:.1f}" text-anchor="middle" '
                           f'font-size="10.5" fill="#33404f">{vals[i][1]}</text>')
        out.append(f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" '
                   f'stroke="#e6ebf2"/>')
        out.append("</svg>")
        return "".join(out)

    body = []
    body.append(kpi([
        ("算法备案记录", a_total, f'{len(a_per)} 期清单'),
        ("备案主体", a_subj, "去重主体数"),
        ("生成式AI备案/登记", g_total, f'{len(g_per)} 期清单'),
        ("覆盖属地", len(g_area), "省级行政区"),
    ]))

    body.append('<section class="sp-sec"><h2>为什么要建这个库</h2>'
                '<p class="lead">算法与生成式人工智能的备案信息由国家网信办按批次公告、'
                '属地网信部门分别公示，散落在几十份公告与附件里。这一页把公告附件逐行解析成'
                '结构化信息库：谁备了什么算法、用在哪里、备案号是什么、属地在哪里，'
                '一屏可查——用于回答「同业是否已备案」「某类算法备案口径怎么写」'
                '「我们是否属于应备案主体」。</p>'
                + cum_chart(g_per) +
                '<p class="sp-cnt">上图为生成式人工智能服务累计备案/登记数量（按网信办公告批次累计）。</p>'
                "</section>")

    if a_total:
        body.append('<section class="sp-sec"><h2>算法备案 · 全量信息库</h2>'
                    '<p class="lead">来源：国家互联网信息办公室《关于发布互联网信息服务算法备案'
                    '信息的公告》各期附件（该页持续更新）。备案编号中隐含主体所在地区与备案年份，'
                    '可作为同业对标与内部申报口径参考。</p>'
                    '<input class="sp-q" id="bq" type="search" '
                    'placeholder="搜索算法名称 / 主体 / 应用产品 / 备案编号，例如：推荐、深圳、内容过滤">'
                    f'<p class="sp-cnt" id="bc">共 {a_total} 条</p>'
                    '<div class="sp-wrap sp-lim"><table class="sp-tbl" id="bt"><thead><tr>'
                    "<th>算法名称</th><th>算法类别</th><th>主体名称</th><th>应用产品</th>"
                    "<th>备案编号</th><th>期次</th></tr></thead><tbody>"
                    + "".join(
                        "<tr class=\"ar\"><td>%s</td><td><span class=\"sp-tag\">%s</span></td>"
                        "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                            esc(r["name"]), esc(r["cat"]), esc(r["subj"]), esc(r["prod"]),
                            esc(r["no"]), esc(r["per"]))
                        for r in sorted(a_rows, key=lambda x: x["per"], reverse=True)[:2500])
                    + "</tbody></table></div></section>")
        body.append('<section class="sp-sec"><h2>算法类别分布</h2>'
                    '<p class="lead">按公告中标注的算法类别统计，可看出监管备案口径的分类结构。</p>'
                    + bars(a_cat.most_common(14)) + "</section>")
        body.append('<section class="sp-sec"><h2>备案期次分布</h2>'
                    + bars(sorted(a_per.items()), limit=24) + "</section>")

    if g_total:
        body.append('<section class="sp-sec"><h2>生成式人工智能服务备案与登记库</h2>'
                    '<p class="lead">来源：国家互联网信息办公室《关于发布生成式人工智能服务'
                    '已备案信息的公告》各期附件（含各批次的「已备案」与「已登记」信息）。'
                    '已备案面向模型提供者，已登记面向通过 API 等方式调用已备案模型的'
                    '应用或功能——两条路径的合规义务不同。</p>'
                    '<input class="sp-q" id="gq" type="search" '
                    'placeholder="搜索模型名称 / 备案单位 / 属地 / 备案号，例如：大模型、北京">'
                    f'<p class="sp-cnt" id="gc">共 {g_total} 条</p>'
                    '<div class="sp-wrap sp-lim"><table class="sp-tbl" id="gt"><thead><tr>'
                    "<th>模型/应用名称</th><th>备案单位</th><th>属地</th><th>备案号</th>"
                    "<th>备案时间</th></tr></thead><tbody>"
                    + "".join(
                        "<tr class=\"gr\"><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                        "<td>%s</td></tr>" % (
                            esc(r["name"]), esc(r["org"]), esc(r["area"]), esc(r["no"]),
                            esc(r["date"]))
                        for r in sorted(g_rows, key=lambda x: (x["date"], x["per"]),
                                        reverse=True)[:2500])
                    + "</tbody></table></div></section>")
        body.append('<section class="sp-sec"><h2>属地分布</h2>'
                    '<p class="lead">生成式人工智能服务备案与属地强相关：'
                    '大模型备案由企业所在地省级网信办初审、国家网信办备案；'
                    '应用/功能登记由属地网信办办理。属地分布可反映各地 AI 产业活跃度。</p>'
                    + bars(g_area.most_common(20)) + "</section>")

    body.append("""<section class="sp-sec"><h2>备案合规要点</h2>
<p class="lead">三条备案义务分别来自三部规章，合规判断的第一步是先确定自己落在哪一条。</p>
<div class="sp-acts">
  <div class="sp-act"><h4>① 算法备案（推荐、排序、检索、调度）</h4><ul>
    <li>依据：《互联网信息服务算法推荐管理规定》第二十四条</li>
    <li>义务主体：具有舆论属性或社会动员能力的算法推荐服务提供者</li>
    <li>时限：提供服务之日起 10 个工作日内填报；变更 10 日内、终止 20 日内办注销</li>
    <li>公示：在网站/App 显著位置标明备案编号并提供公示信息链接</li></ul></div>
  <div class="sp-act"><h4>② 深度合成服务备案</h4><ul>
    <li>依据：《互联网信息服务深度合成管理规定》第十九条</li>
    <li>义务主体：提供具有舆论属性或社会动员能力的深度合成服务，及技术支持者</li>
    <li>配套：对生成内容添加标识、建立内容审核与辟谣机制</li></ul></div>
  <div class="sp-act"><h4>③ 生成式AI 备案 / 登记</h4><ul>
    <li>依据：《生成式人工智能服务管理暂行办法》第十七条</li>
    <li>模型提供者：通过属地网信部门履行备案；应用/功能调用方：办理登记</li>
    <li>上线后须在产品显著位置公示模型名称与备案号或上线编号</li></ul></div>
  <div class="sp-act"><h4>④ 自查动作</h4><ul>
    <li>盘点上线的推荐/检索/排序/调度功能，判断是否落入备案范围</li>
    <li>核对备案编号与实际主体、算法、应用产品是否一致（主体变更须及时变更备案）</li>
    <li>检查 App、官网、小程序显著位置是否已公示备案号与公示链接</li></ul></div>
</div></section>""")

    body.append('<div class="sp-note"><b>数据说明</b>　'
                '算法备案与生成式AI备案数据均解析自国家互联网信息办公室官网站内公告页的'
                '附件清单（docx / pdf 表格逐行解析），链接可直达公告页与附件下载地址。'
                '备案号随主体名称变更、算法注销动态调整，'
                '<b>以国家网信办互联网信息服务算法备案系统（beian.cac.gov.cn）实时查询为准</b>。'
                '属地字段为公告原文所列备案地。</div>')

    body.append("""<script>
(function(){
  function wire(qid,cid,tid,rc){
    var q=document.getElementById(qid),c=document.getElementById(cid),t=document.getElementById(tid);
    if(!q||!t) return;
    var rows=[].slice.call(t.tBodies[0].rows);
    q.addEventListener('input',function(){
      var s=q.value.trim().toLowerCase(),n=0;
      rows.forEach(function(r){
        var hit=!s||r.textContent.toLowerCase().indexOf(s)>-1;
        r.style.display=hit?'':'none'; if(hit) n++;
      });
      if(c) c.textContent='命中 '+n+' 条 / 共 '+rows.length+' 条';
    });
  }
  wire('bq','bc','bt'); wire('gq','gc','gt');
  var aq=document.getElementById('aq'),ac=document.getElementById('ac');
  if(aq){var rows=[].slice.call(document.querySelectorAll('tr.ai'));
    aq.addEventListener('input',function(){var s=aq.value.trim().toLowerCase(),n=0;
      rows.forEach(function(r){var h=!s||r.textContent.toLowerCase().indexOf(s)>-1;
        r.style.display=h?'':'none'; if(h)n++;});
      ac.textContent='命中 '+n+' 条 / 共 '+rows.length+' 条';});}
})();
</script>""")

    return page(
        "算法合规治理",
        "汇集国家互联网信息办公室历年公告中的互联网信息服务算法备案清单、生成式人工智能"
        "服务已备案与已登记信息，形成可检索的算法与大模型备案信息库，并按算法类别、"
        "备案期次、属地做数据分析，附三条备案义务的合规要点。",
        "算法合规治理", "算法合规治理",
        "算法备案、深度合成备案、生成式人工智能服务备案与登记，是 AI 合规的三条法定入口。"
        "这一页把散落在几十份公告附件里的备案信息解析成结构化信息库，用于同业对标与内部申报。",
        "\n".join(body), COMMON_CSS)


def main():
    n = 0
    for fn, out in ((build_appviol, "news/app-violations.html"),
                    (build_algo, "news/algo-filing.html")):
        html_out = fn()
        if not html_out:
            print(f"  ! {out} 数据不足，跳过")
            continue
        p = os.path.join(HERE, out)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(html_out)
        print(f"✓ {out}　{len(html_out)/1024:.0f} KB")
        n += 1
    print(f"专项合规页构建完成：{n} 个（{date.today()}）")


if __name__ == "__main__":
    main()
