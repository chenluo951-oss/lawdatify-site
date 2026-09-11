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
import os, re, json, sys, html, hashlib, collections, unicodedata, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H
import edits as E

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
RARE = re.compile("[\u3400-\u4dbf\U00020000-\U0003ffff]")   # Ext-A/Ext-B 生僻字

# PDF 里用「符号字体」（Symbol / Wingdings / Webdings）排的字符，抽取时整体落进私用区，
# 上站后一律显示成方框。这些字形有确定的排版含义，按语义回填，不能当成「编码损坏」丢掉：
#   ± × ≥ ∑ ⊕ Δ ∈ ± 是 Symbol 表里的确定映射；√ / □ / ● 是表格勾选与项目符号。
FONT_SYM = str.maketrans({
    "\uf02b": "+", "\uf02d": "−", "\uf03d": "=", "\uf044": "Δ", "\uf0ce": "∈",
    "\uf0b1": "±", "\uf0b3": "≥", "\uf0b4": "×", "\uf0c4": "⊗", "\uf0c5": "⊕",
    "\uf0e5": "∑", "\uf0e0": "→", "\uf028": "(", "\uf029": ")",
    "\uf050": "√", "\uf0fc": "√", "\uf0a8": "□", "\uf09f": "□", "\uf0a3": "□",
    "\uf0b7": "●", "\uf06c": "●", "\uf06e": "●", "\uf06d": "■",
})
PUA_LEFT = re.compile("[\ue000-\uf8ff]")     # 无语义可判的私用区字形 → 清掉，不留方框

# 「汉字整体平移」型编码损坏的判据：汉字很多但常用字一个都命中不到（如「犐犆犛」=ICS）
COMMON = ("的一是在不了有人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动"
          "同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高")
CJK_RE = re.compile("[\u4e00-\u9fff]")


def quality_ok(t):
    """发布前的质量闸：乱码/编码损坏的抽取结果一律不上站。"""
    if RAD_LEFT.search(t):
        return False, "存在未归一的部首字符"
    n = len(t) or 1
    if len(RARE.findall(t)) / n > 0.002:
        return False, "含大量生僻字，疑似编码损坏"
    cjk = len(CJK_RE.findall(t))
    if cjk >= 80 and sum(t.count(c) for c in COMMON) / cjk < 0.06:
        return False, "汉字常用字命中率过低，疑似字体编码整体错位"
    return True, ""


# 「汇编」「法规目录」类文件：开头是目次，含「节选」「……」点引线或多条法规并列
IDX_HEAD = re.compile(r"目\s*录|目\s*次|\.{5,}|…{2,}|节选|汇编")
ART_IN_HEAD = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")
# 转载页/栏目页的抬头（「XX人大常委会欢迎您」这类），正文再长也不是权威原文
PORTAL_HEAD = re.compile(r"欢迎您|欢迎访问|当前位置[:：]|您现在的位置|网站首页|无障碍|"
                         r"主办[:：]|版权所有|回到顶部|政务公开|政务服务|门户网站|中国人大网")


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

# 政府门户 / 人大网转载页的站点名与信息公开元数据（「XX法_中国人大网」「[发文机构] …」）
SITE_NAME = re.compile(r"门户网站|中国人大网|中国政府网|首都之窗|人民政府网站|政务网")
META_BRACKET = re.compile(r"^\s*\[(?:发文字号|发文机构|发布日期|实施日期|生效日期|有效性|"
                          r"废止日期|成文日期|主题分类|信息索引|信息名称)\][^\n]*$")
BREADCRUMB = re.compile(r"^\s*[^\n]{0,24}(?:\s*>\s*[^\n>]{1,20}){2,}\s*$")
EDITOR_LINE = re.compile(r"^\s*(?:编\s*辑|责\s*编|来\s*源|责任编辑)\s*[:：][^\n]*$|^相关文章\s*$")

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
    t = t.translate(FONT_SYM)                # 符号字体的私用区字形 → 对应符号
    t = PUA_LEFT.sub("", t)                  # 余下无法判义的私用区字形清掉
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
        if SITE_NAME.search(ln) and len(ln) < 120:
            continue                            # 门户/人大网转载页的站点名抬头
        if META_BRACKET.match(ln) or BREADCRUMB.match(ln) or EDITOR_LINE.match(ln):
            continue                            # 信息公开元数据、面包屑、编者署名
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


# 阅读页内联脚本允许出现的「宿主/内置全局」，其余小写函数调用必须在脚本里定义
JS_BUILTINS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "function", "new",
    "delete", "in", "of", "do", "else", "case", "break", "continue", "throw", "try",
    "var", "let", "const", "yield", "await", "async", "instanceof", "void", "with",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent",
    "decodeURIComponent", "escape", "unescape", "setTimeout", "setInterval",
    "clearInterval", "clearTimeout", "requestAnimationFrame", "fetch", "alert",
    "confirm", "prompt", "print", "atob", "btoa", "queueMicrotask",
    "rgba", "calc", "translateY", "rotate", "url", "min", "max", "clamp", "var_",
    "matchMedia", "customElements", "getComputedStyle", "structuredClone",
    "Attr", "CharacterData", "Document", "Element", "Event", "Node", "Text",
    "call", "apply", "bind", "then", "catch_", "not", "and", "or", "isinstance",
}


def lint_page(html):
    """阅读页上线前的静态自检：语法 + 调用未定义的内部函数。

    这条闸针对的是一次真实事故：改版式时误删了 halo()/gongwen() 的定义，
    语法检查（node --check）照样通过，页面上线后整页渲染抛 ReferenceError，
    只剩「正在载入原文…」。只有把「调用名 vs 定义名」对一遍才拦得住。
    """
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    if not m:
        raise SystemExit("阅读页缺少内联脚本")
    js = m.group(1)
    defined = set(re.findall(r"function\s+(\w+)\s*\(", js))
    defined |= set(re.findall(r"(?:var|let|const)\s+(\w+)\s*=", js))
    # 排除 \u2019 这类转义序列（反斜杠后紧跟的名字不是函数调用）
    called = set(re.findall(r"(?<![\w.$\\])([a-z][A-Za-z0-9_]{1,})\s*\(", js))
    missing = sorted(c for c in called if c not in defined and c not in JS_BUILTINS)
    if missing:
        raise SystemExit("阅读页脚本调用了未定义的函数：%s" % "、".join(missing))
    node = os.path.expanduser("~/.workbuddy/binaries/node/versions/22.22.2-2/bin/node")
    node = node if os.path.exists(node) else "node"
    tmp = os.path.join(HERE, "sources", ".cache", "_rd_check.js")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    open(tmp, "w", encoding="utf-8").write(js)
    try:
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise SystemExit("阅读页脚本语法错误：\n" + (r.stderr or "")[:800])
    except FileNotFoundError:
        pass
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    print("脚本自检：%d 个函数定义 / 无未定义调用 / 语法通过" % len(defined))


def main():
    lib = H.load_json(LIB, {"items": []})
    items = [x for x in lib["items"] if not x.get("hidden")]
    laws = [x for x in items if x.get("level") in LAW_LEVELS
            and not BAD_NAME.search(x.get("name") or "")]
    cand = collect_sources()
    print("条目库 %d 条（法定层级候选 %d）；候选正文 %d 份" % (len(items), len(laws), len(cand)))

    os.makedirs(OUT, exist_ok=True)
    # 只清自己的产物：法规分片 p-NN.json + 索引；标准分片 s-NN.json 由 build_std_texts 负责
    for f in os.listdir(OUT):
        if f == "index.json" or re.fullmatch(r"p-\d+\.json", f):
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
        # 人工修改覆盖层：按法规名套用「查找 → 替换」规则（编辑器写入）
        t = E.apply_rules("law", it.get("name") or "", t)
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

    for x in kept:
        x["kind"] = "law"

    # 标准正文（本人存档：国标 OCR 定稿 / 行标与团标官方公开 PDF 文字层）
    std_items, std_parts = [], 0
    try:
        import build_std_texts as BS
        std_items, std_parts = BS.build(quiet=True)
    except Exception as e:                                    # 不阻断法规原文库
        print("标准原文库跳过：%s" % e)

    index = [{k: v for k, v in x.items()} for x in kept] + std_items
    json.dump({"_meta": {"count": len(index), "laws": len(kept), "stds": len(std_items),
                         "parts": len(parts), "std_parts": std_parts,
                         "note": "法规/规章/规范性文件官方正文，以及本人存档的标准正文"
                                 "（国标 OCR 定稿 / 官方公开 PDF 文字层），仅供本机学习研究。",
                         "updated": __import__("datetime").date.today().isoformat()},
               "items": index},
              open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False)

    H.save_json(MAP, idmap)
    total = sum(x["chars"] for x in index)
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    write_page(len(kept), total, len(parts), len(std_items))
    print("原文库：法规 %d 条 + 标准 %d 条 / 合计 %d 字 / 磁盘 %.1f MB（gzip 后更小）"
          % (len(kept), len(std_items), total, size / 1024 / 1024))
    if dropped:
        print("未收录 %d 条，示例：%s"
              % (len(dropped), "；".join("%s(%s)" % (n[:18], r) for n, r in dropped[:5])))


PAGE_CSS = """
/* ================= 原文阅读器：公文版式 + 标准版式 ================= */
.rd{display:grid;grid-template-columns:332px 1fr;gap:26px;align-items:start}
@media(max-width:960px){.rd{grid-template-columns:1fr}}
.rd-side{position:sticky;top:76px;background:#fff;border:1px solid var(--line);
  border-radius:14px;padding:14px;max-height:calc(100vh - 108px);display:flex;flex-direction:column}
.rd-box{width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--line);
  border-radius:9px;font-size:14px;margin-bottom:10px;background:#fff;color:var(--ink);font-family:var(--sans)}
.rd-tabs{display:flex;gap:6px;margin-bottom:9px}
.rd-tab{flex:1;font-size:13px;padding:7px 0;border-radius:9px;border:1px solid var(--line);
  background:#fff;color:var(--ink-2);cursor:pointer;font-family:var(--sans);font-weight:600}
.rd-tab.on{background:var(--brand);border-color:var(--brand);color:#fff}
.rd-chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.rd-chip{font-size:12px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);
  background:#fff;color:var(--muted);cursor:pointer;white-space:nowrap;font-family:var(--sans)}
.rd-chip.on{background:var(--ink);border-color:var(--ink);color:#fff}
.rd-count{font-size:12.5px;color:var(--faint);margin:0 0 8px}
.rd-list{overflow:auto;flex:1;margin:0;padding:0;list-style:none}
.rd-list li{margin:0}
.rd-list button{display:block;width:100%;text-align:left;background:none;border:0;cursor:pointer;
  padding:8px 10px;border-radius:8px;font-size:13.5px;line-height:1.5;color:inherit;font-family:var(--sans)}
.rd-list button:hover{background:rgba(127,127,127,.10)}
.rd-list button.on{background:#e8f0fa;box-shadow:inset 2px 0 0 var(--brand)}
.rd-list .lv{font-size:11.5px;color:var(--faint);margin-left:6px;white-space:nowrap}
.rd-main{min-height:460px}

/* 工具条 */
.rd-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:#fff;
  border:1px solid var(--line);border-radius:11px;padding:9px 12px;margin-bottom:16px}
.rd-seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.rd-seg button{border:0;background:#fff;color:var(--ink-2);font-size:13px;padding:6px 12px;
  cursor:pointer;font-family:var(--sans);border-right:1px solid var(--line)}
.rd-seg button:last-child{border-right:0}
.rd-seg button.on{background:var(--ink);color:#fff}
.rd-btn{font-size:13px;padding:6px 13px;border-radius:8px;border:1px solid var(--line);
  background:#fff;color:var(--ink-2);cursor:pointer;font-family:var(--sans)}
.rd-btn:hover{border-color:var(--brand);color:var(--brand)}
.rd-sp{flex:1}
.rd-hint{font-size:12px;color:var(--faint)}
.rd-toc{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.rd-toc a{font-size:12.5px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);
  color:var(--ink-2);background:#fff}
.rd-toc a:hover{border-color:var(--brand);color:var(--brand);text-decoration:none}

/* 纸张 */
.paper{background:#fff;border:1px solid var(--line);border-radius:6px;max-width:920px;margin:0 auto;
  box-shadow:0 1px 2px rgba(16,24,40,.05),0 12px 34px rgba(16,24,40,.07);padding:52px 60px 64px}
@media(max-width:640px){.paper{padding:28px 20px 36px}}

/* 文末信息 */
.rd-meta{font-size:13px;color:var(--muted);line-height:1.95;margin:34px 0 0;
  padding-top:14px;border-top:1px solid var(--line-2)}
.rd-meta a{color:var(--brand)}
.rd-meta .k{color:var(--faint)}

/* ------- 公文版式（法律 / 行政法规 / 规章 / 规范性文件）------- */
.gw{font-family:"FangSong","仿宋_GB2312","STFangsong","Songti SC","SimSun",serif;
  font-size:20.5px;line-height:1.82;color:#101418;letter-spacing:.2px;text-align:justify}
.gw-title{font-family:"STZhongsong","方正小标宋简体","Songti SC","SimSun",serif;font-weight:700;
  font-size:1.6em;line-height:1.55;text-align:center;letter-spacing:3px;margin:0 0 10px}
.gw-sub{text-align:center;font-size:.82em;line-height:1.95;color:#3d444d;margin:4px 0 0;
  font-family:"KaiTi","STKaiti","Kaiti SC",serif}
.gw-org{text-align:center;font-size:.92em;color:#20262d;margin:18px 0 0;letter-spacing:1px}
.gw-rule{border:0;border-top:2px solid #101418;margin:22px 0 30px}
.gw-h1{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  text-align:center;font-size:1.02em;letter-spacing:2px;margin:30px 0 16px;text-indent:0}
.gw-h2{font-weight:700;text-align:center;font-size:1em;letter-spacing:1px;margin:24px 0 12px;text-indent:0}
.gw-p{margin:0 0 .44em;text-indent:2em}
.gw-p.noind{text-indent:0}
.gw-n{font-weight:600}
.gw-att{margin:18px 0 .3em;text-indent:0;font-weight:600}
.gw-sign{text-align:right;text-indent:0;margin:26px 2em 0}
.gw-caption{text-align:center;text-indent:0;font-weight:600;margin:18px 0 8px}
.gw mark,.st mark,.cm mark{background:#fff2a8;padding:1px 2px;border-radius:3px}

/* ------- 标准版式（国标 / 行标 / 团标）：对齐官方发布稿与 GB/T 1.1 的编排习惯 ------- */
.st{font-family:"Songti SC","宋体","SimSun",serif;font-size:16px;line-height:1.9;
  color:#101418;text-align:justify;letter-spacing:.1px}
/* 封面块：ICS/CCS 分列左右 → 标准类别 → 标准号 → 中英文名称 → 发布/实施日期 → 发布机构 */
.st-cover{text-align:center;margin:0 0 34px;padding:0 0 28px;border-bottom:1px solid #dbe1ea}
.st-cover .hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
  font-family:var(--sans);font-size:12.5px;color:#3d444d;letter-spacing:.6px;
  text-align:left;line-height:1.75;margin:0 0 30px;white-space:pre-line}
.st-cover .cls{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:17px;letter-spacing:5px;margin:0 0 16px}
.st-cover .code{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:21px;letter-spacing:2px;margin:0 0 34px}
.st-cover .cn{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:23px;line-height:1.55;margin:0 0 12px;letter-spacing:1px}
.st-cover .en{font-family:var(--sans);font-size:13px;line-height:1.65;color:#3d444d;
  letter-spacing:.2px;margin:0 auto 40px;max-width:640px}
.st-cover .dates{font-family:var(--sans);font-size:14px;color:#20262d;line-height:2.1;
  margin:0 0 6px}
.st-cover .dates span{display:inline-block;min-width:170px}
.st-cover .issuer{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:16px;letter-spacing:3px;margin:30px 0 0}
/* 目次：条款名 ……… 页码 */
.st-toc{margin:0 0 34px}
.st-toc .t{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  text-align:center;font-size:1.08em;letter-spacing:6px;margin:0 0 16px}
.st-toc .ln{display:flex;align-items:baseline;gap:6px;font-size:14.5px;line-height:2;
  text-indent:0}
.st-toc .ln i{flex:1;border-bottom:1px dotted #b9c3d0;transform:translateY(-4px)}
.st-toc .ln em{font-style:normal;color:#3d444d;font-family:var(--sans);font-size:13px}
.st-toc .ln.lv2{padding-left:1.6em}
.st-toc .ln.lv3{padding-left:3.2em}
/* 层级：一级条统排黑体顶格；二三级同字体递减；四级并入正文加粗 */
.st-h1{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:1.14em;margin:34px 0 12px;text-indent:0;letter-spacing:.6px}
.st-h2{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:1em;margin:20px 0 8px;text-indent:0}
.st-h3{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700;
  font-size:.98em;margin:15px 0 6px;text-indent:0}
.st-h4{font-weight:700;margin:11px 0 4px;text-indent:0}
/* 术语和定义：术语名 + 英文对应词 + 定义 */
.st-term{margin:14px 0 4px;text-indent:0;padding-left:0}
.st-term b{font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;font-weight:700}
.st-term i{font-style:normal;font-family:var(--sans);font-size:.9em;color:#3d444d}
.st-def{margin:0 0 .55em;text-indent:0}
.st-p{margin:0 0 .5em;text-indent:0}
.st-ind{padding-left:2em;margin:0 0 .4em;text-indent:0}
/* 列项（a) / 1) / — ）：悬挂缩进，编号不折行 */
.st-li{padding-left:3.4em;text-indent:-1.7em;margin:0 0 .32em}
.st-note{font-size:.87em;line-height:1.85;color:#3d444d;margin:.3em 0 .5em;text-indent:0}
.st-table{margin:.5em 0 1.1em;padding:.55em .9em;border-left:2px solid #dbe1ea;
  background:#fafbfd;font-family:var(--sans);font-size:13.5px;line-height:1.85;
  white-space:pre-wrap;overflow-x:auto}
.st-caption{text-align:center;text-indent:0;font-family:"SimHei","Heiti SC","Microsoft YaHei",sans-serif;
  font-weight:700;font-size:.96em;margin:18px 0 9px}
.st-quote{margin:.4em 0 .7em;padding:.5em .9em;border-left:2px solid #dbe1ea;
  font-size:.9em;line-height:1.85;color:#3d444d;text-indent:0}

/* ------- 舒适阅读版式（屏幕长读）------- */
.cm{font-family:var(--sans);font-size:16px;line-height:2.05;color:var(--ink);letter-spacing:.2px}
.cm-title{font-size:1.5em;font-weight:800;line-height:1.5;text-align:center;margin:0 0 10px}
.cm-sub{text-align:center;font-size:.85em;color:var(--muted);margin:2px 0 0}
.cm-rule{border:0;border-top:2px solid var(--line);margin:22px 0 26px}
.cm-h1,.cm-h2{font-weight:800;text-align:center;margin:28px 0 14px;text-indent:0}
.cm-p{margin:0 0 14px;text-indent:2em}
.cm-p.noind{text-indent:0}
.cm-n{font-weight:700}
.cm-sign{text-align:right;text-indent:0;margin:24px 0 0;color:var(--ink-2)}
.cm-caption{text-align:center;text-indent:0;font-weight:700;margin:18px 0 10px}

.rd-empty{color:var(--faint);font-size:14px;padding:40px 6px;line-height:1.9}
.rd-note{font-size:13px;color:var(--muted);line-height:1.9;margin:0 0 18px}
.rd-splash{padding:56px 6px;color:var(--muted);font-size:14.5px;line-height:2.1}
.rd-splash b{color:var(--ink)}

@media print{
  .topnav,.subnav,.mod-bound,footer,.rd-side,.rd-bar,.rd-toc,.pagehead,.rd-note,
  #toTop{display:none !important}
  body{background:#fff}
  .wrap{max-width:100%;padding:0}
  .paper{border:0;box-shadow:none;padding:0;max-width:100%}
  .rd{display:block}
  .gw{font-size:16pt;line-height:1.75}
  .gw-title{font-size:22pt;letter-spacing:2px}
  .gw-h1,.gw-h2{font-size:16pt}
  .st{font-size:11.5pt;line-height:1.75}
  .st-cover{page-break-after:always;border-bottom:0;padding-bottom:0}
  .st-cover .cn{font-size:20pt}
  .st-cover .code{font-size:18pt}
  .st-cover .cls{font-size:15pt}
  .st-toc{page-break-after:always}
  .st-h1,.st-h2,.st-h3{page-break-after:avoid}
  .st-caption{page-break-after:avoid}
  .st-table,.st-quote{page-break-inside:avoid}
  .cm{font-size:12pt;line-height:1.7}
  .cm-title{font-size:18pt}
  .rd-meta{font-size:9pt;color:#555;border-top:1px solid #ccc}
  @page{size:A4;margin:2.2cm 2cm}
}
"""

PAGE_JS = r"""
(function(){
  var IX=null, CUR=null, PARTS={}, KIND='', LV='', MODE='', HL='', SZ=0;
  var $=function(s){return document.querySelector(s)};
  var esc=function(s){return (s||'').replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})};

  var RE_ARTNO=/^第[一二三四五六七八九十百零〇\d]+条/;
  var RE_PIAN=/^第[一二三四五六七八九十百零〇\d]+编/;
  var RE_ZH=/^第[一二三四五六七八九十百零〇\d]+章/;
  var RE_JIE=/^第[一二三四五六七八九十百零〇\d]+节/;
  var RE_DATE=/^\d{4}年\d{1,2}月\d{1,2}日$/;
  var RE_ATT=/^附件\s*\d*\s*[:：]?/;
  var RE_CAP=/^(表|图)\s*[0-9A-Z一二三四五六七八九十]/;
  var RE_SUB=/^[（(].{0,140}[）)]$/;
  var RE_MULTI=/\s{2,}|\t/;

  function partName(x){ return (x.kind==='std'?'s':'p')+'-'+String(x.part).padStart(2,'0'); }
  function load(x){
    var k=partName(x);
    if(PARTS[k]) return Promise.resolve(PARTS[k]);
    return fetch('texts/'+k+'.json').then(function(r){return r.json()})
      .then(function(d){PARTS[k]=d;return d});
  }

  /* ---------- 结构识别 ---------- */
  function blocks(t){
    var out=[], ps=t.split(/\n{2,}/);
    for(var i=0;i<ps.length;i++){
      var raw=ps[i].replace(/^\n+|\n+$/g,'');
      if(!raw) continue;
      var lines=raw.split('\n').map(function(s){return s.trim()}).filter(Boolean);
      var flat=lines.join('');
      var type='p';
      if(RE_PIAN.test(flat)) type='h1';
      else if(RE_ZH.test(flat)) type='h1';
      else if(RE_JIE.test(flat)) type='h2';
      else if(RE_ARTNO.test(flat)) type='art';
      else if(RE_DATE.test(flat)) type='sign';
      else if(RE_ATT.test(flat)) type='att';
      else if(RE_CAP.test(flat)&&flat.length<44) type='caption';
      else if(lines.length>1&&RE_MULTI.test(raw)) type='table';
      out.push({type:type,text:flat,lines:lines});
    }
    return out;
  }
  function artNo(t){ var m=t.match(RE_ARTNO); return m?m[0]:''; }
  function halo(txt,inner){
    if(!HL||txt.indexOf(HL)<0) return inner;
    return esc(txt).split(esc(HL)).join('<mark>'+esc(HL)+'</mark>');
  }
  function artHtml(t,cls){
    if(HL&&t.indexOf(HL)>=0) return halo(t,'');
    return esc(t).replace(RE_ARTNO,'<span class="'+cls+'">'+artNo(t)+'</span>');
  }

  /* ---------- 公文版式 ---------- */
  function gongwen(x,t){
    var bs=blocks(t), html='', title=x.name, subs=[], org='', i;
    for(i=0;i<Math.min(bs.length,4);i++){
      var tx=bs[i].text;
      if(bs[i].type==='h1'||bs[i].type==='art') break;
      if(RE_SUB.test(tx)&&tx.length<170){ subs.push(tx); bs[i].used=1; continue; }
      if(/^中华人民共和国[^，。]{0,20}(主席令|国务院令|令)$/.test(tx)){ org=tx; bs[i].used=1; continue; }
      if(i===0&&tx.replace(/\s/g,'').length<=x.name.replace(/\s/g,'').length+10
         &&!RE_ARTNO.test(tx)){ title=tx; bs[i].used=1; }
    }
    html+='<div class="gw-title">'+esc(title)+'</div>';
    if(subs.length) html+='<div class="gw-sub">'+subs.map(esc).join('<br>')+'</div>';
    if(org) html+='<div class="gw-org">'+esc(org)+'</div>';
    html+='<hr class="gw-rule">';
    var chapters=[];
    for(i=0;i<bs.length;i++){
      var b=bs[i]; if(b.used) continue;
      var tx2=b.text;
      if(b.type==='h1'||b.type==='h2'){
        var id='c'+(chapters.length); chapters.push(tx2);
        html+='<p class="gw-'+(b.type==='h1'?'h1':'h2')+'" id="'+id+'">'+esc(tx2)+'</p>';
      } else if(b.type==='art'){
        html+='<p class="gw-p" data-art="'+esc(artNo(tx2))+'" id="'+esc(artNo(tx2))+'">'+artHtml(tx2,'gw-n')+'</p>';
      } else if(b.type==='sign') html+='<p class="gw-sign">'+esc(tx2)+'</p>';
      else if(b.type==='att') html+='<p class="gw-att">'+esc(tx2)+'</p>';
      else if(b.type==='caption') html+='<p class="gw-caption">'+esc(tx2)+'</p>';
      else if(b.type==='table') html+='<p class="gw-p noind">'+esc(b.lines.join('　'))+'</p>';
      else html+='<p class="gw-p">'+halo(tx2,esc(tx2))+'</p>';
    }
    return {html:html,chapters:chapters};
  }
  /* ---------- 标准正文结构识别（GB/T 1.1 编排惯例）---------- */
  var RE_SCLS=/^中华人民共和国[^，。；]{0,20}标准$/;
  var RE_STOC=/^(目\s*次|目\s*录)$/;
  var RE_SH0=/^\d{1,2}\s?[\u4e00-\u9fff]/;          // 一级条：1 范围
  var RE_SH1=/^\d{1,2}\.\d{1,2}\s?[\u4e00-\u9fff]/; // 二级条：4.1
  var RE_SH2=/^\d{1,2}(?:\.\d{1,2}){2}\s?[\u4e00-\u9fff]/;
  var RE_SH3=/^\d{1,2}(?:\.\d{1,2}){3}\s?[\u4e00-\u9fff]/;
  var RE_SAPX=/^附\s*录\s*[A-Z]?(\s|$)/;
  var RE_SAPXN=/^[A-Z]\.\d+(?:\.\d+)*\s?[\u4e00-\u9fff]/;
  var RE_SFRONT=/^(前\s*言|引\s*言|参考文献|索\s*引|特别声明)$/;
  var RE_SLI=/^(?:[a-z]\s*[)）]|[1-9]\d?\s*[)）]|[—–－]{1,2}\s|·\s)\s*\S/;
  var RE_SNOTE=/^(?:注\s*\d*\s*[:：]|示例\s*\d*\s*[:：]|注\s*\d*$|示例\s*\d*$)/;
  var RE_STERM=/^\d+(?:\.\d+)*\s?[^\x00-\x7F]{2,26}\s+[A-Za-z][A-Za-z0-9 ,\-'\u2019().]{1,}$/;
  var RE_SCAP=/^(表|图)\s*[0-9A-Z一二三四五六七八九十]/;
  function isTable(lines){
    if(lines.length<4) return false;
    for(var i=0;i<lines.length;i++){
      var l=lines[i];
      if(l.length>30) return false;
      if(/[。；]$/.test(l)) return false;
    }
    return true;
  }
  /* 条标题与正文黏在同一行（PDF 文字层最常见的形态：4.1.2自启动管理a)除提供…）。
     切点只能落在「列项标记」或「正文起句」上——条标题是名词短语，不会含这些词。 */
  var RE_TAIL=/[a-z]\s*[)）]|[1-9]\d?\s*[)）]|[—–－]{1,2}\s|应当?|不应|不得|必须|严禁|须|本标准|本文件|本规范|下列/;
  function splitHead(f,type){
    var m=f.match(/^(\d{1,2}(?:\.\d{1,2}){0,3})\s*/);
    if(!m) return null;
    var num=m[1], rest=f.slice(m[0].length);
    if(!rest) return null;
    var mm=rest.match(RE_TAIL), cut;
    if(mm) cut=mm.index;
    else if(type==='h1'&&rest.length>12){
      var m2=rest.match(/^([\u4e00-\u9fff、，]{2,10})/);
      if(!m2) return null;
      cut=m2[1].length;
    } else return null;
    var title=rest.slice(0,cut).replace(/[\s\u3000]+$/,'');
    var body=rest.slice(cut).replace(/^[\s\u3000]+/,'');
    if(!title||title.length>18||!body) return null;
    return {head:num+title, body:body};
  }
  function stdBlocks(t){
    var out=[], ps=t.split(/\n{2,}/);
    for(var i=0;i<ps.length;i++){
      var raw=ps[i].replace(/^\n+|\n+$/g,'');
      if(!raw) continue;
      var lines=raw.split('\n').map(function(s){return s.trim()}).filter(Boolean);
      if(!lines.length) continue;
      var f=lines[0], type='p';
      if(RE_STOC.test(f)) type='toc';
      else if(RE_SAPX.test(f)) type='h1';
      else if(/^第[一二三四五六七八九十]+章\s*\S/.test(f)) type='h1';
      else if(RE_SFRONT.test(f)) type='h1';
      else if(RE_SAPXN.test(f)&&f.length<44) type='h2';
      else if(RE_SH3.test(f)&&f.length<56) type='h4';
      else if(RE_SH2.test(f)&&f.length<52) type='h3';
      else if(RE_SH1.test(f)&&f.length<46) type='h2';
      else if(RE_SH0.test(f)&&f.length<40) type='h1';
      else if(RE_STERM.test(f)) type='term';
      else if(RE_SCAP.test(f)&&f.length<64) type='caption';
      else if(RE_SNOTE.test(f)) type='note';
      else if(isTable(lines)) type='table';
      else if(RE_SLI.test(f)) type='li';
      if(/^h[1-4]$/.test(type)){
        var head=f, rest='';
        var sp=splitHead(f,type);
        if(sp){ head=sp.head; rest=sp.body; }
        else if(lines.length>1&&f.length<=40){ rest=lines.slice(1).join(''); }
        else if(f.length>40){ type='p'; }        // 切不开又一整段 → 宁可当正文，也不做巨型粗体标题
        if(/^h[1-4]$/.test(type)){
          out.push({type:type,first:head,lines:[head],text:head});
          var segs=rest?paraSegs(rest):[];
          for(var q=0;q<segs.length;q++){
            var sg=segs[q];
            out.push({type:RE_SLI.test(sg)?'li':'p',first:sg,lines:[sg],text:sg});
          }
          continue;
        }
      }
      out.push({type:type,first:f,lines:lines,text:lines.join('')});
    }
    return out;
  }
  /* 一段正文里若夹着 a)/1)/— 列项，就在句末标点后断开，转成悬挂缩进的列项 */
  var RE_LISPLIT=/([。；：])\s*(?=[a-z]\s*[)）]|[1-9]\d?\s*[)）](?=\s*[^\d])|[—–－]{1,2}\s*\S)/g;
  function paraSegs(txt){
    // 不用后行断言（老 WebView 不支持），改用「插入分隔符再切」
    var parts=(txt||'').replace(RE_LISPLIT,'$1\u0001').split('\u0001');
    return parts.filter(function(x){return x&&x.trim()});
  }
  function splitTerm(f){
    var m=f.match(/^(\d+(?:\.\d+)*)\s?([^\x00-\x7F]{2,26})\s+([A-Za-z][A-Za-z0-9 ,\-'\u2019().]{1,})$/);
    if(!m) return null;
    return {n:m[1],cn:m[2],en:m[3]};
  }

  function coverHtml(cv){
    if(!cv) return '';
    var hd=[];
    if(cv.ics) hd.push('<span>ICS '+esc(cv.ics)+'</span>');
    if(cv.ccs) hd.push('<span>CCS '+esc(cv.ccs)+'</span>');
    var inner='';
    if(hd.length) inner+='<div class="hd">'+hd.join('')+'</div>';
    if(cv.cls) inner+='<div class="cls">'+esc(cv.cls)+'</div>';
    if(cv.code) inner+='<div class="code">'+esc(cv.code)+'</div>';
    if(cv.cn) inner+='<div class="cn">'+esc(cv.cn.replace(/\s+/g,' '))+'</div>';
    if(cv.en) inner+='<div class="en">'+esc(cv.en)+'</div>';
    var d=[];
    if(cv.pubdate) d.push('<div><span>'+esc(cv.pubdate)+'</span>发布</div>');
    if(cv.impldate) d.push('<div><span>'+esc(cv.impldate)+'</span>实施</div>');
    if(d.length) inner+='<div class="dates">'+d.join('')+'</div>';
    if(cv.issuer) inner+='<div class="issuer">'+esc(cv.issuer)+'</div>';
    return inner?'<div class="st-cover">'+inner+'</div>':'';
  }
  function tocHtml(toc){
    if(!toc||toc.length<4) return '';
    var withPage=0;
    for(var i=0;i<toc.length;i++) if(toc[i].p) withPage++;
    if(withPage/toc.length<0.5) return '';
    var rows=[];
    for(var j=0;j<toc.length;j++){
      var e=toc[j], t=(e.t||'').trim();
      var lv=/^\d{1,2}\.\d{1,2}\.\d{1,2}/.test(t)?'lv3':(/^\d{1,2}\.\d{1,2}/.test(t)?'lv2':'');
      rows.push('<div class="ln '+lv+'"><span>'+esc(t)+'</span><i></i><em>'+esc(e.p||'')+'</em></div>');
    }
    return '<div class="st-toc"><div class="t">目　次</div>'+rows.join('')+'</div>';
  }

  function stdView(x,t){
    var bs=stdBlocks(t), html='', chapters=[];
    html+=coverHtml(x.cover);
    html+=tocHtml(x.toc);
    // 封面/目次被单独渲染后，正文里若还残留同名块就跳过
    for(var i=0;i<bs.length;i++){
      var b=bs[i], tx=b.text;
      if(b.type==='toc') continue;
      if(b.type==='h1'||b.type==='h2'||b.type==='h3'||b.type==='h4'){
        var id='c'+(chapters.length); chapters.push(tx);
        html+='<p class="st-'+b.type+'" id="'+id+'">'+esc(tx)+'</p>';
      } else if(b.type==='term'){
        var st=splitTerm(b.first);
        if(st){
          html+='<p class="st-term"><b>'+esc(st.n+' '+st.cn)+'</b> <i>'+esc(st.en)+'</i></p>';
          for(var k=1;k<b.lines.length;k++) html+='<p class="st-def">'+esc(b.lines[k])+'</p>';
        } else html+='<p class="st-p">'+halo(tx,esc(tx))+'</p>';
      } else if(b.type==='caption'){ html+='<p class="st-caption">'+esc(tx)+'</p>'; }
      else if(b.type==='note'){ html+='<p class="st-note">'+esc(tx)+'</p>'; }
      else if(b.type==='table'){ html+='<div class="st-table">'+esc(b.lines.join('\n'))+'</div>'; }
      else if(b.type==='quote'){ html+='<div class="st-quote">'+esc(tx)+'</div>'; }
      else if(b.type==='li'){ html+='<p class="st-li">'+halo(tx,esc(tx))+'</p>'; }
      else {
        var segs=paraSegs(tx);
        for(var q=0;q<segs.length;q++){
          if(q===0) html+='<p class="st-p">'+halo(segs[q],esc(segs[q]))+'</p>';
          else html+='<p class="st-li">'+esc(segs[q])+'</p>';
        }
      }
    }
    return {html:html,chapters:chapters};
  }

  /* ---------- 舒适阅读 ---------- */
  function comfort(x,t){
    var isStd=(x.kind==='std');
    var bs=isStd?stdBlocks(t):blocks(t), html='', chapters=[];
    html+='<div class="cm-title">'+esc(x.name)+'</div>';
    if(x.code) html+='<div class="cm-sub">'+esc(x.code)+'</div>';
    html+='<hr class="cm-rule">';
    for(var i=0;i<bs.length;i++){
      var b=bs[i], tx=b.text;
      if(b.type==='h1'||b.type==='h2'){
        var id='c'+(chapters.length); chapters.push(tx);
        html+='<p class="cm-'+(b.type==='h1'?'h1':'h2')+'" id="'+id+'">'+esc(tx)+'</p>';
      } else if(b.type==='art'){
        html+='<p class="cm-p" data-art="'+esc(artNo(tx))+'" id="'+esc(artNo(tx))+'">'+artHtml(tx,'cm-n')+'</p>';
      } else if(b.type==='sign') html+='<p class="cm-sign">'+esc(tx)+'</p>';
      else if(b.type==='caption') html+='<p class="cm-caption">'+esc(tx)+'</p>';
      else if(b.type==='table') html+='<p class="cm-p noind">'+esc(b.lines.join('　'))+'</p>';
      else html+='<p class="cm-p">'+halo(tx,esc(tx))+'</p>';
    }
    return {html:html,chapters:chapters};
  }

  function baseSize(x,mode){ return mode==='cm'?16:(x.kind==='std'?16:20.5); }

  function render(){
    if(!CUR) return;
    var x=CUR, isStd=(x.kind==='std');
    if(!MODE) MODE=isStd?'std':'gw';
    if(isStd&&MODE==='gw') MODE='std';
    if(!isStd&&MODE==='std') MODE='gw';
    $('#rd-main').innerHTML='<div class="paper"><div class="rd-empty">正在载入原文…</div></div>';
    load(x).then(function(d){
      var t=d[x.id]||'';
      var r = MODE==='cm'?comfort(x,t) : (isStd?stdView(x,t):gongwen(x,t));
      var cls = MODE==='cm'?'cm' : (isStd?'st':'gw');
      var bar='<div class="rd-bar">'+
        '<div class="rd-seg">'+
          '<button data-m="'+(isStd?'std':'gw')+'" class="'+(MODE!=='cm'?'on':'')+'">'+
            (isStd?'标准版式':'公文版式')+'</button>'+
          '<button data-m="cm" class="'+(MODE==='cm'?'on':'')+'">舒适阅读</button>'+
        '</div>'+
        '<div class="rd-seg"><button id="rd-minus" title="缩小字号">A-</button>'+
        '<button id="rd-plus" title="放大字号">A+</button></div>'+
        '<button class="rd-btn" id="rd-copy">复制全文</button>'+
        '<button class="rd-btn" id="rd-dl">下载 TXT</button>'+
        '<button class="rd-btn" id="rd-wd">下载 Word</button>'+
        '<button class="rd-btn" id="rd-pr">打印 / 存 PDF</button>'+
        '<span class="rd-sp"></span><span class="rd-hint">'+t.length.toLocaleString()+' 字</span>'+
        '</div>';
      var meta=[];
      if(x.code) meta.push('<span class="k">编号</span> '+esc(x.code));
      meta.push('<span class="k">层级</span> '+esc(x.level));
      if(x.issuer) meta.push('<span class="k">发布机关</span> '+esc(x.issuer));
      if(x.pub) meta.push('<span class="k">发布</span> '+esc(x.pub));
      if(x.impl) meta.push('<span class="k">实施</span> '+esc(x.impl));
      if(x.status) meta.push('<span class="k">状态</span> '+esc(x.status));
      if(x.url) meta.push('<a href="'+esc(x.url)+'" target="_blank" rel="noopener">官方发布页 &#8599;</a>');
      var toc=r.chapters.length>1?('<div class="rd-toc">'+r.chapters.map(function(c){
          return '<a href="#'+x.id+'|'+esc(c)+'">'+esc(c)+'</a>';}).join('')+'</div>'):'';
      $('#rd-main').innerHTML=bar+toc+'<div class="paper">'+
        '<div class="'+cls+'" id="rd-body">'+r.html+'</div>'+
        '<div class="rd-meta">'+meta.join(' · ')+'</div></div>';
      document.title=x.name+' · 原文 · 合规无终点';
      SZ=baseSize(x,MODE);
      function applySize(){ $('#rd-body').style.fontSize=SZ+'px'; }
      $('#rd-plus').onclick=function(){ SZ=Math.min(27,SZ+1); applySize(); };
      $('#rd-minus').onclick=function(){ SZ=Math.max(13,SZ-1); applySize(); };
      var segs=document.querySelectorAll('.rd-seg button[data-m]');
      for(var i=0;i<segs.length;i++){(function(b){
        b.onclick=function(){ MODE=b.getAttribute('data-m'); render(); };
      })(segs[i]);}
      $('#rd-copy').onclick=function(){ navigator.clipboard.writeText(t).then(function(){
        $('#rd-copy').textContent='已复制 ✓';
        setTimeout(function(){$('#rd-copy').textContent='复制全文'},1600);}); };
      $('#rd-dl').onclick=function(){
        download(x.name+'.txt',[x.name+'\n'+(x.code?x.code+'\n':'')+'\n'+t],'text/plain;charset=utf-8'); };
      $('#rd-wd').onclick=function(){ word(x,t); };
      $('#rd-pr').onclick=function(){ window.print(); };
      if(HL) jump(HL);
      window.scrollTo({top:0,behavior:'smooth'});
    });
  }

  function download(name,parts,type){
    var a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob(parts,{type:type}));
    a.download=name; document.body.appendChild(a); a.click();
    setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},900);
  }

  function word(x,t){
    var isStd=(x.kind==='std');
    var body=(isStd?stdView(x,t):gongwen(x,t)).html.replace(/<mark>/g,'').replace(/<\/mark>/g,'');
    var css='@page{size:A4;margin:3.7cm 2.6cm 3.5cm 2.8cm}'+
      'body{font-family:"仿宋_GB2312",FangSong;font-size:16pt;line-height:28pt;text-align:justify}'+
      '.gw-title{font-family:"方正小标宋简体",STZhongsong;font-size:22pt;line-height:34pt;text-align:center;letter-spacing:2pt}'+
      '.gw-sub{text-align:center;font-family:KaiTi;font-size:14pt;line-height:24pt}'+
      '.gw-org{text-align:center;font-size:16pt}'+
      '.gw-rule{border:0;border-top:2pt solid #000}'+
      '.gw-h1,.gw-h2{font-family:SimHei;font-size:16pt;line-height:28pt;text-align:center}'+
      '.gw-p{margin:0;text-indent:2em}.gw-n{font-weight:bold}'+
      '.gw-att{margin:0;text-indent:0;font-weight:bold}.gw-sign{text-align:right;text-indent:0;margin-right:2em}'+
      '.gw-caption{text-align:center;text-indent:0;font-weight:bold}'+
      '.st-title{font-family:SimHei;font-size:20pt;text-align:center}'+
      '.st-code{text-align:center;font-size:12pt}'+
      '.st-h1,.st-h2{font-weight:bold;margin:0;text-indent:0}'+
      '.st-p{margin:0;text-indent:0}'+
      '.st-caption{text-align:center;text-indent:0;font-weight:bold}';
    var doc='<html xmlns:o="urn:schemas-microsoft-com:office:office" '+
      'xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">'+
      '<head><meta charset="utf-8"><title>'+esc(x.name)+'</title><style>'+css+'</style></head>'+
      '<body><div class="'+(isStd?'st':'gw')+'">'+body+'</div></body></html>';
    download(x.name+'.doc',['\ufeff'+doc],'application/msword');
  }

  function jump(art){
    var el=document.querySelector('[data-art="'+String(art).replace(/"/g,'')+'"]');
    if(el){ window.scrollTo({top:el.getBoundingClientRect().top+window.scrollY-140,behavior:'smooth'}); }
  }

  /* ---------- 侧栏 ---------- */
  function renderList(){
    var q=(($('#rd-q')||{}).value||'').trim();
    var ul=$('#rd-list'); ul.innerHTML='';
    var arr=IX.items.filter(function(x){
      if(KIND&&x.kind!==KIND) return false;
      if(LV&&x.level!==LV) return false;
      if(q&&x.name.indexOf(q)<0&&(x.code||'').indexOf(q)<0) return false;
      return true;});
    $('#rd-count').textContent=arr.length+' 条';
    var frag=document.createDocumentFragment();
    arr.forEach(function(x){
      var li=document.createElement('li'), b=document.createElement('button');
      b.innerHTML=esc(x.name)+'<span class="lv">'+esc(x.code||x.level)+'</span>';
      b.onclick=function(){ location.hash=x.id; };
      if(CUR&&CUR.id===x.id) b.className='on';
      li.appendChild(b); frag.appendChild(li);
    });
    ul.appendChild(frag);
  }

  function splash(){
    $('#rd-main').innerHTML='<div class="rd-splash"><b>从左侧选择一部法规或标准</b><br>'+
      '共 '+IX.items.length+' 部原文（法规 '+IX._law+' 部 · 标准 '+IX._std+' 部）。'+
      '正文按官方发文版式排印，支持复制全文、下载 TXT、导出 Word 与打印存 PDF。<br>'+
      '外部可直接定位到条文：<code>texts.html#原文id|第X条</code></div>';
    CUR=null; renderList();
  }

  function open(hash){
    if(!IX) return;
    var id=hash||'', art=HL;
    if(id.indexOf('|')>=0){ var p=id.split('|'); id=p[0]; art=p[1]; } else { art=''; }
    HL=art; SZ=0;
    var x=IX.items.filter(function(y){return y.id===id})[0];
    if(!x){ splash(); return; }
    if(!CUR||CUR.id!==x.id) MODE='';
    CUR=x; renderList(); render();
  }

  fetch('texts/index.json').then(function(r){return r.json()}).then(function(d){
    IX=d; IX._law=0; IX._std=0;
    var lvs={};
    IX.items.forEach(function(x){ lvs[x.level]=(lvs[x.level]||0)+1; if(x.kind==='std') IX._std++; else IX._law++; });
    var tb=$('#rd-tabs'), chipBox=$('#rd-chips');
    function buildChips(){
      chipBox.innerHTML='';
      var order=['法律','行政法规','部门规章','规范性文件','国家标准','行业标准','团体标准'];
      var ks=order.filter(function(k){return lvs[k]});
      Object.keys(lvs).forEach(function(k){ if(ks.indexOf(k)<0) ks.push(k); });
      var all=document.createElement('button');
      all.className='rd-chip'+(LV===''?' on':''); all.textContent='全部层级';
      all.onclick=function(){ LV=''; buildChips(); renderList(); };
      chipBox.appendChild(all);
      ks.forEach(function(k){
        if(KIND==='law'&&['国家标准','行业标准','团体标准'].indexOf(k)>=0) return;
        if(KIND==='std'&&['法律','行政法规','部门规章','规范性文件'].indexOf(k)>=0) return;
        var c=document.createElement('button');
        c.className='rd-chip'+(LV===k?' on':''); c.textContent=k+' '+lvs[k];
        c.onclick=function(){ LV=(LV===k?'':k); buildChips(); renderList(); };
        chipBox.appendChild(c);
      });
    }
    function setTab(kind,btn){
      KIND=kind; LV='';
      for(var i=0;i<tb.children.length;i++) tb.children[i].className='rd-tab';
      btn.className='rd-tab on'; buildChips(); renderList();
    }
    [['','全部 '+IX.items.length],['law','法规 '+IX._law],['std','标准 '+IX._std]].forEach(function(t,i){
      var b=document.createElement('button');
      b.className='rd-tab'+(i===0?' on':''); b.textContent=t[1];
      b.onclick=function(){ setTab(t[0],b); };
      tb.appendChild(b);
    });
    buildChips();
    $('#rd-q').addEventListener('input',renderList);
    renderList();
    window.addEventListener('hashchange',function(){ open(location.hash.slice(1)); });
    var q0=(location.hash||'').slice(1)||new URLSearchParams(location.search).get('id')||'';
    if(q0) open(q0); else splash();
  });
})();
"""


def write_page(count_law, total_chars, parts, count_std=0):
    tpl = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>原文库 · 法规与标准 · 合规无终点</title>
<meta name="description" content="法律、行政法规、部门规章、规范性文件与国家标准、行业标准、团体标准的正文，按官方发文版式排印，可在站内直接阅读、复制、下载与打印。">
<link rel="stylesheet" href="../assets/style.css">
<style>__CSS__</style>
</head>
<body>

<nav class="topnav"></nav>
<!-- SUBNAV:START --><!-- SUBNAV:END -->

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 原文库</div>
  <h1>原文库</h1>
  <p>法规与标准正文统一按官方发文版式排印：标题居中、层级清晰、条文可定位。<br>
     左侧按「法规 / 标准」与效力层级筛选，正文支持复制全文、下载 TXT、导出 Word 与打印存 PDF。</p>
</div></div>

<main class="wrap">
  <p class="rd-note">法规正文来自发布机关官网公开文本；标准正文取自本人存档（国标为三轮 OCR 比对定稿，行标与团标为发布机构公开 PDF 的文字层），仅供个人学习研究，正式引用请以官方发布版本为准。</p>
  <div class="rd">
    <aside class="rd-side">
      <input id="rd-q" class="rd-box" type="search" placeholder="按名称、文号或标准号检索">
      <div class="rd-tabs" id="rd-tabs"></div>
      <div class="rd-chips" id="rd-chips"></div>
      <div class="rd-count" id="rd-count"></div>
      <ul class="rd-list" id="rd-list"></ul>
    </aside>
    <section class="rd-main" id="rd-main">
      <div class="rd-splash">
        <b>左侧共 __COUNT__ 部原文</b>（法规 __LAW__ 部 · 标准 __STD__ 部，合计约 __WAN__ 万字）。<br>
        点选任意一条即可在此按公文版式阅读全文；标准另有「标准版式」，长文阅读可切「舒适阅读」。<br>
        条文可被外部直接定位：<code>texts.html#原文id|第X条</code>。
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
            .replace("__COUNT__", str(count_law + count_std))
            .replace("__LAW__", str(count_law))
            .replace("__STD__", str(count_std))
            .replace("__WAN__", "%.0f" % (total_chars / 10000.0)))
    open(os.path.join(HERE, "kb", "texts.html"), "w", encoding="utf-8").write(html)
    lint_page(html)
    print("阅读页：kb/texts.html")


if __name__ == "__main__":
    main()
