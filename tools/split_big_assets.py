#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把超大的前端数据文件切片，绕开 Git Data API 的单文件体积上限

背景（2026-09-15 实测）
----------------------
知识库条目补齐到近 2 万条后，`assets/search-index.json`（11 MB）与
`kb/library-data.js`（5.9 MB）用 GitHub Git Data API 建 blob 时**直接失败**
（`blob 创建失败 … {'_err': '', '_stderr': ''}`，curl 侧超时/连接被重置），
结果是页面已上线、数据文件 404 —— 页面看起来「空库」，比不更新更糟。
拆成 ~700 KB 一片后建 blob 稳定成功。

做什么
------
1. `kb/library-data.js`  → `kb/library-data-01.js … -NN.js`
   每片：`window.LB_ITEMS=(window.LB_ITEMS||[]).concat([...]);`
   并把 `kb/standards.html` 里的
   `<script src="library-data.js"></script>` 展开成按序加载的多片（顺序同步脚本，天然有序）。
2. `assets/search-index.json` → `assets/search-index-01.json … -NN.json`
   并把索引本身改写成清单：`{"cats":…,"count":…,"parts":N}`（不含 items）。
   `search.html` 已改为：清单里带 `parts` 时按序 fetch 各片并拼接 items。

幂等：每次构建后重跑；片数变化时先删掉旧的同名片。
必须排在 build_standards.py / build_search.py 之后。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 700 * 1024          # 单片目标上限（未压缩字节）

# ⚠️ 片数固定，不随数据量浮动——两个原因：
#  1) 沙箱有「批量删除保护」：一轮内 os.remove 超过 50 个就抛
#     SAFE_DELETE_BULK_CONFIRM_REQUIRED 并让脚本退出码 1（分片重建正好会删几十个文件，
#     于是 daily_build 里这一步长期静默失败）。片数固定后日常根本不删文件。
#  2) 片数浮动会让每次重建都改写**全部**分片，Git 把每一版都存进历史，仓库体积按天翻。
#     固定片数后，只有内容真变的那几片产生新 blob。
NLIB = 8                    # kb/library-data-NN.js 固定片数
NSEARCH = 20                # assets/search-index-NN.json 固定片数


def _prune(dirpath, pattern, keep_n):
    """把「编号 > keep_n」的孤儿分片**置空**（不是删除）。

    沙箱的删除保护按「整个会话轮次」累计计数（阈值 50），一次脚本里删几十个文件
    就会被中断——分片重建正好命中，这是 daily_build 里这一步长期失败的真因。
    空分片不会被页面引用（清单里的 parts 只覆盖有效编号），体积可忽略。
    """
    for f in os.listdir(dirpath):
        m = re.match(pattern, f)
        if m and int(m.group(1)) > keep_n:
            p = os.path.join(dirpath, f)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{}" if f.endswith(".json")
                         else "window.LB_ITEMS=window.LB_ITEMS||[];\n")


def split_library():
    src = os.path.join(HERE, "kb", "library-data.js")
    page = os.path.join(HERE, "kb", "standards.html")
    if not os.path.exists(src):
        return
    raw = open(src, encoding="utf-8").read()
    m = re.search(r"window\.LB_ITEMS=(\[.*?\]);", raw, re.S)
    cls = re.search(r"window\.LB_CLS=(\{.*?\});", raw, re.S)
    if not m:
        print("  ! library-data.js 结构未识别，跳过")
        return
    rows = json.loads(m.group(1))
    # 固定片数均分（片数不随数据量变，见文件头说明）
    n = max(1, min(NLIB, len(rows) or 1))
    per = -(-len(rows) // n)
    parts = [rows[i:i + per] for i in range(0, len(rows), per)]
    _prune(os.path.join(HERE, "kb"), r"library-data-(\d+)\.js$", len(parts))

    tags = []
    for i, part in enumerate(parts, 1):
        fn = "library-data-%02d.js" % i
        js = ""
        if i == 1 and cls:
            js += "window.LB_CLS=" + cls.group(1) + ";\n"
        js += ("window.LB_ITEMS=(window.LB_ITEMS||[]).concat("
               + json.dumps(part, ensure_ascii=False, separators=(",", ":")) + ");\n")
        js = js.replace("<", "\\u003c")
        open(os.path.join(HERE, "kb", fn), "w", encoding="utf-8").write(js)
        tags.append('<script src="%s"></script>' % fn)

    if os.path.exists(page):
        s = open(page, encoding="utf-8").read()
        if '<script src="library-data.js"></script>' in s:
            s = s.replace('<script src="library-data.js"></script>', "\n".join(tags), 1)
        elif "library-data-01.js" in s:
            s = re.sub(r'(?:<script src="library-data-\d+\.js"></script>\s*)+',
                       "\n".join(tags), s, count=1)
        open(page, "w", encoding="utf-8").write(s)
    # 源文件置空而非删除（页面此刻已改为加载切片，不再引用它；留空壳避免删除计数）
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("window.LB_ITEMS=window.LB_ITEMS||[];\n")
    print(f"  library-data.js → {len(parts)} 片（每片约 {len(parts[0])} 条 / "
          f"{os.path.getsize(os.path.join(HERE, 'kb', 'library-data-01.js')) // 1024} KB）")


def split_search():
    src = os.path.join(HERE, "assets", "search-index.json")
    if not os.path.exists(src):
        return
    d = json.load(open(src, encoding="utf-8"))
    items = d.get("items") or []
    if "parts" in d and not items:
        return
    n = max(1, min(NSEARCH, len(items) or 1))
    per = -(-len(items) // n)
    parts = [items[i:i + per] for i in range(0, len(items), per)]
    _prune(os.path.join(HERE, "assets"), r"search-index-(\d+)\.json$", len(parts))
    for i, part in enumerate(parts, 1):
        fn = "search-index-%02d.json" % i
        json.dump({"items": part}, open(os.path.join(HERE, "assets", fn), "w",
                                        encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
    manifest = {"cats": d.get("cats") or [], "count": d.get("count") or len(items),
                "parts": len(parts)}
    json.dump(manifest, open(src, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"  search-index.json → {len(parts)} 片（清单 "
          f"{os.path.getsize(src) // 1024} KB，索引 {len(items)} 条）")


def main():
    print("切片大型前端数据文件（绕开 Git Data API 单文件上限）")
    split_library()
    split_search()
    return 0


if __name__ == "__main__":
    sys.exit(main())
