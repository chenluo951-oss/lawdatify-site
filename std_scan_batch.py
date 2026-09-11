#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量跑「国标在线阅读器 → 整页截图 → 三轮 OCR 比对」的待办清单。

只处理探测阶段确认「有在线阅读器」且尚未完成的条目；
每完成一条即写台账，中断后可原样重跑（幂等）。
"""
import sys
import os
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import std_scan as S  # noqa: E402

PROBE = os.path.join(HERE, "sources", "standards", "gb_probe.json")
LED = os.path.join(HERE, "sources", "standards", "scan_ledger.json")


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    probe = json.load(open(PROBE, encoding="utf-8"))
    done = {k for k, v in (S.load_ledger() or {}).items()
            if not k.startswith("_") and isinstance(v, dict) and v.get("status") == "scan+ocr"}
    todo = [x for x in probe.get("ok", []) if x[0] not in done]
    if limit:
        todo = todo[:limit]
    print("待扫描 %d 条（已完成 %d 条）" % (len(todo), len(done)))
    led = S.load_ledger()
    ok = 0
    for code, name, pages, hcno in todo:
        try:
            rec = S.do_gb(code, name, hcno=hcno, pages_limit=0)
            led[code] = rec
            S.save_ledger(led)
            print("  %-20s %-12s 页=%s 字=%s 冲突=%s"
                  % (code, rec.get("status"), rec.get("images"), rec.get("chars"),
                     rec.get("conflicts")), flush=True)
            if rec.get("status") == "scan+ocr":
                ok += 1
        except Exception as e:
            print("  %-20s ERROR %s" % (code, str(e)[:90]), flush=True)
        time.sleep(1)
    print("完成：%d/%d" % (ok, len(todo)))


if __name__ == "__main__":
    main()
