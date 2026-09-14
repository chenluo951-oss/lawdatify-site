#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首页（监管动态·可视化）生成器。

替换 index.html 中三块标记内容（幂等，骨架其余部分不动）：

  <!-- RADAR:START -->   … <!-- RADAR:END -->   监管动态驾驶舱
      KPI 看板（监管动态 / 未来节点 / 推进中行动 / 覆盖辖区 / 公众号原文）
      + 三栏倒计时牌（即将到期 / 推进中行动 / 全球最新动态，链 news/ 子页）
      + 领域分布条形图（数据看板·按已收录条数）
      + 模块入口（监管动态总览 / 立法日历 / 应对建议 / 全球地图 / 公众号原文 / 简报归档）
  <!-- FEED:START -->    … <!-- FEED:END -->    最新监管动态流
      （合并「监管雷达 + 合规资讯」后统一在此呈现，逐条附官方深链与公众号原文标记）
  <!-- GEOMETA:START --> … <!-- GEOMETA:END -->  全球监管地图元数据（window.GEO_META）

数据源：
  sources/radar/{calendar,actions,global}.json  —— build_radar.load
  sources/news/items.jsonl                       —— build_topics.build_feed（复用已校验结果）
  kb/wx/index.json                               —— 公众号原文存档元数据

与 build_topics / build_radar 解耦：本脚本只写首页 index.html，不重写 news/ 子页。
"""
import json
import os
import re
import sys
from datetime import date

from build_topics import build_feed, DOMAIN_KEYS, DOMAIN_COLOR, esc
from build_radar import load as radar_load

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

RADAR_S, RADAR_E = "<!-- RADAR:START -->", "<!-- RADAR:END -->"
FEED_S, FEED_E = "<!-- FEED:START -->", "<!-- FEED:END -->"
GEO_S, GEO_E = "<!-- GEOMETA:START -->", "<!-- GEOMETA:END -->"

RUN_STATUSES = ("进行中", "待施行", "待发布", "待审议")


def replace_block(path, start, end, content):
    if not os.path.exists(path):
        print(f"  ! 缺少 {path}")
        return False
    s = open(path, encoding="utf-8").read()
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pat.search(s):
        print(f"  ! {os.path.basename(path)} 未找到 {start} 标记")
        return False
    block = start + "\n" + content + "\n" + end
    s = pat.sub(block, s, count=1)
    open(path, "w", encoding="utf-8").write(s)
    return True


def days_between(d):
    try:
        return (date.fromisoformat(d) - date.today()).days
    except Exception:
        return 999


def load_wx():
    p = os.path.join(HERE, "kb", "wx", "index.json")
    try:
        return json.load(open(p, encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []


# ---------------------------------------------------------------- KPI 看板
def render_kpi(n_feed, n_future, n_running, n_juris, n_wx):
    cards = [
        (n_feed, "监管动态"),
        (n_future, "未来合规节点"),
        (n_running, "推进中行动"),
        (n_juris, "覆盖辖区"),
        (n_wx, "公众号原文存档"),
    ]
    cells = "".join(
        f'<div class="kpi-card"><b>{v}</b><span>{t}</span></div>' for v, t in cards
    )
    return f'<div class="kpi">{cells}</div>'


# ---------------------------------------------------------------- 三栏倒计时牌
def render_deck(cal, acts, g):
    today = date.today().strftime("%Y-%m-%d")
    future = sorted([i for i in cal["items"] if i["date"] >= today],
                    key=lambda x: x["date"])
    soon = [i for i in future if days_between(i["date"]) <= 90][:4]
    running = [i for i in acts["items"]
               if i.get("status") in RUN_STATUSES][:4]
    names = {j["code"]: j["name"] for j in g["jurisdictions"]}
    g_latest = sorted(g["items"], key=lambda x: x["date"], reverse=True)[:4]

    def row(when, sub, url, title):
        return (f'<div class="rd-rowline"><span class="rd-when">{esc(when)}'
                f'<i>{esc(sub)}</i></span>'
                f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(title)}</a></div>')

    col1 = "".join(
        row(i["date"][5:].replace("-", "."), f"{days_between(i['date'])} 天后",
            i["url"], i["title"]) for i in soon
    ) or '<div class="rd-empty">未来 90 天内暂无生效节点</div>'
    col2 = "".join(
        row(i.get("series", ""), i.get("status", ""), i["url"], i["name"])
        for i in running
    ) or '<div class="rd-empty">暂无进行中的监管行动</div>'
    col3 = "".join(
        row(names.get(i["code"], i["code"]), i["date"], i["url"], i["title"])
        for i in g_latest
    ) or '<div class="rd-empty">暂无全球动态</div>'

    return f"""<div class="deck">
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#eef6fb;color:#1b4f8a">📅</span>
      即将到期 <a href="news/calendar.html">日历 →</a></div>
    <div class="rd-soon">{col1}</div>
  </div>
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#eaf6f3;color:#0f7b6c">🛡️</span>
      推进中的行动 <a href="news/actions.html">全部 →</a></div>
    <div class="rd-soon">{col2}</div>
  </div>
  <div class="deck-col">
    <div class="deck-h"><span class="deck-ico" style="background:#f1effa;color:#6c5bb0">🌐</span>
      全球最新动态 <a href="news/map.html">地图 →</a></div>
    <div class="rd-soon">{col3}</div>
  </div>
</div>"""


# ---------------------------------------------------------------- 领域分布条形图
def render_dist(verified):
    by = {}
    for it in verified:
        by[it["domain"]] = by.get(it["domain"], 0) + 1
    if not by:
        return ""
    mx = max(by.values())
    rows = []
    for d in DOMAIN_KEYS:
        c = by.get(d, 0)
        if not c:
            continue
        color = DOMAIN_COLOR.get(d, "#1b4f8a")
        w = max(6, round(c / mx * 100))
        rows.append(
            f'<div class="dist-row"><span class="dist-name">{esc(d)}</span>'
            f'<span class="dist-track"><span class="dist-bar" '
            f'style="width:{w}%;background:{color}"></span></span>'
            f'<span class="dist-n">{c}</span></div>'
        )
    return (f'<div class="dist"><div class="dist-h">监管动态 · 领域分布'
            f'<span class="dist-sub">按已收录条数</span></div>'
            f'{"".join(rows)}</div>')


# ---------------------------------------------------------------- 模块入口
def render_mod_entries():
    items = [
        ("news/index.html", "监管动态总览"),
        ("news/calendar.html", "立法日历"),
        ("news/actions.html", "应对建议"),
        ("news/map.html", "全球监管地图"),
        ("kb/wx.html", "公众号原文存档"),
        ("news/briefs.html", "简报归档"),
    ]
    chips = "".join(f'<a class="me" href="{u}">{t} →</a>' for u, t in items)
    return f'<div class="mod-entries">{chips}</div>'


# ---------------------------------------------------------------- 最新动态流
def render_feed(verified, n=10):
    lst = sorted(verified, key=lambda x: (x["date"], x.get("issue", "")),
                 reverse=True)[:n]
    rows = []
    for it in lst:
        color = DOMAIN_COLOR.get(it["domain"], "#1b4f8a")
        wx = '<span class="hl-wx">公众号</span>' if it.get("wx_id") else ""
        rows.append(
            f'<a class="hl" href="news/index.html#g-{esc(it["domain"])}">'
            f'<span class="hl-d" style="background:{color}">{esc(it["domain"])}</span>'
            f'<span class="hl-t">{esc(it["title"])}</span>'
            f'{wx}'
            f'<span class="hl-m">{esc(it["date"])}</span></a>'
        )
    more = (f'<div class="feed-more"><a href="news/index.html">查看全部 '
            f'{len(verified)} 条监管动态 →</a></div>')
    return f'<div class="hlist">{"".join(rows)}</div>{more}'


# ---------------------------------------------------------------- 全球地图元数据
def render_geo(g):
    count, last = {}, {}
    for i in g["items"]:
        count[i["code"]] = count.get(i["code"], 0) + 1
        last[i["code"]] = max(last.get(i["code"], ""), i["date"])
    names = {j["code"]: j["name"] for j in g["jurisdictions"]}
    tips = {c: f"最近 {d}" for c, d in last.items()}
    return ("<script>window.GEO_META={counts:" + json.dumps(count, ensure_ascii=False)
            + ",names:" + json.dumps(names, ensure_ascii=False)
            + ",tips:" + json.dumps(tips, ensure_ascii=False) + "};</script>")


def main():
    do_verify = "--no-verify" not in sys.argv
    verified, _internal, _dead, _native = build_feed(do_verify)
    cal = radar_load("calendar.json")
    acts = radar_load("actions.json")
    g = radar_load("global.json")
    wx = load_wx()

    today = date.today().strftime("%Y-%m-%d")
    n_future = sum(1 for i in cal["items"] if i["date"] >= today)
    n_running = sum(1 for i in acts["items"]
                    if i.get("status") in RUN_STATUSES)
    n_juris = len({i["code"] for i in g["items"]})

    radar_html = (
        render_kpi(len(verified), n_future, n_running, n_juris, len(wx))
        + render_deck(cal, acts, g)
        + render_dist(verified)
        + render_mod_entries()
    )
    feed_html = render_feed(verified)
    geo_js = render_geo(g)

    ok = True
    ok &= replace_block(INDEX, RADAR_S, RADAR_E, radar_html)
    ok &= replace_block(INDEX, FEED_S, FEED_E, feed_html)
    ok &= replace_block(INDEX, GEO_S, GEO_E, geo_js)
    if ok:
        print(f"  index.html ✓ 监管动态驾驶舱（KPI×5 + 领域分布 + 最新 {min(10, len(verified))} 条）"
              f" · 全球 {n_juris} 辖区")
    else:
        print("  index.html 写入失败（未找到标记）")
        return False
    return True


if __name__ == "__main__":
    main()
