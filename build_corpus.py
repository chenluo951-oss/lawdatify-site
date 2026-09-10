#!/usr/bin/env python3
"""
从本机 ~/Documents 提取法规/标准原文，建立本地语料库（不上传公开站点）。
输出：
  sources/library/corpus/<id>.txt   全文纯文本
  sources/library/corpus/_index.json 语料索引（含从封面解析的元数据、目次章节）
"""
import os, re, json, sys, hashlib, datetime

ROOT = os.path.expanduser("~/Documents")
SITE = "/Users/luochen/WorkBuddy/Claw/lawdatify-site"
CORPUS = os.path.join(SITE, "sources/library/corpus")
os.makedirs(CORPUS, exist_ok=True)

scan = json.load(open("/tmp/all_scan2.json"))

# ---------- 文本提取 ----------
def pdf_text(path, maxpages=400):
    import fitz
    d = fitz.open(path)
    out = []
    for i, p in enumerate(d):
        if i >= maxpages:
            break
        out.append(p.get_text())
    d.close()
    return "\n".join(out)

def docx_text(path):
    import docx
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)

def text_of(path, ext):
    if ext == ".pdf":
        return pdf_text(path)
    if ext == ".docx":
        return docx_text(path)
    if ext in (".txt", ".md"):
        return open(path, encoding="utf-8", errors="ignore").read()
    return ""

def clean(t):
    t = t.replace("\u3000", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# ---------- 封面元数据解析 ----------
def parse_cover(txt, code_hint):
    head = txt[:3000]
    # 标准号
    m = re.search(r"(T?/?(?:TAF|CCSA|CESA)\s*[0-9]{2,4}(?:\.[0-9]{1,3})?\s*[—–-]\s*20\d{2})", head)
    if not m:
        m = re.search(r"((?:GB|GA|YD|JR|DL|SB|YY|MH|JT|QX|SN)\s*/?\s*[TZ]?\s*\d{2,5}(?:\.\d{1,3})?\s*[—–-]\s*(?:19|20)\d{2})", head)
    code = re.sub(r"\s+", "", m.group(1)).replace("—", "-").replace("–", "-") if m else code_hint
    # 中文名：取标准号后第一个较长的中文行
    name = ""
    if m:
        after = head[m.end():m.end() + 400]
        for line in after.split("\n"):
            s = line.strip()
            if len(re.findall(r"[\u4e00-\u9fa5]", s)) >= 6 and not re.search(r"Technical|Part |发布|实施|ICS|CCS", s):
                name = s
                break
    pub = impl = ""
    mp = re.search(r"(20\d{2})\s*[-年]\s*(\d{1,2})\s*[-月]\s*(\d{1,2})\s*日?\s*发布", head)
    if mp:
        pub = f"{mp.group(1)}-{int(mp.group(2)):02d}-{int(mp.group(3)):02d}"
    mi = re.search(r"(20\d{2})\s*[-年]\s*(\d{1,2})\s*[-月]\s*(\d{1,2})\s*日?\s*实施", head)
    if mi:
        impl = f"{mi.group(1)}-{int(mi.group(2)):02d}-{int(mi.group(3)):02d}"
    issuer = ""
    mi2 = re.search(r"([\u4e00-\u9fa5]{4,20}(?:协会|委员会|研究院|中心|总局|部|管理局|标准化技术委员会))\s*发布", head)
    if mi2:
        issuer = mi2.group(1)
    return code, name, pub, impl, issuer

# ---------- 目次解析 ----------
def parse_toc(txt):
    """提取目次的章节标题（形如 5.2 xxx .... 12）"""
    seg = txt[:20000]
    idx = seg.find("目")
    m = re.search(r"目\s*次", seg)
    start = m.start() if m else 0
    chunk = seg[start:start + 6000]
    items = []
    for line in chunk.split("\n"):
        s = line.strip()
        s = re.sub(r"\.{3,}\s*\d*\s*$", "", s).strip()
        s = re.sub(r"\s+\d{1,3}$", "", s).strip()
        if re.match(r"^(?:[0-9]+(?:\.[0-9]+)*)\s+[\u4e00-\u9fa5]", s) and 4 <= len(s) <= 60:
            items.append(s)
        if len(items) > 80:
            break
    # 去重保序
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x); out.append(x)
    return out[:60]

def norm_code(c):
    c = re.sub(r"\s+", "", str(c)).upper().replace("—", "-").replace("–", "-")
    return c

# ---------- 主流程 ----------
index = {}
stat = {"ok": 0, "fail": 0, "skip": 0}
for key, v in sorted(scan["stds"].items()):
    cands = [f for f in v["files"] if f["ext"] in (".pdf", ".docx", ".txt", ".md")]
    if not cands:
        stat["skip"] += 1
        continue
    # 选最大的
    f = max(cands, key=lambda x: x["size"])
    try:
        raw = text_of(f["full"], f["ext"])
    except Exception as e:
        print("ERR", key, e, file=sys.stderr)
        stat["fail"] += 1
        continue
    if len(raw) < 200:
        stat["skip"] += 1
        continue
    txt = clean(raw)
    code, name, pub, impl, issuer = parse_cover(txt, v["code"])
    toc = parse_toc(txt)
    cid = norm_code(key)
    fp = os.path.join(CORPUS, cid + ".txt")
    open(fp, "w", encoding="utf-8").write(txt)
    index[cid] = {
        "id": cid,
        "code": code,
        "name": name or os.path.splitext(os.path.basename(f["p"]))[0][:60],
        "pub": pub, "impl": impl, "issuer": issuer,
        "toc": toc,
        "src": f["p"],
        "src_ext": f["ext"],
        "chars": len(txt),
        "files": [x["p"] for x in v["files"]],
    }
    stat["ok"] += 1
    print(f"[{stat['ok']}] {cid} {len(txt)}字 {index[cid]['name'][:34]}", flush=True)

json.dump({"updated": datetime.date.today().isoformat(), "items": index},
          open(os.path.join(CORPUS, "_index.json"), "w"), ensure_ascii=False, indent=1)
print("OK", stat, "-> ", CORPUS)
