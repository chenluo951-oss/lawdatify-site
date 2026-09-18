#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首页（合规动态·可视化）生成器。

替换 index.html 中三块标记内容（幂等，骨架其余部分不动）：

  <!-- RADAR:START -->   … <!-- RADAR:END -->   合规动态驾驶舱
      KPI 看板（合规动态 / 未来节点 / 推进中行动 / 覆盖辖区 / 公众号原文）
      + 三栏倒计时牌（即将到期 / 推进中行动 / 全球最新动态，链 news/ 子页）
      + 领域分布条形图（数据看板·按已收录条数）
      + 模块入口（合规动态总览 / 立法日历 / 应对建议 / 全球地图 / 公众号原文 / 简报归档）
  <!-- FEED:START -->    … <!-- FEED:END -->    最新合规动态流
      （合并「监管雷达 + 合规资讯」后统一在此呈现，逐条附官方深链与公众号原文标记）
  <!-- GEOMETA:START --> … <!-- GEOMETA:END -->  全球监管地图元数据（window.GEO_META）

数据源：
  sources/radar/{calendar,actions,global}.json  —— build_radar.load
  sources/news/items.jsonl                       —— build_topics.build_feed（复用已校验结果）
  kb/wx/index.json                               —— 公众号来源存档元数据

与 build_topics / build_radar 解耦：本脚本只写首页 index.html，不重写 news/ 子页。
"""
import json
import os
import re
import sys
from datetime import date, timedelta

from build_topics import build_feed, DOMAIN_KEYS, DOMAIN_COLOR, esc
from build_radar import load as radar_load, geo_counts

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

RADAR_S, RADAR_E = "<!-- RADAR:START -->", "<!-- RADAR:END -->"
# ⚠️ 首页信息层级（2026-09-17 重排）：
#   速览 → KPI 一行条 → **最新合规动态（正文）** → 驾驶舱（日历/行动/全球 + 领域分布）→ 全球地图
#   驾驶舱与领域分布属于「次级分析」，绝不能挡在正文前面（用户反馈：「图表太大，正文都在最下面」）。
KPI_S, KPI_E = "<!-- KPI:START -->", "<!-- KPI:END -->"
FEED_S, FEED_E = "<!-- FEED:START -->", "<!-- FEED:END -->"
GEO_S, GEO_E = "<!-- GEOMETA:START -->", "<!-- GEOMETA:END -->"
PULSE_S, PULSE_E = "<!-- PULSE:START -->", "<!-- PULSE:END -->"
# 首页「合规义务清单」区块：6 张精选卡是人工写的业务导读，但**规模数字与入口链接不能写死** ——
# 数字会随 duties.json 变化而过期；链接曾经是裸 `kb/standards.html`（不带锚点），点进去落在
# 法规库默认的「资料库」视图，也就是用户 2026-09-18 报障的「点击合规义务清单，跳进去还是
# 原来带法条原文库的页面」。现在数字由构建期算、链接指向独立页 kb/duties.html。
DUTY_LEAD_S, DUTY_LEAD_E = "<!-- DUTYLEAD:START -->", "<!-- DUTYLEAD:END -->"
DUTY_MORE_S, DUTY_MORE_E = "<!-- DUTYMORE:START -->", "<!-- DUTYMORE:END -->"

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


def load_duties():
    """合规义务总数（17 大类 / 77 场景 / 220 项，随数据源动态计算）。"""
    p = os.path.join(HERE, "sources", "standards", "duties.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for c in d.get("categories", []):
        for s in c.get("scenes", []):
            n += len(s.get("duties", []) or [])
    return n


def duty_scale():
    """义务清单规模 (主题大类, 业务场景, 具体义务) —— 从 duties.json 动态算，**禁止写死**。"""
    p = os.path.join(HERE, "sources", "standards", "duties.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return 0, 0, 0
    cats = d.get("categories") or []
    sc = sum(len(c.get("scenes") or []) for c in cats)
    du = sum(len(s.get("duties") or []) for c in cats
             for s in (c.get("scenes") or []))
    return len(cats), sc, du


def render_duty_lead():
    nc, ns, nd = duty_scale()
    return f"<b>{nc}</b> 个主题大类 · <b>{ns}</b> 个业务场景 · <b>{nd}</b> 项具体义务"


def render_duty_more():
    _nc, _ns, nd = duty_scale()
    return ('<a href="kb/duties.html">查看义务清单矩阵总览 · '
            f'{nd} 项逐条含条款原文与参考设计 →</a>')


# ---------------------------------------------------------------- KPI 看板
def render_kpi(n_feed, n_future, n_running, n_juris, n_wx):
    # 每张卡都可点击直达对应模块（req: 驾驶舱数字不应只是展示）
    cards = [
        (n_feed, "合规动态", "news/index.html"),
        (n_future, "未来合规节点", "news/calendar.html"),
        (n_running, "推进中行动", "news/actions.html"),
        (n_juris, "覆盖辖区", "news/map.html"),
        (n_wx, "公众号来源", "kb/wx.html"),
    ]
    cells = "".join(
        f'<a class="kpi-card" href="{u}"><b>{v}</b><span>{t}</span></a>'
        for v, t, u in cards
    )
    return f'<div class="kpi">{cells}</div>'


# ---------------------------------------------------------------- 今日合规速览
def render_pulse(n_future_90, n_future_30, n_running, n_week, n_wx, n_duties):
    """首页黄金位：用「打开网站第一眼该看什么」替代「四个模块分别是什么」。

    每条都是可点击的实时信号，带数字 + 一句「为什么现在要看」+ 去向。
    """
    rows = [
        ("📅", f"{n_future_90}", "部法规 / 标准将在 90 天内施行",
         f"其中 {n_future_30} 部本月生效 · 立法日历逐条附官方深链", "news/calendar.html"),
        ("🛡️", f"{n_running}", "项监管行动正在推进",
         "清朗·AI 乱象 / 食安整治 / 数据出境… · 应对建议一键直达", "news/actions.html"),
        ("📰", f"{n_week}", "条合规动态本周新增",
         f"含 {n_wx} 篇官方公众号原文 · 合规动态流逐条可溯源", "news/index.html"),
        ("📚", f"{n_duties}", "项合规义务随时可查",
         "逐条配法律 / 标准条款原文与可套用文案 · 知识库直达", "kb/index.html"),
    ]
    body = "".join(
        f'<a class="pulse-row" href="{u}">'
        f'<span class="pulse-ico">{ic}</span>'
        f'<span class="pulse-main"><b>{n}</b> {label}<i>{sub}</i></span>'
        f'<span class="pulse-go">→</span></a>'
        for ic, n, label, sub, u in rows
    )
    return f'<div class="pulse">{body}</div>'


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
    # 驾驶舱的每个数字都是入口（用户 2026-09-18：「所有数字应该可以点击」）：
    # 三栏各自的「共几项」挂在栏头，点了进对应模块页，而不是只把「日历 →」做成链接。
    n_soon = len(future)
    n_run = sum(1 for i in acts["items"] if i.get("status") in RUN_STATUSES)
    n_geo = len({i["code"] for i in g["items"]})

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

    def head(ico, bg, fg, title, n, unit, url, label):
        return (f'<div class="deck-h"><span class="deck-ico" style="background:{bg};'
                f'color:{fg}">{ico}</span>{title}'
                f'<a class="deck-n" href="{url}" title="查看全部{title}">'
                f'{n}<i>{unit}</i></a>'
                f'<a class="deck-go" href="{url}">{label} →</a></div>')

    return f"""<div class="deck">
  <div class="deck-col">
    {head("📅", "#eef6fb", "#1b4f8a", "即将到期", n_soon, "项", "news/calendar.html", "日历")}
    <div class="rd-soon">{col1}</div>
  </div>
  <div class="deck-col">
    {head("🛡️", "#eaf6f3", "#0f7b6c", "推进中的行动", n_run, "项", "news/actions.html", "全部")}
    <div class="rd-soon">{col2}</div>
  </div>
  <div class="deck-col">
    {head("🌐", "#f1effa", "#6c5bb0", "全球最新动态", n_geo, "个辖区", "news/map.html", "地图")}
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
            f'<a class="dist-row" href="news/index.html#g-{esc(d)}" '
            f'title="查看「{esc(d)}」的全部合规动态">'
            f'<span class="dist-name">{esc(d)}</span>'
            f'<span class="dist-track"><span class="dist-bar" '
            f'style="width:{w}%;background:{color}"></span></span>'
            f'<span class="dist-n">{c}</span></a>'
        )
    # 2026-09-17：单列 9 行会让这块占到 368px（半屏），正文被顶到 1000px 以下。
    # 拆成双列（各占一半行数）后约 180px —— 条形图是「一眼看分布」，不需要整行宽度。
    half = (len(rows) + 1) // 2
    cols = (f'<div class="dist-cols"><div class="dist-col">{"".join(rows[:half])}</div>'
            f'<div class="dist-col">{"".join(rows[half:])}</div></div>'
            if len(rows) > 5 else "".join(rows))
    return (f'<div class="dist"><div class="dist-h">合规动态 · 领域分布'
            f'<span class="dist-sub">按已收录条数</span></div>'
            f'{cols}</div>')


# ---------------------------------------------------------------- 模块入口
def render_mod_entries():
    items = [
        ("news/index.html", "合规动态总览"),
        ("news/today.html", "今日更新"),
        ("news/calendar.html", "立法日历"),
        ("news/actions.html", "应对建议"),
        ("news/map.html", "全球监管地图"),
        ("news/briefs.html", "简报归档"),
        ("manage/audit.html", "合规审计"),
    ]
    chips = "".join(f'<a class="me" href="{u}">{t} →</a>' for u, t in items)
    return f'<div class="mod-entries">{chips}</div>'


# ---------------------------------------------------------------- 最新动态流
def load_batch():
    """读「今日入库批次单」（由 build_updates.py 写入，口径只此一份）。

    首页列表按条目日期排序，天生看不出「今天采集了什么」；批次单给出的是
    **入库日**口径，两者相加才回答得了「今天更新了几条」。
    """
    try:
        with open(os.path.join(HERE, "sources", "news", "batch.json"),
                  encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def render_feed(verified, n=10):
    b = load_batch()
    n_new = int(b.get("n") or 0)
    # ⚠️ 批次单是上一次 build_updates 留下的文件：若它不是今天写的，就绝不能自称
    #「今日」（构建顺序被手工打乱时最容易踩到）。此时降级为「最近批次」，仍报真数。
    batch_is_today = (bool(b.get("is_today"))
                      and b.get("updated") == date.today().isoformat())
    new_titles = set(b.get("titles") or []) if n_new else set()

    head = ""
    if n_new:
        # 今天没采到就如实说「最近批次」，绝不挂「今日」（同 build_updates 的纪律）
        word = "今日" if batch_is_today else "最近批次"
        head = (
            '<div class="feed-today">'
            f'<span class="ft-n">{n_new}</span>'
            f'<span class="ft-l">{word}新增合规动态'
            f'（入库批次 {esc(b.get("batch") or "")}）</span>'
            '<a class="ft-a" href="news/today.html">逐条查看 →</a></div>'
        )

    lst = sorted(verified, key=lambda x: (x["date"], x.get("issue", "")),
                 reverse=True)[:n]
    rows = []
    for it in lst:
        color = DOMAIN_COLOR.get(it["domain"], "#1b4f8a")
        wx = '<span class="hl-wx">公众号</span>' if it.get("wx_id") else ""
        fresh = ('<span class="hl-new">今日入库</span>'
                 if it["title"] in new_titles else "")
        rows.append(
            f'<a class="hl" href="news/index.html#g-{esc(it["domain"])}">'
            f'<span class="hl-d" style="background:{color}">{esc(it["domain"])}</span>'
            f'<span class="hl-t">{esc(it["title"])}</span>'
            f'{fresh}{wx}'
            f'<span class="hl-m">{esc(it["date"])}</span></a>'
        )
    more = (f'<div class="feed-more"><a href="news/index.html">查看全部 '
            f'{len(verified)} 条合规动态 →</a></div>')
    return f'{head}<div class="hlist">{"".join(rows)}</div>{more}'


# ---------------------------------------------------------------- 全球地图元数据
def render_geo(g):
    # 口径见 build_radar.geo_counts：中国的数字要并上 china.json 的省级属地条目，
    # 否则首页地图上中国显示「6 条动态」、点进去却是 430 条。
    count, last = geo_counts(g)
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

    today = date.today()
    today_s = today.strftime("%Y-%m-%d")
    n_future = sum(1 for i in cal["items"] if i["date"] >= today_s)
    n_running = sum(1 for i in acts["items"]
                    if i.get("status") in RUN_STATUSES)
    n_juris = len({i["code"] for i in g["items"]})

    # 今日合规速览所需的实时信号
    n_future_90 = sum(1 for i in cal["items"]
                      if today_s <= i["date"] <= (today + timedelta(days=90)).strftime("%Y-%m-%d"))
    n_future_30 = sum(1 for i in cal["items"]
                      if today_s <= i["date"] <= (today + timedelta(days=30)).strftime("%Y-%m-%d"))
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    n_week = sum(1 for it in verified
                 if it.get("date") and week_ago <= it["date"] <= today_s)
    n_duties = load_duties()

    kpi_html = render_kpi(len(verified), n_future, n_running, n_juris, len(wx))
    radar_html = (
        render_deck(cal, acts, g)
        + render_dist(verified)
        + render_mod_entries()
    )
    pulse_html = render_pulse(n_future_90, n_future_30, n_running, n_week, len(wx), n_duties)
    feed_html = render_feed(verified)
    geo_js = render_geo(g)

    ok = True
    ok &= replace_block(INDEX, PULSE_S, PULSE_E, pulse_html)
    ok &= replace_block(INDEX, KPI_S, KPI_E, kpi_html)
    ok &= replace_block(INDEX, RADAR_S, RADAR_E, radar_html)
    ok &= replace_block(INDEX, FEED_S, FEED_E, feed_html)
    ok &= replace_block(INDEX, GEO_S, GEO_E, geo_js)
    ok &= replace_block(INDEX, DUTY_LEAD_S, DUTY_LEAD_E, render_duty_lead())
    ok &= replace_block(INDEX, DUTY_MORE_S, DUTY_MORE_E, render_duty_more())
    if ok:
        print(f"  index.html ✓ 速览 + KPI×5 → 最新 {min(10, len(verified))} 条动态（正文前置）"
              f" → 驾驶舱 → 全球 {n_juris} 辖区")
    else:
        print("  index.html 写入失败（未找到标记）")
        return False
    return True


if __name__ == "__main__":
    main()
