#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_amendments.py —— 从法规正文前言里提取「修订沿革」（P2-4 轻量版）

对标：北大法宝「修订沿革」、国家法律法规数据库的「历史版本」。
我们**不做全文版本库**（那需要补历次修订版本全文，数据源不具备），
只做轻量版：把正文前言里已经写明的沿革提炼成一句——
「本法经 N 次修正／修订，最近一次 YYYY-MM-DD」，并链回官方原文。
前言本身就是官方给的沿革说明（「…根据 2019 年 4 月 23 日…《关于修改…的决定》第四次修正」），
所以这不是推测，是逐条读出来的。

数据源：sources/flk_texts/texts.jsonl（全国人大法律法规数据库原文采集）
        kb/texts/index.json（站内原文库目录，用来确认 doc id 有效）
产出：sources/standards/amendments.json   {doc_id: {"n":N,"last":"YYYY-MM-DD","kind":"修正|修订|修正、修订"}}

⚠️ 只读每行的前 900 字符：整文件 113 MB，做完整 JSON 解析纯属浪费——
   沿革只在前言里，而 "x" 是行内最后一个键，前缀就是正文开头。
"""
import collections
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import harvest as H  # noqa: E402

TEXTS = os.path.join(HERE, "sources", "flk_texts", "texts.jsonl")
INDEX = os.path.join(HERE, "kb", "texts", "index.json")
OUT = os.path.join(HERE, "sources", "standards", "amendments.json")

HEAD = 1000          # 每行只取这么长
DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 前言：标题之后第一组括号（中英文皆可）。括号里就是「通过 / 修正 / 修订」沿革。
PAREN = re.compile(r"[（(]([^）)]{20,900})[）)]")
KWD = re.compile(r"修正|修订")


def unesc(s):
    """jsonl 行内的字符串前缀反转义（只需处理 \\n \\" \\\\ 三种）。"""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            break
        d = s[i + 1]
        if d == "n":
            out.append("\n")
        elif d in '"\\/':
            out.append(d)
        elif d == "u":
            try:
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 4
            except ValueError:
                pass
        else:
            out.append(d)
        i += 2
    return "".join(out)


def field(line, key):
    """取行内某键的字符串值（这些短字段都在行首，前缀截取足够）。"""
    m = re.search(r'"%s":"((?:[^"\\]|\\.)*)"' % key, line[:1200])
    return unesc(m.group(1)) if m else ""


def parse_amendment(text, pub):
    """从正文前言解析沿革。返回 None 或 {n,last,kind}。"""
    head = text[:HEAD]
    mm = PAREN.search(head)
    if not mm:
        return None
    pre = mm.group(1)
    # 只认「通过 / 修正 / 修订 / 公布 / 批准 / 废止」这类沿革括号；
    # 正文首句里的括号（如「（以下简称本办法）」）不算前言。
    if not re.search(r"通过|修正|修订|公布|批准|废止", pre):
        return None
    kw = KWD.findall(pre)
    n = len(kw)
    if not n:
        return None
    dates = []
    for y, mo, d in DATE.findall(pre):
        dates.append("%04d-%02d-%02d" % (int(y), int(mo), int(d)))
    last = max(dates) if dates else (pub or "")
    kinds = []
    if "修正" in kw:
        kinds.append("修正")
    if "修订" in kw:
        kinds.append("修订")
    return {"n": n, "last": last, "kind": "、".join(kinds)}


def main():
    idx = json.load(open(INDEX, encoding="utf-8")).get("items", [])
    valid = {}
    for it in idx:
        valid[it["id"]] = it
    print("原文库条目：%d" % len(valid))

    out = {}
    n_lines = n_hit = n_am = 0
    with io.open(TEXTS, encoding="utf-8") as f:
        for line in f:
            n_lines += 1
            i = line.find('"x":"')
            if i < 0:
                continue
            name = field(line, "t")
            code = field(line, "k")
            pub = field(line, "p")
            if not name:
                continue
            tid = hashlib.md5(H.norm((code or "") + name).encode()).hexdigest()[:10]
            if tid not in valid:
                continue
            n_hit += 1
            am = parse_amendment(unesc(line[i + 5:i + 5 + HEAD * 3]), pub)
            if not am:
                continue
            # 同名多版本：取条数最多的一份（新版本的前言包含完整沿革）
            old = out.get(tid)
            if old is None or am["n"] > old["n"]:
                out[tid] = am
                n_am += 1

    json.dump({"_meta": {"updated": __import__("datetime").date.today().isoformat(),
                         "note": "法规修订沿革（由 tools/build_amendments.py 从官方前言提炼）；"
                                 "n = 前言中出现的修正/修订次数，last = 前言里最晚的日期"},
               "items": out},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    c = collections.Counter(v["kind"] for v in out.values())
    print("%d 行 → 命中站内原文 %d 条 → 有沿革 %d 条 %s"
          % (n_lines, n_hit, len(out), dict(c)))
    print("  %s  %.0f KB" % (OUT, os.path.getsize(OUT) / 1024))

    # 抽样自检：几部众所周知的法
    chk = ["中华人民共和国专利法", "中华人民共和国反垄断法", "中华人民共和国广告法",
           "中华人民共和国食品安全法", "中华人民共和国行政处罚法"]
    for it in idx:
        if it["name"] in chk and it["id"] in out:
            v = out[it["id"]]
            print("   %-24s %s版 → 经 %d 次%s · 最近 %s"
                  % (it["name"], it["pub"], v["n"], v["kind"], v["last"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
