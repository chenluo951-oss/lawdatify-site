#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_taf.py — 批量抓取 TAF（电信终端产业协会）团体标准正文 PDF。

链路：taf_fetched.json（含 uid 与详情页 URL）
      → 详情页 HTML 提取 upload/...pdf 相对路径
      → 下载 PDF 到本机标准库
      → 提取文本写入站点语料库（供 enrich_duties 抽条款、search_lib 全文检索）
      → 记录到 sources/standards/taf_docs.json

用法：
  python3 fetch_taf.py            # 抓尚未入库的
  python3 fetch_taf.py --all      # 全量重抓
  python3 fetch_taf.py --limit 5  # 只抓前 N 条（试跑）
"""
import os
import re
import sys
import json
import time
import subprocess
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
TAF_JSON = os.path.join(HERE, "sources", "standards", "taf_fetched.json")
DONE_JSON = os.path.join(HERE, "sources", "standards", "taf_docs.json")
LIBDIR = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库/TAF标准")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def curl(url, timeout=45, binary=False, out=None):
    """统一走 curl 子进程（python urllib 在沙箱会被代理拦截）。"""
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", UA]
    if out:
        cmd += ["-o", out, "-w", "%{http_code}|%{size_download}|%{content_type}"]
    r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 20)
    return r.stdout.strip()


def load_idx():
    if os.path.exists(IDX):
        return json.load(open(IDX, encoding="utf-8"))
    return {"updated": "", "items": {}}


def save_idx(idx):
    import datetime
    idx["updated"] = datetime.date.today().isoformat()
    os.makedirs(CORPUS, exist_ok=True)
    json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False)


def add_to_corpus(idx, title, code, cat, text, src_rel):
    """写入语料库：文本落盘 + 索引登记。返回 doc id。"""
    import hashlib
    did = hashlib.md5((code + title).encode("utf-8")).hexdigest()[:12]
    items = idx["items"]
    if did in items:
        return did
    os.makedirs(CORPUS, exist_ok=True)
    txt_path = os.path.join(CORPUS, did + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    items[did] = {
        "id": did,
        "code": code,
        "name": title,
        "cat": cat,
        "pub": "",
        "impl": "",
        "toc": [],
        "src": src_rel,
        "chars": len(text),
        "head": text[:900],
    }
    return did


def pdf_to_text(pdf_path):
    """PDF → 文本。优先 PyMuPDF，失败返回空串（绝不臆造正文）。"""
    try:
        import fitz
        d = fitz.open(pdf_path)
        t = "\n".join(p.get_text() for p in d)
        d.close()
        return t
    except Exception:
        pass
    # 回退：pdftotext
    try:
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", pdf_path, "-"],
                           capture_output=True, text=True, timeout=120)
        if r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    return ""


def main():
    args = sys.argv[1:]
    do_all = "--all" in args
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])

    taf = json.load(open(TAF_JSON, encoding="utf-8"))
    items = [v for v in (taf.values() if isinstance(taf, dict) else taf) if v]

    done = json.load(open(DONE_JSON, encoding="utf-8")) if os.path.exists(DONE_JSON) else {}
    if do_all:
        done = {}

    os.makedirs(LIBDIR, exist_ok=True)
    idx = load_idx()

    ok = skip = fail = 0
    failed = []
    for it in items:
        code = (it.get("code") or "").strip()
        name = (it.get("name") or "").strip()
        url = it.get("url") or ""
        if not code or not url:
            continue
        if not do_all and code in done:
            skip += 1
            continue
        if limit is not None and (ok + fail) >= limit:
            break

        # 1) 详情页 → 提取 PDF 相对路径
        html = curl(url, timeout=30)
        m = re.search(r'(upload/[^"\'<>\n]+\.pdf)', html)
        if not m:
            fail += 1
            failed.append((code, "详情页无 PDF 链接"))
            continue
        rel = m.group(1)
        pdf_url = "https://www.taf.org.cn/" + urllib.parse.quote(rel, safe="/:")

        # 2) 下载到本机标准库
        safe = re.sub(r'[/\s]+', '_', f"{code} {name}")[:110] + ".pdf"
        dest = os.path.join(LIBDIR, safe)
        res = curl(pdf_url, timeout=90, out=dest)
        http = res.split("|")[0] if res else "000"
        size = int(res.split("|")[1]) if len(res.split("|")) > 1 and res.split("|")[1].isdigit() else 0
        if http != "200" or size < 5000:
            fail += 1
            failed.append((code, f"下载失败 {http}/{size}"))
            if os.path.exists(dest):
                os.remove(dest)
            continue

        # 3) 提取正文
        txt = pdf_to_text(dest)
        if len(txt) < 500:
            fail += 1
            failed.append((code, f"无文本层 {len(txt)}字"))
            continue

        # 4) 正文落本机 txt + 入语料库
        txt_dest = os.path.join(LIBDIR, safe[:-4] + ".txt")
        open(txt_dest, "w", encoding="utf-8").write(txt)
        did = add_to_corpus(idx, f"{code} {name}", code, "团体标准", txt,
                            "0.站点标准库/TAF标准/" + safe)
        done[code] = {
            "name": name,
            "url": url,
            "pdf": pdf_url,
            "corpus_id": did,
            "chars": len(txt),
            "local": dest,
        }
        ok += 1
        print(f"  ✔ {code}  {len(txt)}字  {name[:34]}")
        time.sleep(0.4)

    save_idx(idx)
    json.dump(done, open(DONE_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n抓到 {ok} · 跳过 {skip} · 失败 {fail}")
    for c, why in failed[:15]:
        print(f"   ✘ {c}: {why}")


if __name__ == "__main__":
    main()
