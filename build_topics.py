#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从网页版合规简报中提取结构化条目，按六大领域生成站点内容。

设计要点
--------
1. 解析 news/reports/*.html，按 <h3 class="sub2">（领域）→ <h4 class="sub3">（条目）两级切分。
2. 每条提取：标题 / 日期 / 来源机构 / 官方深链 / 要点 / 朴朴解读。
3. 官方深链一律实测 HTTP 状态码，只保留 200 的条目 —— 这是「零失效链接」的硬闸门。
   校验结果缓存在 sources/link_status.json，增量校验，不重复打站点。
4. 输出时用标记注释替换页面中的区块，手工设计的页面骨架不受影响：
       <!-- FEED:START --> ... <!-- FEED:END -->

用法：python3 build_topics.py [--no-verify]
"""

import os
import re
import json
import html
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "news", "reports")
CACHE = os.path.join(HERE, "sources", "link_status.json")

# 六大领域：键为归一化名，值为展示名 + 主色
DOMAINS = [
    ("数据合规", "#1b4f8a"),
    ("AI合规", "#7c3aed"),
    ("算法合规", "#0f766e"),
    ("平台合规", "#b45309"),
    ("产品合规", "#15803d"),
    ("价格合规", "#be123c"),
]
DOMAIN_KEYS = [d[0] for d in DOMAINS]
DOMAIN_COLOR = dict(DOMAINS)

# 领域中常见的别名 → 归一化
ALIAS = {
    "产品合规（食品安全）": "产品合规",
    "产品合规（食安）": "产品合规",
    "AI 合规": "AI合规",
    "人工智能合规": "AI合规",
    "平台合规（电商）": "平台合规",
}

# 无领域归属时（如「朴朴超市业务专题」下的应对建议）按关键词推断。
# 特异性强的词权重高，避免「数据」这类通用词把什么都吸走。
DOMAIN_KEYWORDS = {
    "产品合规": [("前置仓", 5), ("食品", 5), ("食安", 5), ("生鲜", 4), ("抽检", 4),
                 ("快检", 4), ("餐饮", 4), ("索证", 4), ("批次", 3), ("标签", 3),
                 ("临期", 3), ("冷藏", 3), ("商品", 2)],
    "价格合规": [("划线价", 6), ("促销", 5), ("标价", 5), ("价格", 5), ("收费", 4),
                 ("返利", 4), ("补贴", 3), ("内卷", 3), ("成交", 2)],
    "平台合规": [("入网", 5), ("商户", 5), ("商家", 4), ("入驻", 4), ("平台", 4),
                 ("外卖", 4), ("资质", 3), ("供应商", 3), ("第三方", 2), ("治理", 1)],
    "AI合规": [("大模型", 6), ("人工智能", 6), ("智能体", 6), ("生成式", 5), ("AIGC", 5),
               ("AI", 4), ("深度合成", 4)],
    "算法合规": [("算法", 5), ("推荐", 3), ("个性化", 3), ("推送", 2), ("透明", 2)],
    "数据合规": [("个人信息", 6), ("个保", 6), ("隐私", 5), ("数据", 4), ("SDK", 4),
                 ("出境", 4), ("分类分级", 4), ("重要数据", 4), ("用户权益", 3),
                 ("App", 2), ("网络安全", 2)],
}


def guess_domain(text):
    """按关键词打分推断领域；无命中返回 None。"""
    best, score = None, 0
    for dom, kws in DOMAIN_KEYWORDS.items():
        s = sum(w for kw, w in kws if kw in text)
        if s > score:
            best, score = dom, s
    return best if score >= 4 else None

# 不发布名单：与 gen_briefs.py 保持一致。含编造链接的期次不解析、不进站点。
BLOCKED = ("简报_2026-09-06",)

TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s):
    """去 HTML 标签并把实体还原成纯文本。"""
    s = TAG_RE.sub("", s)
    return html.unescape(s).strip()


def normalize_domain(raw):
    """把 '1. 数据合规' / '2. AI合规 —— 深度分析' 归一化为标准领域名。"""
    t = strip_tags(raw)
    t = re.sub(r"^\s*\d+\s*[.、]\s*", "", t)          # 去掉序号
    t = re.split(r"[—–-]{2,}", t)[0].strip()          # 去掉「—— 深度分析」后缀
    t = ALIAS.get(t, t)
    for k in DOMAIN_KEYS:                              # 兜底：包含匹配
        if k in t:
            return k
    return t


def parse_issue(fname):
    """从文件名解析 (类型, 日期, 版本)。"""
    base = os.path.basename(fname)
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", base)
    date = m.group(1) if m else ""
    kind = "日报"
    for k in ("周报", "月报", "补编", "季报"):
        if k in base:
            kind = k
            break
    ver = "深度分析版" if "深度分析版" in base else "资讯简版"
    return kind, date, ver


def parse_report(path):
    """解析单个报告文件，返回条目列表。"""
    try:
        s = open(path, encoding="utf-8").read()
    except Exception:
        return []

    kind, date, ver = parse_issue(path)
    fname = os.path.basename(path)
    items = []

    # 顺序扫描：h2 开新章节并清空领域，h3.sub2 设定领域，h4.sub3 是条目。
    # 深度版章节顺序是乱的（如「朴朴超市业务专题」排在六大领域之后却无 sub2），
    # 因此必须在遇到 h2 时清空领域，无归属的条目再按关键词推断。
    marks = [(m.start(), m.group(1), m.group(2))
             for m in re.finditer(r'<(h2[^>]*|h3 class="sub2"|h4 class="sub3")>(.*?)</(?:h2|h3|h4)>',
                                  s, re.S)]
    cur = None
    for i, (_pos, tag, inner) in enumerate(marks):
        if tag.startswith("h2"):
            cur = None
            continue
        if tag.startswith("h3"):
            cur = normalize_domain(inner)
            if cur not in DOMAIN_KEYS:
                cur = None
            continue

        # 条目：取本条到下一个标记之间的内容
        end = marks[i + 1][0] if i + 1 < len(marks) else len(s)
        blk = s[_pos:end]

        tm = re.match(r'(?:<span class="mk">.*?</span>)?(.*?)</h4>', inner + "</h4>", re.S)
        if not tm:
            continue
        title = strip_tags(tm.group(1))
        if not title or len(title) < 6:
            continue

        domain = cur
        if domain is None:
            domain = guess_domain(title)       # 专题类条目按标题推断
            if domain is None:
                continue

        # 元信息：日期 + 来源机构
        meta_raw, pub_date, org = "", date, ""
        mm = re.search(r'<p class="meta">(.*?)</p>', blk, re.S)
        if mm:
            meta_raw = strip_tags(mm.group(1))
            parts = [p.strip() for p in re.split(r"[｜|]", meta_raw) if p.strip()]
            if parts:
                dm = re.search(r"(20\d{2}-\d{2}-\d{2})", parts[0])
                pub_date = dm.group(1) if dm else date
            if len(parts) > 1:
                org = parts[-1]

        # 官方深链
        link = ""
        lm = re.search(r'<p class="link"><a href="([^"]+)"', blk)
        if lm:
            link = html.unescape(lm.group(1)).strip()

        # 要点：【要点】所在段落
        points = ""
        pm = re.search(
            r"<p[^>]*>(?:(?!</p>).)*?【要点】(?:(?!</p>).)*?</p>", blk, re.S
        )
        if pm:
            points = strip_tags(pm.group(0))
            points = re.sub(r"^【要点】\s*", "", points)

        # 朴朴解读
        analysis = ""
        am = re.search(r'<blockquote class="ana">(.*?)</blockquote>', blk, re.S)
        if am:
            analysis = strip_tags(am.group(1))
            analysis = re.sub(r"^解读[:：]\s*", "", analysis)

        if not (points or analysis):
            continue

        rm = re.search(r"【风险等级[:：]\s*([^】]+)】", title)
        risk = rm.group(1).strip() if rm else ""
        title = re.sub(r"\s*[　\s]*【风险等级[:：][^】]*】\s*$", "", title).strip()

        items.append(
            {
                "domain": domain,
                "title": title,
                "risk": risk,
                "date": pub_date or date,
                "org": org,
                "meta": meta_raw,
                "url": link,
                "points": points,
                "analysis": analysis,
                "issue": date,
                "kind": kind,
                "ver": ver,
                "file": fname,
            }
        )
    return items


def dedup(items):
    """同一事件在多期/简版深度版重复出现时保留信息量最大的一条。"""
    best = {}
    for it in items:
        # 优先用链接判重，其次用标题
        key = it["url"] or it["title"]
        if key not in best:
            best[key] = it
            continue
        cur = best[key]
        # 打分：解读长度 + 要点长度 + 期次新旧；深度版加权
        def score(x):
            return (
                len(x["analysis"]) * 2
                + len(x["points"])
                + (500 if x["ver"] == "深度分析版" else 0)
                + (x["issue"] > cur["issue"]) * 300
            )

        if score(it) > score(cur):
            best[key] = it
    return list(best.values())


def verify_links(urls, do_verify=True):
    """用 curl 实测链接可达性（Python urllib 在沙箱里会被代理拦截，故用 curl）。"""
    status = {}
    if os.path.exists(CACHE):
        try:
            status = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            status = {}
    if not do_verify:
        return status

    todo = [u for u in urls if u and u not in status]
    if todo:
        print(f"  链接校验：新增 {len(todo)} 条，缓存 {len(urls) - len(todo)} 条")
        for i, u in enumerate(todo, 1):
            try:
                r = subprocess.run(
                    ["curl", "-sL", "-o", "/dev/null", "--max-time", "12",
                     "-A", "Mozilla/5.0", "-w", "%{http_code}", u],
                    capture_output=True, text=True, timeout=20,
                )
                code = (r.stdout or "").strip()[-3:]
                status[u] = code if code.isdigit() else "000"
            except Exception:
                status[u] = "000"
            if i % 10 == 0:
                print(f"    已测 {i}/{len(todo)}")
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(status, open(CACHE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
    return status


# ---------------- 页面生成 ----------------

def esc(s):
    return html.escape(s or "", quote=True)


def snippet(text, n=180):
    """截断成摘要，尽量在句读处断开。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    for sep in ("。", "；", "；", "，", "、"):
        pos = cut.rfind(sep)
        if pos > n * 0.6:
            return cut[: pos + 1]
    return cut + "…"


def render_item_card(it, idx):
    """单条资讯卡片。"""
    color = DOMAIN_COLOR.get(it["domain"], "#1b4f8a")
    url = it["url"]
    link_html = ""
    if url:
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        link_html = (
            f'<a class="src" href="{esc(url)}" target="_blank" rel="noopener">'
            f'{esc(host)} <span class="arw">↗</span></a>'
        )

    ana_html = ""
    if it["analysis"]:
        ana_html = (
            f'<details class="ana"><summary>朴朴视角 · 合规解读</summary>'
            f'<div class="ana-b">{esc(it["analysis"])}</div></details>'
        )

    return f"""<article class="ni" data-domain="{esc(it['domain'])}" data-idx="{idx}">
  <div class="ni-bar" style="background:{color}"></div>
  <div class="ni-body">
    <div class="ni-top">
      <span class="ni-dom" style="color:{color};background:{color}14">{esc(it['domain'])}</span>
      <span class="ni-date">{esc(it['date'])}</span>
      <span class="ni-org">{esc(it['org'])}</span>
      <span class="ni-kind">{esc(it['kind'])}</span>
    </div>
    <h4 class="ni-title">{esc(it['title'])}</h4>
    <p class="ni-pt">{esc(snippet(it['points'], 200))}</p>
    {ana_html}
    <div class="ni-foot">{link_html}</div>
  </div>
</article>"""


def render_news_feed(items):
    """按领域分组的资讯流 + 筛选器。"""
    by = {d: [] for d in DOMAIN_KEYS}
    for it in items:
        by.setdefault(it["domain"], []).append(it)
    for d in by:
        by[d].sort(key=lambda x: (x["date"], x["issue"]), reverse=True)

    tabs = ['<button class="ftab active" data-f="all">全部 <em>%d</em></button>' % len(items)]
    for d in DOMAIN_KEYS:
        if by.get(d):
            tabs.append(f'<button class="ftab" data-f="{esc(d)}">{esc(d)} <em>{len(by[d])}</em></button>')

    blocks = []
    idx = 0
    for d in DOMAIN_KEYS:
        lst = by.get(d) or []
        if not lst:
            continue
        cards = []
        for it in lst:
            cards.append(render_item_card(it, idx))
            idx += 1
        blocks.append(
            f'<section class="fgroup" id="g-{esc(d)}" data-g="{esc(d)}">'
            f'<div class="fgroup-h"><span class="dot" style="background:{DOMAIN_COLOR[d]}"></span>'
            f'<h3>{esc(d)}</h3><span class="cnt">{len(lst)} 条</span></div>'
            f'<div class="nilist">{"".join(cards)}</div></section>'
        )

    latest = max((it["date"] for it in items), default="")

    return f"""<div class="feedbar">
  <div class="fb-stats">
    <div class="st"><div class="n">{len(items)}</div><div class="l">合规动态</div></div>
    <div class="st"><div class="n">{len([d for d in DOMAIN_KEYS if by.get(d)])}</div><div class="l">覆盖领域</div></div>
    <div class="st"><div class="n">{esc(latest)}</div><div class="l">更新至</div></div>
  </div>
  <div class="fb-tools">
    <input id="q" type="search" placeholder="按关键词 / 机构过滤…" aria-label="过滤">
    <div class="ftabs">{"".join(tabs)}</div>
  </div>
</div>
<div id="feed">{"".join(blocks)}</div>
<div id="empty" class="empty" hidden>没有匹配的动态，换个关键词试试。</div>
<script>
(function(){{
  var q=document.getElementById('q'), feed=document.getElementById('feed'),
      empty=document.getElementById('empty'), cur='all';
  function apply(){{
    var kw=(q.value||'').trim().toLowerCase(), shown=0;
    var gs=feed.querySelectorAll('.fgroup');
    for(var i=0;i<gs.length;i++){{
      var g=gs[i], okG=(cur==='all'||g.dataset.g===cur), n=0;
      var ns=g.querySelectorAll('.ni');
      for(var j=0;j<ns.length;j++){{
        var el=ns[j], t=el.innerText.toLowerCase();
        var ok=okG&&(!kw||t.indexOf(kw)>-1);
        el.hidden=!ok; if(ok){{n++;shown++;}}
      }}
      g.hidden=(n===0);
    }}
    empty.hidden=(shown>0);
  }}
  var ts=document.querySelectorAll('.ftab');
  for(var i=0;i<ts.length;i++){{
    ts[i].addEventListener('click',function(){{
      for(var j=0;j<ts.length;j++) ts[j].classList.remove('active');
      this.classList.add('active'); cur=this.dataset.f; apply();
    }});
  }}
  if(q) q.addEventListener('input',apply);
}})();
</script>"""


RISK_CLASS = {"高": "r-hi", "中高": "r-mh", "中": "r-md", "低": "r-lo"}


def render_kb_cards(news_items, actions):
    """知识库：按领域沉淀「合规行动要点」（来自简报应对建议）+ 动态入口。"""
    acts = {d: [] for d in DOMAIN_KEYS}
    for it in actions:
        if it["analysis"] or it["points"]:
            acts.setdefault(it["domain"], []).append(it)
    for d in acts:
        # 高风险的排前面
        order = {"高": 0, "中高": 1, "中": 2, "低": 3}
        acts[d].sort(key=lambda x: (order.get(x.get("risk"), 9), x["date"]), reverse=False)
        acts[d].sort(key=lambda x: order.get(x.get("risk"), 9))

    n_news = {d: sum(1 for x in news_items if x["domain"] == d) for d in DOMAIN_KEYS}

    cards = []
    for d in DOMAIN_KEYS:
        color = DOMAIN_COLOR[d]
        lst = acts.get(d) or []
        if not lst:
            cards.append(f"""<div class="kb-card empty-c">
  <div class="kb-h"><span class="dot" style="background:{color}"></span><h3>{esc(d)}</h3></div>
  <p class="kb-p">暂无行动要点沉淀，后续简报产出应对建议后自动累积。</p>
</div>""")
            continue
        lis = []
        for it in lst[:4]:
            body = it["analysis"] or it["points"]
            risk = it.get("risk", "")
            rb = (f'<span class="rk {RISK_CLASS.get(risk, "r-md")}">{esc(risk)}</span>'
                  if risk else "")
            lis.append(
                f'<li><div class="kb-t">{rb}<b>{esc(it["title"])}</b></div>'
                f'<div class="kb-a">{esc(snippet(body, 150))}</div>'
                f'<div class="kb-m">{esc(it["date"])} · 源自{esc(it["kind"])}</div></li>'
            )
        more = ""
        if n_news.get(d):
            more = (f'<div class="kb-more">'
                    f'<a href="../news/index.html#g-{esc(d)}">该领域 {n_news[d]} 条监管动态 →</a></div>')
        cards.append(f"""<div class="kb-card">
  <div class="kb-h"><span class="dot" style="background:{color}"></span><h3>{esc(d)}</h3>
    <span class="kb-n">{len(lst)} 项要点</span></div>
  <ul class="kb-list">{"".join(lis)}</ul>
  {more}
</div>""")
    return f'<div class="kb-grid">{"".join(cards)}</div>'


def render_home_latest(items, n=6):
    """首页最新动态：跨领域取最新 n 条。"""
    lst = sorted(items, key=lambda x: (x["date"], x["issue"]), reverse=True)[:n]
    rows = []
    for it in lst:
        color = DOMAIN_COLOR.get(it["domain"], "#1b4f8a")
        rows.append(f"""<a class="hl" href="news/index.html">
  <span class="hl-d" style="background:{color}">{esc(it['domain'])}</span>
  <span class="hl-t">{esc(it['title'])}</span>
  <span class="hl-m">{esc(it['date'])}</span>
</a>""")
    return f'<div class="hlist">{"".join(rows)}</div>'


def replace_block(path, content):
    """替换 <!-- FEED:START --> … <!-- FEED:END --> 之间的内容。"""
    if not os.path.exists(path):
        print(f"  ! 缺少文件 {path}")
        return False
    s = open(path, encoding="utf-8").read()
    pat = re.compile(r"(<!-- FEED:START -->)(.*?)(<!-- FEED:END -->)", re.S)
    if not pat.search(s):
        print(f"  ! {os.path.basename(path)} 未找到 FEED 标记，跳过")
        return False
    s = pat.sub(lambda m: m.group(1) + "\n" + content + "\n" + m.group(3), s)
    open(path, "w", encoding="utf-8").write(s)
    return True


def main():
    do_verify = "--no-verify" not in sys.argv
    if not os.path.isdir(REPORTS):
        print("未找到 news/reports")
        return

    files = sorted(
        f for f in os.listdir(REPORTS)
        if f.endswith(".html") and not any(b in f for b in BLOCKED)
    )
    print(f"解析 {len(files)} 份网页版简报…")
    items = []
    for f in files:
        got = parse_report(os.path.join(REPORTS, f))
        print(f"  {f[:40]:<42} {len(got)} 条")
        items += got
    print(f"解析合计 {len(items)} 条")

    items = dedup(items)
    print(f"去重后 {len(items)} 条")

    # 链接校验闸门：分三类
    #   verified —— 有官方深链且实测 200，进资讯流（可溯源，满足对外分享要求）
    #   internal —— 无外链的内部行动建议，进知识库（不对外引用，无需外链）
    #   dead     —— 有链接但实测失效，丢弃（绝不进站点）
    urls = sorted({it["url"] for it in items if it["url"]})
    status = verify_links(urls, do_verify)
    # 200 = 正常；403/429 = 对方 WAF 拦脚本 UA，浏览器可正常打开，视为有效；
    # 其余（404 / 000 连接失败 / 其他）视为失效，绝不进站点。
    OK_CODES = {"200", "403", "429"}
    verified, internal, dead = [], [], []
    for it in items:
        u = it["url"]
        if not u:
            internal.append(it)
        elif status.get(u, "?") in OK_CODES:
            verified.append(it)
        else:
            dead.append((it, status.get(u, "?")))
    if dead:
        print(f"链接闸门剔除 {len(dead)} 条（有链接但失效）：")
        for it, st in dead[:12]:
            print(f"    [{st}] {it['title'][:38]}")
    print(f"资讯流 {len(verified)} 条（深链实测 200）｜知识库素材 {len(internal)} 条（内部行动建议）")

    # 生成各页面
    print("写入页面…")
    if replace_block(os.path.join(HERE, "news", "index.html"), render_news_feed(verified)):
        print("  news/index.html ✓")
    if replace_block(os.path.join(HERE, "kb", "index.html"), render_kb_cards(verified, internal)):
        print("  kb/index.html ✓")
    if replace_block(os.path.join(HERE, "index.html"), render_home_latest(verified)):
        print("  index.html ✓")

    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "news_items": len(verified),
        "kb_actions": len(internal),
        "dead_links": len(dead),
        "by_domain": {d: sum(1 for x in verified if x["domain"] == d) for d in DOMAIN_KEYS},
    }
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
