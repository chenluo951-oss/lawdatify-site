#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《合规资讯简报》HTML 生成器（网页版）

输出**自包含单文件 HTML**（内嵌 CSS，零外部依赖），双击即可在浏览器打开，
也可直接 Ctrl/Cmd+P 打印或另存为 PDF。

与 PDF / DOCX 共用同一数据模块与视觉体系：
  · 深蓝主色 #1F3B63 + NAVY2 强调 + muted 风险色阶（#A93B33/#B0652C/#B0862E/#4C7A59）
  · 字号层级按打印 pt × 1.33 换算为屏幕 px：h1 22 / h2 18 / h3 16 / body 14
  · 图表「资料来源」脚注、尾部免责声明栏、核心观点框均与 PDF 一致
"""
import os
import sys
import html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep_data as DD

OUT_DIR = os.environ.get("CBR_OUT_DIR") or "/Users/luochen/Desktop/合规资讯简报"
_DATAMOD = sys.argv[1] if len(sys.argv) > 1 else "weekly_data"
WD = __import__(_DATAMOD)

# ============================================================ 品牌色（与 PDF 引擎一致）
NAVY, NAVY2, BLUE = "#1F3B63", "#2E5E8C", "#3A6B8F"
INK, GRAY, LGRAY = "#2B2B2B", "#6B7280", "#9AA3AF"
RED, ORANGE, AMBER, GREEN = "#A93B33", "#B0652C", "#B0862E", "#4C7A59"
BG_KEY, ZEBRA, GRID = "#F2F6FA", "#EDF1F6", "#D8DEE6"

# ============================================================ 内嵌 CSS
CSS = """
:root{
  --navy:#1F3B63; --navy2:#2E5E8C; --blue:#3A6B8F;
  --ink:#2B2B2B; --gray:#6B7280; --lgray:#9AA3AF;
  --red:#A93B33; --orange:#B0652C; --amber:#B0862E; --green:#4C7A59;
  --bg-key:#F2F6FA; --zebra:#EDF1F6; --grid:#D8DEE6;
}
*{box-sizing:border-box;}
html{-webkit-text-size-adjust:100%;}
body{
  margin:0; padding:0; background:#F7F8FA; color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",
              "Microsoft YaHei","Source Han Sans SC",sans-serif;
  font-size:14px; line-height:1.9;
}
.page{max-width:960px; margin:0 auto; background:#fff; padding:48px 56px 64px;}
@media (max-width:720px){ .page{padding:24px 18px 40px;} body{font-size:15px;} }

/* ---------- 封面 ---------- */
.cover{text-align:center; padding:8px 0 28px; border-bottom:2px solid var(--navy);}
.cover .brandbar{background:var(--navy); color:#fff; padding:12px 18px; border-radius:4px;
  display:flex; justify-content:space-between; align-items:center; font-size:13px; letter-spacing:.5px;}
.cover h1{font-size:30px; line-height:1.35; margin:26px 0 8px; color:var(--navy);
  font-family:"Songti SC","SimSun",serif; font-weight:700; letter-spacing:2px;}
.cover .en{font-size:11px; letter-spacing:3px; color:var(--lgray); text-transform:uppercase;}
.cover .sub{font-size:13px; color:var(--gray); margin-top:14px;}
.cover .date{font-size:14px; color:var(--gray); margin-top:6px;}
.cover .org{font-size:15px; color:var(--navy); font-weight:600; margin-top:18px;}
.cover .motto{font-size:12px; color:var(--gray); margin-top:4px;}

/* ---------- 标题层级（打印 pt × 1.33） ---------- */
h2.sec{font-size:22px; line-height:1.5; color:var(--navy); margin:40px 0 16px; padding:10px 0 10px 14px;
  border-left:5px solid var(--navy); background:linear-gradient(90deg,#EEF3F8,transparent);
  font-family:"Songti SC","SimSun",serif; font-weight:700; letter-spacing:1px;}
h3.sub2{font-size:18px; color:var(--navy); margin:26px 0 10px; font-weight:600;}
h4.sub3{font-size:16px; color:var(--navy2); margin:20px 0 8px; font-weight:600;}
h4.sub3 .mk{color:var(--navy);}

/* ---------- 正文 ---------- */
p{margin:0 0 10px; text-align:justify;}
p.meta{font-size:12px; color:var(--lgray); margin:2px 0 4px;}
p.note{font-size:13px; color:var(--gray); background:#FAFBFC; border-left:3px solid var(--grid);
  padding:8px 12px; margin:0 0 14px; border-radius:0 3px 3px 0;}
p.body0{margin:2px 0 6px;}
p.listitem{margin:0 0 8px 24px; text-indent:-18px;}
.k{color:var(--blue); font-weight:600;}
.k2{color:var(--navy); font-weight:600;}
a{color:var(--navy2); text-decoration:none; word-break:break-all;}
a:hover{text-decoration:underline;}
p.link{font-size:12px; margin:0 0 8px;}

/* ---------- 解读块 ---------- */
blockquote.ana{margin:8px 0 14px; padding:10px 14px; background:#F0F4F9;
  border-left:3px solid #C9D6E4; border-radius:0 3px 3px 0; color:#44546A; font-size:13.5px;}
blockquote.ana b{color:var(--navy);}

/* ---------- 核心观点框 ---------- */
.kbox{margin:18px 0 22px; border:1px solid #C9D6E4; border-radius:4px; overflow:hidden;}
.kbox-t{background:var(--navy); color:#fff; font-size:16px; font-weight:600; padding:8px 16px;}
.kbox-b{background:var(--bg-key); border-left:4px solid var(--navy); padding:14px 18px;}
.kbox-b ol{margin:0; padding-left:20px;}
.kbox-b li{margin:0 0 8px;}
.kbox-b li:last-child{margin-bottom:0;}

/* ---------- 表格 ---------- */
.tw{overflow-x:auto; margin:14px 0 18px;}
table.dt{width:100%; border-collapse:collapse; font-size:12.5px; line-height:1.65;}
table.dt th{background:var(--navy); color:#fff; font-weight:600; text-align:left;
  padding:8px 9px; border:1px solid var(--grid); border-bottom:2px solid var(--navy2); white-space:nowrap;}
table.dt td{padding:8px 9px; border:1px solid var(--grid); vertical-align:top; text-align:left;}
table.dt tbody tr:nth-child(even){background:var(--zebra);}
table.dt td.c,table.dt th.c{text-align:center;}

/* ---------- 图示 ---------- */
figure.fig{margin:20px 0 24px; padding:0;}
figure.fig .figwrap{overflow-x:auto;}
figure.fig figcaption{font-size:12px; color:var(--gray); text-align:center; margin-top:8px; line-height:1.7;}
figure.fig .figsrc{font-size:11px; color:var(--lgray); text-align:left; margin-top:4px;}
table.ft{border-collapse:collapse; width:100%; font-size:12px;}
table.ft th{background:var(--navy); color:#fff; font-weight:600; padding:7px 8px;
  border:1px solid var(--grid); text-align:center;}
table.ft td{padding:7px 8px; border:1px solid var(--grid); text-align:center; vertical-align:middle;}
table.ft td.lbl{text-align:left; font-weight:600; color:var(--navy); background:#F7F9FC;}
.lv{color:#fff; font-weight:600; font-size:11.5px;}
.lv-h{background:var(--red);} .lv-mh{background:var(--orange);} .lv-m{background:var(--amber);}
.lv-l{background:var(--green);} .lv-na{background:#F1F3F6; color:#8A94A6;}
.legend{font-size:12px; color:var(--gray); text-align:center; margin:6px 0 14px;}
.legend span{display:inline-block; color:#fff; padding:1px 8px; margin:0 3px; border-radius:2px; font-size:11px;}

/* ---------- 流程图（SOP） ---------- */
.sop{text-align:center; margin:10px 0;}
.sop .st{display:inline-block; width:78%; padding:9px 14px; border:1.1px solid var(--navy);
  background:#F4F7FB; border-radius:4px; font-size:12.5px; line-height:1.7; font-weight:600; color:var(--navy);}
.sop .ar{font-size:16px; color:var(--lgray); margin:5px 0;}
.sop .br{display:flex; gap:14px; justify-content:center; margin:4px 0;}
.sop .br > div{flex:1; max-width:340px;}
.sop .ok{border-color:#3E6B3E; background:#EDF6ED; color:#2F5D2F;}
.sop .bad{border-color:#8E2B20; background:#FBEEEC; color:#7C241C;}

/* ---------- 框架图 ---------- */
.frm{border:1px solid var(--grid); border-radius:4px; overflow:hidden;}
.frm .hub{background:var(--navy); color:#fff; text-align:center; padding:11px 10px;
  font-size:13px; font-weight:600; letter-spacing:.5px;}
.frm .grid6{display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--grid);}
@media (max-width:720px){ .frm .grid6{grid-template-columns:repeat(2,1fr);} }
.frm .card{background:#F7F9FC; padding:11px 10px; text-align:center;}
.frm .card b{display:block; color:var(--navy); font-size:13px; margin-bottom:4px;}
.frm .card span{font-size:11.5px; color:#37424F; line-height:1.6;}

/* ---------- 分隔 / 尾部 ---------- */
hr.div{border:0; border-top:1px dashed var(--grid); margin:18px 0;}
.disc{margin:24px 0 18px; background:var(--bg-key); border-left:4px solid var(--navy);
  border-radius:0 4px 4px 0; padding:12px 18px; font-size:12px; color:#44546A; line-height:1.85;}
.disc ol{margin:0; padding-left:20px;}
.foot{margin-top:26px; padding-top:14px; border-top:1px solid var(--grid);
  font-size:11.5px; color:var(--lgray); text-align:center;}
.tocbox{background:#FAFBFC; border:1px solid var(--grid); border-radius:4px; padding:14px 22px; margin:20px 0 8px;}
.tocbox h2{font-size:18px; color:var(--navy); margin:0 0 10px; font-weight:600;}
.tocbox ol{margin:0; padding-left:22px; font-size:13.5px; line-height:2;}
.tocbox a{color:var(--navy);}

@media print{
  body{background:#fff;}
  .page{max-width:none; padding:0;}
  h2.sec{page-break-after:avoid; break-after:avoid;}
  h3.sub2,h4.sub3{page-break-after:avoid; break-after:avoid;}
  figure.fig,table.dt,.kbox{page-break-inside:avoid; break-inside:avoid;}
  a{color:var(--navy2);}
}
"""

# ============================================================ 工具
def esc(s):
    return html.escape("" if s is None else str(s), quote=False)


def link_html(url):
    if not url:
        return ""
    u = esc(url)
    return f'<a href="{u}" target="_blank" rel="noopener">{u}</a>'


def body(txt, cls=""):
    return f'<p class="{cls}">{esc(txt)}</p>' if cls else f'<p>{esc(txt)}</p>'


def label_body(label, txt, color=None, cls="body0"):
    c = color or BLUE
    return f'<p class="{cls}"><span class="k" style="color:{c}">{esc(label)}</span>{esc(txt)}</p>'


def ana_block(txt, title="解读"):
    return (f'<blockquote class="ana"><b>{esc(title)}：</b>{esc(txt)}</blockquote>')


def h1_sec(txt, anchor=None):
    a = f' id="{anchor}"' if anchor else ""
    return f'<h2 class="sec"{a}>{esc(txt)}</h2>'


def h2_sub(txt):
    return f'<h3 class="sub2">{esc(txt)}</h3>'


def h3_sub(txt, mark="▍"):
    m = f'<span class="mk">{mark}</span>' if mark else ""
    return f'<h4 class="sub3">{m}{esc(txt)}</h4>'


def note(txt):
    return f'<p class="note">{esc(txt)}</p>'


def divider():
    return '<hr class="div"/>'


def key_box(items, title="核心观点"):
    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
    return (f'<div class="kbox"><div class="kbox-t">{esc(title)}</div>'
            f'<div class="kbox-b"><ol>{lis}</ol></div></div>')


def data_table(headers, rows, center_cols=()):
    th = "".join(f'<th class="c">{esc(h)}</th>' if i in center_cols
                 else f"<th>{esc(h)}</th>" for i, h in enumerate(headers))
    trs = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            cl = ' class="c"' if i in center_cols else ""
            tds.append(f"<td{cl}>{c}</td>")   # cell 已是 HTML（可含链接）
        trs.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<div class="tw"><table class="dt"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>')


def figure(inner, caption, src=None):
    s = f'<div class="figsrc">资料来源：{esc(src)}</div>' if src else ""
    return (f'<figure class="fig"><div class="figwrap">{inner}</div>'
            f'<figcaption>{esc(caption)}</figcaption>{s}</figure>')


def disclaimer(kind="本简报"):
    items = [
        f"{kind}内容基于公开网络信息检索整理，信息来源包括政府部门官网公告、权威媒体报道及监管机构公开通报。",
        "各部分均附原文链接，供核验查证；链接有效性以来源网站为准，如遇调整请以官网最新发布为准。",
        f"{kind}所载分析与建议为基于公开信息的内部合规评估，不构成法律意见，亦不替代专业法律判断。",
        "涉及具体业务决策时，请结合实际情况并咨询法务合规部或外部专业机构。",
    ]
    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
    return f'<div class="disc"><ol>{lis}</ol></div>'


def legend(levels=(("高", "lv-h"), ("中高", "lv-mh"), ("中", "lv-m"), ("低", "lv-l"), ("—", "lv-na"))):
    sp = "".join(f'<span class="lv {cls}">{esc(n)}</span>' for n, cls in levels)
    return f'<div class="legend">{sp}</div>'


# ============================================================ 图示（HTML 重绘，配色与 PDF 一致）
_LV_CLS = {"高": "lv-h", "中高": "lv-mh", "中": "lv-m", "低": "lv-l"}
_WL_CLS = {"领先": "lv-l", "达标": "lv-m", "待提升": "lv-h"}


def fig_matrix(rows):
    """朴朴合规风险热力矩阵（风险主题 × 业务环节）"""
    head = ["风险主题", "采购", "仓储/加工", "线上运营", "配送", "会员营销", "用工"]
    th = "".join(f'<th class="c">{esc(h)}</th>' for h in head)
    trs = []
    for r in rows:
        tds = [f'<td class="lbl">{esc(r[0])}</td>']
        for v in r[1:]:
            if v == "—":
                tds.append('<td class="lv lv-na">—</td>')
            else:
                tds.append(f'<td class="lv {_LV_CLS.get(v, "lv-na")}">{esc(v)}</td>')
        trs.append("<tr>" + "".join(tds) + "</tr>")
    inner = (f'<table class="ft"><thead><tr>{th}</tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')
    return figure(inner, "图1：朴朴超市合规风险热力矩阵（按风险主题 × 业务环节）",
                  "朴朴超市法务合规部基于公开监管动态内部评估") + legend()


_WL_ROWS = [
    ["资质动态预警（到期自动下架）", "待提升", "领先", "达标", "达标", "达标"],
    ["批次快检 + 一品一码溯源", "待提升", "领先", "领先", "达标", "达标"],
    ["算法备案公示（派单/推荐）", "待提升", "领先", "达标", "达标", "达标"],
    ["个性化广告关闭入口", "待提升", "领先", "达标", "达标", "领先"],
    ["隐私政策—行为一致性", "达标", "领先", "达标", "达标", "领先"],
    ["食安抽检应对速度", "达标", "领先", "领先", "达标", "达标"],
]


def fig_waterlevel():
    head = ["合规控制点", "朴朴", "美团", "盒马", "叮咚", "京东到家"]
    th = "".join(f'<th class="c">{esc(h)}</th>' for h in head)
    trs = []
    for r in _WL_ROWS:
        tds = [f'<td class="lbl">{esc(r[0])}</td>']
        for v in r[1:]:
            tds.append(f'<td class="lv {_WL_CLS.get(v, "lv-na")}">{esc(v)}</td>')
        trs.append("<tr>" + "".join(tds) + "</tr>")
    inner = (f'<table class="ft"><thead><tr>{th}</tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')
    return figure(inner,
                  "图：行业合规水位对比矩阵（领先＝绿 / 达标＝黄 / 待提升＝红；朴朴当前相对短板集中于"
                  "资质动态预警、批次快检、算法备案公示与个性化广告关闭四项）",
                  "朴朴超市法务合规部基于同业公开合规实践对比评估")


def fig_food_sop():
    steps = [
        ('<div class="st">① 供应商到货 · 批次到仓</div>', True),
        ('<div class="st">② 资质 + 批次检验合格证明查验<br>（缺证明 → 直接拦截拒收）</div>', False),
        ('<div class="st">③ 入库快检：二氧化硫残留 + 农兽药残留<br>（噻虫嗪 / 胺 / 五氯酚酸钠）</div>', False),
        ('<div class="st">④ 判定：是否合格？</div>', False),
    ]
    out = ['<div class="sop">']
    for s, _ in steps:
        out.append(s)
        out.append('<div class="ar">▼</div>')
    out.append('<div class="br">'
               '<div class="st ok">合格 → 上架销售</div>'
               '<div class="st bad">不合格 → 一键下架召回<br>+ 通知采购 / 品控复核</div>'
               '</div>')
    out.append('<div class="ar">▼</div>')
    out.append('<div class="st ok" style="width:78%">⑤ 合格品：一品一码溯源 · 抽检通报后数分钟定位同批次</div>')
    out.append('</div>')
    return figure("".join(out),
                  "图：生鲜入库食安快检准入标准作业流程——资质与批次合格证明为硬门槛，快检不合格即一键下架召回",
                  "依据《食品安全法》及各地市场监管局快检通报要求梳理")


_PRICE_ROWS = [
    ("划线价 ¥99.9", "须有真实成交记录支撑：系统留存近 7 日最低成交价截图，禁止虚构原价 / 累加核算价"),
    ("促销价 ¥59.9", "规则事前公示：活动前 7 日均价 ¥89，本价低于均价，降幅说明清晰可查"),
    ("动态 / 差别定价", "向用户明示定价规则，禁止“杀熟”；同商品同用户可见价格一致或可解释"),
    ("免密支付 / 自动续期", "显著告知并一键取消，扣款前二次确认，不得默认勾选"),
]


def fig_price_sample():
    trs = []
    for k, v in _PRICE_ROWS:
        trs.append(f'<tr><td class="lbl" style="width:150px">{esc(k)}</td><td style="text-align:left">{esc(v)}</td></tr>')
    inner = ('<table class="ft"><thead><tr><th colspan="2">商品详情页价格展示（合规示范）</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')
    return figure(inner,
                  "图：商品详情页价格展示合规示范——划线价 / 促销价 / 动态定价 / 免密支付逐项留痕可举证",
                  "依据《明码标价和禁止价格欺诈规定》及典型处罚案例梳理")


_FRAME_CARDS = [
    ("数据合规", "个人信息保护 · 数据分类分级 · 第三方 SDK 治理"),
    ("AI 合规", "生成式内容标识 · 深度合成备案 · 智能客服转人工"),
    ("算法合规", "派单 / 推荐算法备案公示 · 可解释可申诉"),
    ("平台合规", "商户资质实质审查 · 入网核验 · 许可证照"),
    ("产品合规 · 食安", "生鲜快检硬门槛 · 一批一码溯源 · 召回闭环"),
    ("价格合规", "明码标价 · 禁止虚构原价 / 价格欺诈 · 动态定价明示"),
]


def fig_framework():
    cards = "".join(f'<div class="card"><b>{esc(n)}</b><span>{esc(f)}</span></div>'
                    for n, f in _FRAME_CARDS)
    inner = ('<div class="frm">'
             '<div class="hub">合规中枢：统一治理 · 风险识别—评估—控制—监测闭环</div>'
             f'<div class="grid6">{cards}</div></div>')
    return figure(inner,
                  "图：朴朴超市六大合规领域要点框架（中枢统领六域，逐域落到可落地控制点）",
                  "朴朴超市法务合规部基于六大合规领域监管脉络梳理")


_REG_ROWS = [
    ("算法备案与公示", "《算法推荐管理规定》第16条", "备案信息真实、公示入口可达", "公示入口已上线", "高"),
    ("AI 生成内容标识", "《AI生成合成内容标识办法》", "显式标识可见、隐式标识可溯", "标识口径尚不统一", "高"),
    ("第三方 SDK 治理", "《个人信息保护法》最小必要", "SDK 清单公示、权限最小化", "清单公示较普遍", "中"),
    ("生鲜快检与溯源", "《食品安全法》一批一码", "到货快检留痕、溯源链路可查", "快检公示程度参差", "中"),
    ("明码标价与动态定价", "《明码标价和禁止价格欺诈规定》", "划线价有据、动态定价规则明示", "划线价争议高发", "高"),
    ("商户资质实质审查", "《电子商务法》第27条", "入网核验、定期复核留痕", "审核深度差异较大", "低"),
]


def fig_reg_matrix():
    head = ["合规控制点", "监管依据", "自检要点", "同业普遍水位", "优先级"]
    th = "".join(f'<th class="c">{esc(h)}</th>' for h in head)
    trs = []
    for r in _REG_ROWS:
        trs.append(
            f'<tr><td class="lbl">{esc(r[0])}</td>'
            f'<td style="text-align:left">{esc(r[1])}</td>'
            f'<td style="text-align:left">{esc(r[2])}</td>'
            f'<td style="text-align:left">{esc(r[3])}</td>'
            f'<td class="lv {_LV_CLS.get(r[4], "lv-na")}">{esc(r[4])}</td></tr>')
    inner = (f'<table class="ft"><thead><tr>{th}</tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')
    return figure(inner,
                  "图：六大关键控制点监管要求对照自检矩阵——由监管依据落到自检要点，"
                  "优先级列（红＝高 / 黄＝中 / 绿＝低）定位本期优先整改项",
                  "依据现行法律法规及公开监管口径梳理，供业务方逐项自检")


# ============================================================ 页面骨架
def cover(meta, deep=False):
    tag = "深度分析版" if deep else "简版"
    bar = (f'<div class="brandbar"><span>{esc(meta["header_text"])}</span>'
           f'<span>{esc(tag)}</span></div>')
    return (f'<div class="cover">{bar}'
            f'<h1>{esc(meta["title"])}</h1>'
            f'<div class="en">{esc(meta["brief_en"])}</div>'
            f'<div class="sub">{esc(meta["subtitle"])}</div>'
            f'<div class="date">{esc(meta["date_str"])}</div>'
            f'<div class="org">朴朴超市 · 法务合规部</div>'
            f'<div class="motto">守护合规底线 · 支撑业务决策</div>'
            f'</div>')


def toc(items):
    lis = "".join(f'<li><a href="#{a}">{esc(t)}</a></li>' for a, t in items)
    return f'<div class="tocbox"><h2>目　录</h2><ol>{lis}</ol></div>'


def page(meta, body_html, deep=False, foot=None):
    tail = foot or "— 本简报由自动化任务生成，内容基于公开网络信息检索整理，仅供参考 —"
    return (f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8"/>\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
            f'<title>{esc(meta["title"])}{" （深度分析版）" if deep else ""} · {esc(meta["date_str"])}</title>\n'
            f'<style>{CSS}</style>\n</head>\n<body>\n<div class="page">\n'
            f'{cover(meta, deep)}\n{body_html}\n'
            f'<div class="foot">{esc(tail)}</div>\n</div>\n</body>\n</html>\n')


def save(html_str, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_str)
    print(f"HTML saved: {path}")
    return path


# ============================================================ 简版
def build_brief(data, meta):
    S = meta["sections"]
    out = [toc([("s-summary", S["summary"]), ("s-policy", S["policy"]),
                ("s-penalties", S["penalties"]), ("s-pupu", S["pupu"]),
                ("s-outlook", S["outlook"])])]

    # 一、今日综述
    out.append(h1_sec(S["summary"], "s-summary"))
    out.append(key_box(data["summary"], "本期核心观点"))

    # 二、六大领域动态回顾
    out.append(h1_sec(S["policy"], "s-policy"))
    for di, (domain, items) in enumerate(data["policy"]):
        out.append(h2_sub(f"{di + 1}. {domain}"))
        for item in items:
            out.append(h3_sub(item["title"]))
            out.append(body(item["meta"], "meta"))
            out.append(f'<p class="link">{link_html(item.get("url", ""))}</p>')
            out.append(label_body("【要点】", item["content"]).replace('class="body0"', 'class=""'))
            out.append(ana_block(item["analysis"], "解读"))
            out.append(divider())

    # 三、监管通报与处罚汇总
    out.append(h1_sec(S["penalties"], "s-penalties"))
    rows = []
    for r in data["penalties"]:
        cells = [esc(c) for c in r[:5]]
        cells.append(link_html(r[5]))
        rows.append(cells)
    out.append(data_table(["时间", "监管机构", "涉及对象", "违规事由", "处置措施", "来源"], rows))
    out.append(h3_sub("本期处罚统计小结", mark=""))
    for i, s in enumerate(data["penalty_stats"], 1):
        out.append(f'<p class="listitem"><span class="k2">{i}.</span>　{esc(s)}</p>')

    # 四、朴朴超市业务专题
    out.append(h1_sec(S["pupu"], "s-pupu"))
    out.append(note("说明：本板块聚焦与朴朴超市（生鲜电商 / 前置仓即时零售）业务直接相关的监管动态，"
                    "逐项评估合规风险等级（高 / 中高 / 中 / 低）并给出应对建议。"))
    out.append(fig_matrix(data["matrix_rows"]))
    for title, risk, scope, impact, action in data["pupu_items"]:
        color = {"高": RED, "中高": ORANGE, "中": AMBER, "低": GREEN}.get(risk, GRAY)
        out.append(f'<h4 class="sub3"><span class="mk">▍</span>{esc(title)}'
                   f'　<span style="color:{color}">【风险等级：{esc(risk)}】</span></h4>')
        out.append(label_body("涉及业务环节：", scope, color=BLUE))
        out.append(label_body("影响分析：", impact, color=NAVY).replace('class="body0"', 'class=""'))
        out.append(ana_block(action, "应对建议"))
        out.append(divider())

    # 五、明日前瞻
    out.append(h1_sec(S["outlook"], "s-outlook"))
    for i, r in enumerate(data["outlook"], 1):
        out.append(f'<p class="listitem"><span class="k2">{i}.</span>　{esc(r)}</p>')

    # 尾部
    out.append(h3_sub("信息来源与免责声明", mark=""))
    out.append(disclaimer("本简报"))

    p = os.path.join(OUT_DIR, meta["filename"].replace(".pdf", ".html"))
    return save(page(meta, "".join(out), deep=False,
                     foot="— 本简报由自动化任务每日生成，内容基于公开网络信息检索整理，仅供参考 —"), p)


# ============================================================ 深度版
def build_deep(base_data, base_meta):
    S = base_meta["sections"]
    out = [toc([("s-summary", S["summary"]), ("s-policy", S["policy"]),
                ("s-deep", "六、六大领域深度分析"), ("s-survey", "七、行业水位调研"),
                ("s-case", "八、违规与合规案例参考"), ("s-penalties", S["penalties"]),
                ("s-pupu", S["pupu"]), ("s-focus", "九（补）、合规焦点专题"),
                ("s-quotes", "十（补）、监管法规条文摘录"), ("s-roadmap", "十一（补）、90 天合规落地路线图"),
                ("s-gap", "十二（补）、合规差距自评估矩阵"), ("s-caseinterp", "十三（补）、案例深度解读"),
                ("s-timeline", "十四（补）、监管关键节点与合规日历"), ("s-gov", "十五（补）、合规治理与组织职责建议"),
                ("s-ext", "九、关联延伸"), ("s-outlook", S["outlook"])])]

    # 一、今日综述
    out.append(h1_sec(S["summary"], "s-summary"))
    out.append(key_box(base_data["summary"], "本期核心观点"))

    # 二、六大领域动态回顾
    out.append(h1_sec(S["policy"], "s-policy"))
    for di, (domain, items) in enumerate(base_data["policy"]):
        out.append(h2_sub(f"{di + 1}. {domain}"))
        for item in items:
            out.append(h3_sub(item["title"]))
            out.append(body(item["meta"], "meta"))
            out.append(f'<p class="link">{link_html(item.get("url", ""))}</p>')
            out.append(label_body("【要点】", item["content"]).replace('class="body0"', 'class=""'))
            out.append(ana_block(item["analysis"], "解读"))
            out.append(divider())

    # 六、六大领域深度分析
    out.append(h1_sec("六、六大领域深度分析", "s-deep"))
    out.append(note("本板块对六大合规领域逐一展开：监管脉络与立法意图、对朴朴超市业务的影响传导路径、"
                    "同业水位与标杆做法、可落地的控制建议。"))
    for di, (domain, _) in enumerate(base_data["policy"], 1):
        d = DD.DOMAIN_DEEP.get(domain)
        if not d:
            continue
        out.append(h2_sub(f"{di}. {domain} —— 深度分析"))
        for label, key in [("监管脉络与立法意图", "脉络"), ("对朴朴业务的影响传导路径", "影响路径"),
                           ("同业水位与标杆做法", "同业水位"), ("可落地控制建议", "控制建议"),
                           ("法条依据", "法条依据"), ("业务映射（朴朴）", "业务映射"),
                           ("风险信号与预警", "风险信号"), ("分阶段落地步骤", "落地步骤"),
                           ("判例与延展（真实案例参照）", "判例与延展")]:
            out.append(h3_sub(label))
            out.append(body(d[key]))
        out.append(h3_sub("分领域合规自查清单（可直接转化为内部检查表）"))
        for it in DD.CHECK_LISTS.get(domain, []):
            out.append(f'<p><span class="k">✓</span> {esc(it)}</p>')
        out.append(divider())

    # 七、行业水位调研
    out.append(h1_sec("七、行业水位调研", "s-survey"))
    out.append(note("下表从九项合规维度，对比头部平台现行水位、中小平台常见短板，"
                    "并给出朴朴可达的目标水位，作为内部差距分析（Gap Analysis）基线。"))
    out.append(data_table(DD.INDUSTRY_SURVEY["cols"],
                          [[esc(c) for c in r] for r in DD.INDUSTRY_SURVEY["rows"]]))
    out.append(body("调研结论：头部平台已在数据分级、第三方 SDK 治理、资质实质审查、生鲜快检溯源四个维度形成明显领先；"
                    "朴朴应优先补齐“资质动态预警”与“批次快检硬门槛”两项高杠杆控制点，再以头部水位为中期目标。"))
    out.append(h2_sub("同业深度画像"))
    for name, prof in DD.PEER_PROFILES:
        out.append(h3_sub(name))
        out.append(body(prof))
    out.append(divider())

    # 具像化合规参考图示与样例
    out.append(h2_sub("具像化合规参考图示与样例"))
    out.append(note("以下以可落地的图示与样例，将“行业水位”转译为可直接对照的准入流程与展示规范，"
                    "便于业务侧按图执行。"))
    out.append(h3_sub("① 行业合规水位对比（朴朴 vs 同业，按控制点）"))
    out.append(fig_waterlevel())
    out.append(h3_sub("② 监管要求对照自检矩阵（控制点 × 监管依据 / 自检要点 / 同业水位 / 优先级）"))
    out.append(fig_reg_matrix())
    out.append(h3_sub("③ 食安快检准入 SOP（具像化流程样例）"))
    out.append(fig_food_sop())
    out.append(h3_sub("④ 价格展示合规自检清单样例（合规模板）"))
    out.append(fig_price_sample())
    out.append(h3_sub("⑤ 六大合规领域要点框架（中枢统领六域）"))
    out.append(fig_framework())
    out.append(divider())

    # 八、违规与合规案例参考
    out.append(h1_sec("八、违规与合规案例参考", "s-case"))
    out.append(note("下表汇总本期及近期典型违规案例与可借鉴的合规标杆，供内部对照排查。"
                    "“违规”类提示雷区，“合规参考”类提示可复用做法。"))
    crows = []
    for c in DD.CASE_REFS:
        crows.append([esc(c[0]), esc(c[1]),
                      esc(c[2]) + ("<br/>" + link_html(c[5]) if len(c) > 5 and c[5] else ""),
                      esc(c[3]), esc(c[4])])
    out.append(data_table(["类型", "案例 / 实践", "来源 / 文号", "处置 / 效果", "对朴朴的启示"], crows))

    # 三、监管通报与处罚汇总
    out.append(h1_sec(S["penalties"], "s-penalties"))
    prows = []
    for r in base_data["penalties"]:
        cells = [esc(c) for c in r[:5]]
        cells.append(link_html(r[5]))
        prows.append(cells)
    out.append(data_table(["时间", "监管机构", "涉及对象", "违规事由", "处置措施", "来源"], prows))
    for i, s in enumerate(base_data["penalty_stats"], 1):
        out.append(f'<p class="listitem"><span class="k2">{i}.</span>　{esc(s)}</p>')

    # 四、朴朴超市业务专题
    out.append(h1_sec(S["pupu"], "s-pupu"))
    out.append(note("说明：本板块聚焦与朴朴超市（生鲜电商 / 前置仓即时零售）业务直接相关的监管动态，"
                    "逐项评估合规风险等级并给出应对建议。"))
    out.append(fig_matrix(base_data["matrix_rows"]))
    for title, risk, scope, impact, action in base_data["pupu_items"]:
        color = {"高": RED, "中高": ORANGE, "中": AMBER, "低": GREEN}.get(risk, GRAY)
        out.append(f'<h4 class="sub3"><span class="mk">▍</span>{esc(title)}'
                   f'　<span style="color:{color}">【风险等级：{esc(risk)}】</span></h4>')
        out.append(label_body("涉及业务环节：", scope, color=BLUE))
        out.append(label_body("影响分析：", impact, color=NAVY).replace('class="body0"', 'class=""'))
        out.append(ana_block(action, "应对建议"))
        out.append(divider())

    # 九（补）、合规焦点专题
    out.append(h1_sec("九（补）、合规焦点专题", "s-focus"))
    out.append(note("本板块针对与朴朴超市业务最相关的五项合规焦点，逐篇展开监管要点、对业务的映射与可落地控制清单。"))
    for i, (title, paras) in enumerate(DD.FOCUS_TOPICS, 1):
        out.append(h2_sub(f"{i}. {title}"))
        for label, txt in [("监管要点", paras[0]), ("业务映射", paras[1]), ("控制清单", paras[2])]:
            out.append(h3_sub(label))
            out.append(body(txt))
        out.append(divider())

    # 十（补）、监管法规条文摘录
    out.append(h1_sec("十（补）、监管法规条文摘录", "s-quotes"))
    out.append(note("本板块逐领域引述当前有效、与朴朴业务直接相关的关键条文，供内部对照自查。"))
    for dom, src, quotes in DD.REG_QUOTES:
        out.append(h3_sub(f"{dom} —— {src}"))
        for q in quotes:
            out.append(f'<p><span class="k2">·</span>　{esc(q)}</p>')
        out.append(divider())

    # 十一（补）、90 天合规落地路线图
    out.append(h1_sec("十一（补）、90 天合规落地路线图", "s-roadmap"))
    out.append(note("结合本期风险研判，给出分三阶段、可落地的合规加固路线，作为内部排期基线。"))
    out.append(data_table(DD.ROADMAP["cols"], [[esc(c) for c in r] for r in DD.ROADMAP["rows"]]))

    # 十二（补）、合规差距自评估矩阵
    out.append(h1_sec("十二（补）、合规差距自评估矩阵", "s-gap"))
    out.append(note("下表将六大领域关键控制点转化为可排期的内部自查表。状态采用“建议口径”（建议启动 / 待建 / "
                    "待核查 / 进行中 / 部分存在），便于后续据实更新；责任归属与目标时间窗供跨部门对齐，"
                    "建议每月滚动复核一次，并将完成进度回填本表。"))
    out.append(data_table(DD.GAP_MATRIX["cols"], [[esc(c) for c in r] for r in DD.GAP_MATRIX["rows"]]))

    # 十三（补）、案例深度解读
    out.append(h1_sec("十三（补）、案例深度解读", "s-caseinterp"))
    out.append(note("本板块对本期重点案例作延伸剖析，提炼对朴朴超市可直接复用的控制启示。"))
    for title, txt in DD.CASE_INTERP:
        out.append(h3_sub(title))
        out.append(body(txt))

    # 十四（补）、监管关键节点与合规日历
    out.append(h1_sec("十四（补）、监管关键节点与合规日历", "s-timeline"))
    out.append(note("下表将关键监管节点与内部排期对齐，供跨部门排期基线参考。"))
    out.append(data_table(["时间窗", "监管 / 内部节点", "朴朴应对动作"],
                          [[esc(c) for c in r] for r in DD.TIMELINE]))

    # 十五（补）、合规治理与组织职责建议
    out.append(h1_sec("十五（补）、合规治理与组织职责建议", "s-gov"))
    out.append(note("本板块供内部搭建合规治理框架参照，可按实际组织情况裁剪。"))
    for txt in DD.GOV:
        out.append(body(txt))

    # 九、关联延伸
    out.append(h1_sec("九、关联延伸", "s-ext"))
    out.append(note("本板块将分散的合规议题跨领域联动，识别风险叠加点与治理复用机会。"))
    for i, r in enumerate(DD.EXTENSIONS, 1):
        out.append(f'<p class="listitem"><span class="k2">{i}.</span>　{esc(r)}</p>')

    # 五、前瞻
    out.append(h1_sec(S["outlook"], "s-outlook"))
    for i, r in enumerate(base_data["outlook"], 1):
        out.append(f'<p class="listitem"><span class="k2">{i}.</span>　{esc(r)}</p>')
    out.append(h3_sub("深度情景展望：", mark=""))
    for i, r in enumerate(DD.DEEP_OUTLOOK, 1):
        out.append(f'<p class="listitem"><span class="k2">{i}.</span>　{esc(r)}</p>')

    # 尾部
    out.append(h3_sub("信息来源与免责声明", mark=""))
    out.append(disclaimer("本报告"))

    deep_name = base_meta["filename"].replace(".pdf", "_深度分析版.html")
    p = os.path.join(OUT_DIR, deep_name)
    return save(page(base_meta, "".join(out), deep=True,
                     foot="— 本报告为深度分析版，内容基于公开网络信息检索与行业研究整理，仅供参考，不构成法律意见 —"), p)


if __name__ == "__main__":
    build_brief(WD.DATA, WD.META)
    build_deep(WD.DATA, WD.META)
    # 自动刷新报告索引页（新增报告自动纳入汇总检索页）
    try:
        import gen_index_html
        gen_index_html.build()
    except Exception as e:
        print(f"[index] 索引刷新跳过: {e}")
