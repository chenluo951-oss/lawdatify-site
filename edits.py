#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edits.py —— 人工修改覆盖层

站点内容大多由脚本从语料与台账重建，直接改产物会在下次重建时被覆盖。
本模块提供一层「人工修改覆盖」，由 _private/editor 的本地编辑器写入，
所有 build_* 脚本在生成内容后调用，把人工修正叠加回产物：

  sources/edits/overrides.json
    rules[]    文本替换：按 (kind, key) 定位一段生成文本，做「查找 → 替换」
    patches[]  字段修改：按 (kind, key) 定位一条记录，改指定字段
    hide[]     下架：按 (kind, key) 隐藏某条记录

kind 取值：
  law     法规正文（key = 法规名称）
  std     标准正文（key = 标准编号，如 GBT451232024）
  library 条目库条目（key = code::name）
  duty    合规义务（key = 分类id||场景名||义务标题）
  hot     高频引用法条（key = 法条 id，如 pi-66）

用法（在 build_* 脚本里）：
    import edits as E
    t   = E.apply_rules("law", name, t)
    obj = E.apply_patch("library", key, obj)
    if E.is_hidden("library", key): continue
"""
import os
import json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "edits", "overrides.json")

EMPTY = {"_meta": {"updated": "", "note": "人工修改覆盖层，由本地编辑器写入；不要手改结构，改内容请用编辑器。"},
         "rules": [], "patches": [], "hide": []}

_cache = None


def load(reload=False):
    global _cache
    if _cache is not None and not reload:
        return _cache
    if not os.path.exists(SRC):
        _cache = json.loads(json.dumps(EMPTY, ensure_ascii=False))
        return _cache
    try:
        d = json.load(open(SRC, encoding="utf-8"))
    except Exception:
        d = json.loads(json.dumps(EMPTY, ensure_ascii=False))
    for k in ("rules", "patches", "hide"):
        d.setdefault(k, [])
    _cache = d
    return _cache


def save(d):
    global _cache
    d.setdefault("_meta", {})["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(SRC), exist_ok=True)
    json.dump(d, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _cache = d


# ---------------- 读取 ----------------
def rules_for(kind, key, d=None):
    """返回该 (kind, key) 的全部替换规则，按创建顺序排列。

    每项额外带 idx = 在全局 rules 数组中的下标（供编辑器精确删除）；
    返回的是副本，避免 idx 污染缓存对象后被写回 overrides.json。
    """
    d = d or load()
    out = [dict(r, idx=i) for i, r in enumerate(d["rules"])
           if r.get("kind") == kind and r.get("key") == key]
    return sorted(out, key=lambda r: (r.get("at", ""), r.get("idx", 0)))


def apply_rules(kind, key, text):
    """对一段生成文本依次套用替换规则。空 find 的规则忽略。"""
    if not text:
        return text
    for r in rules_for(kind, key):
        f = r.get("find")
        if not f:
            continue
        text = text.replace(f, r.get("replace", ""))
    return text


def apply_patch(kind, key, obj):
    """对一条记录套用字段修改。返回新对象（不修改入参）。"""
    out = dict(obj or {})
    for p in load()["patches"]:
        if p.get("kind") == kind and p.get("key") == key and p.get("field"):
            out[p["field"]] = p.get("value")
    return out


def is_hidden(kind, key):
    return any(h.get("kind") == kind and h.get("key") == key for h in load()["hide"])


def hidden_keys(kind):
    return {h["key"] for h in load()["hide"] if h.get("kind") == kind}


def is_hidden_lib_key(key):
    return is_hidden("library", key)


def stats():
    d = load()
    return {"rules": len(d["rules"]), "patches": len(d["patches"]), "hide": len(d["hide"]),
            "updated": d.get("_meta", {}).get("updated", "")}


# ---------------- 写入（供本地编辑器调用） ----------------
def add_rule(kind, key, find, replace, note="", label=""):
    d = load()
    d["rules"] = [r for r in d["rules"]
                  if not (r.get("kind") == kind and r.get("key") == key
                          and r.get("find") == find)]
    d["rules"].append({"kind": kind, "key": key, "find": find, "replace": replace,
                       "note": note, "label": label,
                       "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    save(d)
    return stats()


def del_rule(idx):
    d = load()
    if 0 <= idx < len(d["rules"]):
        d["rules"].pop(idx)
        save(d)
    return stats()


def clear_rules(kind=None, key=None):
    d = load()
    d["rules"] = [r for r in d["rules"]
                  if not ((kind is None or r.get("kind") == kind)
                          and (key is None or r.get("key") == key))]
    save(d)
    return stats()


def set_patch(kind, key, field, value, note="", label=""):
    d = load()
    d["patches"] = [p for p in d["patches"]
                    if not (p.get("kind") == kind and p.get("key") == key
                            and p.get("field") == field)]
    d["patches"].append({"kind": kind, "key": key, "field": field, "value": value,
                         "note": note, "label": label,
                         "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    save(d)
    return stats()


def del_patch(idx):
    d = load()
    if 0 <= idx < len(d["patches"]):
        d["patches"].pop(idx)
        save(d)
    return stats()


def set_hidden(kind, key, on=True, label=""):
    d = load()
    d["hide"] = [h for h in d["hide"] if not (h.get("kind") == kind and h.get("key") == key)]
    if on:
        d["hide"].append({"kind": kind, "key": key, "label": label,
                          "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    save(d)
    return stats()


def del_hidden(idx):
    d = load()
    if 0 <= idx < len(d["hide"]):
        d["hide"].pop(idx)
        save(d)
    return stats()


if __name__ == "__main__":
    print(json.dumps(stats(), ensure_ascii=False))
