#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规标准知识库」页 kb/standards.html

数据源：sources/standards/library.json（由 build_library_data.py 生成）
视图一  资料库：按专题 / 层级 / 时效性 三维筛选 + 关键词检索
视图二  合规义务清单：① 矩阵总览（主题大类 × 业务场景，一屏看全规模与整改优先级分布）
                       ② 逐条明细（每项义务反查条款原文、标杆做法与可套用文案）

幂等：输出后自动调用 unify_chrome + inject_meta 恢复页头页脚与分享元数据。
"""
import os, re, json, html, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "standards", "library.json")
DRAFTS = os.path.join(HERE, "sources", "library", "drafts.json")
# 合规义务清单（主题大类 → 场景 → 具体义务 三级），与条目库分开维护
DUTY_SRC = os.path.join(HERE, "sources", "standards", "duties.json")


def esc(s):
    return html.escape(str(s or ""), quote=True)


# ------------------------------------------------------------------ 页面骨架
def page(title, desc, crumb, h1, lead, body, depth=1):
    prefix = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} · 合规无终点</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="{prefix}index.html">首页</a> / {crumb}</div>
  <h1>{esc(h1)}</h1>
  <p>{esc(lead)}</p>
</div></div>

<main class="wrap">
{body}
</main>

<footer></footer>
</body>
</html>
"""


STATUS_CLS = {"现行有效": "b-green", "即将实施": "b-blue", "已废止": "b-red",
              "已修改": "b-amber", "征求意见中": "b-amber"}
LEVEL_CLS = {"法律": "b-purple", "行政法规": "b-purple", "部门规章": "b-blue",
             "规范性文件": "b-amber", "强制性国家标准": "b-red",
             "推荐性国家标准": "b-green", "国家标准化指导性技术文件": "b-ghost",
             "指引/指南": "b-ghost"}

# 站内法规原文库（build_texts.py 产出）的条目映射
TEXT_IDS = os.path.join(HERE, "sources", "standards", "text_ids.json")
# 法规修订沿革（tools/build_amendments.py 从官方前言提炼，P2-4）
AMEND = os.path.join(HERE, "sources", "standards", "amendments.json")
_AM = None


def load_amendments():
    global _AM
    if _AM is None:
        try:
            _AM = json.load(open(AMEND, encoding="utf-8")).get("items", {})
        except Exception:
            _AM = {}
    return _AM


def amend_text(am):
    """把沿革数据写成一句话：经 N 次修正／修订 · 最近 YYYY-MM-DD。"""
    if not am or not am.get("n"):
        return ""
    last = am.get("last") or ""
    return "经 %d 次%s%s" % (am["n"], am.get("kind") or "修正",
                            (" · 最近 " + last) if last else "")
SEP_RE = re.compile(r"[\s\-—–/／\\()（）《》〈〉【】\[\]:：.、,，;；·|'\"]+")
_TID = None


def _nkey(s):
    return SEP_RE.sub("", (s or "")).upper()


def text_id(it):
    global _TID
    if _TID is None:
        try:
            _TID = json.load(open(TEXT_IDS, encoding="utf-8"))
        except Exception:
            _TID = {}
    return _TID.get(_nkey((it.get("code") or "") + (it.get("name") or "")), "")


def text_id_count():
    global _TID
    if _TID is None:
        try:
            _TID = json.load(open(TEXT_IDS, encoding="utf-8"))
        except Exception:
            _TID = {}
    return len(_TID)


def std_online_count():
    """站内可直接阅读的标准正文部数（build_std_texts 产出的 std_index.json）。"""
    try:
        d = json.load(open(os.path.join(HERE, "kb", "texts", "std_index.json"),
                           encoding="utf-8"))
        return (d or {}).get("_meta", {}).get("count", 0)
    except Exception:
        return 0


def law_online_count():
    """站内可直接阅读的法规部数（阅读器 index.json 的实际条目数）。

    与 text_ids.json 的差值来自「有原文映射但没过正文质量闸」的少数条目，
    以阅读器实际能打开的部数为准，避免与原文库页面上的数字对不上。
    """
    try:
        d = json.load(open(os.path.join(HERE, "kb", "texts", "index.json"),
                           encoding="utf-8"))
        m = (d or {}).get("_meta", {})
        return m.get("laws") or sum(1 for x in d.get("items", [])
                                    if x.get("kind") == "law")
    except Exception:
        return 0


def hot_counts():
    """高频引用法条规模：(法条数, 案例数)。"""
    try:
        d = json.load(open(os.path.join(HERE, "sources", "standards", "hot_articles.json"),
                           encoding="utf-8"))
    except Exception:
        return 0, 0
    items = d.get("items", [])
    return len(items), sum(len(x.get("cases", [])) for x in items)


def case_count():
    """案例库规模（kb/cases.html 的条目数）。"""
    try:
        d = json.load(open(os.path.join(HERE, "sources", "cases", "cases.json"),
                           encoding="utf-8"))
        return int((d.get("meta") or {}).get("count") or len(d.get("cases") or []))
    except Exception:
        return 0


def online_reader_url(it):
    """标准类：openstd 详情深链 → 官方「在线预览」阅读器深链（图片式全文，供读者自行查阅）。"""
    m = re.search(r"[?&]hcno=([A-Fa-f0-9]{32})", it.get("url") or "")
    if m:
        return ("https://openstd.samr.gov.cn/bzgk/std/showGb?type=online&hcno=" + m.group(1))
    return ""


# 抓取台账：给出「发布机构公开可直接下载的正文」深链（目前主要是行业标准）
LEDGER = os.path.join(HERE, "sources", "standards", "harvest_ledger.json")
COMPETE = os.path.join(HERE, "sources", "standards", "compete_law.json")
STD_PDF = os.path.join(HERE, "kb", "texts", "std_pdf.json")
STD_TEXT_IDS = os.path.join(HERE, "sources", "standards", "std_text_ids.json")
_SPDF = None
_STID = None


def std_text_ids():
    """标准编号（归一化）→ 站内标准正文 id。键含 `STD::` 前缀版与裸编号版两种。"""
    global _STID
    if _STID is None:
        try:
            _STID = json.load(open(STD_TEXT_IDS, encoding="utf-8"))
        except Exception:
            _STID = {}
    return _STID


def std_pdf_map():
    """{原文 id: {file,pages,bytes}} —— 站点内已发布的原版标准 PDF。"""
    global _SPDF
    if _SPDF is None:
        try:
            _SPDF = json.load(open(STD_PDF, encoding="utf-8")).get("items", {})
        except Exception:
            _SPDF = {}
    return _SPDF
_LED = None


def ledger_pdf_url(it):
    global _LED
    if _LED is None:
        try:
            _LED = json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            _LED = {}
    code = (it.get("code") or "").strip()
    if not code:
        return ""
    hits = [v for k, v in _LED.items()
            if isinstance(v, dict) and (v.get("code") or "").strip() == code and v.get("pdf_url")]
    return hits[0]["pdf_url"] if hits else ""


def _region_of(it):
    """判地域：法规库的「地域范围」维度（威科先行有，我们也需要）。

    只对地方法规/地方标准有意义；用发布机关里的行政区名判定，判定不出归「全国」。
    计划单列市单列（深圳/青岛/大连/宁波/厦门），因为它们的立法权与省级并列。
    """
    s = (it.get("issuer") or "") + " " + (it.get("name") or "")
    for city in ("深圳", "青岛", "大连", "宁波", "厦门"):
        if city in s:
            return city
    for p in _PROVINCES:
        if p in s:
            return p
    return "全国"


_PROVINCES = [
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "内蒙古", "广西", "西藏", "宁夏", "新疆",
]

# 左栏「地域范围」的展示顺序：全国在前，其余按经济活跃度与我们业务的关注度排
_REGION_ORDER = (["全国"] + _PROVINCES[:4]
                 + ["广东", "江苏", "浙江", "山东", "四川", "河南", "湖北", "湖南",
                    "福建", "安徽", "河北", "辽宁", "陕西", "江西", "广西", "云南",
                    "山西", "吉林", "黑龙江", "贵州", "海南",
                    "内蒙古", "新疆", "甘肃", "宁夏", "青海", "西藏"]
                 + ["深圳", "青岛", "大连", "宁波", "厦门"])


def pub_trend(items, months=12):
    """近 N 个月的发布量迷你折线（P2-5，对标律商网的逐年数据量折线）。

    为什么放在法规库：左栏的「发布日期」facet 只能告诉你「哪些是近 1 个月」，
    看不出「最近在密集出什么」的趋势。这里给一条一屏可读完的走势，
    峰值月份直接标出来，不占正文位置（高约 30px，不做大图）。
    只统计**合规相关**条目，与页面默认视图口径一致。
    """
    today = datetime.date.today()
    yms = []
    for i in range(months - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        yms.append((y, m))
    cnt = collections.Counter()
    for x in items:
        if not x.get("rel"):
            continue
        m = re.match(r"(\d{4})-(\d{2})", x.get("pub") or "")
        if m:
            cnt[(int(m.group(1)), int(m.group(2)))] += 1
    vals = [cnt.get(k, 0) for k in yms]
    mx = max(vals) or 1
    pk = vals.index(max(vals))
    W, H, PL, PR, TOP, BASE = 320.0, 30.0, 3.0, 3.0, 3.0, 26.0
    n = len(vals)
    step = (W - PL - PR) / (n - 1)
    pts = [(PL + i * step, BASE - (v / mx) * (BASE - TOP)) for i, v in enumerate(vals)]
    poly = " ".join("%.1f,%.1f" % p for p in pts)
    area = ("M%.1f,%.1f L" % (pts[0][0], BASE)) + " L".join(
        "%.1f,%.1f" % p for p in pts) + " L%.1f,%.1f Z" % (pts[-1][0], BASE)
    dots = "".join(
        '<circle cx="%.1f" cy="%.1f" r="%s"><title>%04d-%02d：%d 条</title></circle>'
        % (p[0], p[1], "2.6" if i == pk else "1.7", yms[i][0], yms[i][1], vals[i])
        for i, p in enumerate(pts))
    lab = '%04d-%02d' % yms[pk]
    return (
        '<div class="lv-trend">'
        '<span class="lv-trend-l">近 12 个月发布量</span>'
        '<svg class="lv-spark" viewBox="0 0 %d %d" width="128" height="30" '
        'role="img" aria-label="近 12 个月条目发布量走势">'
        '<path class="lv-spark-a" d="%s"/><polyline class="lv-spark-l" points="%s"/>%s</svg>'
        '<span class="lv-trend-v">峰值 <b>%d</b> 条 · %s</span>'
        '<span class="lv-trend-x">%04d-%02d → %04d-%02d</span>'
        '</div>'
    ) % (int(W), int(H), area, poly, dots, mx, lab,
         yms[0][0], yms[0][1], yms[-1][0], yms[-1][1])


def read_affordance(it):
    """条目上的原文入口：站内原版 PDF 直读 → 站内原文库 → 发布机构公开 PDF → 官方在线阅读器。"""
    tid = text_id(it)
    if not tid:
        c = _nkey(it.get("code") or "")
        if c:
            tid = std_text_ids().get("STD::" + c) or std_text_ids().get(c) or ""
    if tid and tid in std_pdf_map():
        return (f'<a class="lb-read lb-read-pdf" href="texts.html#{tid}" '
                f'title="站内原版 PDF：版式与官方发布件一致">原版 PDF 直读</a>')
    if tid:
        return f'<a class="lb-read" href="texts.html#{tid}">读原文</a>'
    pdf = ledger_pdf_url(it)
    if pdf:
        return (f'<a class="lb-read" href="{esc(pdf)}" target="_blank" rel="noopener" '
                f'title="发布机构公开的标准全文 PDF">官方全文 PDF</a>')
    ou = online_reader_url(it)
    if ou:
        return f'<a class="lb-read" href="{esc(ou)}" target="_blank" rel="noopener">官方在线阅读</a>'
    # 国家法律法规数据库的深链本身就是官方全文阅读页（正文由该站自己的阅读器渲染）。
    # 站内原文库还没抓到全文的条目，至少让读者一步直达官方原文——不能只留个空档。
    if "flk.npc.gov.cn/detail2.html" in (it.get("url") or ""):
        return (f'<a class="lb-read" href="{esc(it["url"])}" target="_blank" '
                f'rel="noopener" title="国家法律法规数据库·官方全文">官方原文</a>')
    return ""


def item_card(it, idx):
    st = it.get("status", "现行有效")
    lv = it.get("level", "")
    tags = "".join(f'<span class="rd-tag">{esc(t)}</span>' for t in it.get("duty", [])[:4])
    dates = []
    if it.get("pub"):
        dates.append(f"发布 {it['pub']}")
    if it.get("impl"):
        dates.append(f"实施 {it['impl']}")
    meta = " · ".join(dates)
    note = f'<div class="rd-prog"><b>要点</b>{esc(it["point"])}</div>' if it.get("point") else ""
    extra = f'<div class="rd-prog"><b>注</b>{esc(it["note"])}</div>' if it.get("note") else ""
    # 标题：有官方深链才做成链接
    title = esc(it["name"])
    if it.get("url"):
        title = (f'<a href="{esc(it["url"])}" target="_blank" rel="noopener">{title}</a>'
                 f'<span class="lb-ext" title="打开发布机构官网原文">↗</span>')
    elif it.get("local"):
        title = f'{title}<span class="lb-local" title="本机存有原文，可离线查阅">本机原文</span>'
    # 章节目录（可阅读：直接看到标准的结构）
    toc = it.get("toc") or []
    toc_html = ""
    if len(toc) >= 3:
        lis = "".join(f"<li>{esc(t)}</li>" for t in toc[:40])
        toc_html = (f'<details class="lb-toc"><summary>章节目录'
                    f'<i>{len(toc)} 节</i></summary><ol class="lb-toclist">{lis}</ol></details>')
    metaparts = [p for p in [it.get("code", ""), it.get("issuer", ""), meta] if p]
    return f"""<div class="rd-item lb-item" data-topic="{esc(it.get('topic',''))}" \
data-level="{esc(lv)}" data-status="{esc(st)}" data-code="{esc(it.get('code',''))}" \
data-text="{esc((it.get('name','')+' '+it.get('code','')+' '+it.get('issuer','')+' '+' '.join(toc)).lower())}">
  <div class="rd-body">
    <div class="rd-row">
      <span class="rd-badge {STATUS_CLS.get(st,'b-ghost')}">{esc(st)}</span>
      <span class="rd-badge {LEVEL_CLS.get(lv,'b-ghost')}">{esc(lv)}</span>
      <span class="rd-tag tg-region">{esc(it.get('topic',''))}</span>
      {read_affordance(it)}
    </div>
    <h3>{title}</h3>
    <div class="rd-meta">{esc(' · '.join(metaparts))}</div>
    {note}{extra}{toc_html}
    <div class="rd-targets">{tags}</div>
  </div>
</div>"""


def draft_card(d):
    """草案跟踪卡片：倒计时 + 状态 + 官方征求意见深链"""
    days = d.get("days_left")
    if days is not None and days >= 0:
        cnt = f'<span class="lb-days hot">剩 {days} 天</span>'
    elif days is not None:
        cnt = f'<span class="lb-days">已截止</span>'
    else:
        cnt = ""
    st = d.get("status", "")
    cls = "b-red" if ("未正式发布" in st or "悬置" in st) else ("b-amber" if "中" in st else "b-ghost")
    span = ""
    if d.get("start") and d.get("end"):
        span = f'<span class="lb-when">{esc(d["start"])} → {esc(d["end"])}</span>'
    note = f'<div class="rd-prog"><b>要点</b>{esc(d["note"])}</div>' if d.get("note") else ""
    return f"""<div class="rd-item lb-item lb-draft" data-text="{esc((d.get('name','')+' '+d.get('issuer','')+' '+d.get('note','')).lower())}">
  <div class="rd-body">
    <div class="rd-row">
      <span class="rd-badge {cls}">{esc(st)}</span>
      <span class="rd-badge b-ghost">{esc(d.get('kind',''))}</span>
      {cnt}
    </div>
    <h3><a href="{esc(d['url'])}" target="_blank" rel="noopener">{esc(d['name'])}</a>
      <span class="lb-ext" title="打开官方征求意见通知">↗</span></h3>
    <div class="rd-meta">{esc(d.get('issuer',''))}{(' · ' + span) if span else ''}</div>
    {note}
  </div>
</div>"""


def build_kb_index(items, duties, drafts, soon, stat_html="", board=""):
    """合规知识库总览：定位三大件入口 + 时效提醒 + 模块边界说明。

    与 build_topics.py 的分工：动态类内容（合规动态、应对建议）归「合规资讯」，
    这里只放长效知识——法规标准原文、义务清单、立法草案。
    """
    today = datetime.date.today().isoformat()
    n_std = sum(1 for x in items if x.get("kind") == "标准")
    n_law = len(items) - n_std
    n_local = sum(1 for x in items if x.get("local"))
    n_sooner = len(soon)
    # 合规相关性口径（与 build_library_data.mark_relevance 一致）：rel=1 才计入展示口径
    # 2026-09-17：法规库的「收录范围」开关已删除（页面本就全量呈现），
    # 总览卡片随之改为全量口径，不再用「仅合规相关」的 rel 计数 —— 否则
    # 卡片数字与进库后看到的条数对不上。
    n_all = len(items)
    n_law_all = n_law
    n_std_all = n_std
    n_rel_all = sum(1 for x in items if x.get("rel"))  # 仍用于首页等处

    # 草案按截止日排序，取最近 5 条
    dl = sorted([d for d in drafts if (d.get("days_left") or 9999) >= 0],
                key=lambda d: d.get("days_left") or 9999)[:5]
    if dl:
        rows = "".join(
            f'<div class="lb-row"><span class="lb-days{" hot" if (d.get("days_left") or 99) <= 14 else ""}">'
            f'剩 {d["days_left"]} 天</span>'
            f'<a href="{esc(d["url"])}" target="_blank" rel="noopener">{esc(d["name"])}</a>'
            f'<span class="lb-when">{esc(d.get("end", ""))} 截止</span></div>'
            for d in dl)
        draft_html = f'<div class="lb-rows">{rows}</div>'
    else:
        draft_html = '<p class="lb-empty">暂无进行中的征求意见。</p>'

    if soon:
        srows = "".join(
            f'<div class="lb-row"><span class="rd-badge b-blue">即将实施</span>'
            f'<a href="standards.html" >{esc(x["name"])}</a>'
            f'<span class="lb-when">{esc(x.get("impl", ""))} 施行</span></div>'
            for x in soon[:5])
        soon_html = f'<div class="lb-rows">{srows}</div>'
    else:
        soon_html = '<p class="lb-empty">暂无即将实施条目。</p>'
    n_online = law_online_count()
    n_std_online = std_online_count()
    n_hot, n_case = hot_counts()
    n_cases = case_count()

    # 义务清单统计（重构后为 大类 → 场景 → 义务 三级）
    cats = duties.get("categories", []) if isinstance(duties, dict) else []
    if cats:
        n_cat = len(cats)
        n_scene = sum(len(c.get("scenes", [])) for c in cats)
        n_duty = sum(len(s.get("duties", [])) for c in cats for s in c.get("scenes", []))
        duty_desc = f"{n_cat} 个主题大类 · {n_scene} 个场景 · {n_duty} 项具体义务"
    else:
        n_duty = len(duties)
        duty_desc = f"{n_duty} 项合规义务"

    body = f"""
  {stat_html}
  <div class="lb-split lb-split6">
    <a class="dcard lb-entry" href="standards.html" style="--dc:#0f7b6c">
      <b>&#128218; 法规库</b>
      <span><strong>{n_all}</strong> 条目 · 法律法规 <strong>{n_law_all}</strong> / 标准 <strong>{n_std_all}</strong>
      · <strong>{n_online + n_std_online}</strong> 份官方正文</span>
      <span class="more">进入法规库 →</span>
    </a>
    <a class="dcard lb-entry" href="duties.html" style="--dc:#1b4f8a">
      <b>🎯 合规义务清单</b>
      <span><strong>{n_cat}</strong> 个主题大类 · <strong>{n_scene}</strong> 个场景 ·
      <strong>{n_duty}</strong> 项具体义务</span>
      <span class="more">查看义务清单 →</span>
    </a>
    <a class="dcard lb-entry" href="citations.html" style="--dc:#b91c1c">
      <b>⚖️ 高频引用法条</b>
      <span><strong>{n_hot}</strong> 条高频被引条款 · 附 <strong>{n_case}</strong> 个真实案例</span>
      <span class="more">查看高频法条 →</span>
    </a>
    <a class="dcard lb-entry" href="cases.html" style="--dc:#a16207">
      <b>📁 合规案例库</b>
      <span><strong>{n_cases}</strong> 个处罚决定与通报案例 · 逐条附官方原文深链</span>
      <span class="more">进入案例库 →</span>
    </a>
    <a class="dcard lb-entry" href="../manage/index.html" style="--dc:#0f766e">
      <b>&#128451; 合规管理</b>
      <span>勾选审计范围 → 记录结论 → 输出审计报告与整改清单</span>
      <span class="more">进入合规管理 →</span>
    </a>
    <a class="dcard lb-entry" href="standards.html#pane-draft" style="--dc:#b45309">
      <b>📌 立法草案跟踪</b>
      <span><strong>{len(drafts)}</strong> 项在途立法与征求意见 · 标注截止日与剩余天数</span>
      <span class="more">查看草案 →</span>
    </a>
  </div>

  <div class="section-title"><span class="bar"></span>时效看板</div>
  {board}

  <div class="section-title"><span class="bar"></span>征求意见截止</div>
  <div class="lb-col">
      {draft_html}
  </div>

  <div class="section-title"><span class="bar"></span>三个模块怎么分</div>
  <div class="notice">
    本站内容按<b>时间属性</b>划分，避免同一条信息在多个模块重复出现：
  </div>
  <div class="lb-bound">
    <div class="lb-bd">
      <div class="lb-bd-h"><b>合规动态</b><span class="lb-tag t-future">未来 / 进行中 · 每日更新</span></div>
      <p>何时生效、何地监管、发生了什么、该做什么 —— 每日更新。</p>
      <a href="../news/index.html">进入合规动态 →</a>
    </div>
    <div class="lb-bd on">
      <div class="lb-bd-h"><b>合规知识库</b><span class="lb-tag t-long">长期稳定</span></div>
      <p>规则本身是什么 —— 法规标准、合规义务、在途草案，长期稳定。</p>
      <span class="lb-here">当前位置</span>
    </div>
  </div>
"""
    out = page(
        "合规知识库",
        "法规与标准原文、按主题拆解的合规义务清单、高频引用法条与合规审计工具——长效合规知识资产。",
        "合规知识库",
        "合规知识库",
        "长效知识资产：法规与标准原文、按主题拆解的合规义务、高频引用法条与监管案例、可落地的合规审计工具。",
        body,
    )
    dst = os.path.join(HERE, "kb", "index.html")
    open(dst, "w", encoding="utf-8").write(out)
    print(f"  kb/index.html        {len(out)} B  ✓  （知识库总览）")


RISK_CLS = {"高": "r-hi", "中高": "r-mh", "中": "r-md", "低": "r-lo"}


# 泛化词：它们是多份文件的共同前缀，用于名称匹配会张冠李戴（如「网络安全标准实践指南」
# 会误配到「敏感个人信息识别指南」）。这类词一律不反查链接，只作纯文字标注。
AMBIGUOUS_REFS = {
    "网络安全标准实践指南", "数据安全技术", "网络安全技术", "信息安全技术", "信息技术",
    "移动互联网应用程序", "中国互联网协会", "食品安全国家标准",
}


def norm_code(s):
    """标准号归一化：去空格/连字符、统一大小写。GB/T 35273 ↔ GB/T35273。"""
    return re.sub(r"[\s—–－-]+", "", (s or "")).upper()


def name_match(ref, name):
    """法规名匹配。短名（如「广告法」）要求与条目名去掉「中华人民共和国」后完全一致，
    避免子串误配；长名（≥6 字）允许包含匹配。
    """
    name = name or ""
    if ref not in name:
        return False
    if len(ref) >= 6:
        return True
    core = re.sub(r"^中华人民共和国", "", name).strip()
    core = re.sub(r"[（(].*?[)）]\s*$", "", core).strip()
    core = re.sub(r"\s*(节选|摘录|全文)\s*$", "", core).strip()
    return core == ref


def short_law(name):
    """显示用短名：去掉「中华人民共和国」前缀。全称仍保留在 title 里，不丢信息。"""
    n = (name or "").strip()
    return n[7:] if n.startswith("中华人民共和国") and len(n) > 9 else n


def ref_label(x):
    """依据标签：能当文号用就用 code，否则退回法规名。

    ⚠️ library.json 里有 6400 多条常用依据的 code 字段其实就是效力级别本身
    （地方法规 3037 / 修改决定 2537 / 司法解释 873 / 行政法规 687 / 法律 352 /
    部门规章 21 / 规范性文件 7）。这类 code 挂在义务下面，读者只看到「部门规章」
    四个字，不知道引用的是哪一部 —— 所以 code 与 level 相同（或本就属级别词）时
    一律显示法规全名。判据用「code == level」而不是维护一张级别词表，避免漏项。
    """
    c = (x.get("code") or "").strip()
    if c and c != (x.get("level") or "").strip():
        return c
    return short_law(x.get("name") or c)


def find_refs(refs, items, n=2):
    """按 refs（标准号或法规名）在条目库中反查依据，返回可点击的条目。

    匹配优先级：标准号（归一化后包含）> 法规名（短名需全等、长名可包含，排除泛化词）。
    匹配不上一律降级为纯文字，绝不制造错误链接。
    """
    out, seen = [], set()
    for r in refs or []:
        if not r:
            continue
        r = r.strip()
        nr = norm_code(r)
        # 1) 标准号匹配。条目 code 可能是「法律」「部门规章」这类泛化短值，
        #    故要求双方都有实质长度，且归一化后比较。
        hit = next((x for x in items
                    if x.get("url") and len(x.get("code") or "") >= 6 and len(nr) >= 5
                    and nr in norm_code(x.get("code"))
                    and x["url"] not in seen), None)
        # 2) 回退到法规名匹配（排除泛化词，短名要求全等）
        if not hit and r not in AMBIGUOUS_REFS:
            hit = next((x for x in items
                        if x.get("url") and name_match(r, x.get("name"))
                        and x["url"] not in seen), None)
        if hit:
            out.append(hit)
            seen.add(hit["url"])
        if len(out) >= n:
            break
    return out


# --------------------------------------------------- 条款原文 / 标杆做法渲染
def render_articles(arts):
    """义务对应的「法律/标准名称 + 条款号 + 条款原文」。原文取自本机语料库，逐字不改写。"""
    arts = [a for a in (arts or []) if a.get("quote")]
    if not arts:
        return ""
    lis = []
    for a in arts:
        # 出处名统一去掉「中华人民共和国」前缀：义务数据里两种写法混用，
        # 不改会在「一句话问」的法条汇总里出现《食品安全法》与《中华人民共和国食品安全法》
        # 两条指向同一条文的重复 chip。全称放 title。
        src = a.get("src") or ""
        lis.append(
            f'<div class="art-item">'
            f'<div class="art-hd"><span class="art-src" title="{esc(src)}">'
            f'{esc(short_law(src))}</span>'
            f'<span class="art-no">{esc(a.get("art") or "")}</span></div>'
            f'<blockquote class="art-quote">{esc(a.get("quote") or "")}</blockquote></div>')
    return ('<details class="art-box"><summary>条款原文'
            f'<i>{len(arts)} 条</i></summary>'
            f'<div class="art-body">{"".join(lis)}</div></details>')


_PRACTICES = None
_MOCKUPS = None


def _load_practices():
    global _PRACTICES, _MOCKUPS
    if _PRACTICES is None:
        p = os.path.join(HERE, "sources", "standards", "practices.json")
        _PRACTICES = json.load(open(p, encoding="utf-8")).get("practices", {}) \
            if os.path.exists(p) else {}
    if _MOCKUPS is None:
        try:
            import duty_mockups
            _MOCKUPS = duty_mockups
        except Exception:
            _MOCKUPS = False
    return _PRACTICES, _MOCKUPS


def render_practice(pkey):
    """场景级「标杆做法 / 参考设计 / 参考文案 / 自查点」。"""
    pr, mk = _load_practices()
    d = pr.get(pkey)
    if not d:
        return ""
    out = ['<div class="prac"><div class="prac-hd">标杆做法 · 参考设计与文案</div>']
    if d.get("peer"):
        seg = "".join(f"<p>{esc(x)}</p>" for x in d["peer"].split("\n") if x.strip())
        out.append(f'<div class="prac-sec"><span class="prac-tag">标杆做法</span>'
                   f'<div class="prac-txt">{seg}</div></div>')
    key = d.get("design")
    if key and mk:
        got = mk.render(key)
        if got:
            title, svg = got
            out.append(f'<div class="prac-sec"><span class="prac-tag">参考设计</span>'
                       f'<figure class="prac-fig">{svg}'
                       f'<figcaption>{esc(title)}　·　示意图，仅用于说明合规要点，'
                       f'不还原任何具体产品界面</figcaption></figure></div>')
    if d.get("copy"):
        out.append(f'<div class="prac-sec"><span class="prac-tag">参考文案</span>'
                   f'<pre class="prac-copy">{esc(d["copy"])}</pre></div>')
    if d.get("check"):
        out.append('<div class="prac-sec"><span class="prac-tag">自查点</span><ul class="prac-ul">'
                   + "".join(f"<li>{esc(x)}</li>" for x in d["check"]) + "</ul></div>")
    out.append("</div>")
    return "".join(out)


RISK_ORDER = ("高", "中高", "中", "低")
RISK_LABEL = {"高": "高", "中高": "中高", "中": "中", "低": "低"}


def _risk_tally(duties):
    t = {}
    for d in duties:
        k = d.get("risk", "") or "未标注"
        t[k] = t.get(k, 0) + 1
    return t


def _riskbar(tally):
    """整改优先级分布条：红＝高、橙＝中、灰＝低（或无标注）。"""
    segs = []
    for k in ("高", "中高", "中", "低"):
        n = tally.get(k, 0)
        if n:
            segs.append(f'<i class="{RISK_CLS.get(k, "r-md")}" style="flex:{n} 1 0" '
                        f'title="{esc(k)} {n} 项"></i>')
    if not segs:
        return ""
    return f'<span class="dm-bar">{"".join(segs)}</span>'


def render_duty_matrix(cats):
    """合规义务矩阵总览：行＝主题大类，列＝业务场景，格＝该场景义务数与优先级分布。"""
    ncol = max((len(c.get("scenes", [])) for c in cats), default=0)
    n_cat = len(cats)
    n_scene = sum(len(c.get("scenes", [])) for c in cats)
    n_duty = sum(len(s.get("duties", [])) for c in cats for s in c.get("scenes", []))

    head = "".join(f'<th class="dm-col">场景 {i + 1}</th>' for i in range(ncol))
    rows = []
    for c in cats:
        scenes = c.get("scenes", [])
        c_duties = [d for s in scenes for d in s.get("duties", [])]
        tally = _risk_tally(c_duties)
        cells = []
        for si, s in enumerate(scenes):
            duties = s.get("duties", [])
            dots = "".join(f'<i class="{RISK_CLS.get(d.get("risk", ""), "r-lo")}"></i>'
                           for d in duties)
            names = "、".join(d.get("t", "") for d in duties)
            cells.append(
                f'<td class="dm-cell" data-cat="{esc(c["id"])}" data-si="{si}" tabindex="0" '
                f'role="button" title="{esc(s["name"])}：{esc(names)}">'
                f'<b>{esc(s["name"])}</b>'
                f'<span class="dm-meta"><em>{len(duties)} 项</em>'
                f'<span class="dm-dots">{dots}</span></span></td>')
        cells += ['<td class="dm-cell dm-empty"></td>'] * (ncol - len(scenes))
        rows.append(
            f'<tr><th class="dm-cat" data-cat="{esc(c["id"])}" scope="row" tabindex="0" '
            f'role="button"><b>{esc(c["name"])}</b>'
            f'<span class="dm-cat-m">{len(scenes)} 场景 · {len(c_duties)} 项</span>{_riskbar(tally)}</th>'
            f'{"".join(cells)}<td class="dm-sum">{len(c_duties)}</td></tr>')

    legend = ('<div class="dm-legend"><span class="dm-lg-t">整改优先级</span>'
              '<span class="dm-lg"><i class="r-hi"></i>高</span>'
              '<span class="dm-lg"><i class="r-md"></i>中</span>'
              '<span class="dm-lg"><i class="r-lo"></i>低 / 未标注</span>'
              '<span class="dm-hint">一格＝一个业务场景 · 点格子看该场景逐条义务</span></div>')

    return (f'<div class="dm-top">{legend}'
            f'<span class="dm-hint-m">← 左右滑动查看全部场景 →</span>'
            f'<div class="dm-scale">{n_cat} 个大类 × {n_scene} 个场景 × {n_duty} 项义务</div></div>'
            f'<div class="dm-scroll"><table class="dm"><thead><tr>'
            f'<th class="dm-th-cat"><b>主题大类</b><span>＼ 业务场景</span></th>{head}'
            f'<th class="dm-th-sum">合计</th></tr></thead><tbody>{"".join(rows)}</tbody>'
            f'<tfoot><tr><td class="dm-foot-l" colspan="2">共 {n_cat} 个主题大类 · '
            f'{n_scene} 个业务场景</td>'
            f'<td class="dm-foot-t" colspan="{max(ncol - 1, 0)}"></td>'
            f'<td class="dm-sum">{n_duty}</td></tr></tfoot></table></div>')


_CP = None


def compete_map():
    """{key: {'short','title','issue','anchor'}} —— 来自 compete_law.json。"""
    global _CP
    if _CP is None:
        try:
            its = json.load(open(COMPETE, encoding="utf-8"))["items"]
        except Exception:
            its = []
        _CP = {}
        for x in its:
            _CP[x["key"]] = {
                "title": x.get("title", ""),
                "short": (x.get("title", "").split("：")[0] or x["key"]),
                "issue": x.get("issue", ""),
                "anchor": (x.get("anchors") or [""])[0],
            }
    return _CP


def compete_html(duty):
    """义务卡片上的「法条竞合与抗辩」入口，指向高频法条页对应法条。"""
    cm = compete_map()
    ks = [k for k in (duty.get("compete") or []) if k in cm]
    if not ks:
        return ""
    chips = "".join(
        f'<a href="citations.html#{esc(cm[k]["anchor"])}" '
        f'title="{esc(cm[k]["title"])}——{esc(cm[k]["issue"][:120])}">{esc(cm[k]["short"])}</a>'
        for k in ks)
    return ('<div class="lb-comp"><span class="lb-comp-l">法条竞合与抗辩</span>'
            + chips + '</div>')


def render_duty_tree(cats, items):
    """合规义务清单 · 逐条明细：主题大类 → 场景 → 具体义务 三级。"""
    # 关联义务索引：rel 键 cat|scene|t → 页内锚点
    rel_anchor = {}
    for c in cats:
        for si, s in enumerate(c.get("scenes", [])):
            for di, d in enumerate(s.get("duties", [])):
                rel_anchor[f'{c["id"]}|{s["name"]}|{d["t"]}'] = f'd-{c["id"]}-{si}-{di}'

    def rel_html(duty):
        keys = [k for k in (duty.get("rel") or []) if k in rel_anchor]
        if not keys:
            return ""
        chips = "".join(
            f'<a href="#{rel_anchor[k]}">{esc(k.split("|", 1)[1] if "|" in k else k)}</a>'
            for k in keys)
        return (f'<div class="lb-rel"><span class="lb-rel-l">关联义务</span>{chips}</div>')

    chips = ['<button class="rd-fchip on" data-dcat="ALL">全部</button>']
    for c in cats:
        n_s = len(c.get("scenes", []))
        n_d = sum(len(s.get("duties", [])) for s in c.get("scenes", []))
        chips.append(f'<button class="rd-fchip" data-dcat="{esc(c["id"])}">'
                     f'{esc(c["name"])}<em>{n_s}·{n_d}</em></button>')
    chips_html = ('<div class="rd-filters duty-filters"><span class="rd-flabel">主题大类</span>'
                  + "".join(chips) + "</div>")

    blocks = []
    for ci, c in enumerate(cats):
        scenes_html = []
        for si, s in enumerate(c.get("scenes", [])):
            rows = []
            for di, d in enumerate(s.get("duties", [])):
                risk = d.get("risk", "")
                rk = (f'<span class="rk {RISK_CLS.get(risk, "r-md")}">{esc(risk)}</span>'
                      if risk else "")
                rels = find_refs(d.get("refs"), items)
                ref_html = ""
                if rels:
                    # 依据标签优先用文号（GB/T 35273、T/TAF 078.7），但库里有一批条目的 code
                    # 直接就是效力级别本身（「部门规章」「行政法规」「法律」「地方法规」…），
                    # 拿它当标签等于没写，读者看不出引用的是哪部法 → 退回用法规名。
                    ref_html = '<div class="lb-refs">' + "".join(
                        f'<a href="{esc(x["url"])}" target="_blank" rel="noopener" '
                        f'title="{esc(x["name"])}">{esc(ref_label(x))}</a>'
                        for x in rels) + "</div>"
                else:
                    ref_html = ('<div class="lb-refs lb-refs-plain">'
                                + "".join(f'<span>{esc(r)}</span>' for r in (d.get("refs") or [])[:2])
                                + "</div>")
                did = f'd-{c["id"]}-{si}-{di}'
                rows.append(
                    f'<div class="lb-d2" id="{did}" data-risk="{esc(risk)}">'
                    f'<div class="lb-d2-t">{rk}<b>{esc(d["t"])}</b></div>'
                    f'<div class="lb-d2-d">{esc(d["d"])}</div>{ref_html}'
                    f'{rel_html(d)}'
                    f'{compete_html(d)}'
                    f'{render_articles(d.get("articles"))}</div>')

            pkey = f'{c["id"]}|{s["name"]}'
            scenes_html.append(
                f'<details class="lb-s" id="s-{c["id"]}-{si}" {"open" if ci == 0 and si < 2 else ""}>'
                f'<summary><b>{esc(s["name"])}</b><i>{len(s.get("duties", []))} 项</i></summary>'
                f'<div class="lb-s-body">{render_practice(pkey)}'
                f'{"".join(rows)}</div></details>')

        n_s = len(c.get("scenes", []))
        n_d = sum(len(x.get("duties", [])) for x in c.get("scenes", []))
        blocks.append(
            f'<section class="lb-cat" data-cat="{esc(c["id"])}">'
            f'<div class="lb-cat-h"><h3>{esc(c["name"])}</h3>'
            f'<span class="lb-cat-n">{n_s} 个场景 · {n_d} 项义务</span>'
            f'<p>{esc(c.get("desc", ""))}</p></div>'
            f'<div class="lb-cat-body">{"".join(scenes_html)}</div></section>')

    return chips_html + '<div class="lb-tree">' + "".join(blocks) + "</div>"


# --------------------------------------------------- P3-8「按话题找依据」（智能图表）
# 对标威科先行「智能图表」：引导步骤选话题 → 直接给出该话题的法律依据清单。
# 与「合规义务清单」共用同一套数据（17 大类 / 93 场景 / 285 义务），差别只在入口：
#   合规义务清单 —— 按目录翻（你得先知道自己属于哪一类）
#   按话题找依据 —— 按业务问题问（先说你正在做什么事）
#
# 关键取舍：**依据清单不另存一份数据**。清单里的每一项义务卡（含条款原文、官方原文深链、
# 关联义务、法条竞合）都从已经渲染好的逐条明细里按话题筛出来复用，浏览器端 clone 即可。
# 好处是单一事实来源 —— 明细改了清单自动跟着改，不会出现两份口径。
#
# ask/eg 是给业务读者看的「问句 + 常见话题示例」，用业务语言而不是分类学语言；
# 场景与义务本身一律取 duties.json，不在本文件里手写，避免与清单走样。
WZ_GUIDE = {
    "app": ("App / 小程序要上新功能、新权限",
            ["摇一摇开屏", "位置权限", "通讯录匹配", "一键登录", "引入第三方 SDK",
             "账号注销"]),
    "pi": ("我们要收集、使用、对外提供用户的个人信息",
           ["单独同意", "隐私政策更新", "人脸识别", "个人信息导出与删除", "委托处理",
            "未成年人"]),
    "data": ("数据的存储、共享与出境",
             ["数据分类分级", "数据出境", "日志留存", "员工数据", "委托处理",
              "数据安全风险评估"]),
    "net": ("网络与系统的安全防护",
            ["等级保护备案", "漏洞管理", "安全事件应急", "供应商安全", "数据泄露报告"]),
    "algo": ("算法推荐、排序与调度",
             ["个性化推荐", "算法备案", "派单与调度", "自动化决策", "算法安全评估",
              "备案变更与注销"]),
    "ai": ("用或对外提供 AI、大模型能力",
           ["生成式 AI 备案", "AI 生成内容标识", "训练数据与语料", "AI 客服",
            "智能体", "AI 与未成年人"]),
    "platform": ("平台的规则、商家准入与交易治理",
                 ["平台规则公示", "商家与供应商准入", "二选一", "保证金与平台收费",
                  "违规处置", "平台责任边界"]),
    "ad": ("广告投放与营销宣传",
           ["开屏广告", "弹窗广告", "摇一摇广告", "种草与软文", "直播带货",
            "绝对化用语"]),
    "price": ("定价、促销与消费者权益",
              ["划线价", "满减凑单", "自动续费", "价格欺诈", "七日无理由退货",
               "格式条款"]),
    "food": ("食品经营与商品质量",
             ["标签标识", "保质期与临期", "抽检不合格处置", "进口食品", "食品主体责任",
              "食用农产品"]),
    "instant": ("线上下单、前置仓拣货与网络交易",
                ["网络交易主体登记", "亮照亮证", "商品信息公示", "交易规则", "平台化经营"]),
    "delivery": ("即时配送与骑手管理",
                 ["餐箱消毒", "食安封签", "骑手用工与权益", "派单算法", "配送安全培训"]),
    "catering": ("网络餐饮与线下门店餐饮",
                 ["入网资质审核", "明厨亮灶", "从业人员健康", "餐饮具与包装", "平台责任"]),
    "store": ("前置仓、仓储与冷链",
              ["冷链温控", "贮存条件", "食用农产品查验", "不合格品处置", "临期处置"]),
    "measure": ("称重、计量与净含量",
                ["计量器具检定", "定量包装", "净含量标注", "计价与标价"]),
    "retail": ("会员、预付与售后",
               ["七日无理由退货", "预付式消费", "会员权益", "自动续费", "赠品与有奖销售"]),
    "green": ("包装、塑料制品与反食品浪费",
              ["一次性塑料制品", "过度包装", "反食品浪费", "快递与配送包装减量"]),
}


def render_topic_ask(cats):
    """「按话题找依据」引导视图：业务问句 → 场景多选 → 法律依据清单。"""
    wz = []
    for c in cats:
        ask, eg = WZ_GUIDE.get(c.get("id"), ("", []))
        scenes = []
        for s in c.get("scenes", []):
            # 每项义务 = [标题, 风险, 说明]。说明只用于「一句话问」的相关度打分，
            # **不渲染**（正文仍从逐条明细 clone），所以只影响检索质量，不影响页面口径。
            scenes.append([s.get("name", ""),
                           [[d.get("t", ""), d.get("risk", ""), (d.get("d") or "")[:160]]
                            for d in s.get("duties", [])]])
        wz.append({"id": c.get("id", ""), "n": c.get("name", ""), "d": c.get("desc", ""),
                   "a": ask, "e": eg, "s": scenes})
    data = json.dumps(wz, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    n_cat = len(cats)
    n_scene = sum(len(c.get("scenes", [])) for c in cats)
    n_duty = sum(len(s.get("duties", [])) for c in cats for s in c.get("scenes", []))

    return f"""<div class="wz">
  <div class="wz-steps" id="wzSteps">
    <button type="button" class="wz-st on" data-s="1"><i>1</i><b>你在做什么</b></button>
    <button type="button" class="wz-st" data-s="2"><i>2</i><b>落到哪个场景</b></button>
    <button type="button" class="wz-st" data-s="3"><i>3</i><b>法律依据清单</b></button>
  </div>

  <div class="wz-free">
    <div class="wz-fr-h"><b>也可以直接一句话问</b>
      <span>系统在 {n_cat} 大类 / {n_scene} 个场景 / {n_duty} 项义务里定位相关场景</span></div>
    <div class="wz-fr-row">
      <input id="wzQ" type="search" autocomplete="off"
        placeholder="例如：骑手派单排名怎么做才合规　/　App 要加人脸登录　/　促销要不要标划线价">
      <button type="button" class="wz-go" id="wzGo">找依据</button>
    </div>
    <div class="wz-fr-tip" id="wzTip">用业务语言描述即可，不用先想它归哪一类。</div>
  </div>

  <div class="wz-pane" id="wzP1"></div>
  <div class="wz-pane" id="wzP2" hidden></div>
  <div class="wz-pane" id="wzOut" hidden></div>
</div>
<script>window.LD_WZ={data};</script>"""


def duty_block(d, items, idx):
    rel = [x for x in items if d["name"] in x.get("duty", [])]
    rel.sort(key=lambda x: (0 if x.get("kind") != "标准" else 1, x.get("impl") or x.get("pub") or ""),
             reverse=False)
    if not rel:
        return ""
    rows = []
    for x in rel:
        st = x.get("status", "现行有效")
        rows.append(
            f'<div class="lb-rel"><span class="rd-badge {STATUS_CLS.get(st,"b-ghost")}">{esc(st)}</span>'
            f'<a href="{esc(x["url"])}" target="_blank" rel="noopener">{esc(x["name"])}</a>'
            f'<span class="lb-code">{esc(x.get("code",""))}</span></div>')
    return f"""<details class="lb-duty" data-topic="{esc(d['topic'])}" {'open' if idx < 3 else ''}>
  <summary><span class="rd-badge b-ghost">{esc(d['topic'])}</span>
    <b>{esc(d['name'])}</b><i>{len(rel)} 项依据</i></summary>
  <p class="lb-desc">{esc(d['desc'])}</p>
  <div class="lb-rels">{''.join(rows)}</div>
</details>"""


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    # 下架条目（非规范性材料）只在 library.json 上打 hidden 标记，渲染层过滤，便于随时恢复
    items = [x for x in data["items"] if not x.get("hidden")]
    today = datetime.date.today().isoformat()

    # 合规义务清单（三级结构）；回退到条目库内的旧式 duties
    if os.path.exists(DUTY_SRC):
        duties = json.load(open(DUTY_SRC, encoding="utf-8"))
    else:
        duties = {"categories": []}
    cats = duties.get("categories", [])
    n_duty = sum(len(d.get("duties", [])) for c in cats for d in c.get("scenes", []))
    # 规模口径（大类 / 场景 / 义务）——独立页 kb/duties.html 的 h1 引语要用，
    # 且**禁止写死数字**：先前首页把 17/93/285 写进静态 HTML，数据一变就失真。
    n_cat = len(cats)
    n_scene = sum(len(c.get("scenes") or []) for c in cats)

    # 时效分区
    soon = [x for x in items if x.get("status") == "即将实施" and (x.get("impl") or "") >= today]
    soon.sort(key=lambda x: x.get("impl") or "9999")
    dead = [x for x in items if x.get("status") == "已废止"]

    n_std = sum(1 for x in items if x.get("kind") == "标准")
    n_law = len(items) - n_std
    # 全量口径（2026-09-17：法规库不再有「仅合规相关 / 显示全部」开关，
    # 页面本来就看全部，统计条随之改为全量，与进库看到的条数一致）
    n_all, n_std_all, n_law_all = len(items), n_std, n_law
    n_rel_all = sum(1 for x in items if x.get("rel"))
    n_std_rel = sum(1 for x in items if x.get("rel") and x.get("kind") == "标准")
    n_law_rel = n_rel_all - n_std_rel
    n_irrelevant = len(items) - n_rel_all
    n_local = sum(1 for x in items if x.get("local"))
    n_online = law_online_count()
    n_std_online = std_online_count()
    n_hot, _n_case = hot_counts()
    topics = data["meta"]["topics"]

    # 草案跟踪
    drafts = []
    if os.path.exists(DRAFTS):
        try:
            drafts = json.load(open(DRAFTS, encoding="utf-8"))["items"]
        except Exception:
            drafts = []

    # ---------------- 统计条
    # 2026-09-17：删掉法规库的「收录范围」开关后，这两个计数已无对应概念
    # （「合规相关条目 / 已筛除技术类标准」说的是那个开关的两侧），
    # 改为直接报全量口径，与进库看到的条数一致。
    stats = [(k, v) for k, v in [
        ("收录条目", n_all),
        ("法律法规", n_law_all),
        ("标准", n_std_all),
        ("本机原文", n_local),
        ("站内法规原文", n_online),
        ("站内标准正文", n_std_online),
        ("高频引用法条", n_hot),
        ("在途草案", f"{len(drafts)} 项"),
        ("合规义务", f"{n_duty} 项"),
    ]]
    stat_html = ('<div class="rd-stats">' + "".join(
        f'<div class="rd-stat"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for k, v in stats
    ) + "</div>")

    # ---------------- 时效看板
    def soon_row(x):
        try:
            d = (datetime.date.fromisoformat(x["impl"]) - datetime.date.today()).days
        except Exception:
            d = None
        cnt = f'<i>{d} 天后</i>' if d is not None and d >= 0 else ""
        return (f'<div class="lb-soon"><span class="lb-when">{esc(x.get("impl",""))}{cnt}</span>'
                f'<a href="{esc(x["url"])}" target="_blank" rel="noopener">{esc(x["name"])}</a>'
                f'<span class="lb-code">{esc(x.get("code",""))}</span></div>')

    def dead_row(x):
        return (f'<div class="lb-soon"><span class="lb-when">{esc(x.get("impl","") or x.get("pub",""))}</span>'
                f'<a href="{esc(x["url"])}" target="_blank" rel="noopener">{esc(x["name"])}</a>'
                f'<span class="lb-code">{esc(x.get("code",""))}</span>'
                f'<span class="lb-dead">已废止</span></div>')

    board = ""
    if soon or dead:
        cols = []
        if soon:
            cols.append(
                '<div class="lb-board c-soon"><h4><span class="dot"></span>即将实施'
                f'<i>{len(soon)} 项</i></h4><div class="lb-soonlist">'
                + "".join(soon_row(x) for x in soon[:8]) + "</div>"
                + (f'<div class="lb-more">还有 {len(soon)-8} 项，见下方资料库</div>'
                   if len(soon) > 8 else "") + "</div>")
        if dead:
            cols.append(
                '<div class="lb-board c-dead"><h4><span class="dot"></span>已废止 / 被替代'
                f'<i>{len(dead)} 项</i></h4><div class="lb-soonlist">'
                + "".join(dead_row(x) for x in dead) + "</div>"
                '<div class="lb-tip">引用前请核对现行版本，避免依据已废止文件</div></div>')
        board = '<div class="lb-boards">' + "".join(cols) + "</div>"

    # ---------------- 筛选
    topic_opts = [("ALL", "全部")] + [(t, t) for t in topics]
    level_opts = [("ALL", "全部层级")] + [(l, l) for l in data["meta"]["levels"]]
    stat_opts = [("ALL", "全部状态")] + [(s, s) for s in data["meta"]["statuses"]]
    # 2026-09-17：资料库改为左栏 facet + 右栏列表后，横铺 chip 筛选条与顶部搜索框
    # 都不再需要（搜索框进了右栏工具栏，筛选项由 JS 按 facet 定义动态渲染 + 动态计数）。
    _ = (topic_opts, level_opts, stat_opts)

    # 2026-09-15：法规库 + 标准库补齐后条目从 1419 涨到近 2 万，内联渲染会把
    # kb/standards.html 顶到 19MB（移动端无法加载）。改为全量数据写入独立文件
    # kb/library-data.js，浏览器端渲染 —— 条目一条不少，HTML 反而从 19MB 降到几十 KB。
    am_map = load_amendments()
    lb_rows = []
    n_amend = 0
    for x in items:
        # 修订沿革（P2-4 轻量版）：只对站内有官方原文的条目可得，值形如
        # 「经 4 次修正 · 最近 2020-10-17」。判据来自官方前言，不是推测。
        tid_x = text_id(x)
        a_txt = amend_text(am_map.get(tid_x)) if tid_x else ""
        if a_txt:
            n_amend += 1
        lb_rows.append([
            x.get("level", ""), x.get("topic", ""), x.get("status", ""),
            x.get("code", ""), x.get("name", ""), x.get("url", ""),
            x.get("issuer", ""), x.get("pub", ""), x.get("impl", ""),
            x.get("point", ""), x.get("note", ""), x.get("toc") or [],
            x.get("duty") or [], read_affordance(x),
            x.get("rel", 1), x.get("kind", ""),
            _region_of(x), len(x.get("toc") or []),
            a_txt,
        ])
    print(f"  修订沿革：{n_amend} 条目标注「经 N 次修正」"
          f"（数据源 {len(am_map)} 部法规的官方前言）")
    _data_js = ("window.LB_ITEMS=" + json.dumps(lb_rows, ensure_ascii=False,
                                               separators=(",", ":")) + ";\n"
                + "window.LB_CLS=" + json.dumps({"status": STATUS_CLS, "level": LEVEL_CLS},
                                                ensure_ascii=False) + ";\n"
                # LB_META 此前**只被读取、从未写入** → 左栏「效力级别」实际退化成
                # 按计数降序，与「按位阶从高到低」的意图不符（2026-09-17 补）。
                # 现在把它显式下发：levels 的数组顺序即**法律位阶顺序**，
                # 左栏分组与列表默认排序（位阶优先）都用它。
                + "window.LB_META=" + json.dumps(
                    {"level": data["meta"]["levels"]}, ensure_ascii=False) + ";\n")
    _data_js = _data_js.replace("<", "\\u003c")
    _dp = os.path.join(HERE, "kb", "library-data.js")
    os.makedirs(os.path.dirname(_dp), exist_ok=True)
    open(_dp, "w", encoding="utf-8").write(_data_js)
    print(f"  kb/library-data.js   {len(_data_js) / 1024:.0f} KB  ({len(lb_rows)} 条目，"
          f"浏览器端渲染)")

    cards = ""

    # ---------------- 义务视图（矩阵总览 ⇄ 逐条明细）
    duty_matrix = render_duty_matrix(cats)
    duty_detail = render_duty_tree(cats, items)
    duty_html = (
        '<div class="lb-search duty-search">'
        '<input id="dutyQ" type="search" '
        'placeholder="搜索义务关键词，如 摇一摇、单独同意、划线价、温湿度…" autocomplete="off">'
        '<span id="dutyCount" class="lb-count"></span></div>'
        '<div class="dm-switch">'
        '<button class="dm-sw on" data-view="matrix">矩阵总览</button>'
        '<button class="dm-sw" data-view="detail">逐条明细</button>'
        '<span class="dm-sw-tip">搜索或点矩阵中的格子会自动切到逐条明细</span>'
        '<button type="button" class="dm-goto" data-goto-tab="ask">'
        '不知道从哪看起？按话题找依据 →</button></div>'
        f'<div class="dm-view" id="dmMatrix">{duty_matrix}</div>'
        f'<div class="dm-view" id="dmDetail" hidden>'
        f'<div class="lb-duties">{duty_detail}</div></div>')

    # ---------------- 按话题找依据（P3-8，对标威科先行「智能图表」）
    ask_html = render_topic_ask(cats)

    # ---------------- 草案跟踪视图
    draft_html = "\n".join(draft_card(d) for d in drafts)
    if not draft_html:
        draft_html = '<p class="rd-note">暂无在途草案记录。</p>'

    # ---------------- 资料库（威科先行式：左栏多维筛选 + 右栏高密度结果列表）
    # 2026-09-17（用户要求「多参考威科先行这类的行业标杆」）：
    # 旧版是「一排横铺 chip 筛选 + 大卡片列表」，一屏只看得到 4 条，且筛选项不带计数、
    # 没有分页，2 万条数据实际上翻不动。现在改为标杆站的范式：
    #   左栏 = 过滤条件（资源类型 / 效力级别 / 时效性 / 专题 / 发文机关 / 地域 / 发布日期），
    #          每项带**当前结果集下的动态计数**；
    #   右栏 = 工具栏（检索 + 范围 / 匹配粒度 + 排序 + 每页条数）+ 发布量走势 + 已选条件
    #          + 紧凑列表（一条一行，含状态徽章、层级、专题、机关与日期、要点摘要、修订沿革）
    #          + 分页器。
    trend_html = pub_trend(items)
    lib_pane = "\n".join([
        '<section class="lb-pane" id="pane-lib">',
        '<div class="lv">',
        '<aside class="lv-side"><div class="lv-side-h"><b>过滤条件</b>'
        '<button type="button" class="lv-reset" id="lvReset">重置</button></div>'
        '<div class="lv-facets" id="lvSide"></div></aside>',
        '<div class="lv-main">',
        # 工具栏（2026-09-17 增补，对标北大法宝的三种检索方式）：
        #   · 标题 / 全文 —— 检索范围。全文含条款要点、说明与章节目录
        #     （站内 2 万条目的正文没有随页下发，检索的是结构化字段而非 PDF 全文，故文案写明口径）
        #   · 精确 / 模糊 —— 精确=整串连续命中；模糊=按字序跳字命中（对标「模糊检索」）
        #   · 结果中检索 —— 把当前关键词冻结成一个条件，后续关键词在它的结果里继续收敛（AND）
        '<div class="lv-bar">'
        '<div class="lv-q"><input id="lbQ" type="search" autocomplete="off" '
        'placeholder="检索名称 / 文号 / 发布机关 / 章节目录，如 个人信息、GB/T 35273、江苏省">'
        '<button type="button" class="lv-inq" id="lvInq" '
        'title="把当前关键词冻结为条件，后续关键词在它的结果里继续筛（多条以 AND 组合）">'
        '结果中检索</button></div>'
        '<div class="lv-seg" id="lvField" role="group" aria-label="检索范围">'
        '<button type="button" class="on" data-f="t">标题</button>'
        '<button type="button" data-f="f">全文</button></div>'
        '<div class="lv-seg" id="lvMode" role="group" aria-label="匹配方式">'
        '<button type="button" class="on" data-m="exact">精确</button>'
        '<button type="button" data-m="fuzzy">模糊</button></div>'
        '<select id="lvSort" class="lv-sel" aria-label="排序">'
        '<option value="rank" selected>位阶：高 → 低（同阶按生效时间）</option>'
        '<option value="pub_desc">发布日期：新 → 旧</option>'
        '<option value="pub_asc">发布日期：旧 → 新</option>'
        '<option value="impl_desc">实施日期：新 → 旧</option>'
        '<option value="name">按名称排序</option>'
        '</select>'
        '<select id="lvSize" class="lv-sel" aria-label="每页条数">'
        '<option value="20">每页 20 条</option>'
        '<option value="50">每页 50 条</option>'
        '<option value="100">每页 100 条</option>'
        '</select>'
        '</div>',
        trend_html,
        '<div class="lv-bar2"><div class="lv-chips" id="lvChips"></div>'
        '<div class="lv-cnt" id="lvCount"></div></div>',
        '<div class="lv-list" id="lvList"></div>',
        '<div class="lv-pager" id="lvPager"></div>',
        '</div>',
        '</div>',
        "</section>",
    ])

    body = "\n".join([
        '<div class="lb-tabs">'
        '<button class="rd-fchip on" data-tab="lib">资料库</button>'
        '<button class="rd-fchip" data-tab="draft">草案跟踪<i class="lb-dot"></i></button>'
        "</div>",
        lib_pane,
        '<section class="lb-pane" id="pane-draft" hidden>',
        '<p class="rd-note">跟踪<b>尚未生效</b>的立法与标准制定动态：国家标准征求意见、部门规章草案、'
        '以及长期悬置未发布的规范性文件。数据来自全国网络安全标准化技术委员会与中央网信办官网，'
        '截止日期与剩余天数按页面打开当天计算。<b>草案不产生合规义务</b>，但往往预示监管方向。</p>',
        f'<div class="rd-list" id="draftList">{draft_html}</div>',
        "</section>",
        '<p class="rd-note">标准数据取自<b>国家标准全文公开系统</b>（发布/实施日期与现行状态以官方为准）；'
        '法律法规与规范性文件均附发布机构官网原文深链。'
        '本页用于合规检索与自查参考，<b>不构成法律意见</b>；引用前请点开原文核对现行有效版本。</p>',
        LIB_RENDER,
        TABS_JS,
    ])

    out = page(
        "法规库",
        "个人信息保护、数据安全、网络安全、算法与 AI、移动应用、平台与电商、食品安全、"
        "计量与冷链等合规领域的法律法规、国家标准与指引指南汇总，按资源类型、效力级别、时效性、"
        "专题、发文机关与地域多维筛选，逐条标注发布与实施日期并附官方原文深链。",
        '<a href="index.html">合规知识库</a> / 法规库',
        "法规库",
        "共 " + str(len(items)) + " 条目，默认按效力位阶从高到低排列，"
        "同位阶内按生效时间从新到旧；左侧多维过滤，右侧逐条给出官方原文入口。",
        body,
    )

    dst = os.path.join(HERE, "kb", "standards.html")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8").write(out)
    print(f"  kb/standards.html  {len(out)} B  ✓  "
          f"({len(items)} 条目)")

    # ---------------- 合规义务清单（**独立页面** kb/duties.html）
    # 2026-09-18（用户报障：「点击合规义务清单，跳进去还是原来带法条原文库的页面」）：
    # 义务清单此前只是法规库页面的第三个页签 —— 子导航与知识库总览都把它当作与
    # 「法规库」并列的模块，点进来却停在「资料库」（也就是法条原文列表）视图上，
    # 入口名与落地页身份不符。拆成独立页面后，页面身份 / h1 / 默认视图三者一致。
    #
    # ⚠️「按话题找依据」必须跟着一起搬：它从 #pane-duty 里已经渲染好的义务卡 clone 正文
    # （见 DUTY_JS 里 cloneDuty 的注释），两个面板分居两页会断掉这份单一事实来源。
    duty_body = "\n".join([
        '<div class="lb-tabs">'
        '<button class="rd-fchip on" data-tab="duty">义务清单</button>'
        '<button class="rd-fchip" data-tab="ask">按话题找依据</button>'
        "</div>",
        '<section class="lb-pane" id="pane-duty">',
        '<p class="rd-note"><b>矩阵总览</b>按「主题大类 × 业务场景」铺开，一格即一个场景，'
        '格内数字为该场景的义务条数、色点为其整改优先级分布，一屏看全覆盖面与风险重心；'
        '点任一格子进入<b>逐条明细</b>，每项义务下列出可直接引用的法律法规与标准条款原文、'
        '行业标杆做法与可套用文案。</p>',
        duty_html,
        "</section>",
        '<section class="lb-pane" id="pane-ask" hidden>',
        '<p class="rd-note"><b>按话题找依据</b>与「义务清单」是同一套数据的两个入口：'
        '清单是按目录翻，这一页是按问题问。你说清楚<b>正在做什么事</b>，它就在义务清单里定位到相关场景，'
        '直接输出该话题的<b>法律依据清单</b>——每项义务对应哪些法规标准、哪些条款、原文怎么写，'
        '并可一键复制成 Markdown 或打印成 PDF。</p>',
        ask_html,
        '<p class="rd-note">清单中的条款原文逐字取自我站<b>官方原文库</b>，'
        '条文出处与官方发布页均为深链。</p>',
        "</section>",
        TABS_JS,
        DUTY_JS,
    ])

    duty_out = page(
        "合规义务清单",
        "按 17 个主题大类 × 93 个业务场景铺开的合规义务清单：每项义务给出可直接引用的法规与"
        "标准条款原文、整改优先级、行业标杆做法与可套用文案，并可按业务话题反查法律依据。",
        '<a href="index.html">合规知识库</a> / 合规义务清单',
        "合规义务清单",
        f"共 {n_cat} 个主题大类 · {n_scene} 个业务场景 · {n_duty} 项具体义务，"
        "每项附条款原文、整改优先级与可套用文案。",
        duty_body,
    )

    dst2 = os.path.join(HERE, "kb", "duties.html")
    open(dst2, "w", encoding="utf-8").write(duty_out)
    print(f"  kb/duties.html     {len(duty_out)} B  ✓  "
          f"({n_cat} 大类 / {n_scene} 场景 / {n_duty} 义务)")

    build_kb_index(items, duties, drafts, soon, stat_html=stat_html, board=board)

    # 恢复统一页头页脚与分享元数据
    import importlib.util
    for name in ("unify_chrome", "inject_meta"):
        p = os.path.join(HERE, name + ".py")
        if not os.path.exists(p):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            m.main()
        except Exception as e:
            print(f"  {name} 跳过：{e}")


LIB_RENDER = """
<script src="library-data.js"></script>
<script>
(function(){
  var host=document.getElementById('lvList');
  if(!host||!window.LB_ITEMS) return;
  var IT=window.LB_ITEMS;
  var S=(window.LB_CLS||{}).status||{}, L=(window.LB_CLS||{}).level||{};
  var SIDE=document.getElementById('lvSide'),
      CHIPS=document.getElementById('lvChips'),
      PAGER=document.getElementById('lvPager'),
      Q=document.getElementById('lbQ'),
      INQ=document.getElementById('lvInq'),
      FSEG=document.getElementById('lvField'),
      MSEG=document.getElementById('lvMode'),
      SORTD=document.getElementById('lvSort'),
      SIZED=document.getElementById('lvSize'),
      CNT=document.getElementById('lvCount'),
      RESET=document.getElementById('lvReset');
  if(!SIDE) return;

  // 字段下标 —— 必须与 build_standards.py 里 lb_rows 的写入顺序严格一致
  var F={level:0,topic:1,status:2,code:3,name:4,url:5,issuer:6,pub:7,impl:8,
         point:9,note:10,toc:11,duty:12,read:13,rel:14,kind:15,region:16,tocn:17,
         amend:18};

  function e(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
  function n2(v){return String(v).replace(/\\B(?=(\\d{3})+(?!\\d))/g,',');}

  var NOW=(function(){var d=new Date();d.setHours(0,0,0,0);return d.getTime();})();
  var DAY=86400000;
  function tms(s){var t=s?Date.parse(s):NaN; return isNaN(t)?null:t;}
  function band(s){var t=tms(s); if(t===null) return 'none';
    var d=(NOW-t)/DAY; if(d<=31) return 'm1'; if(d<=93) return 'm3';
    if(d<=366) return 'y1'; if(d<=1097) return 'y3'; return 'old';}

  // 预计算两条检索串（一次，之后筛选只做比较）：
  //   HT = 标题与文号（只搜名称 / 文号，对标法宝的「标题检索」）
  //   HF = 全文（名称 / 文号 / 机关 / 专题 / 章节目录 / 要点 / 说明）
  var N=IT.length, HT=new Array(N), HF=new Array(N), BND=new Array(N);
  for(var i=0;i<N;i++){
    var r=IT[i];
    HT[i]=(r[F.name]+' '+r[F.code]).toLowerCase();
    HF[i]=(r[F.name]+' '+r[F.code]+' '+r[F.issuer]+' '+r[F.topic]+' '
           +(r[F.point]||'')+' '+(r[F.note]||'')+' '
           +((r[F.toc]||[]).join(' '))).toLowerCase();
    BND[i]=band(r[F.pub]);
  }
  // 模糊匹配：查询串的字符按顺序出现即可（允许跳字），对标法宝的「模糊检索」
  function fuzzy(hay,q){
    var p=0, n=q.length;
    if(!n) return true;
    for(var i=0;i<hay.length&&p<n;i++) if(hay.charAt(i)===q.charAt(p)) p++;
    return p===n;
  }

  var PUB_LABEL={m1:'近 1 个月',m3:'近 3 个月',y1:'近 1 年',y3:'近 3 年',
                 old:'3 年以上',none:'未标注'};
  var FACETS=[
    {k:'kind',   t:'资源类型', multi:true, label:{'法规':'法规','标准':'标准','文件':'其他文件'}},
    {k:'level',  t:'效力级别', multi:true},
    {k:'status', t:'时效性',  multi:true},
    {k:'topic',  t:'专题',    multi:true},
    {k:'issuer', t:'发文机关', multi:true, top:10},
    {k:'region', t:'地域范围', multi:true, top:12},
    {k:'pub',    t:'发布日期', multi:false, fixed:['m1','m3','y1','y3','old','none']}
  ];
  var FMAP={}; FACETS.forEach(function(f){FMAP[f.k]=f;});
  function valAt(i,k){ return k==='pub' ? BND[i] : IT[i][F[k]]; }

  // 当前条件：qs=已冻结的关键词（结果中检索）；q=当前关键词；
  //           fld=检索范围（t 标题 / f 全文）；md=匹配方式（exact / fuzzy）；
  //           sort 默认 rank = 位阶（法律 → 行政法规 → …）优先，同位阶按生效时间 新 → 旧
  var st={q:'',qs:[],fld:'t',md:'exact',sort:'rank',page:1,size:20,
          sel:{kind:{},level:{},status:{},topic:{},issuer:{},region:{},pub:{}}};

  function keepSel(o){var n=0; for(var k in o) if(o[k]) n++; return n;}

  function oneQ(i,q){
    if(!q) return true;
    var hay=(st.fld==='f')?HF[i]:HT[i];
    return st.md==='fuzzy' ? fuzzy(hay,q) : hay.indexOf(q)>=0;
  }
  function qHit(i,skip){
    if(skip!=='q' && !oneQ(i,st.q)) return false;
    if(skip!=='qs') for(var j=0;j<st.qs.length;j++) if(!oneQ(i,st.qs[j])) return false;
    return true;
  }
  function pass(i,skip){
    if(!qHit(i,skip)) return false;
    for(var k in st.sel){
      if(k===skip) continue;
      var s=st.sel[k]; if(!keepSel(s)) continue;
      if(!s[valAt(i,k)]) return false;
    }
    return true;
  }

  // ---------------- 筛选（返回命中下标 + 各 facet 计数）
  var hits=[], cnt={};
  function refilter(keepPage){
    var j,k;
    for(k in FMAP) cnt[k]={};
    hits.length=0;
    for(var i=0;i<N;i++){
      if(!pass(i,null)) continue;
      hits.push(i);
      for(k in FMAP){ var v=valAt(i,k); cnt[k][v]=(cnt[k][v]||0)+1; }
    }
    sortHits();
    if(!keepPage) st.page=1;
    renderSide(); renderChips(); render();
  }

  // 「位阶」顺序来自 LB_META.level（法律 → 行政法规 → 部门规章 → …），
  // 未登记的层级排最后。
  function rk(x){ var v=RANK[x[F.level]]; return (v==null)?999:v; }
  function cmp(a,b){
    var x=IT[a],y=IT[b];
    if(st.sort==='name') return (x[F.name]||'').localeCompare(y[F.name]||'','zh');
    if(st.sort==='rank'){
      var ra=rk(x), rb=rk(y);
      if(ra!==rb) return ra-rb;                                   // ① 位阶高 → 低
      var xa=x[F.impl]||x[F.pub]||'', ya=y[F.impl]||y[F.pub]||'';
      if(xa!==ya) return (xa<ya?1:-1);                            // ② 生效时间 新 → 旧
      return (x[F.name]||'').localeCompare(y[F.name]||'','zh');   // ③ 名称兜底，保证稳定
    }
    var xa=x[F.pub]||'', ya=y[F.pub]||'';
    if(st.sort==='impl_desc'){ xa=x[F.impl]||''; ya=y[F.impl]||''; }
    if(!xa&&!ya) return (y[F.name]||'').localeCompare(x[F.name]||'','zh');
    if(!xa) return 1;
    if(!ya) return -1;
    if(xa===ya) return 0;
    return (st.sort==='pub_asc') ? (xa<ya?-1:1) : (xa<ya?1:-1);
  }
  function sortHits(){ hits.sort(cmp); }

  // ---------------- 左栏
  var META=window.LB_META||{};
  var RANK={}; (META.level||[]).forEach(function(l,i){ RANK[l]=i; });
  function buckets(k){
    var m=cnt[k]||{}, out=[], v;
    var f=FMAP[k];
    if(f.fixed){ for(var i=0;i<f.fixed.length;i++){ v=f.fixed[i];
        if(m[v]) out.push([v,PUB_LABEL[v]||v,m[v]]); } return out; }
    for(v in m) out.push([v, v, m[v]]);
    var ord=META[k];
    if(ord&&ord.length){
      // 维度顺序由数据层定义（法律→行政法规→…；全国→各省），未列出的按计数降序排末尾
      var pos={}; ord.forEach(function(x,ix){ if(!(x in pos)) pos[x]=ix; });
      out.sort(function(a,b){
        var pa=pos[a[0]], pb=pos[b[0]];
        if(pa==null&&pb==null) return b[2]-a[2]||a[0].localeCompare(b[0],'zh');
        if(pa==null) return 1;
        if(pb==null) return -1;
        return pa-pb;
      });
    }else{
      out.sort(function(a,b){ return b[2]-a[2]||a[0].localeCompare(b[0],'zh'); });
    }
    if(f.top && out.length>f.top){
      // 已选中的项必须留在可视区，否则用户看不到自己选了什么
      var sel=st.sel[k], head=out.slice(0,f.top);
      out.slice(f.top).forEach(function(x){ if(sel[x[0]]) head.push(x); });
      out=head;
    }
    return out;
  }
  function renderSide(){
    var h=[];
    // 左侧只列过滤维度。2026-09-17 起不再有范围开关（用户要求）：进库就是看全部，
    // 列表默认按位阶高→低、同位阶按生效时间新→旧排序（见 cmp 的 rank 分支）。
    FACETS.forEach(function(f){
      var bs=buckets(f.k), sel=st.sel[f.k];
      h.push('<div class="lv-f"><div class="lv-fh">'+e(f.t)+'</div><div class="lv-fb">');
      bs.forEach(function(b){
        var lab=(f.label&&f.label[b[0]])||b[1];
        var on=sel[b[0]]?' on':'';
        h.push('<button type="button" class="lv-o'+on+'" data-k="'+e(f.k)+'" data-v="'+e(b[0])
          +'"><span class="lv-ck"></span><span class="lv-ol">'+e(lab)+'</span>'
          +'<b>'+n2(b[2])+'</b></button>');
      });
      if(!bs.length) h.push('<div class="lv-none">无匹配</div>');
      h.push('</div></div>');
    });
    SIDE.innerHTML=h.join('');
  }

  // ---------------- 已选条件
  function renderChips(){
    var out=[];
    for(var k in st.sel){
      var f=FMAP[k]; if(!f) continue;
      for(var v in st.sel[k]){
        if(!st.sel[k][v]) continue;
        var lab=(f.label&&f.label[v])|| (k==='pub'?(PUB_LABEL[v]||v):v);
        out.push('<button type="button" class="lv-chip" data-k="'+e(k)+'" data-v="'+e(v)+'">'
          +e(lab)+'<i>×</i></button>');
      }
    }
    // 结果中检索：每个被冻结的关键词各给一枚可单独移除的 chip（AND 关系）
    for(var j=st.qs.length-1;j>=0;j--){
      out.unshift('<button type="button" class="lv-chip lv-chip-q" data-k="qs" data-i="'+j
        +'" title="结果中检索：本条与前后的关键词以 AND 组合">在「'+e(st.qs[j])+'」结果中<i>×</i></button>');
    }
    if(st.q) out.unshift('<button type="button" class="lv-chip lv-chip-q" data-k="q">关键词：'+e(st.q)+'<i>×</i></button>');
    CHIPS.innerHTML = out.length ? out.join('') : '';
    var extra=[];
    if(st.fld==='f') extra.push('全文');
    if(st.md==='fuzzy') extra.push('模糊');
    if(CNT) CNT.innerHTML='共 <b>'+n2(hits.length)+'</b> 条'
      + (extra.length?' · '+extra.join(' · '):'');
  }

  // ---------------- 右栏列表
  function row(i,idx){
    var r=IT[i];
    var lv=r[F.level],tp=r[F.topic],s=r[F.status],code=r[F.code],name=r[F.name],
        url=r[F.url],issuer=r[F.issuer],pub=r[F.pub],impl=r[F.impl],
        point=r[F.point],note=r[F.note],toc=r[F.toc],duty=r[F.duty],
        read=r[F.read],region=r[F.region],tocn=r[F.tocn],amend=r[F.amend];
    var h='<article class="lv-it"><div class="lv-no">'+(idx+1)+'</div><div class="lv-bd">';
    h+='<div class="lv-r1"><h3 class="lv-t">';
    h+= url ? '<a href="'+e(url)+'" target="_blank" rel="noopener">'+e(name)
              +'</a><span class="lv-ext" title="打开发布机构官网原文">\\u2197</span>'
            : e(name);
    h+='</h3><span class="lv-act">'+(read||'')+'</span></div>';
    h+='<div class="lv-r2"><span class="rd-badge '+(S[s]||'b-ghost')+'">'+e(s)+'</span>'
      +'<span class="rd-badge '+(L[lv]||'b-ghost')+'">'+e(lv)+'</span>'
      +'<span class="lv-tg">'+e(tp)+'</span>';
    var meta=[]; if(code) meta.push(code); if(issuer) meta.push(issuer);
    if(region&&region!=='全国') meta.push(region);
    if(pub) meta.push('发布 '+pub); if(impl) meta.push('实施 '+impl);
    h+='<span class="lv-mt">'+e(meta.join(' · '))+'</span></div>';
    // 修订沿革（P2-4）：显示在徽章行下，来源是官方前言里写明的「第 N 次修正 / 修订」。
    // 用中性底色，不与「时效性」徽章抢注意力 —— 它是补充信息，不是状态。
    if(amend) h+='<div class="lv-am"><span class="lv-am-k">修订沿革</span>'+e(amend)+'</div>';
    var ab=point||note||'';
    if(ab) h+='<p class="lv-ab">'+e(ab.length>160?ab.slice(0,160)+'…':ab)+'</p>';
    var tg='';
    if(duty) for(var k=0;k<Math.min(duty.length,4);k++) tg+='<span class="rd-tag">'+e(duty[k])+'</span>';
    if(tg||tocn>=3){
      h+='<div class="lv-tags">'+tg+(tocn>=3
        ? '<details class="lv-toc"><summary>章节目录 '+tocn+' 节</summary><ol class="lb-toclist">'
          +(toc||[]).slice(0,40).map(function(x){return '<li>'+e(x)+'</li>';}).join('')
          +'</ol></details>' : '')+'</div>';
    }
    return h+'</div></article>';
  }
  function render(){
    var size=st.size, pages=Math.max(1,Math.ceil(hits.length/size));
    if(st.page>pages) st.page=pages;
    var a=(st.page-1)*size, b=Math.min(a+size,hits.length), out=[];
    if(!hits.length){
      host.innerHTML='<div class="lv-empty">没有符合条件的条目。可点左上「重置」清空条件，'
        +'或放宽「资源类型 / 效力级别 / 时效性」的勾选。</div>';
    }else{
      for(var i=a;i<b;i++) out.push(row(hits[i],i));
      host.innerHTML=out.join('');
    }
    renderPager(pages,a,b);
  }
  function renderPager(pages,a,b){
    if(!PAGER) return;
    if(hits.length<=st.size){ PAGER.innerHTML=''; return; }
    var p=st.page, win=[];
    for(var i=1;i<=pages;i++){
      if(i===1||i===pages||(i>=p-2&&i<=p+2)) win.push(i);
      else if(win[win.length-1]!=='…') win.push('…');
    }
    var h='<div class="lv-pg">';
    h+='<button type="button" data-p="1"'+(p<=1?' disabled':'')+'>首页</button>';
    h+='<button type="button" data-p="'+(p-1)+'"'+(p<=1?' disabled':'')+'>上一页</button>';
    win.forEach(function(x){
      h+= x==='…' ? '<span class="lv-gap">…</span>'
        : '<button type="button" data-p="'+x+'"'+(x===p?' class="on"':'')+'>'+x+'</button>';
    });
    h+='<button type="button" data-p="'+(p+1)+'"'+(p>=pages?' disabled':'')+'>下一页</button>';
    h+='<button type="button" data-p="'+pages+'"'+(p>=pages?' disabled':'')+'>末页</button>';
    h+='<span class="lv-info">'+n2(a+1)+'–'+n2(b)+' / 共 '+n2(hits.length)+' 条 · 第 '+p+' / '+pages+' 页</span>';
    PAGER.innerHTML=h+'</div>';
  }

  // ---------------- 交互
  SIDE.addEventListener('click',function(ev){
    var b=ev.target.closest('.lv-o'); if(!b) return;
    var k=b.getAttribute('data-k'), v=b.getAttribute('data-v');
    var f=FMAP[k];
    if(f&&f.multi){ st.sel[k][v]=!st.sel[k][v]; }
    else { var had=st.sel[k][v]; for(var x in st.sel[k]) st.sel[k][x]=false; st.sel[k][v]=!had; }
    refilter(false);
  });
  CHIPS.addEventListener('click',function(ev){
    var b=ev.target.closest('.lv-chip'); if(!b) return;
    var k=b.getAttribute('data-k');
    if(k==='q'){ st.q=''; if(Q) Q.value=''; }
    else if(k==='qs'){ st.qs.splice(parseInt(b.getAttribute('data-i'),10)||0,1); }
    else st.sel[k][b.getAttribute('data-v')]=false;
    refilter(false);
  });
  // 「结果中检索」：把当前关键词冻结为一条条件（不进输入框，改为 chip 呈现），
  // 之后输入的关键词在它的结果集里继续收敛 —— 等价于北大法宝的「结果中检索」。
  if(INQ) INQ.addEventListener('click',function(){
    var v=(Q&&Q.value||'').trim().toLowerCase();
    if(!v){ if(Q) Q.focus(); return; }
    st.qs.push(v); st.q='';
    if(Q){ Q.value=''; Q.focus(); }
    refilter(false);
  });
  PAGER.addEventListener('click',function(ev){
    var b=ev.target.closest('button[data-p]'); if(!b||b.disabled) return;
    st.page=parseInt(b.getAttribute('data-p'),10)||1;
    render();
    var top=host.getBoundingClientRect().top+window.scrollY-80;
    window.scrollTo({top:top,behavior:'smooth'});
  });
  if(RESET) RESET.addEventListener('click',function(){
    st.q=''; st.qs=[]; st.fld='t'; st.md='exact'; st.sort='rank';
    if(SORTD) SORTD.value='rank';
    for(var k in st.sel) st.sel[k]={};
    if(Q) Q.value='';
    syncSeg(FSEG,'f','t'); syncSeg(MSEG,'m','exact');
    refilter(false);
  });
  // 检索范围 / 匹配方式：分段按钮（对标北大法宝的「标题 / 全文」「精确 / 模糊」）
  function syncSeg(box,attr,val){
    if(!box) return;
    var bs=box.querySelectorAll('button');
    for(var i=0;i<bs.length;i++)
      bs[i].className = (bs[i].getAttribute('data-'+attr)===val)?'on':'';
  }
  function bindSeg(box,attr,key,def){
    if(!box) return;
    box.addEventListener('click',function(ev){
      var b=ev.target.closest('button'); if(!b) return;
      var v=b.getAttribute('data-'+attr)||def;
      st[key]=v; syncSeg(box,attr,v); refilter(false);
    });
  }
  bindSeg(FSEG,'f','fld','t');
  bindSeg(MSEG,'m','md','exact');
  var timer=null;
  if(Q) Q.addEventListener('input',function(){
    if(timer) clearTimeout(timer);
    timer=setTimeout(function(){ st.q=(Q.value||'').trim().toLowerCase(); refilter(false); },140);
  });
  // Enter = 直接冻结为「结果中检索」条件，省一次点击
  if(Q) Q.addEventListener('keydown',function(ev){
    if(ev.key==='Enter' && INQ){ ev.preventDefault(); INQ.click(); }
  });
  if(SORTD) SORTD.addEventListener('change',function(){
    st.sort=SORTD.value; sortHits(); st.page=1; render();
  });
  if(SIZED) SIZED.addEventListener('change',function(){
    st.size=parseInt(SIZED.value,10)||20; st.page=1; render();
  });

  refilter(false);
})();
</script>
"""

# ---------------------------------------------------------------- 页签通用逻辑（两页共用）
# 2026-09-18：法规库与合规义务清单拆成两个页面后，两页仍用同一套「页签切换 + 深链直达」逻辑，
# 故抽成共用块。业务脚本通过 window.kbTab 调用（原 activateTab）。
TABS_JS = """
<script>
(function(){
  // ⚠️ 旧锚点兜底 —— 拆页的**必要条件**，不能删。
  // standards.html#pane-duty / #pane-ask / #d-xxx 曾经都落在法规库页，站外分享、搜索
  // 引擎收录、公众号里传过的链接都带这些锚点；本页没有对应面板时若不转走，读者会
  // 静默停在错误视图（用户 2026-09-18 的原话：「点击合规义务清单，跳进去还是原来
  // 带法条原文库的页面」）。用 location.replace 而非 href：不留历史记录，返回键可正常回退。
  var h=location.hash||'';
  var hasDuty=!!document.getElementById('pane-duty');
  var hasLib=!!document.getElementById('pane-lib');
  if(hasLib && !hasDuty && /^#(pane-(duty|ask)(?:-[a-z]+)?|d-[A-Za-z0-9-]+)$/.test(h)){
    location.replace('duties.html'+h); return;
  }
  if(hasDuty && !hasLib && /^#pane-(lib|draft)(?:-[a-z]+)?$/.test(h)){
    location.replace('standards.html'+h); return;
  }
  var tabs=[].slice.call(document.querySelectorAll('.lb-tabs > .rd-fchip'));
  var panes=[].slice.call(document.querySelectorAll('.lb-pane'));
  var noSmooth=false;
  tabs.forEach(function(b){
    b.addEventListener('click',function(){
      tabs.forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      var want='pane-'+b.getAttribute('data-tab');
      panes.forEach(function(p){ p.hidden = (p.id!==want); });
      if(noSmooth){ window.scrollTo(0,0); }
      else { window.scrollTo({top:0,behavior:'smooth'}); }
    });
  });
  function activateTab(name){
    var b=tabs.filter(function(x){return x.getAttribute('data-tab')===name;})[0];
    if(!b) return;
    noSmooth=true; b.click(); noSmooth=false;   // 深链直达时直接定位，不做滚动动画
  }
  window.kbTab=activateTab;
  var hm=/^#pane-(lib|draft|duty|ask)(?:-([a-z]+))?$/.exec(h);
  if(hm) activateTab(hm[1]);
})();
</script>
"""


DUTY_JS = """
<script>
(function(){
  var activateTab=window.kbTab||function(){};

  // ---------- 合规义务清单：主题大类切换 + 义务全文搜索 ----------
  var dchips=[].slice.call(document.querySelectorAll('.duty-filters .rd-fchip'));
  var dcats=[].slice.call(document.querySelectorAll('.lb-cat'));
  var dq=document.getElementById('dutyQ'), dcnt=document.getElementById('dutyCount');
  var curCat='ALL';
  function applyDuty(){
    var kw=(dq&&dq.value||'').trim().toLowerCase();
    var n=0;
    if(kw){ [].slice.call(document.querySelectorAll('.lb-s')).forEach(function(s){s.open=true;}); }
    dcats.forEach(function(c){
      var okCat=(curCat==='ALL'||c.getAttribute('data-cat')===curCat);
      var shown=0;
      if(okCat){
        [].slice.call(c.querySelectorAll('.lb-d2')).forEach(function(d){
          var txt=(d.textContent||'').toLowerCase();
          var ok=(!kw||txt.indexOf(kw)>=0);
          d.style.display=ok?'':'none';
          if(ok) shown++;
        });
        [].slice.call(c.querySelectorAll('.lb-s')).forEach(function(s){
          var vis=[].slice.call(s.querySelectorAll('.lb-d2'))
            .filter(function(d){return d.style.display!=='none';}).length;
          s.style.display=vis?'':'none';
        });
      }
      c.style.display=(okCat&&(shown>0||!kw))?'':'none';
      n+=shown;
    });
    if(dcnt) dcnt.textContent=kw?('匹配 '+n+' 项义务'):'';
  }
  // ---------- 视图切换：矩阵总览 ⇄ 逐条明细 ----------
  var dviews={matrix:document.getElementById('dmMatrix'),detail:document.getElementById('dmDetail')};
  var dsw=[].slice.call(document.querySelectorAll('.dm-switch .dm-sw'));
  function showDutyView(v){
    dsw.forEach(function(b){b.classList.toggle('on',b.getAttribute('data-view')===v);});
    for(var k in dviews){ if(dviews[k]) dviews[k].hidden=(k!==v); }
  }
  dsw.forEach(function(b){
    b.addEventListener('click',function(){ showDutyView(b.getAttribute('data-view')); });
  });
  function mark(el){
    el.style.transition='background .3s'; el.style.background='#fff8dc';
    setTimeout(function(){ el.style.background=''; },2600);
  }
  function pickCat(cat){
    curCat=cat||'ALL';
    dchips.forEach(function(x){x.classList.toggle('on',x.getAttribute('data-dcat')===curCat);});
    if(dq) dq.value='';
    applyDuty();
  }
  function goScene(cat,si){
    showDutyView('detail'); pickCat(cat);
    var sec=document.getElementById('s-'+cat+'-'+si);
    if(sec){ sec.open=true; sec.scrollIntoView({behavior:'smooth',block:'center'}); mark(sec); }
  }
  function goCat(cat){
    showDutyView('detail'); pickCat(cat);
    var sec=document.querySelector('.lb-cat[data-cat="'+cat+'"]');
    if(sec){ sec.scrollIntoView({behavior:'smooth',block:'start'}); mark(sec); }
  }
  [].slice.call(document.querySelectorAll('.dm-cell[data-cat]')).forEach(function(td){
    function go(){ goScene(td.getAttribute('data-cat'), td.getAttribute('data-si')); }
    td.addEventListener('click',go);
    td.addEventListener('keydown',function(e){
      if(e.key==='Enter'||e.key===' '){ e.preventDefault(); go(); }
    });
  });
  [].slice.call(document.querySelectorAll('.dm-cat[data-cat]')).forEach(function(th){
    function go(){ goCat(th.getAttribute('data-cat')); }
    th.addEventListener('click',go);
    th.addEventListener('keydown',function(e){
      if(e.key==='Enter'||e.key===' '){ e.preventDefault(); go(); }
    });
  });

  dchips.forEach(function(b){
    b.addEventListener('click',function(){
      dchips.forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      curCat=b.getAttribute('data-dcat'); applyDuty();
      if(curCat!=='ALL'){
        var sec=document.querySelector('.lb-cat[data-cat="'+curCat+'"]');
        if(sec) sec.scrollIntoView({behavior:'smooth',block:'start'});
      }
    });
  });
  if(dq) dq.addEventListener('input',function(){
    if((dq.value||'').trim()) showDutyView('detail');
    applyDuty();
  });
  applyDuty();

  // 通用：任何带 data-goto-tab 的按钮都可切到指定页签（如义务清单里指向「按话题找依据」）
  [].slice.call(document.querySelectorAll('[data-goto-tab]')).forEach(function(b){
    b.addEventListener('click',function(){ activateTab(b.getAttribute('data-goto-tab')); });
  });

  // ---------- 按话题找依据（P3-8，对标威科先行「智能图表」）----------
  //
  // 数据 window.LD_WZ 由构建期从 duties.json 生成（17 大类 / 93 场景 / 285 义务），
  // 只含「结构 + 义务标题 + 风险」，**不含正文**。正文一律从 #pane-duty 里已经渲染好的
  // 义务卡按 d-<cat>-<si>-<di> clone 过来（见 cloneDuty）—— 单一事实来源，
  // 明细改了清单自动跟着改，不会出现两份口径。
  (function(){
    var pane=document.getElementById('pane-ask'); if(!pane) return;
    var IDX=window.LD_WZ||[]; if(!IDX.length) return;
    var q=document.getElementById('wzQ'), go=document.getElementById('wzGo'),
        tip=document.getElementById('wzTip'), steps=document.getElementById('wzSteps'),
        p1=document.getElementById('wzP1'), p2=document.getElementById('wzP2'),
        out=document.getElementById('wzOut');
    // sel 的键是 "大类下标-场景下标"：一句话问可能跨大类命中，所以场景选择不能只按当前大类存。
    var cur=null, sel={}, p2List=[], p2Multi=false, q2Head='', blocks=[], wzArts=[],
        mdCache='', mdTitle='', curStep=1, curLabel='';

    var WSC=String.fromCharCode(9,10,13,32,12288);   // 制表/换行/回车/空格/全角空格
    var SEP='，、；;。.？?！!／/|「」【】（）(),:：·'+WSC;
    var RCLS={'高':'r-hi','中高':'r-mh','中':'r-md','低':'r-lo'};
    var N_TOTAL_SCENE=IDX.reduce(function(a,c){return a+c.s.length;},0);

    function sKey(ci,si){ return ci+'-'+si; }
    function selList(){
      var out=[], k, p;
      for(k in sel){ if(!sel[k]) continue; p=k.split('-');
        out.push([parseInt(p[0],10), parseInt(p[1],10)]); }
      out.sort(function(a,b){ return (a[0]-b[0])||(a[1]-b[1]); });
      return out;
    }
    function selDutyCount(){
      var n=0;
      selList().forEach(function(p){ n+=IDX[p[0]].s[p[1]][1].length; });
      return n;
    }
    // 中文没有词边界：把问句切成 2-gram / 3-gram，命中「场景名 / 义务标题 / 义务说明」
    // 的程度即相关度。疑问词（怎么/要不要/吗…）在语料里本来就命中不了，会自然得 0 分，
    // 不必维护停用词表。
    function grams(str){
      var s=String(str||'').toLowerCase(), segs=[], cur2='', i, j;
      for(i=0;i<s.length;i++){
        var c=s.charAt(i);
        if(SEP.indexOf(c)>=0){ if(cur2){segs.push(cur2); cur2='';} }
        else cur2+=c;
      }
      if(cur2) segs.push(cur2);
      var set={};
      segs.forEach(function(seg){
        if(seg.length>=2) set[seg]=1;
        for(j=0;j+2<=seg.length;j++) set[seg.substr(j,2)]=1;
        for(j=0;j+3<=seg.length;j++) set[seg.substr(j,3)]=1;
      });
      var out=[]; for(var k in set) out.push(k);
      return out;
    }
    // 「场景名 + 义务标题」的索引：用来算词频权重。中文里「处理 / 管理 / 合规 / 食品」
    // 这种高频词一旦按命中数计分，会把「委托处理」「食品安全主体责任」这类
    // 与提问无关的场景顶上来（实测「门店临期食品怎么处理」会把「委托处理、共同处理与提供」
    // 排进去）。所以按「出现在多少个场景/义务标题里」反向降权：只出现在 1-2 个标题里的
    // 词（派单、临期、摇一摇）拿满权重，烂大街的词基本不计分。
    var NAMES=null;
    function nameIndex(){
      if(NAMES) return NAMES;
      NAMES=[];
      IDX.forEach(function(c){
        c.s.forEach(function(s){
          NAMES.push(s[0].toLowerCase());
          s[1].forEach(function(x){ NAMES.push((x[0]||'').toLowerCase()); });
        });
      });
      return NAMES;
    }
    function queryGrams(txt){
      var raw=grams(txt), nm=nameIndex(), out=[], i, j, g, df;
      for(i=0;i<raw.length;i++){
        g=raw[i];
        df=0;
        for(j=0;j<nm.length;j++) if(nm[j].indexOf(g)>=0) df++;
        if(df > nm.length*0.35) continue;              // 太烂大街，直接不计分
        var base=(g.length>=6?3:(g.length>=3?1.5:1)); // 长词权重更高
        out.push({g:g, w:base/(1+df*0.5)});
      }
      return out;
    }
    function gHit(qg,hay){
      var n=0, i;
      for(i=0;i<qg.length;i++) if(hay.indexOf(qg[i].g)>=0) n+=qg[i].w;
      return n;
    }

    function e2(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
    function flat(s){
      s=String(s==null?'':s);
      var o='', i, c;
      for(i=0;i<s.length;i++){ c=s.charAt(i); o+=(WSC.indexOf(c)>=0?' ':c); }
      while(o.indexOf('  ')>=0) o=o.split('  ').join(' ');
      return o.replace(/^ | $/g,'');
    }
    function riskBar(ds){
      var t={}, i;
      for(i=0;i<ds.length;i++){ var r=ds[i][1]||''; t[r]=(t[r]||0)+1; }
      var s='';
      ['高','中高','中','低'].forEach(function(k){
        if(t[k]) s+='<i class="'+RCLS[k]+'" style="flex:'+t[k]+' 1 0" title="'+k+' '+t[k]+' 项"></i>';
      });
      return s?('<span class="dm-bar">'+s+'</span>'):'';
    }
    function say(html,cls){
      if(!tip) return;
      tip.innerHTML=html;
      tip.className='wz-fr-tip'+(cls?(' '+cls):'');
    }

    function goStep(n){
      curStep=n;
      var ps=steps.querySelectorAll('.wz-st');
      for(var i=0;i<ps.length;i++)
        ps[i].className='wz-st'+((parseInt(ps[i].getAttribute('data-s'),10)<=n)?' on':'');
      p1.hidden=(n!==1); p2.hidden=(n!==2); out.hidden=(n!==3);
    }

    // ---------- 第 1 步：选一件「正在做的事」
    function renderP1(){
      var h='<div class="wz-hint"><b>第 1 步</b>　先选一件<b>你正在做的事</b>。'
        +'不确定就从下面的问句里挑最接近的那句——不用先想它归哪一类。</div><div class="wz-cats">';
      IDX.forEach(function(c,ci){
        var ds=[];
        c.s.forEach(function(s){ ds=ds.concat(s[1]); });
        h+='<button type="button" class="wz-cat" data-ci="'+ci+'">'
          +'<span class="wz-cat-q">'+e2(c.a||c.n)+'</span>'
          +'<span class="wz-cat-n">'+e2(c.n)+'</span>'
          +'<span class="wz-cat-m">'+c.s.length+' 个场景 · '+ds.length+' 项义务</span>'
          +'<span class="wz-cat-r">'+riskBar(ds)+'</span>'
          +'<span class="wz-cat-e">常见话题：'+e2((c.e||[]).slice(0,4).join(' · '))+'</span>'
          +'</button>';
      });
      p1.innerHTML=h+'</div>';
    }

    // ---------- 第 2 步：勾场景（list 可能是「某个大类的全部场景」，也可能是「一句话问命中的场景」）
    function renderP2(list,opts){
      opts=opts||{};
      var h='<div class="wz-hint">'+opts.head+'</div><div class="wz-scs">';
      list.forEach(function(p){
        var c=IDX[p.ci], s=c.s[p.si], k=sKey(p.ci,p.si);
        h+='<button type="button" class="wz-sc'+(sel[k]?' on':'')+'" data-k="'+k+'">'
          +(opts.multi?('<span class="wz-sc-c">'+e2(c.n)+'</span>'):'')
          +'<b>'+e2(s[0])+'</b><em>'+s[1].length+' 项</em>'+riskBar(s[1])+'</button>';
      });
      h+='</div><div class="wz-acts">'
        +'<button type="button" class="wz-btn wz-primary" data-a="gen">生成法律依据清单 →</button>'
        +'<button type="button" class="wz-btn" data-a="all">全选上面这些</button>'
        +'<button type="button" class="wz-btn" data-a="none">清空</button>'
        +'<button type="button" class="wz-btn" data-a="back">← 按大类自己挑</button>'
        +'<span class="wz-cnt" id="wzCnt"></span></div>';
      p2.innerHTML=h;
      p2List=list; p2Multi=!!opts.multi; q2Head=opts.head||'';
      updCnt();
    }
    function updCnt(){
      var ks=selList(), c=document.getElementById('wzCnt');
      if(c) c.textContent=ks.length?('已选 '+ks.length+' 个场景 · '+selDutyCount()
        +' 项义务 · 点上方场景可增减'):'还没选场景';
    }
    function catList(ci){
      var out=[];
      IDX[ci].s.forEach(function(s,si){ out.push({ci:ci, si:si}); });
      return out;
    }

    function openCat(ci){
      cur=IDX[ci]; curLabel=cur.a||cur.n; sel={};
      var nd=cur.s.reduce(function(a,s){return a+s[1].length;},0);
      renderP2(catList(ci), {head:'<b>第 2 步</b>　话题：<b>'+e2(curLabel)+'</b>　'
        +'勾选这次真正涉及的场景（可多选）。本类共 '+cur.s.length+' 个场景 / '+nd+' 项义务。'});
      goStep(2);
      window.scrollTo({top:Math.max(0, pane.offsetTop-70), behavior:'smooth'});
    }

    p1.addEventListener('click',function(ev){
      var b=ev.target.closest('.wz-cat'); if(!b) return;
      openCat(parseInt(b.getAttribute('data-ci'),10)||0);
    });

    p2.addEventListener('click',function(ev){
      var b=ev.target.closest('button'); if(!b) return;
      var a=b.getAttribute('data-a'), k=b.getAttribute('data-k');
      if(k!=null){
        sel[k]=!sel[k];
        b.className='wz-sc'+(sel[k]?' on':'');
        updCnt();
        return;
      }
      if(a==='all'){ p2List.forEach(function(p){ sel[sKey(p.ci,p.si)]=true; }); renderP2(p2List,
        {head:q2Head, multi:p2Multi}); }
      else if(a==='none'){ sel={}; renderP2(p2List,{head:q2Head, multi:p2Multi}); }
      else if(a==='back'){ goStep(1);
        window.scrollTo({top:Math.max(0,pane.offsetTop-70),behavior:'smooth'}); }
      else if(a==='gen'){
        if(!selList().length){ say('先至少勾选一个场景，再生成清单。','wz-warn'); return; }
        renderOut();
        window.scrollTo({top:Math.max(0, pane.offsetTop-70), behavior:'smooth'});
      }
    });

    // ---------- 第 3 步：清单本体（义务卡直接从逐条明细 clone）
    function cloneDuty(cat,si,di){
      var src=document.getElementById('d-'+cat+'-'+si+'-'+di);
      if(!src) return null;
      var n=src.cloneNode(true);
      n.removeAttribute('id');
      n.style.display='';
      n.setAttribute('data-wz','1');
      return n;
    }
    function readDuty(n,meta){
      function t(sel){ var x=n.querySelector(sel); return x?flat(x.textContent):''; }
      var refs=[].slice.call(n.querySelectorAll('.lb-refs > a, .lb-refs > span'))
        .map(function(x){return flat(x.textContent);})
        .filter(function(x,i,a){return x && a.indexOf(x)===i;});
      var arts=[].slice.call(n.querySelectorAll('.art-item')).map(function(it){
        function g(sel){ var x=it.querySelector(sel); return x?flat(x.textContent):''; }
        return {src:g('.art-src'), no:g('.art-no'), q:g('.art-quote')};
      }).filter(function(a){return a.src||a.no;});
      return {t:t('.lb-d2-t b'), risk:(meta&&meta[1])||t('.lb-d2-t .rk'),
              d:t('.lb-d2-d'), refs:refs, arts:arts};
    }

    function renderOut(){
      var list=selList();
      var wrap=document.createElement('div'); wrap.className='wz-res';
      blocks=[]; wzArts=[];
      var nDuty=0, catsUsed={}, catNames=[];
      list.forEach(function(p,idx){
        var ci=p[0], si=p[1], c=IDX[ci], sc=c.s[si], ds=sc[1];
        if(!catsUsed[c.n]){ catsUsed[c.n]=1; catNames.push(c.n); }
        var sec=document.createElement('section'); sec.className='wz-sc-blk';
        var h4=document.createElement('h4');
        h4.innerHTML='<span class="wz-blk-i">'+(idx+1)+'</span>'
          +(p2Multi?('<span class="wz-blk-c">'+e2(c.n)+'</span>'):'')
          +'<span class="wz-blk-n">'+e2(sc[0])+'</span><i>'+ds.length+' 项义务</i>';
        sec.appendChild(h4);
        var blk={cat:c.n, name:sc[0], n:0, duties:[]};
        for(var di=0;di<ds.length;di++){
          var n=cloneDuty(c.id,si,di);
          if(!n) continue;
          sec.appendChild(n);
          nDuty++; blk.n++;
          blk.duties.push(readDuty(n,ds[di]));
        }
        var jump=document.createElement('button');
        jump.type='button'; jump.className='wz-jump';
        jump.setAttribute('data-cat',c.id); jump.setAttribute('data-si',si);
        jump.textContent='该场景的标杆做法 / 参考设计 / 自查点 →';
        sec.appendChild(jump);
        blocks.push(blk);
        wrap.appendChild(sec);
      });
      mdTitle = catNames.length<=2 ? catNames.join('、') : (catNames.length+' 个大类');

      // 法条汇总：从 clone 出来的条款原文块反推「本话题涉及哪些法条」
      var ak={};
      [].slice.call(wrap.querySelectorAll('.art-item')).forEach(function(it){
        var s=flat((it.querySelector('.art-src')||{}).textContent);
        var a=flat((it.querySelector('.art-no')||{}).textContent);
        if(!s||!a) return;
        var k=s+'|'+a;
        if(ak[k]){ ak[k].n++; return; }
        ak[k]={src:s,no:a,n:1}; wzArts.push(ak[k]);
      });
      var laws={};
      [].slice.call(wrap.querySelectorAll('.art-src')).forEach(function(x){
        var t=flat(x.textContent); if(t) laws[t]=1; });
      [].slice.call(wrap.querySelectorAll('.lb-refs > a, .lb-refs > span')).forEach(function(x){
        var t=flat(x.textContent); if(t) laws[t]=1; });
      var nLaw=Object.keys(laws).length;

      out.innerHTML='';
      var head=document.createElement('div'); head.className='wz-head';
      head.innerHTML='<div class="wz-hd-l"><span class="wz-hd-k">法律依据清单</span>'
        +'<b>'+e2(mdTitle)+'</b>'
        +'<span class="wz-hd-s">'+list.length+' 个场景 · '+nDuty+' 项义务 · '
        +nLaw+' 部依据 · '+wzArts.length+' 条条款原文</span></div>'
        +'<div class="wz-hd-r">'
        +'<button type="button" class="wz-btn" data-a="open">展开全部条款原文</button>'
        +'<button type="button" class="wz-btn" data-a="copy">复制 Markdown</button>'
        +'<button type="button" class="wz-btn" data-a="dl">下载 .md</button>'
        +'<button type="button" class="wz-btn" data-a="print">打印 / 存 PDF</button>'
        +'<button type="button" class="wz-btn" data-a="edit">← 调整场景</button>'
        +'<button type="button" class="wz-btn" data-a="back1">← 换一个话题</button>'
        +'</div>';
      out.appendChild(head);

      if(wzArts.length){
        var ab=document.createElement('div'); ab.className='wz-arts';
        ab.innerHTML='<div class="wz-arts-h">本话题涉及的法条<b>'+wzArts.length+' 条</b>'
          +'<span>点任一条可定位到下方的条款原文；每项义务下另附官方原文深链</span></div>'
          +'<div class="wz-arts-l">'+wzArts.map(function(a,i){
              return '<button type="button" class="wz-art" data-i="'+i+'">《'+e2(a.src)+'》'
                +e2(a.no)+(a.n>1?('<em>'+a.n+' 项引用</em>'):'')+'</button>';
            }).join('')+'</div>';
        out.appendChild(ab);
      }else{
        var nb=document.createElement('div'); nb.className='wz-note';
        nb.innerHTML='本话题的 '+list.length+' 个场景里，义务已锚定到<b>具体条款号</b>的条目暂未覆盖，'
          +'因此没有可展开的条款原文。每项义务下的<b>灰色依据标签</b>即该义务引用的法规与标准，'
          +'点开可直达发布机构官网原文（含标准正文入口）。';
        out.appendChild(nb);
      }
      out.appendChild(wrap);
      mdCache=buildMd(list.length,nDuty,nLaw);
      goStep(3);
    }

    function locate(i){
      var a=wzArts[i]; if(!a) return;
      var items=out.querySelectorAll('.art-item'), hit=null, k;
      for(k=0;k<items.length;k++){
        var s=flat((items[k].querySelector('.art-src')||{}).textContent);
        var n=flat((items[k].querySelector('.art-no')||{}).textContent);
        if(s===a.src && n===a.no){ hit=items[k]; break; }
      }
      if(!hit) return;
      var box=hit.closest('.art-box'); if(box) box.open=true;
      hit.scrollIntoView({behavior:'smooth',block:'center'});
      hit.style.transition='background .3s'; hit.style.background='#fff8dc';
      setTimeout(function(){ hit.style.background=''; },2600);
    }
    function jumpScene(cat,si){
      activateTab('duty'); showDutyView('detail'); pickCat(cat);
      var el=document.getElementById('s-'+cat+'-'+si);
      if(el){ el.open=true; el.scrollIntoView({behavior:'smooth',block:'center'}); mark(el); }
    }

    out.addEventListener('click',function(ev){
      var b=ev.target.closest('button'); if(!b) return;
      var cls=b.className||'';
      if(cls.indexOf('wz-art')>=0 && b.getAttribute('data-i')!=null){
        locate(parseInt(b.getAttribute('data-i'),10)); return;
      }
      if(cls.indexOf('wz-jump')>=0 && b.getAttribute('data-si')!=null){
        jumpScene(b.getAttribute('data-cat'), parseInt(b.getAttribute('data-si'),10)); return;
      }
      var a=b.getAttribute('data-a'); if(!a) return;
      if(a==='open'){
        [].slice.call(out.querySelectorAll('.art-box')).forEach(function(x){x.open=true;});
        b.textContent='条款原文已全部展开';
      }
      else if(a==='copy'){ copyText(mdCache,b); }
      else if(a==='dl'){ download(mdCache); }
      else if(a==='print'){ window.print(); }
      else if(a==='edit'){ goStep(2); window.scrollTo({top:Math.max(0,pane.offsetTop-70),behavior:'smooth'}); }
      else if(a==='back1'){ goStep(1); window.scrollTo({top:Math.max(0,pane.offsetTop-70),behavior:'smooth'}); }
    });

    function copyText(txt,btn){
      function done(ok){
        var o=btn.textContent;
        btn.textContent=ok?'已复制到剪贴板':'复制失败，请手动选择';
        setTimeout(function(){ btn.textContent=o; },2000);
      }
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(txt).then(function(){done(true);},
          function(){done(false);});
        return;
      }
      try{
        var ta=document.createElement('textarea');
        ta.value=txt; ta.style.position='fixed'; ta.style.left='-9999px';
        document.body.appendChild(ta); ta.select();
        var ok=document.execCommand('copy');
        document.body.removeChild(ta); done(ok);
      }catch(e){ done(false); }
    }
    function download(txt){
      try{
        var blob=new Blob([txt],{type:'text/markdown;charset=utf-8'});
        var a=document.createElement('a');
        a.href=URL.createObjectURL(blob);
        a.download='法律依据清单-'+cur.n+'.md';
        document.body.appendChild(a); a.click();
        setTimeout(function(){ URL.revokeObjectURL(a.href);
          if(a.parentNode) a.parentNode.removeChild(a); },500);
      }catch(e){}
    }
    function buildMd(nScene,nDuty,nLaw){
      var L=[], d=new Date();
      L.push('# 法律依据清单 · '+mdTitle);
      L.push('');
      L.push('> 来源：合规无终点 · 法规库「按话题找依据」（义务清单 '+IDX.length+' 个大类 / '
        +N_TOTAL_SCENE+' 个场景）');
      L.push('> 生成时间：'+d.toLocaleString('zh-CN')+'　|　共 '+nScene+' 个场景 / '
        +nDuty+' 项义务 / '+nLaw+' 部依据 / '+wzArts.length+' 条条款原文');
      L.push('');
      L.push('## 一、涉及的法条（'+wzArts.length+' 条）');
      L.push('');
      wzArts.forEach(function(a){
        L.push('- 《'+a.src+'》'+a.no+(a.n>1?('（'+a.n+' 项义务引用）'):''));
      });
      L.push('');
      L.push('## 二、义务与依据');
      blocks.forEach(function(b){
        L.push('');
        L.push('### '+(p2Multi?(b.cat+' › '):'')+b.name+'（'+b.n+' 项）');
        b.duties.forEach(function(x,i){
          L.push('');
          L.push('**'+(i+1)+'. '+(x.risk?('['+x.risk+'] '):'')+x.t+'**');
          if(x.d){ L.push(''); L.push(x.d); }
          if(x.refs.length){
            L.push('');
            L.push('依据：'+x.refs.map(function(r){return '《'+r+'》';}).join('、'));
          }
          x.arts.forEach(function(a){
            L.push('- 《'+a.src+'》'+a.no+(a.q?('：'+a.q):''));
          });
        });
      });
      L.push('');
      L.push('---');
      L.push('条文原文逐字取自我站官方原文库；引用前请核对现行有效版本。'
        +'本清单用于合规检索与自查参考，不构成法律意见。');
      return L.join('\\n');
    }

    // ---------- 一句话问：在义务清单语料里给「场景」打分并跨大类排序
    //
    // 三层权重：场景名（业务最小单位）> 义务标题 > 描述正文。
    // 命中场景名或义务标题的才进候选；只有大类介绍命中（说明只问到了领域、
    // 没问到具体动作）时不擅自编场景，改为提示用户自己勾。宁可少给，不给错。
    function search(txt){
      var qg=queryGrams(txt), ci, si;
      if(!qg.length) return null;
      var hits=[], cats=[];
      for(ci=0;ci<IDX.length;ci++){
        var c=IDX[ci];
        var cb=flat(c.a+' '+c.n+' '+(c.d||'')+' '+(c.e||[]).join(' ')).toLowerCase();
        var cScore=gHit(qg,cb);
        for(si=0;si<c.s.length;si++){
          var s=c.s[si], sn=s[0].toLowerCase();
          var tt=s[1].map(function(x){return (x[0]||'').toLowerCase();}).join(' ');
          var dd=s[1].map(function(x){return (x[2]||'').toLowerCase();}).join(' ');
          var vName=gHit(qg,sn)*10, vTtl=gHit(qg,tt)*3;
          // 「场景名 + 义务标题」是人工维护的词表，命中才算相关；
          // 义务说明是散文，只作为加权补充，单独命中不足以把场景拉进来
          // （否则「zzz不存在的词」这类胡问也会命中含「存在」二字的说明句）。
          if(vName+vTtl<=0) continue;
          hits.push({ci:ci, si:si, v:vName+vTtl+gHit(qg,dd)*1});
        }
        if(cScore) cats.push({ci:ci, v:cScore});
      }
      if(!hits.length) return {hits:[], cats:cats};
      hits.sort(function(a,b){ return b.v-a.v || a.ci-b.ci || a.si-b.si; });
      return {hits:hits, cats:cats};
    }

    function doSearch(){
      var txt=(q&&q.value||'').trim();
      if(!txt){ if(q) q.focus(); return; }
      var r=search(txt);
      if(!r || (!r.hits.length && !r.cats.length)){
        say('没匹配到。换个更贴近业务的说法试试（例如把「赔付」换成「售后」「退货」，'
          +'或补上具体动作），也可以从上面的大类里挑。','wz-warn');
        goStep(1); return;
      }
      if(!r.hits.length){
        // 只问到了领域、没问到动作：落到该大类，让用户自己勾场景
        r.cats.sort(function(a,b){ return b.v-a.v; });
        cur=IDX[r.cats[0].ci]; curLabel=cur.a||cur.n; sel={};
        renderP2(catList(r.cats[0].ci), {head:'<b>第 2 步</b>　只在分类层面匹配到'
          +'「<b>'+e2(cur.n)+'</b>」，没锁定到具体场景 —— 请从下面的场景里勾选'
          +'（本类共 '+cur.s.length+' 个场景 / '
          +cur.s.reduce(function(a,s){return a+s[1].length;},0)+' 项义务）。'});
        say('没锁定到具体场景，已把你送到「<b>'+e2(cur.n)+'</b>」，请勾选涉及的场景。','wz-warn');
        goStep(2);
        window.scrollTo({top:Math.max(0, pane.offsetTop-70), behavior:'smooth'});
        return;
      }
      var top=r.hits[0].v;
      var keep=r.hits.filter(function(h){ return h.v>=Math.max(1.2, top*0.35); }).slice(0,8);
      sel={};
      keep.forEach(function(h){ sel[sKey(h.ci,h.si)]=true; });
      cur=null;
      renderP2(keep, {multi:true, head:'<b>第 2 步</b>　一句话问：<b>'+e2(txt)+'</b>　'
        +'命中 <b>'+r.hits.length+'</b> 个场景，按相关度列出前 '+keep.length+' 个'
        +'（已默认勾选，可增减；每张卡左上角是该场景所属的大类）。'});
      renderOut();
      var cn={};
      keep.forEach(function(h){ cn[IDX[h.ci].n]=1; });
      say('已在 <b>'+Object.keys(cn).length+'</b> 个大类里定位到 <b>'+r.hits.length
        +'</b> 个相关场景，清单见下方；点「← 按大类自己挑」可换成按目录浏览。','wz-ok');
    }
    if(go) go.addEventListener('click',doSearch);
    if(q) q.addEventListener('keydown',function(ev){
      if(ev.key==='Enter'){ ev.preventDefault(); doSearch(); }
    });
    // 步骤条：可以往回点，或回到已经生成过的清单；不允许跳过
    steps.addEventListener('click',function(ev){
      var b=ev.target.closest('.wz-st'); if(!b) return;
      var n=parseInt(b.getAttribute('data-s'),10)||1;
      if(n===3 && out.innerHTML){ goStep(3); return; }
      if(n>curStep || (n===2 && !cur)){
        say('按顺序来：先选一件正在做的事 → 勾场景 → 生成清单。','wz-warn'); return;
      }
      goStep(n);
    });

    // ---------- 初始化：支持 #pane-ask-<大类id> 深链直达该大类的第 2 步
    var hm2=/^#pane-ask(?:-([a-z]+))?$/.exec(location.hash||'');
    renderP1();
    var found=-1, z;
    if(hm2 && hm2[1]) for(z=0;z<IDX.length;z++) if(IDX[z].id===hm2[1]) found=z;
    if(found>=0) openCat(found); else goStep(1);
  })();

  // ---------- 深链定位：从搜索结果跳转 #d-xxx 时展开父级并高亮 ----------
  function focusDuty(){
    var h=(location.hash||'').replace(/^#/,'');
    if(!/^d-/.test(h)) return;
    activateTab('duty');
    showDutyView('detail');
    var el=document.getElementById(h);
    if(!el) return;
    var p=el.closest('.lb-s'); if(p) p.open=true;
    var c=el.closest('.lb-cat'); if(c){ c.style.display=''; }
    [].slice.call(c?c.querySelectorAll('.lb-d2'):[]).forEach(function(d){d.style.display='';});
    [].slice.call(c?c.querySelectorAll('.lb-s'):[]).forEach(function(s){s.style.display='';});
    el.scrollIntoView({behavior:'smooth',block:'center'});
    el.style.transition='background .3s'; el.style.background='#fff8dc';
    setTimeout(function(){ el.style.background=''; },2600);
  }
  window.addEventListener('hashchange',focusDuty);
  focusDuty();
})();
</script>
"""


def refresh_chrome():
    """页面整体重写后恢复子导航、统一导航/页脚与分享元数据（均幂等）。"""
    import importlib.util
    for name in ("inject_subnav", "unify_chrome", "inject_meta"):
        p = os.path.join(HERE, name + ".py")
        if not os.path.exists(p):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            m.main()
        except Exception as e:
            print(f"  跳过 {name}：{e}")


if __name__ == "__main__":
    main()
    refresh_chrome()
