#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""算法合规治理专项数据源：算法备案库 + 生成式AI（大模型）备案/登记库

数据来源（全部为官方原文，深链为网信办官网站内页 + 附件下载接口）
--------------------------------------------------------------
1) 算法备案：国家网信办《关于发布互联网信息服务算法备案信息的公告》
   https://www.cac.gov.cn/2022-08/12/c_1661927474338504.htm
   该页「后续持续更新」，附件 1~N = 境内互联网信息服务算法备案清单（按批次月）——
   即算法备案的**权威全量清单**（含个性化推送/检索过滤/排序精选/调度决策/生成合成各类）。
2) 生成式AI 备案与登记：《关于发布生成式人工智能服务已备案信息的公告》
   https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm（含 2024-04 起各批次附件）
   附件 = 生成式人工智能服务「已备案」与「已登记」信息（大模型备案 + AI 应用登记）。

技术要点
--------
· 附件不是直链，而是 /cms/pub/interact/downloadfile.jsp?filepath=<加密串>&fText=<文件名>，
  必须带 Referer 才会返回文件（否则回 HTML）。
· 附件格式为 .docx，用 zipfile + ElementTree 直接解 word/document.xml 的表格，零依赖。
· 原始 docx 只落本机缓存（sources/.cache/algo，不入仓），入仓的是解析后的结构化 JSON。

用法：
  python3 tools/harvest_algo_filing.py             # 增量（已有批次跳过）
  python3 tools/harvest_algo_filing.py --full      # 全量重抓
"""
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import date
from html import unescape
from urllib.parse import unquote, quote
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(HERE, "sources", "algo")
CACHE = os.path.join(HERE, "sources", ".cache", "algo")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

PAGES = {
    "algo": {
        "url": "https://www.cac.gov.cn/2022-08/12/c_1661927474338504.htm",
        "title": "国家互联网信息办公室关于发布互联网信息服务算法备案信息的公告",
        "org": "国家互联网信息办公室",
        "out": "algo_filing.json",
        "kind": "算法备案",
    },
    "genai": {
        "url": "https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm",
        "title": "国家互联网信息办公室关于发布生成式人工智能服务已备案信息的公告",
        "org": "国家互联网信息办公室",
        "out": "genai_filing.json",
        "kind": "生成式AI备案与登记",
    },
}


def curl(url, referer=None, out=None, timeout=90):
    cmd = ["curl", "-sL", "-m", str(timeout), url, "-H", "User-Agent: " + UA]
    if referer:
        cmd += ["-H", "Referer: " + referer]
    if out:
        cmd += ["-o", out, "-w", "%{http_code}"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.stdout.strip()
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout


def attachments(html, page_url):
    """从公告页提取 (附件名, 下载链接)。"""
    out = []
    for m in re.finditer(r'href="(/cms/pub/interact/downloadfile\.jsp\?[^"]+)"', html):
        href = unescape(m.group(1))
        q = {}
        for kv in href.split("?", 1)[1].split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                q[k] = unquote(v.replace("+", "%20"))
        name = (q.get("fText") or "").strip()
        if not name:
            continue
        out.append((name, "https://www.cac.gov.cn" + href, q.get("filepath", "")))
    # 去重（同名只留一个）
    seen, uniq = set(), []
    for n, u, fp in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append((n, u, fp))
    return uniq


def period_of(name):
    m = re.search(r"（(\d{4})年(\d{1,2})月）", name)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return ""


def docx_tables(path):
    """docx → 表头 + 数据行（纯标准库解析）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)

    def cell(tc):
        return re.sub(r"\s+", " ", "".join(t.text or "" for t in tc.findall(".//w:t", NS))).strip()

    tables = []
    for tb in root.findall(".//w:tbl", NS):
        rows = [[cell(tc) for tc in tr.findall("./w:tc", NS)] for tr in tb.findall("./w:tr", NS)]
        rows = [r for r in rows if any(r)]
        if len(rows) >= 2:
            tables.append(rows)
    return tables


def pdf_tables(path):
    """PDF 附件 → 表头 + 数据行（附件有 docx 也有 pdf，实测两批格式混用）。"""
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for tb in page.extract_tables() or []:
                rows = [[re.sub(r"\s+", " ", (c or "")).strip() for c in r] for r in tb]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    out.append(rows)
    return out


def file_tables(path):
    """按真实文件类型选解析器（扩展名不可信，看魔数）。"""
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:4] == b"%PDF":
        return pdf_tables(path)
    return docx_tables(path)


def parse_table(rows, header_hint):
    """在表中找到含 header_hint 的表头行，返回 (header, 数据行列表)。"""
    for i, r in enumerate(rows):
        joined = "".join(r)
        if all(h in joined for h in header_hint):
            return r, rows[i + 1:]
    return None, []


def norm_header(h):
    h = h.replace(" ", "").replace("\n", "")
    return h


def main():
    full = "--full" in sys.argv
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    summary = {}
    for key, cfg in PAGES.items():
        outpath = os.path.join(OUTDIR, cfg["out"])
        old = {}
        if os.path.exists(outpath) and not full:
            try:
                old = json.load(open(outpath, encoding="utf-8"))
            except Exception:
                old = {}
        have = {b["period"] for b in old.get("batches", [])}
        print(f"\n=== {cfg['kind']}　{cfg['url']}")
        html = curl(cfg["url"], timeout=60)
        if len(html) < 2000:
            print("  ✗ 公告页抓取失败，保留原数据"); continue
        atts = attachments(html, cfg["url"])
        print(f"  附件 {len(atts)} 个：{[a[0] for a in atts][:4]} …")
        batches = old.get("batches", [])
        byp = {b["period"]: b for b in batches}
        for name, url, fp in atts:
            per = period_of(name) or name[:20]
            if per in have and not full:
                print(f"  · 已有 {per}，跳过")
                continue
            cache = os.path.join(CACHE, key + "_" + re.sub(r"[^\w\-]", "_", per) + ".bin")
            got = False
            for attempt in range(2):
                code = curl(url, referer=cfg["url"], out=cache, timeout=180)
                if code == "200" and os.path.exists(cache) and os.path.getsize(cache) > 2000:
                    with open(cache, "rb") as f:
                        hd = f.read(4)
                    if hd[:4] == b"%PDF" or hd[:2] == b"PK":
                        got = True
                        break
                time.sleep(1.5)
            if not got:
                print(f"  ! {per} 附件下载失败")
                continue
            try:
                tables = file_tables(cache)
            except Exception as e:
                print(f"  ! {per} 解析失败 {e}")
                continue
            rows = []
            header = None
            hint = ["备案编号", "主体名称"] if key == "algo" else ["备案", "登记"]
            for tb in tables:
                hdr, data = parse_table(tb, hint)
                if not hdr:
                    hdr, data = parse_table(tb, ["序号"])
                if hdr and header is None:
                    header = [norm_header(c) for c in hdr]
                    rows += [list(map(str, r)) for r in data]
                elif hdr and header is not None and len(hdr) >= len(header) - 1:
                    # 跨页重复表头：丢掉表头行，只取数据
                    rows += [list(map(str, r)) for r in data]
                else:
                    rows += [list(map(str, r)) for r in tb]
            if not rows or not header:
                print(f"  ! {per} 表结构未识别（表数 {len(tables)}）")
                continue
            recs = []
            for r in rows:
                r = (list(r) + [""] * len(header))[:len(header)]
                d = dict(zip(header, [str(x).strip() for x in r]))
                if not any(v for k, v in d.items() if k != "序号"):
                    continue
                recs.append(d)
            byp[per] = {
                "period": per,
                "name": name,
                "url": url,
                "page": cfg["url"],
                "count": len(recs),
                "header": header,
                "rows": recs,
            }
            print(f"  ✓ {per}　{len(recs)} 条　表头 {header}")
            time.sleep(0.6)
        batches = sorted(byp.values(), key=lambda x: x["period"])
        total = sum(b["count"] for b in batches)
        json.dump({
            "meta": {
                "title": cfg["title"],
                "org": cfg["org"],
                "page": cfg["url"],
                "kind": cfg["kind"],
                "updated": date.today().isoformat(),
                "batches": len(batches),
                "records": total,
                "note": "清单取自国家网信办官网公告附件（docx 表格逐行解析）；"
                        "备案号/主体随主体变更与注销会动态调整，以网信办官网为准。",
            },
            "batches": batches,
        }, open(outpath, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print(f"  ✓ 写入 {cfg['out']}：{len(batches)} 批次 / {total} 条　"
              f"{os.path.getsize(outpath) / 1024:.0f} KB")
        summary[key] = (len(batches), total)
    for k, (b, t) in summary.items():
        print(f"  {k}: {b} 批次 {t} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
