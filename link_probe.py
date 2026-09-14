#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
link_probe.py —— 全站外链实测（用 curl，不用 urllib：沙箱代理会误判全失效）

用法：
    python3 link_probe.py                 # 全量实测（并发 10）
    python3 link_probe.py --only news     # 只测某目录
    python3 link_probe.py --resume        # 复用已有结果，只补未测
产出：
    sources/link_probe.json   每条 URL 的 status / final_url / note
"""
import os
import re
import sys
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sources", "link_probe.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SKIP = (".git", "_private", "node_modules", ".cache", "_quarantine")


def collect_pages(only=None):
    pages = []
    for root, dirs, files in os.walk(HERE):
        if any(s in root for s in SKIP):
            continue
        for f in files:
            if not f.endswith(".html"):
                continue
            p = os.path.join(root, f)
            if only and only not in p:
                continue
            pages.append(p)
    return sorted(pages)


def hrefs(path):
    t = open(path, encoding="utf-8", errors="ignore").read()
    # 只取正文链接：href="..." 且 http(s) 开头
    urls = set(re.findall(r'href="(https?://[^"#]+)"', t))
    # 排除站内自身
    urls = {u for u in urls if "chenluo951-oss.github.io" not in u
            and "lawdatify" not in u}
    return urls


def probe(url, timeout=25):
    """返回 (status, final_url)。status 为 '000' 表示连接失败。"""
    cmd = ["curl", "-s", "-o", "/dev/null", "-L", "--compressed",
           "-A", UA, "--max-time", str(timeout),
           "-w", "%{http_code}\t%{url_effective}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 8)
        out = (r.stdout or "").strip()
        if "\t" in out:
            code, fin = out.split("\t", 1)
            return code.strip(), fin.strip()
        return (out or "000"), url
    except Exception:
        return "000", url


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    resume = "--resume" in sys.argv

    pages = collect_pages(only)
    per_page = {}
    allurl = set()
    for p in pages:
        us = hrefs(p)
        if us:
            per_page[os.path.relpath(p, HERE)] = sorted(us)
        allurl |= us

    old = {}
    if resume and os.path.exists(OUT):
        old = json.load(open(OUT, encoding="utf-8")).get("results", {})

    todo = sorted(u for u in allurl if u not in old)
    print(f"页面 {len(pages)} · 去重外链 {len(allurl)} · 待测 {len(todo)}", flush=True)

    results = dict(old)
    if todo:
        done = 0
        with ThreadPoolExecutor(max_workers=10) as ex:
            for u, (code, fin) in zip(todo, ex.map(probe, todo)):
                results[u] = {"status": code, "final": fin}
                done += 1
                if done % 50 == 0:
                    print(f"  ... {done}/{len(todo)}", flush=True)
                    json.dump({"results": results, "per_page": per_page},
                              open(OUT, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)

    json.dump({"results": results, "per_page": per_page},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    bad = {u: v for u, v in results.items() if v["status"] not in ("200", "206")}
    print(f"\n完成：OK {len(results)-len(bad)} / 异常 {len(bad)}", flush=True)
    for code in sorted({v["status"] for v in bad.values()}):
        us = [u for u, v in bad.items() if v["status"] == code]
        print(f"  [{code}] {len(us)} 条", flush=True)


if __name__ == "__main__":
    main()
