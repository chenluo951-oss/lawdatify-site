#!/bin/sh
# queue_difang.sh —— 地方法规官方全文抓取的**守护壳**（2026-09-17）
#
# 为什么需要它：
#   1. `harvest_flk_texts.py` 本身按 bbbs 断点续跑，单次跑不完没关系——但本机环境会
#      在会话/轮次结束时**回收长跑子进程**（2026-09-17 实测：PID 59720 跑 25 分钟后消失）。
#      所以需要一层壳：被回收/异常退出后自动再起一轮，直到没有待抓条目。
#   2. 绝不能加并发。flk 前置腾讯云 WAF 有一次性 cookie 挑战，`--workers > 1` 会直接
#      触发 JS 挑战（302 循环）。这里固定单线程 `--sleep 0.8`。
#
# ⚠️ 本脚本所有日志一律**纯 ASCII**。2026-09-17 首版用中文写日志，
#    实测 /bin/sh 落盘时多字节字符会错位（读出来是乱码），排查时没法看。
#    脚本内任何面向日志/终端的文案都不要用中文。
#
# 日志：/tmp/difang.log（各轮抓取明细汇总）/ tmp/difang_round.log（本轮明细）
#       logs/difang_supervisor.log（轮次记录，ASCII）
#
# 停止条件：① 脚本报「没有待抓条目。」；② 连续 3 轮 jsonl 无新增（疑似被 WAF 拦住，
#          要人工看一眼，不要盲目重试把 IP 打进小黑屋）。
#
# 启动方式（脱离会话进程组，避免被回收）：
#   /Users/luochen/.workbuddy/binaries/python/envs/default/bin/python -c \
#     "import subprocess;subprocess.Popen(['/bin/sh','tools/queue_difang.sh'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=open('/tmp/difang_sup.log','a'),stderr=subprocess.STDOUT)"

SITE="/Users/luochen/WorkBuddy/Claw/lawdatify-site"
PY="/Users/luochen/.workbuddy/binaries/python/envs/default/bin/python"
ROUND_LOG="/tmp/difang_round.log"
MAIN_LOG="/tmp/difang.log"
SUP_LOG="$SITE/logs/difang_supervisor.log"
JSONL="$SITE/sources/flk_texts/texts.jsonl"

cd "$SITE" || exit 1
mkdir -p "$SITE/logs"

count_jsonl() { wc -l < "$JSONL" 2>/dev/null | tr -d ' \t'; }

prev=$(count_jsonl)
echo "[$(date '+%F %T')] supervisor start, jsonl=$prev" >> "$SUP_LOG"

i=0
stale=0
while [ "$i" -lt 500 ]; do
    i=$((i + 1))
    echo "[$(date '+%F %T')] round $i begin (jsonl=$prev)" >> "$SUP_LOG"

    # -u 不缓冲；单线程；不 --fresh（--fresh 会把已抓的 texts.jsonl 备份掉重头来）
    "$PY" -u tools/harvest_flk_texts.py --kinds 地方法规 --sleep 0.8 > "$ROUND_LOG" 2>&1
    rc=$?
    cat "$ROUND_LOG" >> "$MAIN_LOG"

    now=$(count_jsonl)
    echo "[$(date '+%F %T')] round $i end rc=$rc jsonl=$prev->$now" >> "$SUP_LOG"

    if grep -q "没有待抓条目。" "$ROUND_LOG"; then
        echo "[$(date '+%F %T')] no todo left, supervisor exits normally" >> "$SUP_LOG"
        break
    fi

    if [ "$now" -le "$prev" ]; then
        stale=$((stale + 1))
        echo "[$(date '+%F %T')] no progress (stale=$stale)" >> "$SUP_LOG"
        if [ "$stale" -ge 3 ]; then
            echo "[$(date '+%F %T')] 3 rounds with no progress - suspected WAF block, stop for manual check" >> "$SUP_LOG"
            break
        fi
        sleep 60
    else
        stale=0
        sleep 5
    fi
    prev=$now
done
echo "[$(date '+%F %T')] supervisor done (rounds=$i jsonl=$(count_jsonl))" >> "$SUP_LOG"
