#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全站每日重建编排器 —— 一句话把站点所有模块刷到最新。

为什么需要它
------------
站点模块多、依赖顺序有硬约束（踩过坑）：
  · build_std_texts → build_std_pdf → build_texts（顺序颠倒会把新目录并进旧目录）；
  · build_topics 会把全站页脚「数据更新至」重设为**最新资讯期次**，
    因此它之后必须再跑一次 unify_chrome 才会刷回今天（否则页脚悄悄回退到往期并上线）；
  · build_topics / build_radar / gen_briefs 等会整体重写页面，冲掉统一导航与 OG 标签，
    所以 inject_subnav / unify_chrome / inject_meta 必须排在所有页面生成脚本之后。
把顺序固化成脚本，避免每次靠记忆拼命令。

覆盖模块
--------
今日更新 / 合规动态（立法日历·应对建议·全球地图，由合规资讯与监管雷达合并）/ 法律分析 /
合规知识库（条目库·义务矩阵·原文入口·高频法条·合规审计·公众号原文）/ 首页（合规动态总览+可视化）/ 搜索索引。

用法
----
    python3 tools/daily_build.py                 # 每日增量（含数据同步，不含重量级 PDF 重建）
    python3 tools/daily_build.py --no-network    # 只重建页面，不联网抓取
    python3 tools/daily_build.py --with-texts    # 新归档了标准正文时才加，会重生成原版 PDF
    python3 tools/daily_build.py --skip-build    # 只跑数据同步
"""

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

VENV_PY = "/Users/luochen/.workbuddy/binaries/python/envs/default/bin/python"
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable

# (标签, 命令, 是否关键)  —— 关键步骤失败即中止，非关键失败只告警继续
STEPS = [
    # ---------- 1. 数据同步（独立于本地简报的站点自有数据源）----------
    ("草案跟踪",        [PY, "fetch_drafts.py"],                     False),
    ("原文抓取·每日",   [PY, "harvest.py", "--run", "--daily", "--limit", "60"], False),
    ("私有库同步",      [PY, "harvest.py", "--sync"],               False),
    # 法规库全量（国家法律法规数据库）—— 首次较慢，之后增量很快
    ("法规全量·flk",    [PY, "tools/harvest_flk_bulk.py"],          False),
    # 标准门户批量检索（全国标准信息公共服务平台 + 行业标准信息服务平台）
    ("标准门户·检索",   [PY, "tools/harvest_std_portals.py"],       False),
    # 两个专项合规：移动应用违规通报历史库 + 算法/大模型备案库
    # ⚠️ 省局栏目发现必须排在 App 通报采集之前——它产出 sources/appviol/prov_columns.json
    # （28 个省通信管理局的通报栏目路径与文书清单）；省局栏目路径不统一且会调整，
    # 每天重扫一次才能跟上，否则新增省份/改名栏目会静默漏采。
    ("专项·省局栏目发现", [PY, "tools/prov_ca_discover.py"],           False),
    ("专项·App违规通报", [PY, "tools/harvest_app_violations.py"],    False),
    # ⚠️ 必须紧跟 App 通报采集：省局列表接口不返回发布日期，新采的文书 date 为空，
    # 而「按年统计通报量」是治理分析的地基 → 立刻从页面 PubDate 回填（带缓存，增量很快）。
    ("专项·发布日期回填", [PY, "tools/backfill_appviol_dates.py"],    False),
    ("专项·算法备案",   [PY, "tools/harvest_algo_filing.py"],       False),
    # 地市监局官网「行政处罚公示」—— 案例库的一手来源。
    # ⚠️ 必须排在「合规案例库」之前：它产出 sources/cases/local_amr.jsonl，
    # harvest_cases.py 会把它并入 cases.json（含「一条公开表 = N 个案件」的拆分结果）。
    ("地市监处罚公示",  [PY, "tools/harvest_local_amr.py"],          False),
    ("合规案例库",      [PY, "tools/harvest_cases.py"],             False),
    # 公示页的**文书附件**（Word / PDF / Excel）：相当多地市局的处罚公示页正文是空壳，
    # 事实/依据/罚款只在附件里（见 tools/case_attach.py）。新采的记录已随采集解析，
    # 这一步补的是「历史存量 + 上级机关那些带附件的外链页」。
    # ⚠️ 加 --limit：单条要下 1～3 个附件，不限量会把每日构建拖长；漏掉的次日再补。
    ("案例文书附件",    [PY, "tools/attach_backfill.py", "--limit", "80"], False),
    ("台账并库",        [PY, "merge_ledgers.py"],                   False),
    ("法规标准条目库",  [PY, "build_library_data.py"],              False),
    ("语料合并",        [PY, "merge_corpus.py"],                    False),
    ("义务逐字抽取",    [PY, "enrich_duties.py"],                   False),
    # ---------- 2. 页面生成（顺序敏感）----------
    # ⚠️ 站内原文页必须排在「知识库」之前：build_texts 产出 sources/standards/text_ids.json
    # （条目 → 原文 id 映射），build_standards 靠它给条目挂「读原文」按钮。
    # 排在后面的话按钮永远指向上一版索引——表现为「刚补的原文，库上看不到入口」。
    ("站内原文页",      [PY, "build_texts.py"],                     False),
    ("知识库·义务矩阵", [PY, "build_standards.py"],                 True),
    ("知识库·案例库",   [PY, "tools/build_cases_page.py"],          False),
    # ⚠️ 治理分析必须排在专项合规页之前：它产出 sources/appviol/analytics.json
    # （机构×年度矩阵、治理动作年度构成、再犯分析、执法强度），页面直接消费该文件。
    ("专项·治理分析",   [PY, "tools/appviol_analytics.py"],         False),
    ("专项合规页",      [PY, "tools/build_special_topics.py"],      False),
    ("高频法条",        [PY, "build_citations.py"],                  False),
    ("合规审计",        [PY, "build_audit.py"],                      False),
    ("监管雷达",        [PY, "build_radar.py"],                      True),
    ("法律分析",        [PY, "build_analysis.py"],                   False),
    # 公众号原文存档 → kb/wx.html + sources/wx/replaces.json
    # 必须在 build_topics 之前：build_topics 读 replaces.json 把二手来源链接改指站内存档
    ("公众号原文存档",  [PY, "tools/build_wx_archive.py"],           False),
    ("合规资讯·首页",   [PY, "build_topics.py"],                     True),
    ("今日更新",        [PY, "build_updates.py"],                    True),
    ("搜索索引",        [PY, "build_search.py"],                     False),
    # 大文件切片：Git Data API 建 blob 对单文件体积敏感（>6MB 会失败），
    # 必须排在 build_standards（产出 library-data.js）与 build_search（产出索引）之后。
    ("大文件切片",      [PY, "tools/split_big_assets.py"],          False),
    # ---------- 3. 统一外壳与自检（必须最后）----------
    ("首页（合规动态·可视化）", [PY, "build_home.py"],                True),
    ("模块子导航",      [PY, "inject_subnav.py"],                    False),
    ("全站导航页脚",    [PY, "unify_chrome.py"],                     True),
    ("OG 元数据",       [PY, "inject_meta.py"],                      True),
    ("站点体积体检",    [PY, "tools/site_size.py"],                  False),
    ("构建前护栏",      [PY, "preflight.py"],                        False),
]

# 仅当 --with-texts（新归档了标准正文）时才跑，避免无谓重生成 290MB PDF
TEXT_STEPS = [
    ("标准正文库",      [PY, "build_std_texts.py"]),
    ("标准原版 PDF",    [PY, "build_std_pdf.py"]),
]


def run(label, cmd, timeout=1800):
    t0 = time.time()
    print(f"\n▶ {label}　$ {' '.join(cmd[1:])}")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        print(f"  ✗ 超时（>{timeout}s）")
        return False, time.time() - t0
    lines = [x for x in out.strip().splitlines() if x.strip()]
    for x in lines[-12:]:
        print("    " + x[:190])
    ok = r.returncode == 0
    print(f"  {'✓' if ok else '✗'} {label} 退出码 {r.returncode}　{time.time() - t0:.1f}s")
    return ok, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-network", action="store_true", help="跳过 fetch_drafts / harvest")
    ap.add_argument("--with-texts", action="store_true", help="含标准正文库与原版 PDF 重建")
    ap.add_argument("--skip-build", action="store_true", help="只跑数据同步")
    a = ap.parse_args()

    net_labels = {"草案跟踪", "原文抓取·每日", "私有库同步", "法规全量·flk",
                  "标准门户·检索", "专项·省局栏目发现", "专项·App违规通报",
                  "专项·发布日期回填", "专项·算法备案", "地市监处罚公示", "合规案例库",
                  "案例文书附件"}
    steps = [s for s in STEPS if not (a.no_network and s[0] in net_labels)]
    if a.skip_build:
        steps = [s for s in steps if s[0] in
                 {"草案跟踪", "原文抓取·每日", "私有库同步", "法规全量·flk",
                  "标准门户·检索", "专项·App违规通报", "专项·算法备案",
                  "地市监处罚公示", "合规案例库",
                  "台账并库", "法规标准条目库", "语料合并", "义务逐字抽取"}]
    if a.with_texts:
        idx = [i for i, s in enumerate(steps) if s[0] == "法规标准条目库"]
        pos = (idx[0] + 1) if idx else 1
        steps = steps[:pos] + [(l, c, False) for l, c in TEXT_STEPS] + steps[pos:]

    print(f"全站每日重建：{len(steps)} 步　python={PY}　{'含' if a.with_texts else '不含'} PDF 重建")
    t0 = time.time()
    failed, warned = [], []
    for label, cmd, critical in steps:
        ok, _ = run(label, cmd)
        if not ok:
            if critical:
                failed.append(label)
                print(f"\n× 关键步骤「{label}」失败，中止（避免把半成品推上线）")
                break
            warned.append(label)
    print(f"\n==== 编排完成：{time.time() - t0:.0f}s　"
          f"告警 {len(warned)} 项{'（' + '、'.join(warned) + '）' if warned else ''} ====")
    if failed:
        sys.exit(1)
    print("下一步：核对 git diff，有实质变更再 commit + push（无变更不推送，省构建额度）")


if __name__ == "__main__":
    main()
