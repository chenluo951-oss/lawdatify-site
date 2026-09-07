#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《合规资讯》深度分析版 PDF 生成器
在简版（weekly_data_*）基础上叠加：六大领域深度分析、行业水位调研、
违规与合规案例参考、关联延伸。日报≥30页、周报≥50页、月报≥80页。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_report_pdf as G
import deep_data as DD
_BASEMOD = sys.argv[1] if len(sys.argv) > 1 else "weekly_data"
WD = __import__(_BASEMOD)
from reportlab.platypus import (Paragraph, Spacer, Table, TableStyle, HRFlowable,
                                KeepTogether, PageBreak)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm

NAVY, NAVY2, INK, GRAY, LGRAY = G.NAVY, G.NAVY2, G.INK, G.GRAY, G.LGRAY
RED, ORANGE, AMBER, GREEN = G.RED, G.ORANGE, G.AMBER, G.GREEN
BG_H1, BG_ANA, EDGE_ANA, ZEBRA, BG_KEY = G.BG_H1, G.BG_ANA, G.EDGE_ANA, G.ZEBRA, G.BG_KEY
OUT_DIR, CONTENT_W = G.OUT_DIR, G.CONTENT_W
M_L, M_R, M_T, M_B = G.M_L, G.M_R, G.M_T, G.M_B
PAGE_W, PAGE_H = G.PAGE_W, G.PAGE_H
SP_XS, SP_S, SP_M, SP_L = G.SP_XS, G.SP_S, G.SP_M, G.SP_L

DEEP_SECTIONS = ["六大领域深度分析", "行业水位调研", "违规与合规案例参考", "关联延伸"]


def _gb2312_chars():
    """GB2312 全量汉字（6763 字）兜底，彻底杜绝字体子集化漏字形（缺字/P0 致命）。"""
    out = []
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.append(bytes([hi, lo]).decode("gb2312"))
            except Exception:
                pass
    return "".join(out)


# 兜底字符集：界面固定文案 + 常见合规术语 + 特殊符号（含 en dash 等排版符号）
SAFE_CHARS = (
    "日报周报月报深度分析版本期导读本期处罚统计小结本期监管与合规动态每日监管与合规动态"
    "六大领域深度分析行业水位调研违规与合规案例参考关联延伸深度情景展望"
    "数据合规人工智能算法备案生成式深度合成调度决策外卖派单运力调度"
    "平台资质实质审查入网商户供应商核验冷食类经营许可"
    "产品合规食品安全监督抽检农兽药残留二氧化硫苯甲酸噻虫嗪五氯酚酸钠甜蜜素酸价"
    "价格合规虚构划线价明码标价动态定价差别定价不正当价格行为价格欺诈"
    "个人信息保护专项行动侵害用户权益注销功能投诉举报渠道下架复测"
    "网络数据安全风险评估办法重要数据处理者分类分级"
    "智能客服国家标准转人工承诺算法生成内容标识"
    "公平竞争政策宣传周反垄断合规指引全网最低价二选一"
    "即时零售前置仓生鲜电商配送会员营销用工采购仓储加工线上运营"
    "风险热力矩阵涉及业务环节影响分析应对建议风险等级高高中中中低"
    "原文链接来源文号要点解读里程碑交付物阶段时间窗重点任务维度"
    "一二三四五六七八九十百千万亿第章节目附录图表注尾页共页"
    "◆▍■●○→↓↘↙←↑＋－／＼（）〔〕【】《》「」『』""''、。，；：？！…—–－·　"
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "
    )

# ============================================================ 深度版尾注前三索引附录（对齐对标库第三批 D① / 建议 10）
INDEX_GLOSSARY = [
    ("AIGC", "生成式人工智能内容（AI Generated Content），含文本、图像、音视频的合成生成。"),
    ("算法备案", "互联网信息服务算法推荐合规备案（国家网信办），涉及排序、推荐、生成合成等算法。"),
    ("PIPL", "《中华人民共和国个人信息保护法》，个人信息处理活动的上位法依据。"),
    ("前置仓", "贴近社区的小型仓储履约节点，是即时零售生鲜电商的核心履约形态。"),
    ("即时零售", "线上下单、就近履约、分钟级送达的本地零售模式。"),
    ("明码标价", "经营者标价应当真实、明确、无歧义的价格合规基本要求。"),
    ("合规水位", "内部对照监管要求的合规达标程度标尺，用于横向评估与差距识别。"),
]

def _idx_table_style():
    """三索引附录通用表样式（对齐深度版其他表格：藏蓝表头 + 网格 + 斑马纹 + 顶线）。"""
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ])

def index_appendix_text(base_data):
    """收集「三索引附录」全部渲染文本，供 subset_fonts 子集化，杜绝 tofu。
    纯展示：法规依据索引 / 官方来源索引 全部源自本期数据，术语表为固定对照，不引入业务内容数据。"""
    parts = ["附录", "索引与术语对照", "本附录在尾注前集中提供三项可追溯索引，便于内部核验与跨期比对。",
             "一、法规依据索引", "本期简报所引述、对照的主要法规与监管文件（按领域归类）：",
             "领域", "法规 / 监管文件",
             "二、官方来源索引", "来源说明", "官方链接",
             "本期共引用官方来源", "条（均为具体通报 / 公告 / 处罚决定书深链，正文各条附可点击原文链接）：",
             "三、术语表", "术语", "释义"]
    for domain, items in base_data["policy"]:
        parts.append(domain)
        for it in items:
            parts.append(it["title"])
            if it.get("url"):
                parts.append(it["url"])
    for r in base_data["penalties"]:
        if len(r) > 5 and r[5]:
            parts.append(r[5])
            if len(r) > 1 and r[1]:
                parts.append(r[1])
    for term, desc in INDEX_GLOSSARY:
        parts.append(term); parts.append(desc)
    return "".join(parts)

def index_appendix(S, F, base_data):
    """深度版尾注前三索引（对齐对标库第三批 D① / 建议 10）：
    法规依据索引 / 官方来源索引 / 术语表。纯展示、全部源自本期数据或固定术语对照，不引入业务内容数据。
    返回 flowable 列表，由 build() 在「信息来源与免责声明」前插入。"""
    flow = []
    flow.append(G.h1_block("附录、索引与术语对照", S))
    flow.append(Paragraph("本附录在尾注前集中提供三项可追溯索引，便于内部核验与跨期比对。", S["note"]))
    flow.append(Spacer(1, SP_S))

    # ① 法规依据索引
    flow.append(Paragraph("一、法规依据索引", S["h2"]))
    flow.append(Paragraph("本期简报所引述、对照的主要法规与监管文件（按领域归类）：", S["note"]))
    reg_rows = [[Paragraph(h, S["tc"]) for h in ["领域", "法规 / 监管文件"]]]
    for domain, items in base_data["policy"]:
        for it in items:
            reg_rows.append([Paragraph(domain, S["tc2"]), Paragraph(it["title"], S["tc2"])])
    rt = Table(reg_rows, colWidths=[3.2 * cm, CONTENT_W - 3.2 * cm], repeatRows=1)
    rt.setStyle(_idx_table_style())
    flow.append(rt)
    flow.append(Spacer(1, SP_M))

    # ② 官方来源索引
    flow.append(Paragraph("二、官方来源索引", S["h2"]))
    src_entries = []
    for domain, items in base_data["policy"]:
        for it in items:
            if it.get("url"):
                src_entries.append((it["title"], it["url"]))
    for r in base_data["penalties"]:
        if len(r) > 5 and r[5]:
            label = r[1] if len(r) > 1 and r[1] else (r[0] if r else "")
            src_entries.append((label, r[5]))
    seen, uniq = set(), []
    for lbl, u in src_entries:
        if u not in seen:
            seen.add(u); uniq.append((lbl, u))
    flow.append(Paragraph(
        f"本期共引用官方来源 {len(uniq)} 条（均为具体通报 / 公告 / 处罚决定书深链，正文各条附可点击原文链接）：",
        S["note"]))
    src_rows = [[Paragraph(h, S["tc"]) for h in ["来源说明", "官方链接"]]]
    for lbl, u in uniq:
        src_rows.append([Paragraph(lbl, S["tc2"]), Paragraph(u, S["tc2"])])
    st = Table(src_rows, colWidths=[5.0 * cm, CONTENT_W - 5.0 * cm], repeatRows=1)
    st.setStyle(_idx_table_style())
    flow.append(st)
    flow.append(Spacer(1, SP_M))

    # ③ 术语表
    flow.append(Paragraph("三、术语表", S["h2"]))
    flow.append(Paragraph("本期涉及的常见合规缩略语与术语对照：", S["note"]))
    gl_rows = [[Paragraph(h, S["tc"]) for h in ["术语", "释义"]]]
    for term, desc in INDEX_GLOSSARY:
        gl_rows.append([Paragraph(term, S["tc2"]), Paragraph(desc, S["tc2"])])
    gt = Table(gl_rows, colWidths=[3.0 * cm, CONTENT_W - 3.0 * cm], repeatRows=1)
    gt.setStyle(_idx_table_style())
    flow.append(gt)
    return flow

def build(base_data, base_meta):
    all_text = _collect(base_data, base_meta) + "".join(
        [v for d in DD.DOMAIN_DEEP.values() for v in d.values()])
    for r in DD.INDUSTRY_SURVEY["rows"]:
        all_text += "".join(r)
    for c in DD.CASE_REFS:
        all_text += "".join(c)
    for _, paras in DD.FOCUS_TOPICS:
        all_text += "".join(paras)
    for name, prof in DD.PEER_PROFILES:
        all_text += name + prof
    for items in DD.CHECK_LISTS.values():
        all_text += "".join(items)
    for _, _, quotes in DD.REG_QUOTES:
        all_text += "".join(quotes)
    for r in DD.ROADMAP["rows"]:
        all_text += "".join(r)
    for r in DD.GAP_MATRIX["rows"]:
        all_text += "".join(r)
    for title, txt in DD.CASE_INTERP:
        all_text += title + txt
    for r in DD.TIMELINE:
        all_text += "".join(r)
    all_text += "".join(DD.GOV)
    all_text += "".join(DD.EXTENSIONS) + "".join(DD.DEEP_OUTLOOK)
    # ---- 补齐此前遗漏的表头 / 标题 / 键名，避免子集化漏字形 ----
    all_text += "".join(DD.INDUSTRY_SURVEY["cols"])
    all_text += "".join(DD.ROADMAP["cols"])
    all_text += "".join(DD.GAP_MATRIX["cols"])
    all_text += "".join(DD.DOMAIN_DEEP.keys())
    all_text += "".join(t for t, _ in DD.FOCUS_TOPICS)
    all_text += "".join(a + b for a, b, _ in DD.REG_QUOTES)
    all_text += "".join(DD.CHECK_LISTS.keys())
    all_text += "".join(k for d in DD.DOMAIN_DEEP.values() for k in d.keys())
    # ---- 兜底字符集：GB2312 全量汉字 + 常用符号，杜绝 Subsetter 漏字 ----
    all_text += SAFE_CHARS
    all_text += _gb2312_chars()
    # ---- 索引附录文本纳入子集化，杜绝新块 tofu ----
    all_text += index_appendix_text(base_data)
    F = G.subset_fonts(all_text)
    S = G.build_styles(F)
    story = []

    # 封面
    n_policy = sum(len(items) for _, items in base_data["policy"])
    story.append(G.brand_bar(S, base_meta["title"] + "（深度分析版）",
                              base_meta.get("tagline", "深度分析版")))
    story.append(Spacer(1, 18))
    story.append(Paragraph(base_meta["brief_en"] + " · DEEP ANALYSIS", S["brand"]))
    story.append(Paragraph(base_meta["date_str"], S["date"]))
    story.append(Paragraph(base_meta["subtitle"] + " · 深度分析版", S["subtitle"]))
    story.extend(G.org_motto(S))
    story.append(Paragraph(
        f"本期导读：六大领域重点动态 {n_policy} 项 · 深度分析 6 领域（每领域 8 段）· 行业水位调研 1 篇 · "
        f"违规与合规案例参考 {len(DD.CASE_REFS)} 例 · 合规焦点专题 {len(DD.FOCUS_TOPICS)} 篇 · "
        f"自查清单 6 份 · 差距自评估矩阵 1 张 · 关联延伸 {len(DD.EXTENSIONS)} 条", S["toc"]))
    story.extend(G.issue_history_block(S, base_meta["date_str"]))
    _src_urls = {it.get("url") for _, items in base_data["policy"] for it in items if it.get("url")}
    _src_urls |= {p[5] for p in base_data["penalties"] if len(p) > 5 and p[5]}
    story.extend(G.compile_note(S, cutoff=base_meta["date_str"], n_src=len(_src_urls)))
    story.append(Spacer(1, SP_XS))
    story.append(HRFlowable(width="100%", thickness=1.6, color=NAVY, spaceAfter=1))
    story.append(HRFlowable(width="100%", thickness=0.4, color=LGRAY, spaceAfter=SP_M))

    # 目录
    toc = G.styled_toc(F)
    story.append(G.h1_block("目　录", S, toc=False))
    story.append(Spacer(1, SP_S))
    story.append(toc)
    story.append(Spacer(1, SP_M))

    # 一、综述（base）
    key_rows = [[Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{s}", S["listitem"])]
                for i, s in enumerate(base_data["summary"], 1)]
    kt = G.key_points_box(S, key_rows)
    story.append(KeepTogether([G.h1_block(base_meta["sections"]["summary"], S), kt]))

    # 二、六大领域动态回顾（base）
    story.append(Spacer(1, SP_S))
    story.append(G.h1_block(base_meta["sections"]["policy"], S))
    for di, (domain, items) in enumerate(base_data["policy"]):
        story.append(Paragraph(f"<font color='#1F3B63'>{di + 1}.</font>　{domain}", S["h2"]))
        for item in items:
            story.append(Paragraph(f"<font color='#1F3B63'>{G.MARK}</font>{item['title']}", S["h3"]))
            story.append(Paragraph(item["meta"], S["meta"]))
            story.append(Paragraph(G.link_html(item.get("url", "")), S["link"]))
            story.append(Paragraph(f"<font name='{G.HEITI}' color='#3A6B8F'>【要点】</font>{item['content']}", S["bodyc"]))
            story.append(G.analysis_block(item["analysis"], S, "解读"))
            story.append(G.divider())

    # 三、六大领域深度分析（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("六、六大领域深度分析", S))
    story.append(Paragraph("本板块对六大合规领域逐一展开：监管脉络与立法意图、对朴朴超市业务的影响传导路径、"
                           "同业水位与标杆做法、可落地的控制建议。", S["note"]))
    for di, (domain, _) in enumerate(base_data["policy"], 1):
        d = DD.DOMAIN_DEEP.get(domain)
        if not d:
            continue
        story.append(Spacer(1, SP_S))
        story.append(Paragraph(f"{di}. {domain} —— 深度分析", S["h2"]))
        for label, key in [("监管脉络与立法意图", "脉络"), ("对朴朴业务的影响传导路径", "影响路径"),
                           ("同业水位与标杆做法", "同业水位"), ("可落地控制建议", "控制建议"),
                           ("法条依据", "法条依据"), ("业务映射（朴朴）", "业务映射"),
                           ("风险信号与预警", "风险信号"), ("分阶段落地步骤", "落地步骤"),
                           ("判例与延展（真实案例参照）", "判例与延展")]:
            story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>▍{label}</font>", S["h3"]))
            story.append(Paragraph(d[key], S["bodyc"]))
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>▍分领域合规自查清单（可直接转化为内部检查表）</font>", S["h3"]))
        for item in DD.CHECK_LISTS.get(domain, []):
            story.append(Paragraph(f"<font name='{G.HEITI}' color='#3A6B8F'>✓</font> {item}", S["bodyc"]))
        story.append(G.divider())

    # 四、行业水位调研（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("七、行业水位调研", S))
    story.append(Paragraph("下表从九项合规维度，对比头部平台现行水位、中小平台常见短板，"
                           "并给出朴朴可达的目标水位，作为内部差距分析（Gap Analysis）基线。", S["note"]))
    rows = [[Paragraph(h, S["tc"]) for h in DD.INDUSTRY_SURVEY["cols"]]]
    for r in DD.INDUSTRY_SURVEY["rows"]:
        rows.append([Paragraph(c, S["tc2"]) for c in r])
    t = Table(rows, colWidths=[3.4 * cm, 4.7 * cm, 4.7 * cm, 4.8 * cm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    story.append(t)
    story.append(Spacer(1, SP_M))
    story.append(Paragraph("调研结论：头部平台已在数据分级、第三方 SDK 治理、资质实质审查、生鲜快检溯源四个维度形成明显领先；"
                           "朴朴应优先补齐“资质动态预警”与“批次快检硬门槛”两项高杠杆控制点，再以头部水位为中期目标。", S["bodyc"]))
    story.append(Spacer(1, SP_S))
    story.append(Paragraph("同业深度画像", S["h2"]))
    for name, prof in DD.PEER_PROFILES:
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>▍{name}</font>", S["h3"]))
        story.append(Paragraph(prof, S["bodyc"]))
    story.append(G.divider())

    # 四（补）、具像化合规参考图示与样例
    story.append(Spacer(1, SP_S))
    story.append(Paragraph("具像化合规参考图示与样例", S["h2"]))
    story.append(Paragraph("以下以可落地的图示与样例，将“行业水位”转译为可直接对照的准入流程与展示规范，便于业务侧按图执行。", S["note"]))
    story.append(Paragraph("① 行业合规水位对比（朴朴 vs 同业，按控制点）", S["h3"]))
    _wl = [
        ["资质动态预警（到期自动下架）", "待提升", "领先", "达标", "达标", "达标"],
        ["批次快检 + 一品一码溯源", "待提升", "领先", "领先", "达标", "达标"],
        ["算法备案公示（派单/推荐）", "待提升", "领先", "达标", "达标", "达标"],
        ["个性化广告关闭入口", "待提升", "领先", "达标", "达标", "领先"],
        ["隐私政策—行为一致性", "达标", "领先", "达标", "达标", "领先"],
        ["食安抽检应对速度", "达标", "领先", "领先", "达标", "达标"],
    ]
    story.append(G.fig_waterlevel(F, _wl))
    story.append(Paragraph("图1：行业合规水位对比矩阵（领先＝绿 / 达标＝黄 / 待提升＝红；朴朴当前相对短板集中于资质动态预警、批次快检、算法备案公示与个性化广告关闭四项）", S["fig"]))
    story.append(G.src_note("朴朴超市法务合规部基于同业公开合规实践对比评估", S))
    story.append(Spacer(1, SP_M))
    story.append(KeepTogether([
        Paragraph("② 监管要求对照自检矩阵（控制点 × 监管依据 / 自检要点 / 同业水位 / 优先级）", S["h3"]),
        G.fig_reg_matrix(F),
        Paragraph("图2：六大关键控制点监管要求对照自检矩阵——由监管依据落到自检要点，优先级列（红＝高 / 黄＝中 / 绿＝低）定位本期优先整改项", S["fig"]),
        G.src_note("依据现行法律法规及公开监管口径梳理，供业务方逐项自检", S),
    ]))
    story.append(Spacer(1, SP_M))
    story.append(Paragraph("③ 食安快检准入 SOP（具像化流程样例）", S["h3"]))
    story.append(G.fig_food_sop(F))
    story.append(Paragraph("图3：生鲜入库食安快检准入标准作业流程——资质与批次合格证明为硬门槛，快检不合格即一键下架召回", S["fig"]))
    story.append(G.src_note("依据《食品安全法》及各地市场监管局快检通报要求梳理", S))
    story.append(Spacer(1, SP_M))
    story.append(Paragraph("④ 价格展示合规自检清单样例（合规模板）", S["h3"]))
    story.append(G.fig_price_sample(F))
    story.append(Paragraph("图4：商品详情页价格展示合规示范——划线价/促销价/动态定价/免密支付逐项留痕可举证", S["fig"]))
    story.append(G.src_note("依据《明码标价和禁止价格欺诈规定》及典型处罚案例梳理", S))
    story.append(Spacer(1, SP_M))
    story.append(Paragraph("⑤ 六大合规领域要点框架（中枢统领六域）", S["h3"]))
    story.append(KeepTogether([G.fig_framework(F),
                               Paragraph("图5：朴朴超市六大合规领域要点框架（中枢统领六域，逐域落到可落地控制点）", S["fig"]),
                               G.src_note("朴朴超市法务合规部基于六大合规领域监管脉络梳理", S)]))
    story.append(G.divider())

    # 五、违规与合规案例参考（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("八、违规与合规案例参考", S))
    story.append(Paragraph("下表汇总本期及近期典型违规案例与可借鉴的合规标杆，供内部对照排查。"
                           "“违规”类提示雷区，“合规参考”类提示可复用做法。", S["note"]))
    crows = [[Paragraph(h, S["tc"]) for h in ["类型", "案例/实践", "来源/文号", "处置/效果", "对朴朴的启示"]]]
    for c in DD.CASE_REFS:
        crows.append([Paragraph(c[0], S["tc2"]), Paragraph(c[1], S["tc2"]),
                      Paragraph(c[2] + "<br/>" + G.link_html(c[5]), S["tc2"]), Paragraph(c[3], S["tc2"]),
                      Paragraph(c[4], S["tc2"])])
    ct = Table(crows, colWidths=[1.7 * cm, 4.6 * cm, 3.6 * cm, 3.4 * cm, 4.3 * cm], repeatRows=1)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    story.append(ct)

    # 六、监管通报与处罚汇总（base）
    story.append(PageBreak())
    story.append(G.h1_block(base_meta["sections"]["penalties"], S))
    story.append(Spacer(1, SP_S))
    pdata = [[Paragraph(h, S["tc"]) for h in ["时间", "监管机构", "涉及对象", "违规事由", "处置措施", "来源"]]]
    for r in base_data["penalties"]:
        cells = [Paragraph(c, S["tc2"]) for c in r[:5]]
        cells.append(Paragraph(G.link_html(r[5]), S["link"]))
        pdata.append(cells)
    pt = Table(pdata, colWidths=[1.5 * cm, 2.8 * cm, 3.2 * cm, 4.5 * cm, 2.7 * cm, 1.9 * cm], repeatRows=1)
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    story.append(pt)
    story.append(Spacer(1, SP_M))
    for i, s in enumerate(base_data["penalty_stats"], 1):
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{s}", S["listitem"]))

    # 七、朴朴超市业务专题（base）
    story.append(Spacer(1, SP_L))
    story.append(G.h1_block(base_meta["sections"]["pupu"], S))
    story.append(Paragraph("说明：本板块聚焦与朴朴超市（生鲜电商/前置仓即时零售）业务直接相关的监管动态，"
                           "逐项评估合规风险等级并给出应对建议。", S["note"]))
    # 热力矩阵：图 + 图注 + 资料来源 + 图例 整体 KeepTogether，确保图例不与矩阵分页 orphan
    story.append(KeepTogether([G.fig3_matrix(F, base_data["matrix_rows"]),
                               Paragraph("图6：朴朴超市合规风险热力矩阵（按风险主题 × 业务环节）", S["fig"]),
                               G.src_note(G.SRC_INTERNAL, S),
                               G.legend_paragraph(S)]))
    for title, risk, scope, impact, action in base_data["pupu_items"]:
        rc = {"高": RED, "中高": ORANGE, "中": AMBER, "低": GREEN}.get(risk, GRAY)
        story.append(Paragraph(f"<font color='#1F3B63'>{G.MARK}</font>{title}"
                               f"　<font color='#{rc.hexval()[2:]}'>【风险等级：{risk}】</font>", S["h3"]))
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#3A6B8F'>涉及业务环节：</font>{scope}", S["body0"]))
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>影响分析：</font>{impact}", S["bodyc"]))
        story.append(G.analysis_block(action, S, "应对建议"))
        story.append(G.divider())

    # 八（补）、合规焦点专题（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("九（补）、合规焦点专题", S))
    story.append(Paragraph("本板块针对与朴朴超市业务最相关的五项合规焦点，逐篇展开监管要点、对业务的映射与可落地控制清单。", S["note"]))
    for i, (title, paras) in enumerate(DD.FOCUS_TOPICS, 1):
        story.append(Spacer(1, SP_S))
        story.append(Paragraph(f"{i}. {title}", S["h2"]))
        for label, txt in [("监管要点", paras[0]), ("业务映射", paras[1]), ("控制清单", paras[2])]:
            story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>▍{label}</font>", S["h3"]))
            story.append(Paragraph(txt, S["bodyc"]))
        story.append(G.divider())

    # 十（补）、监管法规条文摘录（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("十（补）、监管法规条文摘录", S))
    story.append(Paragraph("本板块逐领域引述当前有效、与朴朴业务直接相关的关键条文，供内部对照自查。", S["note"]))
    for dom, src, quotes in DD.REG_QUOTES:
        story.append(Spacer(1, SP_S))
        story.append(Paragraph(f"▍{dom} —— {src}", S["h3"]))
        for q in quotes:
            story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>·</font>　{q}", S["bodyc"]))
        story.append(G.divider())

    # 十一（补）、90 天合规落地路线图（NEW）
    story.append(Spacer(1, SP_L))
    story.append(G.h1_block("十一（补）、90 天合规落地路线图", S))
    story.append(Paragraph("结合本期风险研判，给出分三阶段、可落地的合规加固路线，作为内部排期基线。", S["note"]))
    rrows = [[Paragraph(h, S["tc"]) for h in DD.ROADMAP["cols"]]]
    for r in DD.ROADMAP["rows"]:
        rrows.append([Paragraph(c, S["tc2"]) for c in r])
    rt = Table(rrows, colWidths=[3.0 * cm, 2.6 * cm, 6.6 * cm, 5.0 * cm], repeatRows=1)
    rt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    story.append(rt)

    # 十二（补）、合规差距自评估矩阵（NEW）
    story.append(Spacer(1, SP_L))
    story.append(G.h1_block("十二（补）、合规差距自评估矩阵", S))
    story.append(Paragraph("下表将六大领域关键控制点转化为可排期的内部自查表。状态采用“建议口径”（建议启动／待建／"
                           "待核查／进行中／部分存在），便于后续据实更新；责任归属与目标时间窗供跨部门对齐，"
                           "建议每月滚动复核一次，并将完成进度回填本表。", S["note"]))
    grows = [[Paragraph(h, S["tc"]) for h in DD.GAP_MATRIX["cols"]]]
    for r in DD.GAP_MATRIX["rows"]:
        grows.append([Paragraph(c, S["tc2"]) for c in r])
    gt = Table(grows, colWidths=[2.4 * cm, 5.6 * cm, 3.0 * cm, 3.0 * cm, 3.0 * cm], repeatRows=1)
    gt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    story.append(gt)

    # 十三（补）、案例深度解读（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("十三（补）、案例深度解读", S))
    story.append(Paragraph("本板块对本期重点案例作延伸剖析，提炼对朴朴超市可直接复用的控制启示。", S["note"]))
    for title, txt in DD.CASE_INTERP:
        story.append(Spacer(1, SP_S))
        story.append(Paragraph(f"▍{title}", S["h3"]))
        story.append(Paragraph(txt, S["bodyc"]))

    # 十四（补）、监管关键节点与合规日历（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("十四（补）、监管关键节点与合规日历", S))
    story.append(Paragraph("下表将关键监管节点与内部排期对齐，供跨部门排期基线参考。", S["note"]))
    trows = [[Paragraph(h, S["tc"]) for h in ["时间窗", "监管/内部节点", "朴朴应对动作"]]]
    for r in DD.TIMELINE:
        trows.append([Paragraph(c, S["tc2"]) for c in r])
    tt = Table(trows, colWidths=[2.8 * cm, 6.8 * cm, 7.6 * cm], repeatRows=1)
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    story.append(tt)

    # 十五（补）、合规治理与组织职责建议（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("十五（补）、合规治理与组织职责建议", S))
    story.append(Paragraph("本板块供内部搭建合规治理框架参照，可按实际组织情况裁剪。", S["note"]))
    for txt in DD.GOV:
        story.append(Paragraph(txt, S["bodyc"]))
        story.append(Spacer(1, SP_XS))

    # 八、关联延伸（NEW）
    story.append(PageBreak())
    story.append(G.h1_block("九、关联延伸", S))
    story.append(Paragraph("本板块将分散的合规议题跨领域联动，识别风险叠加点与治理复用机会。", S["note"]))
    for i, r in enumerate(DD.EXTENSIONS, 1):
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{r}", S["listitem"]))

    # 九、前瞻（base + deep）
    story.append(Spacer(1, SP_S))
    story.append(G.h1_block(base_meta["sections"]["outlook"], S))
    for i, r in enumerate(base_data["outlook"], 1):
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{r}", S["listitem"]))
    story.append(Spacer(1, SP_XS))
    story.append(Paragraph("深度情景展望：", S["h3"]))
    for i, r in enumerate(DD.DEEP_OUTLOOK, 1):
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{r}", S["listitem"]))

    # 十六（补）、附录三索引（对齐对标库第三批 D① / 建议 10：法规依据索引 / 官方来源索引 / 术语表）
    story.append(PageBreak())
    story.extend(index_appendix(S, F, base_data))

    # 信息来源与免责声明（固定尾部栏）
    story.append(Spacer(1, SP_L))
    story.append(Paragraph("信息来源与免责声明", S["h3"]))
    story.append(G.disclaimer_block(S, "本报告"))

    # 尾注
    story.append(Spacer(1, SP_M))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=SP_S))
    story.append(Paragraph("— 本报告为深度分析版，内容基于公开网络信息检索与行业研究整理，仅供参考，不构成法律意见 —", S["footer"]))

    os.makedirs(OUT_DIR, exist_ok=True)
    deep_name = base_meta["filename"].replace(".pdf", "_深度分析版.pdf")
    pdf_path = os.path.join(OUT_DIR, deep_name)
    doc = G.ComplianceDoc(pdf_path, pagesize=G.A4,
                          leftMargin=M_L, rightMargin=M_R,
                          topMargin=M_T + 0.4 * cm, bottomMargin=M_B + 0.6 * cm,
                          title=base_meta["title"] + "（深度分析版）", author="WorkBuddy 合规自动化")
    hf = G.make_header_footer(base_meta["header_text"] + " · 深度分析版", base_meta["date_str"])
    doc.multiBuild(story, canvasmaker=G.NumberedCanvas, onFirstPage=hf, onLaterPages=hf)
    print(f"PDF saved: {pdf_path}")
    return pdf_path

def _collect(base_data, base_meta):
    parts = [base_meta["title"], base_meta["date_str"], base_meta["header_text"], base_meta["subtitle"],
             base_meta["brief_en"], base_meta["filename"], base_meta["tagline"], "目　录",
             "六大领域深度分析", "行业水位调研", "违规与合规案例参考", "关联延伸", "深度情景展望"]
    parts.extend(list(base_meta["sections"].values()))
    parts.extend(base_data["summary"])
    for domain, items in base_data["policy"]:
        parts.append(domain)
        for it in items:
            parts.extend([it["title"], it["meta"], it["content"], it["analysis"], it.get("url", "")])
    for r in base_data["penalties"]:
        parts.extend(r)
    parts.extend(base_data["penalty_stats"])
    for t in base_data["pupu_items"]:
        parts.extend(t)
    parts.extend(base_data["outlook"])
    return "".join(parts)

if __name__ == "__main__":
    build(WD.DATA, WD.META)
