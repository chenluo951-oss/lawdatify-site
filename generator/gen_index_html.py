#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《合规资讯简报》报告索引页生成器

扫描输出目录下**全部历史报告**（HTML / PDF / DOCX），按「期次」聚合成一张可检索的索引页。
网页版（HTML）优先；尚未生成网页版的历史期次自动降级链接到 PDF，保证历史不缺失。

索引由「合规报告索引自动刷新（每 30 分钟）」自动化任务定期重跑本脚本刷新；
每次新增报告后 30 分钟内自动纳入，无需手动重跑、无需每日重新发送。
"""
import os
import re
import html
import datetime

OUT_DIR = os.environ.get("CBR_OUT_DIR") or "/Users/luochen/Desktop/合规资讯简报"
INDEX_NAME = "合规资讯报告索引.html"   # 本地查阅用
SITE_ENTRY = "index.html"               # 站点入口（部署为网页时自动成为首页）
SKIP_NAMES = {INDEX_NAME, SITE_ENTRY}   # 扫描时排除索引自身

# 文件名解析：类型 _ 期次 [_深度分析版] . 扩展名
# 例：合规资讯简报_2026-09-01_深度分析版.html / 合规动态补编_2026-08-30.pdf
PAT = re.compile(
    r"^(合规资讯(?:简报|日报|周报|月报)|合规动态补编)_(\d{4}-\d{2}(?:-\d{2})?)"
    r"(?:_(深度分析版))?\.(html|pdf|docx)$"
)

KIND_ORDER = {"月报": 0, "周报": 1, "日报": 2, "简报": 3, "补编": 4}
FMT_LABEL = {"html": "网页版", "pdf": "PDF", "docx": "Word"}
FMT_ORDER = {"html": 0, "pdf": 1, "docx": 2}


def esc(s):
    return html.escape("" if s is None else str(s), quote=False)


def parse_name(fname):
    """返回 (类型, 期次, 版本, 格式) 或 None"""
    m = PAT.match(fname)
    if not m:
        return None
    prefix, period, deep, ext = m.groups()
    kind = prefix.replace("合规资讯", "").replace("合规动态", "")
    return kind, period, ("深度分析版" if deep else "简版"), ext


def extract_sections(path, limit=14):
    """从 HTML 报告中提取章节（h2）与领域级（h3）标题，作为检索关键词"""
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read(500000)
    except Exception:
        return []
    secs = re.findall(r'<h2 class="sec"[^>]*>(.*?)</h2>', s, re.S)
    subs = re.findall(r'<h3 class="sub2"[^>]*>(.*?)</h3>', s, re.S)

    def clean(x):
        return re.sub(r"<[^>]+>", "", x).strip()

    out = []
    for x in secs + subs:          # 章节在前、领域在后
        t = clean(x)
        if t and t not in out:
            out.append(t)
    return out[:limit]


def scan():
    """扫描目录 → {期次key: {kind, period, files:{版本:{格式:文件名}}, secs:[]}}"""
    if not os.path.isdir(OUT_DIR):
        return {}
    groups = {}
    for fn in sorted(os.listdir(OUT_DIR)):
        if fn in SKIP_NAMES:
            continue
        p = parse_name(fn)
        if not p:
            continue
        kind, period, ver, ext = p
        g = groups.setdefault(period, {"kind": kind, "period": period,
                                       "files": {}, "secs": [], "mtime": 0})
        # 同名期次若类型不同（如同日有简报/日报/补编），用更具体的
        g.setdefault("kinds", set()).add(kind)
        g["files"].setdefault(ver, {})[ext] = fn
        try:
            mt = os.path.getmtime(os.path.join(OUT_DIR, fn))
            g["mtime"] = max(g["mtime"], mt)
        except OSError:
            pass
        if ext == "html" and not g["secs"]:
            g["secs"] = extract_sections(os.path.join(OUT_DIR, fn))
    return groups


# ============================================================ 页面
CSS = """
:root{
  --navy:#1F3B63; --navy2:#2E5E8C; --blue:#3A6B8F;
  --ink:#2B2B2B; --gray:#6B7280; --lgray:#9AA3AF;
  --bg-key:#F2F6FA; --zebra:#EDF1F6; --grid:#D8DEE6;
}
*{box-sizing:border-box;}
body{margin:0;background:#F7F8FA;color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",
              "Microsoft YaHei",sans-serif;font-size:14px;line-height:1.75;}
.page{max-width:1000px;margin:0 auto;background:#fff;padding:44px 52px 60px;}
@media (max-width:720px){.page{padding:22px 16px 40px;}}

.hd{text-align:center;padding:6px 0 22px;border-bottom:2px solid var(--navy);}
.hd .bar{background:var(--navy);color:#fff;padding:11px 18px;border-radius:4px;
  display:flex;justify-content:space-between;font-size:13px;letter-spacing:.5px;}
.hd h1{font-size:27px;color:var(--navy);margin:22px 0 6px;font-weight:700;letter-spacing:2px;
  font-family:"Songti SC","SimSun",serif;}
.hd .en{font-size:11px;letter-spacing:3px;color:var(--lgray);text-transform:uppercase;}
.hd .sub{font-size:13px;color:var(--gray);margin-top:10px;}

.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 6px;}
@media (max-width:720px){.stats{grid-template-columns:repeat(2,1fr);}}
.stat{background:var(--bg-key);border-radius:6px;padding:14px 12px;text-align:center;border-left:3px solid var(--navy);}
.stat .n{font-size:22px;font-weight:700;color:var(--navy);line-height:1.2;}
.stat .l{font-size:11.5px;color:var(--gray);margin-top:2px;}

.tools{margin:20px 0 8px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;}
#q{flex:1;min-width:220px;padding:9px 13px;font-size:14px;border:1px solid var(--grid);
  border-radius:5px;outline:none;font-family:inherit;}
#q:focus{border-color:var(--navy2);box-shadow:0 0 0 2px rgba(46,94,140,.12);}
.chip{padding:6px 13px;font-size:12.5px;border:1px solid var(--grid);background:#fff;
  border-radius:14px;cursor:pointer;color:var(--gray);user-select:none;font-family:inherit;}
.chip:hover{border-color:var(--navy2);color:var(--navy2);}
.chip.on{background:var(--navy);border-color:var(--navy);color:#fff;}
.hint{font-size:12px;color:var(--lgray);margin:0 0 6px;}

table.idx{width:100%;border-collapse:collapse;margin-top:6px;font-size:13.5px;}
table.idx thead th{background:var(--navy);color:#fff;text-align:left;padding:10px 11px;
  font-weight:600;font-size:12.5px;white-space:nowrap;}
table.idx td{padding:11px;border-bottom:1px solid var(--grid);vertical-align:top;}
table.idx tbody tr:nth-child(even){background:var(--zebra);}
table.idx tbody tr:hover{background:#E8EFF7;}
.per{font-weight:600;color:var(--navy);font-size:15px;white-space:nowrap;}
.kind{display:inline-block;background:var(--bg-key);color:var(--navy);border:1px solid var(--grid);
  border-radius:3px;padding:1px 8px;font-size:11.5px;margin-left:6px;vertical-align:2px;}
.btns{display:flex;flex-wrap:wrap;gap:6px;}
.btns a{display:inline-block;padding:4px 11px;border-radius:4px;font-size:12px;text-decoration:none;
  border:1px solid var(--navy2);color:var(--navy2);background:#fff;}
.btns a:hover{background:var(--navy2);color:#fff;}
.btns a.web{background:var(--navy);border-color:var(--navy);color:#fff;}
.btns a.web:hover{background:#16304F;}
.btns a.na{opacity:.45;border-style:dashed;color:var(--lgray);border-color:var(--grid);
  pointer-events:none;background:#FAFAFA;}
.secs{font-size:11.5px;color:var(--lgray);line-height:1.7;}
.secs span{display:inline-block;background:#F5F7F9;border:1px solid #E6EAEF;border-radius:3px;
  padding:1px 6px;margin:2px 3px 2px 0;}
.empty{text-align:center;color:var(--lgray);padding:34px 0;font-size:13px;}
.foot{margin-top:26px;padding-top:13px;border-top:1px solid var(--grid);
  font-size:11.5px;color:var(--lgray);text-align:center;line-height:1.9;}

@media print{
  body{background:#fff;} .page{max-width:none;padding:0;}
  .tools,.hint{display:none;}
  table.idx tbody tr{page-break-inside:avoid;}
}
"""


def build():
    groups = scan()
    items = sorted(groups.values(), key=lambda g: g["period"], reverse=True)

    n_web = sum(1 for g in items if any("html" in v for v in g["files"].values()))
    n_pdf = sum(1 for g in items if any("pdf" in v for v in g["files"].values()))
    latest = items[0]["period"] if items else "—"

    # 每行：期次 / 版本 / 格式链接 / 章节
    rows = []
    for g in items:
        kinds = sorted(g.get("kinds", {g["kind"]}), key=lambda k: KIND_ORDER.get(k, 9))
        kind_txt = " / ".join(kinds)
        for ver in ("简版", "深度分析版"):
            if ver not in g["files"]:
                continue
            fmts = g["files"][ver]
            btns = []
            for ext in ("html", "pdf", "docx"):
                label = FMT_LABEL[ext]
                if ext in fmts:
                    fn = fmts[ext]
                    cls = "web" if ext == "html" else ""
                    btns.append(f'<a class="{cls}" href="{esc(fn)}" target="_blank" rel="noopener">{label}</a>')
                else:
                    btns.append(f'<a class="na">{label}</a>')
            secs = ""
            if ver == "简版" and g["secs"]:
                sp = "".join(f"<span>{esc(s)}</span>" for s in g["secs"])
                secs = f'<div class="secs">{sp}</div>'
            search_blob = " ".join([g["period"], kind_txt, ver] + g["secs"]).lower()
            rows.append(
                f'<tr data-k="{esc(kind_txt)}" data-v="{esc(ver)}" data-s="{esc(search_blob)}">'
                f'<td><span class="per">{esc(g["period"])}</span>'
                f'<span class="kind">{esc(kind_txt)}</span></td>'
                f'<td>{esc(ver)}</td>'
                f'<td><div class="btns">{"".join(btns)}</div></td>'
                f'<td>{secs}</td></tr>')

    body_rows = "".join(rows) if rows else \
        '<tr><td colspan="4"><div class="empty">未找到报告文件</div></td></tr>'
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    kinds_all = sorted({k for g in items for k in g.get("kinds", {g["kind"]})},
                       key=lambda k: KIND_ORDER.get(k, 9))

    chips = ['<span class="chip on" data-f="all">全部</span>']
    chips += [f'<span class="chip" data-f="{esc(k)}">{esc(k)}</span>' for k in kinds_all]
    chips.append('<span class="chip" data-f="__web">仅网页版</span>')

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>合规资讯报告索引 · 朴朴超市法务合规部</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <div class="hd">
    <div class="bar"><span>朴朴超市 · 法务合规部</span><span>报告索引</span></div>
    <h1>合规资讯报告索引</h1>
    <div class="en">Compliance Briefing Archive</div>
    <div class="sub">汇总全部历史与最新合规资讯报告，支持按日期、类型、章节关键词检索</div>
  </div>

  <div class="stats">
    <div class="stat"><div class="n">{len(items)}</div><div class="l">报告期次</div></div>
    <div class="stat"><div class="n">{n_web}</div><div class="l">有网页版</div></div>
    <div class="stat"><div class="n">{n_pdf}</div><div class="l">PDF 归档</div></div>
    <div class="stat"><div class="n">{esc(latest)}</div><div class="l">最新期次</div></div>
  </div>

  <div class="tools">
    <input id="q" type="search" placeholder="搜索期次、类型、章节关键词，如 2026-09 / 周报 / 数据合规…"/>
  </div>
  <div class="tools" style="margin-top:0">{"".join(chips)}</div>
  <p class="hint">共 {len(rows)} 条记录 · 网页版可直接在浏览器打开；未生成网页版的历史期次链接到 PDF 归档</p>

  <table class="idx">
    <thead><tr>
      <th style="width:150px">期次 / 类型</th>
      <th style="width:90px">版本</th>
      <th style="width:190px">打开格式</th>
      <th>章节关键词</th>
    </tr></thead>
    <tbody id="tb">{body_rows}</tbody>
  </table>

  <div class="foot">
    本索引每 30 分钟自动刷新 · 最后更新 {esc(now)}<br/>
    新增报告后自动纳入，分享本页一次即可，无需每日重新发送
  </div>
</div>
<script>
var q=document.getElementById('q'), tb=document.getElementById('tb'),
    rows=[].slice.call(tb.querySelectorAll('tr')), filt='all';
function apply(){{
  var kw=(q.value||'').trim().toLowerCase(), n=0;
  rows.forEach(function(r){{
    var okK = filt==='all' || (filt==='__web' ? !!r.querySelector('a.web') : r.dataset.k.indexOf(filt)>=0);
    var okS = !kw || (r.dataset.s||'').indexOf(kw)>=0 || r.textContent.toLowerCase().indexOf(kw)>=0;
    var show = okK && okS;
    r.style.display = show ? '' : 'none';
    if(show) n++;
  }});
  document.getElementById('cnt').textContent = n;
}}
q.addEventListener('input', apply);
[].slice.call(document.querySelectorAll('.chip')).forEach(function(c){{
  c.addEventListener('click', function(){{
    [].slice.call(document.querySelectorAll('.chip')).forEach(function(x){{x.classList.remove('on');}});
    c.classList.add('on'); filt=c.dataset.f; apply();
  }});
}});
</script>
</body>
</html>
"""
    # hint 中的计数占位
    doc = doc.replace(f"共 {len(rows)} 条记录", '共 <span id="cnt">%d</span> 条记录' % len(rows))

    os.makedirs(OUT_DIR, exist_ok=True)
    # ① 本地查阅版 ② 站点入口 index.html（部署为网页时自动成为首页，内容完全一致）
    for name in (INDEX_NAME, SITE_ENTRY):
        p = os.path.join(OUT_DIR, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(doc)
        print(f"INDEX saved: {p}")
    print(f"  期次 {len(items)} · 记录 {len(rows)} · 有网页版 {n_web} · 最新 {latest}")
    return os.path.join(OUT_DIR, INDEX_NAME)


if __name__ == "__main__":
    build()
