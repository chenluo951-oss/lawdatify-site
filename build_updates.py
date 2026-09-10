#!/usr/bin/env python3
"""生成「今日更新」页：回答「今天这个网站更新了什么」。

为什么需要它：站点数据分散在 library.json（法规标准）、calendar.json（立法日历）、
actions.json（监管动向）、drafts.json（草案跟踪）四个源里，读者无从知道「今天变了什么」。
本脚本用**快照 diff** 的方式把增量算出来，而不是靠人工维护更新日志：

    上次快照 ──diff──> 现在   ⇒   新增 / 状态变更 / 失效 三张清单

快照存 sources/updates/snapshot.json 并入仓，因此每次重建都能拿到真实增量。
首次运行时快照来自 git HEAD 里的历史版本（git show HEAD:<path>），
这样第一次就能 diff 出"本次提交新增的条目"，而不是空基线。

写入 updates/index.html，并向全站注入导航/页脚/社交元数据。
"""

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "sources", "updates")
SNAP = os.path.join(SNAP_DIR, "snapshot.json")

LIB = "sources/standards/library.json"
CAL = "sources/radar/calendar.json"
ACT = "sources/radar/actions.json"
DRAFT = "sources/library/drafts.json"

TODAY = date.today()
TODAY_S = TODAY.isoformat()


# ------------------------------------------------------------------ 基础工具
def load(rel):
    p = os.path.join(HERE, rel)
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def key_of(it):
    """条目唯一键。

    注意：法规类条目的 code 字段存的是**效力层级**（如「部门规章」「法律」），
    多部法规共用同一个 code，只按 code 取键会大面积冲突（实测：只按 code 时
    新增条目会被误判成"变更"）。因此必须用 code + name 复合键。
    """
    return f'{(it.get("code") or "").strip()}::{(it.get("name") or "").strip()}'


def fingerprint(it):
    """用于判断"是否发生变化"的指纹：状态 / 实施日期 / 链接 / 要点。"""
    return "|".join([
        (it.get("status") or ""),
        (it.get("impl") or ""),
        (it.get("url") or ""),
        (it.get("point") or "")[:200],
    ])


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"(\d{4})[-/年]?(\d{1,2})?[-/月]?(\d{1,2})?", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1))
    except ValueError:
        return None


def days_between(d):
    return (d - TODAY).days if d else None


def git(*args):
    try:
        return subprocess.run(["git"] + list(args), cwd=HERE,
                              capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


# ------------------------------------------------------------------ 快照
def load_snapshot():
    if os.path.exists(SNAP):
        try:
            return json.load(open(SNAP, encoding="utf-8"))
        except Exception:
            pass
    return None


def seed_from_git():
    """首次运行：用 git HEAD 里的历史版本建基线，这样第一次就有真实增量。"""
    raw = git("show", f"HEAD:{LIB}")
    if not raw.strip():
        return None
    try:
        old = json.loads(raw)
    except Exception:
        return None
    return build_snap(old.get("items", []))


def build_snap(items):
    return {
        "date": TODAY_S,
        "items": {key_of(i): fingerprint(i) for i in items if key_of(i)},
        "meta": {key_of(i): {
            "name": i.get("name", ""), "level": i.get("level", ""),
            "topic": i.get("topic", ""), "status": i.get("status", ""),
            "impl": i.get("impl", ""), "pub": i.get("pub", ""),
            "url": i.get("url", ""),
        } for i in items if key_of(i)},
    }


def save_snapshot(items):
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = build_snap(items)
    json.dump(snap, open(SNAP, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return snap


# ------------------------------------------------------------------ 增量计算
def diff_items(cur_items, snap):
    if not snap:
        return [], [], []
    old_fp = snap.get("items", {})
    old_meta = snap.get("meta", {})
    added, changed, removed = [], [], []
    cur_keys = set()
    for it in cur_items:
        k = key_of(it)
        if not k:
            continue
        cur_keys.add(k)
        if k not in old_fp:
            added.append(it)
        elif old_fp[k] != fingerprint(it):
            changed.append((old_meta.get(k, {}), it))
    for k in old_fp:
        if k not in cur_keys:
            removed.append(old_meta.get(k, {"name": k}))
    return added, changed, removed


# ------------------------------------------------------------------ 渲染
CHIP = {
    "法律": "chip-law", "行政法规": "chip-law", "部门规章": "chip-law",
    "规范性文件": "chip-doc",
    "强制性国家标准": "chip-std", "推荐性国家标准": "chip-std",
    "国家标准化指导性技术文件": "chip-std",
    "行业标准": "chip-std", "团体标准": "chip-std",
}


def item_row(it, badge=""):
    name = esc(it.get("name") or "")
    code = esc(it.get("code") or "")
    url = it.get("url") or ""
    title = f'<a href="{esc(url)}" target="_blank" rel="noopener">{name}</a>' if url else name
    lvl = it.get("level") or ""
    cls = CHIP.get(lvl, "chip-doc")
    impl = it.get("impl") or ""
    chips = [f'<span class="chip {cls}">{esc(lvl)}</span>' if lvl else "",
             f'<span class="chip">{esc(it.get("topic") or "")}</span>' if it.get("topic") else "",
             f'<span class="chip chip-warn">施行 {esc(impl)}</span>' if impl else "",
             badge]
    return f"""<div class="up-item">
  <div class="up-title">{title}</div>
  <div class="up-chips">{''.join(c for c in chips if c)}</div>
  {f'<p class="up-point">{esc(it.get("point") or "")}</p>' if it.get("point") else ''}
  {f'<p class="up-note">{esc(it.get("note") or "")}</p>' if it.get("note") else ''}
</div>"""


def stat_card(n, label, sub="", tone=""):
    return (f'<div class="stat{"  " + tone if tone else ""}">'
            f'<div class="stat-n">{n}</div>'
            f'<div class="stat-l">{label}</div>'
            f'{f"<div class=stat-s>{sub}</div>" if sub else ""}</div>')


def countdown(d):
    n = days_between(d)
    if n is None:
        return ""
    if n < 0:
        return f'<span class="chip chip-done">已生效</span>'
    if n == 0:
        return '<span class="chip chip-today">今日生效</span>'
    if n <= 30:
        return f'<span class="chip chip-soon">{n} 天后</span>'
    if n <= 180:
        return f'<span class="chip">{n} 天后</span>'
    return f'<span class="chip chip-dim">{n} 天后</span>'


def main():
    lib = load(LIB) or {}
    items = lib.get("items", [])
    cal = (load(CAL) or {}).get("items", [])
    act = (load(ACT) or {}).get("items", [])
    draft_raw = load(DRAFT) or {}
    drafts = draft_raw.get("items", []) if isinstance(draft_raw, dict) else draft_raw

    snap = load_snapshot()
    if not snap:
        snap = seed_from_git()
        src = "git HEAD"
    else:
        src = snap.get("date", "?")
    added, changed, removed = diff_items(items, snap)

    # --- 生效时间轴 ---
    def soon(days_lo, days_hi):
        out = []
        for it in items:
            d = parse_date(it.get("impl"))
            if not d:
                continue
            n = days_between(d)
            if n is None:
                continue
            if days_lo <= n <= days_hi:
                out.append((d, n, it))
        return sorted(out, key=lambda x: x[0])

    today_eff = soon(0, 0)
    soon30 = soon(1, 30)
    soon180 = soon(31, 180)

    # --- 立法日历 ---
    def cal_in(days_hi):
        out = []
        for e in cal:
            d = parse_date(e.get("date"))
            if not d:
                continue
            n = days_between(d)
            if n is not None and 0 <= n <= days_hi:
                out.append((d, n, e))
        return sorted(out, key=lambda x: x[0])

    cal7 = cal_in(7)

    # --- 草案截止 ---
    dl = []
    for dft in drafts:
        for f in ("deadline", "end", "due", "截止", "comment_deadline"):
            v = dft.get(f)
            dt = parse_date(v)
            if dt:
                n = days_between(dt)
                if n is not None and n >= 0:
                    dl.append((dt, n, dft))
                break
    dl = sorted(dl, key=lambda x: x[0])[:10]

    # --- 进行中的监管行动 ---
    ongoing = [a for a in act if (a.get("status") or "") in ("进行中", "持续推进", "常态化")]

    # --- 站点本次变更文件 ---
    changed_files = []
    for line in git("status", "--porcelain").splitlines():
        if len(line) > 3:
            p = line[3:].strip().strip('"')
            if p.endswith(".html"):
                changed_files.append(p)

    # ---------------------------------------------------------- 组装 HTML
    parts = []
    parts.append(f"""<div class="up-hero">
  <div class="up-date">{TODAY_S}</div>
  <div class="up-hero-t">今日更新</div>
  <p class="up-hero-d">本页由快照比对自动生成：以上次构建留存的条目基线（{esc(src)}）与当前条目库逐条比对，
  算出本次新增、状态变更与失效条目，再叠加生效倒计时、立法日历与草案截止，回答「今天变了什么」。</p>
</div>""")

    # 统计卡
    parts.append('<div class="stat-grid">')
    parts.append(stat_card(len(added), "新增法规 / 标准", "本次相对基线新增", "tone-new"))
    parts.append(stat_card(len(changed), "状态 / 内容变更", "施行日期或要点变化", "tone-chg"))
    parts.append(stat_card(len(today_eff), "今日生效", f"另有 {len(soon30)} 项 30 日内生效", "tone-eff"))
    parts.append(stat_card(len(cal7), "7 日内立法节点", f"{len(ongoing)} 项监管行动进行中", "tone-cal"))
    parts.append(stat_card(len(dl), "草案征求意见", "按截止日排序", "tone-drt"))
    parts.append("</div>")

    # 1. 新增
    parts.append('<div class="section-title"><span class="bar"></span>本次新增条目</div>')
    if added:
        for it in added:
            parts.append(item_row(it, '<span class="chip chip-new">NEW</span>'))
    else:
        parts.append('<p class="lead">本次无新增条目。</p>')

    # 2. 变更
    if changed:
        parts.append('<div class="section-title"><span class="bar"></span>状态 / 内容变更</div>')
        for old, new in changed:
            ob = (old.get("status") or "—")
            nb = (new.get("status") or "—")
            oi = (old.get("impl") or "—")
            ni = (new.get("impl") or "—")
            delta = []
            if ob != nb:
                delta.append(f"状态 {esc(ob)} → <b>{esc(nb)}</b>")
            if oi != ni:
                delta.append(f"施行 {esc(oi)} → <b>{esc(ni)}</b>")
            if not delta:
                delta.append("要点更新")
            nm = esc(new.get("name") or "")
            url = new.get("url") or ""
            t = f'<a href="{esc(url)}" target="_blank" rel="noopener">{nm}</a>' if url else nm
            parts.append(f'<div class="up-item"><div class="up-title">{t}</div>'
                         f'<div class="up-chips"><span class="chip chip-chg">{" · ".join(delta)}</span></div></div>')

    if removed:
        parts.append('<div class="section-title"><span class="bar"></span>下线条目</div>')
        for r in removed:
            parts.append(f'<div class="up-item"><div class="up-title">{esc(r.get("name") or "")}</div>'
                         f'<div class="up-chips"><span class="chip chip-dim">已从条目库移除</span></div></div>')

    # 3. 生效倒计时
    parts.append('<div class="section-title"><span class="bar"></span>生效倒计时</div>')
    if today_eff or soon30 or soon180:
        parts.append('<table class="up-table"><thead><tr>'
                     '<th style="width:110px">实施日期</th><th style="width:88px">倒计时</th>'
                     '<th>法规 / 标准</th><th style="width:120px">效力层级</th></tr></thead><tbody>')
        for d, n, it in (today_eff + soon30 + soon180):
            nm = esc(it.get("name") or "")
            url = it.get("url") or ""
            t = f'<a href="{esc(url)}" target="_blank" rel="noopener">{nm}</a>' if url else nm
            cd = esc(it.get("code") or "")
            # 法规类条目的 code 是效力层级（"部门规章"），只在含数字时才当作标准号展示
            show = " <span class=up-code>" + cd + "</span>" if re.search(r"\d", cd) and cd != nm else ""
            parts.append(f'<tr><td>{d.isoformat()}</td><td>{countdown(d)}</td>'
                         f'<td>{t}{show}</td>'
                         f'<td>{esc(it.get("level") or "")}</td></tr>')
        parts.append("</tbody></table>")
    else:
        parts.append('<p class="lead">未来 180 天内无新增生效节点。</p>')

    # 4. 立法日历
    if cal7:
        parts.append('<div class="section-title"><span class="bar"></span>7 日内立法与监管节点</div>')
        parts.append('<table class="up-table"><thead><tr><th style="width:110px">日期</th>'
                     '<th style="width:96px">类型</th><th>事项</th><th style="width:150px">发布机构</th>'
                     '</tr></thead><tbody>')
        for d, n, e in cal7:
            nm = esc(e.get("title") or "")
            url = e.get("url") or ""
            t = f'<a href="{esc(url)}" target="_blank" rel="noopener">{nm}</a>' if url else nm
            src_tag = ' <span class="chip chip-dim">评述</span>' if e.get("src") == "analysis" else ""
            parts.append(f'<tr><td>{d.isoformat()}</td><td>{esc(e.get("type") or "")}</td>'
                         f'<td>{t}{src_tag}</td><td>{esc(e.get("issuer") or "")}</td></tr>')
        parts.append("</tbody></table>")

    # 5. 草案
    if dl:
        parts.append('<div class="section-title"><span class="bar"></span>征求意见截止倒计时</div>')
        parts.append('<table class="up-table"><thead><tr><th style="width:110px">截止</th>'
                     '<th style="width:88px">剩余</th><th>草案名称</th></tr></thead><tbody>')
        for d, n, dft in dl:
            nm = esc(dft.get("name") or dft.get("title") or "")
            url = dft.get("url") or ""
            t = f'<a href="{esc(url)}" target="_blank" rel="noopener">{nm}</a>' if url else nm
            parts.append(f'<tr><td>{d.isoformat()}</td><td>{countdown(d)}</td><td>{t}</td></tr>')
        parts.append("</tbody></table>")

    # 6. 进行中的监管行动
    if ongoing:
        parts.append('<div class="section-title"><span class="bar"></span>进行中的监管行动</div>')
        for a in ongoing:
            nm = esc(a.get("name") or "")
            url = a.get("url") or ""
            t = f'<a href="{esc(url)}" target="_blank" rel="noopener">{nm}</a>' if url else nm
            parts.append(f'<div class="up-item"><div class="up-title">{t}</div>'
                         f'<div class="up-chips">'
                         f'<span class="chip chip-warn">{esc(a.get("status") or "")}</span>'
                         f'<span class="chip">{esc(a.get("issuer") or "")}</span>'
                         f'<span class="chip">{esc(a.get("period") or "")}</span></div>'
                         f'<p class="up-point">{esc(a.get("focus") or "")}</p>'
                         + (f'<p class="up-note">进展：{esc(a.get("progress") or "")}</p>'
                            if a.get("progress") else "") + '</div>')

    # 7. 站点变更
    if changed_files:
        parts.append('<div class="section-title"><span class="bar"></span>本次同步改动的页面</div>')
        parts.append('<div class="up-files">' + "".join(
            f'<code>{esc(f)}</code>' for f in changed_files[:40]) + '</div>')

    body = "\n".join(parts)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>今日更新 · lawdatify</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>

<nav class="topnav"><div class="inner">
  <a class="brand" href="../index.html">law<span>datify</span></a>
  <div class="navlinks">
    <a href="../index.html">首页</a>
    <a href="../radar/index.html">监管雷达</a>
    <a href="../news/index.html">合规资讯</a>
    <a href="../analysis/index.html">法律分析</a>
    <a href="../kb/index.html">合规知识库</a>
    <a href="../about.html">关于</a>
  </div>
</div></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / 今日更新</div>
  <h1>今日更新</h1>
  <p>法规标准增量、生效倒计时、立法节点与草案截止，一屏掌握今天变了什么。</p>
</div></div>

<div class="wrap">
{body}
</div>

<footer><div class="inner">
  <div class="foot-brand">law<span>datify</span> · 法律合规主站</div>
  <div class="foot-desc">由法务团队维护 · 内容基于监管机构官网公开信息整理，逐条附原文深链</div>
</div></footer>
</body>
</html>
"""

    outdir = os.path.join(HERE, "updates")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "index.html")
    open(out, "w", encoding="utf-8").write(html)

    print(f"已生成 updates/index.html")
    print(f"  基线 {src} | 新增 {len(added)} / 变更 {len(changed)} / 下线 {len(removed)}")
    print(f"  今日生效 {len(today_eff)} | 30日内 {len(soon30)} | 180日内 {len(soon180)}")
    print(f"  7日内立法节点 {len(cal7)} | 草案截止 {len(dl)} | 进行中行动 {len(ongoing)}")

    # 钩子：统一导航页脚 + 社交元数据
    for s in ("unify_chrome.py", "inject_meta.py"):
        p = os.path.join(HERE, s)
        if os.path.exists(p):
            os.system(f'/usr/bin/python3 "{p}" >/dev/null 2>&1')
    save_snapshot(items)
    print(f"  快照已更新 → sources/updates/snapshot.json（{len(items)} 条）")


if __name__ == "__main__":
    main()
