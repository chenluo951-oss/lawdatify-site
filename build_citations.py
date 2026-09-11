#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_citations.py —— 生成「高频引用法条」模块 kb/citations.html

数据源：
  sources/standards/hot_articles.json   法条 + 真实案例 + 合规场景/处罚标准/法律责任/正面示例（人工维护）
  kb/texts/index.json                   站内原文库目录（把法条挂到法规原文的锚点）
  sources/library/corpus/ + 站内页面     引用热度（被引次数）统计，缓存于 sources/standards/citation_counts.json

用法：
    python3 build_citations.py              # 用缓存热度，渲染页面
    python3 build_citations.py --recount    # 重新统计引用热度再渲染
"""
import os
import re
import sys
import json
import html
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H
import edits as E

HOT = os.path.join(HERE, "sources", "standards", "hot_articles.json")
COUNTS = os.path.join(HERE, "sources", "standards", "citation_counts.json")
TEXT_INDEX = os.path.join(HERE, "kb", "texts", "index.json")
OUT = os.path.join(HERE, "kb", "citations.html")

SITE_GLOBS = ["kb", "news", "analysis", "radar", "updates"]
SKIP_DIRS = {".git", "sources", "_quarantine", "_private", "assets", "node_modules"}


def esc(s):
    return html.escape(str(s or ""), quote=True)


# ---------------- 引用热度统计 ----------------
def norm_art(a):
    """把「第十四条第（四）项」这类表述截成「第十四条」，便于文本匹配。"""
    m = re.match(r"第[一二三四五六七八九十百零〇\d]+条", a or "")
    return m.group(0) if m else (a or "")


def count_citations(items):
    """统计每条法条被引用的次数：法规名 + 该条条号同时出现，计一次。

    只统计语料库与站内文章（跳过本模块自身产物，避免自计数）。
    """
    pats = {}
    for it in items:
        art = norm_art(it["art"])
        if not art:
            continue
        alts = []
        for n in (it["law"], it.get("law_short") or ""):
            n = (n or "").replace("中华人民共和国", "").replace("（2025 修订）", "").strip()
            if len(n) >= 4:
                alts.append(re.escape(n))
        if not alts:
            continue
        names = "(?:%s)" % "|".join(alts)
        pats[it["id"]] = re.compile(
            r"(?:《%s》|%s)[^。；\n]{0,6}?%s" % (names, names, re.escape(art)))
    counts = {k: 0 for k in pats}
    srcs = []
    corpus = H.CORPUS
    if os.path.isdir(corpus):
        srcs += [os.path.join(corpus, f) for f in os.listdir(corpus) if f.endswith(".txt")]
    for dp, dns, fns in os.walk(HERE):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for f in fns:
            if f.endswith((".html", ".json", ".md")):
                srcs.append(os.path.join(dp, f))
    for p in srcs:
        try:
            t = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for k, rx in pats.items():
            counts[k] += len(rx.findall(t))
    return counts


def load_counts(items, recount=False):
    d = H.load_json(COUNTS, {})
    if recount or not d.get("counts") or d.get("stamp") != len(items):
        print("统计引用热度（扫描 %s 与站内页面）…" % H.CORPUS)
        c = count_citations(items)
        d = {"stamp": len(items), "counts": c}
        H.save_json(COUNTS, d)
        print("   完成：最高 %d 次 / 最低 %d 次" % (max(c.values() or [0]), min(c.values() or [0])))
    return d["counts"]


# ---------------- 渲染 ----------------
KIND_CLS = {"行政处罚": "k-adm", "行政执法": "k-adm", "监管通报": "k-watch",
            "监管执法": "k-watch", "行政监管": "k-watch",
            "司法案例": "k-jud", "刑事案例": "k-cri"}

PAGE_CSS = """
.ct-lead{font-size:14.5px;color:var(--muted);line-height:1.95;margin:0 0 20px;max-width:860px}
.ct-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:#fff;border:1px solid var(--line);
  border-radius:12px;padding:12px 14px;margin-bottom:18px}
.ct-bar input[type=search]{flex:1;min-width:220px;padding:8px 12px;border:1px solid var(--line);
  border-radius:8px;font-size:14px;font-family:var(--sans);color:var(--ink);outline:none}
.ct-chips{display:flex;flex-wrap:wrap;gap:6px}
.ct-chip{font-size:12.5px;padding:4px 11px;border-radius:999px;border:1px solid var(--line);
  background:#fff;color:var(--muted);cursor:pointer;font-family:var(--sans)}
.ct-chip.on{background:var(--ink);border-color:var(--ink);color:#fff}
.ct-seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.ct-seg button{border:0;background:#fff;color:var(--ink-2);font-size:12.5px;padding:6px 12px;
  cursor:pointer;font-family:var(--sans);border-right:1px solid var(--line)}
.ct-seg button:last-child{border-right:0}
.ct-seg button.on{background:var(--brand);color:#fff}
.ct-meta{font-size:12.5px;color:var(--faint);margin-bottom:12px}
.ct-list{display:grid;gap:12px}
.ct-card{background:#fff;border:1px solid var(--line);border-radius:13px;overflow:hidden;
  box-shadow:0 1px 2px rgba(16,24,40,.04)}
.ct-head{display:flex;gap:14px;align-items:flex-start;padding:16px 18px;cursor:pointer}
.ct-head:hover{background:#fafbfd}
.ct-no{flex:0 0 46px;height:46px;border-radius:11px;background:#f1f5fa;color:var(--brand);
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:15px;
  font-variant-numeric:tabular-nums}
.ct-main{flex:1;min-width:0}
.ct-law{font-size:12.5px;color:var(--muted);margin-bottom:4px}
.ct-law b{color:var(--ink);font-size:13.5px;font-weight:700}
.ct-art{font-size:17px;font-weight:800;color:var(--ink);line-height:1.5;margin:0 0 6px}
.ct-hl{font-size:13.5px;color:var(--ink-2);line-height:1.75;margin:0}
.ct-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.ct-tag{font-size:11.5px;padding:2px 9px;border-radius:999px;background:#eef2f7;color:var(--ink-2)}
.ct-tag.dm{background:#e8f0fa;color:var(--brand)}
.ct-heat{flex:0 0 116px;text-align:right}
.ct-heat .n{font-size:20px;font-weight:800;color:var(--warn);font-variant-numeric:tabular-nums}
.ct-heat .n small{font-size:11.5px;font-weight:600;color:var(--muted);margin-left:2px}
.ct-heat .l{font-size:11.5px;color:var(--faint);margin-top:2px}
.ct-heatbar{height:4px;border-radius:2px;background:#eef2f7;margin-top:6px;overflow:hidden}
.ct-heatbar i{display:block;height:100%;background:linear-gradient(90deg,#e8a33d,#d97706)}
.ct-body{display:none;border-top:1px solid var(--line-2);padding:18px}
.ct-card.open .ct-body{display:block}
.ct-secs{display:grid;gap:14px}
@media(min-width:900px){.ct-secs{grid-template-columns:1fr 1fr}}
.ct-sec{background:#fafbfd;border:1px solid var(--line-2);border-radius:10px;padding:13px 15px}
.ct-sec h4{margin:0 0 8px;font-size:13px;color:var(--brand);letter-spacing:.4px;font-weight:800}
.ct-sec p{margin:0;font-size:13.5px;line-height:1.9;color:var(--ink-2)}
.ct-quote{grid-column:1/-1;background:#fffdf5;border:1px solid #f0e2c0}
.ct-quote p{font-family:"Songti SC","宋体",serif;font-size:14.5px;line-height:2.0;color:#3a3226}
.ct-cases{grid-column:1/-1}
.ct-case{background:#fff;border:1px solid var(--line);border-radius:10px;padding:13px 15px;margin-top:10px}
.ct-case:first-of-type{margin-top:0}
.ct-ck{display:inline-block;font-size:11.5px;padding:2px 9px;border-radius:999px;margin-right:8px;font-weight:700}
.k-adm{background:#fdeaea;color:#b3261e}
.k-watch{background:#fdf3e3;color:#9a6108}
.k-jud{background:#e8f0fa;color:#1b4f8a}
.k-cri{background:#efe8fb;color:#5b3fa8}
.ct-ct{font-size:14.5px;font-weight:700;color:var(--ink);line-height:1.6;display:inline}
.ct-cm{font-size:12.5px;color:var(--faint);margin:6px 0 0}
.ct-cr{font-size:13px;color:#8a3b12;background:#fff6ed;border-left:3px solid #e8a33d;
  padding:7px 11px;border-radius:0 7px 7px 0;margin:9px 0 0;line-height:1.8}
.ct-cs{font-size:13.5px;color:var(--ink-2);line-height:1.9;margin:8px 0 0}
.ct-cl{font-size:12.5px;margin:10px 0 0}
.ct-cl a{font-weight:600}
.ct-link,.ct-btn{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;padding:5px 11px;
  border:1px solid var(--line);border-radius:8px;color:var(--ink-2);background:#fff;
  font-family:var(--sans);cursor:pointer}
.ct-link:hover,.ct-btn:hover{border-color:var(--brand);color:var(--brand);text-decoration:none}
.ct-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.ct-empty{color:var(--faint);font-size:14px;padding:40px 0;text-align:center}
.ct-note{font-size:12.5px;color:var(--faint);line-height:1.9;margin:22px 0 0}
@media print{
  .topnav,.subnav,.mod-bound,footer,.ct-bar,#toTop{display:none !important}
  .ct-body{display:block !important}
  .ct-card{break-inside:avoid;box-shadow:none}
}
"""

PAGE_JS = r"""
(function(){
  var CUR_DM='', CUR_ORDER='heat';
  var cards=[].slice.call(document.querySelectorAll('.ct-card'));
  var box=document.getElementById('ct-list');
  function val(c){ return c.dataset; }
  function apply(){
    var q=(document.getElementById('ct-q').value||'').trim();
    var arr=cards.filter(function(c){
      if(CUR_DM && c.dataset.dm!==CUR_DM) return false;
      if(q && c.dataset.text.indexOf(q)<0) return false;
      return true;
    });
    if(CUR_ORDER==='heat') arr.sort(function(a,b){return (+b.dataset.heat)-(+a.dataset.heat)});
    else if(CUR_ORDER==='dm') arr.sort(function(a,b){
      return a.dataset.dm.localeCompare(b.dataset.dm) || (+b.dataset.heat)-(+a.dataset.heat); });
    else arr.sort(function(a,b){return a.dataset.seq.localeCompare(b.dataset.seq)});
    cards.forEach(function(c){c.style.display='none'});
    arr.forEach(function(c){c.style.display=''; box.appendChild(c)});
    document.getElementById('ct-count').textContent=arr.length+' 条法条 · '+
      arr.reduce(function(s,c){return s+(+c.dataset.cases)},0)+' 个案例';
    document.getElementById('ct-empty').style.display=arr.length?'none':'';
  }
  document.getElementById('ct-q').addEventListener('input',apply);
  document.querySelectorAll('.ct-chip').forEach(function(b){
    b.onclick=function(){
      CUR_DM=b.dataset.dm;
      document.querySelectorAll('.ct-chip').forEach(function(x){x.className='ct-chip'});
      b.className='ct-chip on'; apply();
    };
  });
  document.querySelectorAll('.ct-seg button').forEach(function(b){
    b.onclick=function(){
      CUR_ORDER=b.dataset.o;
      b.parentNode.querySelectorAll('button').forEach(function(x){x.className=''});
      b.className='on'; apply();
    };
  });
  document.querySelectorAll('.ct-head').forEach(function(h){
    h.onclick=function(ev){
      if(ev.target.tagName==='A') return;
      h.parentNode.classList.toggle('open');
    };
  });
  document.querySelectorAll('.ct-tocopy').forEach(function(b){
    b.onclick=function(){
      var card=b.closest('.ct-card');
      navigator.clipboard.writeText(card.innerText.replace(/\n{3,}/g,'\n\n').trim())
        .then(function(){ b.textContent='已复制 ✓'; setTimeout(function(){b.textContent='复制本条'},1500); });
    };
  });
  apply();
  if(location.hash){
    var t=document.getElementById(location.hash.slice(1));
    if(t){ t.classList.add('open'); t.scrollIntoView({block:'start'}); }
  }
})();
"""


PAGE_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>高频引用法条 · 合规无终点</title>
<meta name="description" content="按合规领域与引用热度排序的高频引用法条：逐条索引真实监管案例、行政处罚、司法裁判，并给出合规场景、处罚标准、法律责任与正面示例。">
<link rel="stylesheet" href="../assets/style.css">
<style>__CSS__</style>
</head>
<body>

<nav class="topnav"></nav>
<!-- SUBNAV:START --><!-- SUBNAV:END -->

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 高频引用法条</div>
  <h1>高频引用法条</h1>
  <p>收录 __N__ 条被引用频率最高的法条，逐条关联 __C__ 个真实案例——监管通报、行政处罚决定与司法裁判，<br>
     并给出对应的合规场景、处罚标准、法律责任与正面示例。可按合规领域筛选、按引用热度或法条序排列。</p>
</div></div>

<main class="wrap">
  <p class="ct-lead">案例全部取自监管机构与法院官网公开发布的具体页面（通报、典型案例、裁判文书），链接可直达原文。
     「站内引用热度」= 该法条在法规标准语料与站内文章中被引用的次数，用于反映现实执法与合规实务中的关注强度。</p>

  <div class="ct-bar">
    <input id="ct-q" type="search" placeholder="搜索法条、关键词、案例当事人或处罚事由">
    <div class="ct-seg">
      <button class="on" data-o="heat">按引用热度</button>
      <button data-o="dm">按合规领域</button>
      <button data-o="seq">按法规名</button>
    </div>
    <div class="ct-chips">__CHIPS__</div>
  </div>
  <div class="ct-meta" id="ct-count"></div>

  <div class="ct-list" id="ct-list">__CARDS__</div>
  <div class="ct-empty" id="ct-empty" style="display:none">没有符合条件的法条，换个关键词试试。</div>

  <p class="ct-note">说明：条文原文为便于阅读的摘录，完整条文请点「在原文库中定位」跳转站内原文库；处罚标准与法律责任根据现行有效版本整理，
     个案的处罚幅度还会受裁量基准、从轻从重情节影响。案例信息以官方发布内容为准。</p>
</main>

<footer></footer>
<script>__JS__</script>
</body>
</html>
"""


def sec(title, body, cls=""):
    if not body:
        return ""
    return f'<div class="ct-sec {cls}"><h4>{title}</h4>{body}</div>'


def render(items, counts, dm_name, law_index):
    heat_max = max([counts.get(x["id"], 0) for x in items] + [1])
    dm_count = collections.Counter(x["domain"] for x in items)
    order = [d["id"] for d in json.load(open(HOT, encoding="utf-8"))["domains"]]
    chips = ['<button class="ct-chip on" data-dm="">全部 %d</button>' % len(items)]
    for did in order:
        if not dm_count.get(did):
            continue
        chips.append('<button class="ct-chip" data-dm="%s">%s %d</button>'
                     % (esc(did), esc(dm_name[did]), dm_count[did]))

    cards = []
    for i, x in enumerate(items, 1):
        heat = counts.get(x["id"], 0)
        pct = max(4, round(heat / heat_max * 100))
        tid = x.get("text_id") or ""
        law_rec = law_index.get((x["law"] or "").strip(), {})
        tid = law_rec.get("id") or tid
        arts = [c for c in x["cases"]]
        tags = [f'<span class="ct-tag dm">{esc(dm_name[x["domain"]])}</span>',
                f'<span class="ct-tag">{esc(x["art"])}</span>',
                f'<span class="ct-tag">{len(arts)} 个案例</span>']
        if tid:
            tags.append(f'<span class="ct-tag">站内原文可定位</span>')
        cases_html = ""
        for c in arts:
            kc = KIND_CLS.get(c["kind"], "k-watch")
            cases_html += (
                '<div class="ct-case">'
                f'<div><span class="ct-ck {kc}">{esc(c["kind"])}</span>'
                f'<span class="ct-ct">{esc(c["title"])}</span></div>'
                f'<p class="ct-cm">{esc(c["org"])} · {esc(c["date"])}'
                + (f' · {esc(c["no"])}' if c.get("no") else "") + '</p>'
                f'<p class="ct-cr">处理结果：{esc(c["result"])}</p>'
                f'<p class="ct-cs">{esc(c["summary"])}</p>'
                f'<p class="ct-cl"><a class="ct-link" href="{esc(c["url"])}" '
                f'target="_blank" rel="noopener">查看官方原文 &#8599;</a></p>'
                '</div>')
        src_link = ""
        if tid:
            src_link = (f'<a class="ct-link" href="texts.html#{esc(tid)}|{esc(x["art"])}">'
                        f'在原文库中定位 {esc(x["art"])} &#8599;</a>')
        if law_rec.get("url"):
            src_link += (f'<a class="ct-link" href="{esc(law_rec["url"])}" target="_blank" '
                         f'rel="noopener">法规官方发布页 &#8599;</a>')
        body = '<div class="ct-secs">' + \
               sec("条文原文（摘录）", f'<p>{esc(x["quote"])}</p>', "ct-quote") + \
               sec("合规场景", f'<p>{esc(x["scene"])}</p>') + \
               sec("处罚标准", f'<p>{esc(x["penalty"])}</p>') + \
               sec("法律责任", f'<p>{esc(x["liability"])}</p>') + \
               sec("正面示例", f'<p>{esc(x["positive"])}</p>') + \
               sec("真实案例（%d）" % len(arts), cases_html, "ct-cases") + \
               '</div>' + \
               '<div class="ct-acts"><button class="ct-btn ct-tocopy">复制本条</button>' + src_link + '</div>'
        search_text = " ".join([x["law"], x.get("law_short", ""), x["art"], x["headline"],
                                x["scene"], x["penalty"], x["liability"], x["positive"]] +
                               [c["title"] + c["summary"] for c in arts])
        cards.append(
            f'<article class="ct-card" id="{esc(x["id"])}" data-dm="{esc(x["domain"])}" '
            f'data-heat="{heat}" data-cases="{len(arts)}" '
            f'data-seq="{esc(x["law_short"])}{esc(x["art"])}" '
            f'data-text="{esc(search_text)}">'
            '<div class="ct-head">'
            f'<div class="ct-no">{i:02d}</div>'
            '<div class="ct-main">'
            f'<div class="ct-law">{esc(x["law"])} · <b>{esc(x["art"])}</b></div>'
            f'<p class="ct-art">{esc(x["headline"])}</p>'
            f'<div class="ct-tags">{"".join(tags)}</div>'
            '</div>'
            f'<div class="ct-heat"><div class="n">{heat}<small>次被引</small></div>'
            '<div class="l">站内引用热度</div>'
            f'<div class="ct-heatbar"><i style="width:{pct}%"></i></div></div>'
            '</div>'
            f'<div class="ct-body">{body}</div>'
            '</article>')

    tpl = PAGE_TPL
    htmls = (tpl.replace("__CSS__", PAGE_CSS.strip())
             .replace("__JS__", PAGE_JS.strip())
             .replace("__CHIPS__", "".join(chips))
             .replace("__CARDS__", "".join(cards))
             .replace("__N__", str(len(items)))
             .replace("__C__", str(sum(len(x["cases"]) for x in items))))
    open(OUT, "w", encoding="utf-8").write(htmls)
    print("高频法条页：kb/citations.html（%d 条 / %d 案例 / %.0f KB）"
          % (len(items), sum(len(x["cases"]) for x in items), os.path.getsize(OUT) / 1024))


def main():
    data = json.load(open(HOT, encoding="utf-8"))
    items = data["items"]
    # 人工修改覆盖层：字段修正（编辑器写入）
    items = [E.apply_patch("hot", x["id"], x) for x in items]
    dm_name = {d["id"]: d["name"] for d in data["domains"]}
    idx = H.load_json(TEXT_INDEX, {"items": []})
    law_index = {}
    for x in idx.get("items", []):
        law_index.setdefault(x["name"], x)
    missing = [x["id"] for x in items
               if not law_index.get(x["law"]) and not x.get("text_id")]
    if missing:
        print("以下法条未匹配到站内原文：", missing)
    counts = load_counts(items, recount="--recount" in sys.argv)
    render(items, counts, dm_name, law_index)


if __name__ == "__main__":
    main()
