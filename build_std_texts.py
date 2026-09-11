#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_std_texts.py —— 把已归档的标准正文接入站内原文库（与 build_texts.py 共用阅读器）。

正文来源（全部为本人存档，仅供本机学习研究）：
  国标：<标准库>/国标（截图+OCR）/<编号>/<编号> 全文（OCR）.txt   ← std_scan.py 三轮 OCR 定稿
  行标：<标准库>/行业标准/<编号> <名称>.pdf                       ← hbba /portal/download 官方公开 PDF，含文字层
  团标：<标准库>/TAF标准/<编号>_<名称>.pdf 或 .txt                 ← TAF 官方公开 PDF

产出：
  kb/texts/s-NN.json                标准正文分片（阅读器按需加载）
  kb/texts/std_index.json           标准目录（由 build_texts.py 并入统一 index.json）
  sources/standards/std_text_ids.json   标准编号 → 原文 id（供 build_standards 加「站内原文」入口）

用法：
    python3 build_std_texts.py            # 全量（有缓存则秒回）
    python3 build_std_texts.py --rebuild  # 忽略缓存重新抽取
"""
import os
import re
import sys
import json
import html
import hashlib
import warnings
import collections

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H
import build_texts as BT
import edits as E

STORE = H.STORE
LIB = H.LIB
OUT = os.path.join(HERE, "kb", "texts")
MAP = os.path.join(HERE, "sources", "standards", "std_text_ids.json")
CACHE = os.path.join(HERE, "sources", ".cache", "std")

PART_CHARS = 1_200_000
MIN_CHARS = 1200

# 组 → (目录, 层级, 取文方式)
GROUPS = [
    ("国标（截图+OCR）", "国家标准", "ocr"),
    ("行业标准", "行业标准", "pdf"),
    ("TAF标准", "团体标准", "pdf"),
]

# 从文件名/目录名里抠标准编号：YD_T 6090-2024 / T_TAF_267.8—2025 / GB/T 45123-2024 / AQ 3064.1—2025
CODE_RE = re.compile(
    r"^([A-Z]{1,6}(?:[_\s/][A-Z]{1,6})*)[_\s]*(\d+(?:\.\d+)*)\s*[—\-–_]+\s*(\d{4})")

# 标准正文必须出现的标志性章节（与 harvest.py 的正文校验闸同源）
SECTIONS = ("范围", "规范性引用文件", "术语和定义")

# 标准 PDF 的页眉页脚：编号行、罗马页码、纯数字页、发布日期
PAGE_JUNK = re.compile(
    r"^\s*(?:[IVXLC]{1,5}|[0-9]{1,4}|"
    r"[A-Z]{1,4}(?:[/_\s][A-Z]{1,4})*\s*\d+(?:\.\d+)*\s*[—\-–]\s*\d{4}|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*(?:发布|实施))\s*$")


def ncode(s):
    """标准编号归一：去所有分隔符与大小写差异 → GBT451232024。"""
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def code_of(s):
    m = CODE_RE.match((s or "").strip())
    if not m:
        return ""
    return ncode(m.group(1) + m.group(2) + m.group(3))


def std_clean(t, code, name):
    """标准正文的追加清洗：去掉重复页眉（标准号/标准名）、校次号、孤立页码。"""
    out = []
    for ln in (t or "").split("\n"):
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if PAGE_JUNK.match(s):
            continue
        flat = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", s)
        if flat and flat == re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", code or ""):
            continue
        if flat and name and flat == re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", name):
            continue
        out.append(s)
    t = "\n".join(out)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def pdf_text(path):
    import fitz
    d = fitz.open(path)
    try:
        return "".join(p.get_text() for p in d)
    finally:
        d.close()


def cached_text(path, rebuild=False):
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5(path.encode()).hexdigest()[:16]
    cp = os.path.join(CACHE, key + ".txt")
    if os.path.exists(cp) and not rebuild:
        return open(cp, encoding="utf-8").read()
    ext = os.path.splitext(path)[1].lower()
    try:
        raw = pdf_text(path) if ext == ".pdf" else open(path, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        print("  抽取失败 %s：%s" % (os.path.basename(path), e))
        return ""
    open(cp, "w", encoding="utf-8").write(raw)
    return raw


def collect():
    """扫描标准库，返回 [{'code','file','level','raw_name'}]，同编号优先 .txt（免抽取）。"""
    seen = {}
    for sub, level, mode in GROUPS:
        d = os.path.join(STORE, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            full = os.path.join(d, name)
            if mode == "ocr":
                if not os.path.isdir(full):
                    continue
                txt = [f for f in os.listdir(full) if f.endswith(".txt") and "OCR" in f]
                if not txt:
                    continue
                p = os.path.join(full, txt[0])
                code = code_of(name)
                key = (code or ncode(name), "国家标准")
                seen.setdefault(key, {"code": code, "file": p, "level": level,
                                      "raw_name": name, "sub": sub})
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext not in (".pdf", ".txt"):
                    continue
                stem = os.path.splitext(name)[0]
                code = code_of(stem)
                key = (code or ncode(stem), level)
                cur = seen.get(key)
                # 同编号：.txt 优先（已是文字层，无需再抽 PDF）
                if cur is None or (ext == ".txt" and cur["file"].endswith(".pdf")):
                    seen[key] = {"code": code, "file": full, "level": level,
                                 "raw_name": stem, "sub": sub}
    return list(seen.values())


def lib_names():
    """标准编号 → (名称, 条目库字段)，用于把文件名的简写换成规范中文名。"""
    lib = H.load_json(LIB, {"items": []})
    out = {}
    for it in lib.get("items", []):
        c = ncode(it.get("code"))
        if c and it.get("level") in BT.STD_LEVELS:
            out[c] = it
    return out


def build(rebuild=False, quiet=False):
    os.makedirs(OUT, exist_ok=True)
    rows = collect()
    names = lib_names()
    kept, idmap, dropped = [], {}, []
    for r in rows:
        raw = cached_text(r["file"], rebuild)
        if not raw:
            dropped.append((r["raw_name"], "抽取为空"))
            continue
        t = std_clean(BT.clean(raw), r["code"], r["raw_name"])
        t = E.apply_rules("std", ncode(r["code"]), t)
        if len(t) < MIN_CHARS:
            dropped.append((r["raw_name"], "篇幅不足 %d 字" % len(t)))
            continue
        # 正文校验闸：标准必须能检出「范围 / 规范性引用文件 / 术语和定义」
        if not any(s in t[:4000] for s in SECTIONS):
            dropped.append((r["raw_name"], "未检出标准正文特征（可能是版权页/目次）"))
            continue
        qok, why = BT.quality_ok(t)
        if not qok:
            dropped.append((r["raw_name"], why))
            continue
        it = names.get(ncode(r["code"])) or {}
        name = it.get("name") or re.sub(r"^[A-Z_/\s\d\.\-—–]+", "", r["raw_name"]).strip() or r["raw_name"]
        key = "STD::" + (r["code"] or ncode(r["raw_name"]))
        tid = hashlib.md5(key.encode()).hexdigest()[:10]
        rec = {"id": tid, "kind": "std", "code": r["code"] or it.get("code") or "",
               "name": name, "level": r["level"],
               "issuer": it.get("issuer") or "", "pub": it.get("pub") or "",
               "impl": it.get("impl") or "", "status": it.get("status") or "",
               "url": it.get("url") or "", "chars": len(t), "src": r["sub"],
               "_text": t}
        kept.append(rec)
        idmap[key] = tid
        if r["code"]:
            idmap[ncode(r["code"])] = tid

    kept.sort(key=lambda x: (x["level"], x["code"], x["name"]))
    part, acc = 1, 0
    for x in kept:
        if acc and acc + x["chars"] > PART_CHARS:
            part += 1
            acc = 0
        x["part"] = part
        acc += x["chars"]

    for f in os.listdir(OUT):
        if re.fullmatch(r"s-\d+\.json", f):
            os.remove(os.path.join(OUT, f))
    parts = collections.defaultdict(dict)
    for x in kept:
        parts[x["part"]][x["id"]] = x.pop("_text")
    for p, d in parts.items():
        json.dump(d, open(os.path.join(OUT, "s-%02d.json" % p), "w", encoding="utf-8"),
                  ensure_ascii=False)

    json.dump({"_meta": {"count": len(kept), "parts": len(parts),
                         "note": "本人存档的标准正文（OCR 定稿 / 官方公开 PDF 文字层），仅供本机学习研究。"},
               "items": kept},
              open(os.path.join(OUT, "std_index.json"), "w", encoding="utf-8"), ensure_ascii=False)
    H.save_json(MAP, idmap)

    by_level = collections.Counter(x["level"] for x in kept)
    total = sum(x["chars"] for x in kept)
    if not quiet:
        print("标准原文库：%d 部 / %d 字 / %d 片" % (len(kept), total, len(parts)))
        for k, v in by_level.most_common():
            print("   %s %d 部" % (k, v))
        if dropped:
            print("未收录 %d 部，示例：%s"
                  % (len(dropped), "；".join("%s(%s)" % (n[:22], r) for n, r in dropped[:6])))
    return kept, len(parts)


if __name__ == "__main__":
    build(rebuild="--rebuild" in sys.argv)
