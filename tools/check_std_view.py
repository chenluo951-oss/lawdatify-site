#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准阅读页版式自检（无头 Chrome）。

校验项：
  1) 封面块 .st-cover（标准类别 / 标准号 / 中英文名 / 发布实施日期 / 发布机构）
  2) 目次块 .st-toc + 点线页码条目 .ln / em
  3) 章节标题 .st-h1/.st-h2/.st-h3/.st-h4 至少出现，且字号递减
  4) 列项 .st-li 悬挂缩进（text-indent 为负、padding-left 为正）
  5) 正文段落首行缩进
  6) 打印样式：封面/目次独立成页

踩坑记录（勿改）：
  · --dump-dom 打完不退出 → 必须 Popen + communicate(timeout) + kill
  · --dump-dom 会把属性引号统一成双引号 → 断言一律写 class="xxx"
  · 别用页面里出现过的字符串做断言（script 源码也进 DOM）
  · 探针必须等异步取文完成后再写 document.title，否则探针永远是空的
"""
import os
import re
import sys
import json
import subprocess
import threading
import http.server
import socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

FAIL = []
WARN = []


def serve(port=0):
    class Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=ROOT, **k)

        def log_message(self, *a):
            pass

    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), Q)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def dump(url, budget=9000):
    p = subprocess.Popen(
        [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
         "--virtual-time-budget=%d" % budget, "--dump-dom", url],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        out, _ = p.communicate(timeout=budget / 1000.0 + 30)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
    return (out or b"").decode("utf-8", "ignore")


PROBE_SEL = [".st-cover", ".st-toc", ".st-toc .ln", ".st-h1", ".st-h2", ".st-h3",
             ".st-li", ".st-ind", ".st-term", ".st-table"]


def probe_page(sid, port):
    """把探针注入阅读页，等异步取文完成后把计算样式写进 document.title。"""
    js = ("(function(){var n=0;var t=setInterval(function(){n++;"
          "var e=document.querySelector('.st-cover,.st-p');"
          "if(!e&&n<80)return;clearInterval(t);"
          "var o={},S=%s;"
          "for(var i=0;i<S.length;i++){try{var el=document.querySelector(S[i]);"
          "if(!el)continue;var c=getComputedStyle(el),r=el.getBoundingClientRect();"
          "o[S[i]]={fs:c.fontSize,ti:c.textIndent,pl:c.paddingLeft,ff:c.fontFamily.slice(0,28),"
          "w:Math.round(r.width),h:Math.round(r.height),txt:(el.textContent||'').slice(0,40)};"
          "}catch(err){}}"
          "document.title='PROBE'+JSON.stringify(o);},120);})();" % json.dumps(PROBE_SEL))
    src = open(os.path.join(ROOT, "kb", "texts.html"), encoding="utf-8").read()
    # 探针必须写回 kb/ 目录：阅读页用相对路径取 index.json / 分片，
    # 放到 tools/ 下相对路径会 404，页面永远取不到正文，探针也就永远是空的。
    # 且必须替换最后一个 </body>：阅读页脚本里含 '</body></html>' 字面量，
    # 命中第一个会把探针插进 JS 字符串里，制造 SyntaxError 假故障。
    probe = os.path.join(ROOT, "kb", "_probe.html")
    k = src.rfind("</body>")
    open(probe, "w", encoding="utf-8").write(src[:k] + "<script>%s</script>" % js + src[k:])
    dom = dump("http://127.0.0.1:%d/kb/_probe.html#%s" % (port, sid), 25000)
    m = re.search(r"PROBE(\{.*?\})</title>", dom, re.S)
    return json.loads(m.group(1)) if m else {}


def px(v):
    try:
        return float(re.sub(r"[^0-9.\-]", "", v or "") or 0)
    except ValueError:
        return 0.0


def main():
    httpd = serve()
    port = httpd.server_address[1]
    idx = json.load(open(os.path.join(ROOT, "kb", "texts", "index.json"), encoding="utf-8"))
    stds = [x for x in idx["items"] if x.get("kind") == "std"]
    with_toc = [x for x in stds if len(x.get("toc") or []) >= 6]
    samples = with_toc[:3] or stds[:2]
    print("样本 %d 部：%s" % (len(samples), "；".join(
        "%s %s" % (s["code"], s["name"][:14]) for s in samples)))

    doms = []
    for s in samples:
        d = dump("http://127.0.0.1:%d/kb/texts.html#%s" % (port, s["id"]), 20000)
        # 必须去掉 <script> 源码再断言：阅读页的 script 源码本身就是 DOM 文本节点，
        # 里面含 '<div class="st-cover">' 之类的字符串，直接找类名一定命中、永远假通过。
        d = re.sub(r"<script\b[^>]*>.*?</script>", "", d, flags=re.S)
        doms.append(d)
        print("  %s：正文 DOM %d 字符" % (s["code"], len(d)))
    dom = "\n".join(doms)

    for needle, label in [('class="st-cover"', "封面块"),
                          ('class="st-toc"', "目次块"),
                          ('class="ln', "目次条目（点线+页码）"),
                          ('class="st-li"', "列项"),
                          ('class="st-p"', "正文段落")]:
        if needle in dom:
            print("  ✓ %s" % label)
        else:
            FAIL.append("未渲染 %s（缺 %s）" % (label, needle))

    heads = [c for c in ("st-h1", "st-h2", "st-h3", "st-h4") if 'class="%s"' % c in dom]
    if heads:
        print("  ✓ 章节标题层级：%s" % "、".join(heads))
    else:
        FAIL.append("未渲染任何章节标题（st-h1~h4）")

    body = re.search(r'id="rd-body"[^>]*>(.*)', dom, re.S)
    if body:
        n = len(re.findall(r"<p class=", body.group(1)))
        print("  ✓ 正文块数 %d" % n)
        if n < 8:
            WARN.append("正文块数偏少（%d），确认断行是否生效" % n)
    else:
        FAIL.append("未找到 #rd-body 容器")

    styles = probe_page(samples[0]["id"], port)
    if not styles:
        FAIL.append("样式探针未取到（无头渲染未完成或探针注入失败）")
        styles = {}
    print("样式探针：")
    for k, v in styles.items():
        print("   %-12s fs=%-7s ti=%-8s pl=%-8s h=%-5s %s"
              % (k, v["fs"], v["ti"], v["pl"], v["h"], v["txt"][:26].replace("\n", " ")))

    c = styles.get(".st-cover")
    if styles and (not c or c["h"] < 60 or not c["txt"].strip()):
        FAIL.append("封面块尺寸/内容异常：%s" % c)
    elif c:
        print("  ✓ 封面块高度 %dpx" % c["h"])
    li = styles.get(".st-li")
    if li:
        if not (li["ti"].startswith("-") and px(li["pl"]) > 0):
            FAIL.append("列项非悬挂缩进：ti=%s pl=%s" % (li["ti"], li["pl"]))
        else:
            print("  ✓ 列项悬挂缩进（ti=%s / pl=%s）" % (li["ti"], li["pl"]))
    h1, h2 = styles.get(".st-h1"), styles.get(".st-h2")
    if h1 and h2:
        if px(h1["fs"]) <= px(h2["fs"]):
            FAIL.append("标题层级字号未递减：h1=%s h2=%s" % (h1["fs"], h2["fs"]))
        else:
            print("  ✓ 标题字号递减 h1=%s → h2=%s" % (h1["fs"], h2["fs"]))
    ind = styles.get(".st-ind")
    if ind and px(ind["ti"]) <= 0:
        WARN.append("正文段落未首行缩进（ti=%s）" % ind["ti"])
    elif ind:
        print("  ✓ 正文首行缩进 %s" % ind["ti"])

    css = open(os.path.join(ROOT, "kb", "texts.html"), encoding="utf-8").read()
    if re.search(r"\.st-cover\s*\{[^}]*page-break-after", css):
        print("  ✓ 打印分页（封面/目次独立成页）")
    else:
        FAIL.append("打印样式缺 .st-cover 分页规则")

    try:
        os.remove(os.path.join(ROOT, "kb", "_probe.html"))
    except OSError:
        pass
    httpd.shutdown()
    print()
    for w in WARN:
        print("  警告：" + w)
    if FAIL:
        print("失败 %d：" % len(FAIL))
        for f in FAIL:
            print("  ✗ " + f)
        sys.exit(1)
    print("标准阅读页版式自检通过")


if __name__ == "__main__":
    main()
