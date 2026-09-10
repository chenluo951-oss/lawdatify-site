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
<title>{esc(title)} · lawdatify</title>
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
    duties = data["duties"]
    today = datetime.date.today().isoformat()

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
        ("合规义务", f"{len(duties)} 项"),
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

    # ---------------- 义务视图
    duty_html = "\n".join(
        d for d in (duty_block(x, items, i) for i, x in enumerate(duties)) if d)

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
          f"({len(items)} 条目 / {len(duties)} 义务)")

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
  var tabs=[].slice.call(document.querySelectorAll('.lb-tabs .rd-fchip'));
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
})();
</script>
"""


if __name__ == "__main__":
    main()
