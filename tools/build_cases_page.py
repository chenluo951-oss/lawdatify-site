#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规案例库」页 kb/cases.html

数据源：sources/cases/cases.json（tools/harvest_cases.py 采集）
内容：监管处罚与通报案例的结构化索引 —— 机关、类型、日期、**被处罚主体**、
      **处罚事由**、依据法条、**处罚**、官方原文深链，并按类型 / 机关 / 年度
      给出分布，用于合规判断时反查同类执法口径。

⚠️ 两个字段的取数口径（2026-09-17 用户反馈后重做）：
  · **处罚事由** = 「为什么处罚」的违法事实，等价于裁判文书的「法院认定事实」。
    不是整页正文，更不是「当事人：XX 主体资格证照名称…」抬头或「近年来，
    市场监管总局按照…」通稿导语。抽取逻辑在 tools/case_reason.py。
  · **处罚** = 全部处罚种类与幅度（罚款、吊销营业执照、停业整顿、通报批评、
    没收违法所得、责令停产停业、列入严重违法失信名单…），不只有罚款。
    取数在**决定段**里找，见 tools/case_reason.py 的 extract_penalty()。
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
from case_gate import classify  # noqa: E402
from case_reason import extract_penalty, extract_reason  # noqa: E402

SRC = os.path.join(HERE, "sources", "cases", "cases.json")
# 法条 → 案例 的反向索引（tools/build_article_index.py 生成）。
# 本页用它把「依据」列里明确写出条号的引用做成可点链接（P1-2 的反方向）：
# 点进去要么落在「高频引用法条」对应条目，要么直落站内原文库的该条。
ART_REFS = os.path.join(HERE, "sources", "standards", "case_refs.json")


def load_art_refs():
    try:
        d = json.load(open(ART_REFS, encoding="utf-8"))
    except Exception:
        return {}, {}, {}
    m = d.get("_meta") or {}
    return m.get("by_case") or {}, m.get("hot") or {}, m.get("art_docs") or {}

# 类型标签配色：按类型名取稳定哈希（**不能用内置 hash()**：PYTHONHASHSEED
# 每次构建都变，同一类型两天两个颜色），6 色低饱和轮转，便于横向扫读。
def tag_cls(t):
    h = int(hashlib.md5((t or "").encode("utf-8")).hexdigest()[:6], 16)
    return f"t{h % 6}"


def case_id_of(url):
    """行锚点 id —— 必须与 tools/build_article_index.py 的 case_id() 完全一致，
    否则「高频引用法条 → 案例」的反向链接会落到页面顶部而不是具体那一行。"""
    return "cr-" + hashlib.md5((url or "").encode("utf-8")).hexdigest()[:10]


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
    # ── 闸门：滤掉「不是处罚案例」的条目（会议 / 报告 / 约谈 / 工作动态 / 行政裁决）
    # ⚠️ 数据不删，只在这里过滤：cases.json 里仍保留原记录与 noncase_reason，
    #    便于日后复核「这条为什么没上页面」。
    raw_n = len(cases)
    dropped = [c for c in cases if not classify(c.get("title"), c.get("fact"), c.get("kind"))[0]]
    cases = [c for c in cases if classify(c.get("title"), c.get("fact"), c.get("kind"))[0]]
    print(f"  · 闸门过滤：{raw_n} → {len(cases)} 条"
          f"（滤除 {len(dropped)} 条非处罚案例）")
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
    by_case, hot_map, doc_map = load_art_refs()
    n_with_art = 0
    with_subj = 0
    with_attach = 0
    with_reason = 0
    with_pen = 0
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
        # 优先用采集/回填时**从全文**抽好的 c["reason"]（决定书末尾的「为什么处罚」常常
        # 超出 900 字正文窗口，只有全文才抽得到）；没有就现场从 fact 抽。
        rs = c.get("reason")
        if rs is None:
            rs = extract_reason(fact, c.get("title"), c.get("kind"))["text"]
        rs = (rs or "").strip()
        rmode = c.get("reason_mode") or ""
        if rs:
            with_reason += 1
            # 汇编类是多起案件的列表（\n 分行），要保留换行 → CSS 用 white-space:pre-line
            btn = ('<button class="fx-b" type="button" aria-label="展开处罚事由"></button>'
                   if (len(rs) > 76 or "\n" in rs) else "")
            if rmode == "compilation" and c.get("reason_n"):
                head = (f'<span class="fx-n">共 {c["reason_n"]} 起案件 · 逐起违法事实</span>')
            else:
                head = ""
            fx_html = f'{head}<div class="fx-t">{esc(rs)}</div>{btn}'
        else:
            fx_html = '<span class="sbj-no">见原文</span>'

        # ── 处罚（种类 + 幅度） ────────────────────────────────────
        # 「罚款」只是处罚的一种。吊销营业执照 / 停业整顿 / 通报批评 / 没收违法所得
        # 一样是处罚结果，用户 2026-09-17 明确要求合并到一列。
        pen = c.get("pen")
        pkinds = c.get("pen_kinds") or []
        if pen is None:
            _p = extract_penalty(fact, c.get("fines"), c.get("title"), c.get("kind"))
            pen, pkinds = _p["text"], _p["kinds"]
        pen = (pen or "").strip()
        # 汇编类：一条公示装了 N 起案件，处罚金额也来自不同案件 → 鼠标悬停说明清楚，
        # 避免被读成「这一个主体被罚了这么多」。
        ptitle = (f' title="本条为 {c.get("reason_n")} 起案件的汇编，'
                  f'处罚种类与金额按各起案件合列，逐起对应关系见左侧「处罚事由」"'
                  if (rmode == "compilation" and c.get("reason_n", 0) >= 2) else "")
        if pen:
            with_pen += 1
            chunks = [x for x in pen.split("、") if x]
            pill, amts = [], []
            for x in chunks:
                if x.startswith("罚款") and len(x) > 2:
                    pill.append('<span class="pn-k pn-k-f">罚款</span>')
                    for v in x[2:].strip().split("／"):
                        if v:
                            amts.append(f'<span class="pn-a">{esc(v)}</span>')
                else:
                    tone = {"吊销营业执照": "s", "吊销许可证": "s", "责令停产停业": "s",
                            "没收违法所得": "m", "没收非法财物": "m",
                            "公开通报": "t", "通报批评": "t"}.get(x, "")
                    pill.append(f'<span class="pn-k{" pn-k-" + tone if tone else ""}">{esc(x)}</span>')
            pen_html = ('<div class="pn-w">' + "".join(pill)
                        + ("".join(amts) if amts else "") + "</div>")
        elif c.get("fines"):
            pen_html = ('<div class="pn-w">' + "".join(
                f'<span class="pn-a">{esc(v)}</span>' for v in c["fines"][:3]) + "</div>")
        else:
            pen_html = '<span class="sbj-no" title="公示正文未写处罚结果（部分通报只公布违法情形）">—</span>'

        # ── 原文 / 文书附件 ────────────────────────────────────────
        # 相当多的公示页正文是空壳，处罚内容只在 .docx/.pdf 里（见 tools/case_attach.py）。
        # 这类记录给两个入口：「原文」是公示页本身，「文书」直达决定书/告知书原件。
        ats = [u for u in (c.get("attach") or [])
               if isinstance(u, str) and u.startswith("http")]
        if ats:
            with_attach += 1
            att_html = (f'<a class="cs-att" href="{esc(ats[0])}" target="_blank" rel="noopener" '
                        f'title="处罚决定书 / 告知书原件（本行的处罚事由取自该文书）">文书</a>')
        else:
            att_html = ""

        # ── 依据：明确写出条号的引用做成可点链接 ────────────────────
        # 「只说法规名」的引用无法定位到条，保持纯文字；写成《X 法》第 X 条的，
        # 优先链到「高频引用法条」对应条目（那里有场景/处罚标准/竞合分析），
        # 没有则直落站内原文库该条。法条悬浮卡（assets/art-card.js）也认这些文字。
        url_c = c.get("url") or ""
        plist = [p for p in (by_case.get(url_c) or "").split(";") if p]
        lw_chips, seen_laws = [], set()
        for p in plist[:6]:
            law_n, _, art_n = p.rpartition("|")
            seen_laws.add(law_n)
            label = f"《{law_n}》{art_n}"
            hid = hot_map.get(p)
            if hid:
                href, tip = f"citations.html#{hid}", "在高频引用法条中查看该条（含场景与处罚标准）"
            else:
                did = doc_map.get(p)
                href = f"texts.html#{did}|{art_n}" if did else ""
                tip = "在站内原文库中定位该条"
            if href:
                lw_chips.append(f'<a class="lw-r" href="{esc(href)}" title="{tip}">{esc(label)}</a>')
            else:
                lw_chips.append(f'<span class="lw-r lw-r-p">{esc(label)}</span>')
        rest = []
        for nm_l in (c.get("laws") or []):
            k = re.sub(r"^中华人民共和国", "", re.sub(r"[\s《》]", "", nm_l))
            if k in seen_laws or nm_l in seen_laws:
                continue
            rest.append(nm_l)
        for nm_l in rest[:4]:
            lw_chips.append(f'<span class="lw-n">{esc(nm_l)}</span>')
        if len(rest) > 4:
            lw_chips.append(f'<span class="lw-n lw-n-more">等 {len(rest)} 部</span>')
        if plist:
            n_with_art += 1
        lw_html = ("".join(lw_chips) if lw_chips
                   else '<span class="sbj-no">—</span>')
        lw_title = law + ("　|　条文级引用：" + "；".join(plist) if plist else "")
        rows.append(
            f'<tr class="cr" id="{esc((case_id_of(url_c)))}">'
            f'<td class="dt">{esc(c.get("date") or "—")}</td>'
            f'<td class="ag">{esc(c.get("agency") or c.get("org") or "—")}</td>'
            f'<td class="ty"><span class="cs-tag {tag_cls(c.get("type"))}">{esc(c.get("type") or "其他")}</span></td>'
            f'<td class="tt"><div class="tt-t" title="{esc(c.get("title") or "")}">{esc(c.get("title") or "")}</div></td>'
            f'<td class="sbj">{sbj_html}</td>'
            f'<td class="fx">{fx_html}</td>'
            f'<td class="lw"><div class="lw-t" title="{esc(lw_title)}">{lw_html}</div></td>'
            f'<td class="fn"{ptitle}>{pen_html}</td>'
            f'<td class="lk"><a href="{esc(c.get("url"))}" target="_blank" rel="noopener">原文</a>'
            f'{att_html}</td>'
            "</tr>")

    css = """
/* KPI 只占**一行条**：8 张卡在 1248px 里排成 8 列需要 minmax ≤ 128px
   （8×128+7×8=1080 ≤ 1248）。原写 minmax(148px) 只能排 7 列 → 8 张卡折成两行、
   独占 149px，把首屏往下压了近 90px。数字卡是「读数」不是「海报」。 */
.cs-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:8px;margin:14px 0 4px}
.cs-k{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:8px 11px;box-shadow:var(--shadow)}
.cs-k b{display:block;font-size:18px;color:var(--brand);font-weight:800;line-height:1.22}
.cs-k span{display:block;color:var(--muted);font-size:11.8px;margin-top:2px}
.cs-sec{margin:26px 0 0}
/* 主体块（表格所在节）贴紧 KPI，不再让说明文字插在中间 */
.cs-sec.cs-main{margin:16px 0 0}
.cs-sec h2{margin:0 0 6px;font-size:19px;color:var(--brand);display:flex;align-items:center;gap:9px}
.cs-sec h2::before{content:"";width:5px;height:19px;background:var(--accent);border-radius:3px}
.cs-bar{display:flex;align-items:center;gap:9px;margin:5px 0}
.cs-bar .lb{width:190px;font-size:12.6px;color:var(--ink-2);flex:none;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.cs-bar .tr{flex:1;background:#eef2f7;border-radius:5px;height:11px;overflow:hidden;display:block}
/* ⚠️ 必须 display:block：.fl 是 <span>，行内元素忽略 height/width，
   否则柱条只剩空轨道、无数据填充（与 build_special_topics.py 同坑）。 */
.cs-bar .fl{display:block;height:100%;min-width:2px;
  background:linear-gradient(90deg,#b3541e,#c98a3c);border-radius:5px}
.cs-bar .vv{width:52px;text-align:right;font-size:12.5px;color:var(--muted);flex:none}
.cs-q{flex:1 1 300px;min-width:200px;padding:9px 13px;border:1px solid var(--line);
  border-radius:9px;font-size:13.5px;font-family:var(--sans);margin:0;color:var(--ink)}
.cs-note{background:#f7fafd;border:1px solid var(--line);border-left:4px solid var(--accent);
  border-radius:10px;padding:14px 18px;color:var(--ink-2);font-size:13.5px;margin-top:18px}
/* 「共 N 条」并进 <h2> 行右侧（JS 命中后改写为「命中 N 条 / 共 M 条」）——
   它本来就只是这一节的读数，独占一行会白占 ~30px。 */
.cs-cnt{margin-left:auto;color:var(--muted);font-size:12.5px;font-weight:600;letter-spacing:0}
/* 统计附录（2026-09-17 新增）：四组分布图默认收起，展开后限宽 920px——
   横条图在 1728px 宽的版面上会拉成一条横跨全屏的线，反而读不出差异。 */
.cs-stats{margin:26px 0 0;background:var(--card);border:1px solid var(--line);
  border-radius:var(--radius);padding:0 16px 4px}
.cs-stats>summary{cursor:pointer;padding:13px 0;font-size:14.5px;font-weight:700;color:var(--brand);
  list-style:none;display:flex;align-items:center;gap:9px}
.cs-stats>summary::-webkit-details-marker{display:none}
.cs-stats>summary::before{content:"";width:5px;height:17px;background:var(--accent);border-radius:3px;flex:none}
.cs-stats>summary::after{content:"展开";margin-left:auto;font-size:12px;font-weight:600;
  color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 10px}
.cs-stats[open]>summary::after{content:"收起"}
.cs-stats[open]>summary{border-bottom:1px solid var(--line-2)}
.cs-stats .cs-sec{max-width:920px}
.cs-stats .cs-sec:last-child{padding-bottom:14px}
/* 搜索框 + 机关 / 类型 两枚筛选器排**同一行**：原先是「搜索框独占一行 +
   筛选条再占一行」，两行控件把表格又往下推了 ~90px。
   同时去掉 <label>——select 的默认项（「全部机关」/「全部类型」）本身已自解释。 */
.cs-fl{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:11px 0 9px}
.cs-fl select{padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:var(--card);
  color:var(--ink);font-size:13px;font-family:var(--sans);max-width:236px}

/* ---------------- 明细表 ---------------- */
/* 表格是这一页的主体：信息密度高，靠「表头吸顶 + 首列吸附 + 横向滚动」保证
   在 1120px 里也能一次看完 9 列，不用来回找列名。 */
/* ⚠️ 可视高度跟视口走，别写死 660px：在 1440×900 上盒子底边会掉到屏幕外，
   用户得「先滚页面、再滚盒子」两层滚动。改 vh 后一屏内能看完一个整框。 */
.cs-wrap{overflow:auto;max-height:min(76vh,820px);border:1px solid var(--line);
  border-radius:var(--radius);background:var(--card);box-shadow:var(--shadow);
  -webkit-overflow-scrolling:touch}
/* ⚠️ 表格必须给**硬性最小宽度**（= 各列宽之和），否则 `width:100%` 会把 9 列
   硬挤进 1072px 容器：机关名「地方市场监督管理局」被折成竖排一个字一行，
   单元格上的 min-width 在 table-layout:auto 下不足以撑开列。给表格定宽后
   由 .cs-wrap 横向滚动，列宽才按设计生效。 */
.cs-tbl{width:100%;border-collapse:collapse;font-size:13.5px;min-width:1300px}
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
  font-variant-numeric:tabular-nums;width:88px;min-width:88px}
.cs-tbl td.ag{min-width:118px;max-width:134px;color:var(--ink-2)}
.cs-tbl td.tt{min-width:212px;max-width:236px;color:var(--ink);font-weight:600}
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
/* 条文级依据（P1-2）：案例正文明确写出《法规》第 X 条时，把它做成可点链接——
   点到「高频引用法条」对应条目（含场景 / 处罚标准 / 竞合分析），没有该条目则直落原文库。
   纯法规名保持灰字（无法定位到条）。 */
.lw-r{display:inline-block;margin:0 3px 3px 0;padding:1px 7px;border-radius:6px;
  background:#eef4fb;border:1px solid #d7e5f5;color:#1b4f8a;font-size:12px;
  font-weight:600;text-decoration:none;line-height:1.5;word-break:break-word}
.lw-r:hover{background:var(--brand);border-color:var(--brand);color:#fff;text-decoration:none}
.lw-r-p{background:#f4f6f9;border-color:#e5eaf1;color:var(--ink-2)}
.lw-n{display:inline;color:var(--muted)}
.lw-n-more{color:var(--faint)}
.cs-tbl td.fn{min-width:120px;max-width:156px;color:var(--ink-2);font-size:12.5px}
.cs-tbl td.lk{white-space:nowrap;width:92px;min-width:92px}
/* 「原文」列固定在右侧：9 列合计 1300px+ 超出 1120px 容器，中部要横向滚动，
   但**原文深链必须永远可点**（这一页存在的意义就是能直达官方原文）→ 右吸附。 */
.cs-tbl th:last-child,.cs-tbl td.lk{position:sticky;right:0;z-index:2;
  background:var(--card);box-shadow:-6px 0 8px -6px rgba(16,24,40,.13)}
/* 正文来自文书附件的行，额外给一个「文书」入口（直达 .docx/.pdf 原件），
   用描边款与实心的「原文」区分开，视觉上不抢主链。 */
.cs-tbl td.lk .cs-att{display:inline-block;margin-top:4px;padding:3px 9px;
  border:1px dashed #d6c3a8;border-radius:999px;color:#8a5a1e;font-size:12px;
  background:#fdfaf4;text-decoration:none}
.cs-tbl td.lk .cs-att:hover{background:#f6ecd9;border-color:#c9a877;text-decoration:none}
.cs-tbl th:last-child{z-index:4;background:#f2f6fb}
.cs-tbl tbody tr:nth-child(even) td.lk{background:#fcfdff}
.cs-tbl tr:hover td.lk{background:#f7fbff}
.cs-tbl td.lk a{display:inline-block;padding:4px 10px;border:1px solid #cfe0f2;border-radius:999px;
  background:#f4f9ff;color:var(--brand);font-size:12.5px;font-weight:600;text-decoration:none;
  transition:.16s}
.cs-tbl td.lk a::after{content:"↗";margin-left:3px;font-weight:400;font-size:11.5px}
.cs-tbl td.lk a:hover{background:var(--brand);border-color:var(--brand);color:#fff;text-decoration:none}

/* 类型标签：6 色轮转（服务端按类型名稳定取色）。
   ⚠️ 必须能收敛：标签 nowrap + 单元格有 max-width 时，长标签会**溢出单元格、
   直接压住「案件」列**（2026-09-17 用户截图：102 行「移动应用与个人信息」
   标签 126.3px 撑出 118px 的单元格 20.3px，连带表头也被盖住）。
   所以这里 ① 给 max-width:100% + 省略号兜底（将来出现更长的类型名也不会串列），
   ② 类型列宽度按当前最长类型名（9 字 ≈ 126px）定死，正常情况**完整显示不省略**。 */
.cs-tag{display:inline-block;border-radius:6px;padding:2px 8px;font-size:12px;
  white-space:nowrap;font-weight:600;max-width:100%;overflow:hidden;
  text-overflow:ellipsis;vertical-align:top}
.cs-tag.t0{background:#eef4fb;color:#1b4f8a}
.cs-tag.t1{background:#eaf4ef;color:#1c6349}
.cs-tag.t2{background:#fdf3e7;color:#8f5312}
.cs-tag.t3{background:#f2eefb;color:#55418f}
.cs-tag.t4{background:#fdeef1;color:#99304b}
.cs-tag.t5{background:#e9f4f6;color:#145e69}

/* 被处罚主体 */
.cs-tbl td.sbj{min-width:138px;max-width:158px}
/* 类型列（色块）：宽度按**当前最长类型名**（9 字「移动应用与个人信息」≈126px）
   + 左右内边距 24px 定死为 152px，让标签在不省略的情况下完整显示。
   此前收窄到 104/118px 是为了把横向空间让给「处罚事由 / 处罚」两列，
   但代价是长标签溢出压住「案件」列 —— 表格本来就横向滚动，
   多这 34px 不影响阅读，串列才是硬伤。 */
.cs-tbl td.ty{min-width:152px;max-width:152px}
.sbj-n{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  max-height:3.24em;color:var(--ink);font-weight:600;word-break:break-word;line-height:1.62}
.sbj-n em{font-style:normal;color:var(--muted);font-weight:400;font-size:12px;margin-left:4px;
  white-space:nowrap}
.sbj-no{color:var(--faint)}

/* 处罚事由：默认 2 行截断，点「展开」看全文（长文不把表格撑散） */
.cs-tbl td.fx{min-width:260px;max-width:330px;color:var(--ink-2);font-size:13px}
/* ⚠️ 只写 -webkit-line-clamp 不够：在 table-cell 里行高仍按**完整内容**计算，
   折叠后每行下方会留一大片空白（实测行高被撑到 200px+）。必须再给一个
   显式 max-height（2 行 × 行高）兜住盒子高度。 */
/* white-space:pre-line —— 典型案例汇编的事由是「逐起案件」的多行列表，
   不加这句换行会被折成一行，一屏只能看一条。 */
.fx-t{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;line-height:1.62;max-height:3.24em;white-space:pre-line}
.fx-n{display:block;margin-bottom:3px;font-size:11.6px;font-weight:700;color:var(--accent);
  letter-spacing:.3px}
.cs-tbl td.fx.open{max-width:none}
.cs-tbl td.fx.open .fx-t{display:block;overflow:visible;-webkit-line-clamp:unset;
  max-height:none;white-space:pre-line}
.fx-b{border:0;background:none;padding:0;margin-top:5px;cursor:pointer;
  font-family:var(--sans);font-size:12.5px;font-weight:600;color:var(--brand)}
/* 按钮文字用伪元素：不进 DOM 文本，避免被关键词搜索误命中 */
.fx-b::before{content:"展开事由"}
.cs-tbl td.fx.open .fx-b::before{content:"收起"}
.fx-b::after{content:" ▾";font-weight:400;color:var(--muted)}
.cs-tbl td.fx.open .fx-b::after{content:" ▴"}
.fx-b:hover{text-decoration:underline}

/* 处罚（种类 + 幅度）：罚款只是其中一种，吊销 / 停业 / 没收 / 通报都是处罚结果，
   用不同底色区分「严厉程度」，扫一眼就能看出这条是「罚钱」还是「吊照」。 */
.pn-w{display:flex;flex-wrap:wrap;gap:4px 5px;align-items:flex-start}
/* ⚠️ 标签**不能**加 `white-space:nowrap`：table-layout:auto 下不可断行的行内盒
   会把列撑到 min-content 宽度，「列入严重违法失信名单」这种长标签直接把处罚列
   顶到 150px+，表格整体溢出容器、最右侧的「原文 / 文书」吸附列盖住处罚列。
   中文天然可按字断行，去掉 nowrap 后列宽才由 max-width 说了算。 */
.pn-k{display:inline-block;border-radius:6px;padding:1px 7px;font-size:11.8px;
  font-weight:600;background:#eef4fb;color:#1b4f8a;line-height:1.4;word-break:break-word}
.pn-k-s{background:#fdeaea;color:#a01d1d}
.pn-k-m{background:#fdf3e7;color:#8f5312}
.pn-k-t{background:#eef7f1;color:#1c6349}
.pn-k-f{background:#fff4e5;color:#9a5b06}
.pn-a{display:block;width:100%;font-size:12.6px;font-weight:700;color:#8a3b0a;
  line-height:1.5;font-variant-numeric:tabular-nums}

@media(max-width:900px){
  .cs-tbl{min-width:840px}
  /* ⚠️ 这里**只能收「类型 / 依据」**，绝不能收「处罚」：罚款 → 处罚 这一列改造之后
     「处罚」是用户要看的主列（罚款/吊销/停业整顿/通报都在这），窄屏隐藏它等于把改动藏起来。
     旧写法收的是第 7 列（依据）**和第 8 列（处罚）**，正是踩了这个坑。 */
  .cs-tbl td.lw,.cs-tbl th:nth-child(7),
  .cs-tbl td.ty,.cs-tbl th:nth-child(3){display:none}
}
@media(max-width:640px){
  .cs-bar .lb{width:110px}.cs-kpi{grid-template-columns:repeat(2,1fr)}
  /* 窄屏三枚控件各占一行：搜索框铺满，两枚 select 平分一行 */
  .cs-q{flex:1 1 100%}
  .cs-fl select{flex:1 1 44%;max-width:none}
  .cs-tbl{min-width:660px;font-size:13px}
  .cs-tbl td.ag{display:none}
}
"""

    body = []
    body.append('<div class="cs-kpi">'
                f'<div class="cs-k"><b>{len(cases)}</b><span>处罚案例条数</span></div>'
                f'<div class="cs-k"><b>{with_subj}</b><span>已定位被处罚主体</span></div>'
                f'<div class="cs-k"><b>{with_reason}</b><span>已提炼处罚事由</span></div>'
                f'<div class="cs-k"><b>{with_attach}</b><span>取自文书附件</span></div>'
                f'<div class="cs-k"><b>{len([o for o in orgs if o != "未标注"])}</b><span>覆盖监管机关</span></div>'
                f'<div class="cs-k"><b>{len(types)}</b><span>违法类型</span></div>'
                f'<div class="cs-k"><b>{with_pen}</b><span>已解析处罚结果</span></div>'
                f'<div class="cs-k"><b>{n_with_art}</b><span>依据已精确到条</span></div>'
                '</div>')

    # 2026-09-18（用户报「那个案例库也是一样的，只有一个小框」）：
    # 「案例库怎么用」是纯说明文字，原先排在表格**前面**，连同「案例明细」的 5 行导语
    # 把表格起点推到 821px（1440×1000 视口只有 913px）——首屏只剩 ~90px 表格，
    # 看着就是"一个小框"。按 static-site-fold-layout 的配方处理：
    # **正文（表格）提到说明块之前**，说明文字与表尾「数据说明」合并下移。
    howto_head = ('<section class="cs-sec"><h2>案例库怎么用</h2>'
             '<p class="lead">按违法类型、执法机关、依据法条与实际处罚结果做结构化索引，'
             '写风险评估、做业务评审、回应监管问询时可直接反查同类先例。</p>')

    # 2026-09-17（用户要求「没必要的废话废图表就删掉」）：
    # 四组分布图原先铺在案例表**前面**，在 1728px 宽的版面上每条横条要横跨整个屏幕，
    # 表格却被压到第 5 屏；这与用户此前对首页的抱怨（「图表太大、正文在最下面」）同型。
    # 改为：表格紧跟导语，四组统计折叠到表尾的 <details> 里，默认收起。
    stats = []
    stats.append('<section class="cs-sec"><h2>违法类型分布</h2>' + bars(types.most_common(14))
                 + "</section>")
    stats.append('<section class="cs-sec"><h2>执法机关分布</h2>' + bars(orgs.most_common(14))
                 + "</section>")
    stats.append('<section class="cs-sec"><h2>年度分布</h2>'
                 + bars(sorted(years.items()), limit=12) + "</section>")
    if laws:
        stats.append('<section class="cs-sec"><h2>高频依据法条</h2>'
                     '<p class="lead">案例正文中援引的法律法规名称（仅统计明确写出书名号的引用）。</p>'
                     + bars(laws.most_common(16)) + "</section>")

    # 表格节：标题行内联读数 + 搜索/筛选同一行 + 表格。**不插任何说明段落**——
    # 说明文字全部下移到表尾（见下方 howto_head / note）。
    body.append('<section class="cs-sec cs-main">'
                f'<h2>案例明细<span class="cs-cnt" id="cc">共 {len(cases)} 条</span></h2>'
                '<div class="cs-fl">'
                '<input class="cs-q" id="cq" type="search" '
                'placeholder="搜索关键词，例如：虚假宣传、明码标价、过期食品、个人信息">'
                '<select id="ca" aria-label="按执法机关筛选">'
                '<option value="">全部机关</option>'
                + "".join(f'<option value="{esc(a)}">{esc(a)}（{n}）</option>'
                          for a, n in agys.most_common() if a != "未标注")
                + '</select><select id="cty" aria-label="按违法类型筛选">'
                '<option value="">全部类型</option>'
                + "".join(f'<option value="{esc(t)}">{esc(t)}（{n}）</option>'
                          for t, n in types.most_common())
                + '</select></div>'
                '<div class="cs-wrap"><table class="cs-tbl" id="ct"><thead><tr>'
                "<th>日期</th><th>机关</th><th>类型</th><th>案件</th>"
                "<th>被处罚主体</th><th>处罚事由</th>"
                "<th>依据</th><th>处罚</th><th>原文 / 文书</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div></section>")

    body.append('<details class="cs-stats"><summary>统计视角：违法类型 / 执法机关 / 年度 / 高频依据法条</summary>'
                + "".join(stats) + "</details>")

    note = ('<div class="cs-note"><b>数据说明</b>　'
                '只收<b>监管机关作出的行政处罚与执法通报</b>：处罚决定书、行政处罚信息公开表、'
                '典型案例通报、App 违规通报；会议、座谈、年度报告、政策出台、约谈、'
                '专项整治工作动态不计入（不含被处罚主体）。'
                '来源为监管机关官方网站（市场监管总局曝光台、中央网信办与工业和信息化部通报、'
                '省市市场监督管理局官网的「行政处罚公示 / 案件信息公开表」等）公开页面，链接直达原文；'
                '一条公示内含多案的，按案件拆分并定位到该案所在的页面。'
                '<b>被处罚主体</b>取自正文「当事人」标注或案件叙述里的企业全称，'
                '一条公示打包多起案件的显示「等 N 家」；公示对当事人脱敏（写作 `***`）'
                '或正文未标注的留空，可在原文中核对。'
                '<b>处罚事由、依据、处罚结果由正文自动解析</b>：「处罚事由」只取认定违法事实的段落；'
                '「处罚」收录罚款金额与吊销营业执照、责令停产停业、没收违法所得、通报批评等全部种类；'
                '公示页正文为空、内容只在附件里的，已<b>下载并解析其 Word / PDF / Excel 文书</b>'
                '后并入本行，并在「原文」列旁给出<b>文书</b>入口直达原件。'
                '<b>个案的事实认定与处罚幅度以官方发布的处罚决定书 / 通报原文为准</b>，本库随每日构建增量补入。</div>')

    # 表尾顺序：统计视角（折叠）→「案例库怎么用」+ 数据说明（同一块，紧邻表格）。
    body.append(howto_head + note + '</section>')

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
<meta name="description" content="监管处罚与通报案例的结构化索引：按被处罚主体、处罚事由、违法类型、执法机关、依据法条与实际处罚结果归类，逐条附发布机关官网原文深链，用于反查同类执法口径。">
<link rel="stylesheet" href="../assets/style.css">
<style>{css}</style>
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 案例库</div>
  <h1>合规案例库</h1>
  <p>把监管机关公开的处罚决定、通报与典型案例结构化：同类行为怎么定性、按哪条罚、罚到什么程度，一屏可查。每条的「处罚事由」是认定违法事实的段落，「处罚」含罚款与吊销营业执照、停业整顿、通报等全部处罚种类。</p>
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
