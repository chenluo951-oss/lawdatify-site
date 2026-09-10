#!/usr/bin/env python3
"""生成「法律分析」索引页。

文章正文是手写的 HTML（含 SVG 图示），本脚本只负责：
  1. 从 sources/analysis/registry.json 读取文章清单，渲染卡片式索引
  2. 保留"在研选题"区，说明后续研究方向

为什么要做成注册表驱动：新增一篇专题时，只需往 registry.json 加一条记录
再跑本脚本，索引页自动更新，不必手工改 HTML——否则索引页迟早会和实际文章脱节。

用法：
    python3 build_analysis.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "sources", "analysis", "registry.json")

DOMAIN_TONE = {
    "产品与食安合规": "#b3541e",
    "数据合规": "#1b4f8a",
    "AI 合规": "#0f7b6c",
    "算法合规": "#7d5ba6",
    "平台合规": "#0f6e8c",
    "价格合规": "#a3352c",
}


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def main():
    reg = json.load(open(REG, encoding="utf-8"))
    arts = reg.get("articles", [])
    pipe = reg.get("pipeline", [])

    cards = []
    for a in arts:
        tone = DOMAIN_TONE.get(a.get("domain", ""), "#1b4f8a")
        tags = "".join(f'<span class="chip">{esc(t)}</span>' for t in a.get("tags", []))
        cards.append(f"""    <div class="topic-card">
      <h4><a href="{esc(a['slug'])}.html">{esc(a['title'])}</a></h4>
      <div class="tc-meta"><span style="color:{tone};font-weight:700">{esc(a.get('domain',''))}</span>
        · {esc(a.get('date',''))} · {esc(a.get('minutes',''))} · {a.get('figs', 0)} 张图示</div>
      <p>{esc(a.get('summary',''))}</p>
      <div class="tc-foot">{tags}<span class="tc-go"><a href="{esc(a['slug'])}.html">阅读全文 →</a></span></div>
    </div>""")

    rows = [f"""    <div class="item">
      <h4>{esc(p.get('title',''))}</h4>
      <div class="meta">{esc(p.get('status','在研'))}</div>
      <p>{esc(p.get('desc',''))}</p>
    </div>""" for p in pipe]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>法律分析 · 合规无终点</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>

<nav class="topnav"><div class="inner">
  <a class="brand" href="../index.html">law<span>datify</span></a>
  <div class="navlinks">
    <a href="../index.html">首页</a>
    <a href="../updates/index.html">今日更新</a>
    <a href="../radar/index.html">监管雷达</a>
    <a href="../news/index.html">合规资讯</a>
    <a href="../analysis/index.html" class="active">法律分析</a>
    <a href="../kb/index.html">合规知识库</a>
    <a href="../about.html">关于</a>
  </div>
</div></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / 法律分析</div>
  <h1>法律分析</h1>
  <p>围绕合规实务场景的专题研究：结论先行、逐条附官方原文深链、配产品级合规图示，可直接用于内部沟通与落地改造。</p>
</div></div>

<div class="wrap">
  <div class="section-title"><span class="bar"></span>专题研究</div>
  <p class="lead">每篇均标注依据文件、成稿日期与图示数量；正文中的全部外链均为发布机构官网具体页面，发布前逐条实测可达。</p>
  <div class="card-grid-2">
{chr(10).join(cards)}
  </div>

  <div class="section-title" style="margin-top:36px"><span class="bar"></span>在研选题</div>
  <div class="list">
{chr(10).join(rows)}
  </div>
</div>

<footer><div class="inner">
  <div class="foot-brand">law<span>datify</span> · 合规无终点</div>
  <div class="foot-desc">由个人独立维护 · 内容基于监管机构官网公开信息整理，逐条附原文深链</div>
</div></footer>
</body>
</html>
"""

    outdir = os.path.join(HERE, "analysis")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "index.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"已生成 analysis/index.html（专题 {len(arts)} 篇 / 在研 {len(pipe)} 项）")

    for s in ("unify_chrome.py", "inject_meta.py"):
        p = os.path.join(HERE, s)
        if os.path.exists(p):
            os.system(f'/usr/bin/python3 "{p}" >/dev/null 2>&1')


if __name__ == "__main__":
    main()
