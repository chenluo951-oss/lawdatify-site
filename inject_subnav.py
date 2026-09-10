#!/usr/bin/env python3
"""模块子导航 + 边界一句话（幂等注入）。

三个一级模块各有明确的「回答什么问题」，用 SUBNAV:START/END 幂等块注入，
避免同一条信息在多个模块重复出现、也避免名称混淆：

  监管雷达   何时生效 / 何地监管 / 何种行动（时间 + 地域维度，前瞻）
  合规资讯   发生了什么 / 我们该做什么（事件流 + 应对，日更）
  合规知识库 规则本身是什么（法规标准原文 + 义务拆解 + 草案，长期稳定）
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

RADAR_NAV = [
    ("index.html", "总览"),
    ("calendar.html", "立法日历"),
    ("actions.html", "监管动向"),
    ("map.html", "全球监管地图"),
]
NEWS_NAV = [
    ("index.html", "领域动态"),
    ("briefs.html", "简报归档"),
    ("actions.html", "应对建议"),
]
KB_NAV = [
    ("index.html", "总览"),
    ("standards.html", "标准与义务"),
]

BOUNDARY = {
    "radar": "本模块回答<b>何时生效、何地监管、何种行动</b>——按时间与地域重排监管信息。"
             "已发生的事件与应对建议见 <a href=\"../news/index.html\">合规资讯</a>；"
             "规则条文本身见 <a href=\"../kb/index.html\">合规知识库</a>。",
    "news": "本模块回答<b>已经发生了什么、我们该做什么</b>——监管动态逐条附官方深链，"
            "并从简报沉淀应对建议。未来的生效节点见 <a href=\"../radar/index.html\">监管雷达</a>；"
            "规则条文本身见 <a href=\"../kb/index.html\">合规知识库</a>。",
    "kb": None,  # 知识库总览已有「三个模块怎么分」区块，不再重复
}

GROUPS = [
    ("radar", RADAR_NAV),
    ("news", NEWS_NAV),
    ("kb", KB_NAV),
]

BLOCK_RE = re.compile(r"<!-- SUBNAV:START -->.*?<!-- SUBNAV:END -->", re.S)


def build_block(module, nav, rel):
    cur = os.path.basename(rel)
    items = []
    for href, label in nav:
        on = " on" if href == cur else ""
        items.append(f'<a class="{on.strip()}" href="{href}">{label}</a>')
    html = ['<!-- SUBNAV:START -->', '<nav class="subnav">' + "".join(items) + "</nav>"]
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
    print(f"子导航：{n} 个页面" + ("" if do_write else "（仅检查）"))


if __name__ == "__main__":
    main()
