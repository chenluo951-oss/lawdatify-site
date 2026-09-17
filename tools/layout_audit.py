#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排版体检：用无头 Chrome 实测各页面「可视化块」占位与正文起点。

解决的问题：静态站点里图示/图表/数字卡常被写成 width:100% 的大块，
把真正的正文推到屏外。肉眼看不准，用实测数据说话。

用法：
    python3 tools/layout_audit.py                 # 审计内置页面清单
    python3 tools/layout_audit.py index.html kb/index.html
    python3 tools/layout_audit.py --json out.json

输出：每页一行 —— 正文首段 Y 坐标、最大的可视化块（选择器/高度/占视口比）。
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

DEFAULT_PAGES = [
    "index.html",
    "news/index.html", "news/actions.html", "news/map.html",
    "news/calendar.html", "news/briefs.html", "news/today.html",
    "analysis/index.html", "analysis/food-label.html",
    "analysis/app-violation-pattern.html", "analysis/pi-audit.html",
    "analysis/ai-label.html", "analysis/algo-filing-guide.html",
    "analysis/dark-store-license.html",
    "analysis/app-violations.html", "analysis/algo-filing.html",
    "kb/index.html", "kb/standards.html", "kb/cases.html",
    "kb/citations.html", "kb/texts.html",
    "manage/index.html", "manage/audit.html",
]

# 视为「可视化/大块数据展示」的选择器
VIZ_SEL = ",".join([
    "figure", ".art-fig", ".prac-fig", ".geo-frame", ".kpi", ".kpi-card",
    ".stat-grid", ".stat-card", ".stat", ".lb-row", ".lb-rows", ".cab",
    ".deck", ".rd-tile", ".dist", ".dist-row", "svg", "canvas",
    ".pulse", ".hero", ".up-hero", ".pagehead", ".fbar", ".lb-tools",
])

# 视为「正文首段」的选择器（按优先级）
BODY_SEL = [
    ".art-lead p", ".art p", ".up-item .up-point", ".ni-body",
    "main p", ".wrap p", ".inner p",
]

PROBE = r"""
<script>
(function(){
 try{
  var VIZ = %(viz)s, BODY = %(body)s;
  function h(el){var r=el.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),top:Math.round(r.top+window.scrollY)};}
  function pick(el){
    var cls=(el.className&&el.className.toString?el.className.toString():"").trim().split(/\s+/)[0];
    return el.tagName.toLowerCase()+(cls?("."+cls):"");
  }
  var out={vw:window.innerWidth, vh:window.innerHeight, docH:document.documentElement.scrollHeight, viz:[], body:null, bodyTop:null, blocks:[]};
  document.querySelectorAll(VIZ).forEach(function(el){
    var r=h(el);
    if(r.h<20) return;
    out.viz.push({sel:pick(el), h:r.h, w:r.w, top:r.top});
  });
  for(var i=0;i<BODY.length;i++){
    var el=document.querySelector(BODY[i]);
    if(el){ var r=h(el); out.body=BODY[i]; out.bodyTop=r.top; break; }
  }
    document.querySelectorAll('.art-fig,.kpi,.stat-grid,.lb-row,figure,.dist,.deck,.hero,.pulse,.pagehead,.fbar,.art h2.at').forEach(function(el){
      var r=h(el);
      if(r.h<20||r.top>9000) return;
      out.blocks.push({sel:pick(el), top:r.top, h:r.h});
    });
    out.blocks.sort(function(a,b){return a.top-b.top;});
    // 首屏（视口高度内）里，正文区之外的大块合计占了多少
    var sum=0; out.blocks.forEach(function(b){
      if(b.top<out.vh) sum+=Math.min(b.h, out.vh-b.top);
    });
  out.firstScreenViz = sum;
  document.body.setAttribute("data-layout-audit", JSON.stringify(out));
 }catch(e){
  document.body.setAttribute("data-layout-audit",
    JSON.stringify({error: String(e && e.message || e)}));
 }
})();
</script>
"""


def measure(page):
    path = os.path.join(ROOT, page)
    if not os.path.exists(path):
        return {"page": page, "error": "missing"}
    html = open(path, encoding="utf-8").read()
    probe = PROBE % {"viz": json.dumps(VIZ_SEL), "body": json.dumps(BODY_SEL)}
    tmp = os.path.join(ROOT, "_qa", "._audit_tmp.html")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    # 保持相对路径可用：把临时文件放在页面同级目录
    tmp = os.path.join(os.path.dirname(path), "._audit_tmp.html")
    instr = html.replace("</body>", probe + "</body>")
    if probe not in instr:
        instr = html + probe
    open(tmp, "w", encoding="utf-8").write(instr)
    try:
        r = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--window-size=1280,900", "--virtual-time-budget=2500",
             "--dump-dom", "file://" + tmp],
            capture_output=True, text=True, timeout=90)
        dom = r.stdout
    finally:
        os.remove(tmp)
    m = re.search(r'data-layout-audit="(.*?)"></body>', dom, re.S)
    if not m:
        m = re.search(r'data-layout-audit="(.*?)"', dom, re.S)
    if not m:
        return {"page": page, "error": "probe-failed"}
    raw = m.group(1)
    raw = (raw.replace("&quot;", '"').replace("&amp;", "&")
              .replace("&lt;", "<").replace("&gt;", ">"))
    d = json.loads(raw)
    d["page"] = page
    return d


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    json_out = None
    if "--json" in sys.argv:
        json_out = sys.argv[sys.argv.index("--json") + 1]
    pages = args or DEFAULT_PAGES
    rows = []
    for p in pages:
        d = measure(p)
        rows.append(d)
        if "error" in d:
            print("%-42s ERROR %s" % (p, d["error"]))
            continue
        viz = sorted(d["viz"], key=lambda x: -x["h"])[:3]
        vtxt = " | ".join("%s %dpx" % (v["sel"], v["h"]) for v in viz)
        bt = d["bodyTop"]
        flag = ""
        if bt is not None and bt > 1000:
            flag = "  << 正文起点过低"
        print("%-42s 正文=%-22s Y=%-6s 块: %s%s" % (
            p, str(d["body"]), str(bt), vtxt, flag))
        for b in (d.get("blocks") or [])[:8]:
            if b["h"] >= 60 or b["sel"].startswith((".hero", ".pagehead", ".dist")):
                print("      %-22s top=%-6d h=%d" % (b["sel"], b["top"], b["h"]))
    if json_out:
        open(os.path.join(ROOT, json_out), "w", encoding="utf-8").write(
            json.dumps(rows, ensure_ascii=False, indent=1))
        print("已写出", json_out)


if __name__ == "__main__":
    main()
