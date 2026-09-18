#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_text_links.py —— 原文阅读器的「法条 → 站内关联」索引

解决的问题（用户 2026-09-18 报障）：
    站内原文库（kb/texts.html）把一部长法排得整整齐齐，却是一份**孤岛**——
    读到《食品安全法》第四十五条，看不出站内有没有引用它的处罚案例、
    有没有围绕它写的专题分析、义务清单里哪几条落在这一条上。
    站内其实三样都有（案例库 640 条、专题分析 9 篇、义务清单 285 项），
    只是没有任何一条数据通路把它们挂到条文上。

产出 kb/links.js（window.LD_LINKS）：
    laws: { "<法规名归一>": {
              "d": "<原文库 doc id>",
              "c": [["cr-xxxx","案例标题","机关","日期","类型"], …],   # 引用本法规的处罚案例
              "a": [["分析标题","../analysis/xxx.html","2026-09-15"], …], # 引用本法规的专题分析
              "w": [["主题大类","场景","义务标题","#d-xxx"], …] }        # 依据本法规的义务
    arts: { "<法规名归一>|第X条": {
              "c": [[…案例…]], "w": [[…义务…]] } }

口径与配套（三处必须一致，改动要同步）：
  · 法规名归一 = 去空白/书名号 → 去「中华人民共和国」前缀 → 去（…修订/修正）后缀
    （与 assets/art-card.js 的 nkey()、tools/build_article_index.py 的 nkey() 同一套）
  · 案例锚点 = "cr-" + md5(url)[:10]（与 tools/build_article_index.py:case_id 同源）
  · 义务锚点 = "d-{分类id}-{场景序号}-{义务序号}"（与 build_standards.render_duty_tree 同源）
  · 原文定位 = "texts.html#<docId>|<第X条>"（与 assets/art-card.js 的链接形态同源）

⚠️ 只收**站内真的引用过**的关系：法规名在原文库找不到对应条目的一律丢弃，
   前端拿不到键就不挂关联入口，绝不出现点了没内容的空壳。
"""
import collections
import hashlib
import io
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEXTS_INDEX = os.path.join(HERE, "kb", "texts", "index.json")
CASES = os.path.join(HERE, "sources", "cases", "cases.json")
CASE_REFS = os.path.join(HERE, "sources", "standards", "case_refs.json")
DUTIES = os.path.join(HERE, "sources", "standards", "duties.json")
ANALYSIS_REG = os.path.join(HERE, "sources", "analysis", "registry.json")
ANALYSIS_DIR = os.path.join(HERE, "analysis")
OUT = os.path.join(HERE, "kb", "links.js")

# 泛称不能当法规名，否则「《办法》第四十五条」会去乱匹配
GENERIC = {"法", "办法", "规定", "条例", "标准", "通知", "公告", "决定", "意见",
           "细则", "规则", "规范", "指南", "要求", "本法", "该法", "有关法律"}

LAW_CHARS = r"[\u4e00-\u9fff0-9A-Za-z（）()〈〉·\-—]{2,60}"
REF_ANY = re.compile("《(" + LAW_CHARS + ")》")
ART = r"第[一二三四五六七八九十百千零〇0-9]+条"


def nkey(name):
    s = re.sub(r"[\s\u3000《》]", "", name or "")
    s = re.sub(r"^中华人民共和国", "", s)
    s = re.sub(r"[（(][^）)]{0,12}(修订|修正|草案|征求意见稿)[）)]$", "", s)
    return "" if len(s) < 3 or s in GENERIC else s


def case_id(url):
    return "cr-" + hashlib.md5((url or "").encode("utf-8")).hexdigest()[:10]


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


# ---------------------------------------------------------------- 1. 法规名 → 原文库条目
def law_docs():
    """归一名 → 原文库条目（同名多版本优先「现行有效」，与 build_article_index 同规则）。"""
    PRI = {"现行有效": 0, "已修改": 1, "即将实施": 2, "已废止": 3}
    idx = (load_json(TEXTS_INDEX) or {}).get("items", [])
    best = {}
    for it in idx:
        k = nkey(it.get("name"))
        if not k:
            continue
        d = it.get("pub") or ""
        score = (PRI.get(it.get("status"), 4), tuple(-int(x) for x in re.findall(r"\d+", d)[:3]))
        if k not in best or score < best[k][0]:
            best[k] = (score, it)
    return {k: v[1] for k, v in best.items()}


# ---------------------------------------------------------------- 2. 案例 → 法规 / 法条
def cases_by_law(keys):
    """法规归一名 → 引用它的案例（含条号级）。"""
    d = load_json(CASES) or {}
    meta, by_law, by_art = {}, collections.defaultdict(list), collections.defaultdict(list)
    for c in d.get("cases", []):
        url = c.get("url") or ""
        if not url:
            continue
        names = set()
        raw = c.get("laws")
        for x in (raw if isinstance(raw, list) else ([raw] if raw else [])):
            k = nkey(x)
            if k:
                names.add(k)
        for m in REF_ANY.finditer((c.get("fact") or "") + "\n" + (c.get("title") or "")):
            k = nkey(m.group(1))
            if k:
                names.add(k)
        hit = [k for k in names if k in keys]
        if not hit:
            continue
        cid = case_id(url)
        meta[cid] = [cid, (c.get("title") or "（未标注标题）")[:90],
                     (c.get("org") or c.get("agency") or ""), (c.get("date") or ""),
                     (c.get("kind") or c.get("type") or "")]
        for k in hit:
            by_law[k].append(cid)
    # 条号级：直接取 build_article_index 的精确结果（它做的是「案例事实里出现的条文号」）
    cr = load_json(CASE_REFS) or {}
    cm = (cr.get("_meta") or {}).get("cases") or {}
    for k, urls in (cr.get("refs") or {}).items():
        law, _, art = k.partition("|")
        if law not in keys or not art:
            continue
        seen = set()
        for u in urls:
            cid = case_id(u)
            if cid in seen:
                continue
            seen.add(cid)
            if cid not in meta:
                m = cm.get(u) or {}
                meta[cid] = [cid, (m.get("t") or "（未标注标题）")[:90], m.get("o") or "",
                             m.get("d") or "", m.get("k") or ""]
            by_art[k].append(cid)
    return meta, by_law, by_art


# ---------------------------------------------------------------- 3. 义务 → 法规 / 法条
def duties_by_law(keys):
    d = load_json(DUTIES) or {}
    by_law, by_art = collections.defaultdict(list), collections.defaultdict(list)
    for c in d.get("categories", []):
        for si, s in enumerate(c.get("scenes", [])):
            for di, du in enumerate(s.get("duties", [])):
                anchor = "d-%s-%d-%d" % (c.get("id"), si, di)
                row = [c.get("name") or "", s.get("name") or "", (du.get("t") or "")[:60], "#" + anchor]
                names, art_pairs = set(), []
                for a in (du.get("articles") or []):
                    doc = a.get("doc") or a.get("src") or ""
                    k = nkey(doc)
                    if not k:
                        continue
                    names.add(k)
                    art = (a.get("art") or "").strip()
                    if re.fullmatch(ART + r"(之[一二三四五六七八九十]+)?", art):
                        art_pairs.append(k + "|" + art)
                for r in (du.get("refs") or []):
                    k = nkey(r)
                    if k:
                        names.add(k)
                for k in names:
                    if k not in keys:
                        continue
                    if row not in by_law[k]:
                        by_law[k].append(row)
                for ak in art_pairs:
                    law = ak.split("|", 1)[0]
                    if law in keys and row not in by_art[ak]:
                        by_art[ak].append(row)
    return by_law, by_art


# ---------------------------------------------------------------- 4. 专题分析 → 法规
def analysis_by_law(keys):
    reg = (load_json(ANALYSIS_REG) or {}).get("articles", [])
    by_law = collections.defaultdict(list)
    for a in reg:
        slug = a.get("slug") or ""
        p = os.path.join(ANALYSIS_DIR, slug + ".html")
        if not os.path.exists(p):
            continue
        txt = io.open(p, encoding="utf-8", errors="ignore").read()
        names = {a.get("key") or ""}
        for m in REF_ANY.finditer(txt):
            names.add(m.group(1))
        uniq = []
        for n in names:
            k = nkey(n)
            if k and k in keys and k not in uniq:
                uniq.append(k)
        row = [(a.get("title") or "")[:90], "../analysis/" + slug + ".html", a.get("date") or ""]
        for k in uniq:
            by_law[k].append(row)
    return by_law


# ---------------------------------------------------------------- 5. 汇总输出
CAP_LAW_CASE, CAP_LAW_DUTY, CAP_LAW_AN = 40, 14, 6
CAP_ART_CASE, CAP_ART_DUTY = 8, 6


def main():
    docs = law_docs()
    keys = set(docs)
    print("原文库法规（归一名）：%d 部" % len(keys))

    cm, c_law, c_art = cases_by_law(keys)
    w_law, w_art = duties_by_law(keys)
    a_law = analysis_by_law(keys)

    def case_rows(ids, cap):
        out, seen = [], set()
        for cid in ids:
            if cid in seen:
                continue
            seen.add(cid)
            m = cm.get(cid)
            if m:
                out.append(m)
        out.sort(key=lambda x: x[3], reverse=True)      # 按日期倒序，新的在前
        return out[:cap]

    def duty_rows(rows, cap):
        # 主题大类 → 场景 的稳定性排序（保持 duties.json 的原始顺序，不用集合顺序）
        return rows[:cap]

    laws, arts = {}, {}
    for k in sorted(keys):
        e = {}
        cs = case_rows(c_law.get(k) or [], CAP_LAW_CASE)
        ws = duty_rows(w_law.get(k) or [], CAP_LAW_DUTY)
        ans = (a_law.get(k) or [])[:CAP_LAW_AN]
        if not (cs or ws or ans):
            continue
        e["d"] = docs[k]["id"]
        if cs:
            e["c"] = cs
        if ws:
            e["w"] = ws
        if ans:
            e["a"] = ans
        laws[k] = e

    for k, ids in c_art.items():
        law, _, art = k.partition("|")
        if law not in keys or not ids:
            continue
        e = {}
        cs = case_rows(ids, CAP_ART_CASE)
        ws = (w_art.get(k) or [])[:CAP_ART_DUTY]
        if cs:
            e["c"] = cs
        if ws:
            e["w"] = ws
        if e:
            e["d"] = docs[law]["id"]
            arts[k] = e

    for k, rows in w_art.items():
        if k in arts:
            continue
        law, _, art = k.partition("|")
        if law not in keys or not rows:
            continue
        arts[k] = {"d": docs[law]["id"], "w": rows[:CAP_ART_DUTY]}

    data = {
        "_meta": {
            "updated": __import__("datetime").date.today().isoformat(),
            "note": "法条 → 站内关联（案例 / 义务 / 专题分析）。由 tools/build_text_links.py 生成。",
            "laws": len(laws), "arts": len(arts),
            "cases": len(cm),
        },
        "laws": laws,
        "arts": arts,
    }

    js = "window.LD_LINKS=" + json.dumps(data, ensure_ascii=False,
                                         separators=(",", ":")) + ";\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(js)
    n_c = sum(len(v.get("c") or []) for v in laws.values())
    n_w = sum(len(v.get("w") or []) for v in laws.values())
    n_a = sum(len(v.get("a") or []) for v in laws.values())
    print("法规级关联：%d 部（案例 %d 条次 · 义务 %d 项次 · 分析 %d 篇次）"
          % (len(laws), n_c, n_w, n_a))
    print("法条级关联：%d 条" % len(arts))
    print("写入 %s（%.0f KB）" % (os.path.relpath(OUT, HERE), len(js.encode("utf-8")) / 1024.0))


if __name__ == "__main__":
    main()
