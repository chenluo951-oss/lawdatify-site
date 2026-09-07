#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lawdatify 站点 · 模块生成脚本（打磨日志 + 对标库）

读取：
  ~/.workbuddy/skills/compliance-report-generator/references/polish_changelog.md
  ~/.workbuddy/skills/compliance-report-generator/references/benchmark_reports.md

生成：
  lawdatify-site/analysis/polish.html     （打磨日志·按时间倒序时间线卡片）
  lawdatify-site/kb/benchmarks.html       （对标库·按分类卡片矩阵）

同步：assets/manifest.json 加入两个新页面，确保站内搜索可索引。

可重复运行；源 md 文件不变，本脚本只解析并渲染到站点侧。
"""
import os
import re
import html
import json
import datetime

# 路径可配置：本地默认读 skill 的 references；云端（GitHub Actions）通过 REFS_DIR
# 指向仓库内 sources/references/。DST_ROOT 恒为脚本所在目录，本地/云端通用。
REFS = os.environ.get("REFS_DIR") or os.path.expanduser(
    "~/.workbuddy/skills/compliance-report-generator/references"
)
DST_ROOT = os.path.dirname(os.path.abspath(__file__))
POLISH_OUT = os.path.join(DST_ROOT, "analysis", "polish.html")
BENCH_OUT = os.path.join(DST_ROOT, "kb", "benchmarks.html")
MANIFEST = os.path.join(DST_ROOT, "assets", "manifest.json")

POLISH_FILE = os.path.join(REFS, "polish_changelog.md")
BENCH_FILE = os.path.join(REFS, "benchmark_reports.md")


def h(s):
    return html.escape("" if s is None else str(s), quote=False)


def md_to_html(md):
    """极简 Markdown 渲染：仅处理 GFM 表格、列表、引用、段落；其余转义输出。"""
    out = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # GFM 表格
        if (
            line.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
        ):
            header = [c.strip() for c in line.strip("|").split('|')]
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                row = [c.strip() for c in lines[i].strip('|').split('|')]
                rows.append(row)
                i += 1
            tbl = ['<table class="mdt"><thead><tr>']
            for c in header:
                tbl.append(f'<th>{h(c)}</th>')
            tbl.append('</tr></thead><tbody>')
            for r in rows:
                tbl.append('<tr>' + ''.join(f'<td>{h(c)}</td>' for c in r) + '</tr>')
            tbl.append('</tbody></table>')
            out.append(''.join(tbl))
            continue
        # 引用
        if line.startswith('>'):
            out.append(f'<blockquote>{h(line[1:].strip())}</blockquote>')
            i += 1
            continue
        # 列表
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append('<ul>' + ''.join(f'<li>{h(it)}</li>' for it in items) + '</ul>')
            continue
        # 空行
        if not line.strip():
            i += 1
            continue
        # 段落（合并连续非空行）
        para = line.strip()
        j = i + 1
        while j < len(lines) and lines[j].strip() and not lines[j].startswith('|') \
                and not lines[j].startswith('>') and not re.match(r"^\s*[-*]\s+", lines[j]):
            para += ' ' + lines[j].strip()
            j += 1
        out.append(f'<p>{h(para)}</p>')
        i = j
    return ''.join(out)


NAV_TOP = """<nav class="topnav"><div class="inner">
  <a class="brand" href="../index.html">law<span>datify</span></a>
  <div class="navlinks">
    <a href="../index.html">首页</a>
    <a href="../news/index.html">资讯索引</a>
    <a href="../analysis/index.html" class="active">法律分析</a>
    <a href="../kb/index.html">合规知识库</a>
    <a href="../prm.html">工作项目</a>
  </div>
</div></nav>"""

NAV_KB = """<nav class="topnav"><div class="inner">
  <a class="brand" href="../index.html">law<span>datify</span></a>
  <div class="navlinks">
    <a href="../index.html">首页</a>
    <a href="../news/index.html">资讯索引</a>
    <a href="../analysis/index.html">法律分析</a>
    <a href="../kb/index.html" class="active">合规知识库</a>
    <a href="../prm.html">工作项目</a>
  </div>
</div></nav>"""

FOOT = """<footer><div class="inner">
  <div>lawdatify.site · 法律合规主站</div>
  <div><a href="../index.html">首页</a> · <a href="../news/index.html">资讯索引</a> · <a href="../analysis/index.html">法律分析</a> · <a href="../kb/index.html">知识库</a> · <a href="../prm.html">PRM</a></div>
</div></footer>"""


# ---------- 打磨日志解析 ----------
POLISH_ENTRY_RE = re.compile(
    r"^### \[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:[\dxX]{2})\]\s*(?P<title>.+?)\s*$", re.M
)
POLISH_FIELD_RE = re.compile(r"^-\s*\*\*(?P<k>[^*]+)\*\*\s*[:：]\s*(?P<v>.+)$", re.M)
POLISH_SUB_RE = re.compile(r"^####\s+(?P<sub>.+?)\s*$", re.M)


def parse_polish():
    """返回 [(ts, title, {k: v, ...}, [sub_blocks, ...]), ...] 时间倒序。
    sub_blocks: [{'title': ..., 'fields': {k: v}}]，对应每条主记录下的 #### 子条目。
    """
    if not os.path.exists(POLISH_FILE):
        return []
    with open(POLISH_FILE, encoding="utf-8") as f:
        text = f.read()
    parts = re.split(r"(?=^### \[\d{4}-\d{2}-\d{2} \d{2}:[\dxX]{2}\])", text, flags=re.M)
    entries = []
    for p in parts:
        m = POLISH_ENTRY_RE.search(p)
        if not m:
            continue
        ts = m.group("ts").strip()
        title = m.group("title").strip()
        body = p[m.end():]
        # 主条目字段（仅取 #### 出现之前的字段，避免被子条目污染）
        main_body_limited = re.split(r"^#### ", body, flags=re.M)[0]
        main_fields = {}
        for fm in POLISH_FIELD_RE.finditer(main_body_limited):
            main_fields[fm.group("k").strip()] = fm.group("v").strip()
        # 切分子条目
        sub_entries = []
        sub_parts = re.split(r"(?=^#### )", body, flags=re.M)
        for sp in sub_parts[1:]:  # 跳过首段（主条目字段段）
            sm = POLISH_SUB_RE.match(sp)
            if not sm:
                continue
            sub_title = sm.group("sub").strip()
            sub_body = sp[sm.end():]
            # 截取到下一个 #### 或 ### 前
            sub_body_limited = re.split(r"^### ", sub_body, flags=re.M)[0]
            sub_fields = {}
            for fm in POLISH_FIELD_RE.finditer(sub_body_limited):
                sub_fields[fm.group("k").strip()] = fm.group("v").strip()
            sub_entries.append(
                {"title": sub_title, "fields": sub_fields, "raw_md": sub_body_limited.strip()}
            )
        entries.append((ts, title, main_fields, sub_entries))
    entries.sort(key=lambda e: e[0], reverse=True)
    return entries


def render_polish(entries):
    """渲染 analysis/polish.html。"""
    n = len(entries)
    latest = entries[0][0] if entries else "—"
    cards = []
    for entry in entries:
        ts, title, fields, subs = entry
        date, time = ts, ""
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:[\dxX]{2})$", ts)
        if m:
            date, time = m.group(1), m.group(2)
        order = [
            ("改动文件/函数", "file"),
            ("改动前 → 改动后", "diff"),
            ("改动依据", "why"),
            ("预期提升", "goal"),
            ("QA 验证", "qa"),
        ]
        body = []
        for k, ck in order:
            if k in fields and fields[k]:
                v_html = h(fields[k]).replace(chr(10), "<br/>")
                body.append(
                    f'<div class="pol-row"><div class="pol-k">{h(k)}</div>'
                    f'<div class="pol-v">{v_html}</div></div>'
                )
        # 子条目渲染：先尝试字段格式，否则原样渲染 Markdown 表格
        sub_html = ""
        if subs:
            sub_items = []
            for s in subs:
                if s["fields"]:
                    sbody = []
                    for k, ck in order:
                        if k in s["fields"] and s["fields"][k]:
                            v_html = h(s["fields"][k]).replace(chr(10), "<br/>")
                            sbody.append(
                                f'<div class="pol-row"><div class="pol-k">{h(k)}</div>'
                                f'<div class="pol-v">{v_html}</div></div>'
                            )
                    sub_items.append(
                        f'<div class="pol-sub"><div class="pol-sub-title">{h(s["title"])}</div>'
                        f'<div class="pol-body">{"".join(sbody)}</div></div>'
                    )
                elif s["raw_md"]:
                    # 把 Markdown 表格转为 HTML 表格 + 其余按行渲染
                    md_html = md_to_html(s["raw_md"])
                    sub_items.append(
                        f'<div class="pol-sub"><div class="pol-sub-title">{h(s["title"])}</div>'
                        f'<div class="pol-md">{md_html}</div></div>'
                    )
            if sub_items:
                sub_html = (
                    '<div class="pol-subs" style="margin-top:8px;padding-top:8px;'
                    'border-top:1px dashed var(--line)">'
                    + "".join(sub_items)
                    + "</div>"
                )
        # QA 标签
        qa_tag = ""
        qa_src = fields.get("QA 验证") or ""
        # 优先从主字段读，否则从最后一个子条目读
        if not qa_src and subs:
            qa_src = subs[-1]["fields"].get("QA 验证", "")
        if "回退" in qa_src:
            qa_tag = '<span class="qa back">回退</span>'
        elif "通过" in qa_src or "无需改动" in title:
            qa_tag = '<span class="qa pass">通过</span>'
        elif qa_src:
            qa_tag = '<span class="qa">—</span>'
        else:
            qa_tag = '<span class="qa">—</span>'
        card = f"""<div class="pol-card">
  <div class="pol-head">
    <span class="pol-date">{h(date)}</span>
    <span class="pol-time">{h(time)}</span>
    {qa_tag}
    <span class="pol-title">{h(title)}</span>
  </div>
  <div class="pol-body">{''.join(body)}</div>
  {sub_html}
</div>"""
        cards.append(card)
    body_html = "".join(cards) if cards else '<div class="empty">尚无打磨记录</div>'
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>报告排版打磨日志 · lawdatify</title>
<link rel="stylesheet" href="../assets/style.css">
<style>
.pol-summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0 6px}}
@media(max-width:720px){{.pol-summary{{grid-template-columns:repeat(1,1fr)}}}}
.pol-stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 12px;text-align:center;box-shadow:var(--shadow)}}
.pol-stat .n{{font-size:22px;font-weight:700;color:var(--brand);line-height:1.2}}
.pol-stat .l{{font-size:11.5px;color:var(--muted);margin-top:2px}}
.pol-card{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--brand);border-radius:8px;padding:14px 16px;margin:10px 0;box-shadow:var(--shadow)}}
.pol-card .pol-head{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px}}
.pol-card .pol-date{{font-weight:600;color:var(--brand)}}
.pol-card .pol-time{{color:var(--muted);font-variant-numeric:tabular-nums}}
.pol-card .pol-title{{font-weight:600;font-size:14px;flex:1;min-width:200px}}
.pol-card .pol-body{{margin-top:10px;font-size:13px}}
.pol-card .pol-row{{display:flex;gap:10px;padding:5px 0;border-top:1px dashed var(--line)}}
.pol-card .pol-row:first-child{{border-top:0}}
.pol-card .pol-k{{flex:0 0 130px;color:var(--muted);font-size:12px}}
.pol-card .pol-v{{flex:1;color:#222;line-height:1.6;word-break:break-word}}
.pol-card .qa{{padding:2px 8px;border-radius:10px;font-size:11.5px;font-weight:600;border:1px solid var(--line);color:var(--muted);background:#f5f7f9}}
.pol-card .qa.pass{{background:#eaf5ee;color:#2e7d4f;border-color:#cfe5d5}}
.pol-card .qa.back{{background:#fdecea;color:#b0352a;border-color:#f4c1bb}}
.pol-sub{{margin:8px 0 6px;background:#fafbfc;border:1px solid var(--line);border-radius:6px;padding:8px 12px}}
.pol-sub-title{{font-size:13px;font-weight:600;color:var(--brand-2,#0f6e8c);margin-bottom:4px}}
.pol-md{{font-size:12.5px;line-height:1.6}}
.pol-md p{{margin:6px 0}}
.pol-md blockquote{{border-left:3px solid var(--brand);background:#f5f8fc;padding:4px 10px;margin:6px 0;color:#333;font-size:12.5px}}
.pol-md ul{{padding-left:20px;margin:4px 0}}
.pol-md table.mdt{{width:100%;border-collapse:collapse;margin:8px 0;font-size:12px;background:#fff}}
.pol-md table.mdt th{{background:var(--brand);color:#fff;padding:6px 8px;text-align:left;font-weight:600}}
.pol-md table.mdt td{{padding:5px 8px;border:1px solid var(--line)}}
.pol-md table.mdt tr:nth-child(even){{background:#f4f7fb}}
.empty{{text-align:center;color:var(--muted);padding:34px 0;font-size:13px}}
.pol-hint{{font-size:12px;color:var(--muted);margin:14px 0 0}}
@media print{{body{{background:#fff}}.pol-card{{page-break-inside:avoid}}}}
</style>
</head>
<body>
{NAV_TOP}
<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">法律分析</a> / 打磨日志</div>
  <h1>报告排版打磨日志</h1>
  <p>持续打磨「合规资讯简报」自动化（日报 / 周报 / 月报）的排版与格式水准。每半小时巡检、每改必过 QA 门禁；本页由自动化同步、保持可追溯。</p>
</div></div>

<div class="wrap">
  <div class="pol-summary">
    <div class="pol-stat"><div class="n">{n}</div><div class="l">打磨记录</div></div>
    <div class="pol-stat"><div class="n">{h(latest)}</div><div class="l">最新一次</div></div>
    <div class="pol-stat"><div class="n">每 30 分钟</div><div class="l">巡检频率</div></div>
  </div>

  <div style="margin-top:18px">{body_html}</div>

  <p class="pol-hint">本页由「站点模块生成脚本」同步 · 最后更新 {h(now)} · 数据源：references/polish_changelog.md</p>
</div>
{FOOT}
</body>
</html>
"""
    with open(POLISH_OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    return n, latest


# ---------- 对标库解析 ----------
BENCH_CAT_RE = re.compile(r"^###\s+(?P<cat>[^/]+?)\s*/\s*(?P<sub>.+?)$", re.M)
BENCH_SAMPLE_RE = re.compile(r"^####\s+(?P<no>.+?)$", re.M)
BENCH_FIELD_RE = re.compile(r"^-\s*\*\*(?P<k>[^*]+)\*\*\s*[:：]\s*(?P<v>.+)$", re.M)


def parse_bench():
    """返回 [{cat, sub, samples:[{机构,标题,发布日期,链接,链接文本,可借鉴点清单}, ...]}, ...]"""
    if not os.path.exists(BENCH_FILE):
        return []
    with open(BENCH_FILE, encoding="utf-8") as f:
        text = f.read()
    # 按 ### 分类切分（保留标题）；跳过前部的字段规范与说明段
    parts = re.split(r"(?=^### )", text, flags=re.M)
    cats = []
    for p in parts:
        m = BENCH_CAT_RE.search(p)
        if not m:
            continue
        cat = m.group("cat").strip()
        sub = m.group("sub").strip()
        # 该分类下的样本
        samples = []
        sparts = re.split(r"(?=^#### )", p, flags=re.M)
        for sp in sparts:
            sm = BENCH_SAMPLE_RE.search(sp)
            if not sm:
                continue
            no = sm.group("no").strip()
            body = sp[sm.end():]
            fields = {}
            for fm in BENCH_FIELD_RE.finditer(body):
                k = fm.group("k").strip()
                v = fm.group("v").strip()
                fields[k] = v
            samples.append(
                {
                    "no": no,
                    "机构": fields.get("机构", ""),
                    "标题": fields.get("标题", ""),
                    "发布日期": fields.get("发布日期", ""),
                    "链接": fields.get("链接", ""),
                    "可借鉴点清单": fields.get("可借鉴点清单", ""),
                }
            )
        if samples:
            cats.append({"cat": cat, "sub": sub, "samples": samples})
    return cats


def render_bench(cats):
    """渲染 kb/benchmarks.html。"""
    n_cat = len(cats)
    n_smp = sum(len(c["samples"]) for c in cats)
    cats_html = []
    for c in cats:
        cards = []
        for s in c["samples"]:
            link = s["链接"]
            link_html = (
                f'<a href="{h(link)}" target="_blank" rel="noopener" class="bm-link">{h(link[:72] + ("…" if len(link) > 72 else ""))}</a>'
                if link
                else '<span class="muted">—</span>'
            )
            # 借鉴点用项目列表（每行以 ①～⑧ 开头则作为列表项）
            pts = s["可借鉴点清单"]
            pts_html = ""
            if pts:
                lines = [ln.strip() for ln in pts.splitlines() if ln.strip()]
                items = []
                for ln in lines:
                    if re.match(r"^[①②③④⑤⑥⑦⑧]", ln):
                        # 去掉首字符和后续空格作为内容
                        items.append(f"<li>{h(ln)}</li>")
                    else:
                        # 续行（拼到上一个 li）
                        if items:
                            items[-1] = items[-1][:-5] + h(ln) + "</li>"
                        else:
                            items.append(f"<li>{h(ln)}</li>")
                pts_html = "<ol class='bm-pts'>" + "".join(items) + "</ol>"
            cards.append(
                f"""<div class="bm-card">
  <div class="bm-org">{h(s['机构'])}</div>
  <div class="bm-title">{h(s['标题'])}</div>
  <div class="bm-meta"><span class="bm-date">{h(s['发布日期'])}</span></div>
  <div class="bm-linkbox">深链：{link_html}</div>
  {pts_html}
</div>"""
            )
        cats_html.append(
            f"""<section class="bm-cat">
  <h2>{h(c['cat'])} <span class="bm-sub">{h(c['sub'])}</span> <span class="bm-cnt">{len(c['samples'])} 份样本</span></h2>
  <div class="bm-grid">{''.join(cards)}</div>
</section>"""
        )
    body_html = "".join(cats_html) if cats_html else '<div class="empty">尚无对标样本</div>'
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>行业报告排版对标库 · lawdatify</title>
<link rel="stylesheet" href="../assets/style.css">
<style>
.bm-summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0 6px}}
@media(max-width:720px){{.bm-summary{{grid-template-columns:repeat(1,1fr)}}}}
.bm-stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 12px;text-align:center;box-shadow:var(--shadow)}}
.bm-stat .n{{font-size:22px;font-weight:700;color:var(--brand);line-height:1.2}}
.bm-stat .l{{font-size:11.5px;color:var(--muted);margin-top:2px}}
.bm-cat{{margin:22px 0}}
.bm-cat h2{{font-size:18px;color:var(--brand);border-left:4px solid var(--brand);padding-left:10px;margin-bottom:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.bm-cat .bm-sub{{font-size:13px;color:var(--muted);font-weight:400}}
.bm-cat .bm-cnt{{font-size:12px;background:#eef3f9;color:var(--brand);border:1px solid var(--line);border-radius:10px;padding:2px 10px;font-weight:500}}
.bm-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
.bm-card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px;box-shadow:var(--shadow)}}
.bm-org{{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.2px;text-transform:uppercase}}
.bm-title{{font-size:15px;font-weight:600;color:#222;margin:4px 0 6px;line-height:1.4}}
.bm-meta{{font-size:12px;color:var(--muted);margin-bottom:8px}}
.bm-linkbox{{font-size:12px;margin-bottom:8px;word-break:break-all}}
.bm-link{{color:var(--brand-2,#0f6e8c);text-decoration:none;border-bottom:1px dotted var(--brand-2,#0f6e8c)}}
.bm-link:hover{{background:var(--brand-2,#0f6e8c);color:#fff}}
.bm-pts{{font-size:12.5px;color:#333;line-height:1.7;padding-left:18px;margin:6px 0 0}}
.bm-pts li{{margin-bottom:3px}}
.empty{{text-align:center;color:var(--muted);padding:34px 0;font-size:13px}}
.bm-hint{{font-size:12px;color:var(--muted);margin:18px 0 0}}
@media print{{body{{background:#fff}}.bm-card{{page-break-inside:avoid}}}}
</style>
</head>
<body>
{NAV_KB}
<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 报告对标库</div>
  <h1>行业报告排版对标库</h1>
  <p>持续沉淀 ESG / 法律 / 券商研报等专业报告的「结构特征+可借鉴点」，作为打磨合规资讯简报排版格式的对标基准。每 2 天由自动化收集更新；所有链接均为发布机构官网的具体深链（非首页根域名）。</p>
</div></div>

<div class="wrap">
  <div class="bm-summary">
    <div class="bm-stat"><div class="n">{n_cat}</div><div class="l">对标分类</div></div>
    <div class="bm-stat"><div class="n">{n_smp}</div><div class="l">累计样本</div></div>
    <div class="bm-stat"><div class="n">每 2 天</div><div class="l">收集频率</div></div>
  </div>

  <div style="margin-top:18px">{body_html}</div>

  <p class="bm-hint">本页由「站点模块生成脚本」同步 · 最后更新 {h(now)} · 数据源：references/benchmark_reports.md</p>
</div>
{FOOT}
</body>
</html>
"""
    with open(BENCH_OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    return n_cat, n_smp


# ---------- 搜索索引 ----------
def update_manifest():
    entries = [
        {
            "title": "合规简报归档",
            "url": "news/briefs.html",
            "desc": "自动化合规资讯（日报/周报/月报/补编）全期次归档，含网页版与PDF，按类型与关键词检索。",
            "cat": "资讯索引",
            "tags": ["日报", "周报", "月报", "简报", "归档"],
        },
        {
            "title": "报告排版打磨日志",
            "url": "analysis/polish.html",
            "desc": "合规资讯简报排版打磨全过程时间线，每条含改动文件、前后对比、依据、QA 验证结果。",
            "cat": "法律分析",
            "tags": ["打磨", "排版", "格式", "QA", "巡检"],
        },
        {
            "title": "行业报告对标库",
            "url": "kb/benchmarks.html",
            "desc": "ESG/法律/券商研报专业报告样本对标库，含可借鉴点与发布机构官网深链。",
            "cat": "合规知识库",
            "tags": ["对标", "ESG", "研报", "律所", "排版", "可借鉴"],
        },
    ]
    data = []
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    have = {d.get("title") for d in data}
    added = 0
    for e in entries:
        if e["title"] not in have:
            data.append(e)
            added += 1
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return added


def main():
    print("=== 打磨日志 ===")
    if not os.path.exists(POLISH_FILE):
        print("源文件缺失:", POLISH_FILE)
    else:
        entries = parse_polish()
        n, latest = render_polish(entries)
        print(f"  解析 {n} 条记录，最新 {latest}")
    print("=== 对标库 ===")
    if not os.path.exists(BENCH_FILE):
        print("源文件缺失:", BENCH_FILE)
    else:
        cats = parse_bench()
        n_cat, n_smp = render_bench(cats)
        print(f"  解析 {n_cat} 个分类，共 {n_smp} 份样本")
    a = update_manifest()
    print(f"搜索索引：新增 {a} 项")


if __name__ == "__main__":
    main()