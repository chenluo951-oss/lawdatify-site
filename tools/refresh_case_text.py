#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重取被「页面壳」污染的案例正文。

## 背景

`parse_case()` 的老版本用 `re.sub(r"来源：.{0,40}", " ")` 清「信息来源」标签。
`.{0,40}` 贪婪且不限字符类，把标签后面的**正文**一起吃掉：

    信息来源：市场监管总局 市场监管部门针对电动自行车生产、销售领域违法违 → （没了）
    实际存库：… 15:33 信息 管部门针对电动自行车…

实测 376 条（市场监管总局 239 / 地方 122 / 公安部 15）同时带两种伤：
① 面包屑 + 元信息栏原样留在摘要里；② 正文被吃掉几十字。

② 属于**已丢失内容**，只能回原页重取。本脚本就是干这件事：对每条可疑记录
重新拉一次它的 url，用修好的 `parse_case()` 重解析，**只替换 fact / fines**，
其余字段（title / org / type / laws / date）保持不动，避免解析口径变化引起回归。

用法：
    python tools/refresh_case_text.py --dry          # 只看命中多少条
    python tools/refresh_case_text.py                # 实跑
    python tools/refresh_case_text.py --limit 50     # 先试一小批
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from case_text_clean import clean_fact, is_shell  # noqa: E402
from harvest_cases import curl, parse_case        # noqa: E402

CASES = os.path.join(HERE, "sources", "cases", "cases.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 旧解析留下的「断裂」痕迹：清掉标签后残留的孤立词，或正文被吃掉后的拼接
SCARRED = re.compile(
    r"你的位置|您现在的位置|当前位置\s*[:：]|发布时间\s*[:：]|信息来源\s*[:：]|"
    r"第\s*\d+\s*页\s*[,，]?\s*共\s*\d+\s*页"
)


def suspects(cases):
    """需要重取的记录：带页面壳、正文被吃掉，或**撞上 260 字旧上限被截断**。

    第三条是 2026-09 新增：旧上限 260 字让 334 条记录写满即止，而案例库新加的
    「被处罚主体」字段要从正文里取第一个企业名——正文被截断，名字就取不到。
    """
    from case_subject import extract_subject
    out = []
    for c in cases:
        f = c.get("fact") or ""
        if SCARRED.search(f):
            out.append(c)
            continue
        # 正文被吃掉的拼接痕迹：「信息 」后面直接接动词/名词（正常应是「信息来源：机关名」）
        if re.search(r"信息\s*[、，,。]|\s信息\s+[\u4e00-\u9fa5]{1,3}(?:部门|局|委)", f):
            out.append(c)
            continue
        # 撞旧上限 + 正文没写完整（结尾不是句末标点）→ 主体大概率在被切掉的部分
        if len(f) >= 240 and not re.search(r"[。！？；：”\"）)]$", f):
            out.append(c)
            continue
        # 主体取不到，但正文还在 → 回原页看完整正文能不能提到
        if f and not extract_subject(f, c.get("title"))[0]:
            out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.5)
    a = ap.parse_args()

    data = json.load(open(CASES, encoding="utf-8"))
    cases = data["cases"]
    todo = suspects(cases)
    if a.limit:
        todo = todo[:a.limit]
    print(f"案例库 {len(cases)} 条，需重取 {len(todo)} 条")
    if a.dry:
        for c in todo[:10]:
            print("  ·", c.get("org"), "|", (c.get("fact") or "")[:70])
        return

    fixed = failed = shell_left = 0
    for i, c in enumerate(todo, 1):
        url = c.get("url") or ""
        if not url.startswith("http"):
            failed += 1
            continue
        html = curl(url)
        if not html or len(html) < 400:
            failed += 1
            time.sleep(a.delay * 2)
            continue
        old = c.get("fact") or ""
        title = c.get("title") or ""
        try:
            new = parse_case(html, title, url, c.get("org") or "")
        except Exception as e:                       # noqa: BLE001
            failed += 1
            print(f"  ! {i} 解析异常 {e}")
            continue
        nf = new.get("fact") or ""
        # 只在「变干净了」时替换：不是更短就更好，得先确认壳没了
        if nf and not is_shell(nf) and len(nf) >= 30:
            c["fact"] = nf[:900]
            if not c.get("fines") and new.get("fines"):
                c["fines"] = new["fines"]
            if not c.get("laws") and new.get("laws"):
                c["laws"] = new["laws"]
            fixed += 1
        else:
            # 重取也拿不到干净正文（页面本身没正文）→ 就地清洗兜底
            cl = clean_fact(old, title)
            if cl and cl != old:
                c["fact"] = cl[:900]
                fixed += 1
            else:
                shell_left += 1
        if i % 25 == 0:
            print(f"  … {i}/{len(todo)}  修好 {fixed}  失败 {failed}")
        time.sleep(a.delay)

    data["meta"] = data.get("meta") or {}
    data["meta"]["text_cleaned"] = "2026-09-16"
    json.dump(data, open(CASES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n✓ 重取完成：修好 {fixed}，失败 {failed}，仍带壳 {shell_left}")
    left = [c for c in data["cases"] if is_shell(c.get("fact") or "")]
    print(f"✓ 全库仍带页面壳：{len(left)} / {len(data['cases'])}")
    for c in left[:8]:
        print("   ·", c.get("org"), "|", (c.get("fact") or "")[:80])


if __name__ == "__main__":
    main()
