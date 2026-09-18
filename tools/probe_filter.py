#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交互探针：模拟点击看板上的数字，验证「过滤条件条 + 命中数」是否真的动了。

无头 Chrome 的 --dump-dom 会执行 JS，但不会点击。这里注入一段探针脚本，
用 dispatchEvent 触发真实点击（走同一个 document 级监听），再把结果写回 DOM 属性。
判据：命中数必须与矩阵单元格上印的数字一致 —— 数字可点但点完对不上，比不可点更糟。
"""
import json
import os
import re
import subprocess
import sys

try:
    from _stash import stash          # 直接运行 tools/xxx.py 时，本目录在 sys.path[0]
except ImportError:                   # 被当包导入时
    from tools._stash import stash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PROBE = r"""
<script>
setTimeout(function(){
  var out={};
  try{
    var cell=document.querySelector('[data-flt*="org="]');
    out.cond = cell ? cell.getAttribute('data-flt') : null;
    out.printed = cell ? cell.textContent.trim() : null;
    if(cell){ cell.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})); }
    var bar=document.getElementById('fltBar');
    out.bar = bar && !bar.hidden ? bar.textContent.replace(/\s+/g,' ').trim() : '(无)';
    var rows=[].slice.call(document.querySelectorAll('#docTbl tbody tr[data-docrow]'));
    out.total = rows.length;
    out.vis = rows.filter(function(r){return !r.hidden;}).length;
    out.cnt = (document.getElementById('docCnt')||{}).textContent;
    var ai=document.querySelector('[data-ai]');
    out.ai = ai ? ai.getAttribute('data-ai') : null;
    out.nFlt = document.querySelectorAll('[data-flt]').length;
    out.nAi  = document.querySelectorAll('[data-ai]').length;
    out.nNum = document.querySelectorAll('.num-a').length;
    // 算法看板没有 data-flt，走 data-ai：点它应触发「按需加载索引 → 列出条目」
    if(!cell && ai){
      ai.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
      var tries=0;
      var t=setInterval(function(){
        var tb=document.querySelectorAll('#algoIdx tbody tr');
        var bar=document.querySelector('#algoIdx .flt-bar');
        if((tb.length>1) || ++tries>25){
          clearInterval(t);
          out.idxRows = tb.length;
          out.idxBar = bar ? bar.textContent.replace(/\s+/g,' ').trim() : '(无)';
          document.body.setAttribute('data-probe', JSON.stringify(out));
        }
      },200);
      return;
    }
  }catch(e){ out.err = String(e); }
  document.body.setAttribute('data-probe', JSON.stringify(out));
}, 900);
</script>
"""


def run(page):
    path = os.path.join(ROOT, page)
    html = open(path, encoding="utf-8").read()
    tmp = os.path.join(os.path.dirname(path), "._probe_flt.html")
    k = html.rfind("</body>")
    open(tmp, "w", encoding="utf-8").write(
        html[:k] + PROBE + html[k:] if k != -1 else html + PROBE)
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=6000", "--dump-dom",
                            "file://" + tmp],
                           capture_output=True, text=True, timeout=120)
        dom = r.stdout
    finally:
        stash(tmp)
    m = re.search(r'data-probe="(.*?)"', dom, re.S)
    if not m:
        print(f"{page}  ! 探针未执行")
        return
    raw = (m.group(1).replace("&quot;", '"').replace("&amp;", "&")
           .replace("&lt;", "<").replace("&gt;", ">"))
    d = json.loads(raw)
    print(f"—— {page}")
    print(f"   可点数字: data-flt {d.get('nFlt')} · data-ai {d.get('nAi')} · .num-a {d.get('nNum')}")
    print(f"   点击条件: {d.get('cond')}")
    print(f"   单元格印数: {d.get('printed')}   过滤后命中: {d.get('vis')} / {d.get('total')}"
          f"   #docCnt={d.get('cnt')}")
    print(f"   条件条: {d.get('bar')}")
    if d.get("ai"):
        print(f"   速查入口示例: {d.get('ai')}")
    if d.get("idxRows") is not None:
        print(f"   速查索引已按需加载：渲染 {d.get('idxRows')} 行　条件条: {d.get('idxBar')}")
    if d.get("err"):
        print("   ERROR", d["err"])


if __name__ == "__main__":
    for p in (sys.argv[1:] or ["analysis/app-violations.html",
                               "analysis/algo-filing.html"]):
        run(p)
