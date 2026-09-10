#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规标准知识库」页 kb/standards.html

数据源：sources/standards/library.json（由 build_library_data.py 生成）
视图一  资料库：按专题 / 层级 / 时效性 三维筛选 + 关键词检索
视图二  合规义务：以 26 项合规义务为主干，反查每一义务对应的法律法规与标准

幂等：输出后自动调用 unify_chrome + inject_meta 恢复页头页脚与分享元数据。
"""
import os, re, json, html, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "standards", "library.json")
DRAFTS = os.path.join(HERE, "sources", "library", "drafts.json")
# 合规义务主干（主题大类 → 场景 → 具体义务 三级），与条目库分开维护
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
              "征求意见中": "b-amber"}
LEVEL_CLS = {"法律": "b-purple", "行政法规": "b-purple", "部门规章": "b-blue",
             "规范性文件": "b-amber", "强制性国家标准": "b-red",
             "推荐性国家标准": "b-green", "国家标准化指导性技术文件": "b-ghost",
             "指引/指南": "b-ghost"}


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


def build_kb_index(items, duties, drafts, soon):
    """合规知识库总览：定位三大件入口 + 时效提醒 + 模块边界说明。

    与 build_topics.py 的分工：动态类内容（监管动态、应对建议）归「合规资讯」，
    这里只放长效知识——法规标准原文、义务清单、立法草案。
    """
    today = datetime.date.today().isoformat()
    n_std = sum(1 for x in items if x.get("kind") == "标准")
    n_law = len(items) - n_std
    n_local = sum(1 for x in items if x.get("local"))
    n_sooner = len(soon)

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

    # 义务主干统计（重构后为 大类 → 场景 → 义务 三级）
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
  <div class="lb-split">
    <a class="dcard lb-entry" href="standards.html" style="--dc:#0f7b6c">
      <b>📚 合规标准知识库</b>
      <span>{len(items)} 条目：法律 {n_law} 件 / 标准 {n_std} 项，含国家标准、行业与团体标准、指引指南。
      标注效力状态（现行有效 / 即将实施 / 已废止）与发布实施日期。</span>
      <span class="more">进入标准知识库 →</span>
    </a>
    <a class="dcard lb-entry" href="standards.html#pane-duty" style="--dc:#1b4f8a">
      <b>🎯 合规义务主干</b>
      <span>{duty_desc}。按 App 合规、广告合规、AI 合规、平台治理等主题大类组织，
      每项义务细化到可落地要求并反查依据条款。</span>
      <span class="more">查看义务清单 →</span>
    </a>
    <a class="dcard lb-entry" href="standards.html#pane-drafts" style="--dc:#b45309">
      <b>📌 立法草案跟踪</b>
      <span>{len(drafts)} 项在途立法与征求意见，标注起止日期与剩余天数，链接到官方征求意见通知页。</span>
      <span class="more">查看草案 →</span>
    </a>
  </div>

  <div class="section-title"><span class="bar"></span>时效提醒</div>
  <div class="lb-cols">
    <div class="lb-col">
      <h3>即将实施（{n_sooner} 项）</h3>
      {soon_html}
    </div>
    <div class="lb-col">
      <h3>征求意见截止</h3>
      {draft_html}
    </div>
  </div>

  <div class="section-title"><span class="bar"></span>三个模块怎么分</div>
  <div class="notice">
    本站内容按<b>时间属性</b>划分，避免同一条信息在多个模块重复出现：
  </div>
  <div class="lb-bound">
    <div class="lb-bd">
      <div class="lb-bd-h"><b>监管雷达</b><span class="lb-tag t-future">未来 / 进行中</span></div>
      <p>回答「何时生效、何地监管、何种行动」：立法日程与施行倒计时、监管专项行动与执法态势、全球监管地图。</p>
      <a href="../radar/index.html">进入监管雷达 →</a>
    </div>
    <div class="lb-bd">
      <div class="lb-bd-h"><b>合规资讯</b><span class="lb-tag t-daily">每日更新</span></div>
      <p>回答「已经发生了什么、我们该做什么」：六大领域监管动态（逐条附官方深链）、
      简报归档、以及从简报沉淀的应对建议。</p>
      <a href="../news/index.html">进入合规资讯 →</a>
    </div>
    <div class="lb-bd on">
      <div class="lb-bd-h"><b>合规知识库</b><span class="lb-tag t-long">长期稳定</span></div>
      <p>回答「规则本身是什么」：法规与标准原文、按主题拆解的合规义务清单、在途立法草案。
      内容不随日更变化。</p>
      <span class="lb-here">当前位置</span>
    </div>
  </div>
"""
    out = page(
        "合规知识库",
        "合规标准知识库、按主题拆解的合规义务清单与在途立法草案跟踪——长效合规知识资产。",
        "合规知识库",
        "合规知识库",
        "长效知识资产：法规与标准原文、按主题拆解的合规义务、在途立法草案。",
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
        lis.append(
            f'<div class="art-item">'
            f'<div class="art-hd"><span class="art-src">{esc(a.get("src") or "")}</span>'
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


def render_duty_tree(cats, items):
    """合规义务主干：主题大类 → 场景 → 具体义务 三级。"""
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
                    ref_html = '<div class="lb-refs">' + "".join(
                        f'<a href="{esc(x["url"])}" target="_blank" rel="noopener" '
                        f'title="{esc(x["name"])}">{esc(x.get("code") or x["name"])}</a>'
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

    return chips_html + ('<div class="lb-search duty-search">'
                         '<input id="dutyQ" type="search" placeholder="搜索义务关键词，如 摇一摇、单独同意、划线价、温湿度…" autocomplete="off">'
                         '<span id="dutyCount" class="lb-count"></span></div>'
                         ) + '<div class="lb-tree">' + "".join(blocks) + "</div>"


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
    items = data["items"]
    today = datetime.date.today().isoformat()

    # 合规义务主干（三级结构）；回退到条目库内的旧式 duties
    if os.path.exists(DUTY_SRC):
        duties = json.load(open(DUTY_SRC, encoding="utf-8"))
    else:
        duties = {"categories": []}
    cats = duties.get("categories", [])
    n_duty = sum(len(d.get("duties", [])) for c in cats for d in c.get("scenes", []))

    # 时效分区
    soon = [x for x in items if x.get("status") == "即将实施" and (x.get("impl") or "") >= today]
    soon.sort(key=lambda x: x.get("impl") or "9999")
    dead = [x for x in items if x.get("status") == "已废止"]

    n_std = sum(1 for x in items if x.get("kind") == "标准")
    n_law = len(items) - n_std
    n_local = sum(1 for x in items if x.get("local"))
    topics = data["meta"]["topics"]

    # 草案跟踪
    drafts = []
    if os.path.exists(DRAFTS):
        try:
            drafts = json.load(open(DRAFTS, encoding="utf-8"))["items"]
        except Exception:
            drafts = []

    # ---------------- 统计条
    stats = [(k, v) for k, v in [
        ("收录条目", len(items)),
        ("标准", n_std),
        ("法律法规", n_law),
        ("本机原文", n_local),
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

    def bar(fid, opts, label):
        return ('<div class="rd-filters"><span class="rd-flabel">%s</span>%s</div>' % (
            esc(label), "".join(
                f'<button class="rd-fchip{" on" if i == 0 else ""}" data-fg="{fid}" '
                f'data-fv="{esc(v)}">{esc(t)}</button>' for i, (v, t) in enumerate(opts))))

    search = ('<div class="lb-search"><input id="lbQ" type="search" '
              'placeholder="搜索标准号 / 名称 / 发布机构，如 GB/T 35273、个人信息、App" '
              'autocomplete="off"><span id="lbCount" class="lb-count"></span></div>')

    cards = "\n".join(item_card(x, i) for i, x in enumerate(items))

    # ---------------- 义务视图（主题大类 → 场景 → 具体义务）
    duty_html = render_duty_tree(cats, items)

    # ---------------- 草案跟踪视图
    draft_html = "\n".join(draft_card(d) for d in drafts)
    if not draft_html:
        draft_html = '<p class="rd-note">暂无在途草案记录。</p>'

    body = "\n".join([
        stat_html,
        board,
        '<div class="lb-tabs">'
        '<button class="rd-fchip on" data-tab="lib">资料库</button>'
        '<button class="rd-fchip" data-tab="draft">草案跟踪<i class="lb-dot"></i></button>'
        '<button class="rd-fchip" data-tab="duty">合规义务主干</button>'
        "</div>",
        '<section class="lb-pane" id="pane-lib">',
        search,
        bar("topic", topic_opts, "专题"),
        bar("level", level_opts, "层级"),
        bar("status", stat_opts, "时效性"),
        f'<div class="rd-list" id="lbList">{cards}</div>',
        "</section>",
        '<section class="lb-pane" id="pane-draft" hidden>',
        '<p class="rd-note">跟踪<b>尚未生效</b>的立法与标准制定动态：国家标准征求意见、部门规章草案、'
        '以及长期悬置未发布的规范性文件。数据来自全国网络安全标准化技术委员会与中央网信办官网，'
        '截止日期与剩余天数按页面打开当天计算。<b>草案不产生合规义务</b>，但往往预示监管方向。</p>',
        f'<div class="rd-list" id="draftList">{draft_html}</div>',
        "</section>",
        '<section class="lb-pane" id="pane-duty" hidden>',
        '<p class="rd-note">以<b>合规义务</b>为主线反查依据：每一项义务下列出可直接引用的法律法规与标准。'
        '义务清单源自个人信息保护合规审计底稿与网数合规自查清单，并按监管文件要点整理。</p>',
        f'<div class="lb-duties">{duty_html}</div>',
        "</section>",
        '<p class="rd-note">标准数据取自<b>国家标准全文公开系统</b>（发布/实施日期与现行状态以官方为准）；'
        '法律法规与规范性文件均附发布机构官网原文深链。'
        '本页用于合规检索与自查参考，<b>不构成法律意见</b>；引用前请点开原文核对现行有效版本。</p>',
        LIB_JS,
    ])

    out = page(
        "合规标准知识库",
        "个人信息保护、数据安全、网络安全、算法与 AI、移动应用合规的国家标准、法律法规与指引指南汇总，"
        "标注效力状态、发布与实施日期，并以合规义务为主线组织。",
        '<a href="index.html">合规知识库</a> / 标准知识库',
        "合规标准知识库",
        "把散落在各处的标准与法规收在一处：哪部现行、哪部即将实施、哪部已废止，"
        "以及每一项合规义务该引用哪些依据。",
        body,
    )

    dst = os.path.join(HERE, "kb", "standards.html")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8").write(out)
    print(f"  kb/standards.html  {len(out)} B  ✓  "
          f"({len(items)} 条目)")

    build_kb_index(items, duties, drafts, soon)

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


LIB_JS = """
<script>
(function(){
  var tabs=[].slice.call(document.querySelectorAll('.lb-tabs > .rd-fchip'));
  var panes=[].slice.call(document.querySelectorAll('.lb-pane'));
  tabs.forEach(function(b){
    b.addEventListener('click',function(){
      tabs.forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      var want='pane-'+b.getAttribute('data-tab');
      panes.forEach(function(p){ p.hidden = (p.id!==want); });
      window.scrollTo({top:0,behavior:'smooth'});
    });
  });

  var cards=[].slice.call(document.querySelectorAll('#lbList .lb-item'));
  var q=document.getElementById('lbQ'), cnt=document.getElementById('lbCount');
  var sel={topic:'ALL',level:'ALL',status:'ALL'};

  function apply(){
    var kw=(q&&q.value||'').trim().toLowerCase();
    var n=0;
    cards.forEach(function(c){
      var ok=true;
      for(var k in sel){ if(sel[k]!=='ALL' && c.getAttribute('data-'+k)!==sel[k]) ok=false; }
      if(ok && kw && (c.getAttribute('data-text')||'').indexOf(kw)<0) ok=false;
      c.style.display=ok?'':'none'; if(ok) n++;
    });
    if(cnt) cnt.textContent='共 '+n+' 条';
  }

  [].slice.call(document.querySelectorAll('#pane-lib .rd-fchip')).forEach(function(b){
    b.addEventListener('click',function(){
      var g=b.getAttribute('data-fg'); if(!g) return;
      [].slice.call(document.querySelectorAll('#pane-lib .rd-fchip[data-fg="'+g+'"]'))
        .forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      sel[g]=b.getAttribute('data-fv'); apply();
    });
  });
  if(q) q.addEventListener('input',apply);
  apply();

  // ---------- 合规义务主干：主题大类切换 + 义务全文搜索 ----------
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
  dchips.forEach(function(b){
    b.addEventListener('click',function(){
      dchips.forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      curCat=b.getAttribute('data-dcat'); applyDuty();
    });
  });
  if(dq) dq.addEventListener('input',applyDuty);
  applyDuty();

  // ---------- 深链定位：从搜索结果跳转 #d-xxx 时展开父级并高亮 ----------
  function focusDuty(){
    var h=(location.hash||'').replace(/^#/,'');
    if(!/^d-/.test(h)) return;
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
