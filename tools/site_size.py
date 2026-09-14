#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
site_size.py —— 站点容量体检与外部化预警。

背景（用户 2026-09-14 提问）
--------------------------
「公众号内容是非常重要的来源，如果后续 GitHub 网页资源不够了怎么办」
先说结论：**公众号原文存档不是容量风险**。实测单篇存档约 6 KB（JSON）+ 约 8 KB（渲染片段），
而标准原版 PDF 平均 1.2 MB/部。两者差三个数量级：现有 305 MB 已发布体积里，PDF 占 91%，
公众号存档即使做到 1 万篇也只占 60 MB 左右。

但站点确实有硬上限，所以要有一条**可量化的红线**与**明确的处置预案**：

GitHub Pages / 仓库的限制（官方口径）
  · 已发布的站点内容 ≤ 1 GB（软限，超过后构建开始告警甚至失败）
  · 单文件 ≤ 100 MB（GitHub 硬限，超过直接拒绝 push）
  · 仓库推荐 ≤ 1 GB、硬限 5 GB
  · 软带宽 100 GB/月（PDF 是主要消耗者：34 MB 的 PDF 被下载 3000 次即用满）

本工具的职责
------------
  1. 用 `git ls-files` 统计**真正会发布到 Pages 的体积**（gitignored 的语料库不计）；
  2. 按目录 / 文件类型拆解，指出体积大头；
  3. 对照红线给余量与「还能容纳多少篇公众号存档 / 多少部 PDF」的估算；
  4. 列出外部化候选（单文件 > 阈值，或合计占比过高的目录）。

退出码：0 = 正常；1 = 已越红线（供编排脚本告警）。
"""
import os, sys, json, subprocess, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# GitHub Pages / 仓库限制（MB）
SITE_SOFT_LIMIT = 1024
SITE_WARN = int(SITE_SOFT_LIMIT * 0.70)      # 70% 起预警
SITE_CRIT = int(SITE_SOFT_LIMIT * 0.85)      # 85% 起须启动外部化
FILE_HARD_LIMIT = 100                        # 单文件硬限
BIG_FILE = 5                                 # 外部化候选阈值

# 单篇公众号存档的实测体积（KB）：JSON + 渲染片段 + 分片摊销
WX_PER_ITEM_KB = 12   # 实测：单篇 html+text 约 11.6 KB，含目录摊销
# 标准原版 PDF 的平均体积（MB）
PDF_PER_ITEM_MB = 1.2


def tracked_files():
    """git ls-files -z：非 ASCII 文件名默认会被引号转义，必须用 NUL 分隔读取。"""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        print("！不是 git 仓库或 git 不可用，改用全目录扫描（含 gitignored 文件，会偏大）")
        return None
    return [x for x in out.stdout.split("\0") if x.strip()]


def scan(paths=None):
    files = []
    if paths is None:
        for dp, _, fs in os.walk(ROOT):
            if "/.git" in dp or dp.endswith("/.git"):
                continue
            for f in fs:
                p = os.path.join(dp, f)
                files.append((os.path.relpath(p, ROOT), os.path.getsize(p)))
    else:
        for rel in paths:
            p = os.path.join(ROOT, rel)
            if os.path.isfile(p):
                files.append((rel, os.path.getsize(p)))
    return files


def mb(n):
    return n / 1024 / 1024


def main():
    as_json = "--json" in sys.argv
    paths = tracked_files()
    files = scan(paths)
    total = sum(s for _, s in files)

    by_dir = collections.defaultdict(int)
    by_ext = collections.defaultdict(int)
    for rel, s in files:
        top = rel.split("/")[0] if "/" in rel else "(根目录)"
        if rel.startswith("kb/std/"):
            top = "kb/std（标准原版 PDF）"
        elif rel.startswith("kb/"):
            top = "kb（其余知识库页面）"
        elif rel.startswith("sources/"):
            top = "sources（数据与存档）"
        by_dir[top] += s
        ext = os.path.splitext(rel)[1].lower() or "(无扩展名)"
        by_ext[ext] += s

    big = sorted([(rel, s) for rel, s in files if mb(s) >= BIG_FILE],
                 key=lambda x: -x[1])
    over_hard = [(r, s) for r, s in files if mb(s) > FILE_HARD_LIMIT]

    # .git 体积（仓库推荐上限参考，不影响 Pages 发布体积）
    gitdir = os.path.join(ROOT, ".git")
    gitsize = 0
    for dp, _, fs in os.walk(gitdir):
        for f in fs:
            try:
                gitsize += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass

    remain = SITE_SOFT_LIMIT - mb(total)
    wx_cap = int(remain * 1024 / WX_PER_ITEM_KB)
    pdf_cap = int(remain / PDF_PER_ITEM_MB)
    pct = mb(total) / SITE_SOFT_LIMIT * 100

    if as_json:
        print(json.dumps({
            "tracked_files": len(files), "bytes": total, "mb": round(mb(total), 1),
            "pct_of_limit": round(pct, 1), "remain_mb": round(remain, 1),
            "warn": SITE_WARN, "crit": SITE_CRIT,
            "by_dir_mb": {k: round(mb(v), 1) for k, v in sorted(by_dir.items(), key=lambda x: -x[1])},
            "big_files": [{"path": r, "mb": round(mb(s), 1)} for r, s in big],
            "over_hard_limit": [r for r, _ in over_hard],
            "git_dir_mb": round(mb(gitsize), 1),
            "wx_capacity_items": wx_cap, "pdf_capacity_items": pdf_cap,
            "status": "crit" if mb(total) >= SITE_CRIT else ("warn" if mb(total) >= SITE_WARN else "ok"),
        }, ensure_ascii=False, indent=1))
        return 0 if mb(total) < SITE_CRIT else 1

    print(f"站点容量体检（已发布体积 = git 跟踪文件；Pages 软限 {SITE_SOFT_LIMIT} MB）")
    print("─" * 62)
    print(f"  已发布文件      {len(files)} 个　合计 {mb(total):.1f} MB"
          f"　占上限 {pct:.1f}%")
    print(f"  预警线 {SITE_WARN} MB　红线 {SITE_CRIT} MB　余量 {remain:.1f} MB")
    bar = "█" * int(pct / 2.5) + "░" * (40 - int(pct / 2.5))
    print(f"  [{bar}] {pct:.0f}%")
    print()
    print("  体积构成（Top）")
    for k, v in sorted(by_dir.items(), key=lambda x: -x[1])[:8]:
        print(f"    {k:<26} {mb(v):>8.1f} MB　{v/total*100:>5.1f}%")
    print()
    print("  文件类型")
    for k, v in sorted(by_ext.items(), key=lambda x: -x[1])[:6]:
        n = sum(1 for r, _ in files if os.path.splitext(r)[1].lower() == k)
        print(f"    {k:<12} {n:>4} 个　{mb(v):>8.1f} MB")
    print()
    if big:
        print(f"  外部化候选（单文件 ≥ {BIG_FILE} MB，共 {len(big)} 个 / {mb(sum(s for _, s in big)):.1f} MB）")
        for r, s in big[:8]:
            print(f"    {mb(s):>7.1f} MB  {r}")
        if len(big) > 8:
            print(f"    …另有 {len(big)-8} 个")
        print()
    print("  容量余量换算")
    print(f"    公众号原文存档（实测 {WX_PER_ITEM_KB} KB/篇）  还可容纳约 {wx_cap:,} 篇")
    print(f"    标准原版 PDF（均 {PDF_PER_ITEM_MB} MB/部）     还可容纳约 {pdf_cap:,} 部")
    print()
    print(f"  .git 目录      {mb(gitsize):.1f} MB（仓库推荐 ≤1024 MB，硬限 5120 MB）")

    status = "ok"
    if mb(total) >= SITE_CRIT:
        status = "crit"
    elif mb(total) >= SITE_WARN:
        status = "warn"
    print()
    if over_hard:
        print(f"  ✗ 有 {len(over_hard)} 个文件超过 GitHub 单文件硬限 {FILE_HARD_LIMIT} MB：")
        for r, s in over_hard:
            print(f"      {mb(s):.1f} MB  {r}")
    if status == "ok":
        print(f"  ✓ 正常：距红色预警线还有 {SITE_CRIT - mb(total):.1f} MB")
    elif status == "warn":
        print(f"  △ 预警：已达 {pct:.0f}%，建议开始外部化大体积 PDF（见 about 页容量说明）")
    else:
        print(f"  ✗ 越线：已达 {pct:.0f}%，必须启动 PDF 外部化，否则 Pages 构建会失败")
    return 0 if status != "crit" else 1


if __name__ == "__main__":
    sys.exit(main())
