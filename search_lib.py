#!/usr/bin/env python3
"""
本地法规/标准原文语料库全文检索。

用途：做合规分析、写法律意见、核对标准条款时，直接在本机原文里查，
不必再联网抓取（避免链接失效、版本错误、来源不可溯源）。

用法：
  python3 search_lib.py 关键词                  # 全文检索
  python3 search_lib.py 关键词 -n 20            # 最多 20 条
  python3 search_lib.py 关键词 -c 国家标准       # 只查某类
  python3 search_lib.py 关键词 -x               # 显示命中上下文
  python3 search_lib.py --list 国家标准          # 列出某类全部条目
  python3 search_lib.py --stat                  # 语料库概览
  python3 search_lib.py 关键词 --open 3          # 用系统默认程序打开第 3 条原文

语料位置：sources/library/corpus/（已 gitignore，不上传站点）
"""
import os, re, sys, json, argparse, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
DOCROOT = os.path.expanduser("~/Documents")


def load():
    if not os.path.exists(IDX):
        print("语料索引不存在，请先运行 build_corpus / extract_corpus_all 提取脚本", file=sys.stderr)
        sys.exit(1)
    return json.load(open(IDX, encoding="utf-8"))["items"]


def snippet(text, kw, width=90):
    i = text.find(kw)
    if i < 0:
        return text[:width].replace("\n", " ")
    s = max(0, i - width // 2)
    return ("…" if s > 0 else "") + text[s:i + width].replace("\n", " ") + "…"


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("keyword", nargs="?", help="检索关键词（支持空格分隔的多词，全部命中才算）")
    ap.add_argument("-n", "--limit", type=int, default=15, help="最多结果数，默认 15")
    ap.add_argument("-c", "--cat", default="", help="按类别过滤：国家标准/行业标准/团体标准/法律/行政法规/部门规章/规范性文件/指引指南")
    ap.add_argument("-x", "--context", action="store_true", help="显示命中上下文")
    ap.add_argument("--list", metavar="CAT", help="列出某类别全部条目")
    ap.add_argument("--stat", action="store_true", help="语料库概览")
    ap.add_argument("--open", type=int, metavar="N", help="打开第 N 条原文（配合检索结果序号）")
    a = ap.parse_args()

    items = load()

    if a.stat:
        import collections
        c = collections.Counter(v["cat"] for v in items.values())
        print(f"语料库：{len(items)} 篇，"
              f"总字数 {sum(v['chars'] for v in items.values()):,} 字")
        for k, n in c.most_common():
            print(f"  {k:<10} {n:>5}")
        print(f"\n索引更新：{json.load(open(IDX, encoding='utf-8'))['updated']}")
        return

    if a.list:
        rows = [(cid, v) for cid, v in items.items() if v["cat"] == a.list]
        rows.sort(key=lambda x: x[1]["name"])
        print(f"【{a.list}】{len(rows)} 条")
        for i, (cid, v) in enumerate(rows, 1):
            print(f"{i:>4}. {v['code']:<18} {v['name'][:56]}")
        return

    if not a.keyword:
        ap.print_help()
        return

    kws = [k for k in re.split(r"\s+", a.keyword.strip()) if k]
    hits = []
    for cid, v in items.items():
        if a.cat and v["cat"] != a.cat:
            continue
        path = os.path.join(CORPUS, cid + ".txt")
        if not os.path.exists(path):
            continue
        try:
            txt = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        low = txt.lower()
        if all(k.lower() in low for k in kws):
            # 命中次数用于排序
            hits.append((low.count(kws[0].lower()), cid, v, txt))

    # 排序：法规/标准优先于参考资料，其次按命中次数
    CAT_W = {"法律": 0, "行政法规": 0, "部门规章": 1, "规范性文件": 1,
             "国家标准": 0, "行业标准": 0, "团体标准": 0, "指引指南": 2, "参考资料": 3}
    hits.sort(key=lambda x: (CAT_W.get(x[2]["cat"], 3), -x[0]))
    hits = hits[: a.limit]
    print(f"命中 {len(hits)} 条（关键词：{' '.join(kws)}"
          + (f"，类别：{a.cat}" if a.cat else "") + "）\n")
    for i, (cnt, cid, v, txt) in enumerate(hits, 1):
        print(f"{i:>3}. [{v['cat']}] {v['code']:<18} {v['name'][:52]}  ×{cnt}")
        if a.context:
            print(f"     {snippet(txt, kws[0])}")
        print(f"     原文：{v['src']}")
    if not hits:
        print("无命中。可试试更短的关键词，或用 --list 浏览。")

    if a.open:
        if 1 <= a.open <= len(hits):
            _, cid, v, _ = hits[a.open - 1]
            p = os.path.join(DOCROOT, v["src"])
            if os.path.exists(p):
                subprocess.run(["open", p])
                print(f"\n已打开：{p}")
            else:
                print(f"\n文件不存在：{p}\n（语料文本仍在 {os.path.join(CORPUS, cid + '.txt')}）")
        else:
            print("序号超出范围")


if __name__ == "__main__":
    main()
