#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""算法合规治理专项数据源（多序列版）

发布主体与序列全景（全部为国家网信办官网原文，深链可直达）
========================================================
【A】互联网信息服务算法备案清单
    国家互联网信息办公室关于发布互联网信息服务算法备案信息的公告
    https://www.cac.gov.cn/2022-08/12/c_1661927474338504.htm （本页持续更新）
    附件 19 期（2022-08 → 2026-07），按双月/季度增量发布。
    表列：序号/算法名称/算法类别/主体名称/应用产品/主要用途/备案编号/备注
    —— 这是「算法推荐类」（个性化推送、检索过滤、排序精选、调度决策）的主序列。

【B】深度合成服务算法备案信息  ← 此前完全遗漏
    自 2023-06 起单独成序列，**按批编号（第一批 → 第十八批）**，
    每批一个公告页，附件为「境内深度合成服务算法备案清单（YYYY年M月）」docx。
    与【A】是**并列而非包含**关系（【A】2026-07 期 76 条中「生成合成类」仅 10 条）。

【C】生成式人工智能服务备案与登记
    https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm （本页持续更新）
    ⚠️ 同一份清单里**混装两类主体，必须拆开**：
      · 大模型**备案**：备案编号形如 `Jiangsu-ZhiBiaoBao-202512030061`（无 S），序号连续递增
      · 应用/功能**登记**：备案编号形如 `Guangdong-Dr.GDCDC-20260706S0054`（含 S），序号自 1 起
    判据：编号里出现 `\\d{8}S\\d+` 即「登记」。
    ⚠️ 该序列另有**年度汇总公告**（2024年、2025年）与**双月公告**并存，汇总类会把
    全年清单再列一遍，**累加即重复计数** → 单列入 aggregates.json，只做校验不参与合计。

【D】算法备案编号注销公告  ← 此前完全遗漏
    不定期发布（如「关于注销『仲帆PreWrite算法』等28个算法备案编号的公告」），
    附件 PDF。注销后才得到「**累计有效备案数** = 累计备案 − 注销」的正确口径。

【E】省级网信办属地公告（福建、江苏、新疆等）
    地方备案完成后**先行公告**，国家公告为**双月汇总**。
    实测：福建省网信办 2026-09-08 公告的 3 款（河图影像/智安智库/美柚智能助手）
    在国家级公告中 0 命中 —— 说明两者是**时间错位**关系，而非简单子集。
    → 主口径取国家级公告（权威、全量、含「属地」列，可直接做省级分布），
      地方公告仅作属地先行信息的补充，并入后按备案编号去重。

技术要点
--------
· 附件不是直链，而是 /cms/pub/interact/downloadfile.jsp?filepath=…&fText=…，
  **必须带 Referer** 才返回文件（否则回 HTML）。
· 附件 docx / pdf 混用（扩展名不可信），按魔数选解析器。
· 原始附件只落本机缓存（sources/.cache/algo，不入仓），入仓的是结构化 JSON。

用法：
  python3 tools/harvest_algo_filing.py            # 增量
  python3 tools/harvest_algo_filing.py --full     # 全量重抓
  python3 tools/harvest_algo_filing.py --only genai
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
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

# 【A】算法备案主序列（单页持续更新）
PAGE_ALGO = "https://www.cac.gov.cn/2022-08/12/c_1661927474338504.htm"
# 【C】生成式AI 备案与登记（单页持续更新）
PAGE_GENAI = "https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm"

# 【B】深度合成服务算法备案：第一批于 2023-06-20 发布（当时未写批号）
PAGES_DEEPFAKE = [
    ("2023-06", "http://www.cac.gov.cn/2023-06/20/c_1688910683316256.htm", "第一批"),
    ("2023-09", "http://www.cac.gov.cn/2023-09/01/c_1695224377544009.htm", "第二批"),
    ("2024-01", "http://www.cac.gov.cn/2024-01/05/c_1706119043746644.htm", "第三批"),
    ("2024-02", "http://www.cac.gov.cn/2024-02/18/c_1709925427424332.htm", "第四批"),
    ("2024-04", "https://www.cac.gov.cn/2024-04/11/c_1714509267496697.htm", "第五批"),
    ("2024-06", "https://www.cac.gov.cn/2024-06/12/c_1719783421546747.htm", "第六批"),
    ("2024-08", "https://www.cac.gov.cn/2024-08/05/c_1724541639039621.htm", "第七批"),
    ("2024-11", "https://www.cac.gov.cn/2024-11/01/c_1732152604917193.htm", "第八批"),
    ("2024-12", "https://www.cac.gov.cn/2024-12/20/c_1736389545949567.htm", "第九批"),
    ("2025-03", "https://www.cac.gov.cn/2025-03/12/c_1743480314931271.htm", "第十批"),
    ("2025-05", "https://www.cac.gov.cn/2025-05/19/c_1749365589879703.htm", "第十一批"),
    ("2025-07", "https://www.cac.gov.cn/2025-07/14/c_1754207718303963.htm", "第十二批"),
    ("2025-09", "https://www.cac.gov.cn/2025-09/11/c_1759222331638208.htm", "第十三批"),
    ("2025-11", "https://www.cac.gov.cn/2025-11/06/c_1764156698314535.htm", "第十四批"),
    ("2026-01", "https://www.cac.gov.cn/2026-01/07/c_1769516642440314.htm", "第十五批"),
    ("2026-03", "https://www.cac.gov.cn/2026-03/12/c_1775050837565188.htm", "第十六批"),
    ("2026-05", "https://www.cac.gov.cn/2026-05/06/c_1779809434590762.htm", "第十七批"),
    ("2026-07", "https://www.cac.gov.cn/2026-07/17/c_1786032856662750.htm", "第十八批"),
]

# 【D】注销公告（备案系统「信息公告」，附件 PDF）
PAGE_CANCEL_LIST = "https://beian.cac.gov.cn/api/notice/list"

# 【C】年度/半年度汇总公告（**全量清单，累加即重复** → 只做校验）
PAGES_AGGREGATE = [
    ("2024-04", "https://www.cac.gov.cn/2024-04/02/c_1713729983803145.htm",
     "首次全量公告（截至 2024-03 累计）"),
    ("2025-01", "https://www.cac.gov.cn/2025-01/08/c_1738034725920930.htm",
     "2024 年度汇总"),
    ("2026-01", "https://www.cac.gov.cn/2026-01/09/c_1769688009588554.htm",
     "2025 年度汇总"),
]

# 编号含 `YYYYMMDD S nnnn` 的属于「应用/功能登记」，否则属于「大模型备案」
RE_REGISTERED = re.compile(r"\d{8}\s*S\s*\d+", re.I)


def curl(url, referer=None, out=None, timeout=90):
    # ⚠️ cac.gov.cn 与 beian.cac.gov.cn 无 Referer 一律返回空（不是 403，是空体）
    if not referer:
        if "beian.cac.gov.cn" in url:
            referer = "https://beian.cac.gov.cn/"
        elif "cac.gov.cn" in url:
            referer = "https://www.cac.gov.cn/"
    cmd = ["curl", "-sSL", "-m", str(timeout), "-H", "User-Agent: " + UA]
    if referer:
        cmd += ["-H", "Referer: " + referer]
    cmd.append(url)
    if out:
        cmd += ["-o", out, "-w", "%{http_code}"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.stdout.strip()
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    return p.stdout


def attachments(html):
    """公告页 → [(附件名, 下载链接)]，去重保序。"""
    out = []
    for m in re.finditer(r'href="(/cms/pub/interact/downloadfile\.jsp\?[^"]+)"', html):
        href = unescape(m.group(1))
        q = {}
        for kv in href.split("?", 1)[1].split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                q[k] = unquote(v.replace("+", "%20"))
        name = (q.get("fText") or "").strip()
        if name:
            out.append((name, "https://www.cac.gov.cn" + href))
    seen, uniq = set(), []
    for n, u in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append((n, u))
    return uniq


def period_of(name):
    m = re.search(r"（(\d{4})年(\d{1,2})月）", name)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return ""


def docx_tables(path):
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


def pdf_flat(path):
    """注销公告只有文字（无表格），单独提全文。"""
    import pdfplumber
    parts = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            parts.append(pg.extract_text() or "")
    return "\n".join(parts)


def file_tables(path):
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:4] == b"%PDF":
        return pdf_tables(path)
    return docx_tables(path)


def norm_header(h):
    return re.sub(r"\s+", "", h or "")


def parse_table(rows, header_hint):
    for i, r in enumerate(rows):
        joined = "".join(r)
        if all(h in joined for h in header_hint):
            return r, rows[i + 1:]
    return None, []


def norm_id(s):
    return re.sub(r"[\s\u3000]", "", (s or "")).lower()


def download(url, cache_key, referer):
    os.makedirs(CACHE, exist_ok=True)
    ext = ".bin"
    p = os.path.join(CACHE, cache_key + ext)
    if os.path.exists(p) and os.path.getsize(p) > 2000:
        return p
    for _ in range(2):
        code = curl(url, referer=referer, out=p, timeout=180)
        if code == "200" and os.path.exists(p) and os.path.getsize(p) > 2000:
            with open(p, "rb") as f:
                hd = f.read(4)
            if hd[:4] == b"%PDF" or hd[:2] == b"PK":
                return p
        time.sleep(1.5)
    return None


def rows_of(path, hints):
    """附件 → (header, rows)，兼容跨页重复表头。"""
    try:
        tables = file_tables(path)
    except Exception:
        return None, []
    header, rows = None, []
    for tb in tables:
        hdr, data = parse_table(tb, hints)
        if not hdr:
            hdr, data = parse_table(tb, ["序号"])
        if hdr and header is None:
            header = [norm_header(c) for c in hdr]
            rows += [[str(x).strip() for x in r] for r in data]
        elif hdr and header is not None and len(hdr) >= len(header) - 1:
            rows += [[str(x).strip() for x in r] for r in data]
        elif header is not None:
            rows += [[str(x).strip() for x in r] for r in tb]
    return header, rows


def recordify(header, rows):
    recs = []
    for r in rows:
        r = (list(r) + [""] * len(header))[:len(header)]
        d = dict(zip(header, [re.sub(r"\s+", "", str(x)) for x in r]))
        if not any(v for k, v in d.items() if k not in ("序号", "编号")):
            continue
        recs.append(d)
    return recs


# =================================================== 【A】算法备案主序列
def harvest_algo(full):
    out = os.path.join(OUTDIR, "algo_filing.json")
    old = {} if full or not os.path.exists(out) else json.load(open(out, encoding="utf-8"))
    have = {b["name"] for b in old.get("batches", [])}
    print(f"\n=== 【A】互联网信息服务算法备案清单")
    html = curl(PAGE_ALGO, timeout=60)
    if len(html) < 2000:
        print("  ✗ 公告页抓取失败，保留原数据")
        return old.get("batches", [])
    batches = old.get("batches", [])
    for name, url in attachments(html):
        if name in have:
            continue
        p = download(url, "algo_" + re.sub(r"[^\w\-]", "_", period_of(name) or name[:16]),
                     PAGE_ALGO)
        if not p:
            print(f"  ! {name} 下载失败")
            continue
        header, rows = rows_of(p, ["备案编号", "主体名称"])
        if not header:
            print(f"  ! {name} 表结构未识别")
            continue
        recs = recordify(header, rows)
        batches.append({"period": period_of(name) or name[:16], "name": name,
                        "url": url, "page": PAGE_ALGO,
                        "count": len(recs), "header": header, "rows": recs,
                        "series": "算法备案"})
        print(f"  ✓ {period_of(name)}　{len(recs)} 条　{header}")
        time.sleep(0.5)
    batches.sort(key=lambda x: x["period"])
    return batches


# =================================================== 【B】深度合成序列
def harvest_deepfake(full):
    out = os.path.join(OUTDIR, "deepfake_filing.json")
    old = {} if full or not os.path.exists(out) else json.load(open(out, encoding="utf-8"))
    have = {b["period"] for b in old.get("batches", [])}
    print(f"\n=== 【B】深度合成服务算法备案（第一批 → 第十八批）")
    batches = old.get("batches", [])
    for period, page, batch_label in PAGES_DEEPFAKE:
        if period in have and not full:
            continue
        html = curl(page, timeout=60)
        if len(html) < 1500:
            print(f"  ! {batch_label} 公告页抓取失败 {page}")
            continue
        atts = attachments(html)
        if not atts:
            print(f"  ! {batch_label} 无附件")
            continue
        name, url = atts[0]
        p = download(url, f"deepfake_{period}", page)
        if not p:
            print(f"  ! {batch_label} 附件下载失败 {name}")
            continue
        header, rows = rows_of(p, ["备案编号"])
        if not header:
            print(f"  ! {batch_label} 表结构未识别 {header}")
            continue
        recs = recordify(header, rows)
        batches.append({"period": period, "batch": batch_label, "name": name,
                        "url": url, "page": page, "count": len(recs),
                        "header": header, "rows": recs, "series": "深度合成备案"})
        print(f"  ✓ {batch_label}（{period}）　{len(recs)} 条　{header}")
        time.sleep(0.5)
    batches.sort(key=lambda x: x["period"])
    return batches


# ============================================ 【C】生成式AI（拆备案/登记）
def harvest_genai(full):
    out = os.path.join(OUTDIR, "genai_filing.json")
    old = {} if full or not os.path.exists(out) else json.load(open(out, encoding="utf-8"))
    have = {b["period"] for b in old.get("batches", [])}
    print(f"\n=== 【C】生成式人工智能服务备案与登记")
    html = curl(PAGE_GENAI, timeout=60)
    if len(html) < 2000:
        print("  ✗ 公告页抓取失败，保留原数据")
        return old.get("batches", [])
    batches = old.get("batches", [])
    for name, url in attachments(html):
        per = period_of(name) or name[:16]
        if per in have and not full:
            continue
        p = download(url, "genai_" + re.sub(r"[^\w\-]", "_", per), PAGE_GENAI)
        if not p:
            print(f"  ! {per} 附件下载失败")
            continue
        # 一个附件内含多张表（备案表 + 登记表 + 端侧表），逐表保留来源，便于拆分
        try:
            tables = file_tables(p)
        except Exception as e:
            print(f"  ! {per} 解析失败 {e}")
            continue
        header, rows, segs = None, [], []
        for tb in tables:
            # ⚠️ PDF 转出的表会跨页拆成多张：**首张有表头，后续是续表（首行即数据）**。
            # 早先只认含表头关键字的那张 → 续表被整张丢弃（2026-08 期 257 条只剩 49 条）。
            hdr, data = parse_table(tb, ["备案编号"] if "备案编号" in "".join(tb[0])
                                    else ["备案"])
            if hdr:
                hh = [norm_header(c) for c in hdr]
            elif header and len(tb[0]) >= len(header) - 1:
                hh, data = header, tb           # 续表：沿用上一张表的表头
            else:
                hdr2, data2 = parse_table(tb, ["序号"])
                if not hdr2:
                    continue
                hh, data = [norm_header(c) for c in hdr2], data2
            if header is None:
                header = hh
            recs = []
            for r in data:
                r = (list(r) + [""] * len(hh))[:len(hh)]
                d = dict(zip(hh, [re.sub(r"\s+", "", str(x)) for x in r]))
                if any(v for k, v in d.items() if k != "序号"):
                    recs.append(d)
            segs.append({"header": hh, "rows": recs})
            rows += recs
        if not header:
            print(f"  ! {per} 表结构未识别")
            continue
        # 拆 备案 / 登记
        for s in segs:
            key = "备案编号" if "备案编号" in s["header"] else \
                  ("备案号" if "备案号" in s["header"] else None)
            for r in s["rows"]:
                rid = r.get(key, "") if key else ""
                r["_kind"] = "登记" if RE_REGISTERED.search(rid) else "备案"
        kept = [r for s in segs for r in s["rows"]]
        n_b = sum(1 for r in kept if r["_kind"] == "备案")
        n_r = sum(1 for r in kept if r["_kind"] == "登记")
        # 端侧模型（表头带「适用场景」）单列，避免与主表混计
        n_edge = sum(1 for s in segs if any("适用场景" in h for h in s["header"])
                     for _ in s["rows"])
        batches.append({"period": per, "name": name, "url": url, "page": PAGE_GENAI,
                        "count": len(kept), "n_beian": n_b, "n_dengji": n_r,
                        "n_edge": n_edge, "header": header, "rows": kept,
                        "series": "生成式AI备案与登记", "aggregate": False})
        print(f"  ✓ {per}　合计 {len(kept)}（备案 {n_b} / 登记 {n_r} / 端侧 {n_edge}）")
        time.sleep(0.5)
    batches.sort(key=lambda x: x["period"])
    return batches


# ==================================================== 【D】注销公告
def harvest_cancel():
    """注销公告。

    两个坑（都踩过）：
    ① 附件真实入口是 `api/file/fileDownLoad?noticeId=<noticeId>`。
       公告 content 里给的 `/static/fileUpload/...pdf` 静态路径会随服务器文件清理而 **404**
       （7 份实测全部 404），挂上站点就是失效链接。noticeId 才是不变的稳定键。
    ② 附件是**真表格**（序号/算法名称/角色/主体名称/应用产品/主要用途/备案编号/注销时间），
       不要用「正文里数『XX算法』」的土办法。且表格**跨页续表**里会插入「上一行文字的残余碎片」
       （首列空、第 6 列是半句话），必须用「**首列是纯数字**」筛掉，否则 57 条会多数出 5 条。
    ③ 标题里「等 N 个」有时不写数量（实测 2 份），只能靠解析表行得到真实条数 → 一律以表行为准。
    """
    print(f"\n=== 【D】算法备案编号注销公告")
    raw = curl(PAGE_CANCEL_LIST, referer="https://beian.cac.gov.cn/", timeout=45)
    try:
        items = json.loads(raw)["datas"]
    except Exception:
        print("  ✗ 公告列表获取失败")
        return []
    recs = []
    for x in items:
        title = (x.get("title") or "").strip()
        if "注销" not in title:
            continue
        nid = x.get("noticeId") or ""
        if not nid:
            continue
        # noticeId 稳定深链，替代会 404 的 /static/... 静态路径
        url = "https://beian.cac.gov.cn/api/file/fileDownLoad?noticeId=" + nid
        dt = (x.get("createTime") or "")[:10]
        p = download(url, "cancel_" + re.sub(r"\W+", "_", dt + title)[:48],
                     "https://beian.cac.gov.cn/")
        rows = []
        if p and open(p, "rb").read(4) == b"%PDF":
            try:
                for tb in pdf_tables(p):
                    for r in tb:
                        # 首列必须是纯序号 → 滤掉续表碎片行
                        if len(r) >= 8 and r[0].isdigit():
                            rows.append({"name": r[1], "role": r[2], "entity": r[3],
                                         "product": r[4], "code": r[6], "cancel": r[7]})
            except Exception as e:
                print(f"  ! {dt} 解析异常 {e}")
        # 同一备案编号只留一次
        seen = set()
        uniq = []
        for r in rows:
            if r["code"] and r["code"] in seen:
                continue
            if r["code"]:
                seen.add(r["code"])
            uniq.append(r)
        recs.append({"date": dt, "title": title, "noticeId": nid, "url": url,
                     "count": len(uniq), "records": uniq})
        flag = "" if uniq else "  ⚠️ 未解析到明细"
        print(f"  ✓ {dt}　{len(uniq)} 条　{title[:40]}{flag}")
        time.sleep(0.4)
    recs.sort(key=lambda r: r["date"])
    return recs


# ============================================ 【C2】年度汇总（只做校验）
def harvest_aggregate():
    print(f"\n=== 【C2】生成式AI 年度/全量汇总公告（不参与累加，仅作校验）")
    out = []
    for period, page, label in PAGES_AGGREGATE:
        html = curl(page, timeout=60)
        if len(html) < 1500:
            print(f"  ! {label} 抓取失败")
            continue
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", unescape(text))
        nums = {k: v for k, v in re.findall(
            r"累计[^。]{0,20}?(\d+)\s*款|(\d+)\s*款[^。]{0,10}?完成(?:备案|登记)", text)}
        # 直接抽公告里的官方累计口径
        cum = re.search(r"累计(?:有)?\s*(\d+)\s*款生成式人工智能服务完成备案", text)
        dji = re.search(r"(\d+)\s*款生成式人工智能应用或功能完成登记", text)
        out.append({"period": period, "label": label, "page": page,
                    "cum_beian": int(cum.group(1)) if cum else None,
                    "cum_dengji": int(dji.group(1)) if dji else None})
        print(f"  · {label}：累计备案 {out[-1]['cum_beian']}　累计登记 {out[-1]['cum_dengji']}")
    return out


def write(path, payload):
    json.dump(payload, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"  → {os.path.basename(path)}  {os.path.getsize(path)/1024:.0f} KB")


def main():
    argv = sys.argv[1:]
    full = "--full" in argv
    only = argv[argv.index("--only") + 1] if "--only" in argv else ""
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    today = date.today().isoformat()

    if only in ("", "algo"):
        b = harvest_algo(full)
        if b:
            write(os.path.join(OUTDIR, "algo_filing.json"), {
                "meta": {"title": "互联网信息服务算法备案信息公告", "org": "国家互联网信息办公室",
                         "page": PAGE_ALGO, "kind": "算法备案", "series": "增量",
                         "updated": today, "batches": len(b),
                         "records": sum(x["count"] for x in b),
                         "note": "全国统一序列，含个性化推送类/检索过滤类/排序精选类/调度决策类等；"
                                 "清单按双月或季度增量发布，各期备案编号互不重复。"},
                "batches": b})
    if only in ("", "deepfake"):
        b = harvest_deepfake(full)
        if b:
            write(os.path.join(OUTDIR, "deepfake_filing.json"), {
                "meta": {"title": "深度合成服务算法备案信息公告",
                         "org": "国家互联网信息办公室", "kind": "深度合成算法备案",
                         "series": "按批（第一批 → 第十八批）", "updated": today,
                         "batches": len(b), "records": sum(x["count"] for x in b),
                         "note": "依据《互联网信息服务深度合成管理规定》履行备案手续的"
                                 "深度合成服务提供者与技术支持者清单，与「互联网信息服务"
                                 "算法备案清单」为并列序列，按备案编号去重。"},
                "batches": b})
    if only in ("", "genai"):
        b = harvest_genai(full)
        if b:
            nb = sum(x.get("n_beian", 0) for x in b)
            nr = sum(x.get("n_dengji", 0) for x in b)
            write(os.path.join(OUTDIR, "genai_filing.json"), {
                "meta": {"title": "生成式人工智能服务已备案信息公告",
                         "org": "国家互联网信息办公室", "kind": "生成式AI备案与登记",
                         "series": "增量（双月）", "updated": today, "batches": len(b),
                         "records": sum(x["count"] for x in b),
                         "n_beian": nb, "n_dengji": nr,
                         "note": "「备案」（大模型，编号无 S，由国家网信办受理）与"
                                 "「登记」（应用/功能，编号含 YYYYMMDDSnnnn，由属地网信办受理）"
                                 "两类主体混装于同一清单，已按编号拆分。"
                                 "另有年度/全量汇总公告另存 aggregates.json，不参与累加。"},
                "batches": b})
    if only in ("", "cancel"):
        c = harvest_cancel()
        if c:
            write(os.path.join(OUTDIR, "cancel.json"), {
                "meta": {"updated": today, "notices": len(c),
                         "cancelled": sum(x["count"] for x in c),
                         "source": "beian.cac.gov.cn/api/notice/list（免登录）→ 逐份公告 PDF 附件按 noticeId 直取",
                         "note": "算法备案编号注销公告；累计有效备案数 = 累计备案 − 累计注销。"
                                 "注销编号会随时间继续累积，故本表为「截至更新日」口径。"},
                "notices": c})
    if only in ("", "aggregate"):
        a = harvest_aggregate()
        if a:
            write(os.path.join(OUTDIR, "aggregates.json"), {
                "meta": {"updated": today, "note": "年度/全量汇总公告，**不参与累加**，"
                                                    "仅用于校验分批累加结果与官方口径是否一致。"},
                "aggregates": a})
    return 0


if __name__ == "__main__":
    sys.exit(main())
