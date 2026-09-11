#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
std_ocr_fill.py —— 用本机 macOS Vision OCR 补齐「无文字层 / 文字层损坏」的标准 PDF。

背景：本机标准库里一部分 PDF 是纯扫描件（抽取为空），另一部分是
「有文字层但字体编码损坏」（抽出满屏乱码或私用区符号）。前者只能 OCR；
后者 OCR 也比乱码可靠。

策略（逐页判定，质量与速度兼顾）：
  1. 先看该页自带的文字层能不能用（页级质量闸）；
  2. 能用 → 直接用文字层（零成本、零误差）；
  3. 不能用 → 该页渲染成位图后多轮 OCR：先跑「原图」「放大锐化」两轮，
     两轮一致即定稿；不一致才补「灰度二值」第三轮、逐行投票。

产出：与 PDF 同名的 .txt。build_std_texts.py 对同一编号会优先采用 .txt。

用法：
    python3 std_ocr_fill.py                # 补所有不合格的（已有同名 .txt 的跳过）
    python3 std_ocr_fill.py --dry          # 只体检，不写文件
    python3 std_ocr_fill.py --only 4177    # 只处理编号含该串的
    python3 std_ocr_fill.py --force        # 已有同名 .txt 也重做
    python3 std_ocr_fill.py --rebuild      # 忽略 build_std_texts 的抽取缓存
"""
import os
import re
import sys
import json
import time
import shutil
import argparse
import tempfile
import collections
import concurrent.futures as futures

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_std_texts as S          # noqa: E402
import std_scan as SC                # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]")
RARE = re.compile(r"[\ue000-\uf8ff\ufffd]")
RENDER_W = 1700          # 目标渲染宽度（像素）：按页面宽度自适应，超大页面也不会爆图
WORKERS = 4              # 同一文档内并行 OCR 的页数
CONFLICT_OUT = os.path.join(HERE, "sources", "standards", "ocr_conflicts.json")


# ────────────────────────── ① 页级质量闸 ──────────────────────────
# 常用汉字：乱码（字体 ToUnicode 损坏、整体平移）几乎一个都命中不了
COMMON = "的一是在不了有人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动" \
         "同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高"


def page_bad(t):
    """一页的文字层能不能用。宁可少 OCR（快），也不放过乱码（准）。"""
    s = (t or "").strip()
    n = len(s)
    if n < 20:
        return True                                    # 抽取为空 / 近空页
    cjk = len(CJK.findall(s))
    rare = len(RARE.findall(s))
    if rare >= 6 and rare / n > 0.004:
        return True                                    # 私用区符号扎堆 → 字体编码损坏
    if n >= 100 and cjk < max(5, n * 0.06):
        return True                                    # 抽出上百字符却几乎没有汉字 → 乱码
    # 「汉字很多但常用字一个都见不到」= 字体编码整体平移出来的假汉字（如「犐犆犛」）
    if cjk >= 80:
        hits = sum(s.count(c) for c in COMMON)
        if hits / cjk < 0.08:
            return True
    return False


# ────────────────────────── ② 渲染与 OCR ──────────────────────────
def render(pg, width=RENDER_W):
    z = float(width) / max(1.0, pg.rect.width)
    return pg.get_pixmap(matrix=S._fitz().Matrix(z, z))


def ocr_page_fast(png_path, tmpd, tag):
    """两轮为主、冲突才三轮。返回 (文本, 冲突行数)。"""
    from PIL import Image, ImageFilter, ImageOps

    im = Image.open(png_path).convert("RGB")
    p0 = os.path.join(tmpd, "%s_a.png" % tag)
    im.convert("L").save(p0)
    big = im.resize((int(im.width * 2), int(im.height * 2)), Image.LANCZOS).convert("L")
    big = big.filter(ImageFilter.UnsharpMask(radius=1.4, percent=150, threshold=3))
    p1 = os.path.join(tmpd, "%s_b.png" % tag)
    big.save(p1)

    r0 = SC.vision_ocr(p0)
    r1 = SC.vision_ocr(p1)
    joined = lambda rs: "\n".join(l["text"] for l in rs)      # noqa: E731
    if SC.nkey(joined(r0)) == SC.nkey(joined(r1)):
        return joined(r0), 0

    g = ImageOps.autocontrast(im.convert("L"), cutoff=1)
    g = g.resize((int(g.width * 1.5), int(g.height * 1.5)), Image.LANCZOS)
    g = g.point(lambda p: 255 if p > 168 else 0)
    p2 = os.path.join(tmpd, "%s_c.png" % tag)
    g.save(p2)
    r2 = SC.vision_ocr(p2)

    runs = [r0, r1, r2]
    maps = [SC.align_lines(runs[0], r) for r in runs[1:]]
    final, conflicts = [], 0
    for i, a in enumerate(runs[0]):
        cands = [a["text"]] + [m.get(i, [""])[0] for m in maps]
        cands = [c for c in cands if SC.nkey(c)]
        if not cands:
            continue
        cnt = collections.Counter(SC.nkey(c) for c in cands)
        top, k = cnt.most_common(1)[0]
        if k >= 2:
            final.append(next(c for c in cands if SC.nkey(c) == top))
        else:
            final.append(cands[0])
            conflicts += 1
    return "\n".join(final), conflicts


# ────────────────────────── ③ 单部标准补齐 ──────────────────────────
def fill(pdf, force=False, dry=False, width=RENDER_W, log=print):
    """把一部 PDF 补成定稿 .txt。返回统计字典。"""
    t0 = time.time()
    stem = os.path.splitext(pdf)[0]
    out = stem + ".txt"
    fitz = S._fitz()
    doc = fitz.open(pdf)
    try:
        pages = [pg.get_text() for pg in doc]
        need = [i for i, t in enumerate(pages) if page_bad(t)]
        if not need:
            return {"path": pdf, "skipped": True, "reason": "文字层可用，无需 OCR",
                    "pages": len(pages), "ocr_pages": 0}
        if dry:
            return {"path": pdf, "dry": True, "pages": len(pages), "ocr_pages": len(need)}

        log("  OCR %s —— 共 %d 页，重做 %d 页"
            % (os.path.basename(pdf)[:50], len(pages), len(need)))
        results, conflicts = {}, 0
        tmpd = tempfile.mkdtemp(prefix="stof_")
        try:
            def one(i):
                tag = "p%04d" % i
                png = os.path.join(tmpd, tag + ".png")
                render(doc[i], width).save(png)
                txt, c = ocr_page_fast(png, tmpd, tag)
                for f in os.listdir(tmpd):
                    if f.startswith(tag):
                        try:
                            os.remove(os.path.join(tmpd, f))
                        except OSError:
                            pass
                return i, txt, c

            with futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for i, txt, c in ex.map(one, need):
                    results[i] = txt
                    conflicts += c
                    if len(results) % 10 == 0 or len(results) == len(need):
                        log("     %d/%d 页  %.1fs" % (len(results), len(need), time.time() - t0))
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)
    finally:
        doc.close()

    body = "\n\n".join((results.get(i) or t).strip() for i, t in enumerate(pages))
    code = S.code_of(os.path.basename(stem))
    text = S.std_clean(S.BT.clean(body), code, os.path.basename(stem))
    open(out, "w", encoding="utf-8").write(text)
    return {"path": pdf, "out": out, "pages": len(pages), "ocr_pages": len(results),
            "chars": len(text), "conflicts": conflicts,
            "cjk": len(CJK.findall(text)), "rare": len(RARE.findall(text)),
            "sec": any(x in text[:4000] for x in S.SECTIONS),
            "secs": round(time.time() - t0, 1)}


# ────────────────────────── ④ 入口 ──────────────────────────
def audit(rebuild=False):
    """体检：返回 (合格数, [(row, 原因)])。"""
    rows = S.collect()
    good, todo = 0, []
    for r in rows:
        raw = S.cached_text(r["file"], rebuild)
        if not raw:
            todo.append((r, "抽取为空"))
            continue
        t = S.std_clean(S.BT.clean(raw), r["code"], r["raw_name"])
        if len(t) < S.MIN_CHARS:
            todo.append((r, "篇幅不足 %d 字" % len(t)))
            continue
        if not any(x in t[:4000] for x in S.SECTIONS):
            todo.append((r, "未检出标准正文章节"))
            continue
        qok, why = S.BT.quality_ok(t)
        if not qok:
            todo.append((r, why))
            continue
        good += 1
    return rows, good, todo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--width", type=int, default=RENDER_W)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows, good, todo = audit(a.rebuild)
    if a.only:
        key = S.ncode(a.only)
        todo = [(r, w) for r, w in todo if key in S.ncode(r["code"] or r["raw_name"])]
    if a.limit:
        todo = todo[:a.limit]

    print("标准库共 %d 部：文字层合格 %d 部，待补 %d 部" % (len(rows), good, len(todo)))
    report, changed = [], []
    for i, (r, why) in enumerate(todo, 1):
        fn = r["file"]
        out = os.path.splitext(fn)[0] + ".txt"
        has_txt = fn.lower().endswith(".pdf") and os.path.exists(out)
        print("[%d/%d] %-50s %s%s"
              % (i, len(todo), r["raw_name"][:48], why,
                 "（已有 .txt，跳过）" if (has_txt and not a.force) else ""))
        if has_txt and not a.force:
            report.append({"name": r["raw_name"], "file": fn, "why": why, "action": "已有 .txt"})
            continue
        if fn.lower().endswith(".txt"):
            # 文本损坏：若同目录有同名 PDF，就改用 PDF 重新 OCR（TAF 团标常见形态）
            sib = os.path.splitext(fn)[0] + ".pdf"
            if os.path.exists(sib):
                print("     ↻ 文本损坏，改用同名 PDF 重新 OCR")
                fn = sib
            else:
                report.append({"name": r["raw_name"], "file": fn, "why": why,
                               "action": "文本损坏且无位图可渲染"})
                continue
        try:
            res = fill(fn, force=a.force, dry=a.dry, width=a.width)
        except Exception as e:
            res = {"path": fn, "error": "%s: %s" % (type(e).__name__, e), "why": why}
        res["name"] = r["raw_name"]
        res.setdefault("why", why)
        report.append(res)
        if res.get("out"):
            # 定稿必须过同一道质量闸，否则不留档（避免把封面页/版权页当成正文存下来）
            txt = open(res["out"], encoding="utf-8").read()
            ok = (len(txt) >= S.MIN_CHARS
                  and any(x in txt[:4000] for x in S.SECTIONS)
                  and S.BT.quality_ok(txt)[0])
            if not ok:
                try:
                    os.remove(res["out"])
                except OSError:
                    pass
                res["out"] = ""
                res["rejected"] = True
                print("     ✗ 定稿未过质量闸（多为封面/版权页或乱码），不留档")
                continue
            changed.append(res)
            print("     ✓ 已写入 %s｜%d 字 / 汉字 %d / 残留生僻 %d / 章节特征 %s / %.1fs"
                  % (os.path.basename(res["out"]), res["chars"], res["cjk"],
                     res["rare"], res["sec"], res["secs"]))
        elif res.get("error"):
            print("     ✗ %s" % res["error"])

    json.dump(report, open("/tmp/std_ocr_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    cf_rows = [r for r in report if r.get("conflicts")]
    if cf_rows and not a.dry:
        json.dump(cf_rows, open(CONFLICT_OUT, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print("\n完成：新增/更新 %d 部；明细 /tmp/std_ocr_report.json" % len(changed))


if __name__ == "__main__":
    main()
