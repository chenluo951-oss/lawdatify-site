#!/usr/bin/env python3
"""
为 sources/standards/duties.json 的每条义务，从本地原文语料库定位「条款号 + 条款原文」。

设计原则：
- 原文只能来自本机语料库（sources/library/corpus/），**绝不生成、绝不臆造**。
- 匹配不到条款的义务，只保留出处名称，articles 留空（页面显示「未定位到条款原文」）。
- 输出为 duties.json 的 articles 字段，供 build_standards.py 渲染。

用法：
  python3 enrich_duties.py              # 抽取并写回 duties.json
  python3 enrich_duties.py --dry        # 只输出抽取报告，不写回
  python3 enrich_duties.py --report     # 输出每条义务的匹配情况（人工复核用）
"""
import os, re, sys, json, hashlib, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
DUTIES = os.path.join(HERE, "sources", "standards", "duties.json")
ARTS_MAP = os.path.join(HERE, "sources", "standards", "arts_map.json")

# ---------------- 语料库 ----------------

def norm(s):
    return re.sub(r"[\s\-—–/／\(\)（）《》【】\[\]:：.、,，]+", "", s or "").upper()


def load_corpus():
    idx = json.load(open(IDX, encoding="utf-8"))["items"]
    return list(idx.values())


def doc_text(doc):
    p = os.path.join(CORPUS, doc["id"] + ".txt")
    if not os.path.exists(p):
        return ""
    return open(p, encoding="utf-8", errors="ignore").read()


class Resolver:
    """把 duties.json 里的 refs 名称解析到语料库文档。"""

    # refs 里写的简称 -> 语料库里的实际名称/编号（人工确认过的映射）
    ALIAS = {
        # 由 fetch_standards.py 抓取入库的官方正文
        "广告法": ["中华人民共和国广告法"],
        "互联网广告管理办法": ["互联网广告管理办法"],
        "明码标价和禁止价格欺诈规定": ["明码标价和禁止价格欺诈规定"],
        "生成式人工智能服务管理暂行办法": ["生成式人工智能服务管理暂行办法"],
        "人工智能生成合成内容标识办法": ["人工智能生成合成内容标识办法"],
        # 语料库中名称不含编号的国家标准
        "GB/T 35273": ["GBT35273-2020", "信息安全技术 个人信息安全规范", "数据安全技术 个人信息安全规范"],
        "GB/T 39335": ["个人信息安全影响评估指南"],
        "GB/T 37988": ["数据安全能力成熟度模型"],
        "GB/T 38667": ["数据分类指南"],
        "GB/T 43697": ["数据分类分级规则"],
        "GB/T 41391": ["收集个人信息基本要求"],
        "GB 7718": ["预包装食品标签通则"],
        "GB/T 22239": ["中 华 人 民 共 和 国 国 家 标 准", "网络安全等级保护基本要求"],
        "GB/T 41391": ["GBT41391-2022", "移动互联网应用程序（App）收集个人信息基本要求"],
        "GB/T 39335": ["GBT39335-2020", "个人信息安全影响评估指南"],
        "GB/T 43697": ["GBT43697-2024", "数据安全技术 数据分类分级规则"],
        "GB/T 38667": ["GBT38667-2020", "大数据 数据分类指南"],
        "GB/T 37988": ["GBT37988-2019", "数据安全能力成熟度模型"],
        "GB/T 22239": ["GBT22239-2019", "网络安全等级保护基本要求"],
        "GB 45438": ["GB45438-2025", "人工智能生成合成内容标识"],
        "GB 7718": ["GB7718", "预包装食品标签通则"],
        "GB 31654": ["GB31654", "餐饮服务通用卫生规范"],
        "个人信息保护法": ["个人信息保护法"],
        "数据安全法": ["数据安全法"],
        "网络安全法": ["网络安全法"],
        "民法典": ["民法典"],
        "消费者权益保护法": ["消费者权益保护法"],
        "电子商务法": ["电子商务法"],
        "未成年人网络保护条例": ["未成年人网络保护条例"],
        "网络数据安全管理条例": ["网络数据安全管理条例"],
        "互联网信息服务算法推荐管理规定": ["互联网信息服务算法推荐管理规定"],
        "移动互联网应用程序个人信息保护管理暂行规定": ["移动互联网应用程序个人信息保护管理暂行规定"],
        "个人信息保护合规审计管理办法": ["个人信息保护合规审计管理办法"],
        "数据出境安全评估办法": ["数据出境安全评估办法"],
        "网络交易监督管理办法": ["网络交易监督管理办法"],
        "网络信息内容生态治理规定": ["网络信息内容生态治理规定"],
        "网络产品安全漏洞管理规定": ["网络产品安全漏洞管理规定"],
        "数据安全技术 个人信息保护合规审计要求": ["数据安全技术 个人信息保护合规审计要求"],
        "数据安全技术 数据提供、委托处理、共同处理实施指南": ["数据提供、委托处理、共同处理实施指南"],
        "网络安全标准实践指南": ["网络安全标准实践指南"],
        "信息安全技术 敏感个人信息处理安全要求": ["敏感个人信息处理安全要求"],
        "信息安全技术 网络安全等级保护基本要求": ["网络安全等级保护基本要求"],
        "网络安全技术 人工智能应用安全分类分级方法": ["人工智能应用安全分类分级方法"],
        "网络安全技术 生成式人工智能数据标注安全规范": ["生成式人工智能数据标注安全规范"],
        "食品安全国家标准 餐饮服务通用卫生规范": ["餐饮服务通用卫生规范"],
        "国家网络安全事件应急预案": ["国家网络安全事件应急预案"],

        "GB/T 35273-2020": ["信息安全技术 个人信息安全规范"],
        "GB/T 39335-2020": ["个人信息安全影响评估指南"],
        "GB/T 37988-2019": ["数据安全能力成熟度模型"],
        "GB/T 22239-2019": ["网络安全等级保护基本要求"],
        "GB/T 43697-2024": ["数据分类分级规则"],
        "GB/T 38667-2020": ["数据分类指南"],
        "GB 45438-2025": ["人工智能生成合成内容标识"],
        "最高人民法院关于审理使用人脸识别技术处理个人信息相关民事案件适用法律若干问题的规定": ["人脸识别技术处理个人信息"],
        "食品安全法": ["中华人民共和国食品安全法"],
        "食品安全法实施条例": ["食品安全法实施条例"],
        "价格法": ["中华人民共和国价格法"],
        "反垄断法": ["反垄断法"],
        "产品质量法": ["产品质量法"],
        "反不正当竞争法": ["反不正当竞争法"],
        "网络食品安全违法行为查处办法": ["网络食品安全违法行为查处办法"],
        "网络餐饮服务食品安全监督管理办法": ["网络餐饮服务食品安全监督管理办法"],
        "个人信息出境标准合同办法": ["个人信息出境标准合同办法"],
        "消费者权益保护法实施条例": ["消费者权益保护法实施条例"],
        "GB 31654-2021": ["GB31654-2021", "餐饮服务通用卫生规范"],
        "GB/T 45574-2025": ["敏感个人信息处理安全要求", "GB/T45574-2025"],
        "GB/T 46903-2025": ["个人信息保护合规审计要求", "GB/T46903-2025"],
        "GB/T 45674-2025": ["生成式人工智能数据标注安全规范", "GB/T45674-2025"],
        "移动互联网应用程序信息服务管理规定": ["移动互联网应用程序信息服务管理规定"],
    }

    def __init__(self, docs):
        self.docs = docs
        self._cache = {}
        for d in docs:
            self._cache.setdefault(norm(d.get("code")), []).append(d)
            self._cache.setdefault(norm(d.get("name")), []).append(d)

    def resolve(self, ref):
        keys = self.ALIAS.get(ref)
        if keys:
            for k in keys:
                got = self._cache.get(norm(k)) or []
                if got:
                    return max(got, key=lambda d: d["chars"])
        n = norm(ref)
        got = self._cache.get(n)
        if got:
            return max(got, key=lambda d: d["chars"])
        # 子串回退（长名称优先，避免误命中）
        if len(n) >= 6:
            cands = [d for d in self.docs if n in norm(d.get("name")) or n in norm(d.get("code"))]
            if cands:
                return max(cands, key=lambda d: d["chars"])
        return None


# ---------------- 条款切分 ----------------

RE_LAW_ART = re.compile(r"(?:^|\n)\s*(第[〇一二三四五六七八九十百零\d]{1,6}条)")
RE_STD_NUM = re.compile(r"(?:^|\n)\s*(\d{1,2}(?:\.\d{1,2}){0,3})[\s　]+[^\n]{2,40}")
# 标准/团体标准章节标题行：整行「序号 + 标题」，如「8  欺骗误导强迫点击跳转」
RE_STD_CHAP = re.compile(
    r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,2}){0,2})[ \t　]{1,4}(\S[^\n]{1,38})[ \t　]*$")

STOP = re.compile(r"^(目次|前言|引言|参考文献|附录|索引|ICS|CCS)")


def split_clauses(text):
    """把原文切成 (条款号, 正文) 列表。法律按「第X条」，标准按「x.y 标题」。"""
    art_marks = [(m.start(), m.group(1)) for m in RE_LAW_ART.finditer(text)]
    if len(art_marks) >= 5:
        kind = "law"
        marks = art_marks
    else:
        kind = "std"
        marks = []
        seen = {}
        for m in RE_STD_CHAP.finditer(text):
            num = m.group(1)
            title = m.group(2).strip()
            if re.match(r"^\d{4}[-.]\d{1,2}", num):      # 跳过日期
                continue
            if re.search(r"\.{3,}|…", title):            # 跳过目次行
                continue
            if not title or len(title) < 2:
                continue
            if re.match(r"^[\d\.\s]*$", title):          # 纯数字/点 → 页码
                continue
            no = num + " " + title
            # 正文中的章节保留最后一次出现（目次在前、正文在后）
            seen[no] = (m.start(), no)
        marks = sorted(seen.values(), key=lambda x: x[0])
    if len(marks) < 3:
        return []
    out = []
    for i, (pos, no) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end].strip()
        body = re.sub(r"^\s*" + re.escape(no) + r"\s*", "", body)
        body = re.sub(r"\n+", " ", body).strip()
        if 0 < len(body) <= 1200 and not STOP.match(body[:4]):
            out.append((no.strip(), body))
    return out


# ---------------- 关键词打分 ----------------

STOPW = set("的 了 和 与 或 在 是 有 对 为 以 及 等 不 应 当 须 需 其 之 中 个 者 被 将 由 于 并 且 但 若 如 该 本 上 下 内 外 后 前 时 可 能 要 会 进行 不得 应当 应当 按照 相关 其他 情况 说明 规定 要求 管理 处理 使用 服务 用户 信息 平台 提供 机构 部门 国家 有关 法律 法规".split())


def terms(s):
    ws = re.findall(r"[\u4e00-\u9fa5]{2,6}|[A-Z]{2,6}", s or "")
    return [w for w in ws if w not in STOPW]


def grams(s, k=4):
    """取文本的四字滑窗集合——法条与义务描述常共享固定搭配（如「一键关闭」）。"""
    s = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", s or "")
    return {s[i:i + k] for i in range(max(0, len(s) - k + 1))}


# 总则性/程序性条款不作为义务依据：立法目的、适用范围、术语定义、附则等
JUNK_NO = re.compile(r"^(第[一二三四五六七八]条|第[1-8]条|1|1\.0|2|3|4)$")
JUNK_TITLE = ("范围", "规范性引用文件", "术语和定义", "缩略语", "概述", "原则",
              "总则", "附则", "目次", "前言", "引言", "参考文献")


def JUNK_CLAUSE(no, body):
    n = (no or "").strip()
    if JUNK_NO.match(n):
        return True
    for t in JUNK_TITLE:
        if n.endswith(t) and len(n) <= len(t) + 8:
            return True
    b = (body or "").strip()
    if len(b) < 40:
        return True
    if b.startswith(("为了", "为规范", "本办法所称", "本法所称", "根据")) and len(b) < 220:
        return True
    # 定义/解释性条款（"所称……是指"）不承载具体义务
    if b.count("所称") >= 2 or b.count("是指") >= 2:
        return True
    # 施行日期 / 废止条款
    if re.search(r"(本法|本条例|本办法|本规定|本标准)自.{0,24}(施行|实施)", b) and len(b) < 260:
        return True
    return False


def score_clause(duty, clause_body):
    """锚点重合度打分：义务描述里有多少四字搭配在条款正文中原样出现。"""
    duty_txt = (duty.get("t", "") + "。" + duty.get("d", ""))[:260]
    g = grams(duty_txt, 4)
    if not g:
        return 0
    cb = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", clause_body)
    hit = sum(1 for x in g if x in cb)
    if not hit:
        return 0
    # 覆盖率 = 命中数 / 义务描述长度开方，避免长描述天然占优
    return round(hit / (len(g) ** 0.62), 3)


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--top", type=int, default=1)
    ap.add_argument("--min", type=float, default=0.5)
    a = ap.parse_args()

    docs = load_corpus()
    res = Resolver(docs)
    duties = json.load(open(DUTIES, encoding="utf-8"))
    amap = {}
    if os.path.exists(ARTS_MAP):
        amap = json.load(open(ARTS_MAP, encoding="utf-8")).get("map", {})

    doc_cache = {}
    stats = {"duty": 0, "hit": 0, "refmiss": 0, "noclause": 0, "by_map": 0, "by_auto": 0}
    ref_miss = {}
    report = []

    for cat in duties["categories"]:
        for sc in cat["scenes"]:
            for du in sc["duties"]:
                stats["duty"] += 1
                arts = []
                # ① 人工校验的条款号优先：只指定条款号，原文逐字取自语料库
                for ref, art_no in amap.get(f'{cat["id"]}|{sc["name"]}|{du.get("t")}', []):
                    doc = res.resolve(ref)
                    if not doc:
                        continue
                    if doc["id"] not in doc_cache:
                        doc_cache[doc["id"]] = split_clauses(doc_text(doc)) or None
                    clauses = doc_cache[doc["id"]] or []
                    body = next((b for no, b in clauses if no.strip() == art_no.strip()), None)
                    if body:
                        arts.append({"src": ref, "doc": doc.get("name") or "",
                                     "art": art_no, "quote": body[:420],
                                     "score": "manual"})
                        stats["by_map"] += 1
                    else:
                        arts.append({"src": ref, "doc": doc.get("name") or "",
                                     "art": art_no, "quote": "", "score": "missing"})
                # ② 未指定条款号的，用锚点自动匹配兜底
                if not arts:
                    for ref in du.get("refs", []):
                        doc = res.resolve(ref)
                        if not doc:
                            stats["refmiss"] += 1
                            ref_miss[ref] = ref_miss.get(ref, 0) + 1
                            continue
                        if doc["id"] not in doc_cache:
                            doc_cache[doc["id"]] = split_clauses(doc_text(doc)) or None
                        clauses = doc_cache[doc["id"]]
                        if not clauses:
                            stats["noclause"] += 1
                            continue
                        ranked = sorted(
                            ((score_clause(du, body), no, body)
                             for no, body in clauses if not JUNK_CLAUSE(no, body)),
                            key=lambda x: -x[0])
                        best = [r for r in ranked[:a.top] if r[0] > a.min]
                        if not best:
                            continue
                        for sc_, no, body in best:
                            arts.append({"src": ref, "doc": doc.get("name") or "",
                                         "art": no, "quote": body[:420],
                                         "score": round(sc_, 3)})
                            stats["by_auto"] += 1
                if any(x.get("quote") for x in arts):
                    stats["hit"] += 1
                du["articles"] = arts
                report.append((cat["name"], sc["name"], du.get("t"), len(arts),
                               [f'{x["art"]}' for x in arts]))

    if a.report or a.dry:
        for r in report:
            flag = "OK " if r[3] else "-- "
            print(f'{flag}{r[0][:6]}/{r[1][:14]:16s} {r[2][:34]:36s} {r[4]}')
    print(f'\n义务 {stats["duty"]} 条 | 命中条款 {stats["hit"]} 条 '
          f'({stats["hit"]*100//max(1,stats["duty"])}%) | 出处未入库 {stats["refmiss"]} | 无条款结构 {stats["noclause"]}')
    if ref_miss:
        print("未入库的出处（按引用次数）：")
        for k, v in sorted(ref_miss.items(), key=lambda x: -x[1]):
            print(f"   {v:3d}  {k}")

    if not a.dry:
        duties.setdefault("_meta", {})["articles_built"] = __import__("datetime").date.today().isoformat()
        json.dump(duties, open(DUTIES, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("已写回", DUTIES)


if __name__ == "__main__":
    main()
