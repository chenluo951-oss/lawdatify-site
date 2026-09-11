#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_texts.py —— 生成站内「法规原文」阅读库（只收法规，不收标准）。

为什么可以放上站：
  《著作权法》第五条——法律、法规，国家机关的决议、决定、命令和其他具有立法、
  行政、司法性质的文件及其官方正式译文，不适用著作权法。所以法规/规章/规范性文件的
  官方正文可以随站点公开发布与下载。
  而国家标准、行业标准、团体标准正文受著作权保护（openstd、hbba 官网均以版权为由不提供
  下载），因此**一律不发布正文**，只在条目上提供官方在线阅读深链。

成本控制（站点是免费版，带宽与空间都有限）：
  - 正文按 40 条/片切分，页面只在用户点开某一条时才 fetch 对应分片 → 单次阅读只消耗几百 KB；
  - 一次性体积约 17 MB（远低于 1 GB 站点上限），静态文本 gzip 后更小；
  - 不生成「每条一页」的 HTML，避免上千个页面拖慢构建。

产出：
  kb/texts/index.json      目录（id/编号/名称/层级/机关/日期/官方深链/字数/所属分片）
  kb/texts/p-NN.json       {id: 正文}
  sources/standards/text_ids.json   条目 → 原文 id 映射（供 build_standards 加「读原文」按钮）
"""
import os, re, json, sys, html, hashlib, collections, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H

LIB = H.LIB
OUT = os.path.join(HERE, "kb", "texts")
MAP = os.path.join(HERE, "sources", "standards", "text_ids.json")
PER_PART = 40
PART_CHARS = 1_200_000   # 单片字符上限：一次阅读只拉一片，兼顾体积与请求数
MIN_CHARS = 600

# 只收「法定效力层级」的公文；指引/指南（第三方或行业自律）、标准正文都不进本库
LAW_LEVELS = {"法律", "行政法规", "部门规章", "规范性文件"}
# 名称排除：第三方法律汇编、研究报告、境外文件、书稿、节选本 —— 不是某一份公文的正文
BAD_NAME = re.compile(
    r"汇编|指引|指南|报告|清单|判例|教材|ISO|IEC|HKEX|尽调|尽职调查|税收|白皮书|"
    r"解读|标准体系|操作规程|业务规程|工作要点|议事规则|手册|百科|问答|案例|课件|"
    r"培训|节选|新旧对比|简评|研读|笔记|试题|范本|模板|修正案")
ART_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")

# 「CJK 部首补充区」是 NFKC 管不到的一批部首形字符（简体部件），按语料实况逐一对应回汉字
RAD_FIX = str.maketrans({
    "\u2ea0": "民", "\u2ec5": "见", "\u2ec6": "角", "\u2ecb": "车", "\u2ed3": "长",
    "\u2ed4": "门", "\u2eda": "页", "\u2edb": "风", "\u2e9e": "确",
})
RAD_LEFT = re.compile(r"[\u2e80-\u2eff]")        # 归一后仍有 → 抽取损坏，不予发布

# 只对「康熙部首 U+2F00-2FDF」与「CJK 部首补充 U+2E80-2EFF」两段做 NFKC：
# 整篇 NFKC 会把中文全角标点（，。：；）折成半角，反而制造排版错误。
RAD_RE = re.compile(r"[\u2e80-\u2fdf]")
_nfkc1 = lambda m: unicodedata.normalize("NFKC", m.group(0))
RARE = re.compile("[\u3400-\u4dbf\U00020000-\U0003ffff\ue000-\uf8ff]")   # Ext-A/Ext-B/私用区


def quality_ok(t):
    """发布前的质量闸：乱码/编码损坏的抽取结果一律不上站。"""
    if RAD_LEFT.search(t):
        return False, "存在未归一的部首字符"
    n = len(t) or 1
    if len(RARE.findall(t)) / n > 0.002:
        return False, "含大量生僻/私用区字符，疑似编码损坏"
    return True, ""


# 「汇编」「法规目录」类文件：开头是目次，含「节选」「……」点引线或多条法规并列
IDX_HEAD = re.compile(r"目\s*录|目\s*次|\.{5,}|…{2,}|节选|汇编")
ART_IN_HEAD = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")
# 转载页/栏目页的抬头（「XX人大常委会欢迎您」这类），正文再长也不是权威原文
PORTAL_HEAD = re.compile(r"欢迎您|欢迎访问|当前位置[:：]|您现在的位置|网站首页|无障碍|"
                         r"主办[:：]|版权所有|回到顶部|政务公开|政务服务")


def looks_compilation(t):
    """正文头 800 字若像法规汇编目次（无第一条、却有节选/点引线），视为取错文件。"""
    head = t[:800]
    if ART_IN_HEAD.search(head):
        return False
    return bool(IDX_HEAD.search(head))


def looks_portal(t):
    """正文头 300 字混着栏目页/转载页的抬头 → 不是发布机关的原文页。"""
    return bool(PORTAL_HEAD.search(t[:300]))

# 层级纠偏：条目库里有把「规定/办法/方案/标准」标成「法律」的，阅读页上会显得刺眼
LV_FIX = re.compile(r"(条例|办法|规定|规则|细则|通知|意见|方案|公告|通告|决定|批复|"
                    r"标准|规范|指引|指南)$")


def fix_level(name, level):
    n = re.sub(r"[（(].*?[)）]", "", name or "").strip()
    if level == "法律" and LV_FIX.search(n):
        return "行政法规" if n.endswith("条例") else "规范性文件"
    return level


def dkey(name):
    """去重键：剥掉「中华人民共和国」与修订/节选等后缀，避免同一部法重复收录。"""
    n = re.sub(r"[（(].*?[)）]", "", name or "")
    n = n.replace("中华人民共和国", "").replace("中国", "")
    n = re.sub(r"(修订|修正案?|节选|试行|暂行|最新|全文|版本|稿)$", "", n)
    return re.sub(r"[\s、，,。.:：\-—–_]+", "", n)

STD_LEVELS = {"国家标准", "强制性国家标准", "推荐性国家标准", "行业标准", "团体标准",
              "国家标准化指导性技术文件"}

# 政府网页的版式残留（导航、按钮、版权条），逐行剔除
JUNK_LINE = re.compile(
    r"^(打印|关闭|关闭窗口|返回顶部|分享到?|分享|扫一扫在手机打开当前页|相关稿件|相关链接|"
    r"责任编辑[:：].*|来源[:：].*|【字体[:：].*|字体[:：].*|大\s*中\s*小|上一篇.*|下一篇.*|"
    r"网站地图|联系我们|关于我们|版权声明|京ICP备.*|政府网站标识码.*|"
    r"中华人民共和国中央人民政府|中国政府网|首页|网站首页|首\s*页|搜索|站内搜索|"
    r"时政要闻|网信政务|互动服务|热点专题|专题专栏|新闻中心|政务公开|政务服务|信息公开|"
    r"政策法规|法律法规|标准规范|政策解读|数据发布|互动交流|在线服务|办事服务|"
    r"中国人大网|中国政府网|国家法律法规数据库|"
    r"【打印】.*|【纠错】.*|【关闭】.*|\s*)$")

# 行内导航串（与正文挤在同一行的站点头尾），整段摘掉
NAV_BLOB = re.compile(
    r"(设为首页|加入收藏|收藏本站|手机版|繁体|无障碍|长者版|简\s*/\s*繁|"
    r"English|登录|注册|退出|邮箱|微博|微信|分享到|打印本页|关闭窗口|"
    r"网站地图|主办单位|承办单位|技术支持|版权所有|下载\s*pdf|下载文字版|下载PDF)")

# 网页模板里的成对元信息（发布时间、信息来源等），整段摘掉
META_INLINE = re.compile(r"(发布时间|发布日期|信息来源|来源|浏览次数|字体|字号|"
                         r"扫一扫在手机打开当前页|分享到)\s*[:：][^\s，。；]{0,32}")

# PDF 抽取的页眉页码：－3－ / -3- / 第 3 页 / 3/120
PAGENO = re.compile(r"^\s*(?:[－\-—–]\s*\d{1,3}\s*[－\-—–]|第\s*\d{1,3}\s*页|\d{1,3}\s*/\s*\d{1,3})\s*$")
# 自编目录/清单残留的行首序号：6. 《XX法》
LEAD_NO = re.compile(r"^\s*\d{1,2}\s*[\.、)）]\s*(?=[《\u4e00-\u9fa5A-Za-z])")


def clean(text):
    t = text or ""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", t)
    t = re.sub(r"(?s)<[^>]{1,200}>", "", t)
    t = html.unescape(t)
    # PDF 抽取常把汉字映射成「康熙部首」（如 ⽤/⼈/⼆/⾏），看着像汉字却检索不到、
    # 复制到别处也出错。只对部首区做兼容分解（全量 NFKC 会把中文全角标点折成半角，
    # 反而制造排版错误，故不能整篇套用）。
    t = RAD_RE.sub(_nfkc1, t)
    t = t.translate(RAD_FIX)
    t = t.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    t = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", t)
    # 网页模板残留：面包屑导航、转载页 URL、政府信息公开元数据键值对
    t = re.sub(r"(你的位置|当前位置|您现在的位置)\s*[:：][^\n]{0,140}", "\n", t)
    t = re.sub(r"https?://[^\s，。；、）)]+", "", t)
    t = re.sub(r"[^\n]{0,10}(?:首页|政务|专题|政府信息公开|信息公开|政策法规)"
               r"(?:\s*>\s*[^\n>]{1,16}){1,6}", "\n", t)
    t = re.sub(r"第\s*\d{1,3}\s*/\s*\d{1,3}\s*页", "", t)
    t = re.sub(r"(?<=\s)\d{1,2}:\d{2}(?=\s)", " ", t)     # 残留的发布时间
    t = re.sub(r"-{2,}>", "", t)                       # HTML 注释残留 -->
    t = META_INLINE.sub("", t)
    t = re.sub(r"【(发布单位|发布文号|发布日期|实施日期|发文机关|发文机构|信息名称|"
               r"信息索引|生成日期|主题分类|成文日期|有效性|废止日期)】[^\s【]{0,40}", "", t)
    out = []
    for ln in t.split("\n"):
        ln = re.sub(r"[ \t\u3000]+", " ", ln).strip()
        if not ln:
            out.append("")
            continue
        if JUNK_LINE.match(ln):
            continue
        if len(NAV_BLOB.findall(ln)) >= 2:      # 同一行堆了两处以上站点导航 → 整行是模板
            continue
        residue = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", "", NAV_BLOB.sub("", ln))
        if NAV_BLOB.search(ln) and len(residue) < 3:
            continue                            # 扣掉导航词后空空如也 → 整行是模板
        if re.match(r"^[-=—_·．.]{3,}$", ln):
            continue
        if PAGENO.match(ln):                    # PDF 抽出的页眉页码：－3－、第 3 页
            continue
        if re.match(r"^[\s\d第号发文\-—–〔〕\[\]（）()【】]+$", ln) and len(ln) <= 24:
            continue                            # 只由文号/序号组成的孤立行
        out.append(ln)
    t = "\n".join(out)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    t = LEAD_NO.sub("", t, count=1)             # 去掉自编目录留下的「6. 」这类行首序号
    t = _tight(reflow(t))
    return t.strip()


# 网页表格抽取常把「2021 年6 月10 日」这类日期拆出多余空格；中文行内不该有这种空档
SP_AFTER_CJK = re.compile(r"(?<=[\u4e00-\u9fa5])[ \t\u3000]+(?=[0-9])")
SP_BEFORE_CJK = re.compile(r"(?<=[0-9])[ \t\u3000]+(?=[\u4e00-\u9fa5])")


def _tight(t):
    t = SP_AFTER_CJK.sub("", t)
    t = SP_BEFORE_CJK.sub("", t)
    return t


# 条文/编号起始行：作为段落边界，避免把不同条款并成一段
NUM_HEAD = re.compile(r"^\s*(第[一二三四五六七八九十百零〇\d]+[条章节]"
                      r"|[（(][一二三四五六七八九十\d]+[）)]"
                      r"|\d+(?:\.\d+)*[\.、\s])")


def reflow(t):
    """把 PDF/网页抽取留下的软换行合并回自然段（中文正文按 ~25 字硬换行很常见）。"""
    blocks = []
    for blk in t.split("\n\n"):
        cur = []
        for ln in blk.split("\n"):
            if NUM_HEAD.match(ln) and cur:
                blocks.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
        if cur:
            blocks.append(cur)
    out = []
    for lines in blocks:
        lines = [x for x in lines if x.strip()]
        if not lines:
            continue
        avg = sum(len(x) for x in lines) / len(lines)
        if len(lines) >= 2 and avg >= 16:          # 散文式软换行 → 合并
            m = ""
            for x in lines:
                if m and re.search(r"[A-Za-z0-9]$", m) and re.match(r"^[A-Za-z0-9]", x):
                    m += " "
                m += x
            out.append(m)
        else:                                       # 目次/表格/短行 → 保留原样
            out.append("\n".join(lines))
    return "\n\n".join(out)


def nkey(s):
    return H.norm(s)


def collect_sources():
    """返回两份候选：语料库（含 name/code/cat）、本机标准库 txt（按文件名）。"""
    cand = []
    idx = H.load_json(H.IDX, {"items": {}})
    for v in idx["items"].values():
        fp = os.path.join(H.CORPUS, (v.get("id") or "") + ".txt")
        if not os.path.exists(fp):
            continue
        cand.append({"key_name": nkey(v.get("name")), "key_code": nkey(v.get("code")),
                     "name": v.get("name") or "", "code": v.get("code") or "",
                     "file": fp, "kind": "corpus"})
    for dp, _dn, fns in os.walk(H.STORE):
        for fn in fns:
            if not fn.lower().endswith(".txt"):
                continue
            p = os.path.join(dp, fn)
            cand.append({"key_name": nkey(os.path.splitext(fn)[0]), "key_code": "",
                         "name": os.path.splitext(fn)[0], "code": "",
                         "file": p, "kind": "store"})
    return cand


PREFIX = ("中华人民共和国", "中国")


def core(s):
    s = nkey(s)
    for p in PREFIX:
        s = s.replace(nkey(p), "")
    return s


def nmatch(a, b):
    """名称相似度：先去掉「中华人民共和国」前缀，再做包含比。防止把「汇编」当成本条文。"""
    a, b = core(a), core(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return 0.0


def match_list(item, cand, top=6):
    """按候选质量排序返回全部命中，供逐个试读（首个合格者胜出）。"""
    nm, cd = nkey(item.get("name")), nkey(item.get("code"))
    hits = []
    for c in cand:
        score = 0.0
        if nmatch(item.get("name"), c["name"]) >= 0.6:
            score = 0.6 + nmatch(item.get("name"), c["name"])
        if cd and c["key_code"] and cd == c["key_code"] and len(cd) >= 4:
            score = max(score, 1.5)
        if score < 0.6:
            continue
        try:
            sz = os.path.getsize(c["file"])
        except OSError:
            continue
        hits.append(((score, sz, 1 if c["kind"] == "corpus" else 0), c))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in hits[:top]]


def main():
    lib = H.load_json(LIB, {"items": []})
    items = [x for x in lib["items"] if not x.get("hidden")]
    laws = [x for x in items if x.get("level") in LAW_LEVELS
            and not BAD_NAME.search(x.get("name") or "")]
    cand = collect_sources()
    print("条目库 %d 条（法定层级候选 %d）；候选正文 %d 份" % (len(items), len(laws), len(cand)))

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            os.remove(os.path.join(OUT, f))

    kept, idmap, dropped = [], {}, []
    for it in laws:
        picked = None
        for c in match_list(it, cand):
            try:
                raw = open(c["file"], encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            t = clean(raw)
            if len(t) < MIN_CHARS:
                picked = ("篇幅不足 %d 字" % len(t))
                continue
            # 名称与正文自洽：正文前 600 字含条目名，或含「第X条」条款特征
            core = re.sub(r"[^\u4e00-\u9fa5]", "",
                          (it.get("name") or "").replace("中华人民共和国", ""))[:6]
            head = re.sub(r"[^\u4e00-\u9fa5]", "", t[:600])
            if not ((core and core in head) or ART_RE.search(t)):
                picked = "正文与该条目不匹配"
                continue
            qok, why = quality_ok(t)
            if not qok:
                picked = why
                continue
            if looks_compilation(t):
                picked = "取到的是法规汇编/目次页，非该法正文"
                continue
            if looks_portal(t):
                picked = "取到的是栏目页/转载页抬头"
                continue
            picked = c, t
            break
        if isinstance(picked, str):
            dropped.append((it.get("name"), picked))
            continue
        if not picked:
            dropped.append((it.get("name"), "无正文"))
            continue
        t = picked[1]
        key = nkey((it.get("code") or "") + it.get("name", ""))
        tid = hashlib.md5(key.encode()).hexdigest()[:10]
        rec = {"id": tid, "code": it.get("code") or "", "name": it.get("name") or "",
               "level": fix_level(it.get("name"), it.get("level") or ""),
               "issuer": it.get("issuer") or "",
               "pub": it.get("pub") or "", "impl": it.get("impl") or "",
               "status": it.get("status") or "", "url": it.get("url") or "",
               "chars": len(t), "_text": t, "_key": key}
        dk = dkey(it.get("name"))
        rec["_dk"] = dk
        old = next((r for r in kept if r.get("_dk") == dk), None)
        if old is None:
            kept.append(rec)
        else:
            # 同一部法重复收录：保留带官方深链、字段更全、正文更完整的一版
            score_new = (bool(rec["url"]), sum(bool(rec[k]) for k in ("issuer", "pub", "impl")), rec["chars"])
            score_old = (bool(old["url"]), sum(bool(old[k]) for k in ("issuer", "pub", "impl")), old["chars"])
            if score_new > score_old:
                kept[kept.index(old)] = rec
        idmap[key] = tid
    kept.sort(key=lambda x: (x["level"], x["name"]))
    # 按累计字数为片：单次阅读只拉一片，控制在 ~1.2M 字（gzip 后约 400 KB）
    part, acc = 1, 0
    for x in kept:
        if acc and acc + x["chars"] > PART_CHARS:
            part += 1
            acc = 0
        x["part"] = part
        acc += x["chars"]

    parts = collections.defaultdict(dict)
    for x in kept:
        parts[x["part"]][x["id"]] = x.pop("_text")
        x.pop("_key", None)
        x.pop("_dk", None)
    for p, d in parts.items():
        json.dump(d, open(os.path.join(OUT, "p-%02d.json" % p), "w", encoding="utf-8"),
                  ensure_ascii=False)

    index = [{k: v for k, v in x.items()} for x in kept]
    json.dump({"_meta": {"count": len(index), "parts": len(parts), "per_part": PER_PART,
                         "note": "法规/规章/规范性文件官方正文（不受著作权法保护）；"
                                 "标准正文不在此库，见条目页的官方在线阅读入口。",
                         "updated": __import__("datetime").date.today().isoformat()},
               "items": index},
              open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False)

    H.save_json(MAP, idmap)
    total = sum(x["chars"] for x in index)
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    write_page(len(index), total, len(parts))
    print("原文库：%d 条 / %d 字 / %d 片 / 磁盘 %.1f MB（gzip 后更小）"
          % (len(index), total, len(parts), size / 1024 / 1024))
    if dropped:
        print("未收录 %d 条，示例：%s"
              % (len(dropped), "；".join("%s(%s)" % (n[:18], r) for n, r in dropped[:5])))


PAGE_CSS = """
.rd{display:grid;grid-template-columns:320px 1fr;gap:28px;align-items:start}
@media(max-width:900px){.rd{grid-template-columns:1fr}}
.rd-side{position:sticky;top:76px;background:var(--surface,#fff);border:1px solid var(--line,#e6e8ec);
  border-radius:14px;padding:14px;max-height:calc(100vh - 110px);display:flex;flex-direction:column}
.rd-box{width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--line,#e6e8ec);
  border-radius:9px;font-size:14px;margin-bottom:10px;background:transparent;color:inherit}
.rd-tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.rd-tab{font-size:12.5px;padding:4px 10px;border-radius:999px;border:1px solid var(--line,#e6e8ec);
  cursor:pointer;color:var(--muted,#6b7280);background:transparent;white-space:nowrap}
.rd-tab.on{background:var(--ink,#111827);color:#fff;border-color:var(--ink,#111827)}
.rd-list{overflow:auto;flex:1;margin:0;padding:0;list-style:none}
.rd-list li{margin:0}
.rd-list button{display:block;width:100%;text-align:left;background:none;border:0;cursor:pointer;
  padding:8px 10px;border-radius:8px;font-size:13.5px;line-height:1.5;color:inherit;font-family:inherit}
.rd-list button:hover{background:rgba(127,127,127,.10)}
.rd-list button.on{background:rgba(127,127,127,.16);font-weight:600}
.rd-list .lv{font-size:11.5px;color:var(--muted,#6b7280);margin-left:6px}
.rd-main{min-height:420px}
.rd-doc{background:var(--surface,#fff);border:1px solid var(--line,#e6e8ec);border-radius:14px;padding:26px 30px}
.rd-h1{font-size:24px;line-height:1.4;margin:0 0 10px}
.rd-meta{font-size:13px;color:var(--muted,#6b7280);line-height:1.9;margin-bottom:14px}
.rd-meta a{color:inherit;text-decoration:underline}
.rd-act{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px;padding-bottom:16px;
  border-bottom:1px solid var(--line,#e6e8ec)}
.rd-btn{font-size:13px;padding:6px 14px;border-radius:8px;border:1px solid var(--line,#e6e8ec);
  background:transparent;color:inherit;cursor:pointer;font-family:inherit}
.rd-btn:hover{border-color:currentColor}
.rd-body{font-size:16px;line-height:2.0;letter-spacing:.2px}
.rd-body p{margin:0 0 14px;text-indent:2em}
.rd-body p.h{text-indent:0;font-weight:700}
.rd-empty{color:var(--muted,#6b7280);font-size:14px;padding:40px 6px;line-height:1.9}
.rd-note{font-size:13px;color:var(--muted,#6b7280);line-height:1.9;margin:0 0 20px}
.rd-splash{padding:52px 6px;color:var(--muted,#6b7280);font-size:14.5px;line-height:2}
"""

PAGE_JS = r"""
(function(){
  var IX=null, CUR=null, PARTS={}, LV='';
  var $=function(s){return document.querySelector(s)};
  var esc=function(s){return (s||'').replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})};
  function load(p){ if(PARTS[p]) return Promise.resolve(PARTS[p]);
    return fetch('texts/p-'+String(p).padStart(2,'0')+'.json').then(function(r){return r.json()})
      .then(function(d){PARTS[p]=d;return d}); }
  function renderList(){
    var q=($('#rd-q')||{}).value||''; q=q.trim();
    var ul=$('#rd-list'); ul.innerHTML='';
    var arr=IX.items.filter(function(x){
      if(LV && x.level!==LV) return false;
      if(q && x.name.indexOf(q)<0 && (x.code||'').indexOf(q)<0) return false;
      return true; });
    $('#rd-count').textContent=arr.length+' 条';
    arr.forEach(function(x){
      var li=document.createElement('li');
      var b=document.createElement('button');
      b.innerHTML=esc(x.name)+'<span class="lv">'+esc(x.level)+'</span>';
      b.onclick=function(){ location.hash=x.id; };
      if(CUR && CUR.id===x.id) b.className='on';
      li.appendChild(b); ul.appendChild(li);
    });
  }
  function meta(x){
    var m=[]; if(x.code) m.push(esc(x.code)); m.push(esc(x.level));
    if(x.issuer) m.push(esc(x.issuer));
    if(x.pub) m.push('发布 '+esc(x.pub));
    if(x.impl) m.push('实施 '+esc(x.impl));
    if(x.status) m.push(esc(x.status));
    m.push(x.chars+' 字');
    if(x.url) m.push('<a href="'+esc(x.url)+'" target="_blank" rel="noopener">官方原文 &#8599;</a>');
    return m.join(' · ');
  }
  function paragraphs(t){
    return t.split(/\n{2,}/).map(function(p){
      p=p.replace(/^\n+|\n+$/g,'');
      if(!p) return '';
      var flat=p.replace(/\n/g,'');
      var cls='';
      if(/^第[一二三四五六七八九十百零〇\d]+[条章节]/.test(flat)) cls=' class="h"';
      return '<p'+cls+'>'+esc(flat)+'</p>';
    }).join('');
  }
  function open(id){
    var x=IX.items.filter(function(y){return y.id===id})[0];
    if(!x){ $('#rd-main').innerHTML='<div class="rd-splash">请从左侧目录选择要阅读的法规。</div>'; CUR=null; renderList(); return; }
    CUR=x; renderList();
    $('#rd-main').innerHTML='<div class="rd-doc"><div class="rd-empty">正在载入原文…</div></div>';
    load(x.part).then(function(d){
      var t=d[x.id]||'';
      $('#rd-main').innerHTML='<div class="rd-doc">'+
        '<h1 class="rd-h1">'+esc(x.name)+'</h1>'+
        '<div class="rd-meta">'+meta(x)+'</div>'+
        '<div class="rd-act">'+
          '<button class="rd-btn" id="rd-copy">复制全文</button>'+
          '<button class="rd-btn" id="rd-dl">下载 TXT</button>'+
          '<button class="rd-btn" id="rd-pr">打印 / 存为 PDF</button>'+
        '</div><div class="rd-body">'+paragraphs(t)+'</div></div>';
      document.title=x.name+' · 法规原文 · 合规无终点';
      $('#rd-copy').onclick=function(){ navigator.clipboard.writeText(t).then(function(){
        $('#rd-copy').textContent='已复制'; setTimeout(function(){$('#rd-copy').textContent='复制全文'},1600);}); };
      $('#rd-dl').onclick=function(){
        var a=document.createElement('a');
        a.href=URL.createObjectURL(new Blob([x.name+'\n\n'+t],{type:'text/plain;charset=utf-8'}));
        a.download=x.name+'.txt'; document.body.appendChild(a); a.click();
        setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},800); };
      $('#rd-pr').onclick=function(){ window.print(); };
      window.scrollTo({top:0,behavior:'smooth'});
    });
  }
  fetch('texts/index.json').then(function(r){return r.json()}).then(function(d){
    IX=d;
    var lvs={}; IX.items.forEach(function(x){lvs[x.level]=(lvs[x.level]||0)+1});
    var tabs=[['','全部 '+IX.items.length]];
    ['法律','行政法规','部门规章','规范性文件'].forEach(function(k){ if(lvs[k]) tabs.push([k,k+' '+lvs[k]]); });
    var tb=$('#rd-tabs');
    tabs.forEach(function(t){
      var b=document.createElement('button'); b.className='rd-tab'+(t[0]===''?' on':'');
      b.textContent=t[1];
      b.onclick=function(){ LV=t[0]; [].forEach.call(tb.children,function(c){c.className='rd-tab'});
        b.className='rd-tab on'; renderList(); };
      tb.appendChild(b);
    });
    $('#rd-q').addEventListener('input',renderList);
    renderList();
    window.addEventListener('hashchange',function(){ open(location.hash.slice(1)); });
    var q0=(location.hash||'').slice(1) || new URLSearchParams(location.search).get('id') || '';
    if(q0) open(q0);
  });
})();
"""


def write_page(count, total_chars, parts):
    tpl = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>法规原文 · 合规无终点</title>
<meta name="description" content="法律、行政法规、部门规章与规范性文件的官方正文，覆盖数据合规、个人信息保护、算法与人工智能、平台与移动应用等方向；标准正文受著作权保护，见条目页的官方在线阅读入口。">
<link rel="stylesheet" href="../assets/style.css">
<style>__CSS__</style>
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 法规原文</div>
  <h1>法规原文</h1>
  <p>收录 __COUNT__ 部法律、行政法规、部门规章与规范性文件的官方正文，可在站内直接阅读、复制与下载。<br>
     国家标准、行业标准与团体标准的正文受著作权保护，本站不转载，改由条目页提供发布机构的官方在线阅读入口。</p>
</div></div>

<main class="wrap">
  <p class="rd-note">数据来源均为发布机关官网公开文本（全国人大、国务院、国家市场监督管理总局、国家互联网信息办公室等）。阅读时以官方原文为准。</p>
  <div class="rd">
    <aside class="rd-side">
      <input id="rd-q" class="rd-box" type="search" placeholder="按名称或文号检索">
      <div class="rd-tabs" id="rd-tabs"></div>
      <div style="font-size:12.5px;opacity:.72;margin:2px 0 8px" id="rd-count"></div>
      <ul class="rd-list" id="rd-list"></ul>
    </aside>
    <section class="rd-main" id="rd-main">
      <div class="rd-splash">
        左侧目录共 __COUNT__ 部法规，合计约 __WAN__ 万字。<br>
        点选任意一条即可在此阅读全文，并支持复制、下载 TXT 与打印／另存为 PDF。
      </div>
    </section>
  </div>
</main>

<footer></footer>
<script>__JS__</script>
</body>
</html>
"""
    html = (tpl.replace("__CSS__", PAGE_CSS.strip())
            .replace("__JS__", PAGE_JS.strip())
            .replace("__COUNT__", str(count))
            .replace("__WAN__", "%.0f" % (total_chars / 10000.0)))
    open(os.path.join(HERE, "kb", "texts.html"), "w", encoding="utf-8").write(html)
    print("阅读页：kb/texts.html")


if __name__ == "__main__":
    main()
