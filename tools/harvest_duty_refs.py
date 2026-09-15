#!/usr/bin/env python3
"""
补齐「合规义务清单」的条款原文：把 duties.json 里引用、但本机语料库还没有的
出处（法规/规章/规范性文件）从**发布机构官网原文**抓下来，写进
sources/library/corpus/，供 enrich_duties.py 逐条抽条款。

为什么需要这个脚本
------------------
2026-09-15 用户反馈：248 项义务里只有 179 项（72%）挂了条款原文，新增的即时零售、
前置仓、即时配送、零售会员、计量、绿色包装等业务域几乎全空。原因是这批义务引用的
是《食用农产品市场销售质量安全监督管理办法》《餐饮服务食品安全操作规范》这类
**部门规章与规范性文件**，而本机语料库是由 ~/Documents 的 PDF 建的，没这些文。

约定（与 enrich_duties.py 对齐）
-----------------------------
- 原文只来自官方：部委官网 / 中国政府网政策库 / 国家法律法规数据库，绝不转商业站点。
- 文件名必须与 duties.json 的 refs 名称**完全一致**，抽取才能按名称命中。
- 抓不到就如实记为 failed，不写空文件、不臆造。
- 幂等：已入库（同名）即跳过，除非 --force。

用法
----
  python3 tools/harvest_duty_refs.py            # 只抓缺失的
  python3 tools/harvest_duty_refs.py --force    # 重抓全部
  python3 tools/harvest_duty_refs.py --list     # 只列清单与状态
"""
import os, re, sys, json, html, hashlib, subprocess, datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
DUTIES = os.path.join(HERE, "sources", "standards", "duties.json")
FLK = os.path.join(HERE, "sources", "flk_texts", "texts.jsonl")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 名称必须与 duties.json 的 refs 逐字一致
# src=web → 抓 url；src=flk → 从国家法律法规数据库全文库取
REFS = [
    dict(name="食用农产品市场销售质量安全监督管理办法", cat="部门规章", src="web",
         url="https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/"
             "art_6dc95f02953d463b88885cf33a9048ad.html",
         pub="2023-06-30", impl="2023-12-01"),
    dict(name="网络购买商品七日无理由退货暂行办法", cat="部门规章", src="web",
         url="https://www.gov.cn/zhengce/zhengceku/2020-11/03/content_5557118.htm",
         pub="2020-10-23", impl="2017-03-15"),
    dict(name="移动互联网未成年人模式建设指南", cat="规范性文件", src="web",
         url="https://www.cac.gov.cn/2024-11/15/c_1733364304749288.htm",
         pub="2024-11-15", impl="2024-11-15"),
    dict(name="网络直播营销管理办法（试行）", cat="规范性文件", src="web",
         url="https://www.gov.cn/zhengce/zhengceku/2021-04/23/content_5601682.htm",
         pub="2021-04-16", impl="2021-05-25"),
    dict(name="关于落实网络餐饮平台责任切实维护外卖送餐员权益的指导意见",
         cat="规范性文件", src="web",
         url="https://msa.zibo.gov.cn/resources/public/20211123/"
             "%E6%B7%84%E5%8D%9A%E5%B8%82%E5%B8%82%E5%9C%BA%E7%9B%91%E7%9D%A3%E7%AE%A1%E7%90%86"
             "%E5%B1%80%E7%AD%89%E4%B8%83%E9%83%A8%E9%97%A8%E8%BD%AC%E5%8F%91%E5%B8%82%E5%9C%BA"
             "%E7%9B%91%E7%AE%A1%E6%80%BB%E5%B1%80%E7%AD%89%E4%B8%83%E9%83%A8%E9%97%A8%E3%80%8A"
             "%E5%85%B3%E4%BA%8E%E8%90%BD%E5%AE%9E%E7%BD%91%E7%BB%9C%E9%A4%90%E9%A5%AE%E5%B9%B3"
             "%E5%8F%B0%E8%B4%A3%E4%BB%BB%E5%88%87%E5%AE%9E%E7%BB%B4%E6%8A%A4%E5%A4%96%E5%8D%96"
             "%E9%80%81%E9%A4%90%E5%91%98%E6%9D%83%E7%9B%8A%E7%9A%84%E6%8C%87%E5%AF%BC%E6%84%8F"
             "%E8%A7%81%E3%80%8B%E7%9A%84%E9%80%9A%E7%9F%A5.pdf",
         pub="2021-07-26", impl=""),
    # ⚠️ 下面几份暂未取到官方全文，如实留空、不写占位：
    #   ·《关于维护新就业形态劳动者劳动保障权益的指导意见》（人社部发〔2021〕56号）
    #     —— mohrss.gov.cn 返回 JS 挑战页，gov.cn 政策库无独立全文页（只有国务院公报目录）
    #   ·《国务院反垄断委员会关于平台经济领域的反垄断指南》—— 官网正文页未定位到
    #   · 国标/食安国标（GB 7718-2025、GB 28050-2025、GB/T 41391-2022、GB 31621、GB 31605、
    #     GB 4806.1、GB 23350）—— 国标走 openstd 图片阅读器，需 OCR 流水线，另行处理
    # 这些义务（共约 18 项）仍保留出处名称与官方深链，只是页面上不展示条款原文。
    dict(name="餐饮服务食品安全操作规范", cat="规范性文件", src="web",
         url="https://www.samr.gov.cn/cms_files/filemanager/samr/www/samrnew/samrgkml/"
             "nsjg/spjys/202006/W020200617529299543944.pdf",
         pub="2018-06-22", impl="2018-10-01"),
    # 国家法律法规数据库全文（法律层级）
    dict(name="中华人民共和国反垄断法", cat="法律", src="flk", flk="中华人民共和国反垄断法"),
    dict(name="中华人民共和国反食品浪费法", cat="法律", src="flk",
         flk="中华人民共和国反食品浪费法"),
    # 2026-09-15 第二批义务补写新增的引用。法律 / 行政法规 / 司法解释类一律从
    # 国家法律法规数据库**本地全文镜像**取（免外链、免 WAF），部门规章类仍走官网。
    dict(name="中华人民共和国食品安全法实施条例", cat="行政法规", src="flk",
         flk="中华人民共和国食品安全法实施条例"),
    dict(name="中华人民共和国农产品质量安全法", cat="法律", src="flk",
         flk="中华人民共和国农产品质量安全法"),
    dict(name="中华人民共和国计量法实施细则", cat="行政法规", src="flk",
         flk="中华人民共和国计量法实施细则"),
    dict(name="中华人民共和国强制检定的工作计量器具检定管理办法", cat="行政法规", src="flk",
         flk="中华人民共和国强制检定的工作计量器具检定管理办法"),
    dict(name="价格违法行为行政处罚规定", cat="行政法规", src="flk",
         flk="价格违法行为行政处罚规定"),
    dict(name="快递暂行条例", cat="行政法规", src="flk", flk="快递暂行条例"),
    dict(name="互联网平台企业涉税信息报送规定", cat="行政法规", src="flk",
         flk="互联网平台企业涉税信息报送规定"),
    dict(name="网络数据安全管理条例", cat="行政法规", src="flk",
         flk="网络数据安全管理条例"),
    dict(name="中华人民共和国数据安全法", cat="法律", src="flk",
         flk="中华人民共和国数据安全法"),
    dict(name="中华人民共和国电子商务法", cat="法律", src="flk",
         flk="中华人民共和国电子商务法"),
    dict(name="中华人民共和国广告法", cat="法律", src="flk",
         flk="中华人民共和国广告法"),
    dict(name="中华人民共和国反不正当竞争法", cat="法律", src="flk",
         flk="中华人民共和国反不正当竞争法"),
    dict(name="中华人民共和国消费者权益保护法", cat="法律", src="flk",
         flk="中华人民共和国消费者权益保护法"),
    dict(name="中华人民共和国产品质量法", cat="法律", src="flk",
         flk="中华人民共和国产品质量法"),
]

SKIP_AFTER = 400  # 纯文本短于此判为抓错页


def norm(s):
    return re.sub(r"[\s\-—–/／()（）《》【】\[\]:：.、,，]+", "", s or "")


def name_hit(name, text):
    """正文里必须找得到文件名的连续片段，否则判抓错页。

    教训：gov.cn 的 404 页有 ~570 字纯文本，过了长度阈值被当成功入库，
    结果义务挂上一段「页面不存在」。所以长度不够，还得认得出这份文件。
    """
    n, t = norm(name), norm(text)
    if n in t:
        return True
    for L in (12, 10, 8):
        for i in range(0, max(0, len(n) - L) + 1):
            if n[i:i + L] in t:
                return True
    return False


def curl(url, timeout=40):
    """官方站点普遍反爬，必须带完整浏览器头。"""
    cmd = ["curl", "-sSL", "--max-time", str(timeout), "-A", UA,
           "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "-H", "Accept-Language: zh-CN,zh;q=0.9",
           "-H", "Sec-Fetch-Dest: document", "-H", "Sec-Fetch-Mode: navigate",
           "-H", "Sec-Fetch-Site: none", "-H", "Sec-Fetch-User: ?1",
           "-H", "Upgrade-Insecure-Requests: 1", url]
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout


def html_text(raw):
    """HTML → 正文纯文本。官网模板噪声多，取「最长连续正文段」。"""
    s = raw.decode("utf-8", "ignore")
    if not s.strip():
        s = raw.decode("gb18030", "ignore")
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</(p|div|li|tr|h[1-6]|section)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    t = html.unescape(s)
    t = t.replace("\u3000", " ").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in t.split("\n")]
    return "\n".join(x for x in lines if x)


def pdf_text(raw, tmp="/tmp/_dutyref.pdf"):
    with open(tmp, "wb") as f:
        f.write(raw)
    try:
        import fitz
    except Exception:
        return ""
    d = fitz.open(tmp)
    out = [p.get_text() for p in d]
    d.close()
    return "\n".join(out)


def from_flk(title):
    """从国家法律法规数据库全文本地镜像里取一部法的正文。"""
    best = None
    for line in open(FLK, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if (d.get("t") or "").strip() == title:
            x = d.get("x") or ""
            if len(x) > len(best[1] if best else ""):
                best = (d, x)
    return best


def toc_of(text):
    """提取章节目录，供条目页展示。"""
    out = []
    for m in re.finditer(r"^(第[一二三四五六七八九十百]+[章节])\s*(.{2,40})$", text, re.M):
        out.append(f"{m.group(1)} {m.group(2).strip()}")
    return out[:60]


def main():
    argv = sys.argv[1:]
    force = "--force" in argv
    listing = "--list" in argv

    os.makedirs(CORPUS, exist_ok=True)
    idx = json.load(open(IDX, encoding="utf-8")) if os.path.exists(IDX) else {"items": {}}
    items = idx.setdefault("items", {})
    have = {(v.get("name") or "").strip() for v in items.values()}

    # duties.json 里真正被引用的、且语料库缺失的
    duties = json.load(open(DUTIES, encoding="utf-8"))
    refs_used = set()
    for c in duties.get("categories", []):
        for s in c.get("scenes", []):
            for d in s.get("duties", []):
                for r in (d.get("refs") or []):
                    refs_used.add(r.strip())

    todo = [r for r in REFS if r["name"] in refs_used]
    print(f"语料库现有 {len(items)} 条；本次清单 {len(todo)} 项"
          f"（覆盖 {sum(1 for r in todo if r['name'] in refs_used)} 个被引用出处）")

    ok = fail = skip = 0
    report = []
    for r in todo:
        name = r["name"]
        if name in have and not force:
            print(f"  = 已在库  {name}")
            skip += 1
            report.append((name, "in-library", 0, ""))
            continue

        text, note = "", ""
        if r["src"] == "flk":
            got = from_flk(r["flk"])
            if got:
                doc, text = got
                r["pub"], r["impl"] = doc.get("p") or "", doc.get("i") or ""
                note = f"flk:{doc.get('b')}"
            else:
                note = "flk 库中无此标题（全文尚未抓到）"
        else:
            raw = curl(r["url"])
            ctype = raw[:4]
            text = pdf_text(raw) if ctype == b"%PDF" else html_text(raw)
            note = r["url"]

        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        n_art = len(re.findall(r"第[一二三四五六七八九十百]+条", text))
        if len(text) < SKIP_AFTER or not name_hit(name, text):
            print(f"  ✗ 失败    {name}（{len(text)} 字，"
                  f"{'认不出该文件名' if len(text) >= SKIP_AFTER else '太短'}）{note}")
            fail += 1
            report.append((name, "failed", len(text), note))
            continue

        hid = hashlib.sha1((name + text[:400]).encode("utf-8")).hexdigest()[:12]
        with open(os.path.join(CORPUS, hid + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)
        items[hid] = {
            "id": hid, "code": r.get("code", ""), "name": name, "cat": r["cat"],
            "pub": r.get("pub", ""), "impl": r.get("impl", ""), "toc": toc_of(text),
            "src": f"官方原文抓取 · {note}", "chars": len(text),
            "head": text[:400],
        }
        print(f"  ✓ 入库    {name}（{len(text)} 字 / {n_art} 个条款）")
        ok += 1
        report.append((name, "ok", len(text), note))

    idx["updated"] = datetime.date.today().isoformat()
    if not listing:
        json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果：入库 {ok} / 跳过 {skip} / 失败 {fail}；语料库合计 {len(items)} 条")
    print(f"→ {IDX}")


if __name__ == "__main__":
    main()
