#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《合规资讯周报》PDF 生成器（五章节：综述/六大领域/通报处罚/朴朴专题/下周前瞻）
复用 gen_report_pdf 排版引擎 v6.2。独立子进程运行，避免 reportlab 跨文档字体缓存污染。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_report_pdf as G
_DATAMOD = sys.argv[1] if len(sys.argv) > 1 else "weekly_data"
WD = __import__(_DATAMOD)
from reportlab.platypus import (Paragraph, Spacer, Table, TableStyle, HRFlowable,
                                KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm

NAVY, NAVY2, INK, GRAY, LGRAY = G.NAVY, G.NAVY2, G.INK, G.GRAY, G.LGRAY
RED, ORANGE, AMBER, GREEN = G.RED, G.ORANGE, G.AMBER, G.GREEN
BG_H1, BG_ANA, EDGE_ANA, ZEBRA, BG_KEY = G.BG_H1, G.BG_ANA, G.EDGE_ANA, G.ZEBRA, G.BG_KEY
OUT_DIR, CONTENT_W = G.OUT_DIR, G.CONTENT_W
M_L, M_R, M_T, M_B = G.M_L, G.M_R, G.M_T, G.M_B
PAGE_W, PAGE_H = G.PAGE_W, G.PAGE_H
SP_XS, SP_S, SP_M, SP_L = G.SP_XS, G.SP_S, G.SP_M, G.SP_L

SAFE_CHARS = (
    "周报本周综述六大领域动态回顾监管通报处罚汇总朴朴超市业务专题下周前瞻尾注"
    "一二三四五六七八九十"
    "数据合规人工智能算法备案生成式深度合成调度决策外卖派单运力调度"
    "平台资质实质审查入网商户供应商核验冷食类经营许可"
    "产品合规食品安全监督抽检农兽药残留二氧化硫苯甲酸噻虫嗪五氯酚酸钠甜蜜素酸价"
    "价格合规虚构划线价明码标价动态定价差别定价不正当价格行为价格欺诈"
    "个人信息保护专项行动侵害用户权益注销功能投诉举报渠道下架复测"
    "网络数据安全风险评估办法重要数据处理者分类分级"
    "智能客服国家标准转人工承诺算法生成内容标识"
    "公平竞争政策宣传周反垄断合规指引全网最低价二选一"
    "即时零售前置仓生鲜电商配送会员营销用工采购仓储加工线上运营"
    "风险热力矩阵涉及业务环节影响分析应对建议"
    "原文链接来源文号要点解读"
)

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

def build(data, meta):
    all_text = _collect(data, meta) + SAFE_CHARS + _gb2312_chars()
    F = G.subset_fonts(all_text)
    S = G.build_styles(F)
    story = []

    # ---------- 封面 ----------
    n_policy = sum(len(items) for _, items in data["policy"])
    story.append(G.brand_bar(S, meta["title"], meta.get("tagline", "每周监管与合规动态")))
    story.append(Spacer(1, 18))
    story.append(Paragraph(meta["brief_en"], S["brand"]))
    story.append(Paragraph(meta["date_str"], S["date"]))
    story.append(Paragraph(meta["subtitle"], S["subtitle"]))
    story.extend(G.org_motto(S))
    story.append(Paragraph(
        f"本期导读：六大领域重点动态 {n_policy} 项 · 通报处罚 {len(data['penalties'])} 起 · "
        f"朴朴专题 {len(data['pupu_items'])} 项 · 下周前瞻 {len(data['outlook'])} 条", S["toc"]))
    story.extend(G.issue_history_block(S, meta["date_str"]))
    _src_urls = {it.get("url") for _, items in data["policy"] for it in items if it.get("url")}
    _src_urls |= {p[5] for p in data["penalties"] if len(p) > 5 and p[5]}
    story.extend(G.compile_note(S, cutoff=meta["date_str"], n_src=len(_src_urls)))
    story.append(Spacer(1, SP_XS))
    story.append(HRFlowable(width="100%", thickness=1.6, color=NAVY, spaceAfter=1))
    story.append(HRFlowable(width="100%", thickness=0.4, color=LGRAY, spaceAfter=SP_M))

    # ---------- 目录 ----------
    toc = G.styled_toc(F)
    story.append(G.h1_block("目　录", S, toc=False))
    story.append(Spacer(1, SP_S))
    story.append(toc)
    story.append(Spacer(1, SP_M))

    # ---------- 一、本周综述（核心观点框） ----------
    key_rows = [[Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{s}", S["listitem"])]
                for i, s in enumerate(data["summary"], 1)]
    key_table = G.key_points_box(S, key_rows)
    story.append(KeepTogether([G.h1_block(meta["sections"]["summary"], S), key_table]))

    # ---------- 二、六大领域动态回顾 ----------
    story.append(Spacer(1, SP_S))
    story.append(G.h1_block(meta["sections"]["policy"], S))
    for di, (domain, items) in enumerate(data["policy"]):
        story.append(Paragraph(f"<font color='#1F3B63'>{di + 1}.</font>　{domain}", S["h2"]))
        for item in items:
            story.append(Paragraph(f"<font color='#1F3B63'>{G.MARK}</font>{item['title']}", S["h3"]))
            story.append(Paragraph(item["meta"], S["meta"]))
            story.append(Paragraph(G.link_html(item.get("url", "")), S["link"]))
            story.append(Paragraph(f"<font name='{G.HEITI}' color='#3A6B8F'>【要点】</font>{item['content']}", S["bodyc"]))
            story.append(G.analysis_block(item["analysis"], S, "解读"))
            story.append(G.divider())

    # ---------- 三、监管通报与处罚汇总 ----------
    story.append(Spacer(1, SP_L))
    story.append(G.h1_block(meta["sections"]["penalties"], S))
    story.append(Spacer(1, SP_S))
    tdata = [[Paragraph(h, S["tc"]) for h in ["时间", "监管机构", "涉及对象", "违规事由", "处置措施", "来源"]]]
    for r in data["penalties"]:
        cells = [Paragraph(c, S["tc2"]) for c in r[:5]]
        cells.append(Paragraph(G.link_html(r[5]), S["link"]))
        tdata.append(cells)
    table = Table(tdata, colWidths=[1.5 * cm, 2.8 * cm, 3.2 * cm, 4.5 * cm, 2.7 * cm, 1.9 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DEE6")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, NAVY2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, SP_M))
    story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>本周处罚统计小结</font>", S["h3"]))
    for i, s in enumerate(data["penalty_stats"], 1):
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{s}", S["listitem"]))

    # ---------- 四、朴朴超市业务专题 ----------
    story.append(Spacer(1, SP_L))
    story.append(G.h1_block(meta["sections"]["pupu"], S))
    story.append(Paragraph("说明：本板块聚焦与朴朴超市（生鲜电商/前置仓即时零售）业务直接相关的监管动态，"
                           "逐项评估合规风险等级（高/中高/中/低）并给出应对建议。", S["note"]))
    # 热力矩阵：图 + 图注 + 资料来源 + 图例 整体 KeepTogether，确保图例不与矩阵分页 orphan
    story.append(KeepTogether([G.fig3_matrix(F, data["matrix_rows"]),
                               Paragraph("图1：朴朴超市合规风险热力矩阵（按风险主题 × 业务环节）", S["fig"]),
                               G.src_note(G.SRC_INTERNAL, S),
                               G.legend_paragraph(S)]))
    for title, risk, scope, impact, action in data["pupu_items"]:
        rc = {"高": RED, "中高": ORANGE, "中": AMBER, "低": GREEN}.get(risk, GRAY)
        story.append(Paragraph(f"<font color='#1F3B63'>{G.MARK}</font>{title}"
                               f"　<font color='#{rc.hexval()[2:]}'>【风险等级：{risk}】</font>", S["h3"]))
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#3A6B8F'>涉及业务环节：</font>{scope}", S["body0"]))
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>影响分析：</font>{impact}", S["bodyc"]))
        story.append(G.analysis_block(action, S, "应对建议"))
        story.append(G.divider())

    # ---------- 五、下周前瞻 ----------
    story.append(Spacer(1, SP_S))
    story.append(G.h1_block(meta["sections"]["outlook"], S))
    for i, r in enumerate(data["outlook"], 1):
        story.append(Paragraph(f"<font name='{G.HEITI}' color='#1F3B63'>{i}.</font>　{r}", S["listitem"]))

    # ---------- 信息来源与免责声明（固定尾部栏） ----------
    story.append(Spacer(1, SP_L))
    story.append(Paragraph("信息来源与免责声明", S["h3"]))
    story.append(G.disclaimer_block(S, "本周报"))

    # ---------- 尾注 ----------
    story.append(Spacer(1, SP_M))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=SP_S))
    story.append(Paragraph("— 本周报由自动化任务每周生成，内容基于公开网络信息检索整理，仅供参考 —", S["footer"]))

    # ---------- 输出 ----------
    os.makedirs(OUT_DIR, exist_ok=True)
    pdf_path = os.path.join(OUT_DIR, meta["filename"])
    doc = G.ComplianceDoc(pdf_path, pagesize=G.A4 if hasattr(G, 'A4') else None,
                          leftMargin=M_L, rightMargin=M_R,
                          topMargin=M_T + 0.4 * cm, bottomMargin=M_B + 0.6 * cm,
                          title=meta["title"], author="WorkBuddy 合规自动化")
    hf = G.make_header_footer(meta["header_text"], meta["date_str"])
    doc.multiBuild(story, canvasmaker=G.NumberedCanvas, onFirstPage=hf, onLaterPages=hf)
    print(f"PDF saved: {pdf_path}")
    return pdf_path

def _collect(data, meta):
    parts = [meta["title"], meta["date_str"], meta["header_text"], meta["subtitle"],
             meta["brief_en"], meta["filename"], meta["tagline"], "目　录",
             "本周处罚统计小结", "本期导读"]
    parts.extend(list(meta["sections"].values()))
    parts.extend(data["summary"])
    for domain, items in data["policy"]:
        parts.append(domain)
        for it in items:
            parts.extend([it["title"], it["meta"], it["content"], it["analysis"], it.get("url", "")])
    for r in data["penalties"]:
        parts.extend(r)
    parts.extend(data["penalty_stats"])
    for t in data["pupu_items"]:
        parts.extend(t)
    parts.extend(data["outlook"])
    for row in data["matrix_rows"]:
        parts.extend(row)
    parts.extend(["风险主题", "采购", "仓储/加工", "线上运营", "配送", "会员营销", "用工",
                  "高", "中高", "中", "低", "—",
                  "【要点】", "涉及业务环节：", "影响分析：", "应对建议：", "解读：",
                  "原文链接：", "本周处罚统计小结",
                  "图1：朴朴超市合规风险热力矩阵（按风险主题 × 业务环节）"])
    return "".join(parts)

if __name__ == "__main__":
    build(WD.DATA, WD.META)

