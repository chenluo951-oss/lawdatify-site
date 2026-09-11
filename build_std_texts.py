#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_std_texts.py —— 把已归档的标准正文接入站内原文库（与 build_texts.py 共用阅读器）。

正文来源（全部为本人存档，仅供本机学习研究）：
  国标：<标准库>/国标（截图+OCR）/<编号>/<编号> 全文（OCR）.txt   ← std_scan.py 三轮 OCR 定稿
  行标：<标准库>/行业标准/<编号> <名称>.pdf                       ← hbba /portal/download 官方公开 PDF，含文字层
  团标：<标准库>/TAF标准/<编号>_<名称>.pdf 或 .txt                 ← TAF 官方公开 PDF

产出：
  kb/texts/s-NN.json                标准正文分片（阅读器按需加载）
  kb/texts/std_index.json           标准目录（由 build_texts.py 并入统一 index.json）
  sources/standards/std_text_ids.json   标准编号 → 原文 id（供 build_standards 加「站内原文」入口）

用法：
    python3 build_std_texts.py            # 全量（有缓存则秒回）
    python3 build_std_texts.py --rebuild  # 忽略缓存重新抽取
"""
import os
import re
import sys
import json
import html
import hashlib
import warnings
import collections

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest as H
import build_texts as BT
import edits as E

STORE = H.STORE
LIB = H.LIB
OUT = os.path.join(HERE, "kb", "texts")
MAP = os.path.join(HERE, "sources", "standards", "std_text_ids.json")
CACHE = os.path.join(HERE, "sources", ".cache", "std")

PART_CHARS = 1_200_000
MIN_CHARS = 1200

# 组 → (目录, 层级, 取文方式)
GROUPS = [
    ("国标（截图+OCR）", "国家标准", "ocr"),
    ("行业标准", "行业标准", "pdf"),
    ("TAF标准", "团体标准", "pdf"),
]

# 从文件名/目录名里抠标准编号：YD_T 6090-2024 / T_TAF_267.8—2025 / GB/T 45123-2024 / AQ 3064.1—2025
CODE_RE = re.compile(
    r"^([A-Z]{1,6}(?:[_\s/][A-Z]{1,6})*)[_\s]*(\d+(?:\.\d+)*)\s*[—\-–_]+\s*(\d{4})")

# 标准正文必须出现的标志性章节（与 harvest.py 的正文校验闸同源）
SECTIONS = ("范围", "规范性引用文件", "术语和定义")

# 页眉里的标准号：实时编号（GB/T 35273-2020）与占位编号（YD/T XXXXX—XXXX）
_CODE_NUM = r"[A-Z]{1,6}\s*[/_ ]?\s*[A-Z]{0,4}\s*[X\d]{2,}(?:\.\d+)*\s*[—–\-]\s*[X\d]{4}"
CODEHDR = re.compile("^" + _CODE_NUM)
# 占位编号：字母全在、数字全是 X —— 真实标准不会有这种写法，可全局清除
PLACEHOLDER_CODE = re.compile(r"[A-Z]{1,6}\s*/\s*[A-Z]{1,4}\s*X{2,}\s*(?:[—–\-]\s*X{2,4})?\s*")
PLACEHOLDER_DATE = re.compile(r"^X{2,4}\s*[-–—]\s*X{1,2}\s*[-–—]\s*X{1,2}\s*(?:发布|实施)$")
# 页眉位：编号后面紧跟前言/引言/目次/附录/条号（排除「GB/T 40660—2021信息安全技术…」这类参考文献行）
CODEHDR_HEAD = re.compile("^" + _CODE_NUM + r"\s*(?:[IVXLC]{1,5}\s*)?"
                          r"(?=前\s*言|引\s*言|目\s*次|附\s*录|\d{1,2}(?:\.\d+){0,3}\s*[\u4e00-\u9fff])")

# 标准 PDF 的页眉页脚：编号行、罗马页码、纯数字页、发布日期
PAGE_JUNK = re.compile(
    r"^\s*(?:[IVXLC]{1,5}|[0-9]{1,4}|"
    r"[A-Z]{1,4}(?:[/_\s][A-Z]{1,4})*\s*\d+(?:\.\d+)*\s*[—\-–]\s*\d{4}|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*(?:发布|实施))\s*$")


def ncode(s):
    """标准编号归一：去所有分隔符与大小写差异 → GBT451232024。"""
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def code_of(s):
    m = CODE_RE.match((s or "").strip())
    if not m:
        return ""
    return ncode(m.group(1) + m.group(2) + m.group(3))


def std_clean(t, code, name):
    """标准正文的追加清洗：去掉重复页眉（标准号/标准名）、校次号、孤立页码。"""
    out = []
    for ln in (t or "").split("\n"):
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if PAGE_JUNK.match(s):
            continue
        # 报批稿/送审稿页眉里的占位标准号（如 YD/T XXXXX—XXXX）：出现在任何位置都清掉
        s = PLACEHOLDER_CODE.sub(" ", s).strip()
        s = PLACEHOLDER_DATE.sub("", s).strip()
        if not s:
            continue
        # 真实标准号出现在页眉位（后面紧跟前言/引言/目次/附录/条号）时剔除
        s = CODEHDR_HEAD.sub("", s)
        # 「II前 言」「7范围」这类页码与标题挤在一起的残留
        mh = re.match(r"^(?:[IVXLC]{1,5}|\d{1,3})(?=前\s*言|引\s*言|目\s*次|附\s*录)", s)
        if mh:
            s = s[mh.end():].strip()
        elif len(s) <= 40:
            mh = re.match(r"^(?:[IVXLC]{1,5}|\d{1,3})(?=[\u4e00-\u9fff])", s)
            if mh:
                s = s[mh.end():]
        if not s:
            continue
        flat = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", s)
        if flat and flat == re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", code or ""):
            continue
        if flat and name and flat == re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", name):
            continue
        out.append(s)
    t = "\n".join(out)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


_FITZ = None


# ══════════════════ 封面与目次的抽取（构建期做，浏览器端只负责渲染）══════════════════
# PDF 抽出的封面往往把 ICS / 标准类别 / 中英文名称挤成一行，例如：
#   「ICS 33.050 M 30移动智能终端应用软件安全与质量要求Implementation Guidance of ...」
# 与其在页面里用正则硬猜，不如构建时解析成结构化字段，渲染端直接排版。
ICS_RE = re.compile(r"\bICS\s*([0-9]+(?:\.[0-9]+)*)")
CCS_NUM_RE = re.compile(r"\bICS\s*[0-9.]+\s*(?:CCS\s*)?([A-Z]{1,3}\s?\d{1,3}(?:\.\d+)*)")
CCS_EXP_RE = re.compile(r"\bCCS\s*([A-Z]{1,3}\s?\d{1,3}(?:\.\d+)*)")
CLS_WORDS = ("国家标准", "行业标准", "团体标准", "地方标准", "企业标准")
CLS_RE = re.compile(r"((?:中华人民共和国)?[^，。；\s]{0,10}(?:%s))" % "|".join(CLS_WORDS))
CODE_LINE_RE = re.compile(r"^[A-Z]{1,6}(?:[/\s][A-Z]{1,4})?\s*\d+(?:\.\d+)*\s*[—–\-]\s*\d{4}$")
DATE_RE = re.compile(r"(\d{4}\s*[-\u5e74/]\s*\d{1,2}\s*[-\u6708/]\s*\d{1,2}\s*\u65e5?)\s*(发布|实施)")
ORG_RE = re.compile(r"^([\u4e00-\u9fff]{2,22}(?:局|部|委员会|协会|联盟|总局|办公厅|"
                    r"研究院|集团|中心|联合会|学会|标准化技术委员会))\s*(?:发布|提出|归口)?$")
EN_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9 ,\-'\u2019().]{18,}")
TOC_HEAD_RE = re.compile(r"^\s*目\s*次\s*$|^\s*目\s*录\s*$")
# 标题里必须允许「.」：条款号本身是 4.1 / 4.1.2，若把「.」排除在标题之外，
# 正则只能从条款号中间起匹配，目次会退化成「1应用软件管理」（丢掉「4.」）。
# 引导线要求连续 3 个以上点号，所以标题里的单点/双点（4.1 / 4.1.2）不会误当引导线。
TOC_SCAN = re.compile(r"(?P<t>[^\n]{2,90}?)"
                      r"(?:[.\u00b7\u2026\u22ef]{3,}\s*)(?P<p>[IVXLC]{1,5}|\d{1,4})")
# 目次里引导线/页码被吃掉时的兜底：只抠「条号 + 标题」
TOC_NUM_TITLE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){0,3})\s?"
                           r"([\u4e00-\u9fff][\u4e00-\u9fff\u3001\uff0cA-Za-z·]{1,28})")
FRONT_WORDS = ("前言", "引言", "参考文献", "索引", "特别声明")

# 结构断行的标记：先打标记，最后再把「PDF 折行」与「结构换行」分开处理
BRK = "\u0001"
CJK = "\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
LI_MARK = re.compile(r"(?<=[。；：])\s*(?=(?:[a-z]|[1-9]\d?)\s*[)）](?=\s*\S))")
DASH_MARK = re.compile(r"(?<=[。；：])\s*(?=[—–－]{1,2}\s?\S)")
NOTE_MARK = re.compile(r"(?<=[。；：])\s*(?=(?:注|示例)\s*\d*\s*[:：]|注\s*\d*\s*(?=\S))")
CAP_MARK = re.compile(r"(?<=[。；：])\s*(?=(?:表|图)\s*\d+\s)")
CLAUSE_MARK = re.compile(r"(?<=[。；])\s*(?=\d{1,2}(?:\.\d{1,2}){1,3}\s?[\u4e00-\u9fff])")


def _same_title(a, b):
    fa = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", a or "")
    fb = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", b or "")
    return bool(fa) and bool(fb) and (fa == fb or (len(fa) > 8 and fa in fb) or (len(fb) > 8 and fb in fa))


def _flex(s):
    """标题匹配用的宽松形式：短标题允许字与字之间夹空白（PDF 常把「前 言」排成「前　言」）。"""
    s = s or ""
    if len(s) <= 14:
        return r"\s*".join(re.escape(c) for c in s)
    return re.escape(s).replace("\\ ", r"\s*")


def _clean_name(s):
    s = re.sub(r"\s+", " ", (s or "").replace("　", " ")).strip()
    # 汉字之间的空白是竖排/字距造成的，去掉；英文之间保留一个空格
    return re.sub(r"(?<=[\u4e00-\u9fff\u3001\uff0c\uff08\uff09])\s+(?=[\u4e00-\u9fff\u3001\uff0c\uff08\uff09])", "", s)


def _join_wrap(prev, nxt):
    """PDF 折行拼接：汉字之间直接相连，其余情况补一个空格。"""
    if not prev:
        return nxt
    if not nxt:
        return prev
    if re.search("[%s]$" % CJK, prev) and re.match("[%s]" % CJK, nxt):
        return prev + nxt
    if prev.endswith("-"):
        return prev[:-1] + nxt
    return prev + " " + nxt


def reflow_std(t, toc):
    """把「条号 + 标题 + 正文 + 列项」挤在一行的标准正文重排成段落。

    核心手法：用目次里的条款标题当权威词表，在正文里定位标题边界再断行；
    目次覆盖不到的地方，再用句末标点后的条号/列项标记兜底。
    """
    t = t.replace(BRK, "")
    heads = []
    for e in (toc or []):
        s = _clean_name(e.get("t") or "")
        if not s:
            continue
        if s.replace(" ", "") in FRONT_WORDS:
            heads.append((s, s))
            continue
        m = re.match(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s*(.+)$", s)
        if m and re.search("[%s]" % CJK, m.group(2)):
            heads.append((m.group(1), m.group(2)))
    # 长标题优先，避免短标题先抢掉位置
    for num, title in sorted(heads, key=lambda x: -len(x[1])):
        if num == title:                                   # 前言 / 引言 这类无编号的
            pat = re.compile(r"(?<![%s])(%s)" % (CJK, _flex(title)))
        else:
            pat = re.compile(r"(?<![\d.])(%s\s*%s)" % (re.escape(num), _flex(title)))
        t = pat.sub(lambda m: BRK + m.group(1) + BRK, t)

    # 兜底：句末标点后的条号 / 列项 / 注 / 表图题
    for rx in (CLAUSE_MARK, LI_MARK, DASH_MARK, NOTE_MARK, CAP_MARK):
        t = rx.sub(BRK, t)

    # 折行拼回：按行处理，行内多余空白归一
    out = []
    for ln in t.split("\n"):
        ln = re.sub(r"[ \t\u3000]{2,}", " ", ln).strip()
        if not ln:
            continue
        if ln.endswith(BRK):
            out.append(ln)
            continue
        if out and not out[-1].endswith(BRK) and BRK not in ln:
            out[-1] = _join_wrap(out[-1], ln)
        else:
            out.append(ln)
    text = "\n".join(out)
    text = text.replace(BRK, "\n\n")
    pars = [re.sub(r"\s+", " ", p).strip() for p in text.split("\n\n")]
    return "\n\n".join(p for p in pars if p)


def split_cover(t, code, name):
    """抽取封面信息与目次，并把「封面区 / 目次区」整段从正文里摘掉。

    做法：先在头部 90 行里定位三个锚点——目次、前言/引言、第一条正文；
    锚点之前就是封面区，整段摘掉（官方发布稿的封面也确实是独立一页）。
    返回 (正文, cover, toc)。
    """
    lines = t.split("\n")
    head_n = min(len(lines), 110)
    cover = {}

    def find(rx, upto=head_n):
        for i in range(upto):
            if rx.search(lines[i].strip()):
                return i
        return None

    toc_from = find(re.compile(r"目\s*[次录]|[次录]\s*目"))
    if toc_from is None:
        # OCR 常把「目次」竖排/倒序拆成相邻两行
        for i in range(head_n - 1):
            a, b = lines[i].strip(), lines[i + 1].strip()
            if (a, b) in (("次", "目"), ("目", "次"), ("录", "目"), ("目", "录")):
                toc_from = i
                break
    front_from = find(re.compile(r"^(前\s*言|引\s*言)[\s.\u00b7\u2026\u22ef\u2022]*$"))
    body_from = find(re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,3}\s*[\u4e00-\u9fff]"))
    anchors = [x for x in (toc_from, front_from, body_from) if x is not None]
    anchor = min(anchors) if anchors else None

    region = lines[:anchor] if anchor is not None else lines[:min(len(lines), 30)]
    head_text = "\n".join(region)

    # ---- 从封面区里解析字段 ----
    m = CLS_RE.search(head_text)
    if m:
        cover["cls"] = m.group(1)
    else:
        for i, ln in enumerate(region):
            if re.fullmatch(r"[国行团地企]", ln.strip() or ""):
                seq, j = [], i
                while j < len(region) and re.fullmatch(r"[\u4e00-\u9fff]", region[j].strip() or ""):
                    seq.append(region[j].strip())
                    j += 1
                joined = "".join(seq)
                if len(seq) >= 2 and any(joined.endswith(w) for w in CLS_WORDS):
                    cover["cls"] = joined
                break
    m = ICS_RE.search(head_text)
    if m:
        cover["ics"] = m.group(1)
        mc = CCS_EXP_RE.search(head_text) or CCS_NUM_RE.search(head_text)
        if mc:
            cover["ccs"] = re.sub(r"\s+", " ", mc.group(1)).strip()
    m = re.search(r"^(%s)$" % CODE_LINE_RE.pattern.strip("^$"), head_text, re.M)
    if m:
        cover["code"] = re.sub(r"\s+", "", m.group(1))
    for m in DATE_RE.finditer(head_text):
        key = "pubdate" if m.group(2) == "发布" else "impldate"
        cover.setdefault(key, re.sub(r"\s+", "", m.group(1)))
    for ln in region:
        s_ = ln.strip()
        if len(s_) <= 26:
            mo = ORG_RE.match(s_)
            if mo and not re.search(r"ICS|CCS|\d{4}", s_):
                cover.setdefault("issuer", mo.group(1))
    best = ""
    for ln in region[:40]:
        for cand in EN_NAME_RE.findall(ln):
            if len(cand.split()) >= 4 and len(cand) > len(best):
                best = cand
    if best:
        cover["en"] = _clean_name(best)

    # ---- 目次区 ----
    toc, toc_to, fallback = [], None, False
    if toc_from is not None:
        j, last = toc_from, None
        while j < min(len(lines), toc_from + 130):
            s_ = lines[j].strip()
            if not s_:
                j += 1
                continue
            got = False
            for m in TOC_SCAN.finditer(s_):
                tt = _clean_name(m.group("t"))
                bare = tt.replace(" ", "")
                if bare in ("目次", "目录") or _same_title(tt, name):
                    got = True
                    continue
                if len(tt) <= 60 and (bare in FRONT_WORDS
                                      or re.match(r"^\d{1,2}(?:\.\d{1,2}){0,3}", tt)
                                      or re.search("[%s]" % CJK, tt)):
                    toc.append({"t": tt, "p": m.group("p")})
                    got = True
            if got:
                last = j
                j += 1
                continue
            if len(toc) >= 3:
                toc_to = last + 1 if last is not None else j
                break
            j += 1
        if toc_to is None:
            # 用「最后一条目次所在行」定界，避免把目次后面的正文一起摘掉
            toc_to = (last + 1) if last is not None else min(len(lines), toc_from + 1)
        if len(toc) < 3:
            # 兜底：引导线或页码被 OCR 吃掉时，只从目次区里抠「条号 + 标题」，供正文断行用。
            # 关键约束——目次条目都很短且连续，遇到长行或连续 3 行不像条目就收手，
            # 否则会把正文里的条标题也当成目次、连带把正文摘掉。
            toc, last, miss = [], toc_from, 0
            for k in range(toc_from, min(len(lines), toc_from + 90)):
                s_ = lines[k].strip()
                if not s_:
                    continue
                if len(s_) > 46:
                    break
                hits = [(n_, _clean_name(t_)) for n_, t_ in TOC_NUM_TITLE.findall(s_)]
                hits = [(n_, t_) for n_, t_ in hits if 1 <= len(t_) <= 30]
                if hits:
                    for n_, t_ in hits:
                        toc.append({"t": n_ + t_, "p": ""})
                    last, miss = k, 0
                else:
                    miss += 1
                    if toc and miss >= 3:
                        break
            if len(toc) >= 3:
                toc_to = last + 1
                fallback = True
            else:
                toc = []

    # ---- 摘除封面区 + 目次区 ----
    # 封面：只摘短行（超长行常是 OCR 把整页挤成一行，里面混着正文）
    drop = {k for k in range(0, anchor or 0) if len(lines[k].strip()) <= 140}
    # 目次：只有「引导线 + 页码」解析成功的目录才整段摘除；
    # 靠兜底抠出来的条目只用来给正文断行，不据此删行（否则会把正文条标题一起删掉）
    if toc_from is not None and toc and not fallback:
        drop.update(range(toc_from, toc_to or toc_from + 1))
    # 头部残留的引导线行（OCR 常把「目次」打散成「…前言⋯」「5.1xxx•」这类碎片）
    hi = min(len(lines), (toc_from + 110) if toc_from is not None else (anchor or 0))
    for k in range(hi):
        s_ = lines[k].strip()
        if not s_:
            continue
        if re.fullmatch(r"[\s.\u00b7\u2026\u22ef\u2022\u3001\uff0c]+", s_) or \
                (len(s_) <= 42 and len(re.findall(r"[.\u00b7\u2026\u22ef\u2022]", s_)) >= 1):
            drop.add(k)

    cover_ok = len([k for k in ("ics", "ccs", "cls", "code", "en", "issuer", "pubdate")
                    if k in cover]) >= 3
    if not cover_ok:
        cover = {}
        drop = set()
        if toc_from is not None and toc:
            drop.update(range(toc_from, toc_to if toc_to else min(len(lines), toc_from + 130)))
    elif "cn" not in cover:
        cover["cn"] = name

    if toc_from is not None and toc and len(drop) > 40 and \
            len(drop) > max(60, len(lines) * 0.5):
        # 安全阀：摘得超过全文一半说明把正文当目录了 —— 只保留封面摘除
        drop = {k for k in range(0, anchor or 0) if len(lines[k].strip()) <= 140}
    if toc_from is not None and toc:
        span = (toc_to or toc_from) - toc_from
        if span > max(30, 4 * len(toc)):
            # 目录条数远小于跨度 → 落进了正文，撤销目录摘除（标题仍供重排断行）
            drop = {k for k in range(0, anchor or 0) if len(lines[k].strip()) <= 140}
    body = "\n".join(l for k, l in enumerate(lines) if k not in drop)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body, cover, toc




def _fitz():
    """取 PyMuPDF。当前解释器没装时，回退到本机 venv 的 site-packages
    （两个环境同为 3.13，编译扩展可通用），免得构建链因为换了个 python 就抽不出 PDF。"""
    global _FITZ
    if _FITZ is not None:
        return _FITZ
    try:
        import fitz as m
        _FITZ = m
        return m
    except ImportError:
        pass
    import glob
    import sys as _s
    for sp in sorted(glob.glob(os.path.expanduser(
            "~/.workbuddy/binaries/python/envs/*/lib/python*/site-packages"))):
        if os.path.isdir(os.path.join(sp, "fitz")):
            _s.path.append(sp)
            try:
                import fitz as m
                _FITZ = m
                return m
            except ImportError:
                _s.path.pop()
    raise ImportError("未找到 PyMuPDF（fitz），无法抽取 PDF 文字层")


def pdf_text(path):
    fitz = _fitz()
    d = fitz.open(path)
    try:
        return "".join(p.get_text() for p in d)
    finally:
        d.close()


def cached_text(path, rebuild=False):
    """抽取结果缓存。key 必须包含 mtime+size——只按路径做 key 会让 OCR 重写后的
    同名 .txt/.pdf 继续命中旧缓存，表现为「明明补过 OCR 却仍判为损坏」。"""
    os.makedirs(CACHE, exist_ok=True)
    try:
        st = os.stat(path)
        sig = "%s|%d|%d" % (path, st.st_size, int(st.st_mtime))
    except OSError:
        sig = path
    key = hashlib.md5(sig.encode()).hexdigest()[:16]
    cp = os.path.join(CACHE, key + ".txt")
    if os.path.exists(cp) and not rebuild:
        return open(cp, encoding="utf-8").read()
    ext = os.path.splitext(path)[1].lower()
    try:
        raw = pdf_text(path) if ext == ".pdf" else open(path, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        print("  抽取失败 %s：%s" % (os.path.basename(path), e))
        return ""
    open(cp, "w", encoding="utf-8").write(raw)
    return raw


def collect():
    """扫描标准库，返回 [{'code','file','level','raw_name'}]，同编号优先 .txt（免抽取）。"""
    seen = {}
    for sub, level, mode in GROUPS:
        d = os.path.join(STORE, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            full = os.path.join(d, name)
            if mode == "ocr":
                if not os.path.isdir(full):
                    continue
                txt = [f for f in os.listdir(full) if f.endswith(".txt") and "OCR" in f]
                if not txt:
                    continue
                p = os.path.join(full, txt[0])
                code = code_of(name)
                key = (code or ncode(name), "国家标准")
                seen.setdefault(key, {"code": code, "file": p, "level": level,
                                      "raw_name": name, "sub": sub})
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext not in (".pdf", ".txt"):
                    continue
                stem = os.path.splitext(name)[0]
                code = code_of(stem)
                key = (code or ncode(stem), level)
                cur = seen.get(key)
                # 同编号：.txt 优先（已是文字层，无需再抽 PDF）
                if cur is None or (ext == ".txt" and cur["file"].endswith(".pdf")):
                    seen[key] = {"code": code, "file": full, "level": level,
                                 "raw_name": stem, "sub": sub}
    return list(seen.values())


def lib_names():
    """标准编号 → (名称, 条目库字段)，用于把文件名的简写换成规范中文名。"""
    lib = H.load_json(LIB, {"items": []})
    out = {}
    for it in lib.get("items", []):
        c = ncode(it.get("code"))
        if c and it.get("level") in BT.STD_LEVELS:
            out[c] = it
    return out


def build(rebuild=False, quiet=False):
    os.makedirs(OUT, exist_ok=True)
    rows = collect()
    names = lib_names()
    kept, idmap, dropped = [], {}, []
    for r in rows:
        raw = cached_text(r["file"], rebuild)
        if not raw:
            dropped.append((r["raw_name"], "抽取为空"))
            continue
        t = std_clean(BT.clean(raw), r["code"], r["raw_name"])
        t = E.apply_rules("std", ncode(r["code"]), t)
        it = names.get(ncode(r["code"])) or {}
        name = (it.get("name")
                or re.sub(r"^[A-Z_/\s\d\.\-—–]+", "", r["raw_name"]).strip()
                or r["raw_name"])
        t, cover, toc = split_cover(t, r["code"] or it.get("code") or "", name)
        t = reflow_std(t, toc)
        if len(t) < MIN_CHARS:
            dropped.append((r["raw_name"], "篇幅不足 %d 字" % len(t)))
            continue
        # 正文校验闸：标准必须能检出「范围 / 规范性引用文件 / 术语和定义」
        if not any(s in t[:20000] for s in SECTIONS):
            dropped.append((r["raw_name"], "未检出标准正文特征（可能是版权页/目次）"))
            continue
        qok, why = BT.quality_ok(t)
        if not qok:
            dropped.append((r["raw_name"], why))
            continue
        key = "STD::" + (r["code"] or ncode(r["raw_name"]))
        tid = hashlib.md5(key.encode()).hexdigest()[:10]
        rec = {"id": tid, "kind": "std", "code": cover.get("code") or r["code"] or it.get("code") or "",
               "name": name, "level": r["level"],
               "issuer": it.get("issuer") or cover.get("issuer") or "",
               "pub": it.get("pub") or cover.get("pubdate") or "",
               "impl": it.get("impl") or cover.get("impldate") or "",
               "status": it.get("status") or "",
               "url": it.get("url") or "", "chars": len(t), "src": r["sub"],
               "cover": cover, "toc": toc,
               "_text": t}
        kept.append(rec)
        idmap[key] = tid
        if r["code"]:
            idmap[ncode(r["code"])] = tid

    kept.sort(key=lambda x: (x["level"], x["code"], x["name"]))
    part, acc = 1, 0
    for x in kept:
        if acc and acc + x["chars"] > PART_CHARS:
            part += 1
            acc = 0
        x["part"] = part
        acc += x["chars"]

    for f in os.listdir(OUT):
        if re.fullmatch(r"s-\d+\.json", f):
            os.remove(os.path.join(OUT, f))
    parts = collections.defaultdict(dict)
    for x in kept:
        parts[x["part"]][x["id"]] = x.pop("_text")
    for p, d in parts.items():
        json.dump(d, open(os.path.join(OUT, "s-%02d.json" % p), "w", encoding="utf-8"),
                  ensure_ascii=False)

    json.dump({"_meta": {"count": len(kept), "parts": len(parts),
                         "note": "本人存档的标准正文（OCR 定稿 / 官方公开 PDF 文字层），仅供本机学习研究。"},
               "items": kept},
              open(os.path.join(OUT, "std_index.json"), "w", encoding="utf-8"), ensure_ascii=False)
    H.save_json(MAP, idmap)

    by_level = collections.Counter(x["level"] for x in kept)
    total = sum(x["chars"] for x in kept)
    if not quiet:
        print("标准原文库：%d 部 / %d 字 / %d 片" % (len(kept), total, len(parts)))
        for k, v in by_level.most_common():
            print("   %s %d 部" % (k, v))
        if dropped:
            print("未收录 %d 部，示例：%s"
                  % (len(dropped), "；".join("%s(%s)" % (n[:22], r) for n, r in dropped[:6])))
    return kept, len(parts)


if __name__ == "__main__":
    build(rebuild="--rebuild" in sys.argv)
