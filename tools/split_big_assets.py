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
    # 每个分片的目标行数（按平均行字节估算）
    avg = max(120, len(raw) // max(1, len(rows)))
    per = max(200, int(LIMIT / avg))
    parts = [rows[i:i + per] for i in range(0, len(rows), per)]

    for f in os.listdir(os.path.join(HERE, "kb")):
        if re.match(r"library-data-\d+\.js$", f):
            os.remove(os.path.join(HERE, "kb", f))

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
    os.remove(src)
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
    # 单片目标准入 700KB → 按平均条目字节估
    avg = max(80, os.path.getsize(src) // max(1, len(items)))
    per = max(500, int(LIMIT / avg))
    parts = [items[i:i + per] for i in range(0, len(items), per)]
    for f in os.listdir(os.path.join(HERE, "assets")):
        if re.match(r"search-index-\d+\.json$", f):
            os.remove(os.path.join(HERE, "assets", f))
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
