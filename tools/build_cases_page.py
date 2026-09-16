#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规案例库」页 kb/cases.html

数据源：sources/cases/cases.json（tools/harvest_cases.py 采集）
内容：监管处罚与通报案例的结构化索引 —— 机关、类型、日期、依据法条、罚款幅度、官方原文深链，
      并按类型 / 机关 / 年度给出分布，用于合规判断时反查同类执法口径。
"""
import html
import json
import os
import re
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "sources", "cases", "cases.json")


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def bars(rows, limit=14):
    if not rows:
        return ""
    mx = max(v for _, v in rows) or 1
    out = []
    for lb, v in rows[:limit]:
        w = max(2, round(v / mx * 100))
        out.append(f'<div class="cs-bar"><span class="lb" title="{esc(lb)}">{esc(lb)}</span>'
                   f'<span class="tr"><span class="fl" style="width:{w}%"></span></span>'
                   f'<span class="vv">{v}</span></div>')
    return "".join(out)


def main():
    if not os.path.exists(SRC):
        print("  ! 案例数据不存在，跳过 kb/cases.html")
        return 1
    d = json.load(open(SRC, encoding="utf-8"))
    cases = d.get("cases") or []
    if not cases:
        print("  ! 案例库为空，跳过")
        return 1

    orgs = Counter(c.get("org") or "未标注" for c in cases)
    types = Counter(c.get("type") or "其他" for c in cases)
    # 表格里显示的是**具体机关名**（如「广东省市场监督管理局」），筛选也用同一口径，
    # 否则会出现「表里写具体局名、下拉只有分类桶」的对不上。
    agys = Counter(c.get("agency") or c.get("org") or "未标注" for c in cases)
    years = Counter((c.get("date") or "")[:4] for c in cases if c.get("date"))
    with_fine = sum(1 for c in cases if c.get("fines"))
    laws = Counter()
    for c in cases:
        for x in c.get("laws") or []:
            laws[x] += 1

    rows = []
    for c in cases:
        law = "、".join(c.get("laws") or [])[:60]
        fine = "、".join(c.get("fines") or [])
        rows.append(
            "<tr class=\"cr\">"
            f'<td>{esc(c.get("date") or "—")}</td>'
            f'<td>{esc(c.get("agency") or c.get("org") or "—")}</td>'
            f'<td><span class="cs-tag">{esc(c.get("type") or "其他")}</span></td>'
            f'<td class="tt">{esc(c.get("title") or "")}</td>'
            f'<td>{esc(law) or "—"}</td>'
            f'<td>{esc(fine) or "—"}</td>'
            f'<td><a href="{esc(c.get("url"))}" target="_blank" rel="noopener">原文</a></td>'
            "</tr>")

    css = """
.cs-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 6px}
.cs-k{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.cs-k b{display:block;font-size:26px;color:var(--brand);font-weight:800;line-height:1.25}
.cs-k span{display:block;color:var(--muted);font-size:12.5px;margin-top:4px}
.cs-sec{margin:44px 0 0}
.cs-sec h2{margin:0 0 6px;font-size:20px;color:var(--brand);display:flex;align-items:center;gap:9px}
.cs-sec h2::before{content:"";width:5px;height:20px;background:var(--accent);border-radius:3px}
.cs-tbl{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.cs-tbl th{background:#f2f6fb;color:var(--ink-2);font-weight:700;text-align:left;
  padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap;font-size:13px}
.cs-tbl td{padding:10px 12px;border-bottom:1px solid var(--line-2);vertical-align:top;color:var(--ink-2)}
.cs-tbl tr:last-child td{border-bottom:0}
.cs-tbl tr:hover td{background:#fafcff}
.cs-tbl td.tt{max-width:340px}
/* 日期与「原文」列必须 nowrap：列宽被挤时中文会逐字拆行（「原」/「文」两行）。 */
.cs-tbl td:first-child,.cs-tbl td:last-child{white-space:nowrap}
.cs-wrap{overflow:auto;border-radius:var(--radius);max-height:620px}
.cs-tag{display:inline-block;background:#eef4fb;color:#1b4f8a;border-radius:6px;
  padding:2px 8px;font-size:12px;white-space:nowrap}
.cs-bar{display:flex;align-items:center;gap:10px;margin:7px 0}
.cs-bar .lb{width:200px;font-size:13px;color:var(--ink-2);flex:none;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.cs-bar .tr{flex:1;background:#eef2f7;border-radius:6px;height:16px;overflow:hidden;display:block}
/* ⚠️ 必须 display:block：.fl 是 <span>，行内元素忽略 height/width，
   否则柱条只剩空轨道、无数据填充（与 build_special_topics.py 同坑）。 */
.cs-bar .fl{display:block;height:100%;min-width:2px;
  background:linear-gradient(90deg,#b3541e,#c98a3c);border-radius:6px}
.cs-bar .vv{width:52px;text-align:right;font-size:12.5px;color:var(--muted);flex:none}
.cs-q{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;
  font-size:14px;font-family:var(--sans);margin:12px 0;color:var(--ink)}
.cs-note{background:#f7fafd;border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:10px;padding:14px 18px;color:var(--ink-2);font-size:13.5px;margin-top:18px}
.cs-cnt{color:var(--muted);font-size:13px;margin:8px 0 0}
.cs-fl{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:0 0 6px}
.cs-fl label{color:var(--muted);font-size:13px}
.cs-fl select{padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:var(--card);
  color:var(--ink);font-size:13px;font-family:var(--sans);max-width:260px}
@media(max-width:640px){.cs-bar .lb{width:110px}.cs-kpi{grid-template-columns:repeat(2,1fr)}}
"""

    body = []
    body.append('<div class="cs-kpi">'
                f'<div class="cs-k"><b>{len(cases)}</b><span>案例条数</span></div>'
                f'<div class="cs-k"><b>{len([o for o in orgs if o != "未标注"])}</b><span>覆盖监管机关</span></div>'
                f'<div class="cs-k"><b>{len(types)}</b><span>违法类型</span></div>'
                f'<div class="cs-k"><b>{with_fine}</b><span>标明罚款幅度</span></div>'
                '</div>')

    body.append('<section class="cs-sec"><h2>案例库怎么用</h2>'
                '<p class="lead">合规判断最容易出错的地方不是「有没有这条规定」，'
                '而是「同类行为在实践中怎么定性、按哪条罚、罚到什么程度」。'
                '这一页把监管机关官网公开的处罚决定、通报与典型案例，'
                '按违法类型、执法机关、依据法条和罚款幅度做了结构化索引——'
                '写内部风险提示、做业务评审、回应监管问询时，可直接反查同类先例。</p></section>')

    body.append('<section class="cs-sec"><h2>违法类型分布</h2>' + bars(types.most_common(14))
                + "</section>")
    body.append('<section class="cs-sec"><h2>执法机关分布</h2>' + bars(orgs.most_common(14))
                + "</section>")
    body.append('<section class="cs-sec"><h2>年度分布</h2>'
                + bars(sorted(years.items()), limit=12) + "</section>")
    if laws:
        body.append('<section class="cs-sec"><h2>高频依据法条</h2>'
                    '<p class="lead">案例正文中援引的法律法规名称（仅统计明确写出书名号的引用）。</p>'
                    + bars(laws.most_common(16)) + "</section>")

    body.append('<section class="cs-sec"><h2>案例明细</h2>'
                '<p class="lead">可按当事人、事由、机关、法条或类型检索。'
                '「依据」与「罚款」为正文解析结果，最终以官方原文为准。</p>'
                '<input class="cs-q" id="cq" type="search" '
                'placeholder="搜索关键词，例如：虚假宣传、明码标价、过期食品、个人信息">'
                '<div class="cs-fl"><label for="ca">机关</label>'
                '<select id="ca"><option value="">全部机关</option>'
                + "".join(f'<option value="{esc(a)}">{esc(a)}（{n}）</option>'
                          for a, n in agys.most_common() if a != "未标注")
                + '</select><label for="cty">类型</label><select id="cty">'
                '<option value="">全部类型</option>'
                + "".join(f'<option value="{esc(t)}">{esc(t)}（{n}）</option>'
                          for t, n in types.most_common())
                + '</select></div>'
                f'<p class="cs-cnt" id="cc">共 {len(cases)} 条</p>'
                '<div class="cs-wrap"><table class="cs-tbl" id="ct"><thead><tr>'
                "<th>日期</th><th>机关</th><th>类型</th><th>案件</th>"
                "<th>依据</th><th>罚款</th><th>原文</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div></section>")

    body.append('<div class="cs-note"><b>数据说明</b>　'
                '案例全部取自监管机关官方网站（市场监管总局曝光台与总局要闻、'
                '中央网信办与工业和信息化部通报、省市市场监督管理局官网的'
                '「行政处罚公示 / 案件信息公开表」等）公开页面，链接直达原文；'
                '一条公示内含多案的，按案件拆分并定位到该案所在的页面。'
                '类型、依据、罚款幅度由正文自动解析，可能存在遗漏，'
                '<b>个案的事实认定与处罚幅度以官方发布的处罚决定书/通报原文为准</b>。'
                '本库随每日构建增量补入。</div>')

    body.append("""<script>
(function(){
  var q=document.getElementById('cq'),t=document.getElementById('ct'),c=document.getElementById('cc');
  var fa=document.getElementById('ca'),fy=document.getElementById('cty');
  if(!q||!t) return;
  var rows=[].slice.call(t.tBodies[0].rows);
  function apply(){
    var s=q.value.trim().toLowerCase(),a=fa?fa.value:'',y=fy?fy.value:'',n=0;
    rows.forEach(function(r){
      var cells=r.cells,txt=r.textContent.toLowerCase();
      var ok=(!s||txt.indexOf(s)>-1)&&(!a||cells[1].textContent.trim()===a)&&(!y||cells[2].textContent.trim()===y);
      r.style.display=ok?'':'none'; if(ok) n++;
    });
    c.textContent='命中 '+n+' 条 / 共 '+rows.length+' 条';
  }
  q.addEventListener('input',apply);
  if(fa) fa.addEventListener('change',apply);
  if(fy) fy.addEventListener('change',apply);
})();
</script>""")

    out = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>合规案例库 · 合规无终点</title>
<meta name="description" content="监管处罚与通报案例的结构化索引：按违法类型、执法机关、依据法条与罚款幅度归类，逐条附发布机关官网原文深链，用于反查同类执法口径。">
<link rel="stylesheet" href="../assets/style.css">
<style>{css}</style>
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 案例库</div>
  <h1>合规案例库</h1>
  <p>把监管机关公开的处罚决定、通报与典型案例结构化：同类行为怎么定性、按哪条罚、罚到什么程度，一屏可查。</p>
</div></div>

<main class="wrap">
{chr(10).join(body)}
</main>

<footer></footer>
</body>
</html>
"""
    p = os.path.join(HERE, "kb", "cases.html")
    open(p, "w", encoding="utf-8").write(out)
    print(f"✓ kb/cases.html　{len(cases)} 条案例　{len(out)/1024:.0f} KB（{date.today()}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
