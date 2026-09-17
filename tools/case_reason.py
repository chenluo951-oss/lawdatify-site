#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从处罚公示正文里抽出**为什么处罚**（违法事实）与**怎么处罚**（处罚种类+幅度）。

## 为什么需要这一层

案例库的 `fact` 字段是**整页正文倾倒**，不是「事由」。直接把它显示在「处罚事由」列里，
用户看到的是这些东西（2026-09-17 反馈）：

    当事人：******代理事务所（普通合伙） 主体资格证照名称：《营业执照》
    统一社会信用代码（注册号）：************** 住所：****** 执行事务合伙人：***

    ——当事人主体资格抬头，不是违法事实。

    近年来，市场监管总局按照深化群众身边不正之风和腐败问题集中整治要求，坚持以案破局、
    以案促治，持续强化反不正当竞争执法……现选取九起典型案例予以公布。

    ——行动背景（通稿导语），不是违法事实。

用户要的是**裁判文书「法院认定事实」那一段**：谁、什么时候、干了什么违法的事。
所以在构建期做一次结构化抽取，抽不出来就退回「复制正文」。

## 三条抽取路径（按优先级）

1. **汇编拆解**（≥2 起）：`一、XX局查处XX公司XX案` → 每起提炼「主体｜违法事由——事实」。
2. **汇编首起**（正文被截断到只剩 1 起 / 页面只放了 1 起）：去掉通稿导语，
   从第一个案件小标题开始，按单起提炼。
3. **单案事实段**：锚点 `违法事实如下` / `经查，` / `现查明`…；
   止点 `上述事实主要有以下证据` / `本局认为` / `当事人的上述行为违反` / `依据《…》`。

## 处罚种类的抽取

用户要求「罚款」列改成「处罚」：罚款、吊销营业执照、停业整顿、通报批评……都算。
优先在**处罚决定段**里扫（避免正文里「否则将吊销营业执照」这类警示语被当成实际处罚），
没有决定段再退回全文。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

_WS = re.compile(r"\s+")


def _n(s):
    """压空白。政府站正文里常有全角空格与换行混排。"""
    return _WS.sub(" ", (s or "").replace("\u3000", " ")).strip()


def _cut(s, n):
    """按「非空白字符数」截断（与 case_text_clean 同口径）。"""
    cnt = 0
    for i, ch in enumerate(s):
        if not ch.isspace():
            if cnt == n:
                return s[:i].rstrip()
            cnt += 1
    return s


# ---------------------------------------------------------------------------
# 一、单案：定位「违法事实」段
# ---------------------------------------------------------------------------

# 事实起点锚点。**取最靠后命中的那个**：抬头里也可能出现同类字样，
# 但我们想要的是真正进入事实叙述的位置。
_FACT_START = re.compile(
    r"(?:存在|有|实施了?)(?:以下|如下|下列)[^。，；：:]{0,8}?"
    r"(?:违法|价格违法|广告违法|食品)?(?:事实|行为)|"
    r"违法(?:事实|行为)(?:如下|是|：|:)|"
    r"(?:现|现?已|经)查明[，,、：:]|"
    r"经查[，,、：:]|经调查[，,、：:]|"
    r"现将[^。]{0,50}?(?:告知|通知|公告)如下[：:]?|"
    r"(?:本|我)(?:局|机关|委|院|部|厅)?(?:依法)?(?:于[^，。；]{0,30})?立案调查"
)

# 事实止点：证据段 / 定性段 / 决定段。命中即截断。
_FACT_STOP = re.compile(
    r"上述(?:事实|行为|违法事实|违法事实及)|以上(?:事实|行为)|前述(?:事实|行为)|"
    r"有下列证据|有以下证据|主要(?:有以下)?证据|证据(?:证明|如下|充分)|"
    r"当事人(?:的)?(?:上述|以上)?(?:行为|经营行为|销售行为|上述行为)|"
    r"(?:本|我)(?:局|机关|委|院)认为|本机关认为|"
    r"依据《|根据《|依照《|综上|"
    r"决定(?:对当事人)?(?:作出|给予)?(?:如下|以下)?(?:行政)?处罚|"
    r"责令(?:当事人|你(?:单位|公司))?(?:立即)?改正|"
    r"（此件公开发布）|\(此件公开发布\)|"
    r"当事人(?:如|若)?不服|如不服本"
)

# 抽出来的段落开头若是「当事人存在以下违法事实：」这类引导语，再削一刀
_LEAD_JUNK = re.compile(
    r"^(?:(?:当事人|你(?:单位|公司|店|厂)|该公司|当事人的?[\u4e00-\u9fa5]{0,6})?)"
    r"(?:存在|有|实施了?)?(?:以下|如下|下列)?"
    r"(?:[\u4e00-\u9fa5]{0,6})?(?:违法|价格违法)?(?:事实|行为)"
    r"\s*[:：]\s*|"
    r"^(?:经查|经查明|现查明|现已查明|经调查)\s*[:：，,、]\s*"
)

# 当事人身份 KV：`当事人：XX 主体资格证照名称：《营业执照》 统一社会信用代码：…`
# 它在正文里**可以出现多次**（送达公告 → 告知书正文各一份），必须循环剥。
_KV_FIELD = (r"(?:当事人|主体资格证照名称|统一社会信用代码(?:（注册号）)?|注册号|"
             r"住\s*所|经营场所|法定代表人|执行事务合伙人|负责人|身份证号码|"
             r"联系电话|邮政编码|联系地址|邮编|机构代码)")
_KV_ONE = re.compile(r"^" + _KV_FIELD + r"\s*[：:]\s*[^：:]{0,80}?"
                     r"(?=\s*" + _KV_FIELD + r"\s*[：:]|\s*$)")


def _strip_kv(s, rounds=10):
    for _ in range(rounds):
        m = _KV_ONE.match(s)
        if not m:
            break
        s = s[m.end():].strip(" ，,、。；;")
    return s


def _split_fact(s, depth=0):
    """返回 (事由正文, 模式)。抽不到时模式为 ""。"""
    s = _n(s)
    if not s:
        return "", ""
    best = None
    for m in _FACT_START.finditer(s):
        if len(s) - m.end() >= 12:
            best = m
    if best is None:
        return "", ""
    seg = s[best.end():]
    seg = re.sub(r"^[\s，,、。；;：:）)]+", "", seg)
    seg = _LEAD_JUNK.sub("", seg)
    # 引导句后紧跟的当事人身份 KV（送达公告 → 告知书正文，一份正文里可能有两处）
    seg2 = _strip_kv(seg)
    if len(seg2) >= 8:
        seg = seg2
    st = _FACT_STOP.search(seg)
    if st and st.start() >= 12:
        seg = seg[:st.start()]
    seg = seg.strip(" ，,、。；;")
    # 剥完若开头又是一句引导语，说明刚才那个锚点只是向导，再抽一次
    if depth == 0 and re.match(r"^(?:经查|经查明|现查明|现已查明|经调查|当事人\s*[：:])", seg):
        seg3, how3 = _split_fact(seg, depth=1)
        if seg3 and len(seg3) >= 8:
            return seg3, how3
    if len(seg) >= 8:
        return seg, "anchor"
    return "", ""


# ---------------------------------------------------------------------------
# 二、汇编：案件小标题
# ---------------------------------------------------------------------------

# 案件小标题：`一、XX局查处XX公司XX案` / `案例1：…` / `案例一  …`
# ⚠️ 边界类必须含 `：:` / 引号 / 顿号：通稿里小标题常写在「……公布如下： 一、」这种位置，
# 只认句末标点会**整条汇编都拆不出来**（实测 IDX 49 / 74 因此退回 copy 模式，
# 显示的正好是用户投诉的那段导语）。
_CASE_HDR = re.compile(
    r"(?:^|[\s。；;！!：:」』”\"、])"
    r"(?:案例\s*)?([一二三四五六七八九十]{1,3}|\d{1,2})\s*[、.．：:]\s*"
)
_HDR_SIGNAL = re.compile(r"案(?:\s|$|。|，|、|）|\)|；)|查处|处罚|没收|罚款|责令")
# 标题长这样 → 本文是「典型案例汇编」，正文开头那段是通稿导语而不是案情
_COMPILATION_TITLE = re.compile(r"典型案例|案例|曝光|查处|公布|通报|整治|销毁")
# 小标题残渣：「。 一、」/「案例1：」/「（二）」这类前缀
_HDR_JUNK = re.compile(r"^[\s。；;，,、：:」』”\"（()）]*")


def _strip_hdr_junk(s):
    s = _HDR_JUNK.sub("", s)
    return _CASE_HDR.sub("", s, count=1).strip()


def _case_headers(s):
    """找出所有**像案件小标题**的位置。

    ⚠️ 只在小标题后面 90 字内出现「案 / 查处 / 处罚」时才认：
    否则反垄断决定书里的「一、基本情况」「二、违法事实」也会被当成案件小标题。
    """
    hits = []
    for m in _CASE_HDR.finditer(s):
        if _HDR_SIGNAL.search(s[m.end():m.end() + 90]):
            hits.append(m)
    return hits


def _split_compilation(s, hits, max_n=40):
    """按小标题把汇编切成每起案件一段。"""
    blocks = []
    for i, m in enumerate(hits[:max_n]):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(s)
        blocks.append(s[m.end():end].strip())
    return blocks


_AGENCY_TAIL = re.compile(
    r"^[\u4e00-\u9fa5]{2,14}?(?:市场监督管理|监督管理|市场监督|综合行政执法|综合执法|"
    r"生态环境|交通运输|应急管理|药品监督管理|知识产权|卫生健康|农业农村|文化和旅游|"
    r"城市管理|公安|水务|税务|海关|网信|通信管理|发展和改革|住房和城乡建设|民政|教育)"
    r"[\u4e00-\u9fa5]{0,14}?(?:局|委|厅|部|队|署|办|分局|支队|所|处)"
)

_ORG_SUF = (
    "有限责任公司|股份有限公司|有限公司|有限合伙|合伙企业|公司|企业|集团|厂|店|商行|"
    "超市|药房|药店|事务所|研究院|医院|学校|幼儿园|协会|学会|合作社|经营部|工作室|"
    "服务部|门市部|中心|bank|支行|支行|门诊部|酒店|宾馆|饭店|餐厅|农资|加油站"
)
_ORG_RE = re.compile(
    r"^([\u4e00-\u9fa5A-Za-z0-9（）()·．\.\-\"]{1,40}?)(" + _ORG_SUF + r")"
)


_LOC_CHAIN = re.compile(
    r"^(?:[\u4e00-\u9fa5]{2,10}?(?:省|自治区|特别行政区)|"
    r"[\u4e00-\u9fa5]{2,10}?(?:市|自治州|地区|盟)|"
    r"[\u4e00-\u9fa5]{2,10}?(?:县|区|旗|镇|乡|街道))"
)


def _strip_loc(s):
    """`江苏省连云港市东海县井某某…` → `井某某…`（只剥行政区划，保留主体名）。

    汇编小标题里的主体**常带辖区前缀**，不剥掉的话自然人主体的正则匹配不到，
    整段会被当成「违法事由」塞进主体位。
    """
    for _ in range(3):
        m = _LOC_CHAIN.match(s)
        if not m or len(s) - m.end() < 3:
            break
        s = s[m.end():]
    return s


def _split_subject_from_title(seg):
    """`湖南享智科技有限公司虚假宣传` → (主体, 违法事由)。"""
    seg = _n(seg)
    seg = _AGENCY_TAIL.sub("", seg).strip()
    seg = re.sub(r"^(?:(?:依法)?(?:对|向|给予)|分别|另|自)?", "", seg).strip()
    seg = _strip_loc(seg)
    # 脱敏主体常写成「临湘市 某 加油站」→ 去掉名字里的空格，否则主体正则连不上
    seg = re.sub(r"(?<=[\u4e00-\u9fa5])[ \t]+(?=[\u4e00-\u9fa5])", "", seg).strip()
    m = _ORG_RE.match(seg)
    if m:
        subj = m.group(1) + m.group(2)
        return subj, seg[len(subj):].strip(" 、，,。")
    # 自然人（「倪某倩销售侵犯…」/「黄某某销售不符合…」）
    m = re.match(r"^([\u4e00-\u9fa5]{1,4}(?:某某|某))(?:\s*等\s*\d+\s*[人名家户]?)?", seg)
    if m:
        return m.group(1), seg[m.end():].strip(" 、，,。")
    return "", seg


def _digest_case(block):
    """把一起案件的段落提炼成 (主体, 违法事由, 事实摘要)。"""
    b = _n(block)
    # 去掉小标题残渣与「案情简介：」
    b = re.sub(r"^\s*(?:案例\s*[一二三四五六七八九十\d]+\s*[、.：:]?)\s*", "", b)
    b = re.sub(r"^\s*(?:案情简介|基本案情|案情|案件简介|案件情况)\s*[：:]\s*", "", b).strip()

    subj, viol = "", ""
    m = re.search(r"查处(.{2,90}?)案(?:\s|$|。|，|、|（|\()|查处(.{2,90}?)案", b)
    if m:
        seg = (m.group(1) or m.group(2) or "").strip()
        subj, viol = _split_subject_from_title(seg)
    if not subj:
        m2 = re.match(r"(.{2,90}?)案(?:\s|$|。|，|、|（|\()", b)
        if m2:
            subj, viol = _split_subject_from_title(m2.group(1).strip())

    detail, mode = _split_fact(b)
    if not detail:
        # 汇编里常见「2026年6月，…立案调查。经查，…」
        m3 = re.search(r"经查[，,、]?\s*(.{10,400}?)(?:上述|依据《|综上|该(?:公司|店|企业)|$)", b)
        if m3:
            detail, mode = m3.group(1).strip(), "jinhca"
    if not detail:
        body = b[m.end():] if m else re.sub(r"^.{2,90}?案(?:\s|。|，)", "", b, count=1)
        body = re.sub(r"^[\s。；;，,：:]+", "", body)
        detail = "".join(re.split(r"(?<=[。！？])", body)[:2]).strip()
        mode = mode or "fallback"
    return subj, viol, _n(detail), mode


# ---------------------------------------------------------------------------
# 三、处罚种类 + 幅度
# ---------------------------------------------------------------------------

# (标签, 正则)。顺序 = 展示顺序（重的在前）。
PEN_RULES = [
    ("吊销营业执照", re.compile(r"吊销[^，。；]{0,10}营业执照|吊销[^，。；]{0,8}执照")),
    ("吊销许可证", re.compile(r"吊销[^，。；]{0,12}(?:许可证|许可证书|执业证书|资质证书|资质)")),
    ("责令停产停业", re.compile(r"责令[^，。；]{0,12}(?:停产停业|停业|停产|关闭|停办)")),
    ("没收违法所得", re.compile(r"没收[^，。；]{0,8}违法所得")),
    ("没收非法财物", re.compile(r"没收[^，。；]{0,16}(?:非法财物|违法财物|侵权(?:商品|产品)|"
                                 r"涉案(?:物品|商品|产品|食品|药品|物资)|"
                                 r"物品|商品|产品|食品|药品|标签|包装|原材料|工具|设备)")),
    ("罚款", re.compile(r"罚款|处以[^，。；]{0,10}罚(?:款|金)|罚没款|没收违法所得并处")),
    ("警告", re.compile(r"予以警告|给予警告|处以警告|行政警告|警告[，。；]|警告、")),
    ("通报批评", re.compile(r"通报批评|予以通报|公开曝光|予以曝光")),
    ("列入严重违法失信名单", re.compile(r"(?:列入|纳入)[^，。；]{0,14}(?:严重违法失信名单|失信名单|"
                                         r"严重失信主体名单|经营异常名录)")),
    ("行政拘留", re.compile(r"行政拘留|处以拘留|给予拘留")),
    ("移送公安机关", re.compile(r"移送公安|涉嫌犯罪|移送司法|追究刑事责任")),
    ("责令改正", re.compile(r"责令[^，。；]{0,10}(?:改正|限期改正|停止(?:违法)?行为|下架|整改)")),
]

_MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|亿|万元|万|元)")
# ⚠️ 政府站正文里金额常被空格/分页切碎：`27709 .61 元`、`20 万元`。
# 不先合上，会把一个数拆成两个（实测把「27709.61 元」拆成 27709 与 61 两笔罚款）。
_NUM_JOIN = re.compile(r"(?<=\d)\s+(?=[.\d])|(?<=[.\d])\s+(?=(?:亿|万)?元)")

# 「罚款 / 没收违法所得」后面紧跟的那个数才是处罚金额。
# ⚠️ 不能只按「决定段里出现的第一个金额」取：决定书里金额的第一次出现往往是
# **上一年度销售额**（「处 2023 年销售额 2770960.57 元 1% 的罚款，即 27709.61 元」），
# 直接取第一个会把 277.10 万元当成罚款额（实际罚了 2.77 万元）。
_PEN_AMT = re.compile(
    r"(?:罚款|罚没款|罚金|没收违法所得|没收非法所得|没收非法财物|"
    r"没收(?:违法|非法)财物|处以罚款|并处)\s*[,，、：:;；即]?\s*"
    r"(?:人民币)?\s*([\d.,]+)\s*(亿元|亿|万元|万|元)")


def _fix_num(s):
    return _NUM_JOIN.sub("", s or "")


def _pen_amounts(text, limit=3):
    out = []
    for m in _PEN_AMT.finditer(_fix_num(text)):
        x = _fmt_money(m.group(1).replace(",", "") + m.group(2))
        if x and x not in out:
            out.append(x)
    return out[:limit]

# 「决定段」定位：处罚种类优先在这里面找
_DECISION = re.compile(
    r"(?:决定(?:对当事人)?(?:作出|给予)?(?:如下|以下)?(?:行政)?处罚|处罚(?:决定)?如下|"
    r"作出如下处罚|拟(?:对当事人)?(?:作出|给予)?(?:如下|以下)?处罚|"
    r"(?:本|我)(?:局|机关|委|院)(?:决定|现决定)|"
    r"综上[，,]?\s*(?:本|我)?(?:局|机关|委|院)?|"
    r"责令(?:当事人|你(?:单位|公司))?(?:立即)?改正)"
)


def _fmt_money(txt):
    """`28000元` → `2.8万元`；`9375元` → `9375元`；`16.63万元` 原样。"""
    txt = _n(str(txt))
    m = re.fullmatch(r"([\d.]+)\s*(亿元|亿|万元|万|元)", txt)
    if not m:
        return txt
    v = float(m.group(1))
    unit = m.group(2)
    if unit in ("万元", "万", "亿元", "亿"):
        return txt.replace(" ", "")
    if v >= 100000000:
        return ("%g" % (v / 100000000.0)) + "亿元"
    if v >= 10000:
        s = ("%.4f" % (v / 10000.0)).rstrip("0").rstrip(".")
        return s + "万元"
    return ("%g" % v) + "元"


def extract_penalty(fact, fines=None, title="", kind="", limit_fines=3):
    """返回 {'kinds': [...], 'fines': [...], 'text': '吊销营业执照、罚款 2.8万元'}。

    只有找到**至少一个处罚种类或金额**才算解析成功；否则 text 为空，
    由页面显示「—」，不硬猜。
    """
    f = _n(fact)
    kinds = []

    scope = f
    if f:
        m = None
        for x in _DECISION.finditer(f):
            m = x
        if m and len(f) - m.start() >= 20:
            scope = f[m.start():]

    def _scan(text):
        out = []
        for label, pat in PEN_RULES:
            if pat.search(text):
                out.append(label)
        return out

    if scope is not f:
        kinds = _scan(scope)
    if not kinds:
        kinds = _scan(f)

    amts = []
    # ① 最可信：「罚款 / 没收违法所得」后面紧跟的金额
    if f:
        amts = _pen_amounts(scope)
        if not amts and scope is not f:
            amts = _pen_amounts(f)
    # ② 退一步：决定段里出现的任何金额
    if not amts and f:
        src = _fix_num(scope if scope is not f else f)
        for g in _MONEY_RE.finditer(src):
            x = _fmt_money(g.group(0))
            if x not in amts:
                amts.append(x)
        if not amts and scope is not f:
            for g in _MONEY_RE.finditer(_fix_num(f)):
                x = _fmt_money(g.group(0))
                if x not in amts:
                    amts.append(x)
    # ③ 结构化字段兜底（采集期按页面正文抓的金额）
    if not amts:
        for x in (fines or []):
            x = _fmt_money(x)
            if x and x not in amts:
                amts.append(x)
    amts = amts[:limit_fines]

    if "通报批评" in kinds:
        kinds = [k for k in kinds if k != "通报批评"] + ["通报批评"]
    if amts and "罚款" not in kinds:
        kinds.insert(0, "罚款")
    if "罚款" in kinds:
        kinds = [k for k in kinds if k != "罚款"] + ["罚款"]

    # 一条都没解析出来、但标题本身就是「通报 / 曝光」→ 结论就是「公开通报」
    if not kinds and not amts and re.search(r"通报|曝光|下架|评议会|复检", title or ""):
        kinds = ["公开通报"]

    parts = list(kinds)
    if amts:
        parts = [p for p in parts if p != "罚款"] + ["罚款 " + "／".join(amts)]
    return {"kinds": kinds, "fines": amts, "text": "、".join(parts)}


# ---------------------------------------------------------------------------
# 四、对外主函数
# ---------------------------------------------------------------------------

def derive_fields(c, text=None):
    """把「事由 / 处罚」写进案例记录。

    采集期、附件回填期、全文重取期**共用这一套口径**，避免三处各写一份正则。
    `text` 默认为 c["fact"]；调用方在有**全文**时应显式传入全文（决定段常在 900 字之后）。
    """
    t = text if text is not None else (c.get("fact") or "")
    r = extract_reason(t, c.get("title"), c.get("kind"))
    p = extract_penalty(t, c.get("fines"), c.get("title"), c.get("kind"))
    c["reason"] = (r.get("text") or "")[:1500]
    c["reason_mode"] = r.get("mode") or ""
    c["reason_n"] = r.get("n") or 0
    if r.get("subject"):
        c["case_subject"] = r["subject"][:120]
    c["pen"] = (p.get("text") or "")[:240]
    if p.get("kinds"):
        c["pen_kinds"] = p["kinds"]
    return c


def extract_reason(fact, title="", kind="", max_cases=8):
    """返回 dict：

    mode: ``compilation`` 汇编拆解 / ``single`` 单案（或汇编首起）/ ``copy`` 退回复制正文 / ``none``
    text / items / n / truncated / subject / violation
    """
    f = _n(fact)
    if not f:
        return {"mode": "none", "text": "", "items": [], "n": 0,
                "truncated": False, "subject": "", "violation": ""}

    hits = _case_headers(f)
    is_comp = bool(_COMPILATION_TITLE.search(title or ""))

    # ① 汇编：≥2 起，拆开逐起提炼
    # ⚠️ 必须同时满足「标题像汇编」+「小标题过半带『查处』」：
    # 否则行政处罚决定书里的「一、基本情况」「二、违法事实」会被当成案件小标题，
    # 拆出一堆「—行政处罚依据和决定—」这种垃圾（实测黔市监价处〔2024〕3号 被拆成 6 起）。
    if is_comp and len(hits) >= 2 and (hits[-1].start() - hits[0].start()) >= 100:
        blocks = _split_compilation(f, hits)
        head_n = len([b for b in blocks[:12] if "查处" in b[:90]])
        if head_n < max(1, min(len(blocks), 6) // 2):
            blocks = []
        items = []
        for i, b in enumerate(blocks):
            subj, viol, detail, _m = _digest_case(b)
            if not subj and not viol and not detail:
                continue
            items.append({"i": i + 1, "subject": subj, "violation": viol, "detail": detail})
        # 「一、基本情况 / 二、违法事实」这类官方文书分节不会被认成案件小标题
        # （_HDR_SIGNAL 已挡），但万一还是只拆出 1 起，说明不是汇编 → 落到单案路径
        if len(items) >= 2:
            lines = []
            for it in items:
                head = "｜".join([x for x in (it["subject"], it["violation"]) if x])
                if it["detail"]:
                    lines.append(f'{it["i"]}）{head}——{_cut(it["detail"], 160)}')
                else:
                    lines.append(f'{it["i"]}）{head}')
            txt = "\n".join(lines[:max_cases])
            if len(items) > max_cases:
                txt += f'\n……（共 {len(items)} 起，余下见原文）'
            return {"mode": "compilation", "text": txt, "items": items,
                    "n": len(items), "truncated": len(items) > max_cases,
                    "subject": items[0]["subject"], "violation": items[0]["violation"]}

    # ② 汇编首起（页面只放 1 起 / 正文被截断到只剩 1 起）：
    #    此时正文开头是通稿导语，**必须从案件小标题切起**，否则显示的就是导语。
    if is_comp and hits:
        body = _strip_hdr_junk(f[hits[0].start():])
        subj, viol, detail, mode = _digest_case(body)
        if detail or subj:
            head = "｜".join([x for x in (subj, viol) if x])
            txt = (head + "——" + detail) if head else detail
            if len(txt) < 4:
                txt = body
            return {"mode": "single", "text": txt, "items": [], "n": 1,
                    "truncated": not re.search(r"[。！？；：”\"）)]$", f),
                    "subject": subj, "violation": viol, "_how": mode + "+comp1"}

    # ③ 单案事实段
    seg, how = _split_fact(f)
    if seg:
        return {"mode": "single", "text": seg, "items": [], "n": 0,
                "truncated": not re.search(r"[。！？；：”\"）)]$", f),
                "subject": "", "violation": "", "_how": how}

    # ④ 退一步：剥掉通稿导语后再找一次（导语常含「经查」类字样把锚点带偏）
    if is_comp:
        m = hits[0].start() if hits else -1
        if m > 0:
            seg2, how2 = _split_fact(f[m:])
            if seg2:
                return {"mode": "single", "text": seg2, "items": [], "n": 0,
                        "truncated": True, "subject": "", "violation": "",
                        "_how": how2 + "+fromcase"}

    # ⑤ 什么都抽不到：退回复制正文（用户接受「复制」）
    return {"mode": "copy", "text": f, "items": [], "n": 0,
            "truncated": not re.search(r"[。！？；：”\"）)]$", f),
            "subject": "", "violation": ""}


# ---------------------------------------------------------------------------
# 五、自检
# ---------------------------------------------------------------------------

def _selftest(argv):
    import json
    from collections import Counter
    p = os.path.join(HERE, "sources", "cases", "cases.json")
    cases = json.load(open(p, encoding="utf-8"))["cases"]
    mc, pc, lens = Counter(), Counter(), []
    nosub = 0
    for c in cases:
        r = extract_reason(c.get("fact"), c.get("title"), c.get("kind"))
        mc[r["mode"]] += 1
        pen = extract_penalty(c.get("fact"), c.get("fines"), c.get("title"), c.get("kind"))
        pc[pen["text"].split("、")[0] if pen["text"] else "（空）"] += 1
        if r["mode"] != "none" and not (r["subject"] or r["text"]):
            nosub += 1
    print("共", len(cases), "条")
    print("事由抽取模式：", mc.most_common())
    print("处罚解析首项 top：", pc.most_common(14))
    print("处罚为空：", pc.get("（空）", 0))
    print()
    want = [int(x) for x in argv] or [27, 29, 31, 34, 35, 666, 96, 59, 154, 404, 49, 74, 5]
    for i in want:
        if i >= len(cases):
            continue
        c = cases[i]
        r = extract_reason(c.get("fact"), c.get("title"), c.get("kind"))
        pen = extract_penalty(c.get("fact"), c.get("fines"), c.get("title"), c.get("kind"))
        print("=" * 96)
        print(f'[{i}] {c.get("date")} | {c.get("org")} | mode={r["mode"]} n={r["n"]} '
              f'trunc={r["truncated"]}')
        print("T:", (c.get("title") or "")[:80])
        print("事由:", r["text"][:420].replace("\n", " ⏎ "))
        print("处罚:", pen["text"])


if __name__ == "__main__":
    _selftest(sys.argv[1:])
