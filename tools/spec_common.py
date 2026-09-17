#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两个专项合规页共用的渲染部件与样式。

被 `build_special_topics.py`（算法合规治理）与 `appviol_page.py`（移动应用违规治理）
共享 —— 同一套 CSS / KPI / 柱条 / 发布主体登记表只写一遍，避免两处各改各的而走样。
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
/* 2026-09-17 数据块瘦身：KPI 卡 16px/26px → 10px/19px（单行高 104px → 约 62px），
   柱条轨道 16 → 11px。专题页是「读结论」的，不是「看海报」的。 */
.sp-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px;margin:16px 0 6px}
.sp-k{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 13px;box-shadow:var(--shadow)}
.sp-k b{display:block;font-size:19px;color:var(--brand);font-weight:800;line-height:1.25}
.sp-k span{display:block;color:var(--muted);font-size:12.2px;margin-top:2px}
.sp-k em{display:block;color:var(--faint);font-size:11px;font-style:normal;margin-top:1px}
.sp-sec{margin:30px 0 0}
.sp-sec h2{margin:0 0 6px;font-size:19px;color:var(--brand);display:flex;align-items:center;gap:9px}
.sp-sec h2::before{content:"";width:5px;height:19px;background:var(--accent);border-radius:3px}
.sp-sec p.lead{margin:0 0 12px}
.sp-tbl{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.sp-tbl th{background:#f2f6fb;color:var(--ink-2);font-weight:700;text-align:left;
  padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap;font-size:13px}
.sp-tbl td{padding:9px 12px;border-bottom:1px solid var(--line-2);vertical-align:top;color:var(--ink-2)}
.sp-tbl tr:last-child td{border-bottom:0}
.sp-tbl tr:hover td{background:#fafcff}
.sp-wrap{overflow:auto;border-radius:var(--radius)}
.sp-bar{display:flex;align-items:center;gap:9px;margin:5px 0}
.sp-bar .lb{width:190px;font-size:12.6px;color:var(--ink-2);flex:none;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.sp-bar .tr{flex:1;background:#eef2f7;border-radius:5px;height:11px;overflow:hidden;display:block}
/* ⚠️ 必须 display:block：.fl 是 <span>，行内元素会忽略 height/width，
   表现为「柱条只剩空轨道、没有任何数据填充」（曾整站踩过）。 */
.sp-bar .fl{display:block;height:100%;min-width:2px;
  background:linear-gradient(90deg,#2c6fb2,#0f7b6c);border-radius:5px}
.sp-bar .vv{width:52px;text-align:right;font-size:12.2px;color:var(--muted);flex:none;
  font-variant-numeric:tabular-nums}
.sp-note{background:#f7fafd;border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:10px;padding:12px 16px;color:var(--ink-2);font-size:13.2px;margin-top:14px}
.sp-note b{color:var(--ink)}
.sp-warn{background:#fff9f4;border-left-color:#e08a3c}
.sp-note ul{margin:8px 0 0;padding-left:18px}
.sp-note li{margin:5px 0}
/* 折叠式口径声明（2026-09-17）：方法学是附录，不该占掉首屏一整屏。
   展开前只留一行「对外引用什么数」，其余 8 条点开看。 */
.sp-fold{padding:0;overflow:hidden}
.sp-fold>summary{cursor:pointer;list-style:none;padding:11px 16px;font-size:13.4px;
  display:flex;align-items:center;gap:8px;user-select:none}
.sp-fold>summary::-webkit-details-marker{display:none}
.sp-fold>summary::before{content:"▸";color:#b3541e;font-size:12px;transition:transform .15s}
.sp-fold[open]>summary::before{transform:rotate(90deg)}
.sp-fold>summary:hover{background:rgba(224,138,60,.07)}
.sp-fold>summary b{color:var(--ink)}
.sp-fold-tldr{margin:0;padding:0 16px 11px;font-size:13px;line-height:1.85;color:var(--ink-2)}
.sp-fold[open]>.sp-fold-tldr{padding-top:2px}
.sp-fold>ul{padding:0 16px 14px 34px;margin:0}
.sp-fold[open]{padding-bottom:4px}
.sp-2col{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px;margin-top:12px}
.sp-card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:14px 16px;box-shadow:var(--shadow)}
.sp-card h4{margin:0 0 9px;font-size:14.2px;color:var(--ink)}
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
/* 机构 × 年份 热力矩阵：底色深浅表示通报量，空值为灰点 */
.sp-mx{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.sp-mx th{background:#f2f6fb;padding:8px 6px;text-align:center;font-weight:700;
  color:var(--ink-2);white-space:nowrap;border-bottom:1px solid var(--line);font-size:12px}
.sp-mx th.lft{text-align:left;padding-left:12px}
.sp-mx td{padding:7px 6px;text-align:center;border-bottom:1px solid var(--line-2);
  font-variant-numeric:tabular-nums;color:var(--ink-2);white-space:nowrap}
.sp-mx td.lft{text-align:left;padding-left:12px}
.sp-mx tr:hover td{background:#fafcff}
.sp-mx td.z{color:#ccd5df}
.sp-mx td.tt{font-weight:800;color:var(--brand);background:#f7fafd}
.sp-mx .sp-tag{margin:0}
/* 再犯时间线：一次通报一个小方块，色深表示处置升级 */
.sp-tk{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.sp-tk i{display:inline-block;width:11px;height:11px;border-radius:3px;background:#cfe0f2}
.sp-tk i.f{background:#f0d9a8}
.sp-tk i.c{background:#e8b1a8}
.sp-tk em{font-style:normal;font-size:12px;color:var(--faint);margin-left:4px}
@media(max-width:640px){.sp-bar .lb{width:110px}.sp-kpi{grid-template-columns:repeat(2,1fr)}
  .sp-mx{font-size:11.5px}.sp-mx td,.sp-mx th{padding:5px 3px}}
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
            f'<td>{link(it.get("entry"), it.get("entry_label") or "查看原文")}</td>'
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


def f2(v):
    """数字紧凑显示：3.0 → 3，0.5 → 0.5。机构年度计数含联合通报拆分的半份。"""
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else f"{v:g}"
    return str(v)


def mx_cell(v, mxv, cls=""):
    """热力矩阵单元格：底色深浅 ∝ 数值大小；空值为灰点。

    ⚠️ 用 inline `background` 而非 CSS 类，是为了让渲染函数只依赖数值、
    不依赖预先枚举档位（档位会随数据变化而失配）。
    """
    if not v:
        return '<td class="z">·</td>'
    t = min(1.0, v / mxv) if mxv else 0
    bg = f"rgba(44,111,178,{0.05 + 0.32 * t:.2f})"
    return f'<td class="{cls}" style="background:{bg}">{f2(v)}</td>'
