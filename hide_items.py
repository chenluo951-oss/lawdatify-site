#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hide_items.py —— 条目库「下架 / 恢复」管理器（可审核、可回滚）。

背景：知识库条目来自两类来源——① 人工录入的法规/标准（有官方深链、效力层级、义务映射）；
② 从本机文档目录批量合并进来的材料。后者混入了企业制度、第三方法律汇编、境外文件译本、
研究报告、解读文章、无关领域公文等「非规范性材料」，不应出现在公开知识库。

做法：不删除数据，只在 library.json 上打 `hidden: true`，并登记到 excluded.json
（含名称、文号、层级、下架原因、是否「实为真公文、建议恢复」）。渲染层过滤 hidden，
所以下架与恢复都是幂等的、一句话可逆的。

用法：
  python3 hide_items.py --list                 # 看当前下架清单
  python3 hide_items.py --mark-nonreg          # 按规范性判定，下架全部非规范性条目
  python3 hide_items.py --restore "金融消费者权益保护实施办法"   # 恢复某条（名称片段）
  python3 hide_items.py --restore-all          # 全部恢复
"""
import os, re, sys, json, argparse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H

LIB = H.LIB
EXC = os.path.join(HERE, "sources", "standards", "excluded.json")

# 同一文件的「扫描重复件」：知识库已有正式条目 + 官方深链，下架零损失
DUP_HINTS = [
    "未成年人网络保护条例_.01.01生效_下载",
    "中华人民共和国个人信息保护法_.11.01生效_下载",
    "个人信息保护合规审计管理办法_.05.01生效_下载",
    "汽车数据安全管理若干规定-中共中央网络安全和信息化委员会办公室",
    "网络数据安全管理条例_信息产业（含电信）_中国政府网",
]
# 实为真公文、但当前无替代条目：下架会丢内容，标出来请人工拍板
KEEP_HINTS = [
    "金融消费者权益保护实施办法",
    "国家网络安全事件应急预案",
    "检察机关办理侵犯公民个人信息案件指引",
    "人工智能生成合成内容标识方法 文件元数据隐式标识系列实践指南",
    "关于开展电信和互联网行业数据安全检查的通知",
]


def key_of(it):
    return H.norm((it.get("code") or "") + "|" + (it.get("name") or ""))


def load_exc():
    d = H.load_json(EXC, {})
    d.setdefault("_meta", {"desc": "公开知识库下架清单（不打标签展示，仅在渲染层过滤）。"
                                   "hidden=true 的条目本机存档与私有库保留，可随时恢复。",
                           "updated": ""})
    d.setdefault("items", {})
    return d


def save_exc(d):
    d["_meta"]["updated"] = date.today().isoformat()
    d["_meta"]["count"] = len(d["items"])
    d["_meta"]["suggest_keep"] = sorted(k["name"] for k in d["items"].values() if k.get("suggest_keep"))
    H.save_json(EXC, d)


def classify(name, code, kind):
    """给出下架原因分类（用于人工复核，不影响是否下架）。"""
    n = name or ""
    if n in DUP_HINTS:
        return "同一文件的扫描重复件（知识库已有正式条目与官方深链）"
    if re.match(r"^ISO\s*/?\s*IEC|^ISO\b|^IEC\b", n, re.I) or "试译稿" in n:
        return "境外标准/译本，非我国规范性文件"
    if "征求意见稿" in n or "公开征求意见" in n:
        return "征求意见稿/征求意见通知，属立法动态而非现行依据"
    if re.search(r"(合规材料汇集|法律汇编|汇编V\d|KINDING|操作指引|指引——|解读|探索研究|汇总报告|报告9|威胁情报指数|指南：|企业安全建设指南)", n):
        return "第三方汇编/研究报告/解读文章，非官方规范性文件"
    if re.search(r"(制度|附录|验证|工作要求|管理要求)(\s|$)|YRK|咏米|易盾", n):
        return "企业/厂商内部材料"
    if re.search(r"(医保|卫生健康|水利|卫生与健康|人类遗传资源)", n):
        return "与本领域无关的行业公文"
    if re.search(r"(工作报告|工作要点)$", n):
        return "工作报告类，非规范性文件"
    if len(n) <= 6:
        return "标题残缺/信息不足"
    return "非规范性材料（无官方正文，仅本机存档）"


def mark_nonreg():
    lib = H.load_json(LIB, {"items": []})
    wl = H.build_worklist()
    rows = {key_of(r): r for r in wl["rows"]}
    exc = load_exc()
    n = 0
    for it in lib["items"]:
        if it.get("hidden"):
            continue
        k = key_of(it)
        r = rows.get(k)
        if r is None:
            continue
        if r["reg"]:
            continue
        name, code = it.get("name", ""), it.get("code", "")
        rec = {"name": name, "code": code, "level": it.get("level", ""),
               "reason": classify(name, code, it.get("kind", "")),
               "has_doc": r["has"], "hidden_at": date.today().isoformat(),
               "batch": "2026-09-11 非规范性材料清理",
               "suggest_keep": any(h in name for h in KEEP_HINTS)}
        exc["items"][k] = rec
        it["hidden"] = True
        n += 1
    H.save_json(LIB, lib)
    save_exc(exc)
    print("已下架 %d 条；清单 %s" % (n, os.path.relpath(EXC, HERE)))
    sk = [v["name"] for v in exc["items"].values() if v.get("suggest_keep")]
    if sk:
        print("其中「实为真公文、建议恢复」%d 条：" % len(sk))
        for s in sk:
            print("   -", s)


def restore(pat="", all_=False):
    lib = H.load_json(LIB, {"items": []})
    exc = load_exc()
    hit = 0
    for it in lib["items"]:
        if not it.get("hidden"):
            continue
        k = key_of(it)
        if all_ or (pat and pat in (it.get("name") or "")):
            it["hidden"] = False
            exc["items"].pop(k, None)
            hit += 1
    H.save_json(LIB, lib)
    save_exc(exc)
    print("已恢复 %d 条" % hit)


def show():
    exc = load_exc()
    items = exc["items"]
    print("当前下架 %d 条（%s 更新）" % (len(items), exc["_meta"].get("updated")))
    from collections import Counter
    for reason, c in Counter(v["reason"] for v in items.values()).most_common():
        print("  %2d  %s" % (c, reason))
    sk = [v for v in items.values() if v.get("suggest_keep")]
    if sk:
        print("\n建议恢复（实为真公文、下架会丢内容）：")
        for v in sk:
            print("   - %s（%s）" % (v["name"], v["level"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mark-nonreg", action="store_true")
    ap.add_argument("--restore", default="")
    ap.add_argument("--restore-all", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.mark_nonreg:
        mark_nonreg()
    elif a.restore_all:
        restore(all_=True)
    elif a.restore:
        restore(a.restore)
    else:
        show()
