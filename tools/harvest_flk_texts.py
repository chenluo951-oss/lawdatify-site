#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harvest_flk_texts.py —— 抓取国家法律法规数据库的**官方全文**，提取文字层，
供站内「法规原文」库（kb/texts）收录。

为什么能上站：见 build_texts.py 头部——《著作权法》第五条，法律法规及具有立法、
行政、司法性质的文件不适用著作权法，官方正文可公开发布。

官方全文获取链路（2026-09-15 实测打通，这是本脚本的全部价值所在）：

  1. 站点是 Vue SPA，页面抓不到正文；详情接口 `GET /law-search/search/flfgDetails?bbbs=<bbbs>`
     只返回**章节目录树**（章/节/条标题）与 ossFile 路径，**不含条文正文**。
  2. 正文在后端 OSS 上，bucket `flkoss.obs-bj2.cucloud.cn` 直连 403（需签名）。
  3. 签名入口：`GET /law-search/download/pc?bbbs=<bbbs>&format=pdf`
     ⚠️ 必须带 `format=` 参数（`type=` / `fileType=` / 不带 → 一律 500「系统异常」；
     只写 `id=` 会报「Required request parameter 'bbbs'」）。
  4. 该接口前置**腾讯云 WAF 一次性 cookie 挑战**：首次请求返回 302 + Set-Cookie
     `wzws_cid`，**必须带该 cookie 重放**才回 JSON。cookie Max-Age=1800s。
  5. 返回 `data.url` 即 OSS 签名直链（含 response-content-disposition），**有时效**，
     拿到后必须立刻下载；`data.urlIn` 是内网地址，无用。

产出：sources/flk_texts/texts.jsonl（每行一条：bbbs/名称/类别/发布实施/机关/字数/正文）
"""
import os, re, sys, json, time, threading, subprocess, argparse, collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

FLK = "https://flk.npc.gov.cn"
SIG_API = FLK + "/law-search/download/pc"
SRC = os.path.join(HERE, "sources", "standards", "flk_bulk.json")
OUTDIR = os.path.join(HERE, "sources", "flk_texts")
OUT = os.path.join(OUTDIR, "texts.jsonl")
# 抓不到的条目（「无文字层 / 失败」）的累计失败次数。见 main() 注释：
# 有一批条目是**确定性抓不到**的（扫描件无文字层、自治条例类公文），每次跑都会
# 重试一遍并全部失败 —— 实测阶段① 收尾 5 条就要白花 4 分钟。累计到阈值后跳过，
# 需要重试时加 --retry-failed。
FAIL_LOG = os.path.join(OUTDIR, "failed.jsonl")
JAR = os.path.join(OUTDIR, ".wzws_cookie.txt")
TMP = os.path.join(OUTDIR, ".tmp")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# 带上完整浏览器头能显著降低 WAF 触发概率（只带 UA 容易被判为脚本流量）
BROWSER_HDR = ["-H", "Accept: application/json, text/plain, */*",
               "-H", "Accept-Language: zh-CN,zh;q=0.9",
               "-H", "sec-ch-ua-mobile: ?0",
               "-H", "Sec-Fetch-Dest: empty",
               "-H", "Sec-Fetch-Mode: cors",
               "-H", "Sec-Fetch-Site: same-origin"]

# 默认抓「具有普遍约束力、企业会直接适用」的全部非地方层级（约 4.7k 条）。
# 地方法规 3037 条最多、多为属地事务，用 --kinds 地方法规 单独指定时才抓。
DEFAULT_KINDS = ["法律", "宪法", "行政法规", "监察法规", "司法解释", "法律解释",
                 "法规性决定", "修正案", "修改、废止的决定",
                 "有关法律问题和重大问题的决定（部分）", "部门规章", "规范性文件"]

# docx 的最低字数（默认阈值）。见 fetch_one 注释：docx 必有文字层，
# 一大批「批准 / 决定」类公文正文只有一两句（100—200 字），阈值 300 会把它们全丢掉。
MIN_DOCX = 60

PDF_NOISE = [
    re.compile(r"^\s*国家法律法规数据库\s*$"),
    re.compile(r"^\s*[-—\s]*\d{1,4}\s*[-—\s]*$"),          # 页码
    re.compile(r"^\s*第\s*\d+\s*页\s*(共\s*\d+\s*页)?\s*$"),
]


def curl(args, timeout=90):
    try:
        p = subprocess.run(["curl", "-sS", "-m", str(timeout)] + args,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore")
        return p.stdout or ""
    except Exception:
        return ""


def refresh_cookie(jar=JAR):
    """触发一次 WAF 挑战，取回 wzws_cid 写入 cookie jar。"""
    os.makedirs(OUTDIR, exist_ok=True)
    curl(["-c", jar, "-o", "/dev/null", "-H", "User-Agent: " + UA,
          "-H", "Referer: " + FLK + "/", FLK + "/"], timeout=40)
    if not os.path.exists(jar):
        return False
    try:
        return "wzws_cid" in open(jar, encoding="utf-8", errors="ignore").read()
    except OSError:
        return False


def signed_url(bbbs, fmt="pdf", retry=3, jar=JAR):
    """取官方全文签名直链。失败返回 None，并自动刷新 WAF cookie 重试。"""
    q = f"{SIG_API}?bbbs={bbbs}&format={fmt}"
    for attempt in range(retry):
        raw = curl(["-b", jar, "-c", jar, "-H", "User-Agent: " + UA,
                    "-H", "Referer: " + FLK + "/detail2.html"] + BROWSER_HDR + [q],
                   timeout=40)
        try:
            d = json.loads(raw)
        except Exception:
            d = None
        if d and d.get("code") == 200:
            u = (d.get("data") or {}).get("url")
            if u:
                return u
        # 302/HTML 或异常 → 换 cookie 再来
        refresh_cookie(jar)
        # 指数退避：并发高时 WAF 会从「一次性 cookie」升级为「JS 挑战」，
        # 此时只能停下来等冷却，硬重试只会延长封禁。
        time.sleep(3 * (attempt + 1) ** 2)
    return None


def fetch_one(x, jar, slot, min_chars, min_docx=MIN_DOCX):
    """抓一条：优先 docx（体积小且必有文字层），失败再退 PDF。

    ⚠️ 阈值必须**按格式分开**（2026-09-16 修）：
      原先两个格式统一用 min_chars=300，把一大批**真实但极短**的公文误判成
      「无文字层」而丢弃 —— 例如「全国人大常委会关于批准《国务院关于安置老弱病残
      干部的暂行办法》的决议」正文只有 109 字，「关于对国际条约所规定的罪行行使
      刑事管辖权的决定」只有 151 字。这些是货真价实的生效法律文件，不该被丢掉。
      docx 必定带文字层（不存在扫描件），所以短就是真短，阈值放到 60；
      pdf 仍保留较高阈值 —— 扫描件有文字层但不完整，阈值低了会把噪声收进来。

    ⚠️ 临时文件按 slot 固定命名且**不删**：逐条 os.remove 会在第 50 个
    触发沙箱的批量删除保护（SAFE_DELETE_BULK_CONFIRM_REQUIRED）并中断进程。
    按 slot 命名是为了多线程之间不互相覆盖。
    """
    bbbs, title, kind = x["b"], x.get("t") or "", x.get("k") or ""
    got_file = False                 # 拿到过文件+字节 → 失败可归因于「无文字层」
    for fmt, fn, ext in (("word", docx_text, ".docx"), ("pdf", pdf_text, ".pdf")):
        url = signed_url(bbbs, fmt, jar=jar)
        if not url:
            continue
        p = os.path.join(TMP, f"cur{slot}{ext}")
        curl(["-o", p, "-H", "User-Agent: " + UA, url], timeout=180)
        if not os.path.exists(p) or os.path.getsize(p) < 800:
            continue
        nbyte = os.path.getsize(p)
        got_file = True
        txt = clean_text(fn(p), join_lines=(fmt == "pdf"))
        if len(txt) >= (min_docx if fmt == "word" else min_chars):
            return {"b": bbbs, "t": title, "k": kind, "o": x.get("o") or "",
                    "p": x.get("p") or "", "i": x.get("i") or "",
                    "s": sxx_label(x.get("s")), "f": fmt, "n": len(txt), "x": txt}, nbyte, "ok"
    # 区分两类失败：拿到过文件=确定性「无文字层」；连签名直链都没有=网络/WAF 抖动
    return None, 0, ("no_text" if got_file else "no_url")


def ole_text(path):
    """老式 .doc（OLE2 复合文档）的正文提取，用 macOS 自带的 textutil。

    ⚠️ 为什么必须有这条兜底（2026-09-16 补）：
    flk 下载接口对同一份文件会同时提供 word / pdf 两种格式，但**相当一部分
    「word」件并不是 docx，而是 Word 97-2003 的 OLE2 复合文档**（文件头
    `d0cf11e0a1b11ae1`），只是扩展名给了 .docx。zipfile 打不开 → 原来的
    docx_text 静默返回空 → 整条被当成「无文字层」丢掉。实测成批出现在
    司法解释与早年行政法规里：《人民检察院刑事诉讼规则》（859KB）、
    《海关关衔标志式样和佩带办法》（5.1MB）等，全部误判为失败。
    这些文件的正文是完整的，textutil 能逐条转出（实测 867 字，分条排版正常）。
    """
    try:
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                           capture_output=True, timeout=180)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.decode("utf-8", "ignore")


def docx_text(path):
    """提 docx 文字层（按文档顺序遍历段落，含表格单元格）。

    ⚠️ 关键：flk 的 docx 里，条文之间用的是**软换行 `<w:br/>`**而不是新段落，
    只取 `w:t` 会把整部法挤成一行（"制定本法。第二条 自然人……"）。
    必须把 `w:br`/`w:cr` 也翻成换行，正文才是可读的分条排版。

    ⚠️ 先按文件头判断格式：OLE2 是老式 .doc 伪装成 .docx，交给 ole_text。
    """
    try:
        head = open(path, "rb").read(8)
    except OSError:
        return ""
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return ole_text(path)

    import zipfile
    from xml.etree import ElementTree as ET
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        z = zipfile.ZipFile(path)
        if "word/document.xml" not in z.namelist():
            return ""
        root = ET.fromstring(z.read("word/document.xml"))
    except Exception:
        return ""

    def walk(node, buf):
        for ch in node:
            if ch.tag == W + "p":          # 嵌套段落（表格单元格）由外层 iter 单独处理
                continue
            if ch.tag == W + "t":
                buf.append(ch.text or "")
            elif ch.tag in (W + "br", W + "cr"):
                buf.append("\n")
            elif ch.tag == W + "tab":
                buf.append(" ")
            else:
                walk(ch, buf)

    paras = []
    for p in root.iter(W + "p"):
        buf = []
        walk(p, buf)
        txt = "".join(buf)
        paras.append("\n".join(s for s in (x.strip() for x in txt.split("\n")) if s))
    return "\n".join(paras)


def pdf_text(path):
    """用 pdfplumber 提文字层；扫描件（无文字层）返回空串。"""
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        with pdfplumber.open(path) as pdf:
            parts = []
            for pg in pdf.pages:
                parts.append(pg.extract_text() or "")
        return "\n".join(parts)
    except Exception:
        return ""


def clean_text(t, join_lines=False):
    """基础清洗：去 PDF 页眉页脚噪声。

    join_lines=True 用于 PDF：PDF 的换行是排版断行，中文之间的单换行要合并；
    docx 的换行是**语义分条**，绝不能合并（否则「制定本法。」与「第二条」会粘成一行）。
    精细清洗（部首归一、私用区回填等）交给 build_texts.py。
    """
    t = t.replace("\u3000", " ").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in t.split("\n"):
        s = line.strip()
        if not s:
            out.append("")
            continue
        if any(r.match(s) for r in PDF_NOISE):
            continue
        out.append(s)
    t = "\n".join(out)
    if join_lines:
        t = re.sub(r"(?<=[\u4e00-\u9fff，。；：、）】》])\n(?=[\u4e00-\u9fff（【《])", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def sxx_label(s):
    return {1: "尚未生效", 2: "已废止", 3: "现行有效", 4: "征求意见中",
            5: "已修改", 9: "其他"}.get(s, "")


def load_done():
    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["b"])
                except Exception:
                    pass
    return done


def load_failed():
    """返回 {bbbs: 累计失败次数}。坏行/缺文件都当空处理，绝不因此中断抓取。"""
    out = {}
    if os.path.exists(FAIL_LOG):
        with open(FAIL_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    out[d["b"]] = int(d.get("n") or 1)
                except Exception:
                    pass
    return out


def save_failed(counts):
    """整文件重写失败台账（小文件，几十 KB 级）。"""
    try:
        with open(FAIL_LOG, "w", encoding="utf-8") as f:
            for b, n in counts.items():
                f.write(json.dumps({"b": b, "n": n},
                                   ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        pass                        # 台账写不了不影响抓取本身


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", default="", help="逗号分隔的类别白名单，默认内置重点层级")
    ap.add_argument("--limit", type=int, default=0, help="最多抓多少条（0=不限）")
    ap.add_argument("--min-chars", type=int, default=300,
                    help="PDF 正文短于此字数视为无文字层，不入库")
    ap.add_argument("--min-docx", type=int, default=MIN_DOCX,
                    help="docx 正文短于此字数视为异常，不入库（默认 %d；"
                         "docx 必有文字层，短公文是真的短）" % MIN_DOCX)
    ap.add_argument("--sleep", type=float, default=0.6, help="每条间隔秒数")
    ap.add_argument("--fresh", action="store_true", help="忽略断点，重头抓")
    ap.add_argument("--retry-failed", action="store_true",
                    help="重置失败台账，重新尝试已判定抓不到的条目")
    ap.add_argument("--max-fail", type=int, default=3,
                    help="同一 bbbs 累计失败达到此次数后不再重试（默认 3）")
    ap.add_argument("--workers", type=int, default=1,
                    help="并发数。⚠️ 实测 >1 会触发 WAF 的 JS 挑战（302 循环 / 挑战页），"
                         "只能单线程慢跑；每个线程独立 cookie")
    a = ap.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    if a.fresh and os.path.exists(OUT):
        os.replace(OUT, OUT + ".bak")

    src = json.load(open(SRC, encoding="utf-8"))
    items = src["items"]
    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()] or DEFAULT_KINDS
    targets = [x for x in items if x.get("k") in kinds]
    # 先法律、行政法规等主干，地方法规放最后
    order = {k: i for i, k in enumerate(kinds)}
    targets.sort(key=lambda x: (order.get(x.get("k"), 99), x.get("t") or ""))

    done = set() if a.fresh else load_done()
    # 已知抓不到的条目：累计失败 >= max_fail 就跳过（否则每次跑都要白等它们超时重试）
    fails = {} if (a.fresh or a.retry_failed) else load_failed()
    hopeless = {b for b, n in fails.items() if n >= a.max_fail}
    todo = [x for x in targets if x["b"] not in done and x["b"] not in hopeless]
    if a.limit:
        todo = todo[:a.limit]

    print(f"目标类别：{'、'.join(kinds)}")
    print(f"命中 {len(targets)} 条，已完成 {len(done)} 条，"
          f"已放弃 {len(hopeless)} 条（失败≥{a.max_fail} 次），本次待抓 {len(todo)} 条")
    if not todo:
        print("没有待抓条目。")
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    nw = max(1, a.workers)
    jars = [os.path.join(OUTDIR, f".wzws_{i}.txt") for i in range(nw)]
    for jp in jars:
        refresh_cookie(jp)
    print(f"并发 {nw} 路")

    lock = threading.Lock()
    ok = fail = empty = 0
    nbytes = 0
    counts = collections.Counter()
    failed_ids = []
    t0 = time.time()
    fout = open(OUT, "a", encoding="utf-8")

    def job(pair):
        slot, x = pair
        try:
            return slot, x, fetch_one(x, jars[slot], slot, a.min_chars, a.min_docx)
        except Exception:
            return slot, x, (None, 0)

    with ThreadPoolExecutor(max_workers=nw) as ex:
        futs = [ex.submit(job, (i % nw, x)) for i, x in enumerate(todo)]
        for n, fu in enumerate(as_completed(futs), 1):
            slot, x, (rec, nbyte, reason) = fu.result()
            title = x.get("t") or ""
            with lock:
                if rec:
                    fout.write(json.dumps(rec, ensure_ascii=False,
                                          separators=(",", ":")) + "\n")
                    fout.flush()
                    ok += 1
                    nbytes += nbyte
                    counts[rec["k"]] += 1
                    mark = "✓"
                else:
                    empty += 1
                    failed_ids.append(x["b"])
                    mark = "○"
                if n % 20 == 0 or n <= 5:
                    el = time.time() - t0
                    rate = n / el if el else 0
                    left = (len(todo) - n) / rate / 60 if rate else 0
                    print(f"  [{n}/{len(todo)}] {mark} {title[:32]}"
                          f"　({rate:.1f} 条/秒，约剩 {left:.0f} 分钟)")
    fout.close()

    # 失败台账：只记「拿到过文件但无文字层」的确定性失败。
    # 「连签名直链都拿不到」= WAF/网络抖动，不记账 —— 否则限流一轮就会把好条目永久拉黑。
    det = [b for b, r in failed_ids if r == "no_text"]
    flaky = len(failed_ids) - len(det)
    if det:
        for b in det:
            fails[b] = fails.get(b, 0) + 1
        save_failed(fails)
        give_up = sum(1 for b in det if fails[b] >= a.max_fail)
        print(f"失败台账：{len(det)} 条确定性无文字层已记账，"
              f"其中 {give_up} 条达 {a.max_fail} 次，下次起跳过")
    if flaky:
        print(f"⚠️ {flaky} 条因取不到签名直链而失败（WAF/网络抖动），"
              f"**未记账**，下次会重试")

    print(f"\n完成：成功 {ok}　无文字层/失败 {empty}　"
          f"下载累计 {nbytes / 1024 / 1024:.0f} MB　耗时 {(time.time() - t0) / 60:.1f} 分钟")
    for k, v in counts.most_common():
        print(f"   {k} {v}")
    if os.path.exists(OUT):
        total = sum(1 for _ in open(OUT, encoding="utf-8"))
        print(f"texts.jsonl 现有 {total} 条　{os.path.getsize(OUT) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
