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
COMPETE = os.path.join(HERE, "sources", "standards", "compete_law.json")
# 机器扩写的法条（tools/extend_hot_articles.py 生成）——与手工文件分开存，
# 合并时**手工优先**（同一 (法规, 条号) 以手工版为准）
AUTO = os.path.join(HERE, "sources", "standards", "hot_articles_auto.json")
COUNTS = os.path.join(HERE, "sources", "standards", "citation_counts.json")
TEXT_INDEX = os.path.join(HERE, "kb", "texts", "index.json")
# 法条 → 引用它的案例（tools/build_article_index.py 生成）：本页的「反向索引」数据源
CASE_REFS = os.path.join(HERE, "sources", "standards", "case_refs.json")
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


# ---------------- 反向索引：一条法条 → 引用它的案例（P1-2） ----------------
# 出处：对标北大法宝「法条联想」。此前本站只能「从案例看到依据」，
# 「从法条看到案例」这一半是缺的 —— 本页补上。
def norm_law(name):
    """与 tools/build_article_index.py 的 nkey() 保持同一口径，键才能对上。"""
    s = re.sub(r"[\s\u3000《》]", "", name or "")
    s = re.sub(r"^中华人民共和国", "", s)
    s = re.sub(r"[（(][^）)]{0,12}(修订|修正|草案|征求意见稿)[）)]$", "", s)
    return s


def load_case_refs():
    d = H.load_json(CASE_REFS, {})
    if not d:
        print("  ! 反向索引缺失：先跑 tools/build_article_index.py")
    return d


def art_keys(law, art):
    """一条法条可能有多个候选键：条目里写着「第二十八条、第二十九条」时要逐个试。"""
    lk = norm_law(law)
    if not lk:
        return []
    out = [f"{lk}|{art}"]
    for a in re.split(r"[、,，;；/]", art or ""):
        a = a.strip()
        if a.startswith("第") and a.endswith("条") and a not in out:
            out.append(f"{lk}|{a}")
    return out


def case_refs_for(crefs, law, art):
    for k in art_keys(law, art):
        got = (crefs.get("refs") or {}).get(k)
        if got:
            return k, got
    return None, []


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
/* 反向索引（P1-2）：从法条反查「案例库里哪些案例引用了本条」。
   与上半区「真实案例（按案件整理）」区分开——那是案件视角，这是法条视角。 */
.ct-lead2{margin:0 0 11px;font-size:12.8px;line-height:1.85;color:var(--muted)}
.ct-caserev{background:#fffdf7;border-color:#f0e2c0}
.ct-caserev .ct-ct{font-size:13.6px;text-decoration:none;color:var(--ink)}
.ct-caserev .ct-ct:hover{color:var(--brand);text-decoration:underline}
.ct-cm-x{color:var(--brand);font-weight:600}
.ct-compete{grid-column:1/-1;background:#fbfaf7;border:1px solid #f0e9dc}
.ct-comp+.ct-comp{margin-top:16px;padding-top:14px;border-top:1px dashed #e6ddc9}
.ct-cp-t{margin:0 0 8px;font-size:14.5px;font-weight:700;color:var(--ink)}
.ct-cp-lab{display:inline-block;margin-right:8px;padding:1px 7px;border-radius:4px;
  background:#eef3fa;color:#1b4f8a;font-size:11.5px;font-weight:700;vertical-align:1px;white-space:nowrap}
.ct-cp-issue,.ct-cp-rule,.ct-cp-guide{margin:0 0 9px;font-size:13.5px;line-height:1.9;color:var(--ink-2)}
.ct-cp-tw{overflow-x:auto;margin:11px 0}
.ct-cp-tb{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff}
.ct-cp-tb th,.ct-cp-tb td{border:1px solid var(--line);padding:7px 9px;text-align:left;
  vertical-align:top;line-height:1.75}
.ct-cp-tb thead th{background:#f4f6fa;color:var(--ink);font-weight:700;white-space:nowrap}
.ct-cp-tb tbody th{background:#fbfcfd;color:var(--ink-2);font-weight:700;white-space:nowrap;width:100px}
.ct-cp-df{margin:11px 0 8px;padding:11px 13px;background:#fff;border:1px solid var(--line);border-radius:8px}
.ct-cp-df h5{margin:0 0 7px;font-size:12.5px;color:#8a6d1f;letter-spacing:.3px}
.ct-cp-df ul{margin:0;padding:0;list-style:none}
.ct-cp-df li{font-size:13px;line-height:1.88;color:var(--ink-2);margin-bottom:6px}
.ct-cp-df li:last-child{margin-bottom:0}
.ct-cp-df li b{color:var(--ink);margin-right:7px}
.ct-cp-basis{margin:7px 0 0;font-size:11.5px;color:var(--faint);line-height:1.8}
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
     个案的处罚幅度还会受裁量基准、从轻从重情节影响。案例信息以官方发布内容为准。<br>
     「案例库中引用本条的案例」由案例正文的违法事实认定段自动识别得出（仅统计<b>明确写出《法规名》第 X 条</b>的引用），
     命中 __NREV__ 条法条；识别不到的（如仅写法规名、或援引的是规章而站内未收原文）不会出现，故该数字是下限，不是全部。</p>
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


def sec_if(title, val, cls=""):
    """纯文本小节：值为空就不渲染（机器扩写的条目部分字段为空，
    渲染成空盒子会让整页看起来「有内容但没写」）。"""
    v = (val or "").strip()
    return sec(title, f"<p>{esc(v)}</p>", cls) if v else ""


def load_compete():
    """按法条 id 归集竞合关系（一组竞合关系可同时挂在多条法条上）。"""
    try:
        d = json.load(open(COMPETE, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for cp in d.get("items", []):
        for a in cp.get("anchors", []):
            out.setdefault(a, []).append(cp)
    return out


def render_compete(cps):
    """法条竞合与抗辩思路：两条轨道的逐项对比 + 引导动作 + 抗辩要点。"""
    if not cps:
        return ""
    out = []
    for cp in cps:
        rows = "".join(
            f'<tr><th>{esc(r.get("k", ""))}</th><td>{esc(r.get("a", ""))}</td>'
            f'<td>{esc(r.get("b", ""))}</td></tr>' for r in cp.get("rows", []))
        dfs = "".join(
            f'<li><b>{esc(d.get("p", ""))}</b><span>{esc(d.get("h", ""))}</span></li>'
            for d in cp.get("defense", []))
        basis = "；".join(esc(b) for b in cp.get("basis", []))
        out.append(
            '<div class="ct-comp">'
            f'<p class="ct-cp-t">{esc(cp.get("title", ""))}</p>'
            f'<p class="ct-cp-issue"><span class="ct-cp-lab">竞合情形</span>'
            f'{esc(cp.get("issue", ""))}</p>'
            f'<p class="ct-cp-rule"><span class="ct-cp-lab">适用顺位</span>'
            f'{esc(cp.get("rule", ""))}</p>'
            '<div class="ct-cp-tw"><table class="ct-cp-tb">'
            '<thead><tr><th>维度</th><th>轨道 A</th><th>轨道 B</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            f'<p class="ct-cp-guide"><span class="ct-cp-lab">引导动作</span>'
            f'{esc(cp.get("guide", ""))}</p>'
            f'<div class="ct-cp-df"><h5>抗辩要点</h5><ul>{dfs}</ul></div>'
            f'<p class="ct-cp-basis">依据：{basis}</p>'
            '</div>')
    return "".join(out)


def render(items, counts, dm_name, law_index, compete=None, crefs=None):
    heat_max = max([counts.get(x["id"], 0) for x in items] + [1])
    dm_count = collections.Counter(x["domain"] for x in items)
    order = [d["id"] for d in json.load(open(HOT, encoding="utf-8"))["domains"]]
    crefs = crefs or {}
    cmeta = (crefs.get("_meta") or {}).get("cases") or {}
    n_rev_cases = len((crefs.get("_meta") or {}).get("by_case") or {})
    chips = ['<button class="ct-chip on" data-dm="">全部 %d</button>' % len(items)]
    for did in order:
        if not dm_count.get(did):
            continue
        chips.append('<button class="ct-chip" data-dm="%s">%s %d</button>'
                     % (esc(did), esc(dm_name[did]), dm_count[did]))

    cards = []
    n_rev_law = 0
    for i, x in enumerate(items, 1):
        heat = counts.get(x["id"], 0)
        pct = max(4, round(heat / heat_max * 100))
        tid = x.get("text_id") or ""
        law_rec = law_index.get((x["law"] or "").strip(), {})
        tid = law_rec.get("id") or tid
        arts = [c for c in x["cases"]]
        rkey, rurls = case_refs_for(crefs, x["law"], x["art"])
        if rurls:
            n_rev_law += 1
        tags = [f'<span class="ct-tag dm">{esc(dm_name[x["domain"]])}</span>',
                f'<span class="ct-tag">{esc(x["art"])}</span>',
                f'<span class="ct-tag">{len(arts)} 个案例</span>']
        if rurls:
            tags.append(f'<span class="ct-tag">案例库引用 {len(rurls)}</span>')
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
        cp_html = render_compete((compete or {}).get(x["id"]))
        # 反向索引块：只列案例库里**正文明确援引过本条**的案例（真引用，不是推测）
        rev_html = ""
        rev_terms = []
        if rurls:
            items_html = []
            for u in rurls[:14]:
                m = cmeta.get(u) or {}
                kc = KIND_CLS.get(m.get("k"), "k-watch")
                items_html.append(
                    '<div class="ct-case ct-caserev">'
                    '<div><span class="ct-ck ' + kc + '">' + esc(m.get("k") or "案例") + '</span>'
                    f'<a class="ct-ct" href="cases.html#{esc(m.get("id") or "")}">'
                    f'{esc(m.get("t") or "（未标注标题）")}</a></div>'
                    f'<p class="ct-cm">{esc(m.get("o") or "未标注机关")} · {esc(m.get("d") or "")}'
                    f'<span class="ct-cm-x">　在案例库中打开 →</span></p></div>')
            more = (f'<p class="ct-cm">另有 {len(rurls) - 14} 条，'
                    f'见 <a href="cases.html">合规案例库</a>。</p>' if len(rurls) > 14 else "")
            rev_html = ('<p class="ct-lead2">下列案例的违法事实认定段里<b>明确援引了本条</b>'
                        '（原文写作《%s》%s）。这是「从法条反查案例」的方向，'
                        '与上面按案件整理的真实案例互为交叉验证。</p>'
                        % (esc(norm_law(x["law"])), esc(x["art"]))) + "".join(items_html) + more
            rev_terms = [(m.get("t") or "") for u in rurls for m in [cmeta.get(u) or {}]]
        body = '<div class="ct-secs">' + \
               sec_if("条文原文（摘录）", x.get("quote"), "ct-quote") + \
               sec_if("合规场景", x.get("scene")) + \
               sec_if("处罚标准", x.get("penalty")) + \
               sec_if("法律责任", x.get("liability")) + \
               (sec("法条竞合与抗辩思路", cp_html, "ct-compete") if cp_html else "") + \
               sec_if("正面示例", x.get("positive")) + \
               sec("真实案例（%d）" % len(arts), cases_html, "ct-cases") + \
               (sec("案例库中引用本条的案例（%d）" % len(rurls), rev_html, "ct-cases")
                if rev_html else "") + \
               '</div>' + \
               '<div class="ct-acts"><button class="ct-btn ct-tocopy">复制本条</button>' + src_link + '</div>'
        search_text = " ".join([x["law"], x.get("law_short", ""), x["art"],
                                x.get("headline", ""), x.get("scene", ""),
                                x.get("penalty", ""), x.get("liability", ""),
                                x.get("positive", "")] +
                               [(cp.get("title", "") + cp.get("issue", "") + cp.get("guide", ""))
                                for cp in (compete or {}).get(x["id"], [])] +
                               rev_terms +
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
            f'<p class="ct-art">{esc(x.get("headline") or x["art"])}</p>'
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
             .replace("__NREV__", f"{n_rev_law} 条法条 / {n_rev_cases} 条案例")
             .replace("__N__", str(len(items)))
             .replace("__C__", str(sum(len(x["cases"]) for x in items))))
    open(OUT, "w", encoding="utf-8").write(htmls)
    print("高频法条页：kb/citations.html（%d 条 / %d 案例 / %.0f KB）"
          % (len(items), sum(len(x["cases"]) for x in items), os.path.getsize(OUT) / 1024))
    print("  反向索引：%d 条法条可反查案例，涉及 %d 条案例" % (n_rev_law, n_rev_cases))


def main():
    data = json.load(open(HOT, encoding="utf-8"))
    items = data["items"]
    # 合并机器扩写条目：同 (法规名归一, 条号) 以手工版为准
    if os.path.exists(AUTO):
        try:
            auto = json.load(open(AUTO, encoding="utf-8")).get("items", [])
        except Exception:
            auto = []
        def _k(z):
            return (re.sub(r"[《》\s]", "", z.get("law") or ""), z.get("art") or "")
        have = {_k(z) for z in items}
        add = [z for z in auto if _k(z) not in have]
        items = items + add
        print("高频法条：手工 %d + 自动 %d → 合计 %d" % (len(have), len(add), len(items)))
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
    compete = load_compete()
    n_cp = sum(1 for x in items if compete.get(x["id"]))
    print("法条竞合与抗辩：%d 条法条已挂载竞合分析" % n_cp)
    crefs = load_case_refs()
    render(items, counts, dm_name, law_index, compete, crefs)


if __name__ == "__main__":
    main()
