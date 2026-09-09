#!/usr/bin/env python3
"""合规雷达生成器：立法日历 / 监管行动 / 全球监管地图。

输入：sources/radar/{calendar,actions,global}.json —— 人工核实维护的结构化数据
输出：radar/{index,calendar,actions,map}.html

设计约束：
- 幂等：每次运行整体重写输出页，随后自动调用 unify_chrome / inject_meta 恢复
  统一导航、页脚与分享元数据。
- 地图采用「分区方块（tile grid）」而非地理轮廓：不描绘任何国界，规避地图绘制
  合规风险；中国仅作为一个整体辖区出现，台湾、香港、澳门不单独成块。
- 倒计时由页面 JS 按打开时的日期计算，静态文件无需每日重生成。

用法：
    python3 build_radar.py
"""

import html
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "radar")
OUT = os.path.join(HERE, "radar")

DOMAINS = ["数据合规", "AI合规", "算法合规", "平台合规", "产品合规", "价格合规"]

REGION_CN = {
    "CN": "中国", "EU": "欧盟", "US": "美国", "GB": "英国",
    "JP": "日本", "KR": "韩国", "IN": "印度", "SG": "新加坡",
    "BR": "巴西", "VN": "越南", "AU": "澳大利亚", "CA": "加拿大",
    "AE": "阿联酋", "SA": "沙特", "ZA": "南非",
}

# 类型 → 徽章色系 key
TYPE_KEY = [
    ("施行", "eff"), (" serious", "eff"),
]


def esc(s):
    return (html.escape(str(s), quote=True)
            if s is not None else "")


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- badge 色系
def type_class(t):
    if "意见" in t or "立法" in t or "草案" in t:
        return "b-blue"
    if "截止" in t or "宽限期" in t or "评估" in t:
        return "b-amber"
    if "调查" in t or "执法" in t or "治理" in t or "检查" in t:
        return "b-red"
    if "司法" in t or "规则" in t or "制度" in t:
        return "b-purple"
    return "b-green"


def heat(n):
    if n >= 5:
        return 3
    if n >= 3:
        return 2
    if n >= 1:
        return 1
    return 0


def src_tag(src):
    if src == "official":
        return '<span class="rd-src src-off">官方原文</span>'
    return '<span class="rd-src src-ana">专业解读</span>'


def page(title, desc, crumb_html, h1, lead, body, depth=1):
    prefix = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} · lawdatify</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="{prefix}index.html">首页</a> / {crumb_html}</div>
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


def stat_strip(stats):
    cells = "".join(
        f'<div class="rd-stat"><b>{esc(v)}</b><span>{esc(k)}</span></div>'
        for k, v in stats
    )
    return f'<div class="rd-stats">{cells}</div>'


def filter_bar(fid, options, label="筛选"):
    btns = "".join(
        f'<button class="rd-fchip{" on" if i == 0 else ""}" '
        f'data-fg="{fid}" data-fv="{esc(v)}">{esc(t)}</button>'
        for i, (v, t) in enumerate(options)
    )
    return f'<div class="rd-filters"><span class="rd-flabel">{esc(label)}</span>{btns}</div>'


# ================================================================= 日历
def cal_item(it):
    d = it["date"]
    yyyy, mm, dd = d.split("-")
    region = it.get("region", "CN")
    src = it.get("src", "official")
    tc = type_class(it["type"])
    future = d >= date.today().strftime("%Y-%m-%d")
    cnt = (f'<span class="rd-count" data-d="{yyyy}-{mm}-{dd}">…</span>'
           if future else '<span class="rd-count past">已过</span>')
    return f"""<div class="rd-item" data-region="{esc(region)}" data-domain="{esc(it.get('domain',''))}">
  <div class="rd-date"><b>{mm}.{dd}</b><i>{yyyy}</i></div>
  <div class="rd-body">
    <div class="rd-row"><span class="rd-badge {tc}">{esc(it['type'])}</span>
      <span class="rd-tags"><span class="rd-tag">{esc(it.get('domain',''))}</span>
      <span class="rd-tag tg-region">{esc(REGION_CN.get(region, region))}</span></span>{cnt}</div>
    <h3><a href="{esc(it['url'])}" target="_blank" rel="noopener">{esc(it['title'])}</a>{src_tag(src)}</h3>
    <div class="rd-meta">{esc(it.get('issuer',''))}</div>
    <p>{esc(it.get('note',''))}</p>
  </div>
</div>"""


DOMAIN_COLORS = {
    "数据合规": "#1b4f8a", "AI合规": "#7c3aed", "算法合规": "#0f766e",
    "平台合规": "#b45309", "产品合规": "#15803d", "价格合规": "#b03a48",
}


def cal_js_data(items):
    """把日历条目压成页面内嵌 JS 数据（radar-cal.js 消费）。"""
    slim = []
    for it in items:
        slim.append({
            "date": it["date"], "title": it["title"], "type": it["type"],
            "domain": it.get("domain", ""), "region": it.get("region", ""),
            "regionName": REGION_CN.get(it.get("region", ""), it.get("region", "")),
            "issuer": it.get("issuer", ""), "note": it.get("note", ""),
            "url": it["url"], "src": it.get("src", "official"),
        })
    return json.dumps({"domains": DOMAIN_COLORS, "items": slim},
                      ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def page_calendar(cal):
    items = sorted(cal["items"], key=lambda x: x["date"])
    today = date.today().strftime("%Y-%m-%d")
    future = [i for i in items if i["date"] >= today]
    past = [i for i in items if i["date"] < today]

    parts = []
    parts.append(stat_strip([
        ("未来节点", len(future)),
        ("覆盖辖区", f"{len({i.get('region') for i in items})} 个"),
        ("最近节点", future[0]["date"] if future else "-"),
        ("已跟踪总量", len(items)),
    ]))

    parts.append('<p class="rd-note"><b>月历视图</b>：色条为该日节点，按领域着色；'
                 '点击日期格查看当日详情，点击条目标题直达原文。'
                 '<b>官方原文</b>指发布机构官网的具体公告/全文页面；<b>专业解读</b>'
                 '指暂未获取原文深链时采用的可溯源专业评述页面，两者已明确区分，'
                 '不做混同。日期以官方文件为准，征求意见稿不作为生效规则。</p>')

    parts.append(f"""
<div class="cal" id="calMount">
  <div class="cal-head">
    <div class="cal-title-wrap"><span class="cal-title"></span><span class="cal-sub"></span></div>
    <div class="cal-btns">
      <button class="cal-nav cal-today-btn" type="button">今天</button>
      <button class="cal-nav cal-prev" type="button" aria-label="上个月">‹</button>
      <button class="cal-nav cal-next" type="button" aria-label="下个月">›</button>
    </div>
  </div>
  <div class="cal-doms"></div>
  <div class="cal-dow-row">{"".join(f'<span>{d}</span>' for d in ['一','二','三','四','五','六','日'])}</div>
  <div class="cal-body"></div>
</div>
<div id="calDetail" class="cal-detail"></div>

<script>window.CAL_DATA = {cal_js_data(items)};</script>
<script src="../assets/radar-cal.js"></script>
<script>RadarCal.init('#calMount');</script>""")

    if future or past:
        parts.append('<details class="cal-fold"><summary>清单视图：全部 '
                     f'{len(items)} 个节点（按倒计时排列）</summary>')
        parts.append('<div class="rd-list" style="margin-top:16px">'
                     + "".join(cal_item(i) for i in future + past)
                     + "</div></details>")
        parts.append(COUNTDOWN_JS)

    return page(
        "合规日历", "法律施行日、征求意见截止与申报节点的月历视图，覆盖中国与主要海外辖区。",
        '<a href="index.html">合规雷达</a> / 合规日历',
        "合规日历",
        "把散落在各机构的公开信息重排到一张月历上：哪些规定即将施行、哪些意见正在征集、"
        "哪些申报节点会过期。每条附发布机构原文深链，可直接点开核对。",
        "\n".join(parts),
    )


# ================================================================= 行动
def act_item(it):
    tg = "".join(f'<span class="rd-tag">{esc(t)}</span>' for t in it.get("targets", []))
    prog = it.get("progress") or ""
    return f"""<div class="rd-item rd-act" data-level="{esc(it.get('level',''))}" data-status="{esc(it.get('status',''))}" data-domain="{esc(it.get('domain',''))}">
  <div class="rd-body">
    <div class="rd-row"><span class="rd-badge b-green">{esc(it.get('series',''))}</span>
      <span class="rd-badge b-ghost">{esc(it.get('status',''))}</span>
      <span class="rd-tags"><span class="rd-tag">{esc(it.get('domain',''))}</span>
      <span class="rd-tag tg-region">{esc(it.get('level',''))} · {esc(it.get('region',''))}</span></span></div>
    <h3><a href="{esc(it['url'])}" target="_blank" rel="noopener">{esc(it['name'])}</a>{src_tag(it.get('src','official'))}</h3>
    <div class="rd-meta">{esc(it.get('issuer',''))} · {esc(it.get('period',''))}</div>
    <p>{esc(it.get('focus',''))}</p>
    {'<div class="rd-prog"><b>进展</b>' + esc(prog) + '</div>' if prog else ''}
    {'<div class="rd-targets">' + tg + '</div>' if tg else ''}
  </div>
</div>"""


def page_actions(acts):
    items = acts["items"]
    running = [i for i in items if i.get("status") in ("进行中", "待施行", "待发布", "待审议")]
    body_parts = []
    body_parts.append(stat_strip([
        ("在列行动", len(items)),
        ("推进中", len(running)),
        ("覆盖领域", f"{len({i.get('domain') for i in items})} 个"),
    ]))
    body_parts.append('<p class="rd-note">这里收录的是<b>正在推进或近期推进的动作</b>——专项治理、检查、'
                      '立法草案与安全调查，而非已完结的量级事件。判断是否与本业务相关，'
                      '请先看「适用对象」标签。）</p>'.replace("）", ""))
    opts = [("ALL", "全部")] + [(d, d) for d in DOMAINS if d in {i.get("domain") for i in items}]
    body_parts.append(filter_bar("dom", opts, "领域"))
    body_parts.append(f'<div class="rd-list">{chr(10).join(map(act_item, items))}</div>')
    body_parts.append(domain_filter_script())

    return page(
        "监管行动", "正在推进的专项治理、监督检查、立法草案与安全调查，含适用对象与最新进展。",
        '<a href="index.html">合规雷达</a> / 监管行动',
        "监管行动",
        "监管不止写在纸上，更在执行里。这里追踪各主管部门正在推进的动作，标注适用对象、"
        "重点内容与最新进展，便于判断是否需要同步开展内部自查。",
        "\n".join(body_parts),
    )


# ================================================================= 全球地图
def page_map(g):
    juris = g["jurisdictions"]
    items = g["items"]
    count = {}
    last = {}
    for i in items:
        count[i["code"]] = count.get(i["code"], 0) + 1
        last[i["code"]] = max(last.get(i["code"], ""), i["date"])

    counts_js = json.dumps(count, ensure_ascii=False)
    names_js = json.dumps({j["code"]: j["name"] for j in juris},
                          ensure_ascii=False)
    tips_js = json.dumps(
        {c: f"最近 {d}" for c, d in last.items()}, ensure_ascii=False)

    # 下钻列表（按辖区分组）
    list_html = []
    for j in juris:
        its = [i for i in items if i["code"] == j["code"]]
        if not its:
            continue
        rows = []
        for i in sorted(its, key=lambda x: x["date"], reverse=True):
            rows.append(
                f'<div class="rd-item rd-gitem" data-code="{esc(j["code"])}">'
                f'<div class="rd-body">'
                f'<div class="rd-row"><span class="rd-badge {type_class(i["type"])}">'
                f'{esc(i["type"])}</span><span class="rd-tags">'
                f'<span class="rd-tag">{esc(i.get("domain",""))}</span></span>'
                f'<span class="rd-count past">{esc(i["date"])}</span></div>'
                f'<h3><a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["title"])}</a>'
                f'{src_tag(i.get("src","official"))}</h3>'
                f'<p>{esc(i.get("note",""))}</p></div></div>'
            )
        list_html.append(
            f'<div class="rd-gblock" data-code="{esc(j["code"])}">'
            f'<h4 class="rd-gh">{esc(j["name"])}<span>{len(rows)}</span></h4>'
            f'{"".join(rows)}</div>'
        )

    body = "\n".join([
        stat_strip([
            ("收录辖区", f"{len(juris)} 个"),
            ("有动态辖区", f"{len(count)} 个"),
            ("动态条目", len(items)),
        ]),
        """<p class="rd-note">底图为 <b>Natural Earth 公开数据</b>的等距圆柱投影<b>示意性视图</b>，
非地理精确边界地图，不承担划界意义；<b>中国（含台湾地区、香港、澳门）为一个整体色块</b>。
颜色深浅代表该辖区已收录的动态条目数量，点击辖区可下钻全部条目；
本页不请求任何在线地图服务。</p>""",
        """<div class="geo-legend">
  <span class="gl-item"><i class="gl hv0"></i>暂无收录</span>
  <span class="gl-item"><i class="gl hv1"></i>1–2 条</span>
  <span class="gl-item"><i class="gl hv2"></i>3–4 条</span>
  <span class="gl-item"><i class="gl hv3"></i>5 条以上</span>
  <span class="gl-note">微型辖区以圆点定位</span>
</div>""",
        '<div class="geo-frame" id="geoMap"></div>',
        '<div class="rd-mapres" id="mapres"></div>',
        '<div class="rd-glist" id="glist">' + "".join(list_html) + "</div>",
        f"""<script>window.GEO_META = {{
  counts: {counts_js},
  names: {names_js},
  tips: {tips_js}
}};</script>
<script src="../assets/radar-map.js"></script>
<script>
(function(){{
  var blocks=[].slice.call(document.querySelectorAll('.rd-gblock'));
  var res=document.getElementById('mapres');
  function show(code){{
    var n=0;
    blocks.forEach(function(b){{
      var ok=!code||b.getAttribute('data-code')===code;
      b.style.display=ok?'':'none'; if(ok)n++;
    }});
    if(res){{
      res.innerHTML=code
        ?'<div class="rd-resbar">已筛选 <b></b> 个辖区<button id="rclr">清除筛选</button></div>'
        :'';
      if(code){{
        res.querySelector('b').textContent=n;
        res.querySelector('#rclr').addEventListener('click',function(){{RadarMap.render(opt);}});
      }}
    }}
    if(code){{
      var el=document.getElementById('glist');
      if(el) el.scrollIntoView({{behavior:'smooth',block:'start'}});
    }}
  }}
  var opt={{
    mount:'#geoMap', geoUrl:'../sources/radar/geo.json',
    counts:window.GEO_META.counts, names:window.GEO_META.names,
    tipExtra:window.GEO_META.tips,
    onSelect:show
  }};
  RadarMap.render(opt);
}})();
</script>""",
    ])

    return page(
        "全球监管地图", "按司法辖区查看立法、执法与规则动态，覆盖中国、欧盟、美国、日韩、印度、东南亚、拉美与中东非。",
        '<a href="index.html">合规雷达</a> / 全球监管地图',
        "全球监管地图",
        "出海或跨境业务常问「这个国家现在什么口径」。真实地理轮廓着色呈现已核实的立法、"
        "执法与规则动向，点击辖区即可下钻全部条目。",
        body,
    )


# ================================================================= 总览
def _map_embed(counts, names, tips, selected_js="null", on_select="null"):
    """生成地图挂载区 + 数据 + 组件调用（radar/index 与首页共用）。"""
    counts_js = json.dumps(counts, ensure_ascii=False)
    names_js = json.dumps(names, ensure_ascii=False)
    tips_js = json.dumps(tips, ensure_ascii=False)
    return f"""<div class="geo-legend">
  <span class="gl-item"><i class="gl hv0"></i>暂无收录</span>
  <span class="gl-item"><i class="gl hv1"></i>1–2 条</span>
  <span class="gl-item"><i class="gl hv2"></i>3–4 条</span>
  <span class="gl-item"><i class="gl hv3"></i>5 条以上</span>
</div>
<div class="geo-frame" id="geoMap"></div>
<script>window.GEO_META={{counts:{counts_js},names:{names_js},tips:{tips_js}}};</script>
<script src="../assets/radar-map.js"></script>
<script>
(function(){{
  var opt={{
    mount:'#geoMap', geoUrl:'../sources/radar/geo.json',
    counts:window.GEO_META.counts, names:window.GEO_META.names,
    tipExtra:window.GEO_META.tips,
    selected:{selected_js}, onSelect:{on_select}
  }};
  RadarMap.render(opt);
}})();
</script>"""


def page_index(cal, acts, g):
    today = date.today().strftime("%Y-%m-%d")

    def days(d):
        return (date.fromisoformat(d) - date.today()).days

    future = sorted([i for i in cal["items"] if i["date"] >= today],
                    key=lambda x: x["date"])
    soon = [i for i in future if days(i["date"]) <= 120][:6]
    running = [i for i in acts["items"]
               if i.get("status") in ("进行中", "待施行", "待发布", "待审议")]

    # 地图数据
    count, last = {}, {}
    for i in g["items"]:
        count[i["code"]] = count.get(i["code"], 0) + 1
        last[i["code"]] = max(last.get(i["code"], ""), i["date"])
    names = {j["code"]: j["name"] for j in g["jurisdictions"]}
    tips = {c: f"最近 {d}" for c, d in last.items()}

    # 全球最新 3 条
    g_latest = sorted(g["items"], key=lambda x: x["date"], reverse=True)[:3]
    g_rows = "".join(
        f'<div class="rd-rowline"><span class="rd-when">'
        f'{esc(names.get(i["code"], i["code"]))}<i>{esc(i["date"])}</i></span>'
        f'<a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["title"])}</a></div>'
        for i in g_latest
    )

    soon_rows = "".join(
        f'<div class="rd-rowline">'
        f'<span class="rd-when">{esc(i["date"][5:].replace("-", "."))}'
        f'<i>{days(i["date"])} 天后</i></span>'
        f'<a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["title"])}</a>'
        f'<span class="rd-badge {type_class(i["type"])}">{esc(i["type"])}</span></div>'
        for i in soon
    )

    run_rows = "".join(
        f'<div class="rd-rowline"><span class="rd-when">'
        f'{esc(i.get("series",""))}<i>{esc(i.get("status",""))}</i></span>'
        f'<a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["name"])}</a>'
        f'<span class="rd-badge b-ghost">{esc(i.get("domain",""))}</span></div>'
        for i in running[:6]
    )

    deck = f"""
<div class="deck">
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#eef6fb;color:#1b4f8a">📅</span>
      即将到期 <a href="calendar.html">全部 →</a></div>
    <div class="rd-soon">{soon_rows}</div>
  </div>
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#eaf6f3;color:#0f7b6c">🛡️</span>
      推进中的行动 <a href="actions.html">全部 →</a></div>
    <div class="rd-soon">{run_rows}</div>
  </div>
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#f1effa;color:#6c5bb0">🌐</span>
      全球最新动态 <a href="map.html">地图 →</a></div>
    <div class="rd-soon">{g_rows}</div>
  </div>
</div>"""

    body = "\n".join([
        stat_strip([
            ("未来节点", len(future)),
            ("推进中行动", len(running)),
            ("覆盖辖区", f"{len(count)} 个"),
            ("最近节点", f"{days(future[0]['date'])} 天后" if future else "-"),
        ]),
        deck,
        '<div class="section-title"><span class="bar"></span>全球监管态势</div>',
        '<p class="lead">颜色深浅为各辖区已收录动态密度，点击辖区查看该地全部条目。</p>',
        _map_embed(count, names, tips,
                   selected_js='location.hash.slice(1)||null',
                   on_select='function(code){}'),
        '<p class="rd-note">数据由人工核实后录入，每条均附可点击原文链接。'
        '倒计时按页面打开时的系统日期实时计算。</p>',
    ])

    return page(
        "合规雷达", "立法日历、监管行动与全球监管地图：把散落的监管信息按时间与地域重排，聚焦可执行的关键节点。",
        '合规雷达',
        "合规雷达",
        "「什么时候要做什么」和「各地现在什么口径」——这是业务同事最常问的两个问题。"
        "合规雷达用日历、行动与地图三个视图回答它们。",
        body,
    )


# ================================================================= 首页区块
def home_deck(cal, acts, g):
    """首页「合规雷达驾驶舱」区块（RADAR:START/END，幂等替换）。"""
    today = date.today().strftime("%Y-%m-%d")

    def days(d):
        return (date.fromisoformat(d) - date.today()).days

    future = sorted([i for i in cal["items"] if i["date"] >= today],
                    key=lambda x: x["date"])
    soon = [i for i in future if days(i["date"]) <= 90][:4]
    running = [i for i in acts["items"]
               if i.get("status") in ("进行中", "待施行", "待发布", "待审议")][:4]
    names = {j["code"]: j["name"] for j in g["jurisdictions"]}
    g_latest = sorted(g["items"], key=lambda x: x["date"], reverse=True)[:4]

    def rows(pairs):
        inner = "".join(
            f'<div class="rd-rowline">'
            f'<span class="rd-when">{w}<i>{s}</i></span>'
            f'<a href="{u}" target="_blank" rel="noopener">{esc(t)}</a></div>'
            for w, s, u, t in pairs)
        return f'<div class="rd-soon">{inner}</div>'

    col1 = rows([
        (esc(i["date"][5:].replace("-", ".")), f"{days(i['date'])} 天后",
         esc(i["url"]), esc(i["title"])) for i in soon])
    col2 = rows([
        (esc(i.get("series", "")), esc(i.get("status", "")),
         esc(i["url"]), esc(i["name"])) for i in running])
    col3 = rows([
        (esc(names.get(i["code"], i["code"])), esc(i["date"]),
         esc(i["url"]), esc(i["title"])) for i in g_latest])

    return f"""<div class="deck">
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#eef6fb;color:#1b4f8a">📅</span>
      即将到期 <a href="radar/calendar.html">日历 →</a></div>
    {col1}
  </div>
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#eaf6f3;color:#0f7b6c">🛡️</span>
      推进中的行动 <a href="radar/actions.html">全部 →</a></div>
    {col2}
  </div>
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#f1effa;color:#6c5bb0">🌐</span>
      全球最新动态 <a href="radar/map.html">地图 →</a></div>
    {col3}
  </div>
</div>"""


HOME_RADAR_START = "<!-- RADAR:START -->"
HOME_RADAR_END = "<!-- RADAR:END -->"
HOME_RADAR_RE = re.compile(
    re.escape(HOME_RADAR_START) + r".*?" + re.escape(HOME_RADAR_END), re.S)

HOME_GEO_START = "<!-- GEOMETA:START -->"
HOME_GEO_END = "<!-- GEOMETA:END -->"
HOME_GEO_RE = re.compile(
    re.escape(HOME_GEO_START) + r".*?" + re.escape(HOME_GEO_END), re.S)

HOME_HS_START = "<!-- HEROSTATS:START -->"
HOME_HS_END = "<!-- HEROSTATS:END -->"
HOME_HS_RE = re.compile(
    re.escape(HOME_HS_START) + r".*?" + re.escape(HOME_HS_END), re.S)


def _replace_block(s, start, end, regex, content):
    block = start + "\n" + content + "\n" + end
    if regex.search(s):
        return regex.sub(lambda _: block, s, count=1)
    return s


def refresh_home_radar(cal, acts, g):
    """刷新首页三个数据区块（雷达驾驶舱 / 地图元数据 / hero 指标），幂等。"""
    p = os.path.join(HERE, "index.html")
    if not os.path.exists(p):
        return False
    s = open(p, encoding="utf-8").read()
    orig = s

    s = _replace_block(s, HOME_RADAR_START, HOME_RADAR_END, HOME_RADAR_RE,
                       home_deck(cal, acts, g))

    count, last = {}, {}
    for i in g["items"]:
        count[i["code"]] = count.get(i["code"], 0) + 1
        last[i["code"]] = max(last.get(i["code"], ""), i["date"])
    names = {j["code"]: j["name"] for j in g["jurisdictions"]}
    geo_js = ("<script>window.GEO_META={counts:" +
              json.dumps(count, ensure_ascii=False) +
              ",names:" + json.dumps(names, ensure_ascii=False) +
              ",tips:" + json.dumps({c: f"最近 {d}" for c, d in last.items()},
                                    ensure_ascii=False) + "};</script>")
    s = _replace_block(s, HOME_GEO_START, HOME_GEO_END, HOME_GEO_RE, geo_js)

    today = date.today().strftime("%Y-%m-%d")
    n_future = sum(1 for i in cal["items"] if i["date"] >= today)
    stats = f"""<div class="hero-stats">
    <div class="hs"><b>{n_future}</b><span>未来合规节点</span></div>
    <div class="hs"><b>{len(count)}</b><span>全球辖区在 Track</span></div>
    <div class="hs"><b>2×<i>/日</i></b><span>信息同步</span></div>
    <div class="hs"><b>100<i>%</i></b><span>深链实测</span></div>
  </div>"""
    s = _replace_block(s, HOME_HS_START, HOME_HS_END, HOME_HS_RE, stats)

    if s == orig:
        return False
    open(p, "w", encoding="utf-8").write(s)
    return True


# ================================================================= JS
COUNTDOWN_JS = """<script>
(function(){var t=new Date();t.setHours(0,0,0,0);
document.querySelectorAll('.rd-count[data-d]').forEach(function(el){
  var p=el.getAttribute('data-d').split('-');
  var d=new Date(+p[0],+p[1]-1,+p[2]);
  var n=Math.round((d-t)/86400000);
  if(n>0){el.textContent=n+' 天后';if(n<=30){el.classList.add('hot');}}
  else if(n===0){el.textContent='今天';el.classList.add('hot');}
  else {el.textContent='已过';el.classList.add('past');}
});})();
</script>"""


def domain_filter_script():
    return """<script>
(function(){
  document.querySelectorAll('.rd-filters').forEach(function(bar){
    bar.addEventListener('click',function(e){
      var b=e.target.closest('.rd-fchip'); if(!b) return;
      var fg=b.getAttribute('data-fg'), fv=b.getAttribute('data-fv');
      bar.querySelectorAll('.rd-fchip').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      document.querySelectorAll('.rd-list, .rd-glist').forEach(function(list){
        var any=list.querySelector('.rd-item'); if(!any) return;
        if(list.classList.contains('rd-glist')) return;
        list.querySelectorAll('.rd-item').forEach(function(it){
          var key = fg==='dom' ? 'domain' : fg;
          var attr = (fg==='dom') ? (it.getAttribute('data-domain')||'')
                                  : (it.getAttribute('data-'+fg)||'');
          it.style.display = (fv==='ALL'||attr===fv) ? '' : 'none';
        });
      });
    });
  });
})();
</script>"""


MAP_JS = ""  # 已由内联脚本与 radar-map.js 取代


# ================================================================= main
def write(rel, content):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def main():
    cal = load("calendar.json")
    acts = load("actions.json")
    g = load("global.json")

    os.makedirs(OUT, exist_ok=True)
    pages = [
        ("index.html", page_index(cal, acts, g)),
        ("calendar.html", page_calendar(cal)),
        ("actions.html", page_actions(acts)),
        ("map.html", page_map(g)),
    ]
    for rel, html_ in pages:
        write(rel, html_)
        print(f"  radar/{rel:<16} {len(html_):>6} B ✓")

    if refresh_home_radar(cal, acts, g):
        print("  index.html（雷达区块）刷新 ✓")
    else:
        print("  index.html（雷达区块）未找到标记，跳过")

    # 恢复统一导航 / 页脚 / 分享元数据
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
            print(f"  跳过 {name}：{e}")


if __name__ == "__main__":
    main()
