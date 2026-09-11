#!/usr/bin/env python3
"""
原文统一抓取器（harvest）——「每一个法规/标准都要有原文落盘」的执行器。

目标：对 library.json 里的每一条，尽最大可能拿到**现行有效版本的官方原文**，落三处：
  ① 本机标准库  ~/Documents/2.法规、 标准、指南等/0.站点标准库/<名称>.txt   （人可读）
  ② 站点语料库  sources/library/corpus/<id>.txt + _index.json                （供检索/抽条款，gitignored）
  ③ 抓取台账    sources/standards/harvest_ledger.json                        （URL/时间/字数/sha256/状态）
私有仓库同步交给 sync_standards_repo.py（--sync 调用）。

源优先级（按条目类型自动路由）：
  法律 / 行政法规           → flk（国家法律法规数据库）取权威元数据；gov.cn / npc.gov.cn 取全文
  部门规章 / 规范性文件     → gov.cn 政策文件库 + 部委官网（cac / samr / miit / moa …）
  国家标准（GB / GB/T）     → openstd 国家标准全文公开系统取元数据 + 全文可读性判定
  行业标准                  → hbba 行业标准信息服务平台取元数据
  团体标准                  → 合作平台取元数据 + 公开全文

诚实边界：推荐性国标的「在线预览」是图片式阅读器（反抓取），DOM 里取不到文字层。
本脚本会把这类条目标为 `image-only`（而非假装成功），需要时再走 OCR 专项。

用法：
  python3 harvest.py --plan                 # 只出工作量清单与覆盖率
  python3 harvest.py --plan --missing       # 只看还缺全文的
  python3 harvest.py --run --limit 40       # 实抓（默认只抓"缺全文"的）
  python3 harvest.py --run --only 食品安全法,价格法
  python3 harvest.py --run --daily          # 每日增量：新条目 + 失败重试
  python3 harvest.py --meta                 # 只刷新官方元数据与深链（不抓正文）
  python3 harvest.py --sync                 # 本机标准库 → GitHub 私有仓库
"""
import os, re, sys, json, html, hashlib, zipfile, subprocess, argparse, tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库")
DOC_DIR = os.path.expanduser("~/Documents/2.法规、 标准、指南等")
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
LIB = os.path.join(HERE, "sources", "standards", "library.json")
LEDGER = os.path.join(HERE, "sources", "standards", "harvest_ledger.json")
WORKLIST = os.path.join(HERE, "sources", "standards", "harvest_worklist.json")
VENVPY = os.path.expanduser("~/.workbuddy/binaries/python/envs/default/bin/python")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

FULL_MIN = 3000          # 标准正文 ≥ 3000 字才算"有全文"
FULL_MIN_LAW = 1200      # 法规/规章/文件篇幅天然短，门槛下调
SHORT_MIN = 800          # 800 字以下算片段


def full_threshold(kind, level):
    """标准类要 3000 字；法规、规章、规范性文件 1200 字即可认为收录完整。"""
    if (kind or "") == "标准" or "标准" in (level or ""):
        return FULL_MIN
    return FULL_MIN_LAW


# ══════════════════════════════ 网络 ══════════════════════════════
def curl(url, timeout=40, binary=False, referer=None, data=None, ctype=None):
    """沙箱里 python urllib 常被代理拦掉，统一走 curl 子进程。"""
    cmd = ["curl", "-sL", "-m", str(timeout), "-A", UA,
           "-H", "Accept-Language: zh-CN,zh;q=0.9"]
    if referer:
        cmd += ["-H", "Referer: " + referer]
    if data is not None:
        cmd += ["-X", "POST", "--data-binary", data]
        if ctype:
            cmd += ["-H", "Content-Type: " + ctype]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    except Exception:
        return b"" if binary else ""
    return r.stdout if binary else r.stdout.decode("utf-8", "ignore")


TAG_STRIP = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
TAG = re.compile(r"(?s)<[^>]+>")


def html_text(raw):
    raw = TAG_STRIP.sub(" ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|td|section)>", "\n", raw)
    txt = html.unescape(TAG.sub("", raw))
    txt = re.sub(r"[ \t\r\u3000\xa0]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n", txt).strip()


def pick_main(text):
    """从整页里挑最长的连续文本块（去掉导航/页脚）。"""
    lines = [l.strip() for l in text.split("\n")]
    blocks, cur = [], []
    for l in lines:
        if len(l) < 2:
            if len(cur) > 4:
                blocks.append("\n".join(cur))
            cur = []
        else:
            cur.append(l)
    if len(cur) > 4:
        blocks.append("\n".join(cur))
    if not blocks:
        return text
    body = max(blocks, key=len)
    # 若最大块占比过低，说明正文被切碎，退回全文
    return body if len(body) > 600 else text


def docx_text(path):
    """纯 stdlib 抽 docx 正文（不依赖 python-docx）。"""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return ""
    xml = re.sub(r"(?i)</w:p>", "\n", xml)
    xml = re.sub(r"(?i)<w:tab[^>]*/>", "\t", xml)
    txt = html.unescape(TAG.sub("", xml))
    return re.sub(r"\n\s*\n+", "\n", txt).strip()


def pdf_text(path):
    """优先用本进程 fitz；不可用时调 venv python。"""
    try:
        import fitz  # noqa
        d = fitz.open(path)
        t = "\n".join(pg.get_text() for pg in d)
        d.close()
        return t
    except ImportError:
        pass
    if os.path.exists(VENVPY):
        code = ("import sys,fitz;d=fitz.open(sys.argv[1]);"
                "sys.stdout.write('\\n'.join(p.get_text() for p in d))")
        try:
            r = subprocess.run([VENVPY, "-c", code, path],
                               capture_output=True, timeout=180)
            return r.stdout.decode("utf-8", "ignore")
        except Exception:
            return ""
    return ""


def fetch_any(url, referer=None):
    """抓任意 URL，按魔数判定 PDF / DOCX / HTML，返回 (text, kind)。"""
    raw = curl(url, timeout=60, binary=True, referer=referer)
    if not raw or len(raw) < 200:
        return "", "empty"
    if raw[:4] == b"%PDF":
        fp = tempfile.mktemp(suffix=".pdf")
        open(fp, "wb").write(raw)
        t = pdf_text(fp)
        os.unlink(fp)
        return t, "pdf"
    if raw[:2] == b"PK":
        fp = tempfile.mktemp(suffix=".docx")
        open(fp, "wb").write(raw)
        t = docx_text(fp)
        os.unlink(fp)
        return t, "docx"
    return pick_main(html_text(raw.decode("utf-8", "ignore"))), "html"


# ══════════════════════════════ 语料库 / 台账 ══════════════════════════════
def load_json(p, default):
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return default


def save_json(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


SEP = r"[\s\-—–/／\\()（）《》〈〉【】\[\]:：.、,，;；·|'\"]+"


def norm(s):
    return re.sub(SEP, "", (s or "")).upper()


def add_doc(idx, name, code, cat, text, src):
    """写入语料库；同名条目取更长的一版。"""
    if not text or len(text) < SHORT_MIN:
        return None, "too-short(%d)" % len(text or "")
    key = norm((code or "") + name)
    for k, v in idx["items"].items():
        if norm((v.get("code") or "") + (v.get("name") or "")) == key:
            if len(text) > int(v.get("chars") or 0):
                open(os.path.join(CORPUS, k + ".txt"), "w", encoding="utf-8").write(text)
                v.update(chars=len(text), src=src, head=text[:400])
                return k, "upgraded(%d)" % len(text)
            return k, "exists(%d)" % v.get("chars", 0)
    did = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
    open(os.path.join(CORPUS, did + ".txt"), "w", encoding="utf-8").write(text)
    idx["items"][did] = {"id": did, "code": code or "", "name": name, "cat": cat,
                         "pub": "", "impl": "", "toc": [], "src": src,
                         "chars": len(text), "head": text[:400]}
    return did, "added(%d)" % len(text)


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", (s or "").strip())[:120]


# ── 正文校验闸：防止把「发布公告」「目录页」当成标准/法规正文存下来 ──
DOC_META_RE = re.compile(r"^(标\s*题|发文机关|发文字号|来\s*源|主题分类|公文种类|成文日期|发布日期|实施日期)\s*[:：]")
ART_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")


def strip_gov_head(text):
    """去掉中国政府网公文页顶部重复的元数据块（题名/发文机关/发文字号…）。"""
    lines = [l for l in text.split("\n") if not DOC_META_RE.match(l.strip())]
    return re.sub(r"\n\s*\n+", "\n", "\n".join(lines)).strip()


def doc_shape_ok(text, kind, level):
    """判断抓到的这一页到底是不是目标文档本体。返回 (ok, 原因)。"""
    t = strip_gov_head(text)
    head = t[:260].replace(" ", "")
    # ① 发布公告 / 印发通知页 —— 只是"发布某标准的公告"，不是标准正文
    if re.match(r"^关于(发布|公布|印发|征求)", head) and ("公告" in head[:140] or "通知" in head[:140]):
        return False, "该页是发布/印发公告，非正文"
    # ② 目录、索引、汇编页
    if re.match(r"^(目录|目次|索引)", head):
        return False, "该页是目录/索引页"
    # ③ 标准必须有标准正文特征
    if (kind or "") == "标准" or "标准" in (level or ""):
        if not ("范围" in t and ("规范性引用文件" in t or "术语和定义" in t)):
            if len(ART_RE.findall(t)) < 5:
                return False, "未检出标准正文特征（范围/规范性引用文件）"
    return True, ""


# ══════════════════════════════ 覆盖判定 ══════════════════════════════
def doc_pool():
    """本机全部可读原文的（归一化键，字数）列表：语料库 + 站点标准库 + Documents 存量。"""
    pool = []
    idx = load_json(IDX, {"items": {}})
    for v in idx["items"].values():
        pool.append({"k": norm(v.get("name")) + "|" + norm((v.get("head") or "")[:400])
                     + "|" + norm(v.get("src")), "chars": int(v.get("chars") or 0),
                     "name": norm(v.get("name")), "raw": v.get("name") or ""})
    if os.path.isdir(STORE):
        for dp, _dn, fns in os.walk(STORE):
            for fn in fns:
                p = os.path.join(dp, fn)
                b = norm(os.path.splitext(fn)[0])
                lead = ""
                if fn.lower().endswith(".txt"):
                    try:
                        lead = norm(open(p, encoding="utf-8", errors="ignore").read()[:400])
                    except Exception:
                        lead = ""
                pool.append({"k": b + "|" + lead + "|", "chars": os.path.getsize(p),
                             "name": b, "raw": fn})
    return pool


def title_match(title, name):
    """判断检索到的标题是否就是目标条目（去掉「中华人民共和国」等前缀后比）。"""
    a = norm(title)
    b = norm(name)
    for pre in ("中华人民共和国", "中国"):
        a = a.replace(norm(pre), "")
        b = b.replace(norm(pre), "")
    if not a or not b:
        return False
    return a == b or (len(b) >= 4 and b in a) or (len(a) >= 4 and a in b)


# 规范性文件名特征：看**名称结尾**是否为公文/标准类型词，避免把内部材料误判成法规
REGPAT = re.compile(r"(法|条例|办法|规定|标准|规范|准则|规则|细则|通知|意见|公告|通告|规划|"
                    r"指引|指南|纲要|决定|批复|要求|解释|答复|方案|清单|目录|通则|规程|导则|"
                    r"公报|白皮书|技术要求|评估规则)")


def looks_regulatory(name, kind=""):
    """判断这条到底是规范性文件，还是混进来的内部文档/研究材料。"""
    if (kind or "") == "标准":
        return True
    n = re.sub(r"[\s\d._\-（）()【】\[\]《》]*$", "", (name or "").strip())
    return bool(REGPAT.search(n[-12:]))


def code_keys(code):
    c = (code or "").strip()
    if not c or c in ("法律", "行政法规", "部门规章", "规范性文件", "文件", "国家标准", "行业标准"):
        return []
    n = norm(c)
    ks = {n} if len(n) >= 8 else set()
    m = re.match(r"^(?:GB|GBT|GBZ|DB\d*|T|TAF|HBBA|SB|NY|JT|YD|CAC|SAMR)[A-Z]*(\d{3,6})(\d{4})?$", n)
    if m:
        ks.add(m.group(1) + (m.group(2) or ""))
    return [k for k in ks if len(k) >= 8]


def judge(item, pool):
    """返回 (status, chars, docname)。status ∈ full / short / none。"""
    ks, nm = code_keys(item.get("code")), norm(item.get("name"))
    thr = full_threshold(item.get("kind"), item.get("level"))
    best, bestc = None, 0
    for d in pool:
        # 名字对名字：法规名普遍偏短（如「网络安全法」），下限放到 4 字
        titled = (ks and any(k in d["k"] for k in ks)) or \
                 (len(nm) >= 4 and (nm in d["name"] or d["name"] in nm))
        if not titled:
            continue
        if d["chars"] > bestc:
            best, bestc = d["raw"], d["chars"]
    if best is None:
        return "none", 0, ""
    return ("full" if bestc >= thr else "short"), bestc, best


def build_worklist(force=False):
    lib = load_json(LIB, {"items": []})
    stamp = {}
    for p in (IDX, LIB):
        if os.path.exists(p):
            st = os.stat(p)
            stamp[os.path.basename(p)] = [int(st.st_mtime), st.st_size]
    cache = load_json(WORKLIST, {})
    if not force and cache.get("stamp") == stamp and cache.get("rows"):
        return cache
    pool = doc_pool()
    rows = []
    for it in lib["items"]:
        st, ch, dn = judge(it, pool)
        rows.append({"code": it.get("code", ""), "name": it.get("name", ""),
                     "level": it.get("level", ""), "kind": it.get("kind", ""),
                     "status_doc": it.get("status", ""), "url": it.get("url", ""),
                     "reg": looks_regulatory(it.get("name", ""), it.get("kind", "")),
                     "has": st, "chars": ch, "doc": dn})
    out = {"stamp": stamp, "built_at": date.today().isoformat(),
           "total": len(rows), "rows": rows}
    save_json(WORKLIST, out)
    return out


# ══════════════════════════════ 源适配器 ══════════════════════════════
def govcn_search(title, n=8):
    """中国政府网政策文件库检索官方深链。"""
    import urllib.parse
    url = ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gw&q=%s"
           "&sort=score&sortType=1&searchfield=title&p=1&n=%d"
           % (urllib.parse.quote(title), n))
    raw = curl(url, timeout=25)
    try:
        d = json.loads(raw)
    except Exception:
        return []
    out = []
    for it in ((d.get("searchVO") or {}).get("listVO") or []):
        t = re.sub(r"</?em>", "", it.get("title", "")).strip()
        if it.get("url"):
            out.append((t, it["url"], it.get("puborg", "")))
    return out


FLK_API = "https://flk.npc.gov.cn/law-search"


def flk_search(title, size=5):
    """国家法律法规数据库检索（新 REST 接口）。返回 rows。"""
    payload = json.dumps({
        "searchRange": 1, "sxrq": [], "gbrq": [], "searchType": 2, "sxx": [],
        "gbrqYear": [], "flfgCodeId": [], "zdjgCodeId": [],
        "searchContent": title, "pageNum": 1, "pageSize": size,
        "sortTr": "f_bbrq_s;desc", "sort": True}, ensure_ascii=False)
    raw = curl(FLK_API + "/search/list", timeout=30, data=payload,
               ctype="application/json", referer="https://flk.npc.gov.cn/")
    try:
        d = json.loads(raw)
    except Exception:
        return []
    return d.get("rows") or []


def flk_detail(bbbs):
    raw = curl(FLK_API + "/search/flfgDetails?bbbs=" + bbbs, timeout=30,
               referer="https://flk.npc.gov.cn/")
    try:
        return (json.loads(raw) or {}).get("data") or {}
    except Exception:
        return {}


def openstd_lookup(code):
    """国标全文公开系统：标准号 → hcno + 元数据 + 全文可读性。"""
    import urllib.parse
    q = urllib.parse.quote((code or "").replace(" ", ""))
    raw = curl("https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p1=0"
               "&p.p90=circulation_date&p.p91=desc&p.p2=" + q, timeout=30)
    if not raw:
        return None
    hc = re.search(r"showInfo\('([0-9A-Fa-f]+)'\)", raw)
    if not hc:
        return None
    hcno = hc.group(1)
    det = curl("https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=" + hcno, timeout=30)
    txt = html_text(det)
    meta = {"hcno": hcno, "url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=" + hcno}

    def grab(label):
        m = re.search(label + r"[^\u4e00-\u9fa5]{0,6}(20\d{2}-\d{2}-\d{2})", txt)
        return m.group(1) if m else ""
    meta["pub"] = grab("发布日期")
    meta["impl"] = grab("实施日期")
    m = re.search(r"(现行|即将实施|废止)", txt)
    meta["status"] = m.group(1) if m else ""
    # 全文可读性：showGb 若回落到详情页说明无在线全文
    sh = curl("https://openstd.samr.gov.cn/bzgk/gb/showGb?type=online&hcno=" + hcno, timeout=30)
    meta["fulltext"] = "image-only" if ("暂无全文" not in sh and "newGbInfo" not in sh[:4000]) \
        else ("none" if "暂无全文" in sh else "unknown")
    return meta


def hbba_lookup(keyword):
    raw = curl("https://hbba.sacinfo.org.cn/stdQueryList", timeout=30,
               data="current=1&size=5&key=" + keyword,
               ctype="application/x-www-form-urlencoded")
    try:
        return (json.loads(raw) or {}).get("records") or []
    except Exception:
        return []


# ══════════════════════════════ 抓取主流程 ══════════════════════════════
def targets_by_name(rows, only=None, daily=False, missing_only=True, kinds=None):
    out = []
    for r in rows:
        if only and r["name"] not in only and r["code"] not in only:
            continue
        if kinds and r["kind"] not in kinds:
            continue
        if daily:
            led = LEDGER_CACHE.get(r["name"], {})
            if led.get("status") in ("full", "meta", "image-only"):
                continue
        if missing_only and r["has"] == "full":
            continue
        out.append(r)
    return out


LEDGER_CACHE = {}


def seed_map():
    """seeds.json = 人工校验过的「必备法规官方正文档」清单，作为一级候选源。"""
    d = load_json(os.path.join(HERE, "sources", "standards", "seeds.json"), {})
    out = {}
    for s in d.get("seeds", []):
        if s.get("url"):
            out[s.get("title", "")] = s["url"]
            if s.get("ref"):
                out[s["ref"]] = s["url"]
    return out


def try_fetch(item, idx, ledger, seen_shas, seeds):
    """按类型路由抓原文。返回 (ok, msg)。"""
    name, code = item["name"], item.get("code", "")
    level, kind = item.get("level", ""), item.get("kind", "")
    cands = []                                   # (url, referer, 说明)

    for k, u in seeds.items():                   # ① 人工校验过的种子
        if title_match(name, k) or title_match(k, name):
            cands.append((u, None, "种子清单（人工校验）"))
            break

    if item.get("url") and not re.fullmatch(r"https?://[^/]+/?", item["url"]):
        cands.append((item["url"], None, "条目既有深链"))

    if kind == "标准":
        if level in ("推荐性国家标准", "强制性国家标准", "国家标准化指导性技术文件"):
            m = openstd_lookup(code)
            if m:
                ledger[name] = dict(ledger.get(name) or {}, **{
                    "code": code, "level": level, "official_url": m["url"],
                    "pub": m.get("pub", ""), "impl": m.get("impl", ""),
                    "status": ("image-only" if m.get("fulltext") == "image-only" else "meta"),
                    "source": "openstd", "checked": date.today().isoformat(),
                    "note": "国标在线预览为图片式阅读器，无文字层；元数据已入库"})
                return False, "国产标准：元数据入库，全文需 OCR（image-only）"
        else:
            rec = hbba_lookup(code or name)
            if rec:
                ledger[name] = dict(ledger.get(name) or {}, **{
                    "code": code, "level": level, "status": "meta",
                    "source": "hbba", "checked": date.today().isoformat(),
                    "official_url": "https://hbba.sacinfo.org.cn/stdDetail/" + rec[0]["pk"],
                    "note": "行标全文一般不公开，仅收录元数据与官方深链"})
                return False, "行标：元数据入库"
        # 标准类再试一次名称检索（部分标准被法规库/官网转载）
        for t, u, _o in govcn_search(name)[:2]:
            if title_match(t, name):
                cands.append((u, None, "gov.cn 检索命中"))
                break
    else:
        # 法规 / 文件：先 flk（权威元数据），再 gov.cn（全文）
        if level in ("法律", "行政法规"):
            rows = flk_search(name)
            for r in rows[:5]:
                if title_match(r.get("title"), name):
                    d = flk_detail(r["bbbs"])
                    ledger[name] = dict(ledger.get(name) or {}, **{
                        "code": code, "level": level, "source": "flk",
                        "flk_title": r.get("title", ""),
                        "flk_status": {3: "有效", 2: "已修改", 1: "已废止", 4: "尚未生效"}
                        .get(r.get("sxx"), ""),
                        "pub": r.get("gbrq", ""), "impl": r.get("sxrq", ""),
                        "issuer": r.get("zdjgName", ""),
                        "flk_url": "https://flk.npc.gov.cn/detail2.html?" + r["bbbs"],
                        "oss_docx": ((d.get("ossFile") or {}).get("ossWordPath") or ""),
                        "checked": date.today().isoformat(),
                        "note": "国家法律法规数据库权威元数据"})
                    break
        for t, u, _o in govcn_search(name)[:4]:
            if title_match(t, name):
                cands.append((u, "https://sousuo.www.gov.cn/", "gov.cn 政策库命中"))
                break
        m = re.match(r"^https?://([^/]+)", item.get("url") or "")
        if m:
            cands.append((item["url"], "https://" + m.group(1) + "/", "条目既有深链"))

    seen = set()
    for url, ref, why in cands:
        if url in seen:
            continue
        seen.add(url)
        text, k = fetch_any(url, referer=ref)
        if len(text) < SHORT_MIN:
            continue
        text = strip_gov_head(text)
        good, reason = doc_shape_ok(text, kind, level)
        if not good:
            ledger[name] = dict(ledger.get(name) or {}, **{
                "code": code, "level": level, "source": "gov.cn/官网",
                "official_url": url, "chars": len(text), "http_kind": k,
                "status": "pointer", "checked": date.today().isoformat(),
                "note": reason})
            continue
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        if sha in seen_shas and seen_shas[sha] != name:
            ledger[name] = dict(ledger.get(name) or {}, **{
                "code": code, "level": level, "source": "gov.cn/官网",
                "official_url": url, "chars": len(text), "status": "wrong-page",
                "checked": date.today().isoformat(),
                "note": "与「%s」抓到同一页，疑似错页，已弃用" % seen_shas[sha]})
            continue
        seen_shas[sha] = name
        fn = safe_name(name) + ".txt"
        os.makedirs(STORE, exist_ok=True)
        open(os.path.join(STORE, fn), "w", encoding="utf-8").write(text)
        did, msg = add_doc(idx, name, code, kind, text, url)
        ledger[name] = dict(ledger.get(name) or {}, **{
            "code": code, "level": level, "source": "gov.cn/官网",
            "official_url": url, "http_kind": k, "chars": len(text),
            "sha256": sha, "corpus_id": did or "", "file": fn,
            "status": "full" if len(text) >= full_threshold(kind, level) else "short",
            "fetched": date.today().isoformat(), "note": why})
        return True, "%s %d 字 ← %s" % (msg, len(text), why)
    return False, "未取到正文（%d 个候选源均失败或均非正文）" % len(cands)


def main():
    global LEDGER_CACHE
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--meta", action="store_true")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--kind", default="", help="只处理指定类型：法规,文件,标准（逗号分隔）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-nonreg", action="store_true",
                    help="也处理非规范性条目（内部文件/研究材料）")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    if a.sync:
        os.execv(sys.executable, [sys.executable,
                                  os.path.join(HERE, "sync_standards_repo.py")])

    wl = build_worklist(force=a.force)
    rows = wl["rows"]
    n = {"full": 0, "short": 0, "none": 0}
    for r in rows:
        n[r["has"]] += 1
    cover = n["full"] / max(1, len(rows)) * 100

    if a.plan or not (a.run or a.meta):
        reg = [r for r in rows if r.get("reg")]
        irr = [r for r in rows if not r.get("reg")]
        rn = {"full": 0, "short": 0, "none": 0}
        for r in reg:
            rn[r["has"]] += 1
        print("原文覆盖（本机 / 共 %d 条）" % len(rows))
        print("  ── 规范性条目 %d 条（法规 / 标准 / 规范性文件）" % len(reg))
        print("     ✓ 有全文  %4d  (%.0f%%)" % (rn["full"], rn["full"] / max(1, len(reg)) * 100))
        print("     ~ 有片段  %4d" % rn["short"])
        print("     ✗ 无原文  %4d" % rn["none"])
        print("  ── 非规范性条目 %d 条（内部文件 / 研究材料 / 项目文档，无官网原文可抓）" % len(irr))
        if a.missing:
            print("\n缺全文清单 —— 规范性条目：")
            for r in [x for x in reg if x["has"] != "full"][:40]:
                print("  [%-5s] %-8s %-14s %s" % (r["has"], r["kind"], r["level"][:12], r["name"][:50]))
            print("\n非规范性条目示例（建议从公开列表下架，本机存档保留）：")
            for r in irr[:15]:
                print("  %s" % r["name"][:56])
        return

    only = [x.strip() for x in a.only.split(",") if x.strip()]
    ledger = load_json(LEDGER, {})
    LEDGER_CACHE = ledger
    idx = load_json(IDX, {"updated": "", "items": {}})
    seeds = seed_map()

    kinds = [x.strip() for x in a.kind.split(",") if x.strip()] or None
    todo = targets_by_name(rows, only=only or None, daily=a.daily,
                           missing_only=not a.all, kinds=kinds)
    if not a.include_nonreg and not only:
        todo = [r for r in todo if r.get("reg")]
    if a.limit:
        todo = todo[:a.limit]
    print("待处理 %d 条（台账已有 %d 条）" % (len(todo), len(ledger)))

    ok = fail = 0
    seen_shas = {v["sha256"]: k for k, v in ledger.items() if v.get("sha256")}
    for i, r in enumerate(todo, 1):
        try:
            good, msg = try_fetch(r, idx, ledger, seen_shas, seeds)
        except Exception as e:
            good, msg = False, "异常 %s" % e
        print("  [%3d/%3d] %-4s %-46s %s" % (i, len(todo), "OK" if good else "—",
                                             r["name"][:46], msg[:80]))
        ok += 1 if good else 0
        fail += 0 if good else 1
        if i % 10 == 0:
            save_json(LEDGER, ledger)
            json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    save_json(LEDGER, ledger)
    idx["updated"] = date.today().isoformat()
    json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    save_json(WORKLIST, dict(wl, stamp={}))          # 让下次重建
    print("\n抓到 %d · 未取到 %d · 台账 %d 条" % (ok, fail, len(ledger)))
    print("本机标准库：", STORE)
    print("如需同步私有库：python3 harvest.py --sync")


if __name__ == "__main__":
    main()
