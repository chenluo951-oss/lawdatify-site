#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「合规动态」下的算法合规治理专项页

  news/algo-filing.html   算法合规治理 —— 备案发布序列全景 + 算法备案 / 深度合成 /
                          生成式AI 备案 / 生成式AI 登记四序列 + 注销记录
  news/app-violations.html 移动应用违规治理 —— 见 appviol_page.py

数据源
------
  sources/special/registry.json   发布主体全景登记表（人工维护，谁在通报）
  sources/algo/algo_filing.json   互联网信息服务算法备案清单（19 期）
  sources/algo/deepfake_filing.json 深度合成服务算法备案清单（18 批）
  sources/algo/genai_filing.json  生成式AI 备案与登记（13 期，已拆备案/登记）
  sources/algo/cancel.json        算法备案编号注销公告（7 份）
  sources/algo/aggregates.json    年度/全量汇总公告（仅校验，不参与累加）

算法侧口径
----------
  四条并列序列按备案编号去重；年度汇总公告重列全年清单，**排除在累加之外**仅作校验；
  累计有效数 = 累计备案 − 累计注销。
"""
import os
import re
from collections import Counter

from spec_common import *                 # noqa: F401,F403
from appviol_page import build_appviol    # noqa: E402
# ============================================================ 专项二：算法
def build_algo():
    algo = load(os.path.join(ALGO, "algo_filing.json"))
    deep = load(os.path.join(ALGO, "deepfake_filing.json"))
    genai = load(os.path.join(ALGO, "genai_filing.json"))
    cancel = load(os.path.join(ALGO, "cancel.json"))
    agg = load(os.path.join(ALGO, "aggregates.json"))
    reg = load(REG).get("algo") or {"groups": []}

    ab = algo.get("batches") or []
    db = deep.get("batches") or []
    gb = genai.get("batches") or []
    cn = cancel.get("notices") or []
    ag = agg.get("aggregates") or []

    n_algo = sum(b["count"] for b in ab)
    n_deep = sum(b["count"] for b in db)
    n_b = sum(b.get("n_beian", 0) for b in gb)
    n_r = sum(b.get("n_dengji", 0) for b in gb)
    n_cancel = sum(x.get("count", 0) for x in cn)

    # 去重校验：按备案编号
    ids = set()
    for b in ab + db:
        for r in b["rows"]:
            k = re.sub(r"\s+", "", r.get("备案编号", ""))
            if k:
                ids.add(k)
    gid = set()
    for b in gb:
        for r in b["rows"]:
            k = re.sub(r"\s+", "", r.get("备案编号") or r.get("备案号") or "")
            if k:
                gid.add(k)

    # 算法类别
    cat = Counter(r.get("算法类别", "") for b in ab for r in b["rows"] if r.get("算法类别"))
    # 深度合成角色
    role = Counter(r.get("角色", "") for b in db for r in b["rows"] if r.get("角色"))
    # 属地（生成式AI）
    regn = Counter(r.get("属地", "") for b in gb for r in b["rows"] if r.get("属地"))
    # 主体集中度
    subj = Counter(r.get("主体名称", "") for b in ab + db for r in b["rows"]
                   if r.get("主体名称"))
    # 时间趋势
    algo_trend = [(b["period"], b["count"]) for b in ab]
    deep_trend = [(b.get("batch", b["period"]), b["count"]) for b in db]
    genai_trend = [(b["period"], b["count"]) for b in gb]

    kpis = [
        ("算法备案", num(n_algo), f"{len(ab)} 期 · 备案编号零重复"),
        ("深度合成备案", num(n_deep), f"{len(db)} 批 · ★本次新补序列"),
        ("生成式AI 备案", num(n_b), f"{len(gb)} 期 · 大模型，编号无 S"),
        ("生成式AI 登记", num(n_r), f"{len(gb)} 期 · 应用/功能，属地受理"),
        ("备案编号注销", num(n_cancel), f"{len(cn)} 份注销公告"),
        ("去重唯一编号", num(len(ids) + len(gid)), "四条序列按备案编号去重"),
    ]

    body = []
    body.append(kpi(kpis))

    # ---- 对账与口径
    agg_labels = "、".join(x.get("label", "") for x in ag) or "—"
    last = gb[-1] if gb else {}
    official = ag[-1] if ag else {}
    official_sum = ((official.get("cum_beian") or 0)
                    + (official.get("cum_dengji") or 0)) or "—"
    body.append(f"""
<div class="sp-note sp-warn"><b>⚠️ 口径与对账</b>
<ul>
<li><b>四条并列序列，不可直接相加</b>：
「互联网信息服务算法备案」（{num(n_algo)} 条）、「深度合成服务算法备案」（{num(n_deep)} 条）、
「生成式AI 备案」（{num(n_b)} 条）、「生成式AI 登记」（{num(n_r)} 条）。
算法备案与深度合成两序列按<b>备案编号</b>去重后为 {num(len(ids))} 个唯一编号
（两套编号体系不同，实测互不重复）；生成式AI 备案与登记共用同一编号空间，
去重后 {num(len(gid))} 个。</li>
<li><b>年度汇总公告必须排除</b>：本库另收录 {len(ag)} 份「年度/全量汇总公告」
（{esc(agg_labels)}）。汇总公告把全年清单再列一遍，与增量序列完全重合，
<b>一律不参与累加，仅用于校验</b>。</li>
<li><b>注销要扣减</b>：{len(cn)} 份注销公告共注销 {num(n_cancel)} 个备案编号；
不做扣减会把已注销编号计入存量。</li>
<li><b>对账结果</b>：本库生成式AI 分批累加去重后 <b>{num(len(gid))}</b> 个唯一备案编号；
官方 2026-09-14 公告口径为「累计备案 {esc(official.get('cum_beian') or '—')} 款 +
累计登记 {esc(official.get('cum_dengji') or '—')} 款 = {esc(official_sum)} 款」。
<b>两者一致</b>，说明分批累加口径与官方汇总口径可互相印证（公告同时注明，
备案编号会随主体变更与注销动态调整，故个别条目在备案/登记归类上存在差异）。</li>
</ul></div>""")

    # ---- 来源全景
    body.append(sec("谁在备案、谁在发公告 —— 发布主体与序列全景",
                    "先把发布主体与序列关系摸清楚（哪些是并列序列、哪些是汇总重列），"
                    "统计口径才立得住。",
                    registry_group("algo", reg.get("groups") or [])))

    # ---- 分析
    c1 = ('<div class="sp-card"><h4>算法备案 · 各期新增</h4>'
          + bars(algo_trend, 25) + "</div>")
    c2 = ('<div class="sp-card"><h4>深度合成备案 · 各批新增</h4>'
          + bars(deep_trend, 25) + "</div>")
    c3 = ('<div class="sp-card"><h4>生成式AI · 各期备案 / 登记</h4>'
          + bars(genai_trend, 20) + "</div>")
    body.append(sec("序列趋势", "", '<div class="sp-2col">' + c1 + c2 + c3 + "</div>"))

    c4 = ('<div class="sp-card"><h4>算法备案 · 算法类别分布</h4>'
          + bars(cat.most_common(), 12)
          + '<p class="sp-src" style="margin-top:10px">'
            "反映算法推荐类备案的结构；生成合成类多走「深度合成」独立序列。</p></div>")
    c5 = ('<div class="sp-card"><h4>深度合成备案 · 主体角色分布</h4>'
          + bars(role.most_common(), 8)
          + '<p class="sp-src" style="margin-top:10px">'
            "依据《互联网信息服务深度合成管理规定》第十九条，技术支持者参照提供者履行备案手续。</p></div>")
    c6 = ('<div class="sp-card"><h4>生成式AI · 属地分布</h4>'
          + bars(regn.most_common(), 20)
          + '<p class="sp-src" style="margin-top:10px">'
            "国家公告的清单内含「属地」列，因此省级分布可直接从国家口径得出，无需依赖地方公告。</p></div>")
    body.append(sec("结构分析", "", '<div class="sp-2col">' + c4 + c5 + c6 + "</div>"))

    srows = "".join(
        f'<tr><td>{i}</td><td><b style="color:var(--ink)">{esc(k)}</b></td>'
        f'<td><b style="color:var(--accent)">{v}</b></td></tr>'
        for i, (k, v) in enumerate(subj.most_common(60), 1))
    body.append(sec("备案主体集中度 TOP 60",
                    "按「互联网信息服务算法备案 + 深度合成备案」两个序列合计的备案条目数排序，"
                    "呈现算法合规投入最密集的主体。",
                    '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
                    "<th>#</th><th>主体名称</th><th>备案条目数</th></tr></thead><tbody>"
                    + srows + "</tbody></table></div>"))

    # ---- 注销
    krows = ""
    for x in cn:
        title = x.get("title", "")
        m = re.search(r"等\s*(\d+)\s*个", title)
        cnt = x.get("count", 0)
        mark = "" if m else '<span class="sp-pill off">标题未载明数量</span>'
        krows += (f'<tr><td style="white-space:nowrap">{esc(x.get("date",""))}</td>'
                  f'<td>{esc(title)}{mark}</td>'
                  f'<td><b>{esc(cnt)}</b></td>'
                  f'<td>{link(x.get("url"), "公告原文")}</td></tr>')
    krows += (f'<tr style="background:#fbfcfe"><td colspan="2" style="text-align:right">'
              f'<b style="color:var(--ink)">合计注销编号</b></td>'
              f'<td><b style="color:var(--ink)">{num(n_cancel)}</b></td><td>—</td></tr>')
    detail = ""
    for x in cn:
        for r in (x.get("records") or []):
            detail += (f'<tr><td>{esc(r.get("name",""))}</td>'
                       f'<td>{esc(r.get("entity",""))}</td>'
                       f'<td><span class="sp-src">{esc(r.get("code",""))}</span></td>'
                       f'<td style="white-space:nowrap">{esc(r.get("cancel",""))}</td></tr>')
    body.append(sec(
        "备案编号注销记录",
        "注销才得到「累计有效备案数」的正确口径。下表逐份列示 7 份注销公告，并展开全部注销明细"
        "（算法名称 / 主体 / 备案编号 / 注销时间）——这是把「累计备案」折成「当前有效」的关键一步。",
        '<div class="sp-wrap"><table class="sp-tbl"><thead><tr>'
        "<th>日期</th><th>公告</th><th>注销编号数</th><th>原文</th></tr></thead><tbody>"
        + krows + "</tbody></table></div>"
        + f'<h4 style="margin:22px 0 8px;font-size:14.5px;color:var(--ink)">'
          f'注销明细（{num(sum(len(x.get("records") or []) for x in cn))} 个编号）</h4>'
          '<div class="sp-wrap sp-lim"><table class="sp-tbl"><thead><tr>'
          "<th>算法名称</th><th>主体名称</th><th>备案编号</th><th>注销时间</th>"
          "</tr></thead><tbody>" + detail + "</tbody></table></div>"
        + '<p class="sp-src" style="margin-top:10px">口径说明：2 份公告标题写作「等算法备案编号」'
          '未载明数量，其条数由公告表格行解析得到（分别为 5 条、1 条）；表中「注销编号数」'
          '一律以附件表格行为准，不采用标题数字。公告原文经算法备案系统免登录接口按 noticeId 直取。</p>'))

    return page("算法合规治理专项",
                "算法合规治理专项：汇总国家网信办与省级网信部门的算法备案、深度合成算法备案、"
                "大模型备案与 AI 应用登记信息，形成可溯源的备案信息库，并给出与年度汇总公告的对账口径。",
                "算法合规看板", "算法合规治理专项",
                "汇总国家网信办的互联网信息服务算法备案、深度合成服务算法备案、生成式人工智能服务"
                "备案与登记四条并列序列，并单列注销记录与年度汇总公告（不参与累加），"
                "形成可溯源的备案信息库。",
                "".join(body), COMMON_CSS, parent="法律分析")


# 2026-09-17（用户要求「架构重搭，能整合的整合，该拆出来的拆出来」）：
#   两个**专项数据看板**从「合规动态」迁到「法律分析」。理由是它们不是日更事件流，
#   而是与同域深度长文（analysis/app-violation-pattern.html、analysis/algo-filing-guide.html）
#   配对的「数据底稿」；同域相邻读者才找得到，news 的子导航也才从 8 项收回 6 项。
#   旧地址一律留跳转页，存量外链不 404。
MOVED = [
    ("app-violations.html", "移动应用违规治理", "移动应用看板"),
    ("algo-filing.html", "算法合规治理", "算法合规看板"),
]


def main():
    out = os.path.join(HERE, "analysis")
    os.makedirs(out, exist_ok=True)
    for name, fn in (("app-violations.html", build_appviol),
                     ("algo-filing.html", build_algo)):
        html_text = fn()
        p = os.path.join(out, name)
        open(p, "w", encoding="utf-8").write(html_text)
        print(f"✓ analysis/{name}  {os.path.getsize(p)/1024:.0f} KB")

    old_dir = os.path.join(HERE, "news")
    os.makedirs(old_dir, exist_ok=True)
    for name, title, label in MOVED:
        old = os.path.join(old_dir, name)
        open(old, "w", encoding="utf-8").write(
            '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'<title>{title} · 已迁至法律分析 · 合规无终点</title>\n'
            f'<link rel="canonical" href="../analysis/{name}">\n'
            f'<meta http-equiv="refresh" content="0; url=../analysis/{name}">\n'
            '<style>body{margin:0;font-family:"PingFang SC",system-ui,sans-serif;'
            'display:flex;align-items:center;justify-content:center;min-height:100vh;'
            'background:#f6f8fb;color:#16202c;line-height:1.9}'
            'div{max-width:540px;padding:36px;background:#fff;border:1px solid #e6ebf2;'
            'border-radius:14px;text-align:center}'
            'a{color:#1b4f8a;font-weight:600}</style></head><body><div>\n'
            f'<h1 style="font-size:19px;margin:0 0 10px">「{title}」已迁至「法律分析」</h1>\n'
            '<p style="color:#6b7a8c;font-size:14px;margin:0">'
            f'站点改版后，这一份数据看板与同主题的深度分析放在了一起。<br>'
            f'正在跳转到 <a href="../analysis/{name}">法律分析 · {label}</a>…</p>\n'
            '</div></body></html>\n')
        print(f"  news/{name} 已改为跳转页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
