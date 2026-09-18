#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 `kb/algo-index.js` —— 算法备案条目速查索引（按需加载）。

为什么需要它：算法看板上的「算法备案 / 深度合成 / 生成式AI」三类数字如果点了没处去，
就只是读数。法务在这一页真正会问的是「**我们备案了没有 / 这条算法在第几期**」，
所以把 10,624 条备案条目压成一个可过滤的索引，数字点下去即落到条目列表。

体积与加载策略
--------------
  原始 JSON 形式约 1.2 MB。**不随页面加载** —— 由 assets/algo-idx.js 在用户第一次
  点击数字时动态插入 <script>，首屏零成本。压成「行内 \t 分隔、行间 \n」的纯文本，
  再套一层 JSON 字符串，比对象数组小约 10%，也省掉 10k 个对象的解析开销。
  ⚠️ 字段里的 \t / \n 必须替换掉，否则会毁掉整份索引的列结构。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALGO = os.path.join(HERE, "sources", "algo")
OUT = os.path.join(HERE, "kb", "algo-index.js")
COLS = ["名称", "主体", "类别 / 角色 / 属地", "序列", "期次"]


def load(name):
    try:
        return json.load(open(os.path.join(ALGO, name), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clean(s):
    return re.sub(r"[\t\n\r]+", " ", str(s or "")).strip()


def main():
    rows = []
    for b in (load("algo_filing.json").get("batches") or []):
        for r in b["rows"]:
            rows.append([r.get("算法名称"), r.get("主体名称"), r.get("算法类别"),
                         "算法备案", b.get("period")])
    for b in (load("deepfake_filing.json").get("batches") or []):
        for r in b["rows"]:
            rows.append([r.get("算法名称"), r.get("主体名称"), r.get("角色"),
                         "深度合成", b.get("batch") or b.get("period")])
    for b in (load("genai_filing.json").get("batches") or []):
        for r in b["rows"]:
            rows.append([r.get("模型名称"), r.get("备案单位"), r.get("属地"),
                         "生成式AI", b.get("period")])

    txt = "\n".join("\t".join(clean(x) for x in r) for r in rows)
    js = ("/* 算法备案条目速查索引 —— 由 tools/build_algo_index.py 生成，勿手改。\n"
          "   按需加载（首屏不引入）。字段：" + " / ".join(COLS) + " */\n"
          "window.ALGO_RAW=" + json.dumps(txt, ensure_ascii=False) + ";\n")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(js)
    print(f"✓ kb/algo-index.js  {len(rows)} 条  {os.path.getsize(OUT)/1024/1024:.2f} MB")


if __name__ == "__main__":
    main()
