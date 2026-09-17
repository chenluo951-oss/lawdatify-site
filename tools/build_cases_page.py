#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规案例库」页 kb/cases.html

数据源：sources/cases/cases.json（tools/harvest_cases.py 采集）
内容：监管处罚与通报案例的结构化索引 —— 机关、类型、日期、**被处罚主体**、
      **处罚事由**、依据法条、罚款幅度、官方原文深链，并按类型 / 机关 / 年度
      给出分布，用于合规判断时反查同类执法口径。
"""
import hashlib
import html
import json
import os
import re
import sys
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from case_subject import extract_subject, format_subject  # noqa: E402

SRC = os.path.join(HERE, "sources", "cases", "cases.json")

# 类型标签配色：按类型名取稳定哈希（**不能用内置 hash()**：PYTHONHASHSEED
# 每次构建都变，同一类型两天两个颜色），6 色低饱和轮转，便于横向扫读。
def tag_cls(t):
    h = int(hashlib.md5((t or "").encode("utf-8")).hexdigest()[:6], 16)
    return f"t{h % 6}"


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
    with_subj = 0
    with_fact = sum(1 for c in cases if c.get("fact"))
    for c in cases:
        law = "、".join(c.get("laws") or [])
        fine = "、".join(c.get("fines") or [])
        fact = (c.get("fact") or "").strip()

        # ── 被处罚主体 ────────────────────────────────────────────
        nm, nn = extract_subject(fact, c.get("title"))
        sbj = format_subject(nm, nn)
        if sbj:
            with_subj += 1
            if nn and nn > 1 and sbj.endswith("家"):
                head = sbj.split(" 等 ")[0]
                sbj_html = (f'<span class="sbj-n" title="{esc(sbj)}">{esc(head)}'
                            f'<em>等 {esc(sbj.split(" 等 ")[-1])}</em></span>')
            else:
                sbj_html = f'<span class="sbj-n" title="{esc(sbj)}">{esc(sbj)}</span>'
        else:
            # 空值分两种：正文里根本没写（App 通报）或官方对当事人做了脱敏
            # （广东的决定书把企业名打成 `******`）——都是「原文里没有」，不是解析失败
            sbj_html = '<span class="sbj-no" title="正文未标注当事人（部分公示作了脱敏）">—</span>'

        # ── 处罚事由（长文折叠） ──────────────────────────────────
        if fact:
            btn = ('<button class="fx-b" type="button" aria-label="展开处罚事由"></button>'
                   if len(fact) > 76 else "")
            fx_html = f'<div class="fx-t">{esc(fact)}</div>{btn}'
        else:
            fx_html = '<span class="sbj-no">见原文</span>'

        rows.append(
            "<tr class=\"cr\">"
            f'<td class="dt">{esc(c.get("date") or "—")}</td>'
            f'<td class="ag">{esc(c.get("agency") or c.get("org") or "—")}</td>'
            f'<td><span class="cs-tag {tag_cls(c.get("type"))}">{esc(c.get("type") or "其他")}</span></td>'
            f'<td class="tt"><div class="tt-t" title="{esc(c.get("title") or "")}">{esc(c.get("title") or "")}</div></td>'
            f'<td class="sbj">{sbj_html}</td>'
            f'<td class="fx">{fx_html}</td>'
            f'<td class="lw"><div class="lw-t" title="{esc(law)}">{esc(law) or "—"}</div></td>'
            f'<td class="fn">{esc(fine) or "—"}</td>'
            f'<td class="lk"><a href="{esc(c.get("url"))}" target="_blank" rel="noopener">原文</a></td>'
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

/* ---------------- 明细表 ---------------- */
/* 表格是这一页的主体：信息密度高，靠「表头吸顶 + 首列吸附 + 横向滚动」保证
   在 1120px 里也能一次看完 9 列，不用来回找列名。 */
.cs-wrap{overflow:auto;max-height:660px;border:1px solid var(--line);
  border-radius:var(--radius);background:var(--card);box-shadow:var(--shadow);
  -webkit-overflow-scrolling:touch}
/* ⚠️ 表格必须给**硬性最小宽度**（= 各列宽之和），否则 `width:100%` 会把 9 列
   硬挤进 1072px 容器：机关名「地方市场监督管理局」被折成竖排一个字一行，
   单元格上的 min-width 在 table-layout:auto 下不足以撑开列。给表格定宽后
   由 .cs-wrap 横向滚动，列宽才按设计生效。 */
.cs-tbl{width:100%;border-collapse:collapse;font-size:13.5px;min-width:1280px}
.cs-tbl th{position:sticky;top:0;z-index:3;background:#f2f6fb;color:#42536b;font-weight:700;
  text-align:left;padding:11px 12px;border-bottom:1px solid var(--line);white-space:nowrap;
  font-size:12.5px;letter-spacing:.3px}
.cs-tbl td{padding:11px 12px;border-bottom:1px solid var(--line-2);vertical-align:top;
  color:var(--ink-2);line-height:1.62}
.cs-tbl tbody tr:nth-child(even) td{background:#fcfdff}
.cs-tbl tr:hover td{background:#f7fbff}
.cs-tbl tr:last-child td{border-bottom:0}
/* 日期列吸附在左侧：横向滚动时仍能定位是哪一条 */
.cs-tbl th:first-child,.cs-tbl td:first-child{position:sticky;left:0;z-index:2;
  background:var(--card);box-shadow:6px 0 8px -6px rgba(16,24,40,.13)}
.cs-tbl th:first-child{z-index:4}
.cs-tbl tbody tr:nth-child(even) td:first-child{background:#fcfdff}
.cs-tbl tr:hover td:first-child{background:#f7fbff}

.cs-tbl td.dt{white-space:nowrap;color:var(--muted);font-size:12.5px;
  font-variant-numeric:tabular-nums;width:96px}
.cs-tbl td.ag{min-width:150px;max-width:170px;color:var(--ink-2)}
.cs-tbl td.tt{min-width:238px;max-width:280px;color:var(--ink);font-weight:600}
/* 标题也夹到 3 行：决定书标题常 30+ 字（「…行政处罚文书送达公告（青黄市监罚送告
   〔2026〕4437-4461号）」），不夹会把行高推到 150px+。完整标题在 title 属性里。 */
.tt-t{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
  overflow:hidden;line-height:1.62;max-height:4.86em}
.cs-tbl td.lw{min-width:168px;max-width:210px;color:var(--muted);font-size:12.5px}
/* 同 .fx-t：line-clamp 在 table-cell 里不限制盒子高度，必须显式给 max-height
   （3 行 × 1.62 行高）。不写的话 6 部法规的依据串会把整行撑到 205px，
   表格出现大片空白 —— 实测就是这个原因。 */
.lw-t{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
  overflow:hidden;max-height:4.86em}
.cs-tbl td.fn{min-width:112px;max-width:150px;color:var(--warn);font-weight:600;font-size:12.5px}
.cs-tbl td.lk{white-space:nowrap;width:74px}
/* 「原文」列固定在右侧：9 列合计 1300px+ 超出 1120px 容器，中部要横向滚动，
   但**原文深链必须永远可点**（这一页存在的意义就是能直达官方原文）→ 右吸附。 */
.cs-tbl th:last-child,.cs-tbl td.lk{position:sticky;right:0;z-index:2;
  background:var(--card);box-shadow:-6px 0 8px -6px rgba(16,24,40,.13)}
.cs-tbl th:last-child{z-index:4;background:#f2f6fb}
.cs-tbl tbody tr:nth-child(even) td.lk{background:#fcfdff}
.cs-tbl tr:hover td.lk{background:#f7fbff}
.cs-tbl td.lk a{display:inline-block;padding:4px 10px;border:1px solid #cfe0f2;border-radius:999px;
  background:#f4f9ff;color:var(--brand);font-size:12.5px;font-weight:600;text-decoration:none;
  transition:.16s}
.cs-tbl td.lk a::after{content:"↗";margin-left:3px;font-weight:400;font-size:11.5px}
.cs-tbl td.lk a:hover{background:var(--brand);border-color:var(--brand);color:#fff;text-decoration:none}

/* 类型标签：6 色轮转（服务端按类型名稳定取色） */
.cs-tag{display:inline-block;border-radius:6px;padding:2px 8px;font-size:12px;
  white-space:nowrap;font-weight:600}
.cs-tag.t0{background:#eef4fb;color:#1b4f8a}
.cs-tag.t1{background:#eaf4ef;color:#1c6349}
.cs-tag.t2{background:#fdf3e7;color:#8f5312}
.cs-tag.t3{background:#f2eefb;color:#55418f}
.cs-tag.t4{background:#fdeef1;color:#99304b}
.cs-tag.t5{background:#e9f4f6;color:#145e69}

/* 被处罚主体 */
.cs-tbl td.sbj{min-width:156px;max-width:210px}
.sbj-n{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  max-height:3.24em;color:var(--ink);font-weight:600;word-break:break-word;line-height:1.62}
.sbj-n em{font-style:normal;color:var(--muted);font-weight:400;font-size:12px;margin-left:4px;
  white-space:nowrap}
.sbj-no{color:var(--faint)}

/* 处罚事由：默认 2 行截断，点「展开」看全文（长文不把表格撑散） */
.cs-tbl td.fx{min-width:262px;max-width:360px;color:var(--ink-2);font-size:13px}
/* ⚠️ 只写 -webkit-line-clamp 不够：在 table-cell 里行高仍按**完整内容**计算，
   折叠后每行下方会留一大片空白（实测行高被撑到 200px+）。必须再给一个
   显式 max-height（2 行 × 行高）兜住盒子高度。 */
.fx-t{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;line-height:1.62;max-height:3.24em}
.cs-tbl td.fx.open{max-width:none}
.cs-tbl td.fx.open .fx-t{display:block;overflow:visible;-webkit-line-clamp:unset;
  max-height:none}
.fx-b{border:0;background:none;padding:0;margin-top:5px;cursor:pointer;
  font-family:var(--sans);font-size:12.5px;font-weight:600;color:var(--brand)}
/* 按钮文字用伪元素：不进 DOM 文本，避免被关键词搜索误命中 */
.fx-b::before{content:"展开事由"}
.cs-tbl td.fx.open .fx-b::before{content:"收起"}
.fx-b::after{content:" ▾";font-weight:400;color:var(--muted)}
.cs-tbl td.fx.open .fx-b::after{content:" ▴"}
.fx-b:hover{text-decoration:underline}

@media(max-width:900px){
  .cs-tbl{min-width:840px}
  .cs-tbl td.lw,.cs-tbl th:nth-child(7),
  .cs-tbl td.fn,.cs-tbl th:nth-child(8){display:none}
}
@media(max-width:640px){
  .cs-bar .lb{width:110px}.cs-kpi{grid-template-columns:repeat(2,1fr)}
  .cs-tbl{min-width:660px;font-size:13px}
  .cs-tbl td.ag{display:none}
}
"""

    body = []
    body.append('<div class="cs-kpi">'
                f'<div class="cs-k"><b>{len(cases)}</b><span>案例条数</span></div>'
                f'<div class="cs-k"><b>{with_subj}</b><span>已定位被处罚主体</span></div>'
                f'<div class="cs-k"><b>{with_fact}</b><span>含处罚事由正文</span></div>'
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
                '<p class="lead">可按被处罚主体、处罚事由、机关、法条或类型检索；'
                '「处罚事由」默认收起，点「展开事由」看正文全文；'
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
                "<th>被处罚主体</th><th>处罚事由</th>"
                "<th>依据</th><th>罚款</th><th>原文</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div></section>")

    body.append('<div class="cs-note"><b>数据说明</b>　'
                '案例全部取自监管机关官方网站（市场监管总局曝光台与总局要闻、'
                '中央网信办与工业和信息化部通报、省市市场监督管理局官网的'
                '「行政处罚公示 / 案件信息公开表」等）公开页面，链接直达原文；'
                '一条公示内含多案的，按案件拆分并定位到该案所在的页面。'
                '<b>被处罚主体</b>取自正文中的「当事人」标注或案件叙述里的企业全称，'
                '一条公示打包多起案件的显示「等 N 家」；'
                '部分公示对当事人作了脱敏（决定书里写作 `***`）、'
                '或正文未标注当事人（部分 App 通报），该字段留空，可在原文中核对。'
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

  // 处罚事由展开/收起：事件委托到 tbody，699 行不用绑 699 个监听。
  // 折叠靠 CSS 的 -webkit-line-clamp，展开只是切换 td 上的 .open 类（button 默认
  // 回车/空格即触发 click，键盘可达；这里额外同步 aria-expanded 状态）。
  t.addEventListener('click',function(e){
    var b=e.target.closest?e.target.closest('.fx-b'):null;
    if(!b) return;
    var td=b.parentNode; if(!td||!td.classList) return;
    td.classList.toggle('open');
    b.setAttribute('aria-expanded', td.classList.contains('open')?'true':'false');
  });
})();
</script>""")

    out = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>合规案例库 · 合规无终点</title>
<meta name="description" content="监管处罚与通报案例的结构化索引：按被处罚主体、处罚事由、违法类型、执法机关、依据法条与罚款幅度归类，逐条附发布机关官网原文深链，用于反查同类执法口径。">
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
