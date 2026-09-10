#!/usr/bin/env python3
"""
把本机原文语料库（sources/library/corpus）中的法规/标准/指南条目，
合并进 sources/standards/library.json，与既有条目去重。

原则：
  - 只纳入 法律/行政法规/部门规章/规范性文件/国家标准/行业标准/团体标准/指引指南
  - "参考资料"（研究报告、内部制度、课件等）不进站点知识库条目
  - 去重键：有标准号按标准号；无标准号按名称归一化
  - 语料只提供 章节目录(toc) 与元信息，原文正文不上传（版权）
"""
import json, os, re, sys, datetime

SITE = os.path.dirname(os.path.abspath(__file__))
CORPUS_IDX = os.path.join(SITE, "sources/library/corpus/_index.json")
LIB = os.path.join(SITE, "sources/standards/library.json")

TOPIC_RULES = [
    ("算法与AI合规", r"人工智能|生成式|算法|大模型|AI|深度合成|机器学习|模型|训练数据|标识方法|合成内容"),
    ("个人信息保护", r"个人信息|隐私|人脸|生物特征|未成年人|去标识化|匿名化|告知同意|敏感个人信息|合规审计"),
    ("数据安全", r"数据安全|数据分类|分级|重要数据|数据出境|数据流通|数据交易|数据提供|委托处理|共同处理|公共数据|数据质量|数据治理"),
    ("网络安全", r"网络安全|等级保护|漏洞|密码|信息安全|关键信息基础设施|风险评估|攻防|入侵|防火墙|VPN|零信任|态势感知"),
    ("移动应用合规", r"APP|App|应用程序|移动智能终端|SDK|分发平台|权限|摇一摇|开屏|预置"),
    ("平台合规", r"平台|电商|网络交易|经营者|直播|广告|消费者权益|反不正当竞争|价格|竞争"),
    ("数据跨境", r"出境|跨境|境外|全球化|SCC|标准合同"),
]

CAT_LEVEL = {
    "法律": "法律",
    "行政法规": "行政法规",
    "部门规章": "部门规章",
    "规范性文件": "规范性文件",
    "国家标准": "推荐性国家标准",
    "行业标准": "行业标准",
    "团体标准": "团体标准",
    "指引指南": "指引/指南",
}

# 文件名 -> (编号, 名称) 清洗
RE_CODE_IN_NAME = re.compile(
    r"((?:GB|GA|YD|JR|DL|SB|YY|MH|JT|QX|SN|CB)\s*[∕/]?\s*[TZ]?\s*\d{2,5}(?:\.\d{1,3}){0,3}\s*[—–\-]?\s*(?:19|20)?\d{0,4}"
    r"|(?:T\s*[∕/]\s*)?(?:TAF|CCSA|CESA|CSAE|CECC|AIA|GDA|SDA)\s*\d{2,4}(?:\.\d{1,3}){0,3}\s*[—–\-]?\s*(?:19|20)?\d{0,4}"
    r"|TC260\s*[-–—]?\s*PG\s*[-–—]?\s*\d{4}[A-Za-z]?)", re.I)
JUNK_NAME = re.compile(r"^(中华人民共和国国家标准|网络安全标准实践指南|数据安全技术|信息技术|犐|WD_|GB|T\s*$|本技术文件)", re.I)

def clean_name_from_file(path, cover_name):
    """优先用文件名还原标准/法规名称"""
    base = os.path.splitext(os.path.basename(path))[0]
    s = base
    s = RE_CODE_IN_NAME.sub("", s)
    s = re.sub(r"^WD_?\d*_?", "", s, flags=re.I)
    s = re.sub(r"20\d{2}[-年]?\d{0,2}[-月]?\d{0,2}日?", "", s)
    s = re.sub(r"[（(].*?(?:征求意见稿|送审稿|报批稿|试行|版)[)）]", "", s)
    s = re.sub(r"_\d+$", "", s)                 # 副本标记 _2
    s = re.sub(r"^[0-9]{1,3}[.、\-_\s]+", "", s)  # 序号前缀
    s = re.sub(r"^\s*标准\s*\d*\s*[:：]?\s*", "", s)
    s = s.replace("∕", "/").replace("／", "/")
    s = re.sub(r"[\s\u3000]+", " ", s).strip(" -_—－·")
    # 名称过短或是通用词 -> 用封面解析结果
    if len(re.findall(r"[\u4e00-\u9fa5]", s)) < 4 or JUNK_NAME.match(s):
        s = cover_name
    s = re.sub(r"[\s\u3000]+", " ", s).strip(" -_—－·")
    return s[:80]

def code_from_file(path):
    base = os.path.basename(path)
    m = RE_CODE_IN_NAME.search(base)
    if not m:
        return ""
    c = re.sub(r"\s+", "", m.group(1))
    c = c.replace("∕", "/").replace("／", "/").replace("—", "-").replace("–", "-")
    c = c.upper()
    c = c.replace("GB/T", "GB/T ").replace("GB/T", "GB/T ")
    return c.strip("- ")

# ---- 噪音过滤：企业内部制度、书籍、报告、问卷等 ----
RE_CORP = re.compile(
    r"微医|朴朴|态棒|网易|平安云厨|掌上核心区|一手服装|TTHotel|咪咕|"
    r"有限公司|股份有限公司|集团|门诊部|医院|药房|药店|车库|门店|事业部|"
    r"杜霞|交接|WY-LEGAL|内部|制度汇编|员工手册|岗位职责", re.I)
RE_NOTLAW = re.compile(
    r"^(【好书必读】|【中文编译】)|好书必读|中文编译|"
    r"问卷|测评报告|检测报告|调研|蓝皮书|白皮书|研究报告|产业报告|行研|案例研究|"
    r"简介|手册|课件|培训|直播|课程|讲义|PPT|汇报|周报|日报|月报|总结|规划方案|"
    r"合同|协议|发票|简历|面试|PwC|德勤|普华|安永|毕马威|"
    r"国家标准文本|附件\d|^\d+[.、]", re.I)

def is_excluded(name, src):
    """企业内控制度/书籍/报告 -> True（不进公开知识库条目）"""
    if RE_NOTLAW.search(name):
        return True
    # 路径或名称含企业标识，且不是公开发文机关
    if RE_CORP.search(name) or RE_CORP.search(src):
        return True
    if len(re.findall(r"[\u4e00-\u9fa5]", name)) < 4:
        return True
    return False

RE_STD_CODE_STRICT = re.compile(r"^(GB|GA|YD|JR|DL|SB|YY|MH|JT|QX|SN|CB|TTAF|CCSA|CESA|CSAE)", re.I)

def override_cat(code, name, cat):
    """有正式标准号的一律归为对应标准层级，避免被'要求/规范'误判成规范性文件"""
    c = (code or "").upper()
    if c.startswith("GB"):
        return "强制性国家标准" if re.match(r"^GB\s*\d", c) else "国家标准"
    if c.startswith("TTAF") or c.startswith("CCSA") or c.startswith("CESA"):
        return "团体标准"
    if re.match(r"^(YD|JR|GA|DL|SB|YY|MH|JT|QX|SN|CB)", c):
        return "行业标准"
    # 名称里带 GB/T 但 code 没解析到
    if RE_STD_CODE_STRICT.match(name or ""):
        return "国家标准"
    return cat

def tidy_name(name):
    s = name
    s = re.sub(r"^\s*T\s+(?=[\u4e00-\u9fa5A-Z])", "", s)          # 残留的 "T " 前缀
    s = re.sub(r"^\s*(?:GB|GA|YD|JR|TTAF|CCSA)\s*[∕/]?\s*[TZ]?\s*[\d.x]+\s*[—–-]?\s*(?:19|20)?\d{0,4}\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*(?:GB|GA|YD|JR|TTAF|CCSA)\s*[∕/]?\s*[TZ]?\s*[xX]{3,}\s*", "", s, flags=re.I)
    s = re.sub(r"^【[^】]*】", "", s)
    s = re.sub(r"^\s*0?\d{1,3}[.、\-\s]*(?=[\u4e00-\u9fa5《])", "", s)  # "34关于…" "02《…》"
    s = re.sub(r"[（(]\s*[)）]", "", s)
    s = s.replace("GB_T", "GB/T").replace("GB_T", "GB/T")
    s = re.sub(r"_\d+$", "", s)
    s = re.sub(r"^\s*0?\d{1,2}[.、\-\s]+", "", s)
    s = re.sub(r"^\s*TC260\s*\d{3}\s*[-–—]\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*第?\s*\d{1,3}\s*部分\s*[:：\-—]?\s*", "", s)
    s = re.sub(r"[（(]([^)）]*)[)）]$", r" \1", s)
    s = re.sub(r"[\s\u3000]+", " ", s).strip(" -_—－·")
    return s[:80]

def guess_topic(name):
    for topic, pat in TOPIC_RULES:
        if re.search(pat, name):
            return topic
    return "其他"

def norm_key(code, name):
    if code:
        return re.sub(r"[\s—–-]+", "", code).upper()
    n = re.sub(r"[（(].*?[)）]", "", name)
    n = re.sub(r"[\s、，,。.:：\-—–]+", "", n)
    return n[:40]

def detect_status(item):
    if "失效" in item.get("src", "") or "废止" in item.get("src", ""):
        return "已废止"
    return "现行有效"

def main():
    if not os.path.exists(CORPUS_IDX):
        print("缺少语料索引，请先运行 build_corpus 提取脚本")
        sys.exit(1)
    corpus = json.load(open(CORPUS_IDX, encoding="utf-8"))["items"]
    lib = json.load(open(LIB, encoding="utf-8"))
    items = lib["items"]

    # 既有条目键
    def lib_keys(it):
        ks = set()
        c = re.sub(r"[\s—–-]+", "", it.get("code", "") or "").upper()
        if c:
            ks.add(c)
        txt = (it.get("code", "") or "") + " " + (it.get("name", "") or "")
        for m in re.findall(r"(GB/?T?\s*\d+(?:\.\d+)?|YD/?T\s*\d+|JR/?T\s*\d+|TTAF\s*\d+(?:\.\d+)?|TC260[-–—]PG[-–—]\d{4}[A-Z]?|GA/?T?\s*\d+(?:\.\d+)?)", txt, re.I):
            ks.add(re.sub(r"[\s—–-]+", "", m).upper())
        ks.add(norm_key("", it.get("name", "") or ""))
        return ks

    have = set()
    for it in items:
        have |= lib_keys(it)

    added, skipped = 0, 0
    by_key = {}
    for cid, c in corpus.items():
        cat = c.get("cat", "")
        code = c.get("code", "") or code_from_file(c.get("src", ""))
        name = tidy_name(clean_name_from_file(c.get("src", ""), (c.get("name") or "").strip()))
        if not code:
            code = code_from_file(c.get("src", "")) or ""
        if len(re.findall(r"[\u4e00-\u9fa5]", name)) < 4:
            skipped += 1
            continue
        if re.search(r"(人民共和国国家标准|网络安全标准实践指南$|数据安全技术$|信息技术$)", name):
            name = tidy_name(os.path.splitext(os.path.basename(c.get("src", "")))[0])[:80]
        if is_excluded(name, c.get("src", "")):
            skipped += 1
            continue
        cat = override_cat(code, name, cat)
        if cat not in CAT_LEVEL:
            skipped += 1
            continue
        key = norm_key(code, name)
        if not key:
            skipped += 1
            continue
        if key in have or key in by_key:
            # 已存在：补充章节目录
            tgt = by_key.get(key)
            if tgt and not tgt.get("toc") and c.get("toc"):
                tgt["toc"] = c["toc"]
            continue
        level = CAT_LEVEL[cat]
        # 强制性国标判断
        if cat == "国家标准":
            cod = c.get("code", "")
            if re.match(r"^GB\s*\d", cod) or "强制性" in name:
                level = "强制性国家标准"
        topic = guess_topic(name)
        it = {
            "code": code,
            "name": name,
            "level": level,
            "topic": topic,
            "status": detect_status(c),
            "pub": c.get("pub", ""),
            "impl": c.get("impl", ""),
            "issuer": c.get("issuer", ""),
            "url": "",           # 语料条目无官方深链，站点上不显示外链
            "point": "",
            "duty": [],
            "note": "",
            "kind": "标准" if cat in ("国家标准", "行业标准", "团体标准") else "文件",
            "toc": c.get("toc", []),
            "local": True,       # 标记：本机有原文，仅本机可见
            "src": c.get("src", ""),
        }
        by_key[key] = it
        items.append(it)
        added += 1

    lib["items"] = items
    lib["updated"] = datetime.date.today().isoformat()
    if "meta" in lib and "topics" in lib["meta"]:
        for t in {x["topic"] for x in items}:
            if t not in lib["meta"]["topics"]:
                lib["meta"]["topics"].append(t)
        for lv in {x["level"] for x in items}:
            if "levels" in lib["meta"] and lv not in lib["meta"]["levels"]:
                lib["meta"]["levels"].append(lv)
    with open(LIB, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=1)
    print(f"语料合并：新增 {added} 条，跳过 {skipped} 条，库内总计 {len(items)} 条")
    n_local = sum(1 for x in items if x.get("local"))
    print(f"其中本机有原文（不上传正文）: {n_local} 条")

if __name__ == "__main__":
    main()
