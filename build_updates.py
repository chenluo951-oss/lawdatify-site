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

# 快照口径版本。**改动 key_of / fingerprint 必须 +1**，否则新旧基线混用会虚报增量。
# v1 → v2（2026-09-16）：键由「效力层级::名称」改为「code::name::pub::impl::issuer」。
SNAP_V = 2

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
    """条目唯一键 —— 必须「一部法规的**一个版本**」对应一个键。

    踩过的两个坑（都导致过大规模假变更）：
      1. 只用 code：法规类条目的 code 存的是**效力层级**（「部门规章」「法律」），
         多部法规共用同一个 code，只按 code 取键会大面积冲突；
      2. code + name 仍然不够：法规库里同一部法规存有**多个历史版本**
         （如《武汉市城市节约用水条例》有 2005 / 2021 / 2022 三个版本的记录，
         分别对应不同的公布与施行日期），只用 code+name 会让这些版本碰撞成同一个键，
         快照只记得住其中一个 → 每次列表顺序一变就被误报成「状态 / 内容变更」。
         2026-09-16 实测：碰撞 1072 条，而页面报的「变更」恰好也是 1072 条 —— 全部为假。
    因此用「效力层级 + 名称 + 公布日期 + 施行日期 + 发布机关」五项复合键，
    实测 20003 条中碰撞仅 4 条（为同源重复条目）。
    """
    name = (it.get("name") or "").strip()
    if not name:
        return ""
    k = "::".join([
        (it.get("code") or "").strip(),
        name,
        (it.get("pub") or "").strip(),
        (it.get("impl") or "").strip(),
        (it.get("issuer") or "").strip(),
    ])
    return k if k.strip(":") else (it.get("url") or "").strip()


# 指纹字段分隔符：用 ASCII 0x1f（字段分隔符），不会与任何法名 / 链接冲突。
SEP = "\x1f"


def fp_of(it):
    """单条目的状态指纹。自带 name，这样**下线条目**也能显示名称，
    无需再在快照里另存一份 meta（旧格式的 meta 让快照涨到 11MB，每天一个 blob 拖累仓库）。"""
    return SEP.join([
        (it.get("name") or "").replace(SEP, ""),
        (it.get("status") or "").replace(SEP, ""),
        (it.get("impl") or "").replace(SEP, ""),
        (it.get("url") or "").replace(SEP, ""),
        (it.get("point") or "")[:200].replace(SEP, ""),
    ])


def fp_parts(fp):
    """把指纹还原成字段字典（供「状态 X → Y」「下线条目」展示）。"""
    p = (fp or "").split(SEP)
    p += [""] * (5 - len(p))
    return {"name": p[0], "status": p[1], "impl": p[2], "url": p[3], "point": p[4]}


def state_of(items):
    return {key_of(i): fp_of(i) for i in items if key_of(i)}


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
# 快照采用**双槽**结构（base / today），保证增量是「日对比日」而不是「构建对比构建」：
#
#   {"v":2, "base":{"date":"09-15","fp":{…}}, "today":{"date":"09-16","fp":{…}}}
#
#   · base  = 用来做差分的基线（通常是**前一天**闭市时的状态）
#   · today = 最近一次构建时的状态，跨天时滚成新的 base
#
# 为什么必须有 today 这一槽：旧实现每次构建都把 `items` 覆盖成当前状态，于是
# 同一天重建第二次时，diff 的基线变成了「几小时前的自己」—— 增量数字会塌成 0
# （页面数字取决于当天构建了几次，而不是实际变了多少）。双槽后，同一天内反复重建
# 都对比同一个 base，数字全天稳定；跨天后自动滚动。
def load_snapshot():
    if os.path.exists(SNAP):
        try:
            return json.load(open(SNAP, encoding="utf-8"))
        except Exception:
            pass
    return None


def seed_from_git():
    """建基线兜底：用 git HEAD 里的历史版本。返回 base 槽（含真实提交日期）。"""
    raw = git("show", f"HEAD:{LIB}")
    if not raw.strip():
        return None
    try:
        old = json.loads(raw)
    except Exception:
        return None
    d = git("log", "-1", "--format=%cs", "--", LIB).strip()
    return {"date": d or "git HEAD", "fp": state_of(old.get("items", []))}


def save_snapshot(items, base_slot):
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = {
        "v": SNAP_V,
        "base": base_slot,
        "today": {"date": TODAY_S, "fp": state_of(items)},
    }
    # 紧凑序列化：indent 版体积大一倍，而这个文件每天都要进一次提交。
    json.dump(snap, open(SNAP, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    return snap


# ------------------------------------------------------------------ 增量计算
def diff_items(cur_items, base_fp):
    """当前条目 vs 基线指纹表 → (新增条目, [(旧字段, 新条目)], [下线条目的字段])。"""
    if not base_fp:
        return [], [], []
    added, changed, removed = [], [], []
    cur_fp = state_of(cur_items)
    for it in cur_items:
        k = key_of(it)
        if not k:
            continue
        if k not in base_fp:
            added.append(it)
        elif base_fp[k] != cur_fp[k]:
            changed.append((fp_parts(base_fp[k]), it))
    for k, fp in base_fp.items():
        if k not in cur_fp:
            removed.append(fp_parts(fp))
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
    items = [x for x in lib.get("items", []) if not x.get("hidden")]
    cal = (load(CAL) or {}).get("items", [])
    act = (load(ACT) or {}).get("items", [])
    draft_raw = load(DRAFT) or {}
    drafts = draft_raw.get("items", []) if isinstance(draft_raw, dict) else draft_raw

    # ---- 增量基线：口径版本不一致时必须**重置**，绝不能拿旧基线硬算 ----
    # ⚠️ 口径不一致时**不能**回退到 git 兜底 —— git 里的库可能是几天前的，
    # 拿它当基线会报出「一次性集中补齐」式的虚高增量（实测虚报 18876 条），
    # 在一张叫「今日更新」的页面上等于再骗一次。此时宁可如实置「—」。
    raw_snap = load_snapshot()
    base_note = ""
    if raw_snap is not None and (raw_snap.get("v") or 0) != SNAP_V:
        raw_snap, base_note = None, "统计口径修正"
    base_slot = (raw_snap or {}).get("base")
    today_slot = (raw_snap or {}).get("today")
    a_today = (today_slot or {}).get("date") or ""
    if a_today and a_today < TODAY_S:
        base_slot = today_slot          # 跨天滚动：昨天最后一次构建的状态成为今天的基线
    if base_slot is None and raw_snap is None and not base_note:
        base_slot = seed_from_git()     # 快照文件缺失时的兜底
    # base 槽上的 note 是一次性的「口径修正」说明：跨天滚动后（today 槽没有 note）自动消失
    base_note = base_note or ((base_slot or {}).get("note") or "")
    base_fp = (base_slot or {}).get("fp") or {}
    src = (base_slot or {}).get("date") or (base_note or "新建基线")
    no_base = not base_fp           # 无基线 → 增量无意义，一律显示「—」

    # 键碰撞自检（两套口径都算，用于说明与日志）：
    #   · key_collisions     —— 现行复合键下的残留碰撞（同源重复条目）
    #   · v1_key_collisions  —— 旧口径「效力层级::名称」下的碰撞数，正是此前全部假变更的来源
    _kc, _kc1 = {}, {}
    for _i in items:
        _k = key_of(_i)
        if _k:
            _kc[_k] = _kc.get(_k, 0) + 1
        _k1 = "::".join([(_i.get("code") or "").strip(), (_i.get("name") or "").strip()])
        if _k1.strip(":"):
            _kc1[_k1] = _kc1.get(_k1, 0) + 1
    key_collisions = sum(v - 1 for v in _kc.values() if v > 1)
    v1_key_collisions = sum(v - 1 for v in _kc1.values() if v > 1)

    added, changed, removed = diff_items(items, base_fp)
    # 2026-09-15：法规库（国家法律法规数据库全量）与标准库（标准门户检索）一次性补齐后，
    # 「本次新增」可达上万条，全量铺进本页会把 HTML 顶到 9MB（移动端打不开）。
    # 列表只列示最新的 400 条。
    # ⚠️ 2026-09-16：统计卡曾经直接打印**截断后**的长度 —— 真实变更 1072 条、卡片却显示 400
    # （即列表上限），读者据此以为「只变了 400 条」。凡截断，卡片一律用**真实总量**，
    # 只在列表区标题里写明「本页列示最新 N 条」。
    UP_CAP = 400
    n_added_all, n_changed_all, n_removed_all = len(added), len(changed), len(removed)
    up_trunc = max(n_added_all, n_changed_all, n_removed_all) > UP_CAP
    added, changed, removed = added[:UP_CAP], changed[:UP_CAP], removed[:UP_CAP]

    # --- 站点直采合规动态（独立于本地简报的每日增量，见 tools/collect_news.py）---
    nat_file = os.path.join(HERE, "sources", "news", "items.jsonl")
    nat, nat_new = [], []
    if os.path.exists(nat_file):
        for line in open(nat_file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            # 每周清理的条目（prune_policy 判定）不再计入「今日更新」
            if rec.get("pruned"):
                continue
            nat.append(rec)
    # 本期新增 = 今天入库的动态；若今天还没入库（未联网 / 采集未跑），**回退到最近一次批次，
    # 但必须如实标注批次日期** —— 曾经回退之后仍然挂着「今日新增」的标题，属于误导。
    nat_batch = TODAY_S if any((x.get("collected") or "") == TODAY_S for x in nat) else \
        (max((x.get("collected") or "") for x in nat) if nat else "")
    nat_is_today = bool(nat_batch) and nat_batch == TODAY_S
    today_nat = [x for x in nat if (x.get("collected") or "") == nat_batch] if nat_batch else []
    nat_new = sorted(today_nat, key=lambda x: (x.get("date") or ""), reverse=True)

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
    dl_all = sorted(dl, key=lambda x: x[0])
    # 同上：卡片用真实总数，列表才截断
    DL_CAP = 10
    dl = dl_all[:DL_CAP]

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
    if no_base:
        _base_line = f"增量基线已重置（{base_note or '首次建库'}），本次不报增量"
    else:
        _base_line = f"增量对比基线：{src}" + (f"（{base_note}）" if base_note else "")
    parts.append(f"""<div class="up-hero">
  <div class="up-date">{TODAY_S}</div>
  <div class="up-hero-t">今日更新</div>
  <p class="up-hero-d">汇总当日新增的合规动态，以及法规、标准与监管节点变化：新增与状态变更、生效倒计时、
  7 日内立法节点、草案征求意见截止与进行中的监管行动，逐条附发布机构原文深链。<br>
  <span class="up-base">{_base_line}</span></p>
</div>""")

    # 统计卡 —— 数量一律取**真实总量**（与下方列表是否截断无关）；
    # 基线刚重置时如实置「—」，不报 0（那会被读成「今天什么都没变」）也不报假数。
    nat_label = "今日新增合规动态" if nat_is_today else "最近批次合规动态"
    nat_sub = ("站点直采 · 官方原文" if nat_is_today
               else f"{nat_batch} 入库 · 站点直采 · 官方原文")
    base_sub = f"对比基线 {src}"
    parts.append('<div class="stat-grid">')
    parts.append(stat_card(len(nat_new), nat_label, nat_sub, "tone-new"))
    if no_base:
        parts.append(stat_card("—", "新增法规 / 标准", base_note or "新建基线", "tone-new"))
        parts.append(stat_card("—", "状态 / 内容变更", base_note or "新建基线", "tone-chg"))
    else:
        parts.append(stat_card(n_added_all, "新增法规 / 标准", base_sub, "tone-new"))
        parts.append(stat_card(n_changed_all, "状态 / 内容变更", base_sub, "tone-chg"))
    parts.append(stat_card(len(today_eff), "今日生效", f"另有 {len(soon30)} 项 30 日内生效", "tone-eff"))
    parts.append(stat_card(len(cal7), "7 日内立法节点", f"{len(ongoing)} 项监管行动进行中", "tone-cal"))
    parts.append(stat_card(len(dl_all), "草案征求意见",
                           (f"按截止日排序 · 本页列示 {len(dl)} 条" if len(dl_all) > len(dl)
                            else "按截止日排序"), "tone-drt"))
    parts.append("</div>")

    # 口径说明。⚠️ 这段原来写成「生成后再去找 </main> 插入」，而本页模板里根本没有 </main>
    # —— 于是截断说明**从未渲染过**：读者只看到被截断的 400，却没有任何解释。改为直接渲染。
    notes = []
    if base_note:
        # 面向读者的口径说明（不放内部键设计、不写工程日志；细节见本文件 key_of 注释与构建日志）
        _tail = ('因匹配口径变更，本次<b>重置了对比基线</b>，「新增法规 / 标准」与「状态 / 内容变更」'
                 '暂不展示，自下一次更新起恢复为真实增量。' if no_base else
                 f'本次已按新口径重算，对比基线为上一版发布状态（{src}），结果见上方统计卡。')
        notes.append(
            '<b>数据说明</b>：法规标准条目库中，同一部法规可能存有多个历史版本（公布年份不同）。'
            '此前的增量统计按「名称」匹配条目，会把「同一部法规的新旧版本」误判成'
            '「该法规发生了变更」，因此上一版页面列出的「状态 / 内容变更」并不可靠。'
            f'现已改为按「名称 + 公布日期 + 施行日期 + 发布机关」逐版本匹配（旧口径下误判条目 '
            f'{v1_key_collisions} 条）。' + _tail +
            '本页其余数据（生效倒计时、立法节点、草案截止、合规动态）均按日期直接计算，不受影响。')
    if up_trunc:
        notes.append(
            f'<b>本次增量较大</b>：法规 / 标准条目新增 {n_added_all} 条、变更 {n_changed_all} 条、'
            f'下架 {n_removed_all} 条，下方列表仅列示最新 {UP_CAP} 条。'
            f'完整条目请在 <a href="../kb/standards.html">标准与义务</a> 中按专题、层级、时效性筛选或检索。')
    # 残留键冲突（同源重复条目，实测 4 条）不上面 —— 属内部数据质量，只在构建日志里提示。
    if notes:
        parts.append('<div class="notice">' + "<br>".join(notes) + '</div>')

    # 0. 站点直采合规动态（独立于本地简报）。标题如实反映**实际批次**，今天没采到就不会写「今日」。
    _nat_title = ("今日新增合规动态" if nat_is_today
                  else f"最近批次合规动态 · {nat_batch} 入库" if nat_batch else "合规动态")
    parts.append(f'<div class="section-title"><span class="bar"></span>{_nat_title}'
                 f'（{len(nat_new)} 条）</div>')
    if nat_new:
        for it in nat_new:
            url = it.get("url") or ""
            nm = esc(it.get("title") or "")
            t = f'<a href="{esc(url)}" target="_blank" rel="noopener">{nm}</a>' if url else nm
            ana = (f'<p class="up-point">{esc(it.get("points") or "")}</p>'
                   if it.get("points") else "")
            _card = (
                f'<div class="up-item"><div class="up-title">{t}</div>'
                f'<div class="up-chips"><span class="chip chip-new">NEW</span>'
                f'<span class="chip">{esc(it.get("domain") or "")}</span>'
                f'<span class="chip">{esc(it.get("kind") or "")}</span>'
                f'<span class="chip">{esc(it.get("org") or "")}</span>'
                f'<span class="chip chip-dim">{esc(it.get("date") or "")}</span></div>'
                + ana + '</div>')
            parts.append(_card)
    else:
        parts.append('<p class="lead">本批次无新增动态，可查看下方法规标准增量与监管节点。</p>')

    # 1. 新增（标题写明真实总量；列表截断时说明本页只列示多少条）
    if no_base:
        _t1 = "最新收录条目（无可用基线，本轮不报增量）"
    else:
        _t1 = f"最新收录条目（新增 {n_added_all} 条" + \
              (f"，本页列示最新 {len(added)} 条）" if up_trunc else "）")
    parts.append(f'<div class="section-title"><span class="bar"></span>{_t1}</div>')
    if no_base:
        parts.append('<p class="lead">本轮没有可用的对比基线（'
                     + (base_note or "首次建库") +
                     '），如实不报增量；新增 / 变更清单自下一次更新起恢复。</p>')
    elif added:
        for it in added:
            parts.append(item_row(it, '<span class="chip chip-new">NEW</span>'))
    else:
        parts.append('<p class="lead">本期无新增收录。</p>')

    # 2. 变更
    if changed:
        _t2 = f"状态 / 内容变更（{n_changed_all} 条" + \
              (f"，本页列示最新 {len(changed)} 条）" if n_changed_all > len(changed) else "）")
        parts.append(f'<div class="section-title"><span class="bar"></span>{_t2}</div>')
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
        parts.append(f'<div class="section-title"><span class="bar"></span>下线条目'
                     f'（{n_removed_all} 条' +
                     (f'，本页列示最新 {len(removed)} 条）' if n_removed_all > len(removed) else '）') +
                     '</div>')
        for r in removed:
            parts.append(f'<div class="up-item"><div class="up-title">{esc(r.get("name") or "")}</div>'
                         f'<div class="up-chips"><span class="chip chip-dim">已从条目库移除</span></div></div>')

    # 3. 生效倒计时（按施行日期计算，与增量基线无关，不受口径修正影响）
    _n_eff = len(today_eff) + len(soon30) + len(soon180)
    parts.append(f'<div class="section-title"><span class="bar"></span>生效倒计时'
                 f'（未来 180 天内共 {_n_eff} 条）</div>')
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
        parts.append(f'<div class="section-title"><span class="bar"></span>'
                     f'7 日内立法与监管节点（共 {len(cal7)} 项）</div>')
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
        _t5 = f"征求意见截止倒计时（共 {len(dl_all)} 项" + \
              (f"，本页列示最近 {len(dl)} 项）" if len(dl_all) > len(dl) else "）")
        parts.append(f'<div class="section-title"><span class="bar"></span>{_t5}</div>')
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
        parts.append(f'<div class="section-title"><span class="bar"></span>'
                     f'进行中的监管行动（{len(ongoing)} 项）</div>')
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

    body = "\n".join(parts)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>今日更新 · 合规动态 · 合规无终点</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>

<nav class="topnav"></nav>

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规动态</a> / 今日更新</div>
  <h1>今日更新</h1>
  <p>法规标准增量、生效倒计时、立法节点与草案截止，一屏掌握今天变了什么。
  —— 本节已并入「合规动态」，与每日监管事件流同源同批。</p>
</div></div>

<div class="wrap">
{body}
</div>

<footer></footer>
</body>
</html>
"""

    # 2026-09-17（用户要求「今日更新和合规动态合并」）：
    #   ① news/today.html —— 本页正文（作为「合规动态」的子页，导航里不再占一级入口）
    #   ② sources/updates/block.html —— 同一份内容区块，供 build_topics 内嵌进合规动态首页，
    #      这样读者进「合规动态」第一屏就看到「今天变了什么」，不必再去另一个模块
    #   ③ updates/index.html —— 原地址保留为跳转页，避免任何存量外链 404
    outdir = os.path.join(HERE, "news")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "today.html")
    open(out, "w", encoding="utf-8").write(html)

    blk = os.path.join(SNAP_DIR, "block.html")
    os.makedirs(SNAP_DIR, exist_ok=True)
    open(blk, "w", encoding="utf-8").write(
        "<!-- UPD-BLOCK:START -->\n" + body + "\n<!-- UPD-BLOCK:END -->\n")

    old = os.path.join(HERE, "updates", "index.html")
    os.makedirs(os.path.dirname(old), exist_ok=True)
    open(old, "w", encoding="utf-8").write(
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>今日更新 · 已并入合规动态 · 合规无终点</title>\n'
        '<link rel="canonical" href="../news/today.html">\n'
        '<meta http-equiv="refresh" content="0; url=../news/today.html">\n'
        '<style>body{margin:0;font-family:"PingFang SC",system-ui,sans-serif;'
        'display:flex;align-items:center;justify-content:center;min-height:100vh;'
        'background:#f6f8fb;color:#16202c;line-height:1.9}'
        'div{max-width:520px;padding:36px;background:#fff;border:1px solid #e6ebf2;'
        'border-radius:14px;text-align:center}'
        'a{color:#1b4f8a;font-weight:600}</style></head><body><div>\n'
        '<h1 style="font-size:19px;margin:0 0 10px">「今日更新」已并入「合规动态」</h1>\n'
        '<p style="color:#6b7a8c;font-size:14px;margin:0">'
        '站点改版后，今日增量与每日监管事件合并在同一个模块。<br>'
        '正在为你跳转到 <a href="../news/today.html">合规动态 · 今日更新</a>…</p>\n'
        '</div></body></html>\n')

    print(f"已生成 news/today.html（合规动态 · 今日更新）")
    print(f"  并写出来源区块 sources/updates/block.html（供合规动态首页内嵌）")
    print(f"  updates/index.html 已改为跳转页")

    # ---- 内嵌到「合规动态」首页（幂等：替换 TODAY 标记块；模板无标记时插在子导航之后）----
    # ⚠️ 只内嵌**增量摘要**（即将生效 / 立法节点 / 草案截止 三块），全量留在 today.html：
    # 用户 2026-09-17 抱怨过首页「图表太大、正文在最下面」，把整页增量灌进动态首页会重演。
    # 2026-09-17 二次修正：原先复用 nat_cards（动态卡片）→ 与下方 FEED 列表**逐条重复**，
    # 改为只放 today.html 独有的增量信息，正文列表里看不到的内容才有资格占首屏。
    idx = os.path.join(HERE, "news", "index.html")
    if os.path.exists(idx):
        def _sum_box(title, note, rows):
            """rows: [(右列文字, 名称, 链接)]；无内容返回空串（不占位）"""
            if not rows:
                return ""
            lis = "".join(
                f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{nm}</a>'
                f'<em>{esc(t)}</em></li>' if u else f'<li><span>{nm}</span><em>{esc(t)}</em></li>'
                for t, nm, u in rows)
            return (f'<div class="up-sum-b"><h4>{title}<i>{esc(note)}</i></h4>'
                    f'<ul>{lis}</ul></div>')

        boxes = []
        # ① 即将生效（未来 180 天内最早到期的 4 条）
        rows = []
        for d, n, it in (today_eff + soon30 + soon180)[:4]:
            rows.append((d.isoformat(), it.get("name") or "", it.get("url") or ""))
        boxes.append(_sum_box("即将生效", f"未来 180 天共 {_n_eff} 条", rows))
        # ② 7 日内立法与监管节点
        rows = []
        for d, n, e in cal7[:3]:
            rows.append((d.isoformat(), e.get("title") or "", e.get("url") or ""))
        boxes.append(_sum_box("7 日内立法与监管节点", f"共 {len(cal7)} 项", rows))
        # ③ 进行中的监管行动
        rows = []
        for a in ongoing[:3]:
            rows.append((a.get("status") or "进行中", a.get("name") or "", a.get("url") or ""))
        boxes.append(_sum_box("进行中的监管行动", f"共 {len(ongoing)} 项", rows))
        # ④ 征求意见截止（本页只列示最近 3 项，全量在 today.html）
        rows = []
        for d, n, dft in dl[:3]:
            rows.append((d.isoformat(), dft.get("name") or dft.get("title") or "",
                         dft.get("url") or ""))
        boxes.append(_sum_box("征求意见截止", f"共 {len(dl_all)} 项", rows))

        teaser = []
        teaser.append('<div class="section-title"><span class="bar"></span>今日更新</div>')
        bits = []
        if nat_new:
            bits.append(f'新增合规动态 <b>{len(nat_new)}</b> 条')
        if not no_base and n_added_all:
            bits.append(f'法规标准条目新增 <b>{n_added_all}</b> 条')
        if not no_base and n_changed_all:
            bits.append(f'状态变更 <b>{n_changed_all}</b> 条')
        bits.append(f'未来 180 天内生效 <b>{_n_eff}</b> 条')
        bits.append(f'进行中的监管行动 <b>{len(ongoing)}</b> 项')
        teaser.append(f'<p class="lead">截至 {TODAY_S}：' + " · ".join(bits)
                      + '。<a href="today.html">查看完整今日更新 →</a></p>')
        teaser.append('<div class="up-sum">' + "".join(b for b in boxes if b) + '</div>')
        block = ("<!-- TODAY:START -->\n" + "\n".join(teaser) + "\n<!-- TODAY:END -->")
        s = open(idx, encoding="utf-8").read()
        pat = re.compile(r"<!-- TODAY:START -->.*?<!-- TODAY:END -->", re.S)
        if pat.search(s):
            s2 = pat.sub(lambda m: block, s, count=1)
        else:
            anchor = "<!-- SUBNAV:END -->"
            s2 = s.replace(anchor, anchor + "\n" + block, 1) if anchor in s else s
        if s2 != s:
            open(idx, "w", encoding="utf-8").write(s2)
            print(f"  news/index.html 今日更新摘要已同步（增量块："
                  f"生效 {min(len(today_eff) + len(soon30) + len(soon180), 4)} / "
                  f"节点 {min(len(cal7), 3)} / 行动 {min(len(ongoing), 3)} / "
                  f"草案 {min(len(dl), 3)} 条）")
    print(f"  基线 {src} | 真实增量：新增 {n_added_all} / 变更 {n_changed_all} / 下线 {n_removed_all}"
          f"（页面列表列示 {len(added)}/{len(changed)}/{len(removed)} 条）")
    print(f"  合规动态批次 {nat_batch or '—'} · {len(nat_new)} 条（站点直采库 {len(nat)} 条）"
          f"{'' if nat_is_today else '　⚠ 非今日批次，标题已如实标注'}")
    print(f"  今日生效 {len(today_eff)} | 30日内 {len(soon30)} | 180日内 {len(soon180)}")
    print(f"  7日内立法节点 {len(cal7)} | 草案截止 {len(dl_all)}（列示 {len(dl)}）| 进行中行动 {len(ongoing)}")

    # 钩子：重建全站检索索引（不跑则搜索结果会过期）
    bs = os.path.join(HERE, "build_search.py")
    if os.path.exists(bs):
        os.system(f'/usr/bin/python3 "{bs}" >/dev/null 2>&1')

    # 钩子：统一导航页脚 + 社交元数据
    for s in ("unify_chrome.py", "inject_meta.py"):
        p = os.path.join(HERE, s)
        if os.path.exists(p):
            os.system(f'/usr/bin/python3 "{p}" >/dev/null 2>&1')
    # ⚠️ 这里原来有一段「生成后再读回文件、把截断说明插到 </main> 前」的后处理，
    # 而本页模板用的是 <div class="wrap">，根本不存在 </main> ——
    # 于是说明从未渲染过（读者只看到被截断的 400，没有任何解释）。
    # 现已改为在 parts 里直接渲染（见上方 notes），此处不再做文件回写。
    save_snapshot(items, base_slot)
    print(f"  快照已更新 → sources/updates/snapshot.json（v{SNAP_V} · {len(items)} 条"
          f"{' · 基线 ' + src if not no_base else ' · 无基线'}）"
          f"{'　⚠ 键冲突 %d 条' % key_collisions if key_collisions else ''}")
    if no_base:
        print(f"  ⚠ 本轮无可用基线（{base_note or '首次建库'}）：不报增量；"
              f"本次状态已存入 today 槽，下次构建自动滚为基线")


if __name__ == "__main__":
    main()
