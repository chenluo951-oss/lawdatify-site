#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""省通信管理局「侵害用户权益 APP 通报」栏目自动发现与枚举。

背景
----
全国 31 个省级行政区中，29 个省（区、市）设有独立通信管理局子站
（河北、海南无独立子站，业务并入部里），域名规律 `https://{abbr}ca.miit.gov.cn/`。
每个省局**自成一套通报序列**（如「浙江省通信管理局关于侵害用户权益行为的
APP（小程序）通报（2026年第6批）」），是国家序列之外独立且互不重叠的一路数据源。

技术路径（与工信部完全同构）
--------------------------
省局站点是 jpaas CMS 前端渲染，栏目列表不在 HTML 里，而来自：
  GET /api-gateway/jpaas-publish-server/front/page/build/unit
参数藏在栏目页的 `<script queryData="{...}">` 里；**分页必须追加
`paramJson={"pageNo":N,"pageSize":R}`**（只传 pageNo 接口永远返回第 1 页）。

产出：sources/appviol/prov_columns.json —— 每个省局命中的通报栏目与文书清单，
供 harvest_app_violations.py 读取后抓正文。
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
from html import unescape
from urllib.parse import urlencode

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "sources", "appviol", "prov_columns.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
API = "/api-gateway/jpaas-publish-server/front/page/build/unit"

# 域名代号 → 省（区、市）名。实测 29 个可达，河北/海南无独立子站。
PROV = {
    "bj": "北京市", "tj": "天津市", "sh": "上海市", "cq": "重庆市",
    "sx": "山西省", "nm": "内蒙古自治区", "ln": "辽宁省", "jl": "吉林省",
    "hlj": "黑龙江省", "js": "江苏省", "zj": "浙江省", "ah": "安徽省",
    "fj": "福建省", "jx": "江西省", "sd": "山东省", "hn": "河南省",
    "hb": "湖北省", "gd": "广东省", "gx": "广西壮族自治区", "sc": "四川省",
    "gz": "贵州省", "yn": "云南省", "xz": "西藏自治区", "shx": "陕西省",
    "gs": "甘肃省", "qh": "青海省", "nx": "宁夏回族自治区", "xj": "新疆维吾尔自治区",
}

# 栏目路径候选（省局模板不统一，逐个试）。
# 命名规律实测：网络安全管理/互联网管理/电信和互联网管理 三种叫法 → wlaqgl / hlwgl / dxhhlwgl / wlgl / wlaq。
COL_CAND = [
    "/zwgk/wlaqgl/index.html", "/zwgk/tzgg/index.html", "/xxgk/tzgg/index.html",
    "/xwdt/tzgg/index.html", "/zwgk/hlwgl/index.html", "/gzcy/gggs/index.html",
    "/zwgk/wlgl/index.html", "/xwzx/tzgg/index.html", "/zwgk/dxhhlwgl/index.html",
    "/zwgk/hlwgl/gztz/index.html", "/zwgk/tzgg/gggs/index.html", "/zwgk/tzgg/gg/index.html",
    "/zwgk/wlaq/index.html", "/xxgk/wlaq/index.html",
    "/zwgk/txfz/index.html", "/zwgk/txfzgl/index.html", "/zwgk/dxgl/index.html",
    "/zwgk/dxgl/fwjd/index.html", "/xwdt/index.html", "/xwdt/gzdt/index.html",
    "/zwgk/hlwgl/tzgg/index.html", "/zwgk/xxtxgl/index.html", "/ztzl/wlaq/index.html",
]

HIT = re.compile(r"侵害用户权益|用户权益行为|未按要求完成整改|不合格APP|违规收集|"
                 r"个人信息.*(?:通报|名单)|APP.*(?:通报|名单|下架|整改)")
SKIP = re.compile(r"备案|招聘|采购|招标|职称|考试|许可|年报|指南|解读|问卷|征集")

# 栏目页 HTML 里同时会带出文章链接，可直接反推栏目目录
ART = re.compile(r'href="(/[^"]*)/art/(\d{4})/art_[0-9a-f]+\.html"')


def curl(url, timeout=30, referer=None):
    cmd = ["curl", "-sS", "-m", str(timeout), "-H", "User-Agent: " + UA]
    if referer:
        cmd += ["-H", "Referer: " + referer]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore")
        return p.stdout or ""
    except Exception:
        return ""


def query_data(html):
    m = re.search(r'queryData="(\{[^"]+\})"', html)
    if not m:
        m = re.search(r"queryData='(\{[^']+\})'", html)
        if not m:
            return None
    raw = m.group(1).replace("&quot;", '"')
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw.replace("'", '"'))
        except Exception:
            return None


def unit_list(domain, qd, max_page=40):
    """用 build/unit 接口翻页取列表（返回 (标题, url, 日期)）。"""
    out, page = [], 1
    per = 24
    while page <= max_page:
        d = dict(qd)
        d["paramJson"] = json.dumps({"pageNo": page, "pageSize": per})
        raw = curl("https://" + domain + API + "?" + urlencode(d),
                   referer="https://" + domain + "/")
        if not raw:
            break
        try:
            inner = json.loads(raw)["data"]["html"]
        except Exception:
            break
        items = re.findall(
            r'href="([^"]*art_[^"]*)"[^>]*title="([^"]*)"[^>]*>\s*<i></i>.*?'
            r'<span class="fr">([\d-]+)</span>', inner, re.S)
        if not items:
            items = [(u, t, "") for u, t in re.findall(
                r'href="([^"]*art_[^"]*)"[^>]*title="([^"]*)"', inner)]
        if not items:
            break
        before = len(out)
        for u, t, dt in items:
            out.append({"title": re.sub(r"\s+", " ", unescape(t)).strip(),
                        "url": u if u.startswith("http") else "https://" + domain + u,
                        "date": dt})
        rows = re.search(r'rows="(\d+)"', inner)
        cnt = re.search(r'count="(\d+)"', inner)
        if rows:
            per = int(rows.group(1)) or per
        total = int(cnt.group(1)) if cnt else 0
        if len(out) == before or (total and page * per >= total):
            break
        page += 1
        time.sleep(0.25)
    seen, uniq = set(), []
    for r in out:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        uniq.append(r)
    return uniq


def discover(abbr):
    domain = abbr + "ca.miit.gov.cn"
    prov = PROV[abbr]
    home = curl("https://" + domain + "/")
    if len(home) < 500:
        return {"abbr": abbr, "domain": domain, "province": prov, "ok": False,
                "columns": [], "docs": []}

    # 1) 候选栏目 + 从首页反推出的栏目目录
    cand = list(COL_CAND)
    for d, _y in set(ART.findall(home)):
        if re.search(r"(tzgg|gggs|wlaq|hlwgl|wlgl|xxtx)", d):
            cand.append(d + "/index.html")
    # 首页若直接有命中的文章，其所在栏目也纳入
    for u, t in re.findall(r'href="(/[^"]*art_[^"]*)"[^>]*>(.*?)</a>', home, re.S):
        t = re.sub(r"<[^>]+>", "", t)
        if HIT.search(t) and not SKIP.search(t):
            cand.append(re.sub(r"/art/\d{4}/art_[0-9a-f]+\.html$", "/index.html", u))

    cols, docs = [], {}
    for c in dict.fromkeys(cand):
        html = curl("https://" + domain + c)
        if len(html) < 800 or "ColumnName" not in html:
            continue
        qd = query_data(html)
        if not qd:
            continue
        rows = unit_list(domain, qd)
        hit = [r for r in rows
               if HIT.search(r["title"]) and not SKIP.search(r["title"])]
        if not hit:
            continue
        cols.append({"path": c, "total_rows": len(rows), "hits": len(hit)})
        for r in hit:
            docs[r["url"]] = r
    return {"abbr": abbr, "domain": domain, "province": prov, "ok": True,
            "columns": cols, "docs": list(docs.values())}


def main():
    only = sys.argv[1:] or sorted(PROV)
    res = []
    with cf.ThreadPoolExecutor(6) as ex:
        for r in ex.map(discover, only):
            res.append(r)
            n = len(r["docs"])
            print(f"{'✓' if r['ok'] else '✗'} {r['province']:<12}{r['domain']:<24}"
                  f"栏目 {len(r['columns'])}　命中通报 {n}", flush=True)
            for c in r["columns"]:
                print(f"     └ {c['path']}  列表 {c['total_rows']}  命中 {c['hits']}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"updated": time.strftime("%Y-%m-%d"),
               "provinces": res,
               "docs": [d for r in res for d in r["docs"]]},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = sum(len(r["docs"]) for r in res)
    print(f"\n合计 {len(res)} 个省局，{tot} 份通报文书 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
