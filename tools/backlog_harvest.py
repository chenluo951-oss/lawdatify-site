#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量处罚公示采集编排器（一次性 / 手工触发）。

背景
----
每日自动化里的采集是**增量**的（只抓新链接），存量（已收录但解析规则改进前的旧正文）
不会自动刷新。本脚本把「存量重刷」串成一步，并可选择扩域。

硬约束（踩过的坑）
----------------
· **必须串行**：出口 IP 是同一个，两个采集器并行会互相把对方打成空页（跨站频控）。
  所以第一步先等 `daily_build.py` 退出。
· `--full` 是「重新遍历全部页」，**不是清空重建**；`--refresh` 才会连已收录链接一起重解析。
· 附件下载最慢，先 `--no-attach` 重刷正文，再用 `attach_backfill.py` 单独补附件，
  它的缓存让同 URL 的多条记录只下一次。

用法
----
    python3 tools/backlog_harvest.py --wait-daily            # 等每日构建结束后跑存量
    python3 tools/backlog_harvest.py --skip-wait --attach-limit 400
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = "/Users/luochen/.workbuddy/binaries/python/envs/default/bin/python"
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
LOG = os.path.join(ROOT, "_qa", "backlog_harvest.log")


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def running(pattern):
    r = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True)
    for ln in (r.stdout or "").splitlines():
        if pattern in ln and "backlog_harvest" not in ln and "grep" not in ln:
            return True
    return False


def wait_daily(limit_min=240):
    t0 = time.time()
    log("⏳ 等待 daily_build.py 退出（避免两个采集器撞同一出口 IP）…")
    while running("tools/daily_build.py"):
        if time.time() - t0 > limit_min * 60:
            log("⚠ 等待超时 %d 分钟，放弃等待，继续执行" % limit_min)
            return
        time.sleep(30)
    log("✓ daily_build 已退出（等了 %.1f 分钟）" % ((time.time() - t0) / 60))


def run(label, cmd, timeout=None):
    log("▶ %s　$ %s" % (label, " ".join(cmd[1:])))
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    for x in [y for y in out.strip().splitlines() if y.strip()][-25:]:
        log("    " + x[:200])
    log("%s %s　退出码 %d　%.1fs" % ("✓" if r.returncode == 0 else "✗", label,
                                     r.returncode, time.time() - t0))
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-daily", action="store_true")
    ap.add_argument("--skip-wait", action="store_true")
    ap.add_argument("--skip-discover", action="store_true")
    ap.add_argument("--skip-amr", action="store_true")
    ap.add_argument("--attach-limit", type=int, default=600)
    a = ap.parse_args()

    log("=" * 60)
    log("存量采集开始")
    if a.wait_daily and not a.skip_wait:
        wait_daily()

    if not a.skip_discover:
        # 其他执法领域（生态环境/交通/药监/知识产权…）的处罚公示栏目探测。
        # 只探测不写入 SITES —— 结果需要人看过标题样本再决定接不接。
        run("其他领域·栏目探测",
            [PY, "tools/discover_penalty_cols.py", "--group", "other", "--workers", "5"])

    if not a.skip_amr:
        # 市监 9 站存量重刷：--full 重遍历全部页 + --refresh 连已收录链接一起重解析。
        # 先关附件（慢），附件交给下一步。
        run("市监·存量重刷",
            [PY, "tools/harvest_local_amr.py", "--full", "--refresh", "--no-attach"],
            timeout=7200)

    if a.attach_limit:
        run("案例·文书附件回填",
            [PY, "tools/attach_backfill.py", "--limit", str(a.attach_limit)],
            timeout=10800)

    log("存量采集结束")


if __name__ == "__main__":
    main()
