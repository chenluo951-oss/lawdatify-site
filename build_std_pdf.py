#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_std_pdf.py —— 把本机归档的官方标准 PDF 接入站点，供阅读器「原版直读」。

为什么不用 OCR / 文字层抽取？
    标准 PDF 版式（章条缩进、表格、图、公式、页眉）在纯文本里必然丢失，用户看到的是
    「一坨连在一起的文字」。直接给原版 PDF，阅感与官方发布版本完全一致，且零缺字。

数据来源（本人存档，仅供个人学习研究）：
    <标准库>/行业标准/<编号> <名称>.pdf    ← 行标，发布机构公开 PDF，含文字层
    <标准库>/TAF标准/<编号>_<名称>.pdf     ← 团标，TAF 官方公开 PDF
    国标无官方 PDF（openstd 仅提供图片式在线阅读器），保留官方在线阅读器深链。

产出：
    kb/std/<tid>.pdf                  站点内原版 PDF（文件名用正文 id，避免中文/空格）
    kb/texts/std_pdf.json             {tid: {file, pages, size, bytes}} 供阅读器与条目入口读取

用法：
    python3 build_std_pdf.py                 # 全量同步（增量：体积/时间未变则跳过）
    python3 build_std_pdf.py --limit-mb 80   # 体积预算，超出后按相关度截断
    python3 build_std_pdf.py --prune         # 清掉站点上已不再需要（或超预算）的 PDF
"""
import os
import re
import sys
import json
import shutil
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_std_texts as B

OUT_DIR = os.path.join(HERE, "kb", "std")
MAP = os.path.join(HERE, "kb", "texts", "std_pdf.json")

# 合规相关度：与业务强相关的排前面，体积预算不够时优先保住
REL_HIGH = re.compile(
    r"个人信息|隐私|数据|算法|人工智能|生成式|深度合成|APP|应用软件|移动应用|"
    r"软件开发工具包|SDK|未成年人|儿童|身份|标识|网络|安全|电子商务|平台|"
    r"食品|餐饮|食用|冷链|温控|计量|定量包装|包装|消费者|促销|价格|广告|"
    r"支付|快递|寄递|外卖|预付|绿色|限塑|骑手|灵活用工|劳动")
REL_MID = re.compile(r"通信|终端|测试|评估|规范|指南|要求|技术")


def rel_score(name, code):
    s = 0
    if REL_HIGH.search(name or ""):
        s += 10
    if REL_MID.search(name or ""):
        s += 2
    c = (code or "").upper()
    if c.startswith("GB"):
        s += 4          # 国标效力层级最高
    elif c.startswith("T/"):
        s += 2          # 团标常被监管直接引用（APP 测评、摇一摇等）
    if re.search(r"个人信息|隐私|算法|未成年|APP|应用软件", name or ""):
        s += 6
    return s


def tid_of(code, raw_name):
    key = "STD::" + (code or B.ncode(raw_name))
    return hashlib.md5(key.encode()).hexdigest()[:10]


def pdf_pages(path):
    try:
        import fitz
        with fitz.open(path) as d:
            return d.page_count
    except Exception:
        return 0


def collect_pdfs():
    """返回 [{'tid','code','name','pdf','size','score'}]，同 tid 去重。"""
    out, seen = [], {}
    for r in B.collect():
        stem = os.path.splitext(r["file"])[0]
        pdf = stem + ".pdf"
        if not os.path.exists(pdf):
            continue
        tid = tid_of(r["code"], r["raw_name"])
        sz = os.path.getsize(pdf)
        if tid in seen:
            # 同编号多份：保留大的那份（更完整）
            if sz <= seen[tid]["size"]:
                continue
            out = [x for x in out if x["tid"] != tid]
        rec = {"tid": tid, "code": r["code"], "name": r["raw_name"],
               "pdf": pdf, "size": sz, "level": r["level"],
               "score": rel_score(r["raw_name"], r["code"])}
        seen[tid] = rec
        out.append(rec)
    return out


def main():
    limit_mb = None
    if "--limit-mb" in sys.argv:
        limit_mb = float(sys.argv[sys.argv.index("--limit-mb") + 1])
    prune = "--prune" in sys.argv

    rows = collect_pdfs()
    rows.sort(key=lambda x: (-x["score"], x["size"]))
    budget = (limit_mb * 1e6) if limit_mb else None

    picked, total = [], 0
    for r in rows:
        if budget and total + r["size"] > budget:
            continue
        picked.append(r)
        total += r["size"]

    os.makedirs(OUT_DIR, exist_ok=True)
    keep_names = set()
    mapping = {}
    copied = skipped = 0
    for r in picked:
        dst = os.path.join(OUT_DIR, r["tid"] + ".pdf")
        keep_names.add(r["tid"] + ".pdf")
        need = True
        if os.path.exists(dst) and os.path.getsize(dst) == r["size"]:
            # 抽样比对首尾 4KB，避免同名不同内容的假命中
            with open(dst, "rb") as a, open(r["pdf"], "rb") as b:
                if a.read(4096) == b.read(4096):
                    need = False
        if need:
            shutil.copy2(r["pdf"], dst)
            copied += 1
        else:
            skipped += 1
        mapping[r["tid"]] = {
            "file": "std/" + r["tid"] + ".pdf",
            "bytes": r["size"],
            "pages": pdf_pages(r["pdf"]),
            "code": r["code"],
            "level": r["level"],
            "note": "原版 PDF（取自本人存档的发布机构公开件）",
        }

    if prune:
        removed = 0
        for f in os.listdir(OUT_DIR):
            if f.endswith(".pdf") and f not in keep_names:
                os.remove(os.path.join(OUT_DIR, f))
                removed += 1
        if removed:
            print("清理不再需要的 PDF：%d 个" % removed)

    json.dump({"_meta": {"count": len(mapping), "bytes": total,
                         "note": "站点内原版标准 PDF；本人存档，仅供个人学习研究，"
                                 "正式引用以官方发布版本为准。"},
               "items": mapping},
              open(MAP, "w", encoding="utf-8"), ensure_ascii=False)

    print("标准原版 PDF：%d 部 / %.1f MB（新复制 %d，复用 %d）"
          % (len(mapping), total / 1e6, copied, skipped))
    by_level = {}
    for r in picked:
        by_level[r["level"]] = by_level.get(r["level"], 0) + 1
    for k, v in sorted(by_level.items(), key=lambda x: -x[1]):
        print("   %s %d 部" % (k, v))
    if budget and len(picked) < len(rows):
        rest = [r for r in rows if r["tid"] not in mapping]
        print("   受体积预算限制未发布 %d 部（最小 %.1f MB）"
              % (len(rest), sum(x["size"] for x in rest) / 1e6))


if __name__ == "__main__":
    main()
