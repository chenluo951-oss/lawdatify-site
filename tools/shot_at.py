#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分屏截图：把页面上某个区块提到最前面再截，便于逐段目视检查。

无头 Chrome 的 --screenshot 只截窗口大小、不滚动，长页面没法一次看全；
把目标区块之前的兄弟节点 display:none 掉，等于把「视口」搬到该区块上。
"""
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
OUT = "/Users/luochen/WorkBuddy/Claw/_qa/shots"


def shot(page, sel_index, out, h=1500, w=1440):
    path = os.path.join(ROOT, page)
    html = open(path, encoding="utf-8").read()
    tmp = os.path.join(os.path.dirname(path), "._shot_tmp.html")
    # ⚠️ 不是所有页面都有 <main>：analysis/ 下的专题长文骨架是 .wrap > .art，
    #    只认 main 会静默拍到页面顶部（看不出问题，以为截图成功）。
    #    按 main → .art → .wrap 依次回退。
    js = ("<script>window.addEventListener('load',function(){"
          "var m=document.querySelector('main')||document.querySelector('.art')"
          "||document.querySelector('.wrap');if(!m)return;"
          "var c=[].slice.call(m.children);"
          f"c.slice(0,{sel_index}).forEach(function(e){{e.style.display='none';}});"
          "});</script>")
    k = html.rfind("</body>")
    open(tmp, "w", encoding="utf-8").write(
        html[:k] + js + html[k:] if k != -1 else html + js)
    os.makedirs(OUT, exist_ok=True)
    try:
        subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                        "--hide-scrollbars", f"--window-size={w},{h}",
                        "--virtual-time-budget=6000",
                        f"--screenshot={os.path.join(OUT, out)}",
                        "file://" + tmp], capture_output=True, timeout=120)
    finally:
        stash(tmp)
    print(out, os.path.getsize(os.path.join(OUT, out)) // 1024, "KB")


if __name__ == "__main__":
    a = sys.argv[1:]
    shot(a[0], int(a[1]), a[2], int(a[3]) if len(a) > 3 else 1500)
