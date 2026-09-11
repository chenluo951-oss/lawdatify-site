#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把国标「整页截图 + OCR 定稿」归档进本机标准库，供私有仓库长期保存。

产出（每份标准一个目录）：
  <本机标准库>/国标（截图+OCR）/GB_T_35273-2020/
      GB_T_35273-2020 全文（OCR）.txt      —— 三轮 OCR 比对后的定稿正文
      GB_T_35273-2020 截图合集.pdf          —— 全部整页截图（灰度下采样，体积可控）
      GB_T_35273-2020 待复核清单.json       —— 三轮不一致处，供人工校对

截图原图（sources/scans/，约 1 MB/页）只留本机：随时可从 openstd 重跑复原，
不往私有仓库堆放大图；归档用下采样 PDF 兼顾体积与可读性。

用法：python archive_scans.py [--code GB/T 35273-2020]
"""
import os
import re
import sys
import json
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H  # noqa: E402

SCAN_DIR = os.path.join(HERE, "sources", "scans")
DEST = os.path.join(H.STORE, "国标（截图+OCR）")


def build_pdf(pngs, out, width=1000):
    from PIL import Image
    pages = []
    for p in pngs:
        im = Image.open(p).convert("L")
        if im.width > width:
            im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
        pages.append(im)
    if not pages:
        return 0
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:],
                  resolution=150.0, quality=72)
    return os.path.getsize(out)


def one(code_dir):
    d = os.path.join(SCAN_DIR, code_dir)
    imgd = os.path.join(d, "img")
    if not os.path.isdir(imgd):
        return None
    txts = [f for f in os.listdir(imgd) if f.endswith(".txt")]
    if not txts:
        return None
    txt = os.path.join(imgd, txts[0])
    stem = os.path.splitext(txts[0])[0]
    pngs = sorted(os.path.join(imgd, f) for f in os.listdir(imgd)
                  if f.startswith("page-") and f.endswith(".png"))
    outd = os.path.join(DEST, code_dir)
    os.makedirs(outd, exist_ok=True)

    t_dst = os.path.join(outd, stem + " 全文（OCR）.txt")
    if not os.path.exists(t_dst) or os.path.getmtime(t_dst) < os.path.getmtime(txt):
        shutil.copy2(txt, t_dst)
    rv = os.path.join(imgd, "_review.json")
    if os.path.exists(rv):
        shutil.copy2(rv, os.path.join(outd, stem + " 待复核清单.json"))
    p_dst = os.path.join(outd, stem + " 截图合集.pdf")
    if pngs and (not os.path.exists(p_dst) or os.path.getmtime(p_dst) < os.path.getmtime(pngs[-1])):
        size = build_pdf(pngs, p_dst)
    else:
        size = os.path.getsize(p_dst) if os.path.exists(p_dst) else 0
    return {"code_dir": code_dir, "pages": len(pngs),
            "chars": os.path.getsize(t_dst) if os.path.exists(t_dst) else 0,
            "pdf_kb": round(size / 1024)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="只归档某一项（目录名或标准号）")
    a = ap.parse_args()
    os.makedirs(DEST, exist_ok=True)
    dirs = [a.code] if a.code else sorted(os.listdir(SCAN_DIR))
    for cd in dirs:
        if not os.path.isdir(os.path.join(SCAN_DIR, cd)):
            continue
        r = one(cd)
        if r:
            print("  %-22s 截图 %3d 页 → PDF %5d KB，定稿 %6d 字节"
                  % (r["code_dir"], r["pages"], r["pdf_kb"], r["chars"]), flush=True)
    print("归档目录：%s" % DEST)


if __name__ == "__main__":
    main()
