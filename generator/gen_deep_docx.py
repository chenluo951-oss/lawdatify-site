#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《合规资讯》深度分析版 Word 生成器（简版结构 + 四大深度板块）"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep_data as DD
_BASEMOD = sys.argv[1] if len(sys.argv) > 1 else "weekly_data"
WD = __import__(_BASEMOD)
import gen_report_pdf as G  # 复用 prev_issue_dates 推算往期回顾
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT_DIR = os.environ.get("CBR_OUT_DIR") or "/Users/luochen/Desktop/合规资讯简报"
NAVY = (0x1F, 0x3B, 0x63); NAVY2 = (0x2E, 0x5E, 0x8C); GRAY = (0x66, 0x66, 0x66)
LGRAY = (0x99, 0x99, 0x99); GOLD = (0x8A, 0x4B, 0x08)
SONG = "方正小标宋简体"; HEITI = "微软雅黑"; KAITI = "楷体"

def set_font(run, size=10.5, bold=False, color=None, name=KAITI):
    run.font.name = "Times New Roman"; run.font.size = Pt(size); run.font.bold = bold
    r = run._element.get_or_add_rPr(); rf = r.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); r.append(rf)
    rf.set(qn("w:eastAsia"), name)
    if color: run.font.color.rgb = RGBColor(*color)

def add_h1(doc, text):
    p = doc.add_paragraph(); run = p.add_run(text)
    set_font(run, 15.5, True, NAVY, SONG)
    p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(6)
    return p

def add_h2(doc, text):
    p = doc.add_paragraph(); run = p.add_run(text)
    set_font(run, 13, True, NAVY2, HEITI)
    p.paragraph_format.space_before = Pt(8); p.paragraph_format.space_after = Pt(4)
    return p

def add_body(doc, text, color=None, bold=False, name=KAITI, size=10.5):
    p = doc.add_paragraph(); run = p.add_run(text)
    set_font(run, size, bold, color, name)
    p.paragraph_format.line_spacing = 1.5
    return p

def shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr(); shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), hex_color); tcPr.append(shd)

def main():
    M, D = WD.META, WD.DATA
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.2); section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.5); section.right_margin = Cm(2.5)
    # 封面
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(M["title"] + "（深度分析版）"), 22, True, NAVY, SONG)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(M["brief_en"] + " · DEEP ANALYSIS"), 11, False, LGRAY, HEITI)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(M["date_str"]), 13, False, GRAY, KAITI)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(M["subtitle"] + " · 深度分析版"), 10, False, LGRAY, HEITI)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("朴朴超市 · 法务合规部"), 11, True, NAVY, HEITI)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("守护合规底线 · 支撑业务决策"), 9, False, GRAY, HEITI)
    prev = G.prev_issue_dates(M["date_str"], n=3)
    if prev:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p.add_run("近 3 期回顾：　" + "　·　".join(prev)), 9, False, LGRAY, HEITI)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("覆盖口径：六大合规领域公开监管动态与通报处罚"), 9, False, GRAY, HEITI)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("审核与签发：朴朴超市法务合规部"), 9, False, GRAY, HEITI)
    doc.add_paragraph()
    # 目录
    add_h1(doc, "目　录")
    for sec in ["一、本期综述", "二、六大领域动态回顾", "三、监管通报与处罚汇总", "四、朴朴超市业务专题",
                "五、前瞻（含深度情景）", "六、六大领域深度分析", "七、行业水位调研",
                "八、违规与合规案例参考", "九、关联延伸", "九（补）、合规焦点专题",
                "十（补）、监管法规条文摘录", "十一（补）、90 天合规落地路线图",
                "十二（补）、合规差距自评估矩阵", "十三（补）、案例深度解读",
                "十四（补）、监管关键节点与合规日历", "十五（补）、合规治理与组织职责建议"]:
        add_body(doc, sec, color=NAVY2, bold=True, name=HEITI, size=12)
    # 一、综述
    add_h1(doc, M["sections"]["summary"])
    for i, s in enumerate(D["summary"], 1):
        add_body(doc, f"{i}. {s}")
    # 二、六大领域回顾
    add_h1(doc, M["sections"]["policy"])
    for di, (domain, items) in enumerate(D["policy"], 1):
        add_h2(doc, f"{di}. {domain}")
        for it in items:
            p = doc.add_paragraph(); set_font(p.add_run(f"▍{it['title']}"), 11.5, True, None, HEITI)
            add_body(doc, it["meta"], color=LGRAY, name=HEITI, size=9)
            if it.get("url"): add_body(doc, f"原文链接：{it['url']}", color=NAVY2, name=KAITI, size=9)
            add_body(doc, f"要点：{it['content']}")
            add_body(doc, f"解读：{it['analysis']}", color=GOLD)
        doc.add_paragraph()
    # 六、深度分析
    add_h1(doc, "六、六大领域深度分析")
    add_body(doc, "对六大合规领域逐一展开：监管脉络与立法意图、对朴朴业务的影响传导路径、同业水位与标杆做法、可落地控制建议。", color=GRAY, name=HEITI, size=10)
    for di, (domain, _) in enumerate(D["policy"], 1):
        d = DD.DOMAIN_DEEP.get(domain)
        if not d: continue
        add_h2(doc, f"{di}. {domain} —— 深度分析")
        for label, key in [("监管脉络与立法意图", "脉络"), ("对朴朴业务的影响传导路径", "影响路径"),
                           ("同业水位与标杆做法", "同业水位"), ("可落地控制建议", "控制建议"),
                           ("法条依据", "法条依据"), ("业务映射（朴朴）", "业务映射"),
                           ("风险信号与预警", "风险信号"), ("分阶段落地步骤", "落地步骤"),
                           ("判例与延展（真实案例参照）", "判例与延展")]:
            p = doc.add_paragraph(); set_font(p.add_run(f"▍{label}"), 11, True, NAVY2, HEITI)
            add_body(doc, d[key])
        add_h2(doc, "分领域合规自查清单（可直接转化为内部检查表）")
        for item in DD.CHECK_LISTS.get(domain, []):
            add_body(doc, "✓ " + item)
    # 七、行业水位调研
    add_h1(doc, "七、行业水位调研")
    add_body(doc, "下表从九项合规维度对比头部平台水位、中小平台常见短板，并给出朴朴可达目标水位，作为差距分析基线。", color=GRAY, name=HEITI, size=10)
    table = doc.add_table(rows=1, cols=4); table.style = "Table Grid"; table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, t in enumerate(DD.INDUSTRY_SURVEY["cols"]):
        hdr[i].text = ""; pp = hdr[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9.5, True, (255,255,255), HEITI); shade_cell(hdr[i], "1F3B63")
    for row in DD.INDUSTRY_SURVEY["rows"]:
        rc = table.add_row().cells
        for i, v in enumerate(row):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 8.5, False, None, KAITI)
    doc.add_paragraph()
    add_body(doc, "调研结论：头部平台已在数据分级、第三方 SDK 治理、资质实质审查、生鲜快检溯源四个维度形成明显领先；"
                  "朴朴应优先补齐“资质动态预警”与“批次快检硬门槛”两项高杠杆控制点。", color=GOLD)
    doc.add_paragraph()
    add_h2(doc, "具像化合规参考图示与样例")
    add_body(doc, "以下以可落地的表格与清单，将“行业水位”转译为可直接对照的准入流程与展示规范。", color=GRAY, name=HEITI, size=10)
    add_h2(doc, "① 行业合规水位对比（朴朴 vs 同业）")
    wl = doc.add_table(rows=1, cols=6); wl.style = "Table Grid"; wl.alignment = WD_TABLE_ALIGNMENT.CENTER
    wh = wl.rows[0].cells
    for i, t in enumerate(["合规控制点", "朴朴", "美团", "盒马", "叮咚", "京东到家"]):
        wh[i].text = ""; pp = wh[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9, True, (255, 255, 255), HEITI); shade_cell(wh[i], "1F3B63")
    for row in [["资质动态预警（到期自动下架）", "待提升", "领先", "达标", "达标", "达标"],
                ["批次快检+一品一码溯源", "待提升", "领先", "领先", "达标", "达标"],
                ["算法备案公示（派单/推荐）", "待提升", "领先", "达标", "达标", "达标"],
                ["个性化广告关闭入口", "待提升", "领先", "达标", "达标", "领先"],
                ["隐私政策—行为一致性", "达标", "领先", "达标", "达标", "领先"],
                ["食安抽检应对速度", "达标", "领先", "领先", "达标", "达标"]]:
        rc = wl.add_row().cells
        for i, v in enumerate(row):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 8.5, False, None, KAITI)
    doc.add_paragraph()
    add_h2(doc, "② 食安快检准入 SOP（具像化流程样例）")
    for step in ["① 供应商到货·批次到仓",
                 "② 资质 + 批次检验合格证明查验（缺证明→直接拦截拒收）",
                 "③ 入库快检：二氧化硫残留 + 农兽药残留（噻虫嗪/胺/五氯酚酸钠）",
                 "④ 判定是否合格：合格→上架销售；不合格→一键下架召回 + 通知采购/品控复核",
                 "⑤ 合格品：一品一码溯源，抽检通报后数分钟定位同批次"]:
        add_body(doc, step)
    add_h2(doc, "③ 价格展示合规自检清单样例（合规模板）")
    ps = doc.add_table(rows=1, cols=2); ps.style = "Table Grid"; ps.alignment = WD_TABLE_ALIGNMENT.CENTER
    ph = ps.rows[0].cells
    for i, t in enumerate(["展示项", "合规要点（须留痕可举证）"]):
        ph[i].text = ""; pp = ph[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9.5, True, (255, 255, 255), HEITI); shade_cell(ph[i], "1F3B63")
    for k, v in [("划线价 ¥99.9", "须有真实成交记录支撑：系统留存近7日最低成交价截图，禁止虚构原价/累加核算价"),
                 ("促销价 ¥59.9", "规则事前公示：活动前7日均价¥89，本价低于均价，降幅说明清晰可查"),
                 ("动态/差别定价", "向用户明示定价规则，禁止“杀熟”；同商品同用户可见价格一致或可解释"),
                 ("免密支付/自动续期", "显著告知并一键取消，扣款前二次确认，不得默认勾选")]:
        rc = ps.add_row().cells
        set_font(rc[0].paragraphs[0].add_run(k), 8.5, True, None, HEITI)
        set_font(rc[1].paragraphs[0].add_run(v), 8.5, False, None, KAITI)
    doc.add_paragraph()
    # 七（补）、同业深度画像（头部平台合规做法对标）
    add_h1(doc, "七（补）、同业深度画像（头部平台合规做法对标）")
    add_body(doc, "选取与朴朴业务模式相近的四类头部平台，逐一剖析其合规控制做法与对朴朴的可借鉴点，"
                  "作为行业水位调研的具象化补充。", color=GRAY, name=HEITI, size=10)
    for name, prof in DD.PEER_PROFILES:
        add_h2(doc, "▍" + name)
        add_body(doc, prof)
    doc.add_paragraph()
    # 八、案例参考
    add_h1(doc, "八、违规与合规案例参考")
    add_body(doc, "下表汇总典型违规案例与可借鉴合规标杆。“违规”类提示雷区，“合规参考”类提示可复用做法。", color=GRAY, name=HEITI, size=10)
    ct = doc.add_table(rows=1, cols=6); ct.style = "Table Grid"; ct.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = ct.rows[0].cells
    for i, t in enumerate(["类型","案例/实践","来源/文号","处置/效果","对朴朴启示","来源链接"]):
        hdr[i].text = ""; pp = hdr[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9, True, (255,255,255), HEITI); shade_cell(hdr[i], "1F3B63")
    for c in DD.CASE_REFS:
        rc = ct.add_row().cells
        for i, v in enumerate(c):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 8, False, None, KAITI)
    doc.add_paragraph()
    # 三、处罚汇总
    add_h1(doc, M["sections"]["penalties"])
    pt = doc.add_table(rows=1, cols=6); pt.style = "Table Grid"; pt.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = pt.rows[0].cells
    for i, t in enumerate(["时间","监管机构","涉及对象","违规事由","处置措施","来源"]):
        hdr[i].text = ""; pp = hdr[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 10, True, (255,255,255), HEITI); shade_cell(hdr[i], "1F3B63")
    for row_data in D["penalties"]:
        rc = pt.add_row().cells
        for i, v in enumerate(row_data):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 9, False, None, KAITI)
    doc.add_paragraph()
    add_h2(doc, "本期处罚统计小结")
    for i, s in enumerate(D["penalty_stats"], 1):
        add_body(doc, f"{i}. {s}")
    # 四、朴朴专题
    add_h1(doc, M["sections"]["pupu"])
    add_body(doc, "说明：本板块聚焦与朴朴超市业务直接相关的监管动态，逐项评估合规风险等级并给出应对建议。", color=GRAY, name=HEITI, size=10)
    rc_color = {"高":(0xC0,0x39,0x2B),"中高":(0xD3,0x54,0x00),"中":(0xB8,0x86,0x0B),"低":(0x5B,0x8C,0x5A)}
    for title, risk, scope, impact, action in D["pupu_items"]:
        p = doc.add_paragraph(); set_font(p.add_run(f"▍{title}"), 11.5, True, None, HEITI)
        set_font(p.add_run(f"  【风险等级：{risk}】"), 10.5, True, rc_color.get(risk, GRAY), HEITI)
        add_body(doc, f"涉及业务环节：{scope}", color=NAVY2, bold=True, name=HEITI, size=10)
        add_body(doc, f"影响分析：{impact}")
        add_body(doc, f"应对建议：{action}", color=GOLD)
    doc.add_paragraph()
    # 九（补）、合规焦点专题
    add_h1(doc, "九（补）、合规焦点专题")
    add_body(doc, "针对与朴朴超市业务最相关的五项合规焦点，逐篇展开监管要点、对业务的映射与可落地控制清单。", color=GRAY, name=HEITI, size=10)
    for i, (title, paras) in enumerate(DD.FOCUS_TOPICS, 1):
        add_h2(doc, f"{i}. {title}")
        for label, txt in [("监管要点", paras[0]), ("业务映射", paras[1]), ("控制清单", paras[2])]:
            p = doc.add_paragraph(); set_font(p.add_run(f"▍{label}"), 11, True, NAVY2, HEITI)
            add_body(doc, txt)
    # 十（补）、监管法规条文摘录
    add_h1(doc, "十（补）、监管法规条文摘录")
    add_body(doc, "逐领域引述当前有效、与朴朴业务直接相关的关键条文，供内部对照自查。", color=GRAY, name=HEITI, size=10)
    for dom, src, quotes in DD.REG_QUOTES:
        add_h2(doc, f"▍{dom} —— {src}")
        for q in quotes:
            add_body(doc, "· " + q)
    # 十一（补）、90 天合规落地路线图
    add_h1(doc, "十一（补）、90 天合规落地路线图")
    add_body(doc, "结合本期风险研判，给出分三阶段、可落地的合规加固路线，作为内部排期基线。", color=GRAY, name=HEITI, size=10)
    rt = doc.add_table(rows=1, cols=4); rt.style = "Table Grid"; rt.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = rt.rows[0].cells
    for i, t in enumerate(DD.ROADMAP["cols"]):
        hdr[i].text = ""; pp = hdr[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9.5, True, (255,255,255), HEITI); shade_cell(hdr[i], "1F3B63")
    for r in DD.ROADMAP["rows"]:
        rc = rt.add_row().cells
        for i, v in enumerate(r):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 8.5, False, None, KAITI)
    doc.add_paragraph()
    # 十二（补）、合规差距自评估矩阵
    add_h1(doc, "十二（补）、合规差距自评估矩阵")
    add_body(doc, "下表将六大领域关键控制点转化为可排期的内部自查表。状态采用“建议口径”，便于后续据实更新；"
                  "责任归属与目标时间窗供跨部门对齐，建议每月滚动复核并回填进度。", color=GRAY, name=HEITI, size=10)
    gt = doc.add_table(rows=1, cols=5); gt.style = "Table Grid"; gt.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = gt.rows[0].cells
    for i, t in enumerate(DD.GAP_MATRIX["cols"]):
        hdr[i].text = ""; pp = hdr[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9, True, (255,255,255), HEITI); shade_cell(hdr[i], "1F3B63")
    for r in DD.GAP_MATRIX["rows"]:
        rc = gt.add_row().cells
        for i, v in enumerate(r):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 8, False, None, KAITI)
    doc.add_paragraph()
    # 十三（补）、案例深度解读
    add_h1(doc, "十三（补）、案例深度解读")
    add_body(doc, "对本期重点案例作延伸剖析，提炼对朴朴超市可直接复用的控制启示。", color=GRAY, name=HEITI, size=10)
    for title, txt in DD.CASE_INTERP:
        add_h2(doc, "▍" + title)
        add_body(doc, txt)
    # 十四（补）、监管关键节点与合规日历
    add_h1(doc, "十四（补）、监管关键节点与合规日历")
    add_body(doc, "将关键监管节点与内部排期对齐，供跨部门排期基线参考。", color=GRAY, name=HEITI, size=10)
    tl = doc.add_table(rows=1, cols=3); tl.style = "Table Grid"; tl.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = tl.rows[0].cells
    for i, t in enumerate(["时间窗", "监管/内部节点", "朴朴应对动作"]):
        hdr[i].text = ""; pp = hdr[i].paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(pp.add_run(t), 9, True, (255,255,255), HEITI); shade_cell(hdr[i], "1F3B63")
    for r in DD.TIMELINE:
        rc = tl.add_row().cells
        for i, v in enumerate(r):
            rc[i].text = ""; set_font(rc[i].paragraphs[0].add_run(v), 8.5, False, None, KAITI)
    doc.add_paragraph()
    # 十五（补）、合规治理与组织职责建议
    add_h1(doc, "十五（补）、合规治理与组织职责建议")
    add_body(doc, "供内部搭建合规治理框架参照，可按实际组织情况裁剪。", color=GRAY, name=HEITI, size=10)
    for txt in DD.GOV:
        add_body(doc, txt)
    # 九、关联延伸
    add_h1(doc, "九、关联延伸")
    add_body(doc, "将分散的合规议题跨领域联动，识别风险叠加点与治理复用机会。", color=GRAY, name=HEITI, size=10)
    for i, r in enumerate(DD.EXTENSIONS, 1):
        add_body(doc, f"{i}. {r}")
    # 五、前瞻
    add_h1(doc, M["sections"]["outlook"])
    for i, r in enumerate(D["outlook"], 1):
        add_body(doc, f"{i}. {r}")
    add_h2(doc, "深度情景展望")
    for i, r in enumerate(DD.DEEP_OUTLOOK, 1):
        add_body(doc, f"{i}. {r}")
    # 信息来源与免责声明（固定尾部栏）
    doc.add_paragraph()
    add_h2(doc, "信息来源与免责声明")
    for _t in [
        "一、信息来源：本报告内容基于公开网络检索整理的监管机构官方网站通报、公告、处罚决定书及权威媒体报道，各条动态均附原文链接，便于溯源核验。",
        "二、用途限制：本报告仅供朴朴超市内部合规参考，不构成法律意见或决策依据；据此采取具体合规措施前，请咨询法务或外部专业律师。",
        "三、时效性：监管政策与执法动态更新较快，本报告截至生成时点整理，不排除后续修订或新发文件导致内容变化，请以最新官方发布为准。",
        "四、版权：本报告由自动化任务生成，引用内容著作权归原发布机构所有。",
    ]:
        add_body(doc, _t, color=GRAY, size=9.5)

    doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("— 本报告为深度分析版，内容基于公开信息检索与行业研究整理，仅供参考，不构成法律意见 —"), 9, False, LGRAY, HEITI)
    # 页脚：左来源/免责声明 + 右页码（对齐 PDF footer，benchmark C③）
    G.add_docx_footer(doc)

    os.makedirs(OUT_DIR, exist_ok=True)
    docx_path = os.path.join(OUT_DIR, M["filename"].replace(".pdf", "_深度分析版.docx"))
    doc.save(docx_path)
    print(f"DOCX saved: {docx_path}")
    return docx_path

if __name__ == "__main__":
    main()
