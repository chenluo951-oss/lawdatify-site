#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""省级网信办 App 通报 · 来源探测与候选枚举（立法链路之外的第三条地方链路）

背景
----
App 违规通报库原有两条链路：① 国家层面（工信部 / 国家网信办 / 公安部 / 病毒中心）；
② 地方层面 = **28 个省级通信管理局**。**省级网信办**从未作为独立来源接入 ——
用户 2026-09-15 指出「机构统计里没有省级网信办」，即指此处。

关键事实（本脚本实证）
--------------------
· 省级网信办没有像省通管局（`{abbr}ca.miit.gov.cn` + 统一 jpaas 列表接口）那样的统一入口，
  官网域名命名规则也不统一（`{abbr}wx.gov.cn` / `{abbr}wxb.gov.cn` / `{abbr}xc.gov.cn` /
  `wxb.{abbr}.gov.cn`），须逐一探测。
· ⚠️ **省网信办官网大量「转载」国家层面通报**（如安徽网信网转载中央网信办秘书局
  《关于30款App个人信息收集使用问题的通报》、内蒙古网信网转载国家网络与信息安全
  信息通报中心的 70 款通报）。若不加区分地入库，会把同一份国家通报重复计入国家主体，
  同时制造不存在的「省级通报量」——因此本脚本按**正文落款**判定「原创 / 转载」，
  只有落款为本省网信办的才算该省原创通报。

用法
----
  python3 tools/harvest_cac_prov.py --probe      # 只探测域名可达性
  python3 tools/harvest_cac_prov.py              # 探测 + 枚举候选通报（默认）
  python3 tools/harvest_cac_prov.py --pages 2    # 每个栏目翻几页
产出：sources/appviol/cac_prov_sites.json
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from urllib.parse import quote, urljoin

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(HERE, "sources", "appviol")
OUT = os.path.join(OUTDIR, "cac_prov_sites.json")

# 省级网信办官网（2026-09-15 实测可达；未列出的省份暂无独立官网或未探测到）
SITES = {
    "北京市": "http://www.bjw.gov.cn",
    "上海市": "https://www.shxc.gov.cn",
    "重庆市": "http://www.cqwx.gov.cn",
    "内蒙古自治区": "http://www.nmgwx.gov.cn",
    "辽宁省": "https://www.lnwx.gov.cn",
    "江苏省": "https://www.jswx.gov.cn",
    "浙江省": "https://www.zjwx.gov.cn",
    "安徽省": "https://www.ahwx.gov.cn",
    "福建省": "https://www.fjwx.gov.cn",
    "山东省": "https://www.sdxc.gov.cn",
    "广西壮族自治区": "http://www.gxxc.gov.cn",
    "云南省": "https://www.ynxc.gov.cn",
    "贵州省": "https://www.gzwxb.gov.cn",
    "西藏自治区": "https://wxb.xzdw.gov.cn",
}

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
APP_RX = re.compile(r"(App|APP|应用|小程序|SDK)[^。，,]{0,12}(通报|查处|下架|治理|违规|侵害|问题)"
                    r"|(通报|查处|下架)[^。，,]{0,12}(App|APP|应用|小程序)")
COL_KW = ("通报", "公示", "个人信息", "数据安全", "网络数据", "执法", "治理",
          "要闻", "动态", "工作", "监管", "安全")
# 落款机关 → 判定
NATIONAL_ORG = re.compile(r"中央网信办|国家互联网信息办公室|国家网信办|工业和信息化部|"
                          r"公安部|国家计算机病毒应急处理中心|国家网络与信息安全信息通报中心|"
                          r"国家市场监督管理总局|中国互联网协会|中国网络空间安全协会")


def curl(url, t=15, out=None):
    cmd = ["curl", "-s", "-L", "-A", UA, "--max-time", str(t)]
    if out:
        cmd += ["-o", out]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=t + 12)
        return r.stdout or ""
    except Exception:
        return ""


def textify(html):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    import html as H
    return re.sub(r"\s+", " ", H.unescape(s))


def anchors(html, base):
    out, seen = [], set()
    for u, t in re.findall(r'href=["\']([^"\']+)["\'][^>]*>\s*([^<]{2,60}?)\s*<', html):
        if u.startswith(("javascript", "#", "mailto")) or u in seen:
            continue
        seen.add(u)
        out.append((urljoin(base, u), re.sub(r"\s+", "", t)))
    return out


# 落款机关（真发布机关）：机关名 + 紧跟日期，是最强的署名信号。
# ⚠️ 不能只扫「页面里出现过哪个机关名」——省站页脚常年挂着本省网信办名称，
#    那样每个页面都会被误判成「本省原创」（实测把工信部的转载全判成了江苏原创）。
SIG_RX = re.compile(
    r"([\u4e00-\u9fff]{2,26}?(?:互联网信息办公室|网信办|网络安全和信息化委员会办公室|"
    r"信息通信管理局|网络与信息安全信息通报中心|计算机病毒应急处理中心|"
    r"公安厅|公安局|网安局|市场监督管理局|市场监督管理总局|协会|中心|部|厅|局))"
    r"[\s　]{0,4}(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")


def judge_origin(body, own_org=""):
    """按正文**落款署名（机关名 + 日期）**判定发布机关，再区分原创 / 转载。

    省网信办官网的 App 通报里，绝大多数是**转载国家层面通报**（工信部 / 中央网信办 /
    国家网络与信息安全信息通报中心），只有少数是本省网信办自己组织的检测通报。
    两者混在一起统计会既重复计数、又虚构省级通报量，所以这里必须把署名挖出来。
    """
    hits = SIG_RX.findall(body[-1500:])
    if not hits:
        return "未知", "", ""
    org = hits[-1][0].strip()
    if own_org and own_org.rstrip("办公室")[:3] in org:
        return "原创", org, hits[-1][1]
    if NATIONAL_ORG.search(org):
        return "转载", org, hits[-1][1]
    return "其他", org, hits[-1][1]


def scan_site(item, pages=1):
    name, base = item
    home = curl(base, 15)
    if not home:
        return dict(province=name, base=base, status="不可达", cols=[], docs=[])
    cols = []
    for u, t in anchors(home, base):
        if len(t) <= 14 and any(k in t for k in COL_KW) and re.search(r"gov\.cn", u):
            cols.append((u, t))
    # 去重 + 只保留看起来是栏目的（目录式或以 index/list 结尾）
    seen, cols2 = set(), []
    for u, t in cols:
        if u in seen:
            continue
        seen.add(u)
        if u.endswith("/") or re.search(r"(index|list|column)", u, re.I) or u.count("/") <= 4:
            cols2.append((u, t))
    docs = []
    for cu, ct in cols2[:8]:
        for pg in range(1, pages + 1):
            pu = cu if pg == 1 else re.sub(r"index(_1)?\.(html?|jspx?|shtml)$",
                                           f"index_{pg}.html", cu)
            if pg > 1 and pu == cu:
                pu = cu.rstrip("/") + f"/index_{pg}.html"
            h = curl(pu, 12)
            if not h:
                break
            got = 0
            for au, at in anchors(h, pu):
                if APP_RX.search(at) and at not in [d["title"] for d in docs]:
                    docs.append({"title": at, "url": au, "column": ct, "page": pg})
                    got += 1
            if got == 0 and pg > 1:
                break
    return dict(province=name, base=base, status="可达", n_cols=len(cols2),
                cols=[{"url": u, "name": t} for u, t in cols2], docs=docs)


def deep(item, pages):
    r = scan_site(item, pages)
    prov = r["province"]
    own = prov + "互联网信息办公室"
    for d in r["docs"][:40]:
        body = textify(curl(d["url"], 20))
        d["chars"] = len(body)
        nums = [int(x) for x in re.findall(r"(\d{1,4})\s*款", body)]
        d["declared"] = max(nums) if nums else None
        origin, org, sig_date = judge_origin(body, own)
        d["origin"], d["signed_by"], d["signed_at"] = origin, org, sig_date
        m = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})", d["url"])
        d["date_hint"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""
    return r


def main():
    argv = sys.argv[1:]
    pages = int(argv[argv.index("--pages") + 1]) if "--pages" in argv else 1
    probe_only = "--probe" in argv
    os.makedirs(OUTDIR, exist_ok=True)
    items = list(SITES.items())
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        fn = (lambda it: scan_site(it, 1)) if probe_only else (lambda it: deep(it, pages))
        results = list(ex.map(fn, items))
    ncol = sum(1 for r in results if r["status"] == "可达")
    ndoc = sum(len(r["docs"]) for r in results)
    nown = sum(1 for r in results for d in r["docs"] if d.get("origin") == "原创")
    nrep = sum(1 for r in results for d in r["docs"] if d.get("origin") == "转载")
    data = {
        "_note": "省级网信办官网探测结果（App 违规通报链路）。signed_by 为按正文落款署名"
                 "（机关名+日期）挖出的**真发布机关**：原创=本省网信办自行组织的检测通报；"
                 "转载=国家层面通报（工信部/中央网信办/国家网络与信息安全信息通报中心）的"
                 "地方转载页——转载不得计入机构统计，否则同一份国家通报会被重复计数。",
        "probed": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sites": results,
        "summary": {"probed": len(items), "reachable": ncol, "candidates": ndoc,
                    "origin_docs": nown, "reprint_docs": nrep,
                    "reachable_list": [r["province"] for r in results if r["status"] == "可达"]},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"探测 {len(items)} 省 → 可达 {ncol}；候选 App 通报 {ndoc} 份"
          f"（省级原创 {nown} / 国家转载 {nrep}）")
    for r in results:
        if r["status"] != "可达":
            print(f"  ✗ {r['province']}")
        elif r["docs"]:
            o = sum(1 for d in r["docs"] if d.get("origin") == "原创")
            p = sum(1 for d in r["docs"] if d.get("origin") == "转载")
            print(f"  ✓ {r['province']:12s} 栏目{r['n_cols']:2d} 候选{len(r['docs']):3d} "
                  f"原创{o:2d} 转载{p:3d}")
        else:
            print(f"  ○ {r['province']:12s} 栏目{r['n_cols']:2d} 未发现 App 通报条目")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
