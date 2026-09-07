#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《合规资讯周报》交付前质量门禁检测"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_DATAMOD = sys.argv[1] if len(sys.argv) > 1 else "weekly_data"
WD = __import__(_DATAMOD)
from pypdf import PdfReader

if len(sys.argv) > 2:
    PDF = sys.argv[2]
else:
    PDF = OUT_DIR = os.environ.get("CBR_OUT_DIR") or "/Users/luochen/Desktop/合规资讯简报"

# ---- 1. 收集报告全部字符 ----
def collect_all():
    M = WD.META
    D = WD.DATA
    parts = [M["title"], M["date_str"], M["header_text"], M["subtitle"], M["brief_en"],
             M["filename"], M["tagline"], "目　录", "本周处罚统计小结", "本期导读"]
    parts.extend(list(M["sections"].values()))
    parts.extend(D["summary"])
    for domain, items in D["policy"]:
        parts.append(domain)
        for it in items:
            parts.extend([it["title"], it["meta"], it["content"], it["analysis"], it.get("url", "")])
    for r in D["penalties"]:
        parts.extend(r)
    parts.extend(D["penalty_stats"])
    for t in D["pupu_items"]:
        parts.extend(t)
    parts.extend(D["outlook"])
    for row in D["matrix_rows"]:
        parts.extend(row)
    parts.extend(["风险主题", "采购", "仓储/加工", "线上运营", "配送", "会员营销", "用工",
                  "高", "中高", "中", "低", "—", "【要点】", "涉及业务环节：", "影响分析：",
                  "应对建议：", "解读：", "原文链接：", "时间", "监管机构", "涉及对象",
                  "违规事由", "处置措施", "第", "页", "共", "图1：朴朴超市合规风险热力矩阵",
                  "每周监管与合规动态", "1.", "2.", "3.", "4.", "5.", "6."])
    return "".join(parts)

all_text = collect_all()
src_chars = set(all_text)
cjk_src = [c for c in src_chars if '\u4e00' <= c <= '\u9fff']

# ---- 2. 提取 PDF 文本 ----
reader = PdfReader(PDF)
n_pages = len(reader.pages)
pdf_text = "".join((p.extract_text() or "") for p in reader.pages)
pdf_chars = set(pdf_text)

# ---- 3. 缺字检测（P0）----
missing = sorted(set(c for c in cjk_src if c not in pdf_chars))

# ---- 4. 链接注解统计 ----
n_links = 0
uri_annots = []
for p in reader.pages:
    if "/Annots" in p:
        for a in p["/Annots"]:
            obj = a.get_object()
            if obj.get("/Subtype") == "/Link" and "/A" in obj:
                act = obj["/A"].get_object()
                if act.get("/S") == "/URI":
                    n_links += 1
                    uri_annots.append(str(act.get("/URI", "")))

# ---- 5. 章节标题存在性 ----
sections_present = {sec: (sec in pdf_text) for sec in WD.META["sections"].values()}

# ---- 6. tofu 字符粗检 ----
tofu_like = [c for c in pdf_chars if c in "�"]

print("=" * 60)
print("质量门禁检测结果 · 合规资讯周报 2026-08-30")
print("=" * 60)
print(f"PDF 页数: {n_pages}")
print(f"报告用中文字符总数: {len(cjk_src)}")
print(f"PDF 提取中文字符总数: {len([c for c in pdf_chars if chr(0x4e00) <= c <= chr(0x9fff)])}")
print(f"缺失字符数: {len(missing)}")
if missing:
    print(f"缺失字符: {''.join(missing)}")
print(f"tofu 替换字符数: {len(tofu_like)}")
print(f"可点击链接数: {n_links}")
print("-" * 60)
for sec, ok in sections_present.items():
    print(f"[{'OK' if ok else 'MISSING'}] 章节: {sec}")
print("-" * 60)
print(f"缺字检测: {'通过 (0 缺字)' if not missing else '未通过'}")
print(f"链接检测: {n_links} 条 (应≥10 条官方链接)")

print("\n链接清单:")
for u in uri_annots:
    print("  " + u)

ok = (not missing) and n_links >= 10 and all(sections_present.values()) and not tofu_like
print("\n总体结论:", "通过，允许交付" if ok else "未通过，需修复")
sys.exit(0 if ok else 1)
