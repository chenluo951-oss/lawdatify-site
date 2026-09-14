#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_sources.py —— 检索目标网站（官方集中发布源）注册表

本文件是「每日检索官方来源」的唯一事实来源：
  - 本地内容编辑器（editor_server.py 的「检索来源」标签）在此增删改查；
  - 每日自动化读取 enabled 来源的 host 作为 WebSearch 的 allowed_domains；
  - 新发现的官方集中发布源应写回本注册表，使「人工增加检索来源」真正生效。

条目字段：
  id        唯一标识（kebab，自动生成：host 去点 / 或 name 拼音化失败时的兜底）
  name      来源名称（如「市场监管行政处罚文书网」）
  agency    发布机关（如「国家市场监督管理总局」）
  url       具体栏目 / 深链页（禁官网首页根域名；作为「去哪找」的入口）
  host      用于 allowed_domains 匹配的域名（url 缺省时从 url 推导）
  category  行政处罚 / 信用公示 / 立法发布 / 专项行动 / 通报 / 标准 / 司法 / 综合
  domains   关联合规领域（与 build_topics.DOMAINS 对齐）：数据合规/AI合规/算法合规/平台合规/产品合规/价格合规
  region    全国 / 省-XX
  feed      消费方：news / radar
  tier      来源分级（固定 official；与 sources_tier 口径一致）
  note      备注：为什么收、怎么用
  added     加入日期
  enabled   是否纳入每日检索（人工可临时关停）

用法（编辑器与自动化调用）：
  import search_sources as SS
  SS.load()                       -> {"_meta":..., "items":[...]}
  SS.list(q="", limit=400)       -> {"total","shown","items":[{key,label,sub,topic,status,host,...}]}
  SS.get(id)                     -> 条目 dict 或 None
  SS.allowed_domains()           -> ["cfws.samr.gov.cn", ..., "gov.cn", ...]（去重、含兜底后缀）
  SS.save_entry(entry)           -> 新增或按 id 更新，返回统计
  SS.remove(id)                  -> 删除，返回统计
  SS.as_markdown()               -> 给自动化 prompt 用的可读清单（按 category 分组）
"""
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "seeds.json")

# 兜底域名后缀：即使 seeds.json 未列全，也始终在这些官方域下检索
FALLBACK_SUFFIXES = [
    "gov.cn", "cac.gov.cn", "samr.gov.cn", "miit.gov.cn", "mps.gov.cn",
    "court.gov.cn", "spp.gov.cn", "ndrc.gov.cn", "chinatax.gov.cn",
    "csrc.gov.cn", "neris.csrc.gov.cn", "nfra.gov.cn", "pbc.gov.cn",
    "nmpa.gov.cn", "mee.gov.cn", "customs.gov.cn", "mot.gov.cn",
    "mct.gov.cn", "nrta.gov.cn", "nia.gov.cn", "beian.cac.gov.cn",
    "gsxt.gov.cn", "creditchina.gov.cn", "cfws.samr.gov.cn",
]
CATEGORIES = ["行政处罚", "信用公示", "立法发布", "专项行动", "通报", "标准", "司法", "综合"]
FEEDS = ["news", "radar"]

_cache = None

EMPTY = {"_meta": {"updated": "", "note": "检索目标网站注册表"}, "items": []}


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
    d.setdefault("_meta", {})
    d.setdefault("items", [])
    _cache = d
    return _cache


def save(d):
    global _cache
    d.setdefault("_meta", {})["updated"] = date.today().isoformat()
    os.makedirs(os.path.dirname(SRC), exist_ok=True)
    json.dump(d, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    _cache = d
    return d


# ---------------- 工具 ----------------
def _host_of(url):
    u = (url or "").strip()
    u = re.sub(r"^https?://", "", u)
    u = u.split("/")[0].split("?")[0].split("#")[0]
    u = re.sub(r"^www\.", "", u)
    return u.lower()


def _slug(s):
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", (s or "").lower()).strip("-")
    return s or "src"


def _norm_entry(e):
    e = dict(e or {})
    url = (e.get("url") or "").strip()
    if not e.get("host"):
        e["host"] = _host_of(url)
    if isinstance(e.get("domains"), str):
        e["domains"] = [x.strip() for x in e["domains"].split(",") if x.strip()]
    if isinstance(e.get("feed"), str):
        e["feed"] = [x.strip() for x in e["feed"].split(",") if x.strip() in FEEDS]
    e["feed"] = [x for x in (e.get("feed") or []) if x in FEEDS] or ["news"]
    e["category"] = e.get("category") or "综合"
    e["tier"] = "official"
    e.setdefault("enabled", True)
    e["enabled"] = bool(e["enabled"])
    e.setdefault("added", date.today().isoformat())
    e.setdefault("note", "")
    return e


# ---------------- 读写 ----------------
def stats():
    d = load()
    return {"total": len(d["items"]),
            "enabled": sum(1 for x in d["items"] if x.get("enabled", True)),
            "updated": d.get("_meta", {}).get("updated", "")}


def list(q="", limit=400):
    d = load()
    q = (q or "").strip().lower()
    rows = []
    for it in d["items"]:
        if q and not (q in (it.get("name") or "").lower()
                      or q in (it.get("agency") or "").lower()
                      or q in (it.get("host") or "").lower()
                      or q in (it.get("category") or "").lower()):
            continue
        rows.append({
            "key": it.get("id"),
            "label": it.get("name") or "",
            "sub": it.get("agency") or "",
            "topic": it.get("category") or "",
            "status": it.get("region") or "",
            "host": it.get("host") or "",
            "enabled": it.get("enabled", True),
        })
    rows.sort(key=lambda x: (x["topic"], x["label"]))
    return {"total": len(rows), "shown": len(rows[:limit]),
            "items": rows[:limit]}


def get(id_):
    for it in load()["items"]:
        if it.get("id") == id_:
            return it
    return None


def save_entry(entry):
    """新增或按 id 更新一条来源。"""
    d = load()
    e = _norm_entry(entry)
    id_ = (entry.get("id") or "").strip()
    if not id_:
        id_ = _slug(e.get("host") or e.get("name") or "src")
    # 避免 id 重复
    if not get(id_):
        for x in d["items"]:
            if x.get("id") == id_:
                break
    e["id"] = id_
    items = d["items"]
    for i, x in enumerate(items):
        if x.get("id") == id_:
            merged = dict(x)
            merged.update({k: v for k, v in e.items() if k != "id"})
            items[i] = _norm_entry(merged)
            save(d)
            return {"id": id_, **stats()}
    items.append(e)
    save(d)
    return {"id": id_, **stats()}


def remove(id_):
    d = load()
    before = len(d["items"])
    d["items"] = [x for x in d["items"] if x.get("id") != id_]
    save(d)
    return {"removed": before - len(d["items"]), **stats()}


def allowed_domains(enabled_only=True):
    d = load()
    hosts = set()
    for it in d["items"]:
        if enabled_only and not it.get("enabled", True):
            continue
        h = (it.get("host") or "").strip().lower()
        if h:
            hosts.add(h)
    for s in FALLBACK_SUFFIXES:
        hosts.add(s)
    return sorted(hosts)


def as_markdown():
    """给每日自动化 prompt 用的可读清单（按 category 分组，标 host）。"""
    d = load()
    groups = {}
    for it in d["items"]:
        if not it.get("enabled", True):
            continue
        groups.setdefault(it.get("category") or "综合", []).append(it)
    lines = ["# 本站每日检索的官方集中发布源（enabled）", ""]
    for cat in CATEGORIES:
        items = groups.get(cat)
        if not items:
            continue
        lines.append("## " + cat)
        for it in sorted(items, key=lambda x: x.get("name") or ""):
            lines.append("- **%s**（%s）`%s` — %s" % (
                it.get("name"), it.get("agency"), it.get("host"),
                it.get("note") or ""))
        lines.append("")
    lines.append("> 检索 WebSearch 的 allowed_domains 取以上 host 并集；"
                 "新发现的官方集中发布源请写回 sources/seeds.json。")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--domains":
        print("\n".join(allowed_domains()))
    elif len(sys.argv) > 1 and sys.argv[1] == "--md":
        print(as_markdown())
    else:
        s = stats()
        print("检索来源：%d 条（启用 %d）" % (s["total"], s["enabled"]))
        for it in load()["items"]:
            print("  - [%s] %s  %s" % (
                it.get("category"), it.get("name"), it.get("host")))
