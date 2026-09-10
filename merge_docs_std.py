#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并本机 Documents 挖掘出的标准数据 → sources/standards/docs_items.json"""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "standards")

def topic_of(name):
    n = name
    if re.search(r"餐饮|食品", n): return "产品与食安合规"
    if re.search(r"人工智能|生成式|算法|深度合成|大模型", n): return "算法与AI合规"
    if re.search(r"App|APP|移动智能终端|SDK|应用软件|移动互联网应用程序|安卓|软件列表|调用行为|签名技术", n): return "移动应用合规"
    if re.search(r"个人信息|隐私|未成年人|告知同意", n): return "个人信息保护"
    if re.search(r"数据", n): return "数据安全"
    return "网络安全"

def level_of(code):
    if code.startswith("GB/T"): return "推荐性国家标准"
    if code.startswith("GB"): return "强制性国家标准"
    if code.startswith(("YD/T", "JR/T", "GA/T")): return "行业标准"
    if code.startswith("T/TAF"): return "团体标准"
    return "其他标准"

items = []

# 1) openstd 国标（gb_fetched.json：目标->dict）
gb = json.load(open(os.path.join(SRC, "gb_fetched.json")))
seen_codes = set()
for target, d in gb.items():
    if not d: continue
    code = d["code"]
    if not re.match(r"^GB", code):  # 名称检索到的可能是已有标准（如 GB/T 45674），跳过
        continue
    if code in seen_codes: continue
    seen_codes.add(code)
    items.append(dict(
        code=code, name=d["name"] if "name" in d else code, level=level_of(code),
        topic=topic_of(d.get("name", "")),
        status="现行有效" if d.get("status") == "现行" else ("已废止" if d.get("status") == "废止" else "现行有效"),
        pub=d.get("pub", ""), impl=d.get("impl", ""),
        issuer="国家市场监督管理总局、国家标准化管理委员会",
        url=f"https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={d['hcno']}",
        point="", duty=[], note="", kind="标准"))

# 2) 行标（hbba_fetched.json）
hb = json.load(open(os.path.join(SRC, "hbba_fetched.json")))
for key, d in hb.items():
    if d["code"] in seen_codes: continue
    seen_codes.add(d["code"])
    items.append(dict(code=d["code"], name=d["name"], level="行业标准",
        topic=topic_of(d["name"]),
        status="现行有效" if d.get("status") == "现行" else "现行有效",
        pub=d.get("pub", ""), impl=d.get("impl", ""),
        issuer=d.get("issuer", "工业和信息化部"),
        url=d["url"], point="", duty=[], note="", kind="标准"))

# 3) TTAF 团标（taf_fetched.json）
taf = json.load(open(os.path.join(SRC, "taf_fetched.json")))
for key, d in taf.items():
    if not d: continue
    if d["code"] in seen_codes: continue
    seen_codes.add(d["code"])
    st = d.get("status", "")
    status = "现行有效" if st in ("", "有效") else "已废止"
    items.append(dict(code=d["code"], name=d["name"], level="团体标准",
        topic=topic_of(d["name"]), status=status,
        pub=d.get("pub", ""), impl=d.get("impl", ""),
        issuer="电信终端产业协会",
        url=d["url"], point="", duty=[], note="",
        kind="标准", series=key.startswith("TTAF") and "T/TAF" in d["code"]))

# 4) GB 31654（食品安全，公告页）
if "GB 31654-2021" not in seen_codes:
    items.append(dict(code="GB 31654-2021", name="食品安全国家标准 餐饮服务通用卫生规范",
        level="强制性国家标准", topic="产品与食安合规", status="现行有效",
        pub="2021-02-22", impl="2022-02-22",
        issuer="国家卫生健康委、国家市场监督管理总局",
        url="https://www.cnis.ac.cn/bydt/kydt/202106/t20210615_51600.html",
        point="我国首部餐饮服务行业规范类食品安全国家标准：场所设施、原料管理、加工控制、供餐与配送（含外卖封签）、留样与自查等全流程要求。",
        duty=["食品安全自查", "食品留样", "配送卫生管理"], note="", kind="标准"))

json.dump(items, open(os.path.join(SRC, "docs_items.json"), "w"), ensure_ascii=False, indent=1)
print(f"docs_items.json: {len(items)} 条")
import collections
print(collections.Counter(i["level"] for i in items))
print(collections.Counter(i["topic"] for i in items))
