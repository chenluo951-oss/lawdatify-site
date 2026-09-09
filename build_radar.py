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

ZONES = [
    ("apac", "亚太", "apac"),
    ("eu", "欧洲", "eu"),
    ("na", "北美", "na"),
    ("sa", "拉美", "sa"),
    ("mea", "中东 · 非洲", "mea"),
]

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


# ================================================================= 日历条目
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


def page_calendar(cal):
    items = sorted(cal["items"], key=lambda x: x["date"])
    today = date.today().strftime("%Y-%m-%d")
    future = [i for i in items if i["date"] >= today]
    past = [i for i in items if i["date"] < today]

    n_future = len(future)
    regions = len({i.get("region") for i in items})
    dom = {i.get("domain") for i in items}
    nearest = future[0]["date"] if future else "-"

    opts = [("ALL", "全部")]
    opts += [(d, d) for d in DOMAINS if d in dom]
    dom_filter_js = domain_filter_script()

    parts = []
    parts.append(stat_strip([
        ("未来节点", n_future),
        ("覆盖辖区", f"{regions} 个"),
        ("最近节点", nearest),
        ("已跟踪总量", len(items)),
    ]))

    parts.append('<p class="rd-note">按倒计时排列。<b>官方原文</b>指发布机构官网的具体公告/全文页面；'
                 '<b>专业解读</b>指暂未获取原文深链时采用的可溯源专业评述页面，两者在点开的链接属性上'
                 '已明确区分，不做混同。日期以官方文件为准，征求意见稿不作为生效规则。</p>')

    parts.append(filter_bar("dom", opts, "领域"))
    parts.append(f'<div class="rd-list">{chr(10).join(map(cal_item, future))}</div>')

    if past:
        pat = [("ALL", "全部")] + [(d, d) for d in DOMAINS if d in past and True]
        parts.append(
            '<div class="rd-fold"><h4>已过节点（{n} 项，作为生效状态与裁判风向的对照保留）</h4>'
            '<div class="rd-list">'.format(n=len(past)))
        parts.append("\n".join(cal_item(i) for i in past))
        parts.append("</div></div>")

    parts.append(dom_filter_js)
    parts.append(COUNTDOWN_JS)

    body = "\n".join(parts)
    return page(
        "合规日历", "法律施行日、征求意见截止与申报节点的倒计时清单，覆盖中国与主要海外辖区。",
        '<a href="index.html">合规雷达</a> / 合规日历',
        "合规日历",
        "把散落在各机构的公开信息按时间轴重排：哪些规定即将施行、哪些意见正在征集、哪些申报节点会过期。"
        "每条附发布机构原文深链，可直接点开核对。",
        body,
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
    for i in items:
        count[i["code"]] = count.get(i["code"], 0) + 1

    # 区块
    zone_html = []
    for zkey, zname, _ in ZONES:
        members = [j for j in juris if j["group"] == zkey]
        if not members:
            continue
        tiles = []
        for j in members:
            n = count.get(j["code"], 0)
            h = heat(n)
            dis = "" if n else " off"
            tiles.append(
                f'<button class="rd-tile hv{h}{dis}" data-code="{esc(j["code"])}" '
                f'{"disabled" if not n else ""}>'
                f'<b>{esc(j["name"])}</b><i>{n}</i></button>'
            )
        zn = sum(count.get(j["code"], 0) for j in members)
        zone_html.append(
            f'<div class="rd-zone"><div class="rd-zone-h">{esc(zname)}'
            f'<span>{zn} 项</span></div><div class="rd-zone-b">{"".join(tiles)}</div></div>'
        )

    # 列表（按辖区分组）
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
        '<p class="rd-note">地图采用<b>分区方块</b>而非地理轮廓呈现：不描绘国界，'
        '中国仅作为一个整体辖区出现。颜色深浅代表该辖区动态条目数量，'
        '点击方块可下钻查看该地全部条目。</p>',
        '<div class="rd-map">' + "".join(zone_html) + "</div>",
        '<div class="rd-mapres" id="mapres"></div>',
        '<div class="rd-glist" id="glist">' + "".join(list_html) + "</div>",
        MAP_JS,
    ])

    return page(
        "全球监管地图", "按司法辖区查看立法、执法与规则动态，覆盖中国、欧盟、美国、日韩、印度、东南亚、拉美与中东非。",
        '<a href="index.html">合规雷达</a> / 全球监管地图',
        "全球监管地图",
        "出海或跨境业务常问「这个国家现在什么口径」。这里按辖区分组呈现已核实的立法、执法与规则动向，"
        "点击地图上的辖区即可下钻全部条目。",
        body,
    )


# ================================================================= 总览
def page_index(cal, acts, g):
    today = date.today().strftime("%Y-%m-%d")
    def days(d):
        return (date.fromisoformat(d) - date.today()).days
    future = sorted([i for i in cal["items"] if i["date"] >= today], key=lambda x: x["date"])
    soon = [i for i in future if days(i["date"]) <= 120][:6]
    running = [i for i in acts["items"] if i.get("status") in ("进行中", "待施行", "待发布", "待审议")]

    chips = []
    jd = {j["code"]: j["name"] for j in g["jurisdictions"]}
    cnt = {}
    for i in g["items"]:
        cnt[i["code"]] = cnt.get(i["code"], 0) + 1
    for code, n in sorted(cnt.items(), key=lambda x: -x[1]):
        chips.append(f'<span class="rd-chip">{esc(jd.get(code, code))}<i>{n}</i></span>')

    soon_rows = []
    for i in soon:
        soon_rows.append(
            f'<div class="rd-rowline">'
            f'<span class="rd-when">{esc(i["date"][5:].replace("-","."))}'
            f'<i>{days(i["date"])} 天后</i></span>'
            f'<a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["title"])}</a>'
            f'<span class="rd-badge {type_class(i["type"])}">{esc(i["type"])}</span></div>'
        )

    run_rows = "".join(
        f'<div class="rd-rowline"><span class="rd-when">'
        f'{esc(i.get("series",""))}<i>{esc(i.get("status",""))}</i></span>'
        f'<a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["name"])}</a>'
        f'<span class="rd-badge b-ghost">{esc(i.get("domain",""))}</span></div>'
        for i in running[:6]
    )

    cards = f"""<div class="cards">
  <a class="card" href="calendar.html">
    <div class="ico">📅</div>
    <h3>合规日历</h3>
    <p>施行日、征集截止、申报节点按倒计时排列，未来 {len(future)} 项已收录，最远看到 2028 年。</p>
    <div class="more">查看全部 →</div>
  </a>
  <a class="card" href="actions.html">
    <div class="ico">🛡️</div>
    <h3>监管行动</h3>
    <p>正在推进的专项治理、检查、立法草案与安全调查，标注适用对象与最新进展。</p>
    <div class="more">查看全部 →</div>
  </a>
  <a class="card" href="map.html">
    <div class="ico">🌐</div>
    <h3>全球监管地图</h3>
    <p>按辖区查看立法、执法与规则动向。地图不含国界，中国整体成块，点击即可下钻。</p>
    <div class="more">查看全部 →</div>
  </a>
</div>"""

    body = "\n".join([
        stat_strip([
            ("未来节点", len(future)),
            ("推进中行动", len(running)),
            ("覆盖辖区", f"{len(cnt)} 个"),
            ("最近节点", f"{days(future[0]['date'])} 天后" if future else "-"),
        ]),
        cards,
        '<div class="section-title"><span class="bar"></span>120 天内关键节点</div>',
        '<div class="rd-soon">' + "".join(soon_rows) + "</div>",
        '<div class="section-title"><span class="bar"></span>推进中的监管行动</div>',
        '<div class="rd-soon">' + run_rows + "</div>",
        '<div class="section-title"><span class="bar"></span>全球动态分布</div>',
        '<div class="rd-chips">' + "".join(chips) + "</div>",
        '<p class="rd-note">数据由人工核实后录入，每条均附可点击原文链接。'
        '日历等视图的倒计时按页面打开时的系统日期计算，无需每日重生成。</p>',
    ])

    return page(
        "合规雷达", "立法日历、监管行动与全球监管地图：把散落的监管信息按时间与地域重排，聚焦可执行的关键节点。",
        '合规雷达',
        "合规雷达",
        "「什么时候要做什么」和「各地现在什么口径」——这是业务同事最常问的两个问题。"
        "合规雷达用日历、行动与地图三个视图回答它们。",
        body,
    )


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


MAP_JS = """<script>
(function(){
  var blocks=[].slice.call(document.querySelectorAll('.rd-gblock'));
  var res=document.getElementById('mapres');
  function show(code){
    var n=0;
    blocks.forEach(function(b){
      var ok = !code || b.getAttribute('data-code')===code;
      b.style.display = ok?'':'none'; if(ok) n++;
    });
    if(res){
      res.innerHTML = code
        ? '<div class="rd-resbar">已筛选 <b></b> 个辖区<button id="rclr">清除筛选</button></div>'
        : '';
      if(code){
        res.querySelector('b').textContent=n;
        res.querySelector('#rclr').addEventListener('click',function(){clear();});
      }
    }
  }
  function clear(){
    document.querySelectorAll('.rd-tile.on').forEach(function(t){t.classList.remove('on');});
    show(null);
  }
  document.querySelectorAll('.rd-tile').forEach(function(tile){
    tile.addEventListener('click',function(){
      if(tile.disabled) return;
      var c=tile.getAttribute('data-code');
      if(tile.classList.contains('on')){clear();return;}
      document.querySelectorAll('.rd-tile.on').forEach(function(t){t.classList.remove('on');});
      tile.classList.add('on'); show(c);
    });
  });
})();
</script>"""


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
