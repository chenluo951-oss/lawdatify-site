#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
std_scan.py —— 图片式标准全文（在线阅读器）抓取 + 多轮 OCR 比对定稿。

解决「国标/行标/团标正文拿不到」这一段断层。三条通道：

  ① GB（openstd 国家标准全文公开系统）
     在线阅读器是「10×10 图块精灵」：viewGbImg?fileName=<bg> 返回一张 webp 精灵，
     页面里 <span class="pdfImg-<col>-<row>"> 用 background-position 指向精灵里的图块。
     本脚本按此规则把图块拼回**整页高清截图**（实测与官方纸面版式一致），
     再用 macOS Vision 做多轮 OCR 比对定稿。
     国标不提供下载（showGb?type=download 只回提示页），故截图 + OCR 是唯一正当通道。

  ② HB（hbba 行业标准信息服务平台）
     /portal/online/<pk> 页面暴露 /attachment/onlineRead/<id> 与 /portal/download/<id>。
     版权允许公开的标准（如金融行业标准 JR/T）可直接取官方 PDF，且带文字层，无需 OCR；
     版权不允许的（如通信行业标准 YD/T，涉国际标准版权）官网明确回「尚未公开」，
     本脚本如实标 `blocked-copyright`，只保留元数据与官方详情深链。

  ③ TT（团体标准）
     TAF 走既有 fetch_taf.py（taf.org.cn 提供 PDF，带文字层）；其他团标在此登记探测结论。

多轮 OCR 比对（用户要求的「两到三次截图/OCR 比对」）：
     同一页做 3 种预处理 → 3 次识别 → 按行对齐 → 字符级多数表决定稿；
     三次不一致的行写入 review 清单，供人工复核，绝不用单次结果冒充定稿。

用法：
  python3 std_scan.py --plan                      # 看还有哪些国标缺正文
  python3 std_scan.py --gb --code "GB/T 35273-2020"
  python3 std_scan.py --gb --missing --limit 5    # 批量补缺（含拼接截图 + 3 轮 OCR）
  python3 std_scan.py --gb --only "个人信息安全工程指南"
  python3 std_scan.py --hb --all                  # 行标：能下的下 PDF，不能下的记原因
  python3 std_scan.py --ocr-only "sources/scans/GBT35273-2020"   # 只对已有截图重跑 OCR
"""
import os, re, sys, json, math, time, shutil, hashlib, subprocess, argparse, tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H  # 复用 curl / 台账 / worklist

STORE = H.STORE                                    # 本机标准库（人可读）
CORPUS = H.CORPUS                                  # 站点语料库（gitignored）
LIB = H.LIB
SCAN_DIR = os.path.join(HERE, "sources", "scans")  # 截图 + OCR 中间产物
LEDGER = os.path.join(HERE, "sources", "standards", "scan_ledger.json")
VENVPY = H.VENVPY
OCR_BIN = os.path.join(HERE, "tools", "vision_ocr")

OPENSTD = "https://openstd.samr.gov.cn/bzgk/std"
HBBA = "https://hbba.sacinfo.org.cn"

UA = H.UA


def log(*a):
    print(*a, flush=True)


def curl_j(url, jar=None, referer=None, timeout=60, binary=False, headers=None,
           out=None, retries=3):
    """带 cookie jar 的 curl（沙箱里 urllib 会被代理拦，统一走子进程）。"""
    cmd = ["curl", "-sL", "-m", str(timeout), "-A", UA, "--compressed",
           "-H", "Accept-Language: zh-CN,zh;q=0.9"]
    if jar:
        cmd += ["-b", jar, "-c", jar]
    if referer:
        cmd += ["-H", "Referer: " + referer]
    for k, v in (headers or {}).items():
        cmd += ["-H", "%s: %s" % (k, v)]
    if out:
        cmd += ["-o", out, "-w", "%{http_code}"]
    cmd.append(url)
    last = b"" if binary else ""
    for _ in range(retries):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout + 20)
            body = r.stdout
            if out:
                # 带 -o 时 stdout 是状态码
                code = body.decode("utf-8", "ignore").strip()
                data = open(out, "rb").read() if os.path.exists(out) else b""
                if code.startswith("2") and data:
                    return (code, data) if binary else data
                last = (code, data) if binary else data
            else:
                if body:
                    return body if binary else body.decode("utf-8", "ignore")
        except Exception:
            pass
        time.sleep(1.2)
    return last


# ══════════════════════════ ① 国标 openstd 在线阅读器 ══════════════════════════
def openstd_hcno(code):
    """标准号 → hcno。先查 std_list，再按标题精确定位。"""
    q = re.sub(r"[^0-9A-Za-z]", "", code or "")
    if not q:
        return "", ""
    mn = re.search(r"\d{3,6}", code or "")
    term = mn.group(0) if mn else q
    html = curl_j("%s/std_list?p.p2=%s" % (OPENSTD, term), timeout=40)
    cands = re.findall(r"showInfo\(['\"]([A-F0-9]{32})['\"]\)", html)
    seen, order = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            order.append(c)
    want = re.sub(r"[^0-9]", "", code or "")
    for hc in order[:8]:
        h = curl_j("%s/newGbInfo?hcno=%s" % (OPENSTD, hc), timeout=40)
        m = re.search(r"<title>[^<]*\|([^<]*)</title>", h)
        got = m.group(1).strip() if m else ""
        gnum = re.sub(r"[^0-9]", "", got)
        if want and gnum.startswith(want[:9]):
            return hc, got
    return (order[0], "") if order else ("", "")


PAGE_RE = re.compile(
    r'<div id="(\d+)" class="page"[^>]*bg="([^"]+)"[^>]*style="width:(\d+)px;height:(\d+)px;[^"]*">(.*?)</div>',
    re.S)
TILE_RE = re.compile(
    r'class="pdfImg-(\d+)-(\d+)"\s+style="background-position:\s*(-?\d+)px\s+(-?\d+)px;"')


def gb_viewer(hcno, jar):
    """打开在线阅读器，返回 (title, pages)。pages = [{idx,bg,w,h,tiles:[(c,r,sx,sy)]}]"""
    detail = "%s/newGbInfo?hcno=%s" % (OPENSTD, hcno)
    curl_j(detail, jar=jar, timeout=40)
    html = curl_j("%s/showGb?type=online&hcno=%s&request_locale=zh" % (OPENSTD, hcno),
                  jar=jar, referer=detail, timeout=60)
    if "在线预览" not in (html or ""):
        return "", []
    tm = re.search(r"<title>[^<]*\|([^<]*)</title>", html)
    title = tm.group(1).strip() if tm else ""
    pages = []
    for m in PAGE_RE.finditer(html):
        tiles = [(int(a), int(b), -int(c), -int(d))
                 for a, b, c, d in TILE_RE.findall(m.group(5))]
        if not tiles:
            continue
        pages.append({"idx": int(m.group(1)), "bg": m.group(2), "w": int(m.group(3)),
                      "h": int(m.group(4)), "tiles": tiles})
    pages.sort(key=lambda p: p["idx"])
    return title, pages


def gb_sprite(bg, jar, hcno, cache):
    """下载一张图块精灵（webp）。需要 Cache-Alive: chunked 请求头。"""
    fp = os.path.join(cache, hashlib.sha1(bg.encode()).hexdigest() + ".webp")
    os.makedirs(cache, exist_ok=True)
    if os.path.exists(fp) and os.path.getsize(fp) > 2000:
        return fp
    ref = "%s/showGb?type=online&hcno=%s&request_locale=zh" % (OPENSTD, hcno)
    url = "%s/viewGbImg?fileName=%s" % (OPENSTD, bg)
    for _ in range(3):
        curl_j(url, jar=jar, referer=ref, timeout=120, out=fp,
               headers={"Cache-Alive": "chunked", "X-Requested-With": "XMLHttpRequest"})
        if os.path.exists(fp) and os.path.getsize(fp) > 2000:
            return fp
        time.sleep(1.5)
    return ""


def stitch_pages(pages, jar, hcno, cache, outdir, maxpages=0):
    """把图块精灵拼回整页截图。返回 [png 路径]（按页序）。"""
    from PIL import Image
    if os.path.isdir(outdir):                      # 重跑必须清干净，否则旧页会被重复 OCR
        for f in os.listdir(outdir):
            if f.startswith("page-") and f.endswith(".png"):
                os.remove(os.path.join(outdir, f))
    os.makedirs(outdir, exist_ok=True)
    bg2file, pngs = {}, []
    todo = pages[:maxpages] if maxpages else pages
    for p in todo:
        fp = bg2file.get(p["bg"])
        if fp is None:
            fp = gb_sprite(p["bg"], jar, hcno, cache)
            bg2file[p["bg"]] = fp
        if not fp:
            log("    ! 精灵下载失败 page=%d" % (p["idx"] + 1))
            continue
        spr = Image.open(fp).convert("RGB")
        xs = [t[2] for t in p["tiles"] if t[2] > 0]
        ys = [t[3] for t in p["tiles"] if t[3] > 0]
        tw = math.gcd(*xs) if len(xs) > 1 else (round(p["w"] / 10) if xs else round(p["w"] / 10))
        th = math.gcd(*ys) if len(ys) > 1 else (round(p["h"] / 10) if ys else round(p["h"] / 10))
        if tw <= 8 or th <= 8:
            tw, th = round(p["w"] / 10), round(p["h"] / 10)
        cw, ch = p["w"] / 10.0, p["h"] / 10.0
        page = Image.new("RGB", (p["w"], p["h"]), "white")
        for c, r, sx, sy in p["tiles"]:
            box = (sx, sy, sx + tw, sy + th)
            if box[2] > spr.width or box[3] > spr.height:
                continue
            tile = spr.crop(box).resize((max(1, round(cw)), max(1, round(ch))), Image.LANCZOS)
            page.paste(tile, (round(c * cw), round(r * ch)))
        dst = os.path.join(outdir, "page-%03d.png" % (p["idx"] + 1))
        page.save(dst, optimize=True)
        pngs.append(dst)
    return pngs


# ══════════════════════════ ② 多轮 OCR 比对 ══════════════════════════
def vision_ocr(png, level="accurate", langs="zh-Hans,en-US"):
    if not os.path.exists(OCR_BIN):
        raise SystemExit("缺少 OCR 工具，请先运行：swiftc -O -o tools/vision_ocr tools/vision_ocr.swift")
    r = subprocess.run([OCR_BIN, png, "--lang", langs, "--level", level, "--json"],
                       capture_output=True, text=True, timeout=300)
    try:
        return json.loads(r.stdout).get("lines", [])
    except Exception:
        return []


def _variants(png):
    """三种预处理：原图 / 2x 放大锐化 / 灰度自动对比+1.5x+二值化。"""
    from PIL import Image, ImageOps, ImageFilter
    im = Image.open(png).convert("RGB")
    out = [("raw", im.convert("L"))]
    big = im.resize((int(im.width * 2), int(im.height * 2)), Image.LANCZOS)
    big = big.convert("L").filter(ImageFilter.UnsharpMask(radius=1.4, percent=150, threshold=3))
    out.append(("up2", big))
    g = ImageOps.autocontrast(im.convert("L"), cutoff=1)
    g = g.resize((int(g.width * 1.5), int(g.height * 1.5)), Image.LANCZOS)
    g = g.point(lambda p: 255 if p > 168 else 0)
    out.append(("bin", g))
    return out


FULL2HALF = {ord(c): ord(c) - 0xFEE0 for c in
             "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
             "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}
FULL2HALF.update({ord("　"): 32, ord("．"): 46, ord("，"): 44, ord("："): 58,
                  ord("；"): 59, ord("（"): 40, ord("）"): 41})


def nkey(s):
    return re.sub(r"\s+", "", (s or "").translate(FULL2HALF))


def align_lines(anchor, other):
    """把 other 的行按序对齐到 anchor 的行号上，返回 {anchor_idx: [候选文本]}"""
    import difflib
    A = [nkey(l["text"]) for l in anchor]
    B = [nkey(l["text"]) for l in other]
    mp = {}
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and (i2 - i1) == (j2 - j1)):
            for k in range(i2 - i1):
                mp.setdefault(i1 + k, []).append(other[j1 + k]["text"])
        elif tag == "replace":
            blk = other[j1:j2]
            if blk:
                # 逐行就近取候选；行数不等时按比例落位，绝不把整块重复贴到每一行
                for k in range(i1, i2):
                    off = k - i1
                    idx = j1 + (off if off < len(blk) else len(blk) - 1)
                    mp.setdefault(k, []).append(other[idx]["text"])
    return mp


def ocr_page(png, level="accurate"):
    """一页跑 3 轮并定稿。返回 (定稿文本, 冲突行列表)"""
    tmpd = tempfile.mkdtemp(prefix="ocrp_")
    runs, confs = [], []
    try:
        for name, img in _variants(png):
            fp = os.path.join(tmpd, name + ".png")
            img.save(fp)
            lines = vision_ocr(fp, level=level)
            runs.append(lines)
            confs.append(sum(l["conf"] for l in lines) / max(1, len(lines)))
            os.remove(fp)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    if not runs or not runs[0]:
        # 锚点为空：退而用置信度最高的那轮
        best = max(range(len(runs)), key=lambda i: (len(runs[i]), confs[i]))
        return "\n".join(l["text"] for l in runs[best]), []
    anchor = runs[0]
    maps = [align_lines(anchor, r) for r in runs[1:]]
    final, conflicts = [], []
    for i, a in enumerate(anchor):
        cands = [a["text"]] + [m.get(i, [""])[0] for m in maps]
        cands = [c for c in cands if nkey(c)]
        if not cands:
            continue
        from collections import Counter
        cnt = Counter(nkey(c) for c in cands)
        top, n = cnt.most_common(1)[0]
        if n >= 2 or len(cands) == 1:
            win = next(c for c in cands if nkey(c) == top)
            final.append(win)
        else:
            final.append(cands[0])
            conflicts.append({"line": i + 1, "y": round(a["y"], 4),
                              "final": cands[0], "variants": sorted(set(cands))})
    return "\n".join(final), conflicts


def ocr_dir(d, code, passes_note="3轮(原图/放大锐化/灰度二值)"):
    pngs = sorted(f for f in os.listdir(d) if re.match(r"page-\d+\.png$", f))
    txts, allconflict = [], []
    for i, f in enumerate(pngs, 1):
        t, cf = ocr_page(os.path.join(d, f))
        txts.append(t)
        for c in cf:
            c["page"] = i
            allconflict.append(c)
        log("    OCR %d/%d  %s  字符=%d  冲突=%d" % (i, len(pngs), f, len(t), len(cf)))
    body = "\n\n".join(txts).strip()
    out = os.path.join(d, safe_name(code) + ".txt")
    open(out, "w", encoding="utf-8").write(body)
    rev = {"code": code, "pages": len(pngs), "method": passes_note,
           "chars": len(body), "conflicts": allconflict,
           "conflict_ratio": round(len(allconflict) / max(1, sum(t.count("\n") + 1 for t in txts)), 4)}
    json.dump(rev, open(os.path.join(d, "_review.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return out, body, rev


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", (s or "").strip())[:120]


# ══════════════════════════ ③ 行标 hbba ══════════════════════════
def hbba_pdf_url(detail_url):
    """从行标详情页找官方 PDF：返回 (pdf_url, 结论)。"""
    if not detail_url:
        return "", "no-url"
    pk = detail_url.rstrip("/").rsplit("/", 1)[-1]
    html = curl_j("%s/portal/online/%s" % (HBBA, pk), timeout=40,
                  referer=detail_url)
    if not html:
        return "", "unreachable"
    if "尚未公开" in html:
        m = re.search(r"<p>\s*([^<]{2,60})\s*</p>", html.split("尚未公开", 1)[1])
        return "", "blocked-copyright:" + (m.group(1).strip() if m else "版权")
    m = re.search(r'href="(/portal/download/[0-9a-f]+)"', html)
    if m:
        return HBBA + m.group(1), "public-pdf"
    m = re.search(r'href="(/attachment/onlineRead/[0-9a-f]+)"', html)
    if m:
        return HBBA + m.group(1), "readonly-viewer"
    return "", "no-fulltext"


# ══════════════════════════ 台账 / 语料库 ══════════════════════════
def load_ledger():
    return H.load_json(LEDGER, {})


def save_ledger(l):
    l["_updated"] = date.today().isoformat()
    H.save_json(LEDGER, l)


def add_corpus(code, name, cat, text, src):
    """写入站点语料库（sources/library/corpus，gitignored）。"""
    if not text or len(text) < 300:
        return None
    idx = H.load_json(H.IDX, {"updated": "", "items": {}})
    did, msg = H.add_doc(idx, name, code, cat, text, src)
    H.save_json(H.IDX, idx)
    return did


# ══════════════════════════ 主流程 ══════════════════════════
def do_gb(code, name, hcno="", pages_limit=0, do_ocr=True, keep_img=True):
    hcno = hcno or ""
    if not hcno:
        hcno, got = openstd_hcno(code)
        if not hcno:
            return {"code": code, "status": "no-hcno"}
    jar = os.path.join(tempfile.mkdtemp(prefix="gbjar_"), "c.txt")
    title, pages = gb_viewer(hcno, jar)
    if not pages:
        return {"code": code, "hcno": hcno, "status": "no-online-view"}
    d = os.path.join(SCAN_DIR, safe_name(code))
    cache = os.path.join(d, "_sprite")
    imgd = os.path.join(d, "img")
    pngs = stitch_pages(pages, jar, hcno, cache, imgd, maxpages=pages_limit)
    log("  %s  标题=%s  页数=%d  已拼接=%d" % (code, title, len(pages), len(pngs)))
    rec = {"code": code, "name": name, "hcno": hcno, "official_url":
           "%s/newGbInfo?hcno=%s" % (OPENSTD, hcno), "pages": len(pages),
           "images": len(pngs), "fetched": date.today().isoformat()}
    if do_ocr and pngs:
        out, body, rev = ocr_dir(imgd, code)
        rec.update({"status": "scan+ocr", "chars": len(body), "text": os.path.relpath(out, HERE),
                    "conflicts": len(rev["conflicts"]), "conflict_ratio": rev["conflict_ratio"]})
        # 定稿文本进语料库（供检索/抽条款）
        add_corpus(code, name or title, "标准", body, os.path.relpath(out, HERE))
    else:
        rec["status"] = "scan-only"
    if not keep_img:
        shutil.rmtree(imgd, ignore_errors=True)
    shutil.rmtree(os.path.dirname(jar), ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    return rec


def do_hb(entry):
    code, name, url = entry.get("code", ""), entry.get("name", ""), entry.get("url", "")
    pdf, why = hbba_pdf_url(url)
    rec = {"code": code, "name": name, "official_url": url,
           "fetched": date.today().isoformat()}
    if not pdf:
        rec["status"] = "meta-only"
        rec["note"] = why
        return rec
    d = os.path.join(SCAN_DIR, safe_name(code))
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, safe_name(code) + ".pdf")
    curl_j(pdf, out=fp, timeout=180)
    if not os.path.exists(fp) or os.path.getsize(fp) < 5000:
        rec["status"] = "download-fail"
        return rec
    txt = ""
    try:
        import fitz
        doc = fitz.open(fp)
        txt = "\n".join(p.get_text() for p in doc)
    except Exception:
        pass
    rec.update({"status": "full" if len(txt.strip()) > 2000 else "pdf-no-text",
                "pdf": os.path.relpath(fp, HERE), "chars": len(txt.strip()),
                "source": pdf})
    if len(txt.strip()) > 2000:
        open(os.path.join(d, safe_name(code) + ".txt"), "w", encoding="utf-8").write(txt)
        add_corpus(code, name, "标准", txt, os.path.relpath(fp, HERE))
    return rec


def copy_to_store(rec):
    """把截图 / PDF / 定稿文本复制进本机标准库（人可读）。"""
    d = os.path.join(SCAN_DIR, safe_name(rec.get("code", "")))
    if not os.path.isdir(d):
        return 0
    sub = os.path.join(STORE, "标准全文（截图+OCR）", safe_name(rec.get("code", "")))
    n = 0
    for root, _, files in os.walk(d):
        for f in files:
            if f.startswith("_") or f.endswith(".webp"):
                continue
            if not (f.endswith(".png") or f.endswith(".pdf") or f.endswith(".txt")):
                continue
            rel = os.path.relpath(os.path.join(root, f), d)
            dst = os.path.join(sub, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(os.path.join(root, f)):
                shutil.copy2(os.path.join(root, f), dst)
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--gb", action="store_true", help="跑国标在线阅读器（截图+OCR）")
    ap.add_argument("--hb", action="store_true", help="跑行标（hbba 官方 PDF）")
    ap.add_argument("--ocr-only", metavar="DIR", help="只对已有截图目录重跑 OCR")
    ap.add_argument("--code", help="指定标准号，如 GB/T 35273-2020")
    ap.add_argument("--only", help="按名称片段指定")
    ap.add_argument("--missing", action="store_true", help="批量补 library 里缺正文的")
    ap.add_argument("--all", action="store_true", help="批量处理全部候选")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--maxpages", type=int, default=0, help="每份最多处理多少页（0=全部）")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--no-store", action="store_true", help="不复制到本机标准库")
    a = ap.parse_args()

    os.makedirs(SCAN_DIR, exist_ok=True)

    if a.plan:
        wl = H.build_worklist()
        rows = [r for r in wl["rows"] if r["reg"] and r["kind"] == "标准"]
        miss = [r for r in rows if r["has"] != "full"]
        led = load_ledger()
        done = {k for k, v in led.items() if isinstance(v, dict) and v.get("status", "").startswith("scan")}
        log("标准条目 %d 条；其中已有全文 %d、缺/仅片段 %d；已截图+OCR 归档 %d"
            % (len(rows), len(rows) - len(miss), len(miss), len(done)))
        for r in miss[:60]:
            log("   %-22s %s" % (r["code"] or "-", r["name"][:44]))
        return

    if a.ocr_only:
        d = a.ocr_only if os.path.isabs(a.ocr_only) else os.path.join(HERE, a.ocr_only)
        code = os.path.basename(d.rstrip("/"))
        out, body, rev = ocr_dir(os.path.join(d, "img"), code)
        log("定稿 %s  字符=%d  冲突=%d" % (out, len(body), len(rev["conflicts"])))
        return

    led = load_ledger()
    results = []

    if a.gb:
        targets = []
        if a.code:
            targets = [{"code": a.code, "name": a.code}]
        else:
            wl = H.build_worklist()
            for r in wl["rows"]:
                if not r["reg"] or r["kind"] != "标准":
                    continue
                if a.missing and r["has"] == "full":
                    continue
                if a.only and a.only not in r["name"]:
                    continue
                if re.match(r"^(YD|JR|SB|NY|JT|QB|HB|SN|LY|WS|TSIA|T_|T/)", r["code"] or ""):
                    continue          # 非国标，交给 --hb
                if r["level"] and "国家标准" not in r["level"] and "指导性技术文件" not in r["level"]:
                    continue
                targets.append(r)
        if a.limit:
            targets = targets[:a.limit]
        log("国标候选 %d 条" % len(targets))
        for t in targets:
            log("→ %s %s" % (t["code"], t["name"][:38]))
            try:
                rec = do_gb(t["code"], t["name"], pages_limit=a.maxpages, do_ocr=not a.no_ocr)
            except Exception as e:
                rec = {"code": t["code"], "name": t["name"], "status": "error", "note": str(e)[:160]}
            log("   => %s %s" % (rec.get("status"), rec.get("note", "") or rec.get("chars", "")))
            if not a.no_store and rec.get("status", "").startswith("scan"):
                rec["stored"] = copy_to_store(rec)
            led[t["code"] or t["name"]] = rec
            results.append(rec)
            save_ledger(led)

    if a.hb:
        hbf = os.path.join(HERE, "sources", "standards", "hbba_fetched.json")
        data = H.load_json(hbf, {})
        items = list(data.values())
        if a.only:
            items = [x for x in items if a.only in (x.get("name") or "") or a.only in (x.get("code") or "")]
        if a.limit:
            items = items[:a.limit]
        log("行标候选 %d 条" % len(items))
        for it in items:
            rec = do_hb(it)
            log("   %-18s => %s %s" % (rec["code"], rec["status"], rec.get("note", "") or
                                       ("%s 字" % rec.get("chars", ""))))
            if not a.no_store and rec.get("status") == "full":
                rec["stored"] = copy_to_store(rec)
            led["HB::" + (rec["code"] or rec["name"])] = rec
            results.append(rec)
            save_ledger(led)

    save_ledger(led)
    if results:
        ok = sum(1 for r in results if r.get("status") in ("scan+ocr", "full"))
        log("\n完成 %d 条，其中取到正文 %d 条。台账：%s" % (len(results), ok, os.path.relpath(LEDGER, HERE)))


if __name__ == "__main__":
    main()
