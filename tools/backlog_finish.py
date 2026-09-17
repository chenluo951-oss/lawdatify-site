#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量采集收尾编排（一次性 / 手工触发）。

为什么单独一步
--------------
`harvest_local_amr.py --full --refresh` 跑完 9 站要点几十分钟，人不可能一直守着。
但「采集完 → 补文书附件 → 重建案例页 → 门禁 → 上线」必须**串行**且**不能漏**：
  · 串行：出口 IP 只有一个，两个采集器并行会互相把对方打成空页（跨站频控，见 MEMORY）。
  · 不能漏：`--no-attach` 采回来的记录正文来自网页壳，泸州这类站点内容全在 .docx/.pdf
    附件里，不跑 attach_backfill 就等于白采。

用法
----
    python3 tools/backlog_finish.py              # 等采集结束 → 回填 → 重建 → 上线
    python3 tools/backlog_finish.py --skip-wait  # 采集已结束，直接回填
    python3 tools/backlog_finish.py --no-push    # 只重建不上线（本地看效果）
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = "/Users/luochen/.workbuddy/binaries/python/envs/default/bin/python"
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
LOG = os.path.join(ROOT, "_qa", "backlog_finish.log")


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def running(pattern):
    """进程是否在跑。

    ⚠️ 必须排掉 `zsh -c …` / `bash -c …` 包装进程与脚本自身：包装进程的命令行里
    整段包含被执行的脚本路径，只按子串匹配会把包装进程当目标，导致永远判定「还在跑」。
    """
    r = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True)
    for ln in (r.stdout or "").splitlines():
        if pattern not in ln:
            continue
        if "zsh -c" in ln or "bash -c" in ln or "backlog_finish" in ln or "grep" in ln:
            continue
        return True
    return False


def run(label, cmd, timeout=None):
    """跑一步子命令，**输出实时追加到日志**。

    ⚠️ 别用 `subprocess.run(capture_output=True)`：附件回填要跑几十分钟，
    输出被缓冲住 → 日志里只有「▶ 步骤名」一行，接下来完全看不到进度，
    无法判断是在跑还是死了（这个坑在采集器上已经踩过一次）。
    """
    log("▶ %s　$ %s" % (label, " ".join(cmd[1:])))
    t0 = time.time()
    try:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    except OSError as e:
        log("✗ %s　启动失败：%s" % (label, e))
        return False
    tail = []
    with p.stdout as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            log("    " + line[:200])
            tail.append(line)
            if len(tail) > 200:
                tail.pop(0)
            if timeout and time.time() - t0 > timeout:
                p.kill()
                log("✗ %s　超时 %ss，已终止" % (label, timeout))
                return False
    p.wait()
    log("%s %s　退出码 %d　%.1fs" % ("✓" if p.returncode == 0 else "✗", label,
                                     p.returncode, time.time() - t0))
    return p.returncode == 0


def wait_harvest(limit_min=300):
    t0 = time.time()
    log("⏳ 等待 harvest_local_amr.py 退出（同一出口 IP，必须串行）…")
    while running("tools/harvest_local_amr.py"):
        if time.time() - t0 > limit_min * 60:
            log("⚠ 等待超时 %d 分钟，仍继续往下走（可能采到一半）" % limit_min)
            return
        time.sleep(30)
    log("✓ 采集已退出（等了 %.1f 分钟）" % ((time.time() - t0) / 60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-wait", action="store_true")
    ap.add_argument("--attach-limit", type=int, default=900)
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()

    log("=" * 60)
    log("存量采集收尾开始")
    if not a.skip_wait:
        wait_harvest()

    if a.attach_limit:
        # 附件最慢（每页要下载 .docx/.pdf 再按魔数解析），但泸州这类站点正文只在附件里，
        # 不跑等于白采。缓存让同 URL 的多条记录只下一次。
        run("案例·文书附件回填",
            [PY, "tools/attach_backfill.py", "--limit", str(a.attach_limit)],
            timeout=10800)

    # 重建链顺序不可乱（与 MEMORY 记录的案例库构建链一致）：
    # 案例页 → 元数据 → 子导航 → 统一外壳 → 门禁。
    for label, cmd in [
        ("重建案例库页面", [PY, "tools/build_cases_page.py"]),
        ("刷新元数据", [PY, "inject_meta.py"]),
        ("刷新子导航", [PY, "inject_subnav.py"]),
        ("统一外壳", [PY, "unify_chrome.py"]),
    ]:
        run(label, cmd, timeout=1800)

    ok = run("上线前门禁", [PY, "preflight.py"], timeout=1800)
    if not ok:
        log("⚠ 门禁有阻断项，停止推送（先修再上）")
        log("存量采集收尾结束（未推送）")
        return

    if a.no_push:
        log("（--no-push）跳過推送")
    else:
        run("推送上线", [PY, "push_via_api.py"], timeout=3600)

    log("存量采集收尾结束")


if __name__ == "__main__":
    main()
