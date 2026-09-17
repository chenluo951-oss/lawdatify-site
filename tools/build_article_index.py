#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_article_index.py —— 生成「法条索引」与「法条 → 案例」反向索引

对标北大法宝的两件事（2026-09-17 用户拍板做 P1-1 / P1-2）：
  · 法条悬浮卡（「法宝之窗」）：把页面上的《XX 法》第 X 条变成可悬停的浮层，
    浮层里给出条文原文与官方原文入口 —— **不用跳页**。
  · 法条反向索引（「法条联想」）：一条法条能反查到引用它的案例。
    现状只能「从案例看到依据」，「从法条看到案例」是单向缺失的一半。

产出两份：
  1. kb/arts.js                 window.LD_ARTS —— 悬停浮层要用的条文字典
  2. sources/standards/case_refs.json  {"<法规名归一>|<条>": ["<案例页 url>", ...]}

────────────────────────────────────────────────────────────────────
只收「站内真的引用过」的法条（全站扫描后实测 582 对 / 136 部法规），
所以这份字典很小（几十 KB），可以全站随页面加载 —— 不是把 111 MB 的
原文库搬到浏览器。

⚠️ 键是「法规名归一 + 条号」：
   归一 = 去空白与书名号、去「中华人民共和国」前缀、去「（2025 修订）」后缀。
   所以「中华人民共和国反不正当竞争法」与「反不正当竞争法」命中同一键。
⚠️ 条文原文逐字取自站内官方原文库（kb/texts/*.json），不生成、不改写。
⚠️ 解析不到原文的引用（多为标准或规范性文件，条号体系不同）**静默跳过**，
   前端拿不到键就不挂浮层，不会出现空浮层。
"""
import collections
import hashlib
import html
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

TEXTS_INDEX = os.path.join(HERE, "kb", "texts", "index.json")
TEXTS_DIR = os.path.join(HERE, "kb", "texts")
CASES = os.path.join(HERE, "sources", "cases", "cases.json")
HOT = os.path.join(HERE, "sources", "standards", "hot_articles.json")
AUTO = os.path.join(HERE, "sources", "standards", "hot_articles_auto.json")
OUT_JS = os.path.join(HERE, "kb", "arts.js")
OUT_REFS = os.path.join(HERE, "sources", "standards", "case_refs.json")

# 只扫这些目录找「引用了哪条法条」——sources/ 是原始采集数据，字段形态不统一；
# kb/texts/ 是原文库本体（111 MB），扫它等于把每部法规自己的条文都算成一次引用。
SCAN_DIRS = ("kb", "analysis", "news", "manage", "radar")
SKIP_FILES = {"arts.js"}  # 本脚本自己的产物，避免自引用把字典越滚越大

LAW_CHARS = r"[\u4e00-\u9fff0-9A-Za-z（）()〈〉·\-—]{2,60}"
ART = r"第[一二三四五六七八九十百千零〇0-9]+条"
REF_RE = re.compile("《(" + LAW_CHARS + ")》\\s*(" + ART + ")")
# 条文切分：行首的「第X条」（含「第X条之一」）
ART_SPLIT = re.compile(
    r"(?m)^[ \t\u3000]*((?:第[〇零一二三四五六七八九十百千0-9]+条)(?:之[〇零一二三四五六七八九十]+)?)"
    r"[ \t\u3000]*")


# 泛称（页面上「《办法》第 X 条」这种指代）不能当法规名，否则会拿它去匹配原文库
GENERIC = {"法", "办法", "规定", "条例", "标准", "通知", "公告", "决定", "意见",
           "细则", "规则", "规范", "指南", "要求", "本法", "该法", "有关法律"}


def nkey(name):
    """法规名归一：去空白/书名号/全角空格 → 去「中华人民共和国」前缀 → 去（…修订/修正）后缀。"""
    s = re.sub(r"[\s\u3000《》]", "", name or "")
    s = re.sub(r"^中华人民共和国", "", s)
    s = re.sub(r"[（(][^）)]{0,12}(修订|修正|草案|征求意见稿)[）)]$", "", s)
    return "" if len(s) < 3 or s in GENERIC else s


def art_key(law, art):
    return "%s|%s" % (nkey(law), art)


# ---------------- 1. 站内引用抽取 ----------------
def collect_refs():
    pairs = collections.Counter()

    def eat(txt):
        for m in REF_RE.finditer(txt or ""):
            pairs[(m.group(1), m.group(2))] += 1

    if os.path.exists(CASES):
        for c in json.load(open(CASES, encoding="utf-8")).get("cases", []):
            eat((c.get("fact") or "") + "\n" + (c.get("title") or ""))

    for f in (HOT, AUTO):
        if not os.path.exists(f):
            continue
        for it in json.load(open(f, encoding="utf-8")).get("items", []):
            if it.get("law") and it.get("art"):
                pairs[(it["law"], it["art"])] += 1

    for d in SCAN_DIRS:
        root = os.path.join(HERE, d)
        for dp, dns, fns in os.walk(root):
            dns[:] = [x for x in dns if not x.startswith((".", "_")) and x != "texts"]
            for f in fns:
                if f in SKIP_FILES or not f.endswith((".html", ".md")):
                    continue
                p = os.path.join(dp, f)
                try:
                    eat(io.open(p, encoding="utf-8", errors="ignore").read())
                except OSError:
                    continue
    return pairs


# ---------------- 2. 条文原文解析 ----------------
def load_law_map():
    """归一法规名 → 原文库条目。

    ⚠️ 同名多版本时**必须优先「现行有效」**：库里同时有《商标法》2019 修正版与新修订版
    时，按发布日期取最新会拿到「即将实施」的那版 —— 而站内案例引用的是**当时有效**的
    条号，两版条号会重排，取错版本等于给出错误条文。
    """
    PRI = {"现行有效": 0, "已修改": 1, "即将实施": 2, "已废止": 3}
    idx = json.load(open(TEXTS_INDEX, encoding="utf-8")).get("items", [])
    best = {}
    for it in idx:
        k = nkey(it.get("name"))
        if not k:
            continue
        score = (PRI.get(it.get("status"), 4), _neg_date(it.get("pub")))
        old = best.get(k)
        if old is None or score < old[0]:
            best[k] = (score, it)
    return {k: v[1] for k, v in best.items()}


def _neg_date(d):
    """把日期转成「越大越靠前」的可比较键（取负值参与升序排序）。"""
    return tuple(-int(x) for x in re.findall(r"\d+", d or "")[:3]) or (0,)


_shards = {}


def shard(part):
    if part not in _shards:
        p = os.path.join(TEXTS_DIR, "p-%02d.json" % part)
        _shards[part] = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _shards[part]


def articles_of(doc_id, part):
    """把一部法规的正文按「第X条」切成 {条号: 原文}。"""
    txt = shard(part).get(doc_id) or ""
    if not txt:
        return {}
    ms = list(ART_SPLIT.finditer(txt))
    out = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
        seg = txt[m.start():end].strip()
        seg = re.sub(r"\n{2,}", "\n", seg)
        if len(seg) > 1400:
            seg = seg[:1400] + "…"
        out.setdefault(m.group(1), seg)
    return out


# ---------------- 3. 案例反查 ----------------
def case_id(url):
    return "cr-" + hashlib.md5((url or "").encode("utf-8")).hexdigest()[:10]


def collect_case_refs():
    """{法条键: [案例页 url]}，只收**能上案例库页面**的条目（过 case_gate 闸门）。"""
    if not os.path.exists(CASES):
        return {}, {}
    try:
        from case_gate import classify
    except Exception:
        classify = None
    d = json.load(open(CASES, encoding="utf-8"))
    refs = collections.defaultdict(list)
    meta = {}
    for c in d.get("cases", []):
        if classify:
            try:
                if not classify(c.get("title"), c.get("fact"), c.get("kind"))[0]:
                    continue
            except Exception:
                pass
        url = c.get("url") or ""
        if not url:
            continue
        meta[url] = {"t": c.get("title") or "", "o": c.get("agency") or c.get("org") or "",
                     "d": c.get("date") or "", "k": c.get("kind") or "",
                     "id": case_id(url)}
        seen = set()
        for m in REF_RE.finditer((c.get("fact") or "") + "\n" + (c.get("title") or "")):
            if not nkey(m.group(1)):
                continue
            k = art_key(m.group(1), m.group(2))
            if k in seen:
                continue
            seen.add(k)
            refs[k].append(url)
    return {k: v for k, v in refs.items()}, meta


def main():
    pairs = collect_refs()
    laws = load_law_map()
    case_refs, case_meta = collect_case_refs()
    print("站内引用：%d 个（法规,条）对 / %d 部法规名"
          % (len(pairs), len({nkey(l) for l, _ in pairs})))

    arts = {}
    miss_law = collections.Counter()
    miss_art = []
    for (law, art), n in pairs.items():
        lk = nkey(law)
        if not lk:
            continue  # 泛称（《办法》第 X 条），不是可解析的法规名
        rec = laws.get(lk)
        if not rec:
            miss_law[lk] += 1
            continue
        got = articles_of(rec["id"], rec.get("part") or 1)
        q = got.get(art)
        if not q:
            miss_art.append((law, art))
            continue
        k = art_key(law, art)
        urls = case_refs.get(k, [])
        rows = []
        for u in urls[:8]:
            m = case_meta.get(u) or {}
            rows.append([m.get("id") or case_id(u), m.get("t") or "", m.get("o") or "",
                         m.get("d") or "", m.get("k") or ""])
        arts[k] = [
            q,
            rec["id"],
            rec.get("name") or law,
            rec.get("url") or "",
            len(urls),
            rec.get("status") or "",
            rec.get("impl") or rec.get("pub") or "",
            rows,
        ]

    js = ("window.LD_ARTS=" + json.dumps(arts, ensure_ascii=False, separators=(",", ":"))
          + ";\n")
    js = js.replace("<", "\\u003c")
    open(OUT_JS, "w", encoding="utf-8").write(js)

    # 反向索引：只保留真的解析出条文的键，避免前端挂到空条目上
    refs_out = {k: v for k, v in case_refs.items() if k in arts and v}
    # 给案例库用：每条案例引用了哪些（法条）→ 用于把「依据」列做成可点链接；
    # 以及（法条）→「高频引用法条」页锚点，跨页跳转要稳定 id
    by_case = {}
    for k, urls in case_refs.items():
        for u in urls:
            by_case.setdefault(u, [])
            if k in arts and k not in by_case[u]:
                by_case[u].append(k)
    hot = {}
    for f in (HOT, AUTO):
        if not os.path.exists(f):
            continue
        for it in json.load(open(f, encoding="utf-8")).get("items", []):
            if it.get("id") and it.get("law") and it.get("art"):
                hot.setdefault(art_key(it["law"], it["art"]), it["id"])
    json.dump({"_meta": {"updated": __import__("datetime").date.today().isoformat(),
                         "note": "法条 → 引用它的案例（由 tools/build_article_index.py 生成）",
                         "cases": case_meta,
                         "by_case": {u: ";".join(v) for u, v in by_case.items() if v},
                         "hot": hot,
                         "art_docs": {k: v[1] for k, v in arts.items()}},
               "refs": refs_out},
              open(OUT_REFS, "w", encoding="utf-8"), ensure_ascii=False)

    print("  kb/arts.js            %6.1f KB  （%d 条法条原文）"
          % (len(js.encode("utf-8")) / 1024, len(arts)))
    print("  case_refs.json        %6.1f KB  （%d 条法条有引用案例 / %d 条案例可反查）"
          % (os.path.getsize(OUT_REFS) / 1024, len(refs_out), len(by_case)))
    if miss_art:
        print("  条号未解析：%d 个，如 %s" % (len(miss_art), miss_art[:4]))
    if miss_law:
        print("  法规不在原文库：%d 个，如 %s"
              % (len(miss_law), [x for x, _ in miss_law.most_common(5)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
