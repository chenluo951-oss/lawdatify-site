#!/usr/bin/env python3
"""模块子导航 + 边界一句话（幂等注入）。

四个一级模块各有明确的「回答什么问题」，用 SUBNAV:START/END 幂等块注入，
避免同一条信息在多个模块重复出现、也避免名称混淆：

  合规动态   发生了什么（事件流 + 今日增量 + 前瞻 + 地域，日更）
  法律分析   怎么理解（专题长文 + 数据看板，按主题沉淀）
  合规管理   怎么落地（审计范围 → 过程留痕 → 整改任务）
  合规知识库 依据是什么（法规标准原文 + 案例 + 高频法条，长期稳定）

2026-09-17（用户要求「全站重新设计、架构重搭，能整合的整合，该拆出来的拆出来」）：
  · 「移动应用违规治理」「算法合规治理」两个**专项数据看板**从「合规动态」移出，
    归入「法律分析」——它们与同域的深度长文（app-violation-pattern / algo-filing-guide）
    本是一组「结论 + 数据底稿」，放在一处才找得到；留在 news 只会把子导航挤成 8 项。
  · 「合规动态」子导航由 8 项收敛为 6 项；「法律分析」新增子导航（此前 7 篇专题平铺、无层级）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

NEWS_NAV = [
    ("index.html", "总览"),
    ("today.html", "今日更新"),
    ("calendar.html", "立法日历"),
    ("map.html", "全球监管地图"),
    ("actions.html", "应对建议"),
    ("briefs.html", "简报归档"),
]
# 两个专项看板迁入本模块（原在 news/）：与同域长文构成「分析 + 数据」配对。
ANALYSIS_NAV = [
    ("index.html", "总览"),
    ("app-violations.html", "移动应用看板"),
    ("algo-filing.html", "算法合规看板"),
]
# 2026-09-18（用户报障）：子导航里必须有「合规义务清单」这一项，且它指向**独立页面**。
#   此前把「标准与义务」改名成「法规库」、同时下线「法规原文」时，义务清单在子导航里
#   消失了；而它的落地页仍是法规库页（默认视图是「资料库」= 法条原文列表），
#   入口名与页面身份不符 —— 用户原话「点击合规义务清单，跳进去还是原来带法条原文库的页面」。
#   现在 duties.html 是独立页，与 standards.html 并列。
KB_NAV = [
    ("index.html", "总览"),
    ("standards.html", "法规库"),
    ("duties.html", "合规义务清单"),
    ("cases.html", "案例库"),
    ("citations.html", "高频引用法条"),
    ("wx.html", "公众号存档"),
]
# 2026-09-17（用户要求）：合规审计从「合规知识库」拿出来，单独成立一级模块「合规管理」。
# 边界：知识库回答「规则是什么」，合规管理回答「我们怎么把规则落下去」。
MANAGE_NAV = [
    ("index.html", "总览"),
    ("audit.html", "合规审计"),
]

BOUNDARY = {
    "news": "本模块回答<b>合规动态全貌</b>——今日增量、即将生效的法规（立法日历）、正在推进的监管行动、"
            "已发生的事件与应对建议、全球监管态势，一屏纵览。规则条文本身见 "
            "<a href=\"../kb/index.html\">合规知识库</a>。",
    "analysis": "本模块回答<b>怎么理解</b>——每篇都是「结论先行 + 官方原文深链 + 产品级图示」的"
                "专题研究；两个专项看板是同主题的数据底稿（通报库 / 备案清单），与长文互为参照。",
    "kb": None,  # 知识库总览已有「三个模块怎么分」区块，不再重复
    "manage": "本模块回答<b>怎么把规则落下去</b>——审计范围怎么定、过程怎么留痕、"
              "结论怎么变成整改任务。规则本身是什么见 <a href=\"../kb/index.html\">合规知识库</a>。",
}

GROUPS = [
    ("news", NEWS_NAV),
    ("analysis", ANALYSIS_NAV),
    ("kb", KB_NAV),
    ("manage", MANAGE_NAV),
]

MODULE_NAMES = {"news": "合规动态", "analysis": "法律分析", "kb": "合规知识库",
                "manage": "合规管理"}

# 模块内的「非导航项」页面（专题长文等）：不占子导航格位，但同样注入该模块的子导航。
# 否则读者从站外搜索直接落到这些页时会失去模块层级（架构一致性）。
# 2026-09-17（用户要求「法规库和法规原文重复了，只保留法规库就好」）：
# kb/texts.html（原文库阅读器）**从子导航下线**，不再是并列的模块入口 ——
# 它现在只是「法规库」里条目右侧「读原文」的落地页（下钻层，不是同层模块）。
# 但页面本身保留：① 7739 条「读原文」深链指向它；② 案例库依据列也直落站内原文。
# 所以它仍然要被注入子导航（否则从站外直接落到阅读页会失去模块层级），
# 并把「法规库」标为当前项（它就是这个页面所属的入口）。
EXTRA = {
    "kb": ["texts.html"],
    "analysis": ["pi-audit.html", "ai-label.html", "food-label.html",
                 "app-violation-pattern.html", "algo-filing-guide.html",
                 "dark-store-license.html", "penalty-read.html"],
}

# 下钻页 → 子导航里应被标为「当前」的同层入口
ACTIVE_ALIAS = {"kb/texts.html": "standards.html"}

BLOCK_RE = re.compile(r"<!-- SUBNAV:START -->.*?<!-- SUBNAV:END -->", re.S)


def build_block(module, nav, rel):
    cur = ACTIVE_ALIAS.get(rel.replace(os.sep, "/"), os.path.basename(rel))
    items = []
    for href, label in nav:
        on = " on" if href == cur else ""
        items.append(f'<a class="{on.strip()}" href="{href}">{label}</a>')
    html = [
        "<!-- SUBNAV:START -->",
        '<nav class="subnav"><span class="sn-cap">' + MODULE_NAMES[module] + '</span>'
        + "".join(items) + "</nav>",
    ]
    b = BOUNDARY.get(module)
    if b:
        html.append(f'<p class="mod-bound">{b}</p>')
    html.append("<!-- SUBNAV:END -->")
    return "\n".join(html)


def process(rel, module, nav, do_write=True):
    path = os.path.join(HERE, rel)
    if not os.path.exists(path):
        return f"  {rel} 不存在"
    h = open(path, encoding="utf-8").read()
    block = build_block(module, nav, rel)
    if BLOCK_RE.search(h):
        h = BLOCK_RE.sub(block, h, count=1)
    else:
        # 插入点：h1 之后第一个 </div></div>（hero 结束）
        i = h.find("</h1>")
        if i < 0:
            return f"  {rel} 无 h1，跳过"
        j = h.find("</div></div>", i)
        if j < 0:
            return f"  {rel} 找不到插入点，跳过"
        h = h[: j + len("</div></div>")] + "\n" + block + h[j + len("</div></div>"):]
    if do_write:
        open(path, "w", encoding="utf-8").write(h)
    return f"  {rel} ✓"


def main():
    do_write = "--check" not in sys.argv
    n = 0
    for module, nav in GROUPS:
        for href, _ in nav:
            rel = f"{module}/{href}"
            print(process(rel, module, nav, do_write))
            n += 1
        for href in EXTRA.get(module, []):
            rel = f"{module}/{href}"
            print(process(rel, module, nav, do_write))
            n += 1
    print(f"子导航：{n} 个页面" + ("" if do_write else "（仅检查）"))


if __name__ == "__main__":
    main()
