#!/usr/bin/env python3
"""
为「未定位到条款」的义务，用**关键词定位**候选条款号，输出候选供人工确认。

用法：
  python3 map_arts.py propose              # 列出全部缺条款义务的候选（条款号 + 原文片段）
  python3 map_arts.py propose --cat 食品    # 只看某大类
  python3 map_arts.py apply --file picks.json   # 确认后写回 arts_map.json

picks.json 格式： {"cat|scene|duty": [[ref, 条款号], ...]}
"""
import os, re, json, sys, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from enrich_duties import (load_corpus, doc_text, Resolver, split_clauses,
                           DUTIES, ARTS_MAP, terms)


def key_terms(txt):
    """取义务描述里的实词（2-4 字），去掉高频虚词。"""
    ws = re.findall(r"[\u4e00-\u9fa5]{2,4}", txt or "")
    extra = set("应当不得进行或者如果对于关于以及并且不得是否提供使用用户个人信息平台企业商品服务经营销售价格食品数据安全技术管理处理记录保存告知同意目的方式范围期限责任义务主体资质许可查验标签说明贮存运输检验召回投诉举报取消变更续费权限收集最小必要频繁弹窗后台静默".split())
    return [w for w in ws if w not in set("的 了 和 与 或 在 是 有 对 为 以 及 等 不 应 当 须 需 其 之 中 个 者 被 将 由 于 并 且 但 若 如 该 本 上 下 内 外 后 前 时 可 能 要 会 进行 不得 应当".split()) and w not in extra]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["propose", "apply"])
    ap.add_argument("--cat", default="")
    ap.add_argument("--file", default="")
    a = ap.parse_args()

    docs = load_corpus()
    res = Resolver(docs)
    duties = json.load(open(DUTIES, encoding="utf-8"))
    amap = json.load(open(ARTS_MAP, encoding="utf-8"))

    if a.mode == "apply":
        picks = json.load(open(a.file, encoding="utf-8"))
        amap.setdefault("map", {}).update(picks)
        json.dump(amap, open(ARTS_MAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写入 arts_map.json，新增", len(picks), "条")
        return

    cache = {}
    n = 0
    for cat in duties["categories"]:
        if a.cat and a.cat not in cat["name"]:
            continue
        for sc in cat["scenes"]:
            for du in sc["duties"]:
                if du.get("articles"):
                    continue
                n += 1
                kws = key_terms(du.get("t", "") + "。" + du.get("d", ""))
                print(f"\n### {cat['name']}/{sc['name']} || {du.get('t')}")
                print(f"    refs={du.get('refs')}")
                for ref in du.get("refs", []):
                    doc = res.resolve(ref)
                    if not doc:
                        print(f"    [未入库] {ref}")
                        continue
                    if doc["id"] not in cache:
                        cache[doc["id"]] = split_clauses(doc_text(doc)) or []
                    clauses = cache[doc["id"]]
                    if not clauses:
                        print(f"    [无条款结构] {ref}")
                        continue
                    ranked = []
                    for no, body in clauses:
                        hit = [k for k in kws if k in body]
                        if hit:
                            ranked.append((len(hit), no, body, hit[:5]))
                    ranked.sort(key=lambda x: -x[0])
                    for cnt, no, body, hit in ranked[:3]:
                        print(f"    - {ref} | {no} | 命中{cnt}{hit} | {body[:70]}")
    print(f"\n共 {n} 条义务待定位")


if __name__ == "__main__":
    main()
