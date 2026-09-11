#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hbba_fetch.py — 通信/金融等行业标准（hbba.sacinfo.org.cn）原文抓取。

实测结论（2026-09-11）：
  · 详情页 stdDetail/<pk>            → 只有元数据
  · stdQueryList（POST，key/current/size）→ 可检索全库，返回 pk/编号/名称/状态/发布实施日
  · /portal/online/<pk>              → 在线阅读器；若该标准未公开全文，页面给出提示文案
  · /portal/download/<pk>            → **完整 PDF，且带文字层**（可直接抽文本，无需 OCR）

因此行标链路 = 检索 → 探全文 → 下载 PDF → 抽文本 → 本机标准库 + 语料库 + 台账 + 私有库。

用法：
  python3 hbba_fetch.py --search            # 只检索，打印命中，不下载
  python3 hbba_fetch.py --run               # 抓尚未归档的（含检索发现的新条目）
  python3 hbba_fetch.py --run --all         # 全量重抓
  python3 hbba_fetch.py --run --limit 5     # 试跑
"""
import os
import re
import sys
import json
import time
import hashlib
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H  # noqa: E402


def today():
    return datetime.date.today().isoformat()


def sha16(t):
    return hashlib.sha256((t or "").encode("utf-8")).hexdigest()[:16]


BASE = "https://hbba.sacinfo.org.cn"
KNOWN = os.path.join(HERE, "sources", "standards", "hbba_fetched.json")
LEDGER = os.path.join(HERE, "sources", "standards", "harvest_ledger.json")
LIBDIR = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库/行业标准")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

# 与本知识库领域相关的检索词（通信/金融/交通等行业标准里做合规要用的那批）
KEYS = [
    "个人信息", "数据安全", "数据分类分级", "重要数据", "算法", "生成式人工智能",
    "人工智能", "未成年人", "移动互联网应用", "车联网", "工业互联网", "个人信息保护",
    "用户权益", "隐私", "网络安全", "数据出境", "人脸识别", "深度合成",
]


def curl(url, timeout=60, out=None, data=None, referer=None):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "--compressed", "-A", UA]
    if referer:
        cmd += ["-e", referer]
    if data is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/x-www-form-urlencoded",
                "-H", "X-Requested-With: XMLHttpRequest", "--data", data]
    if out:
        cmd += ["-o", out, "-w", "%{http_code}|%{size_download}|%{content_type}"]
    r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 30)
    return r.stdout.strip()


def curl_json(url, data=None, timeout=60):
    raw = ""
    cmd = ["curl", "-sL", "--max-time", str(timeout), "--compressed", "-A", UA]
    if data is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/x-www-form-urlencoded",
                "-H", "X-Requested-With: XMLHttpRequest", "--data", data]
    try:
        r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 30)
        raw = r.stdout
        return json.loads(raw)
    except Exception:
        return {}


def search(key, size=30):
    """按关键词检索标准，返回规范化的候选列表。"""
    out = []
    for page in (1, 2, 3):
        d = curl_json("%s/stdQueryList" % BASE,
                      data="current=%d&size=%d&key=%s" % (page, size,
                                                          subprocess.run(
                                                              ["python3", "-c",
                                                               "import urllib.parse,sys;"
                                                               "print(urllib.parse.quote(sys.argv[1]))",
                                                               key],
                                                              capture_output=True,
                                                              text=True).stdout.strip()))
        recs = d.get("records") or []
        if not recs:
            break
        for r in recs:
            code = (r.get("code") or "").strip()
            if not code:
                continue
            out.append({
                "code": code,
                "name": (r.get("chName") or "").strip(),
                "pk": r.get("pk") or "",
                "industry": r.get("industry") or "",
                "status": r.get("status") or "",
                "chargeDept": r.get("chargeDept") or "",
                "url": "%s/stdDetail/%s" % (BASE, r.get("pk") or ""),
            })
        if page >= (d.get("pages") or 1):
            break
        time.sleep(0.3)
    return out


def online_available(pk):
    """阅读器页有图块/下载入口 → 视为可获取全文。"""
    html = ""
    cmd = ["curl", "-sL", "--max-time", "45", "--compressed", "-A", UA,
           "-e", "%s/stdDetail/%s" % (BASE, pk), "%s/portal/online/%s" % (BASE, pk)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=70)
        html = r.stdout
    except Exception:
        return False, ""
    if len(html) < 400:
        return False, ""
    tip = re.search(r"<h3>([^<]*)</h3>\s*<p>([^<]*)</p>", html)
    if tip:  # 有明确的「不公开/请购买」提示 → 无全文
        return False, "%s / %s" % (tip.group(1).strip(), tip.group(2).strip()[:60])
    return ("pdfImg" in html or "onlineRead" in html or "viewGbImg" in html), ""


def download(pk, dest):
    ref = "%s/stdDetail/%s" % (BASE, pk)
    stat = curl("%s/portal/download/%s" % (BASE, pk), out=dest, referer=ref, timeout=180)
    if not os.path.exists(dest):
        return False, stat
    with open(dest, "rb") as f:
        head = f.read(5)
    if head[:4] != b"%PDF":
        os.remove(dest)
        return False, stat
    return True, stat


def pdf_text(path, maxchars=400000):
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(path)
    except Exception:
        return ""
    buf = []
    for i in range(min(doc.page_count, 400)):
        try:
            buf.append(doc[i].get_text())
        except Exception:
            continue
        if sum(len(x) for x in buf) > maxchars:
            break
    doc.close()
    return "\n".join(buf)


def norm_code(code):
    return re.sub(r"[^0-9A-Za-z]", "", code or "").upper()


def main():
    argv = sys.argv[1:]
    do_search = "--search" in argv
    do_run = "--run" in argv
    do_all = "--all" in argv
    only_new = "--new-only" in argv
    limit = 0
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    known = H.load_json(KNOWN, {})
    ledger = H.load_json(LEDGER, {})
    idx = H.load_json(H.IDX, {"updated": "", "items": {}})
    os.makedirs(LIBDIR, exist_ok=True)

    if do_search or (do_run and not only_new):
        print("检索 hbba（%d 个关键词）…" % len(KEYS))
        found = {}
        for k in KEYS:
            for r in search(k):
                key = norm_code(r["code"])
                if key and key not in found:
                    found[key] = r
            print("   %-12s 累计命中 %d" % (k, len(found)))
            time.sleep(0.4)
        added = 0
        for key, r in found.items():
            if key in {norm_code(c) for c in known}:
                continue
            known[r["code"]] = {"code": r["code"], "name": r["name"], "status": r["status"],
                                "pub": "", "impl": "", "chargeDept": r["chargeDept"],
                                "industry": r["industry"], "url": r["url"], "pk": r["pk"],
                                "note": "hbba 检索发现"}
            added += 1
        H.save_json(KNOWN, known)
        print("检索命中 %d 条，新增候选 %d 条，已知库共 %d 条" % (len(found), added, len(known)))

    if not do_run:
        for c, v in list(known.items())[:80]:
            print("   %-20s %s" % (c, (v.get("name") or "")[:44]))
        return

    todo = []
    for code, v in known.items():
        fp = os.path.join(LIBDIR, H.safe_name((v.get("code") or code) + " " + (v.get("name") or "")) + ".pdf")
        if not do_all and os.path.exists(fp):
            continue
        todo.append((code, v, fp))
    if limit:
        todo = todo[:limit]
    print("待抓取 %d 条" % len(todo))

    ok = skip = fail = 0
    for i, (code, v, fp) in enumerate(todo, 1):
        pk = v.get("pk") or (v.get("url") or "").rsplit("/", 1)[-1]
        if not pk:
            fail += 1
            continue
        avail, why = online_available(pk)
        if not avail:
            skip += 1
            print("  [%d/%d] 未公开全文  %-18s %s" % (i, len(todo), code, why[:50]))
            ledger_key = "%s::%s" % (code, v.get("name") or "")
            ledger[ledger_key] = {"code": code, "name": v.get("name") or "", "kind": "标准",
                                  "level": "行业标准", "status": "meta",
                                  "official_url": v.get("url") or "", "chars": 0,
                                  "sha256": "", "fetched": today(),
                                  "note": "hbba 未公开全文，仅元数据深链"}
            time.sleep(0.5)
            continue
        good, stat = download(pk, fp)
        if not good:
            fail += 1
            print("  [%d/%d] 下载失败    %-18s %s" % (i, len(todo), code, stat[:60]))
            time.sleep(1.0)
            continue
        txt = pdf_text(fp, maxchars=400000)
        cid = ""
        if len(txt) >= 800:
            cid, _why = H.add_doc(idx, (v.get("code") or code) + " " + (v.get("name") or ""),
                                  v.get("code") or code, "行业标准", txt,
                                  os.path.relpath(fp, HERE))
            cid = cid or ""
        ledger_key = "%s::%s" % (code, v.get("name") or "")
        ledger[ledger_key] = {"code": code, "name": v.get("name") or "", "kind": "标准",
                              "level": "行业标准",
                              "status": "full" if len(txt) >= 800 else "meta",
                              "official_url": v.get("url") or "",
                              "chars": len(txt), "sha256": sha16(txt),
                              "fetched": today(), "file": os.path.relpath(fp, HERE),
                              "corpus_id": cid,
                              "note": "hbba 官方在线阅读器 → 完整 PDF（含文字层）"}
        v["file"] = fp
        v["chars"] = len(txt)
        ok += 1
        print("  [%d/%d] ✓ %-18s %5d 字  %s" % (i, len(todo), code, len(txt),
                                               (v.get("name") or "")[:34]))
        time.sleep(0.6)

    H.save_json(KNOWN, known)
    H.save_json(LEDGER, ledger)
    idx["updated"] = today()
    json.dump(idx, open(H.IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n完成：成功 %d / 未公开 %d / 失败 %d" % (ok, skip, fail))


if __name__ == "__main__":
    main()
