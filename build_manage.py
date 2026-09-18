#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「合规管理」模块总览页 manage/index.html

2026-09-17（用户要求）：把「合规审计」从「合规知识库」里拿出来，单独成立一级模块
「合规管理」。模块边界按「问的问题不同」划：

  合规知识库 —— 规则**是什么**（法条、标准、原文、义务清单、案例）· 长期稳定
  合规管理   —— 我们**怎么把规则落下去**（审计范围、审计记录、报告与整改）· 工具
  合规动态   —— 外面**发生了什么 / 要做什么**（事件流、应对建议）· 日更

审计工具本身在 manage/audit.html（由 build_audit.py 生成）；本页只做模块入口与定位说明。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DUTY_SRC = os.path.join(HERE, "sources", "standards", "duties.json")
OUT = os.path.join(HERE, "manage", "index.html")


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def duty_stats():
    try:
        d = json.load(open(DUTY_SRC, encoding="utf-8"))
    except Exception:
        return 0, 0, 0
    cats = d.get("categories", [])
    n_scene = sum(len(c.get("scenes", [])) for c in cats)
    n_duty = sum(len(s.get("duties", [])) for c in cats for s in c.get("scenes", []))
    return len(cats), n_scene, n_duty


def main():
    n_cat, n_scene, n_duty = duty_stats()

    body = f"""
  <p class="lead">把义务清单变成可勾选的审计范围，把审计过程变成可追溯的记录，
  把结论变成可派发的整改任务。规则本身见
  <a href="../kb/index.html">合规知识库</a>，外面发生了什么见
  <a href="../news/index.html">合规动态</a>。</p>

  <div class="lb-split">
    <a class="dcard lb-entry" href="audit.html" style="--dc:#0f766e">
      <b>&#128451; 合规审计</b>
      <span>审计范围直接取自合规义务清单（{n_cat} 个主题大类 / {n_scene} 个业务场景 /
      {n_duty} 项具体义务）：勾选范围 → 生成审计任务 → 逐项记录进度、审计素材与审计结论 →
      一键输出审计报告与整改任务清单（可打印 / 存 PDF、导出 HTML 与 JSON）。
      数据保存在本机浏览器，不上传、不外发。</span>
      <span class="more">开始审计 →</span>
    </a>
  </div>

  <div class="section-title"><span class="bar"></span>怎么用</div>
  <div class="notice">
    <b>① 选范围</b>　按主题大类或业务场景勾选本次要审的义务项，范围可复用、可导出。
    <br><b>② 留痕迹</b>　每一项都记录「进度 / 审计素材 / 审计结论 / 说明」，素材写清制度名、
    系统入口、日志路径或访谈对象——审计的价值在证据链，不在结论本身。
    <br><b>③ 出结果</b>　不符合项自动汇总为整改任务清单（责任人 + 期限 + 措施），
    并连同覆盖范围与结论分布一起出一份审计报告。
  </div>

  <div class="section-title"><span class="bar"></span>三个模块怎么分</div>
  <div class="lb-bound">
    <div class="lb-bd">
      <div class="lb-bd-h"><b>合规管理</b><span class="lb-tag t-long">工具 · 按需使用</span></div>
      <p>回答「我们怎么把规则落下去」：审计范围、审计记录、结论与整改。
      本模块当前提供合规审计工具，其余管理动作（制度库、台账、培训记录）按需再增。</p>
      <span class="lb-here">当前位置</span>
    </div>
    <div class="lb-bd">
      <div class="lb-bd-h"><b>合规知识库</b><span class="lb-tag t-long">长期稳定</span></div>
      <p>回答「规则本身是什么」：法规与标准原文、义务清单、高频引用法条、监管案例。</p>
      <a href="../kb/index.html">进入合规知识库 →</a>
    </div>
    <div class="lb-bd">
      <div class="lb-bd-h"><b>合规动态</b><span class="lb-tag t-future">每日更新</span></div>
      <p>回答「外面发生了什么、我们要做什么」：监管事件流、立法日程、应对建议、全球态势。</p>
      <a href="../news/index.html">进入合规动态 →</a>
    </div>
  </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>合规管理 · 合规无终点</title>
<meta name="description" content="合规管理：把合规义务落成可执行动作——审计范围勾选、审计过程记录、审计报告与整改任务清单输出。">
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / 合规管理</div>
  <h1>合规管理</h1>
  <p>把合规要求落成可执行的动作：审计范围怎么定、过程怎么留痕、结论怎么变成整改任务。</p>
</div></div>
<!-- SUBNAV:START --><!-- SUBNAV:END -->

<main class="wrap">
{body}
</main>

<footer></footer>
</body>
</html>
"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"  manage/index.html    {len(html)} B  ✓  （合规管理总览）")


if __name__ == "__main__":
    main()
