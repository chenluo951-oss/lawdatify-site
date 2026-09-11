#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把三条抓取链路的成果并进统一台账 sources/standards/harvest_ledger.json

统一台账是「哪些条目已拿到官方原文」的唯一真源，站点条目上的
「读原文 / 官方全文 PDF / 官方在线阅读」入口全部由它驱动。

三条链路：
  1) harvest.py / hbba_fetch.py —— 六源正文抓取与行业标准官方 PDF（已有 pdf_url 字段）
  2) fetch_taf.py —— TAF 团体标准：官网公开 PDF（www.taf.org.cn/upload/AssociationStandard/）
  3) std_scan.py —— 国标在线阅读器：整页截图 + 三轮 OCR 比对定稿

用法：python merge_ledgers.py [--taf] [--gb]  （不带参数则三条都跑）
"""
import os
import re
import sys
import json
import argparse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H  # noqa: E402

SRC = os.path.join(HERE, "sources", "standards")
LEDGER = os.path.join(SRC, "harvest_ledger.json")
TAF_DOCS = os.path.join(SRC, "taf_docs.json")
TAF_FETCHED = os.path.join(SRC, "taf_fetched.json")
SCAN_LEDGER = os.path.join(SRC, "scan_ledger.json")
TAF_STORE = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库/TAF标准")


def nk(s):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", s or "").upper()


def pdf_text(path, maxchars=400000):
    try:
        import fitz
        doc = fitz.open(path)
        out = []
        for pg in doc:
            out.append(pg.get_text())
            if sum(len(x) for x in out) > maxchars:
                break
        doc.close()
        return "\n".join(out)[:maxchars]
    except Exception:
        return ""


def local_taf_files():
    """本机 TAF 目录 → {规范化文件名前缀: 完整路径}"""
    m = {}
    if not os.path.isdir(TAF_STORE):
        return m
    for fn in os.listdir(TAF_STORE):
        stem = os.path.splitext(fn)[0]
        m[nk(stem)] = os.path.join(TAF_STORE, fn)
    return m


def find_taf(code, name, files):
    """按标准号（T/TAF 023—2018 → TTAF0232018）或名称定位本机文件。"""
    c = nk(code)
    for k, p in files.items():
        if c and c in k:
            return p
    n = nk(re.sub(r"^T/?TAF\s*\d+(\.\d+)?\s*[—\-–]\s*\d{4}\s*", "", name))
    if len(n) >= 6:
        for k, p in files.items():
            if n in k:
                return p
    return ""


def do_taf(ledger):
    docs = H.load_json(TAF_DOCS, {})
    fetched = H.load_json(TAF_FETCHED, {})
    files = local_taf_files()
    idx = H.load_json(H.IDX, {"updated": "", "items": {}})
    n_full = n_meta = 0
    for dk, t in docs.items():
        code = (t.get("code") or dk or "").strip()
        name = (t.get("name") or "").strip()
        if not code or not name:
            continue
        pdf_url = t.get("pdf") or ""
        fp = find_taf(code, name, files)
        txt = ""
        if fp and fp.lower().endswith(".pdf"):
            txt = pdf_text(fp)
        elif fp:
            txt = open(fp, encoding="utf-8", errors="ignore").read()[:400000]
        txt = H.norm_text(txt) if hasattr(H, "norm_text") else txt
        cid = ""
        if len(txt) >= 800:
            cid, _ = H.add_doc(idx, code + " " + name, code, "团体标准", txt,
                               os.path.relpath(fp, HERE) if fp else "")
            cid = cid or ""
            n_full += 1
        else:
            n_meta += 1
        key = "%s::%s" % (code, name)
        rec = ledger.get(key) or {}
        rec.update({
            "code": code, "name": name, "kind": "标准", "level": "团体标准",
            "status": "full" if len(txt) >= 800 else "meta",
            "official_url": t.get("url") or (fetched.get(code.replace("/", "").replace(" ", ""), {}) or {}).get("url", ""),
            "chars": len(txt), "fetched": date.today().isoformat(),
            "note": "TAF 官网公开 PDF（含文字层）",
        })
        if pdf_url:
            rec["pdf_url"] = pdf_url
        if fp:
            rec["file"] = os.path.relpath(fp, HERE)
        if cid:
            rec["corpus_id"] = cid
        ledger[key] = rec
    H.save_json(H.IDX, idx)
    print("TAF：%d 条（有正文 %d / 仅元数据 %d，其中 %d 条带官方 PDF 直链）"
          % (n_full + n_meta, n_full, n_meta, sum(1 for v in docs.values() if v.get("pdf"))))
    return n_full


def do_gb(ledger):
    scan = H.load_json(SCAN_LEDGER, {})
    idx = H.load_json(H.IDX, {"updated": "", "items": {}})
    n = 0
    for code, r in scan.items():
        if code.startswith("_") or not isinstance(r, dict):
            continue
        if r.get("status") != "scan+ocr":
            continue
        txtp = os.path.join(HERE, r.get("text") or "")
        txt = ""
        if os.path.exists(txtp):
            txt = H.norm_text(open(txtp, encoding="utf-8", errors="ignore").read()) \
                if hasattr(H, "norm_text") else open(txtp, encoding="utf-8", errors="ignore").read()
        key = "%s::%s" % (code, r.get("name") or code)
        rec = ledger.get(key) or {}
        rec.update({
            "code": code, "name": r.get("name") or code, "kind": "标准",
            "level": "国家标准", "status": "full" if len(txt) >= 800 else "meta",
            "official_url": r.get("official_url") or "", "chars": len(txt),
            "fetched": r.get("fetched") or date.today().isoformat(),
            "file": r.get("text") or "",
            "note": "国标在线阅读器整页截图 + 三轮 OCR 比对定稿（%d 页，%d 处待复核）"
                    % (r.get("images") or 0, r.get("conflicts") or 0),
        })
        if len(txt) >= 800:
            cid, _ = H.add_doc(idx, code + " " + (r.get("name") or ""), code, "国家标准", txt,
                               r.get("text") or "")
            rec["corpus_id"] = cid or ""
            n += 1
        ledger[key] = rec
    H.save_json(H.IDX, idx)
    print("国标 OCR：%d 条已并入台账" % n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--taf", action="store_true")
    ap.add_argument("--gb", action="store_true")
    a = ap.parse_args()
    both = not (a.taf or a.gb)
    ledger = H.load_json(LEDGER, {})
    if a.taf or both:
        do_taf(ledger)
    if a.gb or both:
        do_gb(ledger)
    # 顺序无关：不排序，保留人类可读的键序
    H.save_json(LEDGER, ledger)
    full = sum(1 for v in ledger.values() if isinstance(v, dict) and v.get("status") in ("full", "meta"))
    pdfs = sum(1 for v in ledger.values() if isinstance(v, dict) and v.get("pdf_url"))
    print("台账合计 %d 条，其中已归档 %d 条、带官方公开 PDF 深链 %d 条" % (len(ledger), full, pdfs))


if __name__ == "__main__":
    main()
