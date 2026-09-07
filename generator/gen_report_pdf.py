#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《合规资讯简报》PDF 专业排版引擎 v3
====================================
设计规范（律所/咨询报告风格）：
  - 大标题（报告主标题/一级章节标题）：方正书宋（模拟标宋效果）
  - 小标题（二/三级标题）：汉仪旗黑（视觉上替代微软雅黑）
  - 正文：汉仪楷体，1.5 倍行距，首行缩进两字符
  - 页眉页脚 + “第 X 页 / 共 Y 页”
  - 复杂关系用流程图 / 热力矩阵图呈现，图注在图下方且与图绑定不分页
  - 字体子集化：收集【全部界面文字+正文+符号】，杜绝缺字方框

v3 修复：
  1. [P0] 子集字体漏字 —— collect_all_text 覆盖全部 UI 字符串与符号
  2. [P0] 图注与图跨页分离 —— KeepTogether([图, 图注])
  3. [P0] 标题孤行 —— h1/h2/h3/meta 全部 keepWithNext
  4. [P1] 表格列宽优化 + 日期简写，避免断词
  5. [P1] 条目间细分隔线、间距体系统一(3/6/10/16)、h2/h3 层级差拉大
  6. [P1] 去除无效 <b> 假加粗，改用字体/颜色表达层级
  7. [P1] 符号字形可用性检测与自动回退（◆/▍/■ 缺失时自动替换）
  8. [P1] 列表悬挂缩进、CJK 换行声明、寡行/孤行控制
"""
import os, math
from fontTools.ttLib import TTFont as FTFont
from fontTools.subset import Subsetter, Options

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, KeepTogether, CondPageBreak)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

# ============================================================ 常量
OUT_DIR = os.environ.get("CBR_OUT_DIR") or "/Users/luochen/Desktop/合规资讯简报"
TMP_FONT_DIR = "/tmp/cbr_fonts"
DATE_STR = "2026年8月21日（星期五）"
PAGE_W, PAGE_H = A4
M_L, M_R, M_T, M_B = 2.2*cm, 2.2*cm, 2.0*cm, 2.0*cm
CONTENT_W = PAGE_W - M_L - M_R
DOC_TITLE = "合规资讯简报"
HEADER_TEXT = f"{DOC_TITLE} · 每日监管与合规动态"
FOOTER_NOTE = "— 本简报由自动化任务每日生成，内容基于公开网络信息检索整理，仅供参考 —"
SUBTITLE = "— 六大合规领域动态 · 监管通报速览 · 朴朴超市业务专题 —"

# 间距体系（统一标尺）
SP_XS, SP_S, SP_M, SP_L = 3, 6, 10, 16

FONTS = {
    "song":  {"path": "/Applications/wpsoffice.app/Contents/Resources/office6/fonts/FZSSK.ttf",
              "name": "SongBiao", "fontNumber": 0},
    "kaiti": {"path": "/Applications/wpsoffice.app/Contents/Resources/office6/fonts/HYKaiTiJ.ttf",
              "name": "KaiTi", "fontNumber": 0},
    "qihei": {"path": "/Applications/wpsoffice.app/Contents/Resources/office6/fonts/HYQiHei-55J.ttf",
              "name": "QiHei", "fontNumber": 0},
    # 真·加粗黑体（小标题用）：华文黑体 Medium，子字体索引 1 = 简体 SC
    "heiti": {"path": "/System/Library/Fonts/STHeiti Medium.ttc",
              "name": "HeitiMed", "fontNumber": 1},
    # 真·加粗标宋（一级标题用）：系统宋体 Bold 字重 700，子字体索引 1 = SC Bold
    "songb": {"path": "/System/Library/Fonts/Supplemental/Songti.ttc",
              "name": "SongBold", "fontNumber": 1},
}

# 云端渲染字体覆盖（GitHub Actions 等 Linux 环境没有 WPS/macOS 字体）：
# 设 CBR_FONT_DIR 指向含 song.ttf / kaiti.ttf / qihei.ttf / heiti.ttf / songb.ttf 的目录即可整体替换；
# 也可用 CBR_FONT_SONG / CBR_FONT_KAITI / CBR_FONT_QIHEI / CBR_FONT_HEITI / CBR_FONT_SONGB 逐个指定。
# 推荐开源字体：Noto Sans SC / Noto Serif SC（SIL OFL，可自由分发）。
_FONT_DIR = os.environ.get("CBR_FONT_DIR")
if _FONT_DIR:
    _dir_map = {
        "song": "song.ttf", "kaiti": "kaiti.ttf", "qihei": "qihei.ttf",
        "heiti": "heiti.ttf", "songb": "songb.ttf",
    }
    for _k, _fn in _dir_map.items():
        _p = os.path.join(_FONT_DIR, _fn)
        if os.path.exists(_p):
            FONTS[_k] = {"path": _p, "name": FONTS[_k]["name"], "fontNumber": 0}
for _k, _env in (("song", "CBR_FONT_SONG"), ("kaiti", "CBR_FONT_KAITI"),
                 ("qihei", "CBR_FONT_QIHEI"), ("heiti", "CBR_FONT_HEITI"),
                 ("songb", "CBR_FONT_SONGB")):
    _p = os.environ.get(_env)
    if _p and os.path.exists(_p):
        FONTS[_k] = {"path": _p, "name": FONTS[_k]["name"], "fontNumber": 0}

# 配色（投行研报风格：深蓝主色 + 灰辅色 + 仅风险关键点用红/橙/绿，克制冷静）
NAVY   = colors.HexColor("#1F3B63")
NAVY2  = colors.HexColor("#2E5E8C")
BLUE   = colors.HexColor("#3A6B8F")
GOLD   = colors.HexColor("#B08D57")
INK    = colors.HexColor("#2B2B2B")
GRAY   = colors.HexColor("#6B7280")
LGRAY  = colors.HexColor("#9AA3AF")
RED    = colors.HexColor("#A93B33")   # 高（统一为低饱和深砖红）
ORANGE = colors.HexColor("#B0652C")   # 中高
AMBER  = colors.HexColor("#B0862E")   # 中（统一为低饱和深赭黄）
GREEN  = colors.HexColor("#4C7A59")   # 低（统一为低饱和深松绿）
BG_H1  = colors.HexColor("#EEF3F8")   # 一级标题条浅蓝底
BG_ANA = colors.HexColor("#F0F4F9")   # 解读块浅灰蓝底（原浅金）
EDGE_ANA = colors.HexColor("#C9D6E4") # 解读块灰蓝边（原金棕）
ZEBRA  = colors.HexColor("#EDF1F6")
HAIRLINE = colors.HexColor("#E3E7ED")
ANA_TXT = colors.HexColor("#44546A")  # 解读正文深灰蓝（原金棕）
BG_KEY = colors.HexColor("#F2F6FA")   # 核心观点框底（原 #F7F9FC，加深以拉开与白页对比）

# ============================================================ 字形可用性检测
def _font_cmap(path, fontNumber=0):
    f = FTFont(path, fontNumber=fontNumber, lazy=True)
    cmap = set(f.getBestCmap().keys())
    f.close()
    return cmap

CMAPS = {k: _font_cmap(cfg["path"], cfg["fontNumber"]) for k, cfg in FONTS.items()}

def pick_symbol(candidates, fontkey):
    """从候选符号中选第一个字体里真实存在的，避免 .notdef 方框"""
    for s in candidates:
        if all(ord(ch) in CMAPS[fontkey] for ch in s):
            return s
    return candidates[-1]

BULLET = pick_symbol(["◆", "■", "●", "•"], "heiti")      # h2 领域符号
MARK   = pick_symbol(["▍", "▎", "▏", "■"], "heiti")      # h3 条目标记
SQUARE = pick_symbol(["■", "●", "▪", "◆"], "heiti")      # 图例色块（备用）
AR_DOWN = pick_symbol(["↓", "▼", "v"], "heiti")          # 流程图向下箭头
AR_L = pick_symbol(["↙", "←", "<"], "heiti")             # 流程图左下箭头
AR_R = pick_symbol(["↘", "→", ">"], "heiti")             # 流程图右下箭头

# ============================================================ 字体子集化
UI_TEXTS = [
    DOC_TITLE, DATE_STR, HEADER_TEXT, FOOTER_NOTE, SUBTITLE,
    "目　录", "一、今日重点速览", "二、六大合规领域动态", "三、监管通报与处罚速览",
    "四、朴朴超市业务专题分析", "五、前瞻合规风险提示",
    "时间", "监管机构", "涉及对象", "违规事由", "处置措施",
    "图1：价格欺诈认定与责任链条",
    "图2：监管执法处置流程（通报—整改—复查—处置—公示）",
    "图3：朴朴超市合规风险热力矩阵（按风险主题 × 业务环节）",
    "图4：福建食品安全“政企检”协同预警机制架构",
    "资料来源：依据公开监管通报与处罚决定书整理，详见各条原文链接",
    "资料来源：福建省市场监管局“政企检”协同预警机制公开信息",
    "说明：本板块聚焦与朴朴超市（生鲜电商/前置仓即时零售）业务直接相关的监管动态，逐项评估合规风险等级（高/中/低）并给出应对建议。",
    "解读：", "应对建议：", "【内容】", "涉及业务环节：", "影响分析：",
    "【风险等级：】", "高", "中高", "中", "低", "暂不涉及",
    "第  页 / 共  页", "0123456789",
    "本期导读：领域动态 条 · 通报处罚 起 · 朴朴专题 项 · 前瞻提示 ",
    BULLET, MARK, SQUARE, AR_DOWN, AR_L, AR_R, "　",
    "日常监测 · 专项行动", "发现问题线索", "责令整改 · 约谈告诫", "整改复查",
    "合格 → 结案销号", "不合格 → 通报 · 下架 · 罚款", "处罚信息公示 · 纳入信用记录 · 典型案例发布",
    "朴朴超市 · 法务合规部", "守护合规底线 · 支撑业务决策",
    "核心观点",
    "近 3 期回顾",
    "覆盖口径：六大合规领域公开监管动态与通报处罚",
    "审核与签发：朴朴超市法务合规部",
    "信息来源与免责声明",
    "一、信息来源：本简报内容基于公开网络检索整理的监管机构官方网站通报、公告、处罚决定书及权威媒体报道，各条动态均附原文链接，便于溯源核验。",
    "二、用途限制：本简报仅供朴朴超市内部合规参考，不构成法律意见或决策依据；据此采取具体合规措施前，请咨询法务或外部专业律师。",
    "三、时效性：监管政策与执法动态更新较快，本简报截至生成时点整理，不排除后续修订或新发文件导致内容变化，请以最新官方发布为准。",
    "四、版权：本简报由自动化任务生成，引用内容著作权归原发布机构所有。",
    "虚构“划线价”：团购37.9元 / 假原价570元", "制造巨大优惠假象", "认定构成价格欺诈",
    "法律依据：《明码标价和禁止价格欺诈规定》第19条",
    "行政责任：责令改正 · 没收违法所得 · 罚款", "民事责任：消费者可主张“退一赔三”",
    "合规要点：划线价/原价对比须有真实成交记录支撑，禁止虚构原价",
    "福建省市场监管局（统筹协调 · 牵头组织）", "省产品质量检验研究院\n技术支撑 · 风险研判",
    "朴朴电商（签约企业）\n品控资源 · 数据共享", "永辉超市等企业\n联合参与 · 协同共治",
    "风险防控关口前移至食品入市销售之前\n“一品一码”溯源 · 品控数据对监管透明共享",
    "资料来源：依据公开监管通报与处罚决定书整理，详见各条原文链接",
    "资料来源：福建省市场监管局“政企检”协同预警机制公开信息",
]

# 全局字体注册名（subset_fonts 每次调用后更新，供内联 font 标签 / setFont 使用）
# 用全局变量而非硬编码，避免同一进程多次生成报告时 reportlab 字体缓存冲突
HEITI = "HeitiMed"
KAITI = "KaiTi"
QIHEI = "QiHei"

def subset_fonts(all_text, suffix=""):
    global HEITI, KAITI, QIHEI
    os.makedirs(TMP_FONT_DIR, exist_ok=True)
    extra = ("，。、；：？！（）《》〈〉【】“”‘’—…·％．／｜﹒×"
             + "".join(chr(i) for i in range(32, 127)))
    text = all_text + extra + "".join(UI_TEXTS)
    charset = sorted(set(text))
    registered = {}
    for key, cfg in FONTS.items():
        src, name, fn = cfg["path"], cfg["name"], cfg["fontNumber"]
        out = os.path.join(TMP_FONT_DIR, f"{key}{suffix}.ttf")
        f = FTFont(src, fontNumber=fn)
        opt = Options()
        opt.layout_features = []
        opt.notdef_outline = True
        opt.recommended_glyphs = True
        ss = Subsetter(opt)
        ss.populate(text="".join(charset))
        ss.subset(f)
        f.save(out)
        reg_name = name + suffix
        pdfmetrics.registerFont(TTFont(reg_name, out))
        registered[key] = reg_name
        if key == "heiti": HEITI = reg_name
        elif key == "kaiti": KAITI = reg_name
        elif key == "qihei": QIHEI = reg_name
        print(f"  [font] {key} -> {reg_name} ({os.path.getsize(out)//1024} KB)")
    return registered

# ============================================================ 文本工具（图形内用）
def text_w(s, size):
    return sum(size if ord(c) > 0x2E80 else size*0.55 for c in s)

def split_text(s, size, maxw):
    lines, cur = [], ""
    for c in s:
        if c == "\n":
            lines.append(cur); cur = ""; continue
        if text_w(cur + c, size) <= maxw:
            cur += c
        else:
            if cur: lines.append(cur)
            cur = c
    if cur: lines.append(cur)
    return lines

# ============================================================ 样式
def build_styles(F):
    CJK = {"wordWrap": "CJK"}
    return {
        "title":  ParagraphStyle("title", fontName=F["song"], fontSize=27, leading=38,
                                 alignment=TA_CENTER, textColor=NAVY, spaceAfter=4),
        "brand":  ParagraphStyle("brand", fontName=F["heiti"], fontSize=9, leading=13,
                                 alignment=TA_CENTER, textColor=LGRAY, spaceAfter=10, **CJK),
        "bar_left": ParagraphStyle("bar_left", fontName=F["songb"], fontSize=17, leading=22,
                                   textColor=colors.white, alignment=TA_LEFT, **CJK),
        "bar_right": ParagraphStyle("bar_right", fontName=F["heiti"], fontSize=9, leading=13,
                                    textColor=colors.white, alignment=TA_RIGHT, **CJK),
        "date":   ParagraphStyle("date", fontName=F["kaiti"], fontSize=12.5, leading=20,
                                 alignment=TA_CENTER, textColor=GRAY, spaceAfter=2, **CJK),
        "subtitle": ParagraphStyle("subtitle", fontName=F["qihei"], fontSize=9.5, leading=15,
                                   alignment=TA_CENTER, textColor=LGRAY, spaceAfter=4, **CJK),
        "org":    ParagraphStyle("org", fontName=F["heiti"], fontSize=10.5, leading=16,
                                 alignment=TA_CENTER, textColor=NAVY, spaceAfter=3, **CJK),
        "motto":  ParagraphStyle("motto", fontName=F["qihei"], fontSize=8.8, leading=14,
                                 alignment=TA_CENTER, textColor=GRAY, spaceAfter=6, **CJK),
        "kbox_title": ParagraphStyle("kbox_title", fontName=F["heiti"], fontSize=12, leading=16,
                                     textColor=colors.white, alignment=TA_LEFT, **CJK),
        "toc":    ParagraphStyle("toc", fontName=F["qihei"], fontSize=9, leading=14,
                                 alignment=TA_CENTER, textColor=GRAY, spaceAfter=2, **CJK),
        "h1":     ParagraphStyle("h1", fontName=F["songb"], fontSize=16.5, leading=25,
                                 textColor=NAVY, alignment=TA_LEFT, **CJK),
        "h2":     ParagraphStyle("h2", fontName=F["heiti"], fontSize=13.5, leading=21,
                                 textColor=NAVY, spaceBefore=18, spaceAfter=5,
                                 keepWithNext=1, **CJK),
        "h3":     ParagraphStyle("h3", fontName=F["heiti"], fontSize=12, leading=18,
                                 textColor=NAVY2, spaceBefore=10, spaceAfter=5,
                                 keepWithNext=1, **CJK),
        "meta":   ParagraphStyle("meta", fontName=F["heiti"], fontSize=8.5, leading=13,
                                 textColor=LGRAY, spaceAfter=2, keepWithNext=1, **CJK),
        "link":   ParagraphStyle("link", fontName=F["kaiti"], fontSize=8, leading=12,
                                 textColor=NAVY2, spaceAfter=SP_S, keepWithNext=1, **CJK),
        "body":   ParagraphStyle("body", fontName=F["kaiti"], fontSize=10.5, leading=18.5,
                                 textColor=INK, alignment=TA_JUSTIFY,
                                 firstLineIndent=21, spaceAfter=SP_S,
                                 allowWidows=0, allowOrphans=0, **CJK),
        "body0":  ParagraphStyle("body0", fontName=F["kaiti"], fontSize=10.5, leading=18.5,
                                 textColor=INK, alignment=TA_JUSTIFY,
                                 firstLineIndent=0, spaceAfter=SP_XS,
                                 allowWidows=0, allowOrphans=0, **CJK),
        "bodyc":  ParagraphStyle("bodyc", fontName=F["kaiti"], fontSize=10.5, leading=20,
                                 textColor=INK, alignment=TA_JUSTIFY,
                                 firstLineIndent=0, spaceAfter=8,
                                 allowWidows=0, allowOrphans=0, **CJK),
        "listitem": ParagraphStyle("listitem", fontName=F["kaiti"], fontSize=10.5, leading=18.5,
                                   textColor=INK, alignment=TA_JUSTIFY,
                                   leftIndent=17, firstLineIndent=-17, spaceAfter=SP_XS, **CJK),
        "ana":    ParagraphStyle("ana", fontName=F["kaiti"], fontSize=10.5, leading=18.5,
                                 textColor=ANA_TXT, alignment=TA_JUSTIFY,
                                 firstLineIndent=0, allowWidows=0, allowOrphans=0, **CJK),
        "tc":     ParagraphStyle("tc", fontName=F["heiti"], fontSize=9.5, leading=14,
                                 textColor=colors.white, alignment=TA_CENTER, **CJK),
        "tc2":    ParagraphStyle("tc2", fontName=F["kaiti"], fontSize=9, leading=14,
                                 textColor=INK, alignment=TA_LEFT, **CJK),
        "fig":    ParagraphStyle("fig", fontName=F["qihei"], fontSize=9, leading=14,
                                 textColor=GRAY, alignment=TA_CENTER,
                                 spaceBefore=8, spaceAfter=2, **CJK),
        "src":    ParagraphStyle("src", fontName=F["qihei"], fontSize=7.6, leading=11,
                                 textColor=LGRAY, alignment=TA_LEFT,
                                 spaceBefore=0, spaceAfter=12, **CJK),
        "note":   ParagraphStyle("note", fontName=F["qihei"], fontSize=9, leading=15,
                                 textColor=GRAY, spaceBefore=2, spaceAfter=SP_S,
                                 keepWithNext=1, **CJK),
        "legendc": ParagraphStyle("legendc", fontName=F["qihei"], fontSize=9, leading=16,
                                  textColor=GRAY, alignment=TA_CENTER,
                                  spaceBefore=0, spaceAfter=SP_M, **CJK),
        "footer": ParagraphStyle("footer", fontName=F["qihei"], fontSize=8, leading=12,
                                 textColor=LGRAY, alignment=TA_CENTER, **CJK),
    }

def brand_bar(S, title=DOC_TITLE, tagline="每日监管与合规动态"):
    """封面深蓝品牌条：机构标识带（投行研报封面风格）"""
    left = Paragraph(f"<font color='white'>{title}</font>", S["bar_left"])
    right = Paragraph(f"<font color='white'>{tagline}</font>", S["bar_right"])
    t = Table([[left, right]], colWidths=[CONTENT_W*0.62, CONTENT_W*0.38])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), NAVY),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING", (0,0), (0,0), 14),
        ("RIGHTPADDING", (1,0), (1,0), 14),
    ]))
    return t

def h1_block(text, S, toc=True):
    """一级标题：藏蓝左竖条 + 浅蓝底纹条；keepWithNext 防止孤行"""
    t = Table([[Paragraph(text, S["h1"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BG_H1),
        ("LINEBEFORE", (0,0), (0,-1), 2.6, NAVY),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    t.keepWithNext = True
    if toc:
        t._h1_text = text   # 供 afterFlowable 识别章节标题，生成目录页码
    return t

def analysis_block(text, S, prefix="解读"):
    """解读/建议块：浅灰蓝底 + 深蓝左边线（投行冷静风格）"""
    p = Paragraph(f"<font name='{HEITI}' color='#1F3B63'>{prefix}：</font>"
                  f"<font name='{KAITI}'>{text}</font>", S["ana"])
    t = Table([[p]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BG_ANA),
        ("LINEBEFORE", (0,0), (0,-1), 2.2, NAVY2),
        ("BOX", (0,0), (-1,-1), 0.5, EDGE_ANA),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    return t

def org_motto(S, org="朴朴超市 · 法务合规部", motto="守护合规底线 · 支撑业务决策"):
    """封面机构署名 + 使命标语（对标 PwC/腾讯 ESG 封面：机构名 + 使命标语）
    返回 flowable 列表，插在 subtitle 之后、导读之前。"""
    return [Paragraph(org, S["org"]), Paragraph(motto, S["motto"])]

def prev_issue_dates(date_str, n=3):
    """从封面日期字符串推算前 n 期期次（日更场景：按自然日递减）。

    仅匹配单一日期（YYYY年M月D日，可带星期后缀）；周报/月报 cover 多为区间文本，
    匹配失败或无有效日期时返回空列表，调用方据此降级、绝不抛错。
    """
    import re
    from datetime import date, timedelta
    if not date_str:
        return []
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not m:
        return []
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return [f"{(d - timedelta(days=i)).year}年{(d - timedelta(days=i)).month}月{(d - timedelta(days=i)).day}日"
                for i in range(1, n + 1)]
    except Exception:
        return []

def issue_history_block(S, date_str, n=3):
    """封面「近 N 期回顾」区块（对标 券商研报封面右下角往期回顾，benchmark 第二批 C① / 共性增量第10条）。

    强化读者对期次连续性的认知，属纯封面展示、不引入任何业务内容数据。
    日期由封面 date_str 推算（前 n 个自然日）；解析失败则降级为空块，不破坏生成。
    返回 flowable 列表，插在「本期导读」之后、封面分隔线之前。
    """
    prev = prev_issue_dates(date_str, n=n)
    if not prev:
        return []
    txt = f"近 {n} 期回顾：　" + "　·　".join(prev)
    return [Paragraph(txt, S["motto"])]


def compile_note(S, cutoff=None, n_src=None):
    """封面「编制说明」固定元数据（对标 上交所案例集「报告编制说明三项固定要素」benchmark 第二批 A②：
    报告期 / 覆盖口径 / 审核与签发；第三批 D⑤：ESG 报告明确披露「汇报期与数据口径/数据截止时点」）。
    报告期已由 date_str 呈现，本块补齐「覆盖口径」「审核与签发」两项固定元数据；
    当传入 cutoff / n_src 时追加第三行「数据截止与来源」，强化对外可追溯观感。
    属纯封面展示、不引入任何业务内容数据（不触碰 policy/penalties/pupu_items/matrix_rows 等）。
    返回 flowable 列表，插在「近 3 期回顾」之后、封面分隔线之前；日报/周报/月报 PDF 四件套统一生效。"""
    rows = [
        Paragraph("覆盖口径：六大合规领域公开监管动态与通报处罚", S["motto"]),
        Paragraph("审核与签发：朴朴超市法务合规部", S["motto"]),
    ]
    if cutoff or n_src:
        seg = []
        if cutoff:
            seg.append(f"数据截止：{cutoff}")
        if n_src:
            seg.append(f"官方来源 {n_src} 条（详见各条原文链接）")
        rows.append(Paragraph(" · ".join(seg), S["motto"]))
    return rows

def src_note(text, S):
    """图表「资料来源」脚注（对标 中金/中信/CAICT：图表必带来源）
    与图注同属一个 KeepTogether，保证不与图分离。"""
    return Paragraph(f"资料来源：{text}", S["src"])

SRC_PUBLIC = "依据公开监管通报与处罚决定书整理，详见各条原文链接"
SRC_INTERNAL = "朴朴超市法务合规部基于公开监管动态内部评估"

def disclaimer_block(S, kind="本简报"):
    """尾部「信息来源与免责声明」固定栏（对标 中信证券研报尾部声明栏）"""
    txt = (
        f"一、信息来源：{kind}内容基于公开网络检索整理的监管机构官方网站通报、公告、处罚决定书及权威媒体报道，"
        "各条动态均附原文链接，便于溯源核验。<br/>"
        f"二、用途限制：{kind}仅供朴朴超市内部合规参考，不构成法律意见或决策依据；据此采取具体合规措施前，"
        "请咨询法务或外部专业律师。<br/>"
        f"三、时效性：监管政策与执法动态更新较快，{kind}截至生成时点整理，不排除后续修订或新发文件导致内容变化，"
        "请以最新官方发布为准。<br/>"
        f"四、版权：{kind}由自动化任务生成，引用内容著作权归原发布机构所有。"
    )
    t = Table([[Paragraph(txt, S["body0"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BG_KEY),
        ("LINEBEFORE", (0,0), (0,-1), 2.2, NAVY),
        ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#D8DEE6")),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    return t

def add_docx_footer(doc, kind="本简报"):
    """DOCX 页脚：左来源/免责声明 + 右页码（对齐 PDF draw_footer，benchmark C③ 页脚规范）。

    对 doc 每个 section 设置一致页脚：细线(#E3E8EF) + 左「资料来源详见各条原文链接 · 仅供内部合规参考」
    + 右「第 X 页 / 共 Y 页」；纯展示、不引入任何内容数据，不改变 policy/penalties/pupu_items 等。
    依赖 python-docx（DOCX 生成器已具备），导入置于函数内以不污染 PDF 引擎依赖。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_TAB_ALIGNMENT
    GRAY = RGBColor(0x6B, 0x72, 0x80)
    HEITI = "微软雅黑"
    left_text = "资料来源详见各条原文链接 · 仅供内部合规参考"

    def _set_run(run, text=None, size=8, eastasia=HEITI):
        if text is not None:
            run.text = text
        run.font.name = "Times New Roman"
        run.font.size = Pt(size)
        run.font.color.rgb = GRAY
        rpr = run._element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.append(rf)
        rf.set(qn("w:eastAsia"), eastasia)

    def _field(paragraph, instr):
        run = paragraph.add_run()
        r = run._r
        f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
        it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = instr
        f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "end")
        r.append(f1); r.append(it); r.append(f2)
        _set_run(run)   # 仅设字体，不覆盖字段
        return run

    for section in doc.sections:
        footer = section.footer
        p = footer.paragraphs[0]
        p.text = ""
        # 页脚上细线（对齐 PDF footer 上方 #E3E8EF 0.5pt 线）
        pPr = p._p.get_or_add_pPr()
        pbdr = OxmlElement("w:pBdr")
        top = OxmlElement("w:top")
        top.set(qn("w:val"), "single"); top.set(qn("w:sz"), "4")
        top.set(qn("w:space"), "1"); top.set(qn("w:color"), "E3E8EF")
        pbdr.append(top)
        pPr.append(pbdr)
        # 右对齐制表位：内容宽 = 21cm - 2.5cm - 2.5cm = 16cm（对齐 DOCX 版心边距）
        p.paragraph_format.tab_stops.add_tab_stop(Cm(16.0), WD_TAB_ALIGNMENT.RIGHT)
        _set_run(p.add_run(left_text))
        p.add_run("\t")
        _set_run(p.add_run("第 "))
        _field(p, "PAGE")
        _set_run(p.add_run(" 页 / 共 "))
        _field(p, "NUMPAGES")
        _set_run(p.add_run(" 页"))

    # 强制 Word/WPS 打开时自动更新域（页码），避免页脚显示空白
    try:
        settings = doc.settings.element
        uf = settings.find(qn("w:updateFields"))
        if uf is None:
            uf = OxmlElement("w:updateFields")
            uf.set(qn("w:val"), "true")
            settings.append(uf)
    except Exception:
        pass

def styled_toc(F, dots=True):
    """目录：页码右对齐 + 点状引导线（对标共性第 2 条「章|页码 右对齐目录」）"""
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle(
        "toc1", fontName=F["songb"], fontSize=11, leading=24,
        textColor=NAVY, leftIndent=10, firstLineIndent=-10,
        spaceBefore=2, spaceAfter=2, wordWrap="CJK")]
    toc.rightColumnWidth = 42
    if dots:
        toc.dotsMinLevel = 0     # 默认 1，我们只有 level0，需降到 0 才出引导点
    return toc

def divider():
    """条目间细分隔线"""
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D8DEE6"),
                      spaceBefore=12, spaceAfter=12)

def key_points_box(S, rows, title="核心观点"):
    """核心观点框（Executive Summary 框）：navy 标题条 + 浅蓝底要点列表。

    对标 benchmark_reports.md 跨样本共性第 1 条「摘要/核心观点前置」——
    11 份头部样本 100% 在正文前给出 Executive Summary 或核心结论框。
    由单一 Table 实现（标题行 navy 底白字 + 内容行 BG_KEY 浅蓝底 + 左侧 NAVY 强调条），
    避免嵌套 Table 的不可控撑高；纯样式改动，不引入任何内容数据。
    """
    data = [[Paragraph(f"<font name='{HEITI}' color='#FFFFFF'>{title}</font>", S["kbox_title"])]]
    data += rows
    t = Table(data, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), NAVY),            # 标题条
        ("BACKGROUND", (0, 1), (-1, -1), BG_KEY),        # 内容浅蓝底
        ("LINEBEFORE", (0, 1), (0, -1), 3.0, NAVY),       # 左侧强调条（仅内容区）
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9D6E4")),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), 3.0, None),  # 圆角（reportlab 5.x 支持）
        ("LINEBELOW", (0, 0), (0, 0), 0.8, colors.HexColor("#C9D6E4")),  # 标题条下分隔
        ("TOPPADDING", (0, 0), (0, 0), 6), ("BOTTOMPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (0, 0), (0, 0), 12), ("RIGHTPADDING", (0, 0), (0, 0), 12),
        ("TOPPADDING", (0, 1), (-1, -1), 7), ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 1), (-1, -1), 15), ("RIGHTPADDING", (0, 1), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t

def link_html(url):
    """原文链接行：可点击超链接（蓝色小字）"""
    if not url:
        return ""
    u = url.replace("&", "&amp;")
    return (f"<font name='{HEITI}' color='#6B7280' size='8.5'>原文链接：</font>"
            f"<a href='{u}' color='#2E5E8C'>{u}</a>")

# ============================================================ 图表构建（Table 方案）
# 用 Table 而非手绘矢量：文字自动换行、框随内容自动撑高、箭头对齐，
# 从根上杜绝文字溢出/框重叠/箭头错位导致的"图看不懂"问题
_FB_CACHE = {}

def _fb(text, font, size, color):
    """流程图框内文字：居中、紧凑行距、CJK 自动换行"""
    key = (font, size, color)
    if key not in _FB_CACHE:
        _FB_CACHE[key] = ParagraphStyle(
            f"fb{len(_FB_CACHE)}", fontName=font, fontSize=size,
            leading=size*1.45, alignment=TA_CENTER, textColor=color, wordWrap="CJK")
    return Paragraph(text.replace("\n", "<br/>"), _FB_CACHE[key])

def _fa(sym, color=NAVY2, size=13):
    """流程图箭头符号：居中"""
    st = ParagraphStyle("fa", fontName=HEITI, fontSize=size, leading=size*1.2,
                        alignment=TA_CENTER, textColor=color)
    return Paragraph(sym, st)

def _flow(grid, col_widths, cmds):
    """构造流程图 Table"""
    t = Table(grid, colWidths=col_widths)
    base = [
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
    ]
    t.setStyle(TableStyle(base + cmds))
    return t

def fig1_enforcement(F):
    """图2：监管执法处置流程（纵向 Table）"""
    W3 = [175, 120, 175]
    H = HEITI
    B = lambda txt, tc=INK, sz=9.5: _fb(txt, H, sz, tc)
    A = lambda: _fa(AR_DOWN)
    grid = [
        [B("日常监测 · 专项行动"), "", ""],
        ["", A(), ""],
        [B("发现问题线索"), "", ""],
        ["", A(), ""],
        [B("责令整改 · 约谈告诫"), "", ""],
        ["", A(), ""],
        [B("整改复查"), "", ""],
        [A(), "", A()],
        [B("合格 → 结案销号", colors.HexColor("#2F5D2F"), 9), "",
         B("不合格 → 通报 · 下架 · 罚款", colors.HexColor("#7C241C"), 9)],
        [A(), "", A()],
        [B("处罚信息公示 · 纳入信用记录 · 典型案例发布", NAVY, 9), "", ""],
    ]
    cmds = []
    for r in (0, 2, 4, 6, 10):
        fill = colors.HexColor("#F4F7FB") if r == 10 else colors.white
        bd = NAVY2 if r == 10 else NAVY
        cmds.append(("BACKGROUND", (0, r), (2, r), fill))
        cmds.append(("BOX", (0, r), (2, r), 1.1, bd))
    cmds.append(("BACKGROUND", (0, 8), (0, 8), colors.HexColor("#EDF6ED")))
    cmds.append(("BOX", (0, 8), (0, 8), 1.1, colors.HexColor("#3E6B3E")))
    cmds.append(("BACKGROUND", (2, 8), (2, 8), colors.HexColor("#FBEEEC")))
    cmds.append(("BOX", (2, 8), (2, 8), 1.1, colors.HexColor("#8E2B20")))
    return _flow(grid, W3, cmds)

def fig2_price(F):
    """图1：价格欺诈认定与责任链条（纵向 Table）"""
    W3 = [175, 120, 175]
    H = HEITI
    B = lambda txt, tc=INK, sz=9: _fb(txt, H, sz, tc)
    A = lambda: _fa(AR_DOWN)
    grid = [
        [B("虚构“划线价”：\n团购37.9元 / 假原价570元", sz=8.8), "", ""],
        ["", A(), ""],
        [B("制造巨大优惠假象"), "", ""],
        ["", A(), ""],
        [B("认定构成价格欺诈", colors.HexColor("#8A6D1F")), "", ""],
        ["", A(), ""],
        [B("法律依据：《明码标价和禁止价格欺诈规定》第19条", colors.HexColor("#7A4E0A"), 8.5), "", ""],
        [A(), "", A()],
        [B("行政责任：\n责令改正 · 没收违法所得 · 罚款", colors.HexColor("#7C241C"), 8.6), "",
         B("民事责任：\n消费者可主张“退一赔三”", colors.HexColor("#7C241C"), 8.6)],
        [A(), "", A()],
        [B("合规要点：划线价/原价对比须有真实成交记录支撑，禁止虚构原价", colors.HexColor("#2F5D2F"), 8.5), "", ""],
    ]
    cmds = [
        ("BACKGROUND", (0,0), (2,0), colors.white), ("BOX", (0,0), (2,0), 1.1, NAVY),
        ("BACKGROUND", (0,2), (2,2), colors.white), ("BOX", (0,2), (2,2), 1.1, NAVY),
        ("BACKGROUND", (0,4), (2,4), colors.HexColor("#FFF3D6")), ("BOX", (0,4), (2,4), 1.1, colors.HexColor("#B0862E")),
        ("BACKGROUND", (0,6), (2,6), colors.HexColor("#FBF7EC")), ("BOX", (0,6), (2,6), 1.0, EDGE_ANA),
        ("BACKGROUND", (0,10), (2,10), colors.HexColor("#EDF6ED")), ("BOX", (0,10), (2,10), 1.1, colors.HexColor("#3E6B3E")),
        ("BACKGROUND", (0,8), (0,8), colors.HexColor("#FBEEEC")), ("BOX", (0,8), (0,8), 1.1, colors.HexColor("#8E2B20")),
        ("BACKGROUND", (2,8), (2,8), colors.HexColor("#FBEEEC")), ("BOX", (2,8), (2,8), 1.1, colors.HexColor("#8E2B20")),
    ]
    return _flow(grid, W3, cmds)

def fig4_govern(F):
    """图4：福建食品安全"政企检"协同机制架构（树状 Table）"""
    W3 = [150, 170, 150]
    H = HEITI
    B = lambda txt, tc=INK, sz=9: _fb(txt, H, sz, tc)
    A = lambda: _fa(AR_DOWN)
    grid = [
        [B("福建省市场监管局\n（统筹协调 · 牵头组织）", colors.white, 9.5), "", ""],
        [A(), A(), A()],
        [B("省产品质量检验研究院\n技术支撑 · 风险研判"),
         B("朴朴电商（签约企业）\n品控资源 · 数据共享", colors.HexColor("#8A6D1F")),
         B("永辉超市等企业\n联合参与 · 协同共治")],
        [A(), A(), A()],
        [B("风险防控关口前移至食品入市销售之前\n“一品一码”溯源 · 品控数据对监管透明共享", colors.HexColor("#2F5D2F"), 8.5), "", ""],
    ]
    cmds = [
        ("BACKGROUND", (0,0), (2,0), NAVY), ("BOX", (0,0), (2,0), 1.1, NAVY),
        ("BACKGROUND", (0,2), (0,2), colors.white), ("BOX", (0,2), (0,2), 1.1, NAVY),
        ("BACKGROUND", (1,2), (1,2), colors.HexColor("#FFF3D6")), ("BOX", (1,2), (1,2), 1.1, colors.HexColor("#B0862E")),
        ("BACKGROUND", (2,2), (2,2), colors.white), ("BOX", (2,2), (2,2), 1.1, NAVY),
        ("BACKGROUND", (0,4), (2,4), colors.HexColor("#EDF6ED")), ("BOX", (0,4), (2,4), 1.1, colors.HexColor("#3E6B3E")),
    ]
    return _flow(grid, W3, cmds)

def fig3_matrix(F, table_data):
    """朴朴合规风险热力矩阵（Table 实现）"""
    rows = [["风险主题", "采购", "仓储/加工", "线上运营", "配送", "会员营销", "用工"]]
    rows.extend(table_data)
    colw = [100] + [(CONTENT_W-100)//6]*6
    t = Table(rows, colWidths=colw, rowHeights=[28]+[26]*len(table_data))
    cmds = [
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), F["heiti"]),
        ("FONTSIZE", (0,0), (-1,0), 9),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#D8DEE6")),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]
    # 中高：ORANGE(#B0652C) 已在文件顶部定义，此前未接入本矩阵，
    # 导致「中高」单元格回退为 GRAY，与「暂不涉及」(#B8BFC9) 同色系而被误读。
    level_color = {"高": RED, "中高": ORANGE, "中": AMBER, "低": GREEN}
    for r in range(1, len(rows)):
        cmds.append(("FONTNAME", (0,r), (0,r), F["heiti"]))
        cmds.append(("FONTSIZE", (0,r), (0,r), 8.6))
        cmds.append(("TEXTCOLOR", (0,r), (0,r), NAVY))
        for c in range(1, 7):
            v = rows[r][c]
            if v == "—":
                cmds.append(("BACKGROUND", (c,r), (c,r), colors.HexColor("#B8BFC9")))
            else:
                cmds.append(("BACKGROUND", (c,r), (c,r), level_color.get(v, GRAY)))
                cmds.append(("TEXTCOLOR", (c,r), (c,r), colors.white))
                cmds.append(("FONTNAME", (c,r), (c,r), F["qihei"]))
                cmds.append(("FONTSIZE", (c,r), (c,r), 8.4))
    t.setStyle(TableStyle(cmds))
    return t

def legend_paragraph(S):
    """热力矩阵图例：Paragraph backColor 实现，色块与文字天然对齐"""
    return Paragraph(
        "<font backColor='#A93B33' color='white'>　高　</font>　"
        "<font backColor='#B0652C' color='white'>　中高　</font>　"
        "<font backColor='#B0862E' color='white'>　中　</font>　"
        "<font backColor='#4C7A59' color='white'>　低　</font>　"
        "<font backColor='#B8BFC9' color='white'>　暂不涉及　</font>",
        S["legendc"])

# ============================================================ 具像化参考图示（行业合规水位 / 合规样例）
def fig_waterlevel(F, rows):
    """行业合规水位对比矩阵（控制点 × 平台，按 领先/达标/待提升 着色）"""
    H = HEITI
    W3 = [3.5 * cm] + [(CONTENT_W - 3.5 * cm) / 5.0] * 5
    header = ["合规控制点", "朴朴", "美团", "盒马", "叮咚", "京东到家"]
    grid = [[Paragraph(h, ParagraphStyle("wlh", fontName=F["heiti"], fontSize=9, leading=11,
                                         textColor=colors.white, alignment=TA_CENTER)) for h in header]]
    lvl = {"领先": GREEN, "达标": AMBER, "待提升": RED}
    for r in rows:
        crow = [Paragraph(r[0], ParagraphStyle("wl0", fontName=F["heiti"], fontSize=8.6, leading=11, textColor=NAVY))]
        for v in r[1:]:
            crow.append(Paragraph(v, ParagraphStyle("wlc", fontName=F["qihei"], fontSize=8.4, leading=11,
                                                    textColor=colors.white, alignment=TA_CENTER)))
        grid.append(crow)
    t = Table(grid, colWidths=W3, rowHeights=[26] + [24] * len(rows))
    cmds = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for ri in range(1, len(rows) + 1):
        for ci in range(1, 6):
            v = rows[ri - 1][ci]
            cmds.append(("BACKGROUND", (ci, ri), (ci, ri), lvl.get(v, GRAY)))
    t.setStyle(TableStyle(cmds))
    return t

def fig_food_sop(F):
    """生鲜入库食安快检准入 SOP 流程图（具像化合规样例）"""
    W3 = [180, 110, 180]
    H = HEITI
    B = lambda txt, tc=INK, sz=9: _fb(txt, H, sz, tc)
    A = lambda: _fa(AR_DOWN)
    grid = [
        [B("① 供应商到货 · 批次到仓", NAVY, 9), "", ""],
        ["", A(), ""],
        [B("② 资质 + 批次检验合格证明查验\n（缺证明 → 直接拦截拒收）", NAVY2, 8.8), "", ""],
        ["", A(), ""],
        [B("③ 入库快检：二氧化硫残留\n+ 农兽药残留（噻虫嗪/胺/五氯酚酸钠）", NAVY2, 8.8), "", ""],
        ["", A(), ""],
        [B("④ 判定：是否合格？", NAVY, 9), "", ""],
        [A(), "", A()],
        [B("合格 → 上架销售", colors.HexColor("#2F5D2F"), 9), "",
         B("不合格 → 一键下架召回\n+ 通知采购/品控复核", colors.HexColor("#7C241C"), 8.8)],
        ["", A(), ""],
        [B("⑤ 合格品：一品一码溯源 · 抽检通报后数分钟定位同批次", colors.HexColor("#2F5D2F"), 8.6), "", ""],
    ]
    cmds = []
    for r in (0, 2, 4, 6, 10):
        cmds.append(("BACKGROUND", (0, r), (2, r), colors.HexColor("#F4F7FB")))
        cmds.append(("BOX", (0, r), (2, r), 1.1, NAVY))
    cmds.append(("BACKGROUND", (0, 8), (0, 8), colors.HexColor("#EDF6ED")))
    cmds.append(("BOX", (0, 8), (0, 8), 1.1, colors.HexColor("#3E6B3E")))
    cmds.append(("BACKGROUND", (2, 8), (2, 8), colors.HexColor("#FBEEEC")))
    cmds.append(("BOX", (2, 8), (2, 8), 1.1, colors.HexColor("#8E2B20")))
    cmds.append(("BACKGROUND", (0, 10), (2, 10), colors.HexColor("#EDF6ED")))
    cmds.append(("BOX", (0, 10), (2, 10), 1.1, colors.HexColor("#3E6B3E")))
    return _flow(grid, W3, cmds)

def fig_price_sample(F):
    """商品价格展示合规自检清单样例（合规模板）"""
    H = HEITI
    rows = [
        ("商品详情页价格展示（合规示范）", ""),
        ("划线价 ¥99.9", "须有真实成交记录支撑：系统留存近 7 日最低成交价截图，禁止虚构原价/累加核算价"),
        ("促销价 ¥59.9", "规则事前公示：活动前 7 日均价 ¥89，本价低于均价，降幅说明清晰可查"),
        ("动态 / 差别定价", "向用户明示定价规则，禁止“杀熟”；同商品同用户可见价格一致或可解释"),
        ("免密支付 / 自动续期", "显著告知并一键取消，扣款前二次确认，不得默认勾选"),
    ]
    grid = []
    for i, (k, v) in enumerate(rows):
        if i == 0:
            grid.append([Paragraph(k, ParagraphStyle("ps0", fontName=F["heiti"], fontSize=9.5, leading=12,
                                                     textColor=colors.white, alignment=TA_CENTER)),
                         Paragraph("", ParagraphStyle("psp", fontName=F["kaiti"], fontSize=8))])
        else:
            grid.append([Paragraph(k, ParagraphStyle("psk", fontName=F["heiti"], fontSize=8.8, leading=11, textColor=NAVY)),
                         Paragraph(v, ParagraphStyle("psv", fontName=F["kaiti"], fontSize=8.5, leading=12, textColor=INK))])
    t = Table(grid, colWidths=[4.2 * cm, CONTENT_W - 4.2 * cm])
    cmds = [("SPAN", (0, 0), (1, 0)),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F4F7FB")),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    t.setStyle(TableStyle(cmds))
    return t

def fig_framework(F):
    """六大合规领域要点框架图（中枢统领六域，产品级框架示意）"""
    H, K = HEITI, KAITI
    W3 = [CONTENT_W / 3.0] * 3
    def card(name, focus):
        return Paragraph(
            f"<font name='{H}' size='9.6' color='#1F3B63'>{name}</font><br/>"
            f"<font name='{K}' size='8' color='#37424F'>{focus}</font>",
            ParagraphStyle("fc", fontName=F["kaiti"], fontSize=8, leading=11,
                           alignment=TA_CENTER, textColor=INK))
    top = Paragraph("合规中枢：统一治理 · 风险识别—评估—控制—监测闭环",
                    ParagraphStyle("fmid", fontName=F["heiti"], fontSize=9.5, leading=12,
                                   textColor=colors.white, alignment=TA_CENTER))
    grid = [
        [top],
        [card("数据合规", "个人信息保护 · 数据分类分级 · 第三方SDK治理"),
         card("AI 合规", "生成式内容标识 · 深度合成备案 · 智能客服转人工"),
         card("算法合规", "派单/推荐算法备案公示 · 可解释可申诉")],
        [card("平台合规", "商户资质实质审查 · 入网核验 · 许可证照"),
         card("产品合规·食安", "生鲜快检硬门槛 · 一批一码溯源 · 召回闭环"),
         card("价格合规", "明码标价 · 禁止虚构原价/价格欺诈 · 动态定价明示")],
    ]
    cmds = [
        ("SPAN", (0, 0), (2, 0)),
        ("BACKGROUND", (0, 0), (2, 0), NAVY),
        ("BOX", (0, 0), (2, 0), 1.1, NAVY),
        ("GRID", (0, 1), (2, 2), 0.6, colors.HexColor("#D8DEE6")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    t = Table(grid, colWidths=W3, rowHeights=[26, 46, 46])
    t.setStyle(TableStyle(cmds))
    return t

def fig_reg_matrix(F):
    """监管要求对照自检矩阵（控制点 × 监管依据/自检要点/同业水位/行动优先级）

    对标 benchmark_reports.md 可落地建议 2「新增监管对比矩阵」——
    合规类报告最高频结构为对比表。本图以「监管依据 → 自检要点 → 同业水位 → 优先级」
    四段式呈现，优先级列按统一后色阶着色，便于业务方一眼定位高优先项。
    矢量 Table 实现，纯排版组件，不引入任何业务数据。
    """
    H, K = HEITI, KAITI
    COLW = [85, 120, 120, 95, 50]
    header = ["合规控制点", "监管依据", "自检要点", "同业普遍水位", "优先级"]
    grid = [[Paragraph(h, ParagraphStyle("rmh", fontName=F["heiti"], fontSize=8.8, leading=11,
                                         textColor=colors.white, alignment=TA_CENTER))
             for h in header]]
    rows = [
        ("算法备案与公示", "《算法推荐管理规定》第16条", "备案信息真实、公示入口可达", "公示入口已上线", "高"),
        ("AI 生成内容标识", "《AI生成合成内容标识办法》", "显式标识可见、隐式标识可溯", "标识口径尚不统一", "高"),
        ("第三方 SDK 治理", "《个人信息保护法》最小必要", "SDK 清单公示、权限最小化", "清单公示较普遍", "中"),
        ("生鲜快检与溯源", "《食品安全法》一批一码", "到货快检留痕、溯源链路可查", "快检公示程度参差", "中"),
        ("明码标价与动态定价", "《明码标价和禁止价格欺诈规定》", "划线价有据、动态定价规则明示", "划线价争议高发", "高"),
        ("商户资质实质审查", "《电子商务法》第27条", "入网核验、定期复核留痕", "审核深度差异较大", "低"),
    ]
    for r in rows:
        grid.append([
            Paragraph(r[0], ParagraphStyle("rm0", fontName=F["heiti"], fontSize=8.2, leading=10.5, textColor=NAVY)),
            Paragraph(r[1], ParagraphStyle("rm1", fontName=F["qihei"], fontSize=7.8, leading=10.5, textColor=INK)),
            Paragraph(r[2], ParagraphStyle("rm2", fontName=F["qihei"], fontSize=7.8, leading=10.5, textColor=INK)),
            Paragraph(r[3], ParagraphStyle("rm3", fontName=F["qihei"], fontSize=7.8, leading=10.5, textColor=INK)),
            Paragraph(r[4], ParagraphStyle("rm4", fontName=F["heiti"], fontSize=8.4, leading=10.5,
                                           textColor=colors.white, alignment=TA_CENTER)),
        ])
    t = Table(grid, colWidths=COLW, rowHeights=[26] + [30] * len(rows))
    pri = {"高": RED, "中": AMBER, "低": GREEN}
    cmds = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (3, -1), colors.HexColor("#F7F9FC")),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    for ri, r in enumerate(rows, start=1):
        cmds.append(("BACKGROUND", (4, ri), (4, ri), pri.get(r[4], GRAY)))
    t.setStyle(TableStyle(cmds))
    return t

# ============================================================ 页眉页脚 + 页码
class ComplianceDoc(SimpleDocTemplate):
    """自定义文档模板：afterFlowable 钩子收集章节标题，供 TableOfContents 生成页码"""
    def afterFlowable(self, flowable):
        if getattr(flowable, "_h1_text", None):
            self.notify("TOCEntry", (0, flowable._h1_text, self.page))

class NumberedCanvas(rl_canvas.Canvas):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.draw_footer(n)
            super().showPage()
        super().save()

    def draw_footer(self, total):
        self.setStrokeColor(colors.HexColor("#E3E8EF"))
        self.setLineWidth(0.5)
        self.line(M_L, 1.55*cm, PAGE_W - M_R, 1.55*cm)
        self.setFont(QIHEI, 8)
        self.setFillColor(GRAY)
        # 左：来源/免责声明（对齐对标库 C③ 页脚「免责声明（左）」）
        self.drawString(M_L, 1.05*cm, "资料来源详见各条原文链接 · 仅供内部合规参考")
        # 右：页码（对齐对标库 C③ 页脚「第 X 页，共 Y 页（右）」）
        self.drawRightString(PAGE_W - M_R, 1.05*cm, f"第 {self._pageNumber} 页 / 共 {total} 页")

def make_header_footer(header_text, date_str):
    def header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(QIHEI, 8)
        canvas.setFillColor(GRAY)
        canvas.drawString(M_L, PAGE_H - 1.15*cm, header_text)
        canvas.drawRightString(PAGE_W - M_R, PAGE_H - 1.15*cm, date_str)
        canvas.setStrokeColor(colors.HexColor("#D8DEE6"))
        canvas.setLineWidth(0.6)
        canvas.line(M_L, PAGE_H - 1.35*cm, PAGE_W - M_R, PAGE_H - 1.35*cm)
        canvas.restoreState()
    return header_footer

def header_footer(canvas, doc):
    return make_header_footer(HEADER_TEXT, DATE_STR)(canvas, doc)

# ============================================================ 内容数据
summary = [
    "个人信息保护系列专项行动阶段性成效发布：2万余款App/SDK被核查，1100余款被通报，400余款被下架处罚",
    "市场监管总局举办反垄断合规讲堂，深入解读《互联网平台反垄断合规指引》，聚焦算法共谋、封禁屏蔽、“二选一”",
    "山东查处虚构“划线价”价格欺诈典型案件：团购价37.9元、划线价570元系凭空捏造",
    "福建首创全国首个省级食品安全“政企检”协同预警机制，朴朴电商参与签约",
    "福州台江区以朴朴为试点打造无堂食网络餐饮监管“台江样板”，14家集中厨房统一对标、AI监控直连监管平台",
    "太原市监局凌晨突击夜查线上食品配送企业（七鲜、盒马、小象等），冷链温控与合格证上传成检查重点",
    "厦门发布全省首份外卖配送行业公约，明确摒弃“最严算法”，保障骑手社保与最低工资",
]

domains = [
    ("数据合规", [
        {"title": "2026年个人信息保护系列专项行动阶段性成效发布",
         "meta": "2026-08-19/20 ｜ 中央网信办、工业和信息化部、公安部",
         "content": "累计对2万余款App、SDK个人信息收集使用情况开展核查检测，督促4000余款完成合规整改，公开通报1100余款存在违法违规问题的App、SDK，对400余款采取下架等处置处罚措施。针对个人信息处理规则未明确收集个人信息用于广告、用户画像，未提供个性化广告关闭选项等问题，对1000余家企业和机构的相关产品开展核查检测并督促整改。在教育、交通、卫生健康、金融等领域摸排9万余家企业机构，整改隐患问题1.2万余个。严打信息泄露、信息倒卖等违法犯罪行为，严惩行业“内鬼”。",
         "analysis": "对朴朴等电商平台的启示：会员数据、订单数据、营销推送（广告/用户画像）须明确告知处理规则，且必须提供个性化广告关闭选项；监管核查已常态化，App、小程序、SDK均在检测范围内。", "url": "https://www.cac.gov.cn/2026-08/19/c_1788889479389148.htm"},
        {"title": "75款移动应用被通报违法违规收集使用个人信息",
         "meta": "2026-08-15/17 ｜ 国家计算机病毒应急处理中心（依据三部门专项行动公告）",
         "content": "75款移动应用被公开通报，涉及“有道精品课”“大疆商城”“华夏基金管家”等。三类典型问题：①App首次运行时未以弹窗等明显方式提示用户阅读隐私政策等收集使用规则；②隐私政策未逐一列出App（含委托第三方或嵌入的第三方代码、插件）收集使用个人信息的目的、方式、范围；③向其他个人信息处理者提供个人信息时，未告知接收方信息并取得单独同意。",
         "analysis": "隐私政策完整披露+弹窗明示+单独同意是执法高频检查点，涉及大量微信/支付宝小程序，朴朴小程序、App需逐一对照自查。", "url": "https://m.chinanews.com/wap/detail/cht/zw/10677738.shtml"},
        {"title": "工信部通报2026年第1批（总第54批）22款APP及SDK",
         "meta": "2026-08 ｜ 工业和信息化部",
         "content": "22款APP及SDK存在侵害用户权益行为，问题集中表现为：违规收集个人信息、强制自动续费、窗口乱跳转、过度索取权限，覆盖社交、工具、出行、游戏、生活服务等多个领域。",
         "analysis": "强制自动续费、过度索取权限为高频违规点，涉及订阅类、会员类功能的产品需重点自查。", "url": "https://www.miit.gov.cn/"},
        {"title": "川渝两地通管局通报2026年第五期10款APP/小程序",
         "meta": "2026-08 ｜ 四川省通信管理局、重庆市通信管理局",
         "content": "10款APP/小程序未按要求完成整改。典型案例：①APP集成某SDK存在个人信息收集行为，但未在隐私政策及第三方SDK清单中披露；②APP未在二级菜单向用户明示已收集个人信息清单、SDK共享清单，索取存储权限时未同步告知目的。",
         "analysis": "SDK披露与个人信息清单、权限目的告知成为地方通管局检查重点，需确保隐私政策与SDK清单同步更新。", "url": "http://scca.miit.gov.cn/"},
    ]),
    ("算法合规", [
        {"title": "算法备案进入全面落地期，调度决策类算法明确纳入备案范围",
         "meta": "2026-08 ｜ 网信部门公开信息",
         "content": "2026年全年新增算法备案项目较上年增长约六成，生成合成、个性化推荐和调度决策类算法成为备案主力。算法备案覆盖五类：生成合成类、个性化推送类、排序精选类、检索过滤类、调度决策类。调度决策类明确包含外卖派单、运力调度、物流调度等场景。",
         "analysis": "朴朴配送调度、派单算法若涉及算法决策，需评估是否属于调度决策类备案范围；“已上线”不是免备案理由，产品上线后被发现未备案处境更被动。", "url": "https://beian.cac.gov.cn/"},
        {"title": "《平台劳动规则和算法协商指引（试行）》推动算法公平化",
         "meta": "2026-03 ｜ 全国总工会、人社部、中国企联、全国工商联",
         "content": "要求将订单分配、收入抽成、工作时长与休息、时间预估与路线规划、考核与奖惩等纳入协商范围；规范协商代表产生、协商程序、成果落地和监督，推动算法公平化、可协商。",
         "analysis": "平台算法规则从“单方制定”走向“集体协商”，涉及骑手派单与考核的平台需提前建立协商机制。", "url": "https://www.acftu.org/"},
    ]),
    ("AI合规", [
        {"title": "湖南省建立省级生成式人工智能服务联审工作机制",
         "meta": "2026-08 ｜ 湖南省（网信办牵头）",
         "content": "湖南出台《湖南省网络安全和信息化条例》《湖南省数据条例》等法规，建立省级生成式AI服务联审机制，明确网信、发改、教育、科技、工信、公安等多部门职责；全面落实大模型“备案+登记”分类管理和深度合成、算法推荐备案制度。",
         "analysis": "“备案+登记”分类管理及多部门联审机制或向其他省份推广，涉及AI功能的企业需持续跟踪属地备案要求。", "url": "https://www.cac.gov.cn/"},
        {"title": "全国生成式AI服务备案持续扩容",
         "meta": "截至2026年2月底 ｜ 国家网信办",
         "content": "全国累计796款生成式人工智能服务完成备案；广东备案大模型数量达132款，新增8款，通用大模型与行业大模型各占50%，覆盖市场营销、工业制造、生活服务等领域。",
         "analysis": "AI应用（智能客服、商品推荐、营销文案生成等）若面向公众提供服务，须评估生成式AI服务备案义务。", "url": "https://www.cac.gov.cn/"},
    ]),
    ("平台合规", [
        {"title": "市场监管总局举办反垄断合规讲堂，解读《互联网平台反垄断合规指引》",
         "meta": "2026-08-20 ｜ 国家市场监督管理总局",
         "content": "2026年第三期反垄断合规讲堂聚焦“互联网平台反垄断合规”，结合典型执法案例重点阐释平台间算法共谋、封禁屏蔽、“二选一”等典型场景中的新型垄断风险；提示平台不得利用数据、算法、技术从事垄断行为。",
         "analysis": "平台经营者应健全反垄断合规管理制度，将合规意识贯穿经营全过程；算法共谋等新型垄断风险为监管新焦点。", "url": "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fldzfys/art/2026/art_ad10c5301fcb426cb839153ca9f5a274.html"},
        {"title": "上半年反垄断执法交出半年答卷：办结案件13件，携程案罚没51.79亿元",
         "meta": "2026-08-19 ｜ 国家市场监督管理总局",
         "content": "截至7月，依法办结垄断协议和滥用市场支配地位案件13件。携程案：利用市场支配地位迫使酒店经营者接受独家合作和“全网最低价”，被责令停止违法行为、退还订单储备金1.22亿元、没收违法所得16.58亿元、罚款35.21亿元，合计51.79亿元。该案为平台经济领域反垄断“三合一”处罚首案，首次对激励性独家合作、“全网最低价”行为作出违法认定。同时，市场监管部门正有序开展电商平台补贴及外卖平台服务行业市场竞争状况调查评估。",
         "analysis": "“全网最低价”、独家合作、平台补贴竞争是当前执法重点；与供应商签订排他性价格条款的平台需高度警惕。", "url": "https://www.samr.gov.cn/xw/zj/art/2026/art_46d2c74cbd7249f189622dd030e3c3a7.html"},
        {"title": "市场监管总局：督促平台全面取消“仅退款”、解除“自动跟价”“强制运费险”等不合理限制",
         "meta": "2026-08 ｜ 国新办发布会（市场监管总局）",
         "content": "市场监管部门持续开展网络市场监管专项行动，共督促平台删除违法商品信息454.1万条，责令停止平台服务网店5.8万个次，查处涉网类案件10.5万件；督促网络交易平台全面取消“仅退款”、解除“自动跟价”“强制运费险”等不合理限制，要求外卖平台规范促销行为、理性参与竞争。",
         "analysis": "平台内规则（仅退款、跟价、运费险）监管收紧，平台企业须重新审视相关规则设置的合法性与合理性。", "url": "https://www.samr.gov.cn/"},
    ]),
    ("价格合规", [
        {"title": "虚构“划线价”典型案件：37.9元团购价配570元虚构原价被查处",
         "meta": "2026-08-18 ｜ 山东省市场监管部门",
         "content": "某商户在网络平台销售团购项目，对外标示团购现价37.9元，页面虚构划线原价570元制造巨大优惠假象，实际线下门店真实定价399元，经营过程中从未产生过570元成交记录。监管部门核查后认定构成价格欺诈。法律依据：《明码标价和禁止价格欺诈规定》第19条第3项（虚假折价、减价或价格比较），《价格法》《反不正当竞争法》《电子商务法》等；消费者可依《消费者权益保护法》第55条主张“退一赔三”。",
         "analysis": "划线价、原价对比必须有真实交易记录支撑，虚构原价构成价格欺诈且面临退一赔三风险——朴朴线上促销、满减、划线价展示须重点自查。", "url": "http://amr.shandong.gov.cn/"},
        {"title": "多地开展旅游旺季价格秩序专项整治",
         "meta": "2026-08-18 ｜ 贵州、亳州等地市场监管部门",
         "content": "贵州市场监管系统聚焦景区门票、住宿、餐饮、购物等重点领域，重点查处不按规定明码标价、价格欺诈，整治“两套菜单”、低价诱骗高价结算等乱象。亳州市监局针对药博会期间酒店住宿发布价格提醒告诫函，严禁模糊标价、低价引流、设置隐性收费，不得在公示价外另行加价。",
         "analysis": "明码标价、禁止价格欺诈执法在重点时段、重点行业密集展开，线上预订平台价格展示规范需同步关注。", "url": "https://www.samr.gov.cn/"},
    ]),
    ("产品合规（食品安全）", [
        {"title": "福州台江区以朴朴为试点，创建“三化三全”无堂食网络餐饮监管模式",
         "meta": "2026-08-13 ｜ 福州市台江区市场监管局",
         "content": "以朴朴无堂食集中加工业态为试点：①制度化全链条建设——前移监管关口、逐项审核核心硬件，推动全市14家朴朴集中厨房统一对标落地；②智慧化全天候管控——全部朴朴门店AI监控系统与省级“互联网+明厨亮灶”平台数据直连，自动抓拍从业人员操作不规范、环境卫生不达标、仓储温湿度异常等并实时预警；③精细化全环节共治——督促朴朴总部压实供应链主体责任，入驻商户落实进货查验、一品一码溯源，明确朴朴方对集中区内所有合作商食品安全负总责。",
         "analysis": "朴朴被树为监管样板的同时也承担了更高主体责任：AI监控直连、对合作商负总责、一品一码溯源，相关合规建设要求未来可能进一步标准化、全省推广。", "url": "http://paper.cfsn.cn/content/2026-08/13/content_193654.htm"},
        {"title": "福建首创全国首个省级食品安全“政企检”协同预警机制，朴朴电商签约",
         "meta": "2026-08-17/20 ｜ 福建省市场监管局",
         "content": "福建省市场监管局在福州连江县启动食品安全“政企检”协同预警机制，省产品质量检验研究院与永辉超市、福州朴朴电子商务有限公司签署合作协议。机制由市场监管部门统筹，整合省质检院技术优势与企业品控资源，将风险防控关口前移至食品入市销售之前，联合开展风险研判、技术攻关和质量帮扶。",
         "analysis": "朴朴作为签约企业深度参与监管协同机制，既是品牌信任资产，也意味着供应链品控数据需对监管透明共享；“一品一码”等溯源要求或将深化。", "url": "https://cfsn.cn/news/detail/35/362456.html"},
        {"title": "太原市监局凌晨突击夜查线上食品配送企业",
         "meta": "2026-08-19 ｜ 太原市小店区市场监管局、太原市市场监管局",
         "content": "聚焦七鲜、盒马、小象等头部线上配送企业，紧盯夜间集中到货入仓关键时段突击检查：全程跟进进货、分拣、备货、出库环节，核查食品来源、检验报告及承诺达标合格证；完成监督抽检10批次、快速检测19批次，重点排查肉制品、新鲜蔬菜、调味品的农药残留、兽药残留、非法添加；发现冷库温度监管记录不到位、食用农产品《承诺达标合格证》信息上传不及时等问题，督促企业立行立改。",
         "analysis": "前置仓/即时零售业态夜间监管补位，冷链温控记录、食用农产品合格证信息上传成为检查重点——同类业态企业应自查相关记录完整性与时效性。", "url": "http://scjg.taiyuan.gov.cn/"},
        {"title": "太原将生鲜前置仓纳入食用农产品常态化快检监管",
         "meta": "2026-08-20 ｜ 太原市市场监督管理局",
         "content": "太原在全省率先将快检服务延伸至大型连锁超市、生鲜前置仓和便民服务站点，将即时生鲜零售业态纳入常态化快检监管范畴；提出专项排查线上生鲜业态风险，聚焦外调蔬菜及豇豆、生姜等高风险品类加密抽检频次。",
         "analysis": "生鲜前置仓快速检测常态化趋势明确，线上生鲜平台农残阳性问题被点名，需强化进货验收自检能力。", "url": "http://scjg.taiyuan.gov.cn/"},
        {"title": "法治评论：织密新业态食品安全防护网",
         "meta": "2026-08-18 ｜ 法治日报（法治网）",
         "content": "针对无堂食外卖、直播带货、社区团购等新业态提出监管建议：量化“阴阳地址”“多店一证”禁则，明确速食包使用公示、健康证电子核验、配送温控要求；针对社区团购推行团长备案制，明确提货点贮存条件、生鲜“一品一码”溯源要求；压实平台对入驻主体的资质审核连带责任。",
         "analysis": "速食包公示、配送温控、一品一码溯源等要求或从建议走向立法，前置仓企业可提前布局相关管理能力。", "url": "http://www.legaldaily.com.cn/"},
    ]),
    ("灵活用工", [
        {"title": "厦门发布全省首份外卖配送行业公约",
         "meta": "2026-08-20 ｜ 厦门市市场监管局、人社局、交警支队指导",
         "content": "《厦门市外卖配送行业公约》由美团外卖、淘宝闪购、京东外卖三家平台现场签约。核心内容：明确摒弃“最严算法”，通过“算法取中”等方式合理确定订单数量、准时率、在线率等考核要素，科学设定订单量与配送时限，建立申诉补时机制；确保专职外卖配送员正常劳动所得不低于当地最低工资标准；依法落实社保参保，探索多样化商业保险保障。",
         "analysis": "“摒弃最严算法”、最低工资保障、社保参保要求或向其他城市推广，涉及自建/第三方配送体系的平台需关注履约模式调整。", "url": "https://www.cnr.cn/xmfw/gstjxm/20260820/t20260820_527783305.shtml"},
        {"title": "“新就业形态劳动者基本权益保障办法”正在抓紧制定",
         "meta": "2026-08-19 ｜ 法治日报（记者梳理）",
         "content": "国家层面正抓紧制定“新就业形态劳动者基本权益保障办法”；人社部“十五五”规划提出建立平台企业用工情况报告制度，完善平台劳动规则和算法监管制度；全总“十五五”规划部署推进平台企业算法和劳动规则协商。京东已宣布全职骑手100%签订正式劳动合同、缴纳五险一金。",
         "analysis": "平台用工规则立法提速，用工模式（自营/众包/劳务派遣）与责任边界将更明确，需提前评估用工合规成本。", "url": "https://www.mohrss.gov.cn/"},
    ]),
]

penalties = [
    ("08-19/20", "中央网信办、工信部、公安部", "400余款App、SDK", "违规收集使用个人信息", "下架等处置处罚"),
    ("08-15/17", "国家计算机病毒应急处理中心", "75款移动应用", "未弹窗提示隐私政策、未逐一列明收集使用信息等", "公开通报"),
    ("08月第1批", "工业和信息化部", "22款APP及SDK", "违规收集个人信息、强制自动续费、恶意跳转、过度索取权限", "通报并责令整改"),
    ("08月第五期", "川渝两地通管局", "10款APP/小程序", "SDK未披露、个人信息清单未明示、权限索取未告知目的", "通报限期整改"),
    ("07-25", "市场监管总局", "携程", "滥用市场支配地位（独家合作、“全网最低价”）", "罚没51.79亿元+退储备金1.22亿元"),
    ("08-18", "山东省市场监管部门", "某网络团购商户", "虚构划线价570元，价格欺诈", "依法查处（或涉退一赔三）"),
]

pupu_items = [
    ("食品安全监管全面升级（福州“台江样板”+福建“政企检”+太原夜查）", "高",
     "采购/仓储/集中加工/线上运营/配送",
     "朴朴已被纳入无堂食集中加工监管试点与省级“政企检”预警机制签约企业，AI监控直连省级平台、对合作商负总责、一品一码溯源等要求持续深化；同类业态（七鲜、盒马、小象）已被突击夜查，冷链温控与合格证上传成检查重点。",
     "①主动配合“政企检”机制，完善供应链一品一码溯源与品控数据共享；②全面自查各仓/厨房冷链温控记录完整性、食用农产品承诺达标合格证上传及时性；③关注速食包使用公示、配送温控等立法动向，提前布局。"),
    ("价格合规（虚构“划线价”典型案件警示）", "高",
     "线上运营/营销/客服",
     "虚构划线价、原价对比无真实成交支撑将被认定为价格欺诈，面临行政处罚与“退一赔三”民事赔偿双重风险；线上促销、满减、低价宣传为执法重点。",
     "①全面核查App内划线价、原价、促销价的定价依据，确保有真实成交记录支撑；②规范“历史最低价”“全网最低价”类宣传用语；③促销规则（满减、优惠券）清晰公示，避免误导性表述。"),
    ("个人信息保护专项行动常态化", "中高",
     "会员体系/线上运营/客服/营销推送",
     "会员数据、收货地址、订单数据、广告/用户画像收集须明确告知；未提供个性化广告关闭选项已被列为整改重点；小程序与SDK同受检测。",
     "①核查隐私政策是否逐项列明收集目的、方式、范围及第三方SDK清单；②提供个性化广告/推荐关闭选项；③营销推送须符合个保法“告知-同意”要求。"),
    ("算法合规（调度决策类备案+算法协商）", "中",
     "配送/仓储调度/线上运营",
     "配送派单、运力调度、物流调度属于调度决策类算法，需评估算法备案义务；《平台劳动规则和算法协商指引》要求订单分配、收入抽成、工作时长等纳入协商范围。",
     "①梳理自研/第三方算法清单，评估调度决策类算法备案义务；②建立算法安全自评估与公示机制；③关注平台算法协商机制建设要求。"),
    ("灵活用工与骑手权益保障", "中高",
     "配送/人力/用工合规",
     "厦门公约明确摒弃“最严算法”、保障最低工资与社保；“新就业形态劳动者基本权益保障办法”制定中，平台用工规则立法提速。",
     "①对标厦门公约优化配送考核算法，建立申诉补时机制；②评估骑手用工模式（自营/众包/劳务派遣）的责任边界与社保、职业伤害保障成本；③关注“新就业形态劳动者基本权益保障办法”出台动态。"),
    ("平台规则监管收紧（反垄断+仅退款/跟价）", "中",
     "平台业务/商家管理",
     "“全网最低价”、独家合作、平台补贴竞争为反垄断执法重点；平台“仅退款”“自动跟价”“强制运费险”等不合理限制被要求取消。",
     "①避免对供应商施加“全网最低价”、独家供货等排他性要求；②审查平台内补贴、跟价、退款规则的合规性；③健全平台反垄断合规管理制度。"),
]

risks = [
    "食品安全“一品一码”溯源、配送温控、速食包公示等要求或从地方试点走向全国立法",
    "《新就业形态劳动者基本权益保障办法》等平台用工立法即将出台",
    "生成式AI“备案+登记”分类管理与多部门联审机制或向全国推广",
    "数据产权登记指引落地，数据资产入表提速，企业数据治理合规要求上升",
    "反垄断执法常态化，“全网最低价”、平台补贴等价格竞争行为监管持续收紧",
]

matrix_rows = [
    ["食品安全",   "高", "高", "中", "中", "—", "—"],
    ["价格合规",   "—", "—", "高", "—", "中", "—"],
    ["个人信息",   "—", "—", "高", "中", "高", "—"],
    ["算法合规",   "—", "—", "中", "中", "中", "中"],
    ["灵活用工",   "—", "—", "—", "高", "—", "高"],
    ["平台规则",   "—", "—", "中", "—", "—", "—"],
]

# ============================================================ 组装
def build(all_text_provider):
    F = subset_fonts(all_text_provider())
    S = build_styles(F)
    story = []

    # ---------- 封面标题区（投行研报风格：品牌条 + 英文副标 + 报告信息） ----------
    n_domain_items = sum(len(items) for _, items in domains)
    story.append(brand_bar(S))
    story.append(Spacer(1, 18))
    story.append(Paragraph("DAILY COMPLIANCE BRIEF", S["brand"]))
    story.append(Paragraph(DATE_STR, S["date"]))
    story.append(Paragraph(SUBTITLE, S["subtitle"]))
    story.append(Paragraph("朴朴超市 · 法务合规部", S["org"]))
    story.append(Paragraph("守护合规底线 · 支撑业务决策", S["motto"]))
    story.append(Paragraph(
        f"本期导读：领域动态 {n_domain_items} 条 · 通报处罚 {len(penalties)} 起 · "
        f"朴朴专题 {len(pupu_items)} 项 · 前瞻提示 {len(risks)} 条", S["toc"]))
    story.append(Spacer(1, SP_XS))
    story.append(HRFlowable(width="100%", thickness=1.6, color=NAVY, spaceAfter=1))
    story.append(HRFlowable(width="100%", thickness=0.4, color=LGRAY, spaceAfter=SP_M))

    # ---------- 目录（TableOfContents 自动收集章节页码） ----------
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle(
        "toc1", fontName=F["songb"], fontSize=11, leading=24,
        textColor=NAVY, leftIndent=10, firstLineIndent=-10,
        spaceBefore=2, spaceAfter=2, wordWrap="CJK")]
    story.append(h1_block("目　录", S, toc=False))
    story.append(Spacer(1, SP_S))
    story.append(toc)
    story.append(Spacer(1, SP_M))

    # ---------- 一、今日重点速览（核心观点框，KeepTogether 防分页） ----------
    key_rows = [[Paragraph(f"<font name='{HEITI}' color='#1F3B63'>{i}.</font>　{s}", S["listitem"])]
                for i, s in enumerate(summary, 1)]
    key_table = Table(key_rows, colWidths=[CONTENT_W])
    key_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BG_KEY),
        ("LINEBEFORE", (0,0), (0,-1), 2.2, NAVY),
        ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#D8DEE6")),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    story.append(KeepTogether([h1_block("一、今日重点速览", S), key_table]))

    # ---------- 二、六大合规领域动态 ----------
    story.append(Spacer(1, SP_S))
    story.append(h1_block("二、六大合规领域动态", S))
    for di, (domain, items) in enumerate(domains):
        story.append(Paragraph(f"<font color='#1F3B63'>{di+1}.</font>　{domain}", S["h2"]))
        for ii, item in enumerate(items):
            story.append(Paragraph(f"<font color='#1F3B63'>{MARK}</font>{item['title']}", S["h3"]))
            story.append(Paragraph(item["meta"], S["meta"]))
            story.append(Paragraph(link_html(item.get("url", "")), S["link"]))
            story.append(Paragraph(f"<font name='{HEITI}' color='#3A6B8F'>【内容】</font>{item['content']}", S["bodyc"]))
            story.append(analysis_block(item["analysis"], S, "解读"))
            if item["title"].startswith("虚构“划线价”"):
                story.append(Spacer(1, SP_S))
                story.append(KeepTogether([fig2_price(F),
                                           Paragraph("图1：价格欺诈认定与责任链条", S["fig"]),
                                           Paragraph("资料来源：依据公开监管通报与处罚决定书整理，详见各条原文链接", S["src"])]))
            story.append(divider())

    # ---------- 三、监管通报与处罚速览 ----------
    story.append(Spacer(1, SP_L))
    story.append(h1_block("三、监管通报与处罚速览", S))
    story.append(Spacer(1, SP_S))
    tdata = [[Paragraph(h, S["tc"]) for h in ["时间", "监管机构", "涉及对象", "违规事由", "处置措施"]]]
    for r in penalties:
        tdata.append([Paragraph(c, S["tc2"]) for c in r])
    table = Table(tdata, colWidths=[2.3*cm, 3.6*cm, 2.5*cm, 5.2*cm, 3.0*cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#D8DEE6")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, ZEBRA]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, SP_M))
    story.append(KeepTogether([fig1_enforcement(F),
                               Paragraph("图2：监管执法处置流程（通报—整改—复查—处置—公示）", S["fig"]),
                               Paragraph("资料来源：依据公开监管通报与处罚决定书整理，详见各条原文链接", S["src"])]))

    # ---------- 四、朴朴超市业务专题 ----------
    story.append(Spacer(1, SP_S))
    story.append(h1_block("四、朴朴超市业务专题分析", S))
    story.append(Paragraph("说明：本板块聚焦与朴朴超市（生鲜电商/前置仓即时零售）业务直接相关的监管动态，"
                           "逐项评估合规风险等级（高/中/低）并给出应对建议。", S["note"]))
    story.append(KeepTogether([fig3_matrix(F, matrix_rows),
                               Paragraph("图3：朴朴超市合规风险热力矩阵（按风险主题 × 业务环节）", S["fig"]),
                               Paragraph("资料来源：朴朴超市法务合规部基于公开监管动态内部评估", S["src"])]))
    story.append(legend_paragraph(S))

    for pi, (title, risk, scope, impact, action) in enumerate(pupu_items):
        rc = {"高": RED, "中高": ORANGE, "中": AMBER, "低": GREEN}.get(risk, GRAY)
        story.append(Paragraph(f"<font color='#1F3B63'>{MARK}</font>{title}"
                               f"　<font color='#{rc.hexval()[2:]}'>【风险等级：{risk}】</font>", S["h3"]))
        story.append(Paragraph(f"<font name='{HEITI}' color='#3A6B8F'>涉及业务环节：</font>{scope}", S["body0"]))
        story.append(Paragraph(f"<font name='{HEITI}' color='#1F3B63'>影响分析：</font>{impact}", S["bodyc"]))
        story.append(analysis_block(action, S, "应对建议"))
        story.append(divider())

    story.append(Spacer(1, SP_S))
    story.append(KeepTogether([fig4_govern(F),
                               Paragraph("图4：福建食品安全“政企检”协同预警机制架构", S["fig"]),
                               Paragraph("资料来源：福建省市场监管局“政企检”协同预警机制公开信息", S["src"])]))

    # ---------- 五、前瞻合规风险提示 ----------
    story.append(Spacer(1, SP_S))
    story.append(h1_block("五、前瞻合规风险提示", S))
    for i, r in enumerate(risks, 1):
        story.append(Paragraph(f"<font name='{HEITI}' color='#1F3B63'>{i}.</font>　{r}", S["listitem"]))

    # ---------- 信息来源与免责声明（固定尾部栏，对齐中信研报尾部声明） ----------
    story.append(Spacer(1, SP_L))
    story.append(Paragraph("信息来源与免责声明", S["h3"]))
    disc_text = (
        "一、信息来源：本简报内容基于公开网络检索整理的监管机构官方网站通报、公告、处罚决定书及权威媒体报道，"
        "各条动态均附原文链接，便于溯源核验。<br/>"
        "二、用途限制：本简报仅供朴朴超市内部合规参考，不构成法律意见或决策依据；据此采取具体合规措施前，"
        "请咨询法务或外部专业律师。<br/>"
        "三、时效性：监管政策与执法动态更新较快，本简报截至生成时点整理，不排除后续修订或新发文件导致内容变化，"
        "请以最新官方发布为准。<br/>"
        "四、版权：本简报由自动化任务生成，引用内容著作权归原发布机构所有。"
    )
    disc = Paragraph(disc_text, S["body0"])
    disc_box = Table([[disc]], colWidths=[CONTENT_W])
    disc_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BG_KEY),
        ("LINEBEFORE", (0,0), (0,-1), 2.2, NAVY),
        ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#D8DEE6")),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    story.append(disc_box)
    story.append(Spacer(1, SP_M))

    # ---------- 尾注 ----------
    story.append(HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=SP_S))
    story.append(Paragraph(FOOTER_NOTE, S["footer"]))

    # ---------- 输出 ----------
    os.makedirs(OUT_DIR, exist_ok=True)
    pdf_path = os.path.join(OUT_DIR, "合规资讯简报_2026-08-21.pdf")
    doc = ComplianceDoc(pdf_path, pagesize=A4,
                        leftMargin=M_L, rightMargin=M_R,
                        topMargin=M_T+0.4*cm, bottomMargin=M_B+0.6*cm,
                        title=DOC_TITLE, author="WorkBuddy 合规自动化")
    doc.multiBuild(story, canvasmaker=NumberedCanvas, onFirstPage=header_footer, onLaterPages=header_footer)
    print(f"PDF saved: {pdf_path}")

def collect_all_text():
    """收集全部文本（正文数据 + 全部界面文字），确保子集字体不缺字"""
    parts = [DOC_TITLE, DATE_STR]
    parts.extend(summary)
    for domain, items in domains:
        parts.append(domain)
        for it in items:
            parts.extend([it["title"], it["meta"], it["content"], it["analysis"]])
    for r in penalties:
        parts.extend(r)
    for title, risk, scope, impact, action in pupu_items:
        parts.extend([title, risk, scope, impact, action])
    parts.extend(risks)
    for row in matrix_rows:
        parts.extend(row)
    parts.extend(["日常监测 · 专项行动", "发现问题线索", "责令整改 · 约谈告诫", "整改复查",
                  "合格 → 结案销号", "不合格 → 通报 · 下架 · 罚款",
                  "处罚信息公示 · 纳入信用记录 · 典型案例发布",
                  "虚构“划线价”：团购37.9元 / 假原价570元", "制造巨大优惠假象", "认定构成价格欺诈",
                  "法律依据：《明码标价和禁止价格欺诈规定》第19条",
                  "行政责任：责令改正 · 没收违法所得 · 罚款", "民事责任：消费者可主张“退一赔三”",
                  "合规要点：划线价/原价对比须有真实成交记录支撑，禁止虚构原价",
                  "福建省市场监管局（统筹协调 · 牵头组织）", "省产品质量检验研究院 技术支撑 · 风险研判",
                  "朴朴电商（签约企业）品控资源 · 数据共享", "永辉超市等企业 联合参与 · 协同共治",
                  "风险防控关口前移至食品入市销售之前 “一品一码”溯源 · 品控数据对监管透明共享",
                  "风险主题", "采购", "仓储/加工", "线上运营", "配送", "会员营销", "用工"])
    return "".join(parts)

if __name__ == "__main__":
    build(collect_all_text)
