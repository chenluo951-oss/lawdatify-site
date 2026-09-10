#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lawdatify 站点 · 合规简报归档融合脚本

扫描 Desktop/合规资讯简报 下全部历史报告（HTML/PDF/DOCX），按「期次」聚合，
把报告同步进 lawdatify-site/news/reports/，并生成站点内「简报归档」页
news/briefs.html（套用站点导航与配色），最后把该页接入 assets/manifest.json 搜索索引。

可重复运行：报告仅增量复制（源更新才覆盖），briefs.html 与 manifest 每次覆盖刷新。

用法：python3 gen_briefs.py
"""
import os
import re
import html
import json
import shutil
import datetime
import urllib.parse

# 路径可配置：本地默认读桌面简报目录；云端（GitHub Actions）通过 BRIEF_SRC 指向仓库内
# news/reports/，用已入仓的报告重建归档页。DST_ROOT 恒为脚本所在目录，本地/云端通用。
SRC = os.environ.get("BRIEF_SRC") or "/Users/luochen/Desktop/合规资讯简报"
DST_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(DST_ROOT, "news", "reports")
BRIEFS = os.path.join(DST_ROOT, "news", "briefs.html")
MANIFEST = os.path.join(DST_ROOT, "assets", "manifest.json")

PAT = re.compile(
    r"^(合规资讯(?:简报|日报|周报|月报)|合规动态补编)_(\d{4}-\d{2}(?:-\d{2})?)"
    r"(?:_(深度分析版))?\.(html|pdf|docx)$"
)
KIND_ORDER = {"月报": 0, "周报": 1, "日报": 2, "简报": 3, "补编": 4}
FMT_LABEL = {"html": "网页版", "pdf": "PDF", "docx": "Word"}
# 站点只发布网页版：PDF/DOCX 一律保留在本机，不上传（2026-09-08 用户决定）。
# 原因：PDF 单份 200KB~1.1MB，是打爆 Netlify 带宽额度、拖慢境外主机访问的主因；
# 网页版单份仅 20~130KB，且可直接在线阅读，对外分享体验更好。
ONLINE_FMTS = ("html",)

# 不发布名单（2026-09-09 建立）：文件名含下列片段的期次不进站点。
# 用途：某期报告若被查出含编造/失效来源链接，在此屏蔽即可，文件仍留本机备查。
# 当前屏蔽：2026-09-06 日报（来源链接为 content_1234567890 一类编造值，实测 404）。
BLOCKED = ("简报_2026-09-06",)


def esc(s):
    return html.escape("" if s is None else str(s), quote=False)


def url(fn):
    """站内相对链接（中文文件名做 URL 编码，保证 Netlify 可访问）"""
    return "reports/" + urllib.parse.quote(fn)


def parse_name(fname):
    m = PAT.match(fname)
    if not m:
        return None
    prefix, period, deep, ext = m.groups()
    kind = prefix.replace("合规资讯", "").replace("合规动态", "")
    return kind, period, ("深度分析版" if deep else "简版"), ext


def extract_sections(path, limit=14):
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
    for x in secs + subs:
        t = clean(x)
        if t and t not in out:
            out.append(t)
    return out[:limit]


def scan(base=None):
    groups = {}
    base = base or SRC
    if not os.path.isdir(base):
        return groups
    for fn in sorted(os.listdir(base)):
        # 不发布名单：这些期次经实测含编造来源链接（如 content_1234567890），
        # 文件保留在本机与 _quarantine/，但不进站点。新增屏蔽项在此追加文件名片段。
        if any(b in fn for b in BLOCKED):
            continue
        p = parse_name(fn)
        if not p:
            continue
        kind, period, ver, ext = p
        # 归档键 = (期次, 类型)：同日的日报/周报/月报必须各自独立成条，
        # 否则 files[ver][ext] 会被后扫描到的同名版本覆盖，导致当期次报告「静默丢失」。
        g = groups.setdefault(
            (period, kind),
            {"kind": kind, "period": period, "kinds": {kind}, "files": {}, "secs": [], "mtime": 0},
        )
        g["files"].setdefault(ver, {})[ext] = fn
        try:
            mt = os.path.getmtime(os.path.join(SRC, fn))
            g["mtime"] = max(g["mtime"], mt)
        except OSError:
            pass
        if ext == "html" and not g["secs"]:
            g["secs"] = extract_sections(os.path.join(SRC, fn))
    return groups


def need_copy(src, dst):
    if not os.path.exists(dst):
        return True
    try:
        return os.path.getmtime(src) > os.path.getmtime(dst)
    except OSError:
        return True


def sync_reports(groups, base=None):
    base = base or SRC
    os.makedirs(REPORTS, exist_ok=True)
    copied = skipped = 0
    size = 0
    for g in groups.values():
        for ver, fmts in g["files"].items():
            # 只同步 ONLINE_FMTS 内的格式；归档页也只为这些格式渲染链接，
            # 因此不会出现「页面有链接、reports/ 里却没文件」的 404。
            for fmt in ONLINE_FMTS:
                if fmt not in fmts:
                    continue
                chosen = fmts[fmt]
                src = os.path.join(base, chosen)
                dst = os.path.join(REPORTS, chosen)
                if need_copy(src, dst):
                    shutil.copy2(src, dst)
                    copied += 1
                size += os.path.getsize(src)
            else:
                skipped += 1
    return copied, skipped, size


NAV = """<nav class="topnav"><div class="inner">
  <a class="brand" href="../index.html">law<span>datify</span></a>
  <div class="navlinks">
    <a href="../index.html">首页</a>
    <a href="index.html" class="active">资讯索引</a>
    <a href="../analysis/index.html">法律分析</a>
    <a href="../kb/index.html">合规知识库</a>
    <a href="../prm.html">工作项目</a>
  </div>
</div></nav>"""

FOOT = """<footer><div class="inner">
  <div>lawdatify.site · 即时零售合规主站</div>
  <div><a href="../index.html">首页</a> · <a href="index.html">资讯索引</a> · <a href="../analysis/index.html">法律分析</a> · <a href="../kb/index.html">知识库</a> · <a href="../prm.html">PRM</a></div>
</div></footer>"""


def build_briefs(groups):
    # 期次倒序；同期次内按类型优先级正序（月报 → 周报 → 日报 → 简报 → 补编）
    items = sorted(
        groups.values(),
        key=lambda g: (g["period"], -KIND_ORDER.get(g["kind"], 9)),
        reverse=True,
    )
    n_web = sum(1 for g in items if any("html" in v for v in g["files"].values()))
    n_deep = sum(
        1 for g in items
        if any(ver == "深度分析版" and "html" in fmts for ver, fmts in g["files"].items())
    )
    latest = items[0]["period"] if items else "—"

    rows = []
    for g in items:
        kinds = sorted(g.get("kinds", {g["kind"]}), key=lambda k: KIND_ORDER.get(k, 9))
        kind_txt = " / ".join(kinds)
        for ver in ("简版", "深度分析版"):
            if ver not in g["files"]:
                continue
            fmts = g["files"][ver]
            # 该版本只有 PDF/DOCX（未上网站）时整行跳过，避免出现「点不开的空记录」
            if not any(ext in fmts for ext in ONLINE_FMTS):
                continue
            btns = []
            for ext in ONLINE_FMTS:
                if ext in fmts:
                    fn = fmts[ext]
                    cls = "web" if ext == "html" else ""
                    btns.append(
                        f'<a class="{cls}" href="{esc(url(fn))}" target="_blank" rel="noopener">{FMT_LABEL[ext]}</a>'
                    )
                else:
                    btns.append(f'<a class="na">{FMT_LABEL[ext]}</a>')
            secs = ""
            if ver == "简版" and g["secs"]:
                sp = "".join(f"<span>{esc(s)}</span>" for s in g["secs"])
                secs = f'<div class="secs">{sp}</div>'
            blob = " ".join([g["period"], kind_txt, ver] + g["secs"]).lower()
            rows.append(
                f'<tr data-k="{esc(kind_txt)}" data-v="{esc(ver)}" data-s="{esc(blob)}">'
                f'<td><span class="per">{esc(g["period"])}</span>'
                f'<span class="kind">{esc(kind_txt)}</span></td>'
                f'<td>{esc(ver)}</td>'
                f'<td><div class="btns">{"".join(btns)}</div></td>'
                f'<td>{secs}</td></tr>'
            )

    body_rows = "".join(rows) if rows else \
        '<tr><td colspan="4"><div class="empty">未找到报告文件</div></td></tr>'
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    kinds_all = sorted(
        {k for g in items for k in g.get("kinds", {g["kind"]})},
        key=lambda k: KIND_ORDER.get(k, 9),
    )
    chips = ['<span class="chip on" data-f="all">全部</span>']
    chips += [f'<span class="chip" data-f="{esc(k)}">{esc(k)}</span>' for k in kinds_all]
    chips.append('<span class="chip" data-f="__web">仅网页版</span>')

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>合规简报归档 · lawdatify</title>
<link rel="stylesheet" href="../assets/style.css">
<style>
.bf-stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 6px}}
@media(max-width:720px){{.bf-stats{{grid-template-columns:repeat(2,1fr)}}}}
.bf-stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 12px;text-align:center;box-shadow:var(--shadow)}}
.bf-stat .n{{font-size:22px;font-weight:700;color:var(--brand);line-height:1.2}}
.bf-stat .l{{font-size:11.5px;color:var(--muted);margin-top:2px}}
.bf-tools{{margin:18px 0 8px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}}
#bq{{flex:1;min-width:220px;padding:9px 13px;font-size:14px;border:1px solid var(--line);border-radius:5px;outline:none;font-family:inherit}}
#bq:focus{{border-color:var(--brand)}}
.bf-chip{{padding:6px 13px;font-size:12.5px;border:1px solid var(--line);background:#fff;border-radius:14px;cursor:pointer;color:var(--muted);user-select:none}}
.bf-chip:hover{{border-color:var(--brand);color:var(--brand)}}
.bf-chip.on{{background:var(--brand);border-color:var(--brand);color:#fff}}
.bf-hint{{font-size:12px;color:var(--muted);margin:0 0 6px}}
table.idx{{width:100%;border-collapse:collapse;margin-top:6px;font-size:13.5px}}
table.idx thead th{{background:var(--brand);color:#fff;text-align:left;padding:10px 11px;font-weight:600;font-size:12.5px;white-space:nowrap}}
table.idx td{{padding:11px;border-bottom:1px solid var(--line);vertical-align:top}}
table.idx tbody tr:nth-child(even){{background:#f4f7fb}}
table.idx tbody tr:hover{{background:#e8f0fa}}
.per{{font-weight:600;color:var(--brand);font-size:15px;white-space:nowrap}}
.kind{{display:inline-block;background:#eef3f9;color:var(--brand);border:1px solid var(--line);border-radius:3px;padding:1px 8px;font-size:11.5px;margin-left:6px;vertical-align:2px}}
.btns{{display:flex;flex-wrap:wrap;gap:6px}}
.btns a{{display:inline-block;padding:4px 11px;border-radius:4px;font-size:12px;text-decoration:none;border:1px solid var(--brand-2,#0f6e8c);color:var(--brand-2,#0f6e8c);background:#fff}}
.btns a:hover{{background:var(--brand-2,#0f6e8c);color:#fff}}
.btns a.web{{background:var(--brand);border-color:var(--brand);color:#fff}}
.btns a.web:hover{{background:#143a5e}}
.btns a.na{{opacity:.45;border-style:dashed;color:var(--muted);border-color:var(--line);pointer-events:none;background:#fafafa}}
.secs{{font-size:11.5px;color:var(--muted);line-height:1.7}}
.secs span{{display:inline-block;background:#f5f7f9;border:1px solid #e6eaef;border-radius:3px;padding:1px 6px;margin:2px 3px 2px 0}}
.empty{{text-align:center;color:var(--muted);padding:34px 0;font-size:13px}}
@media print{{body{{background:#fff}}.bf-tools,.bf-hint{{display:none}}table.idx tbody tr{{page-break-inside:avoid}}}}
</style>
</head>
<body>
{NAV}
<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">资讯索引</a> / 合规简报归档</div>
  <h1>合规简报归档</h1>
  <p>聚合自动化合规资讯（日报 / 周报 / 月报 / 补编）全部历史与最新期次，提供网页版在线阅读（PDF/Word 版保留在本机，不对外发布），按类型与关键词检索。由自动化任务每日同步更新。</p>
</div></div>

<div class="wrap">
  <div class="bf-stats">
    <div class="bf-stat"><div class="n">{len(items)}</div><div class="l">报告期次</div></div>
    <div class="bf-stat"><div class="n">{n_web}</div><div class="l">有网页版</div></div>
    <div class="bf-stat"><div class="n">{n_deep}</div><div class="l">深度分析版</div></div>
    <div class="bf-stat"><div class="n">{esc(latest)}</div><div class="l">最新期次</div></div>
  </div>

  <div class="bf-tools">
    <input id="bq" type="search" placeholder="搜索期次、类型、章节关键词，如 2026-09 / 周报 / 数据合规…"/>
  </div>
  <div class="bf-tools" style="margin-top:0">{"".join(chips)}</div>
  <p class="bf-hint">共 <span id="cnt">{len(rows)}</span> 条记录 · 全部为网页版，点开即读（PDF/Word 仅本机留存，不上传站点）</p>

  <table class="idx">
    <thead><tr>
      <th style="width:150px">期次 / 类型</th>
      <th style="width:90px">版本</th>
      <th style="width:190px">打开格式</th>
      <th>章节关键词</th>
    </tr></thead>
    <tbody id="tb">{body_rows}</tbody>
  </table>

  <p class="bf-hint" style="margin-top:18px">本归档由「合规报告索引自动刷新」任务同步生成 · 最后更新 {esc(now)}</p>
</div>
{FOOT}
<script>
var q=document.getElementById('bq'), tb=document.getElementById('tb'),
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
[].slice.call(document.querySelectorAll('.bf-chip')).forEach(function(c){{
  c.addEventListener('click', function(){{
    [].slice.call(document.querySelectorAll('.bf-chip')).forEach(function(x){{x.classList.remove('on');}});
    c.classList.add('on'); filt=c.dataset.f; apply();
  }});
}});
</script>
</body>
</html>
"""
    with open(BRIEFS, "w", encoding="utf-8") as f:
        f.write(doc)
    # 期次数只统计「站点上真的有内容」的期次，避免与记录条数对不上
    n_online = sum(
        1 for g in items
        if any(ext in fmts for fmts in g["files"].values() for ext in ONLINE_FMTS)
    )
    return n_online, len(rows), n_web, n_deep, latest


def update_manifest():
    entry = {
        "title": "合规简报归档",
        "url": "news/briefs.html",
        "desc": "自动化合规资讯（日报/周报/月报/补编）全期次归档，网页版在线阅读，按类型与关键词检索。",
        "cat": "资讯索引",
        "tags": ["日报", "周报", "月报", "简报", "归档"],
    }
    data = []
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    # 清理非公开条目（PRM 与打磨日志不对外，剔除历史残留），否则搜索结果会暴露入口
    # 见 generate_modules.PRIVATE_URLS
    PRIVATE_URLS = {"analysis/polish.html", "prm.html",
                    "_private/polish.html", "_private/prm.html"}
    before = len(data)
    data = [d for d in data if d.get("url") not in PRIVATE_URLS]
    cleaned = before - len(data)

    def _write(items):
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    if any(d.get("title") == "合规简报归档" for d in data):
        if cleaned:
            _write(data)
            return f"已剔除 {cleaned} 条非公开条目"
        return "exists"
    data.append(entry)
    _write(data)
    return "added" + (f"（并剔除 {cleaned} 条非公开条目）" if cleaned else "")


def main():
    print("扫描源目录:", SRC)
    groups = scan()
    if not groups:
        print("未找到任何报告文件，退出。")
        return
    copied, skipped, size = sync_reports(groups)
    print(f"报告同步：新增复制 {copied} 份，跳过 {skipped} 份，本次复制 {size/1024/1024:.1f} MB")
    n_items, n_rows, n_web, n_deep, latest = build_briefs(groups)
    print(f"简报归档页生成：期次 {n_items} · 记录 {n_rows} · 网页版 {n_web} · 深度版 {n_deep} · 最新 {latest}")
    m = update_manifest()
    print("搜索索引 manifest:", m)
    print("完成 →", BRIEFS)


def refresh_chrome():
    """整页重写后恢复统一的对外元数据与页脚。

    本脚本每次运行都会整体重写输出页面，会冲掉 inject_meta.py 注入的
    og/twitter 标签与 unify_chrome.py 统一的导航页脚；两个脚本均幂等，
    在此重新执行即可恢复。"""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("inject_meta", "unify_chrome"):
        p = os.path.join(here, name + ".py")
        if not os.path.exists(p):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            m.main()
        except Exception as e:  # 元数据恢复失败不应阻断主流程
            print(f"  页面元数据刷新跳过（{name}）：{e}")


if __name__ == "__main__":
    main()
    refresh_chrome()
