#!/usr/bin/env python3
"""
补齐 duties.json 所引用法规/标准的**原文**（供 enrich_duties.py 逐字抽条款用）。

来源优先级：
  1. 本机 ~/Documents 已有的 PDF/DOCX/TXT（用 PyMuPDF 抽取，需 venv python）
  2. 发布机构官网正文页（中国政府网政策文件库 / 部门官网），用 curl 抓取

产出（均不上传公开站点）：
  ~/Documents/2.法规、 标准、指南等/0.站点标准库/<name>.txt
  sources/library/corpus/<id>.txt + _index.json（供 enrich_duties 检索）
  sources/standards/library.json（补/正条目的 名称、效力层级、状态、官方深链）

用法：
  python3 fetch_laws.py --list         # 列出待补清单与当前状态
  python3 fetch_laws.py               # 抓取全部缺失项
  python3 fetch_laws.py --only 食品安全法,价格法
"""
import os, re, sys, json, hashlib, subprocess, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STD_DIR = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库")
DOC_DIR = os.path.expanduser("~/Documents/2.法规、 标准、指南等")
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
LIB = os.path.join(HERE, "sources", "standards", "library.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# ---------------------------------------------------------------- 待补清单
# ref: duties.json 中使用的简称；query: 用于在中国政府网政策库检索官方深链
# url 均为发布机构/国家法律法规数据库官网的具体正文页（非首页），已用 curl 实测可达
TARGETS = [
    # —— 法律 ——
    dict(ref="食品安全法", name="中华人民共和国食品安全法", cat="法律", level="法律",
         issuer="全国人民代表大会常务委员会", status="现行有效", impl="2025-12-01",
         url="https://sjfg.samr.gov.cn/law/file/pdf/3235243/1663322301314.pdf", kind="pdf",
         link="https://sjfg.samr.gov.cn/law/file/pdf/3235243/1663322301314.pdf"),
    dict(ref="食品安全法实施条例", name="中华人民共和国食品安全法实施条例", cat="行政法规", level="行政法规",
         issuer="国务院", status="现行有效", impl="2019-12-01",
         url="https://www.gov.cn/zhengce/zhengceku/2019-10/31/content_5447142.htm"),
    dict(ref="价格法", name="中华人民共和国价格法", cat="法律", level="法律",
         issuer="全国人民代表大会常务委员会", status="现行有效", impl="1998-05-01",
         url="https://wb.flk.npc.gov.cn/flfg/PDF/d56096eb7cfa4bd29a20301d1ec49b2f.pdf", kind="pdf"),
    dict(ref="价格法2", name="中华人民共和国价格法", cat="法律", level="法律",
         issuer="全国人民代表大会常务委员会", status="现行有效", impl="1998-05-01",
         url="https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/201105/t20110531_779962.html",
         link="https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/201105/t20110531_779962.html"),
    dict(ref="消费者权益保护法", name="中华人民共和国消费者权益保护法", cat="法律", level="法律",
         issuer="全国人民代表大会常务委员会", status="现行有效", impl="2014-03-15",
         url="http://www.npc.gov.cn/zgrdw//npc///lfzt/xfzqybhfxza/2013-04/19/content_1792348.htm"),
    dict(ref="消费者权益保护法实施条例", name="中华人民共和国消费者权益保护法实施条例", cat="行政法规", level="行政法规",
         issuer="国务院", status="现行有效", impl="2024-07-01",
         url="https://www.gov.cn/zhengce/zhengceku/202403/content_6940159.htm"),
    dict(ref="电子商务法", name="中华人民共和国电子商务法", cat="法律", level="法律",
         issuer="全国人民代表大会常务委员会", status="现行有效", impl="2019-01-01",
         url="http://www.npc.gov.cn/zgrdw//npc////////lfzt/rlyw/2018-08/31/content_2060827.htm"),
    dict(ref="网络安全法", name="中华人民共和国网络安全法", cat="法律", level="法律",
         issuer="全国人民代表大会常务委员会", status="现行有效", impl="2026-01-01",
         url="https://www.ghxrd.gov.cn/zlk_0/zcfg/202511/t20251110_229733.html",
         link="http://www.npc.gov.cn/c2/c30834/202510/t20251028_449048.html"),
    # —— 部门规章 ——
    dict(ref="网络食品安全违法行为查处办法", name="网络食品安全违法行为查处办法", cat="部门规章", level="部门规章",
         issuer="国家食品药品监督管理总局", status="现行有效", impl="2016-10-01",
         url="https://www.gov.cn/gongbao/content/2017/content_5174527.htm"),
    dict(ref="网络餐饮服务食品安全监督管理办法", name="网络餐饮服务食品安全监督管理办法", cat="部门规章", level="部门规章",
         issuer="国家食品药品监督管理总局", status="现行有效", impl="2018-01-01",
         url="https://www.gd.gov.cn/zwgk/wjk/zcfgk/content/post_2532108.html"),
    dict(ref="个人信息出境标准合同办法", name="个人信息出境标准合同办法", cat="部门规章", level="部门规章",
         issuer="国家互联网信息办公室", status="现行有效", impl="2023-06-01",
         url="https://www.cac.gov.cn/2023-02/24/c_1678884830036813.htm"),
]

# 本地已有的 PDF（语料库未收录的），直接抽取入语料库
LOCAL_FILES = [
    ("GB/T 41391", "GB/T 41391-2022 信息安全技术 移动互联网应用程序（App）收集个人信息基本要求",
     "05-移动应用与互联网服务合规/009-GB_T 41391-2022 信息安全技术 移动互联网应用程序（App）收集个人信息基本要求.pdf",
     "推荐性国家标准", "国家标准", "全国信息安全标准化技术委员会", "现行有效", "2023-05-01"),
    ("GB/T 43697", "GB/T 43697-2024 数据安全技术 数据分类分级规则",
     "03-数据安全与数据合规/GB_T 43697-2024 数据安全技术 数据分类分级规则.pdf",
     "推荐性国家标准", "国家标准", "全国信息安全标准化技术委员会", "现行有效", "2024-10-01"),
]


def curl(url, timeout=40, binary=False):
    cmd = ["curl", "-sL", "-m", str(timeout), "-A", UA,
           "-H", "Accept-Language: zh-CN,zh;q=0.9", url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    except subprocess.TimeoutExpired:
        return ""
    if binary:
        return r.stdout
    return r.stdout.decode("utf-8", "ignore")


def html_text(h):
    h = re.sub(r"<script[\s\S]*?</script>", " ", h, flags=re.I)
    h = re.sub(r"<style[\s\S]*?</style>", " ", h, flags=re.I)
    h = re.sub(r"<!--[\s\S]*?-->", " ", h)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</(p|div|tr|li|h\d|table)>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", "", h)
    import html as _h
    h = _h.unescape(h)
    h = re.sub(r"[ \t\u3000]+", " ", h)
    h = re.sub(r"\n\s*\n\s*\n+", "\n\n", h)
    return h.strip()


def gov_search(query):
    """用中国政府网政策文件库检索官方深链。返回 (title, url, puborg)。"""
    import urllib.parse
    q = urllib.parse.quote(query)
    url = ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gw&q=%s"
           "&sort=score&sortType=1&searchfield=title&p=1&n=8" % q)
    raw = curl(url, timeout=25)
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except Exception:
        return []
    out = []
    for it in ((d.get("searchVO") or {}).get("listVO") or []):
        t = re.sub(r"</?em>", "", it.get("title", ""))
        out.append((t.strip(), it.get("url", ""), it.get("puborg", "")))
    return out


def pick_url(query, name):
    cands = gov_search(query)
    if not cands:
        return None, None
    key = name.replace("中华人民共和国", "")
    for t, u, org in cands:
        if key in t:
            return u, t
    for t, u, org in cands:
        if t and t.rstrip("0123456789") in name:
            return u, t
    return cands[0][1], cands[0][0]


# ---------------------------------------------------------------- 语料库写入
def load_index():
    if os.path.exists(IDX):
        return json.load(open(IDX, encoding="utf-8"))
    return {"updated": "", "items": {}}


def save_index(idx):
    idx["updated"] = datetime.date.today().isoformat()
    json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def add_doc(idx, name, code, cat, text, src):
    """写入语料库（去同名重复，取更长的一版）。"""
    if not text or len(text) < 400:
        return None, "too-short(%d)" % len(text or "")
    key = re.sub(r"[\s\-—–/／\(\)（）《》【】\[\]:：.、,，]+", "", (code or "") + name).upper()
    for k, v in idx["items"].items():
        vk = re.sub(r"[\s\-—–/／\(\)（）《》【】\[\]:：.、,，]+", "",
                    (v.get("code") or "") + (v.get("name") or "")).upper()
        if vk == key:
            # 已有条目过短（多为目次/摘要），用更完整的版本替换
            if len(text) > int(v.get("chars", 0) or 0) * 2:
                open(os.path.join(CORPUS, k + ".txt"), "w", encoding="utf-8").write(text)
                v["chars"] = len(text)
                v["src"] = src
                v["head"] = text[:400]
                return k, "upgraded(%d)" % len(text)
            return k, "exists(%d)" % v.get("chars", 0)
    did = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
    open(os.path.join(CORPUS, did + ".txt"), "w", encoding="utf-8").write(text)
    idx["items"][did] = {
        "id": did, "code": code or "", "name": name, "cat": cat,
        "pub": "", "impl": "", "toc": [], "src": src,
        "chars": len(text), "head": text[:400],
    }
    return did, "added(%d)" % len(text)


def upsert_library(name, code, cat, level, issuer, status, impl, url):
    lib = json.load(open(LIB, encoding="utf-8"))
    items = lib["items"]
    nk = re.sub(r"[\s\-—–/／\(\)（）《》]+", "", name).upper()
    hit = None
    for it in items:
        if re.sub(r"[\s\-—–/／\(\)（）《》]+", "", it.get("name", "")).upper() == nk:
            hit = it
            break
        if code and it.get("code") and re.sub(r"[\s\-]+", "", it["code"]).upper() == re.sub(r"[\s\-]+", "", code).upper():
            hit = it
            break
    if hit is None:
        hit = {"code": code or "", "name": name, "level": level or cat, "topic": "",
               "status": status, "pub": "", "impl": impl or "", "issuer": issuer or "",
               "url": url or "", "point": "", "duty": [], "note": "", "kind": "法规"}
        items.append(hit)
    else:
        for k, v in (("code", code), ("level", level), ("issuer", issuer),
                     ("status", status), ("impl", impl), ("url", url)):
            if v:
                hit[k] = v
    lib["updated"] = datetime.date.today().isoformat()
    json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    os.makedirs(CORPUS, exist_ok=True)
    os.makedirs(STD_DIR, exist_ok=True)
    idx = load_index()
    only = [x.strip() for x in args.only.split(",") if x.strip()]

    # 1) 本地 PDF 补录
    if not only or any(o in ("GB/T 41391", "GB/T 43697") for o in only):
        import fitz  # noqa
        for ref, name, rel, level, cat, issuer, status, impl in LOCAL_FILES:
            p = None
            for base in ("知识库-AI按主题分类", "1.合规专题分类", "3.国标、行标、团标等标准文件", "2.法律法规"):
                cand = os.path.join(DOC_DIR, base, rel)
                if os.path.exists(cand):
                    p = cand
                    break
            if not p:
                print("[skip] %s 本地未找到" % name)
                continue
            d = fitz.open(p)
            text = "\n".join(pg.get_text() for pg in d)
            d.close()
            did, msg = add_doc(idx, name, ref.replace("/", "").replace(" ", ""), cat, text,
                               os.path.relpath(p, os.path.expanduser("~/Documents")))
            if did:
                open(os.path.join(STD_DIR, re.sub(r"[/\s]+", "_", name) + ".txt"), "w",
                     encoding="utf-8").write(text)
                upsert_library(name, ref.replace("GB/T ", "GB/T"), cat, level, issuer, status, impl, "")
            print("[local] %-52s %s" % (name[:52], msg))

    # 2) 联网抓取
    for t in TARGETS:
        if only and t["ref"] not in only and t["name"] not in only:
            continue
        url = t.get("url")
        if not url:
            url, got = pick_url(t.get("query", t["name"]), t["name"])
            if not url:
                print("[fail ] %-30s 未检索到官方页" % t["name"][:30])
                continue
        if t.get("kind") == "pdf":
            import fitz, tempfile
            raw = curl(url, timeout=60, binary=True)
            if len(raw) < 5000:
                print("[short] %-30s PDF %d 字节" % (t["name"][:30], len(raw)))
                continue
            fp = os.path.join(tempfile.gettempdir(), "fl_%s.pdf" % abs(hash(url)))
            open(fp, "wb").write(raw)
            try:
                d = fitz.open(fp)
                text = "\n".join(pg.get_text() for pg in d)
                d.close()
            except Exception as e:
                print("[err  ] %-30s %s" % (t["name"][:30], e))
                continue
        else:
            text = html_text(curl(url))
        if len(text) < 2000:
            print("[short] %-30s %d 字 -> %s" % (t["name"][:30], len(text), url))
            continue
        did, msg = add_doc(idx, t["name"], t.get("code", ""), t["cat"], text, url)
        if did:
            open(os.path.join(STD_DIR, re.sub(r"[/\s]+", "_", t["name"]) + ".txt"), "w",
                 encoding="utf-8").write(text)
            upsert_library(t["name"], t.get("code", ""), t["cat"], t["level"],
                           t.get("issuer", ""), t.get("status", "现行有效"), t.get("impl", ""),
                           t.get("link") or url)
        print("[fetch] %-30s %s" % (t["name"][:30], msg))

    save_index(idx)
    print("\n语料库条目：%d" % len(idx["items"]))


if __name__ == "__main__":
    main()
