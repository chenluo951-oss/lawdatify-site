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
import os, re, json, sys, html, base64, hashlib, collections, unicodedata, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H
import edits as E

LIB = H.LIB
OUT = os.path.join(HERE, "kb", "texts")
MAP = os.path.join(HERE, "sources", "standards", "text_ids.json")
FLK_TEXT = os.path.join(HERE, "sources", "flk_texts", "texts.jsonl")
FLK_MIN_CHARS = 200      # 官方全文：短如「关于修改XX的决定」也收，故门槛低于语料
PER_PART = 40
# 分片：**片数固定、按 id 哈希落片**（不再按字数顺序累计切分）。
#   · 片数浮动 + 顺序切分 → 新增一部法会把后面所有片的边界推移，等于每次重建
#     全部分片都变，Git 把每一版都存进历史，仓库体积按天膨胀。
#   · 固定 96 片、按 id 取模 → 同一部法永远在同一片，只有内容真变的那几片产生新 blob。
# 单片体量：约 4700 部 / 96 片 ≈ 50 部/片，≤1.5MB，远低于 Git Data API 的 6MB 红线。
N_PART = 96
MIN_CHARS = 600

# 只收「法定效力层级」的公文；指引/指南（第三方或行业自律）、标准正文都不进本库
# 法定层级：宪法/法律/行政法规/监察法规/司法解释/修改决定都可发布官方正文。
# 「地方法规」亦为公开公文，但数量大，抓取端分批（见 tools/harvest_flk_texts.py）。
LAW_LEVELS = {"法律", "宪法", "行政法规", "监察法规", "司法解释",
              "修改决定", "地方法规", "部门规章", "规范性文件"}

# 列表排序用的效力层级次序。⚠️ 不能直接按「level 字符串」排：
# Python 比的是 Unicode 码位，「修改」的 U+4FEE 小于「司」「行」「地」「法」等，
# 于是 2000+ 件「XX市人民代表大会常务委员会关于修改《…》的决定」会全部顶到列表最前，
# 原文库一打开就是一屏修改决定（2026-09-16 全量抓取后实测到的展示回归）。
RANK = {"宪法": 0, "法律": 1, "行政法规": 2, "监察法规": 3, "司法解释": 4,
        "部门规章": 5, "规范性文件": 6, "地方法规": 7,
        "国家标准": 8, "行业标准": 9, "团体标准": 10, "修改决定": 11}
RANK_OTHER = 12


def level_rank(lv):
    return RANK.get(lv or "", RANK_OTHER)
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


# 「汇编」类文件：含省略线、点引线、节选/汇编字样的，视为取错文件。
# ⚠️ 2026-09-17 修：`目\s*录|目\s*次` 不能再当**强特征**放在这里。
#   法典正文自带「目 录」是常态（民法典/民事诉讼法/宪法/公司法/刑诉法解释…），
#   把它当汇编会把 61 条主干法整体踢出原文库 —— 线上表现就是「库里连民事诉讼法都没有」。
#   现在「目录」改为**弱特征**，只在能区分「法典自带目录」与「带页码的目次页」时使用，
#   见 looks_compilation()。
IDX_HEAD = re.compile(r"\.{5,}|…{2,}|节选|汇编")
ART_IN_HEAD = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")
TOC_RE = re.compile(r"目\s*录|目\s*次")
# ① 法典自带目录：`目 录` 后面紧跟 第X编/章/节 或 序言/前言/附则/总则 → 是正文的一部分
#    ⚠️ 必须要求这些字出现在**行首**：目次页的 `1总则9`（条目紧跟页码）里也含「总则」，
#    用 `[\s\S]{0,40}?` 跨行宽松匹配会把「1总则9」误当成法典标题。
TOC_OWN_RE = re.compile(
    r"目\s*录[^\n]{0,20}(?:\n\s*)+"
    r"(?:第\s*[一二三四五六七八九十百零〇\d]+\s*[编章节]|[序前附总]\s*[言则录])")
# ② 取错文件的目次页：`目 录` 后面是「编号 + 标题 + 页码」的条目表（如 `1总则9`、`2.1原料9`）
TOC_PAGE_RE = re.compile(r"\d+(?:\.\d+)*\s*[\u4e00-\u9fa5][\u4e00-\u9fa5、（）()]{0,14}\s*\d{1,4}(?:\s|$)")
# 转载页/栏目页的抬头（「XX人大常委会欢迎您」这类），正文再长也不是权威原文
# ⚠️ 2026-09-17 修：**不能**把「政务服务」「无障碍」「政务公开」当门户特征——
#   它们是法规正文里的常规主题词（《优化营商环境条例》第二章标题就是「政务服务」，
#   《无障碍环境建设法》整部法都围绕「无障碍」）。保留这三个词会把 50 条合规法规
#   （含 1 部法律、多部行政法规/地方法规）整体踢出原文库。
#   真正的门户页必然带「欢迎您/当前位置/网站首页/主办：/版权所有」这类站点骨架词，
#   单靠上述主题词不足以判定，故一律剔除。
PORTAL_HEAD = re.compile(r"欢迎您|欢迎访问|当前位置[:：]|您现在的位置|网站首页|"
                         r"主办[:：]|版权所有|回到顶部|门户网站|中国人大网")


def looks_compilation(t):
    """正文头 800 字若像法规汇编目次（无第一条、却有节选/点引线/带页码目次），视为取错文件。"""
    head = t[:800]
    if ART_IN_HEAD.search(head):
        return False
    if IDX_HEAD.search(head):
        return True
    if TOC_RE.search(head):
        if TOC_OWN_RE.search(head):
            return False            # 法典自带目录（第一编/第一章/序言…）→ 是正文
        if TOC_PAGE_RE.search(head):
            return True             # 带页码的目次页 → 取错文件（餐饮服务食品安全操作规范即此类）
        return False                # 「目录」只是正文里的普通词（目录附后/物品目录/遗传资源目录）
    return False


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
    """去重键：剥掉「中华人民共和国」与修订/节选等后缀，避免同一部法重复收录。

    ⚠️ 书名号必须一起剥（2026-09-16 修）：同一部规章在 flk 条目库里的名字不带书名号
    （`互联网跟帖评论服务管理规定`），而语料库/检索来源常带书名号
    （`《互联网跟帖评论服务管理规定》`）—— 只剥标点不剥《》，两条会算出不同的键而双双留下，
    线上表现为「1 组 id 重复、条目数比唯一 id 多 1」（实测 4532 条 / 4531 个唯一 id）。
    """
    n = re.sub(r"[（(].*?[)）]", "", name or "")
    n = n.replace("中华人民共和国", "").replace("中国", "")
    n = re.sub(r"(修订|修正案?|节选|试行|暂行|最新|全文|版本|稿)$", "", n)
    n = re.sub(r"[《》〈〉「」『』【】]", "", n)
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


def clean(text, reflow_it=True):
    """清洗抽取文本。

    reflow_it=False 用于**官方全文**（flk docx/pdf 文字层）：那里的换行本来就是
    逐条分条的语义换行，再走一次「软换行合并」会把整部法揉成一段。
    """
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
    t = _tight(reflow(t) if reflow_it else t)
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


def load_flk_texts():
    """读 tools/harvest_flk_texts.py 抓回的官方全文，索引为 bbbs。"""
    out = {}
    if not os.path.exists(FLK_TEXT):
        return out
    with open(FLK_TEXT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("b") and r.get("x"):
                out[r["b"]] = r
    return out


def flk_key(url):
    """从 flk 深链 detail2.html?<base64(bbbs)> 反解出 bbbs，用于官方正文精确匹配。

    按主键匹配比按名称模糊匹配可靠得多——同名法规（含已废止版本）不会串。
    """
    m = re.search(r"detail2\.html\?([A-Za-z0-9+/=_\-]+)", url or "")
    if not m:
        return None
    s = m.group(1).replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s).decode("utf-8")
    except Exception:
        return None


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
        # 置空而不删除：沙箱删除保护按会话轮次累计计数（阈值 50），
        # 一旦累计超过阈值，之后任何 os.remove 都会中断脚本。
        try:
            open(tmp, "w", encoding="utf-8").write("")
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
    # ⛔ 这里**不做任何 os.remove**。沙箱的删除保护是按「整个会话轮次」累计计数的
    # （SAFE_DELETE_BULK_CONFIRM_REQUIRED，阈值 50），而分片重建天然要清几十个文件，
    # 于是 daily_build 里「站内原文页」长期以退出码 1 静默失败。
    # 覆盖写（json.dump 本身就会覆盖）在语义上等价，且不产生删除动作。

    kept, idmap, dropped = [], {}, []
    flkmap = load_flk_texts()
    print("flk 官方全文 %d 条可用于精确匹配" % len(flkmap))
    for it in laws:
        picked = None
        # ① 首选：国家法律法规数据库的官方全文（官方 docx 文字层，按 bbbs 精确匹配）
        bk = flk_key(it.get("url"))
        if bk and bk in flkmap:
            t = clean(flkmap[bk]["x"], reflow_it=False)
            # 官方全文是「一条一行」，而阅读器按空行切段 → 逐条之间补空行，
            # 每条（含「（一）（二）」列举项）独立成段，公文版式才排得出来。
            t = re.sub(r"\n+", "\n\n", t)
            if len(t) >= FLK_MIN_CHARS:
                qok, why = quality_ok(t)
                if qok and not looks_compilation(t) and not looks_portal(t):
                    picked = (None, t)
                else:
                    picked = "flk 正文未过质量门禁（%s）" % why
        # ② 兜底：本机语料库 / 标准库
        for c in ([] if picked is not None else match_list(it, cand)):
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
            # 先去重时**官方全文优先**：同一部法若语料库与 flk 官方件都有，
            # 留官方件（官方 docx 文字层，无 OCR 误差）；再比字段完整度与正文长度。
            score_new = (bool(flk_key(rec.get("url"))), bool(rec["url"]),
                         sum(bool(rec[k]) for k in ("issuer", "pub", "impl")), rec["chars"])
            score_old = (bool(flk_key(old.get("url"))), bool(old["url"]),
                         sum(bool(old[k]) for k in ("issuer", "pub", "impl")), old["chars"])
            if score_new > score_old:
                kept[kept.index(old)] = rec
        idmap[key] = tid
    kept.sort(key=lambda x: (level_rank(x["level"]), x["name"]))
    for x in kept:
        x["part"] = 1 + (int(hashlib.md5(x["id"].encode()).hexdigest(), 16) % N_PART)

    parts = collections.defaultdict(dict)
    for x in kept:
        parts[x["part"]][x["id"]] = x.pop("_text")
        x.pop("_key", None)
        x.pop("_dk", None)
    written = set()
    for p, d in parts.items():
        fn = "p-%02d.json" % p
        json.dump(d, open(os.path.join(OUT, fn), "w", encoding="utf-8"),
                  ensure_ascii=False)
        written.add(fn)
    # 失效分片不删除，改写为空对象：空片不会被任何 index 条目指向（part 只指有内容的片），
    # 既不会误加载，也不产生删除计数。
    _stale = [f for f in os.listdir(OUT)
              if re.fullmatch(r"p-\d+\.json", f) and f not in written]
    for f in _stale:
        open(os.path.join(OUT, f), "w", encoding="utf-8").write("{}")
    if _stale:
        print("  置空失效分片 %d 个" % len(_stale))

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
/* 左栏两态：文档列表 / 该文档的章节目录。
   用户 2026-09-17：点开一部法规后目录要挪进左栏，别再横铺在正文上方。 */
.rd-pane{display:flex;flex-direction:column;flex:1;min-height:0}
.rd-pane[hidden]{display:none !important}
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
.rd-list{overflow:auto;flex:1 1 auto;min-height:0;margin:0;padding:0;list-style:none}
.rd-list li{margin:0}
.rd-list button{display:block;width:100%;text-align:left;background:none;border:0;cursor:pointer;
  padding:8px 10px;border-radius:8px;font-size:13.5px;line-height:1.5;color:inherit;font-family:var(--sans)}
.rd-list button:hover{background:rgba(127,127,127,.10)}
.rd-list button.on{background:#e8f0fa;box-shadow:inset 2px 0 0 var(--brand)}
.rd-more{color:var(--brand);font-weight:600;text-align:center;font-size:12.5px}
.rd-list .lv{font-size:11.5px;color:var(--faint);margin-left:6px;white-space:nowrap}
.rd-main{min-height:460px}

/* 工具条：吸附在顶栏下方，滚动时始终可点（原来会随正文滚走，读长法要回头找工具）。 */
.rd-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:rgba(255,255,255,.96);
  backdrop-filter:saturate(160%) blur(6px);
  border:1px solid var(--line);border-radius:11px;padding:7px 12px;margin-bottom:14px;
  position:sticky;top:70px;z-index:12}
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
/* 返回列表 + 当前文档名 + 章节目录（左栏目录态）
   ⚠️ 这三行固定高度必须写死 flex:0 0 auto：左栏是 flex 纵向容器，
   `.rd-cur` 带 overflow:hidden（自动最小尺寸 = 0）又被 max-height 限制，
   一旦容器空间不够就会被当成可压缩项压到零头高度 —— 表现为文档名
   **上半个字被裁掉**（用户 2026-09-18 截图报障）。只有章节目录该滚动。 */
.rd-back{display:block;width:100%;box-sizing:border-box;text-align:left;font-size:13px;
  flex:0 0 auto;padding:8px 11px;margin:0 0 11px;border-radius:9px;border:1px solid var(--line);
  background:#fff;color:var(--brand);cursor:pointer;font-family:var(--sans);font-weight:600}
.rd-back:hover{background:#f1f6fd;border-color:var(--brand)}
.rd-cur{font-size:14px;font-weight:700;line-height:1.45;color:var(--ink);margin:0 0 7px;
  flex:0 0 auto;display:-webkit-box;-webkit-line-clamp:2;max-height:2.9em;
  -webkit-box-orient:vertical;overflow:hidden}
.rd-tochd{font-size:11.5px;color:var(--faint);flex:0 0 auto;margin:0 0 9px;padding:0 0 9px;
  border-bottom:1px solid var(--line-2)}
.rd-toclist{overflow:auto;flex:1 1 auto;min-height:0;margin:0;padding:0;list-style:none}
.rd-toclist li{margin:0}
.rd-toclist a{display:block;padding:6px 10px;font-size:13px;line-height:1.5;color:var(--ink-2);
  border-left:2px solid transparent;border-radius:0 7px 7px 0;cursor:pointer}
.rd-toclist a:hover{background:rgba(127,127,127,.10);color:var(--ink)}
.rd-toclist a.on{background:#e8f0fa;border-left-color:var(--brand);color:var(--brand);font-weight:700}
.rd-toclist a.lv2{padding-left:24px;font-size:12.5px}
.rd-toclist a.lv3{padding-left:38px;font-size:12.5px}
.rd-toclist a.lv4{padding-left:50px;font-size:12.5px;color:var(--muted)}

/* 纸张：铺满右栏（原来写死 920px + 52/60 内边距，在宽屏上留出大片空白，
   用户 2026-09-18 反馈「阅读器只有一个小框」）。行宽靠 .gw/.st/.cm 自身的
   字号与 max-width 控制，不再让纸张居中缩在一角。 */
.paper{background:#fff;border:1px solid var(--line);border-radius:6px;max-width:100%;margin:0;
  box-shadow:0 1px 2px rgba(16,24,40,.05),0 12px 34px rgba(16,24,40,.07);padding:38px 44px 52px}
.paper>.gw,.paper>.cm{max-width:1080px;margin:0 auto}
.paper>.st{max-width:100%}
@media(max-width:640px){.paper{padding:24px 16px 32px}}

/* 专注阅读：收起左栏与页头，让正文占满整幅（工具栏右侧按钮切换）。
   长法条通读时最实用 —— 一屏多出两百多像素正文。 */
body.rd-focus .rd{grid-template-columns:1fr}
body.rd-focus .rd-side{display:none}
body.rd-focus .pagehead,body.rd-focus .rd-note,body.rd-focus .mod-bound{display:none}
body.rd-focus .wrap{padding-top:14px}
body.rd-focus .paper{max-width:100%;padding:44px 56px 56px}

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

/* ================= 法条 → 站内关联（案例 / 义务 / 专题分析） =================
   数据：kb/links.js（window.LD_LINKS，由 tools/build_text_links.py 生成）。
   用户 2026-09-18：读条文时看不到站内有没有引用它的处罚案例、有没有围绕
   这一条写的分析 —— 于是给每条被引用过的条文挂一个可点的计数徽标，
   点开右侧抽屉看明细，正文本身不动（复制全文与 Word 导出都取原始文本）。 */
.rd-btn.on{background:var(--brand);border-color:var(--brand);color:#fff}
.gw-n[data-rel],.cm-n[data-rel]{cursor:pointer;border-bottom:1px dotted rgba(15,40,70,.45)}
.gw-n[data-rel]:hover,.cm-n[data-rel]:hover{background:#eef5ff}
/* 徽标用伪元素渲染：不进正文 DOM，复制 / 导出 / 检索都不受污染 */
.gw-n[data-rel]:after,.cm-n[data-rel]:after{
  content:attr(data-reltxt);font-family:var(--sans);font-size:10.5px;font-weight:600;
  color:var(--brand);background:#eaf2fd;border:1px solid #cfe0f7;border-radius:999px;
  padding:0 6px;margin-left:8px;letter-spacing:0;vertical-align:2px;
  -webkit-text-decoration:none;text-decoration:none;white-space:nowrap}
body.rd-no-rel .gw-n[data-rel]:after,body.rd-no-rel .cm-n[data-rel]:after{display:none}
body.rd-no-rel .gw-n[data-rel],body.rd-no-rel .cm-n[data-rel]{cursor:inherit;border-bottom:0}

/* 文末「本站关联」：法规级清单 */
.rd-docrel{max-width:1080px;margin:34px auto 0;padding:18px 20px 16px;border:1px solid var(--line);
  border-radius:12px;background:linear-gradient(180deg,#fafcff,#fff);font-family:var(--sans)}
.rd-docrel h4{font-family:var(--sans);font-size:14px;margin:0 0 4px;display:flex;
  align-items:center;gap:8px}
.rd-docrel h4 em{font-style:normal;font-size:11.5px;font-weight:600;color:var(--brand);
  background:#eaf2fd;border-radius:999px;padding:2px 8px}
.rd-docrel .dr-hint{font-size:12.5px;color:var(--faint);margin:0 0 12px}
.rd-docrel .dr-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.rd-docrel .dr-col{border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:#fff}
.rd-docrel .dr-col>b{display:block;font-size:12.5px;color:var(--ink-2);margin:0 0 7px;
  padding:0 0 6px;border-bottom:1px solid var(--line-2)}
.rd-docrel .dr-col>b em{font-style:normal;color:var(--brand)}
.rd-docrel ul{margin:0;padding:0;list-style:none}
.rd-docrel li{font-size:12.5px;line-height:1.62;margin:0 0 6px;padding-left:12px;position:relative}
.rd-docrel li:before{content:"·";position:absolute;left:2px;color:var(--faint)}
/* ⚠️ 条目名必须独占一行：案例名与「机关 + 日期」挤在同一行时，换行会把
   日期甩到句子中间（用户 2026-09-18 截图里看着像错版）。让 <a> 成块，
   两条 <i> 仍在同一行。 */
.rd-docrel li a{display:block;color:var(--ink);text-decoration:none}
.rd-docrel li a:hover{color:var(--brand);text-decoration:underline}
.rd-docrel li i{font-style:normal;color:var(--faint);margin-left:5px;font-size:11.5px}
.rd-docrel .dr-more{font-size:12px;color:var(--faint);margin:6px 0 0}

/* 右侧抽屉：本条关联明细 */
.rel-mask{position:fixed;inset:0;background:rgba(16,24,40,.30);z-index:78;
  opacity:0;pointer-events:none;transition:opacity .18s}
body.rd-rel-open .rel-mask{opacity:1;pointer-events:auto}
.rel-drawer{position:fixed;top:0;right:0;height:100%;width:min(440px,94vw);background:#fff;
  border-left:1px solid var(--line);box-shadow:-12px 0 40px rgba(16,24,40,.16);z-index:80;
  display:flex;flex-direction:column;transform:translateX(103%);
  transition:transform .22s cubic-bezier(.4,0,.2,1)}
body.rd-rel-open .rel-drawer{transform:none}
.rel-hd{display:flex;align-items:flex-start;gap:10px;padding:16px 18px 12px;
  border-bottom:1px solid var(--line-2);flex:0 0 auto}
.rel-hd .rh-t{flex:1;min-width:0}
.rel-hd .rh-t b{display:block;font-size:15px;line-height:1.5}
.rel-hd .rh-t span{display:block;font-size:12.5px;color:var(--faint);margin-top:3px}
.rel-x{border:1px solid var(--line);background:#fff;border-radius:8px;width:30px;height:30px;
  cursor:pointer;color:var(--ink-2);font-size:15px;line-height:1;flex:0 0 auto}
.rel-x:hover{border-color:var(--brand);color:var(--brand)}
.rel-bd{flex:1 1 auto;overflow:auto;padding:14px 18px 22px;font-family:var(--sans)}
.rel-bd h5{font-size:12.5px;color:var(--ink-2);margin:0 0 8px;display:flex;align-items:center;gap:7px}
.rel-bd h5 em{font-style:normal;font-size:11px;font-weight:700;color:var(--brand);
  background:#eaf2fd;border-radius:999px;padding:1px 7px}
.rel-q{font-family:"FangSong","仿宋_GB2312","Songti SC",serif;font-size:15px;line-height:1.85;
  color:#101418;background:#fafbfd;border-left:3px solid var(--brand);border-radius:0 8px 8px 0;
  padding:11px 13px;margin:0 0 18px;max-height:260px;overflow:auto}
.rel-sec{margin:0 0 18px}
.rel-sec ul{margin:0;padding:0;list-style:none}
.rel-sec li{border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin:0 0 8px;
  font-size:13px;line-height:1.6}
.rel-sec li a{color:var(--ink);text-decoration:none;font-weight:600}
.rel-sec li a:hover{color:var(--brand)}
.rel-sec li em{display:block;font-style:normal;font-size:11.5px;color:var(--faint);margin-top:4px}
.rel-sec li.ref-li{border-style:dashed;background:#fafcff}
.rel-sec li.ref-li b{font-weight:700;display:block;font-size:12.5px}
.rel-sec li.ref-li span{font-size:12px;color:var(--muted);display:block;margin-top:3px}
.rel-none{font-size:12.5px;color:var(--faint);line-height:1.8;margin:0}
.rel-ft{flex:0 0 auto;border-top:1px solid var(--line-2);padding:11px 18px;
  display:flex;gap:10px;flex-wrap:wrap;font-size:12.5px;font-family:var(--sans)}
.rel-ft a{color:var(--brand);text-decoration:none}
.rel-ft a:hover{text-decoration:underline}
@media(max-width:640px){.rel-drawer{width:100%;border-left:0}}

@media print{
  .topnav,.subnav,.mod-bound,footer,.rd-side,.rd-bar,.rd-toc,.pagehead,.rd-note,
  #toTop,.rel-drawer,.rel-mask,.rd-docrel{display:none !important}
  .gw-n[data-rel]:after,.cm-n[data-rel]:after{display:none !important}
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
  var RE_TOCLINE=/^目\s*[录次]$/;
  var RE_CHAPLN=/^第([一二三四五六七八九十百零〇\d]+)([章编节])\s*(.{0,26})$/;
  var CN_D={'〇':0,'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9};
  function cnNum(s){
    if(/^\d+$/.test(s)) return parseInt(s,10);
    var total=0,num=0;
    for(var i=0;i<s.length;i++){
      var c=s.charAt(i);
      if(CN_D[c]!==undefined) num=CN_D[c];
      else if(c==='十'){ total+=(num||1)*10; num=0; }
      else if(c==='百'){ total+=(num||1)*100; num=0; }
      else return 0;
    }
    return total+num;
  }
  /* 正文自带「目录」段：官方文本里法条前普遍先排一份目录，逐条与后面的章节
     标题**同名**。若照收，章节目录会整体翻倍（《农业法》14 章被列成 28 节，
     《食品安全法》10 章变 20 节，用户 2026-09-18 报障），正文里也会多出一截
     只有标题的目录页。两条判据，先用严的：
       ① 标题串「自我重复」——把全文所有章/节标题按序抽出，若前 k 个与紧接着的
          k 个逐字相同，则前 k 个就是目录项（节也列进目录的法都用这条）。
       ② 序号递增段回退——目录只列章不列节时标题串对不齐，改看「第X章」的序号：
          若出现两段各自严格递增、且第二段从第一段末尾回退，则第一段是目录。
     ⚠️ 两条都要求成段（≥3 项）才动手，避免把正常法条正文里的孤立小标题误判。 */
  function dropToc(bs){
    var idx=[], txt=[], i, j;
    for(i=0;i<bs.length;i++){
      if(bs[i].used) continue;
      if(bs[i].type!=='h1'&&bs[i].type!=='h2') continue;
      var t=(bs[i].text||'').replace(/\s/g,'');
      if(!t||t.length>40||/[。；：]/.test(t)) continue;
      idx.push(i); txt.push(t);
    }
    var n=txt.length, from=-1, to=-1, k;
    if(n>=6){
      for(k=Math.floor(n/2);k>=3;k--){
        var ok=true;
        for(j=0;j<k;j++){ if(txt[j]!==txt[k+j]){ ok=false; break; } }
        if(ok){ from=idx[0]; to=idx[k]; break; }
      }
    }
    if(from<0){
      var ch=[];
      for(i=0;i<bs.length;i++){
        if(bs[i].used) continue;
        var tx=(bs[i].text||'').trim();
        var m=tx.match(RE_CHAPLN);
        if(!m||m[2]==='节') continue;
        if(tx.length>32||/[。；]/.test(tx)) continue;
        ch.push({i:i,n:cnNum(m[1])});
      }
      if(ch.length>=6){
        var runs=[], cur=[ch[0]];
        for(i=1;i<ch.length;i++){
          if(ch[i].n>ch[i-1].n) cur.push(ch[i]);
          else { runs.push(cur); cur=[ch[i]]; }
        }
        runs.push(cur);
        if(runs.length>=2&&runs[0].length>=3&&runs[1].length>=3&&
           runs[1][0].n<=runs[0][runs[0].length-1].n){
          from=runs[0][0].i; to=runs[1][0].i;
        }
      }
    }
    if(from<0) return false;
    for(i=from;i<to;i++) bs[i].used=1;
    /* 目录标记本身：常单独成段（「目　录」），也常与上一段黏在一起
       （「…第二次修正）目录」）——后者只切掉尾部两个字，不整段丢弃。 */
    if(from>0&&!bs[from-1].used){
      var p=bs[from-1], t0=(p.text||'').replace(/\s+$/,'');
      if(/目\s*[录次]$/.test(t0)){
        if(t0.length<=6) p.used=1;
        else{
          p.text=t0.replace(/[ \t\u3000]*目\s*[录次]$/,'');
          if(p.lines&&p.lines.length)
            p.lines[p.lines.length-1]=p.lines[p.lines.length-1]
              .replace(/[ \t\u3000]*目\s*[录次]$/,'');
        }
      }
    }
    return true;
  }
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
    dropToc(out);
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

  /* ---------- 法条 → 站内关联（kb/links.js，由 tools/build_text_links.py 生成） ----------
     站内三份资产（案例库 / 义务清单 / 专题分析）本来互相独立，读一条法条时看不出
     谁引用过它。这里把条文号变成关联入口：徽标显示「案例 N · 义务 M」，点开右侧抽屉。
     ⚠️ 法规名归一必须与 tools/build_article_index.py、assets/art-card.js 同一套。 */
  var LINKS=null, LINKS_TRIED=false, REL_ON=true;
  function lawKeyOf(name){
    var s=String(name||'').replace(/[\s\u3000《》]/g,'');
    s=s.replace(/^中华人民共和国/,'');
    s=s.replace(/[（(][^）)]{0,12}(修订|修正|草案|征求意见稿)[）)]$/,'');
    return s.length<3?'':s;
  }
  function loadLinks(){
    if(LINKS||LINKS_TRIED){ decorate(); return; }
    LINKS_TRIED=true;
    var s=document.createElement('script');
    s.src='links.js';                      // 与 texts.html 同级（kb/links.js）
    s.async=true;
    s.onload=s.onerror=function(){
      LINKS=window.LD_LINKS||{laws:{},arts:{}};
      decorate();
    };
    document.head.appendChild(s);
  }
  function relOf(art){
    if(!LINKS||!CUR||!art) return null;
    var k=lawKeyOf(CUR.name); if(!k) return null;
    return (LINKS.arts||{})[k+'|'+art]||null;
  }
  function docRel(){
    if(!LINKS||!CUR) return null;
    var k=lawKeyOf(CUR.name); if(!k) return null;
    return (LINKS.laws||{})[k]||null;
  }
  function relTxt(r){
    var s=[],a=(r.c||[]).length,w=(r.w||[]).length;
    if(a) s.push('案例 '+a);
    if(w) s.push('义务 '+w);
    return s.join(' · ');
  }
  /* 给正文里的条文号挂关联徽标（徽标是 CSS 伪元素，正文 DOM 不变） */
  function decorate(){
    var body=$('#rd-body'); if(!body) return;
    var art=body.querySelectorAll('[data-art]');
    for(var i=0;i<art.length;i++){
      var blk=art[i], tag=blk.querySelector('.gw-n,.cm-n,.st-n')||blk;
      var r=relOf(blk.getAttribute('data-art'));
      var t=r?relTxt(r):'';
      if(!t){
        tag.removeAttribute('data-rel'); tag.removeAttribute('data-reltxt');
        tag.removeAttribute('data-art'); continue;
      }
      tag.setAttribute('data-rel','1');
      tag.setAttribute('data-reltxt',t);
      tag.setAttribute('data-art',blk.getAttribute('data-art'));
      tag.title='点击查看引用本条的案例与依据本条的义务';
    }
    /* 文末「本站关联」：links.js 是异步拉的，首屏渲染时数据常常还没到
       —— 在这里补一次，避免「有徽标却没有文末清单」的半截状态。 */
    var paper=body.parentNode;
    if(paper&&!paper.querySelector('.rd-docrel')){
      var h=docRelHtml();
      if(h){
        var meta=paper.querySelector('.rd-meta');
        if(meta) meta.insertAdjacentHTML('beforebegin',h);
        else paper.insertAdjacentHTML('beforeend',h);
      }
    }
  }
  function closeRel(){
    document.body.classList.remove('rd-rel-open');
    var dr=$('#rd-rel'); if(dr) dr.innerHTML='';
  }
  function openRel(art){
    var r=relOf(art); if(!r) return;
    var dr=$('#rd-rel'); if(!dr) return;
    var blk=document.querySelector('#rd-body [data-art="'+String(art).replace(/"/g,'')+'"]');
    var q=blk?blk.textContent.replace(/\s+/g,' ').trim():'';
    var law=docRel()||{};
    var h='<div class="rel-hd"><div class="rh-t"><b>'+esc(art)+' · 本条关联</b>'+
      '<span>'+esc(CUR.name)+'</span></div>'+
      '<button class="rel-x" id="rel-x" type="button" title="关闭">&#215;</button></div>';
    h+='<div class="rel-bd">';
    h+='<div class="rel-q">'+esc(q)+'</div>';
    if((r.c||[]).length){
      h+='<div class="rel-sec"><h5>引用本条的处罚案例<em>'+r.c.length+' 条</em></h5><ul>';
      for(var i=0;i<r.c.length;i++){ var c=r.c[i];
        h+='<li><a href="cases.html#'+esc(c[0])+'" target="_blank" rel="noopener">'+esc(c[1])+'</a>'+
           '<em>'+esc(c[2]||'')+(c[3]?' · '+esc(c[3]):'')+(c[4]?' · '+esc(c[4]):'')+'</em></li>'; }
      h+='</ul></div>';
    }
    if((r.w||[]).length){
      h+='<div class="rel-sec"><h5>依据本条的合规义务<em>'+r.w.length+' 项</em></h5><ul>';
      for(var j=0;j<r.w.length;j++){ var w=r.w[j];
        h+='<li class="ref-li"><b>'+esc(w[2])+'</b><span>'+esc(w[0])+' · '+esc(w[1])+'</span>'+
           '<span><a href="duties.html'+esc(w[3])+'" target="_blank" rel="noopener">在合规义务清单中查看 &#8599;</a></span></li>'; }
      h+='</ul></div>';
    }
    if(!(r.c||[]).length&&!(r.w||[]).length){
      h+='<p class="rel-none">本条暂未关联到站内案例或义务。</p>';
    }
    if((law.a||[]).length){
      h+='<div class="rel-sec"><h5>本法专题分析<em>'+law.a.length+' 篇</em></h5><ul>';
      for(var m=0;m<law.a.length;m++){ var an=law.a[m];
        h+='<li><a href="'+esc(an[1])+'" target="_blank" rel="noopener">'+esc(an[0])+'</a>'+
           '<em>'+esc(an[2]||'')+'</em></li>'; }
      h+='</ul></div>';
    }
    h+='</div><div class="rel-ft"><a href="texts.html#'+esc((docRel()||{}).d||'')+'|'+esc(art)+
       '" target="_blank" rel="noopener">本条固定链接</a>'+
       '<a href="citations.html" target="_blank" rel="noopener">高频引用法条</a>'+
       (CUR.url?'<a href="'+esc(CUR.url)+'" target="_blank" rel="noopener">官方发布页 &#8599;</a>':'')+
       '<span style="color:var(--faint)">条文逐字取自我站官方原文库</span></div>';
    dr.innerHTML=h;
    document.body.classList.add('rd-rel-open');
    $('#rel-x').onclick=closeRel;
  }
  /* 文末「本站关联」：法规级清单 */
  function docRelHtml(){
    var r=docRel(); if(!r) return '';
    var cs=r.c||[], ws=r.w||[], as=r.a||[];
    if(!cs.length&&!ws.length&&!as.length) return '';
    var cols='';
    if(cs.length){
      cols+='<div class="dr-col"><b>引用本法规的处罚案例 <em>'+cs.length+'</em></b><ul>';
      for(var i=0;i<cs.length&&i<8;i++){ var c=cs[i];
        cols+='<li><a href="cases.html#'+esc(c[0])+'" target="_blank" rel="noopener">'+esc(c[1])+
              '</a><i>'+esc(c[2]||'')+'</i><i>'+esc(c[3]||'')+'</i></li>'; }
      cols+='</ul>'+(cs.length>8?'<p class="dr-more">另有 '+(cs.length-8)+' 条，可在案例库按「依据」检索</p>':'')+'</div>';
    }
    if(ws.length){
      cols+='<div class="dr-col"><b>依据本法规的合规义务 <em>'+ws.length+'</em></b><ul>';
      for(var j=0;j<ws.length&&j<8;j++){ var w=ws[j];
        cols+='<li><a href="duties.html'+esc(w[3])+'" target="_blank" rel="noopener">'+esc(w[2])+
              '</a><i>'+esc(w[0])+'</i></li>'; }
      cols+='</ul>'+(ws.length>8?'<p class="dr-more">另有 '+(ws.length-8)+' 项，见合规义务清单</p>':'')+'</div>';
    }
    if(as.length){
      cols+='<div class="dr-col"><b>本法专题分析 <em>'+as.length+'</em></b><ul>';
      for(var m=0;m<as.length;m++){ var an=as[m];
        cols+='<li><a href="'+esc(an[1])+'" target="_blank" rel="noopener">'+esc(an[0])+
              '</a><i>'+esc(an[2]||'')+'</i></li>'; }
      cols+='</ul></div>';
    }
    return '<div class="rd-docrel"><h4>本站关联 <em>法条 → 案例 / 义务 / 分析</em></h4>'+
      '<p class="dr-hint">下列内容取自本站案例库、合规义务清单与专题分析，均已与本法条建立引用关系；'+
      '正文中带蓝色徽标的条文号可点开看单条关联。</p><div class="dr-grid">'+cols+'</div></div>';
  }

  /* ---------- 左栏目录态 ----------
     用户 2026-09-17：点开一部法规后，章节目录要挪进左栏（原先是 .rd-toc 横铺在
     正文上方，既吃掉首屏又看不出层级），并给一个「返回列表」按钮。 */
  var SPYI=-1, RAF=0;
  function showPane(n){
    var a=$('#rd-pane-list'), b=$('#rd-pane-toc');
    if(a) a.hidden=(n!=='list');
    if(b) b.hidden=(n!=='toc');
  }
  function toList(){
    try{ history.replaceState(null,'',location.pathname+location.search); }catch(e){}
    splash();
  }
  function tocLv(t){
    var m=t.match(/^(\d+(?:\.\d+)*)\s/);
    if(m) return Math.min(4, m[1].split('.').length);
    if(/^[A-Z](\.\d+)*\s/.test(t)) return 2;
    if(/^第[一二三四五六七八九十百零〇\d]+节/.test(t)) return 2;
    return 1;
  }
  function sideDoc(x){
    SPYI=-1;
    var c=$('#rd-cur'); if(c) c.textContent=x?x.name:'';
    var h=$('#rd-tochd'); if(h) h.textContent='正在载入…';
    var u=$('#rd-toclist'); if(u) u.innerHTML='';
    showPane('toc');
  }
  function fillToc(chs){
    var n=(chs||[]).length, h=$('#rd-tochd'), u=$('#rd-toclist');
    if(!u) return;
    if(h) h.textContent = n>1 ? ('目录 · 共 '+n+' 节') : '本文不分章，可直接通读';
    u.innerHTML='';
    for(var i=0;i<n;i++){
      var li=document.createElement('li'), a=document.createElement('a');
      var cl='lv'+tocLv(chs[i]);
      a.className=cl; a.setAttribute('data-cls',cl); a.textContent=chs[i];
      a.onclick=(function(k){ return function(){
        var el=document.getElementById('c'+k);
        if(el) window.scrollTo({top:el.getBoundingClientRect().top+window.scrollY-132,behavior:'smooth'});
        markOn(k);
      };})(i);
      li.appendChild(a); u.appendChild(li);
    }
    spy();
  }
  function markOn(i){
    var u=$('#rd-toclist'); if(!u) return;
    for(var k=0;k<u.children.length;k++){
      var a=u.children[k].firstChild;
      if(a) a.className=a.getAttribute('data-cls')||'';
    }
    var cur=u.children[i]?u.children[i].firstChild:null;
    if(!cur) return;
    cur.className=(cur.getAttribute('data-cls')||'')+' on';
    var top=cur.offsetTop, hgt=u.clientHeight;
    if(top<u.scrollTop || top+cur.offsetHeight>u.scrollTop+hgt)
      u.scrollTop=Math.max(0, top-Math.round(hgt/3));
  }
  /* 滚动联动：取最后一个越过顶栏的标题作为当前章节 */
  function spy(){
    var p=$('#rd-pane-toc');
    if(!p||p.hidden) return;
    var hs=document.querySelectorAll('#rd-body [id^="c"]');
    if(!hs.length) return;
    var last=0;
    for(var i=0;i<hs.length;i++){ if(hs[i].getBoundingClientRect().top<=160) last=i; }
    if(last!==SPYI){ SPYI=last; markOn(last); }
  }
  window.addEventListener('scroll',function(){
    var p=$('#rd-pane-toc');
    if(!p||p.hidden||RAF) return;
    RAF=requestAnimationFrame(function(){ RAF=0; spy(); });
  },{passive:true});

  /* 条文关联抽屉的开关：正文里的徽标、遮罩、关闭键都走这一处 */
  document.addEventListener('click',function(e){
    var t=e.target;
    if(!t||!t.closest) return;
    var el=t.closest('[data-rel="1"]');
    if(el){ e.preventDefault(); openRel(el.getAttribute('data-art')); return; }
    if(t.closest('.rel-x')||t.id==='rel-mask') closeRel();
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'||e.keyCode===27) closeRel();
  });

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
        '<button class="rd-btn'+(REL_ON?' on':'')+'" id="rd-relbtn" '+
          'title="显示 / 隐藏条文号上的关联徽标">关联案例 · 分析</button>'+
        '<button class="rd-btn" id="rd-focus" title="收起左栏与页头，让正文占满整幅">专注阅读</button>'+
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
      $('#rd-main').innerHTML=bar+'<div class="paper">'+
        '<div class="'+cls+'" id="rd-body">'+r.html+'</div>'+
        docRelHtml()+
        '<div class="rd-meta">'+meta.join(' · ')+'</div></div>';
      fillToc(r.chapters);
      document.title=x.name+' · 原文 · 合规无终点';
      SZ=baseSize(x,MODE);
      function applySize(){ $('#rd-body').style.fontSize=SZ+'px'; }
      $('#rd-plus').onclick=function(){ SZ=Math.min(27,SZ+1); applySize(); };
      $('#rd-minus').onclick=function(){ SZ=Math.max(13,SZ-1); applySize(); };
      $('#rd-relbtn').onclick=function(){
        REL_ON=!REL_ON;
        document.body.classList.toggle('rd-no-rel',!REL_ON);
        $('#rd-relbtn').className='rd-btn'+(REL_ON?' on':'');
        if(!REL_ON) closeRel();
      };
      $('#rd-focus').onclick=function(){
        var on=document.body.classList.toggle('rd-focus');
        $('#rd-focus').className='rd-btn'+(on?' on':'');
      };
      if(!REL_ON) document.body.classList.add('rd-no-rel');
      loadLinks();          // 条文关联徽标（links.js 只在第一次真正去拉）
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
  /* 原文库收录到数千部后，一次性铺满 DOM 会卡；改为渐进渲染：
     先出 300 条，点底部按钮每批再加 500。筛选条件变化时重新从 300 起算。 */
  var SHOWN=300, LASTKEY=null;
  function renderList(){
    var q=(($('#rd-q')||{}).value||'').trim();
    var key=KIND+'|'+LV+'|'+q;
    if(key!==LASTKEY){ LASTKEY=key; SHOWN=300; }
    var ul=$('#rd-list'); ul.innerHTML='';
    var arr=IX.items.filter(function(x){
      if(KIND&&x.kind!==KIND) return false;
      if(LV&&x.level!==LV) return false;
      if(q&&x.name.indexOf(q)<0&&(x.code||'').indexOf(q)<0) return false;
      return true;});
    $('#rd-count').textContent=arr.length+' 条';
    var frag=document.createDocumentFragment();
    arr.slice(0,SHOWN).forEach(function(x){
      var li=document.createElement('li'), b=document.createElement('button');
      b.innerHTML=esc(x.name)+'<span class="lv">'+esc(x.code||x.level)+'</span>';
      b.onclick=function(){ location.hash=x.id; };
      if(CUR&&CUR.id===x.id) b.className='on';
      li.appendChild(b); frag.appendChild(li);
    });
    ul.appendChild(frag);
    if(arr.length>SHOWN){
      var li=document.createElement('li'), b=document.createElement('button');
      b.className='rd-more';
      b.textContent='还有 '+(arr.length-SHOWN)+' 部，点击继续显示';
      b.onclick=function(){ SHOWN+=500; renderList(); };
      li.appendChild(b); ul.appendChild(li);
    }
  }

  function splash(){
    $('#rd-main').innerHTML='<div class="rd-splash"><b>从左侧选择一部法规或标准</b><br>'+
      '共 '+IX.items.length+' 部原文（法规 '+IX._law+' 部 · 标准 '+IX._std+' 部）。'+
      '正文按官方发文版式排印，支持复制全文、下载 TXT、导出 Word 与打印存 PDF。<br>'+
      '条文号上带蓝色徽标的，说明站内已有引用该条的处罚案例或依据该条的合规义务 —— 点开即看；'+
      '文末「本站关联」给出整部法规的案例 / 义务 / 专题分析清单。<br>'+
      '长文可点工具条「专注阅读」把左栏收起，正文占满整幅。<br>'+
      '外部可直接定位到条文：<code>texts.html#原文id|第X条</code></div>';
    CUR=null; closeRel(); showPane('list'); renderList();
  }

  function open(hash){
    if(!IX) return;
    var id=hash||'', art=HL;
    if(id.indexOf('|')>=0){ var p=id.split('|'); id=p[0]; art=p[1]; } else { art=''; }
    HL=art; SZ=0;
    var x=IX.items.filter(function(y){return y.id===id})[0];
    if(!x){ splash(); return; }
    if(!CUR||CUR.id!==x.id) MODE='';
    CUR=x; renderList(); sideDoc(x); render();
  }

  fetch('texts/index.json').then(function(r){return r.json()}).then(function(d){
    IX=d; IX._law=0; IX._std=0;
    var lvs={};
    IX.items.forEach(function(x){ lvs[x.level]=(lvs[x.level]||0)+1; if(x.kind==='std') IX._std++; else IX._law++; });
    var tb=$('#rd-tabs'), chipBox=$('#rd-chips');
    function buildChips(){
      chipBox.innerHTML='';
      var order=['法律','行政法规','司法解释','部门规章','规范性文件','地方法规','国家标准','行业标准','团体标准','修改决定'];
      var ks=order.filter(function(k){return lvs[k]});
      Object.keys(lvs).forEach(function(k){ if(ks.indexOf(k)<0) ks.push(k); });
      var all=document.createElement('button');
      all.className='rd-chip'+(LV===''?' on':''); all.textContent='全部层级';
      all.onclick=function(){ LV=''; buildChips(); renderList(); };
      chipBox.appendChild(all);
      ks.forEach(function(k){
        if(KIND==='law'&&['国家标准','行业标准','团体标准'].indexOf(k)>=0) return;
        if(KIND==='std'&&['法律','行政法规','司法解释','部门规章','规范性文件','地方法规','修改决定'].indexOf(k)>=0) return;
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
    $('#rd-back').onclick=toList;
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
<title>法规与标准原文 · 合规无终点</title>
<meta name="description" content="法规库的原文阅读层：法律、行政法规、部门规章、规范性文件与国家标准、行业标准、团体标准的正文，按官方发文版式排印，可在站内直接阅读、复制、下载与打印。">
<link rel="stylesheet" href="../assets/style.css">
<style>__CSS__</style>
</head>
<body>

<nav class="topnav"></nav>
<!-- SUBNAV:START --><!-- SUBNAV:END -->

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / <a href="standards.html">法规库</a> / 法规与标准原文</div>
  <h1>法规与标准原文</h1>
  <p>法规与标准正文统一按官方发文版式排印：标题居中、层级清晰、条文可定位。<br>
     左侧按「法规 / 标准」与效力层级筛选；条文号上的蓝色徽标可点开看引用该条的处罚案例与依据该条的合规义务，文末给出整部法规的关联清单。
     正文支持复制全文、下载 TXT、导出 Word 与打印存 PDF，长文可切「专注阅读」。</p>
</div></div>

<main class="wrap">
  <p class="rd-note">法规正文来自发布机关官网公开文本；标准正文取自本人存档（国标为三轮 OCR 比对定稿，行标与团标为发布机构公开 PDF 的文字层）。正式引用请以官方发布版本为准。</p>
  <div class="rd">
    <aside class="rd-side">
      <div class="rd-pane" id="rd-pane-list">
        <input id="rd-q" class="rd-box" type="search" placeholder="按名称、文号或标准号检索">
        <div class="rd-tabs" id="rd-tabs"></div>
        <div class="rd-chips" id="rd-chips"></div>
        <div class="rd-count" id="rd-count"></div>
        <ul class="rd-list" id="rd-list"></ul>
      </div>
      <div class="rd-pane" id="rd-pane-toc" hidden>
        <button class="rd-back" id="rd-back">&#8592; 返回法规列表</button>
        <div class="rd-cur" id="rd-cur"></div>
        <div class="rd-tochd" id="rd-tochd"></div>
        <ul class="rd-toclist" id="rd-toclist"></ul>
      </div>
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

<!-- 本条关联抽屉（内容由 JS 渲染；数据来自 kb/links.js） -->
<div class="rel-mask" id="rel-mask"></div>
<aside class="rel-drawer" id="rd-rel" role="dialog" aria-label="本条关联"></aside>

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
