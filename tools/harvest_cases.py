#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案例库数据源：监管处罚 / 通报 / 典型案例的结构化采集

为什么需要它
------------
知识库里原本只有「高频法条页」顺带列出的少量案例，没有独立的案例库。
案例的事实要件（谁、因何事被罚、依据哪一条、罚多少、由谁罚）恰恰是合规判断最有用的部分，
因此单独建库、单独解析。

可枚举的官方源（均为机关官网站内页面，链接直达）
------------------------------------------------
· 市场监管总局「曝光台」         https://www.samr.gov.cn/zt/pgt/
· 市场监管总局「总局要闻」       https://www.samr.gov.cn/xw/zj/
· 中央网信办 App 违规通报（复用 sources/appviol/batches.json）
· 站点资讯流中已核验的处罚案例 / 执法通报（sources/news/items.jsonl）

技术要点
--------
samr 与 miit 用同一套 jpaas 前端渲染：列表来自
POST/GET /api-gateway/jpaas-publish-server/front/page/build/unit，
参数取自页面 <script queryData="...">，分页必须传 paramJson={"pageNo":N,"pageSize":R}。

用法：
  python3 tools/harvest_cases.py            # 增量
  python3 tools/harvest_cases.py --full     # 全量
  python3 tools/harvest_cases.py --pages 6  # 每个栏目最多翻 6 页
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from html import unescape
from urllib.parse import urlencode

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "sources", "cases", "cases.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

COLS = [
    ("市场监管总局·曝光台", "https://www.samr.gov.cn/zt/pgt/"),
    ("市场监管总局·总局要闻", "https://www.samr.gov.cn/xw/zj/"),
]
# 只收「处罚 / 通报 / 案例」类内容
HIT = re.compile(r"处罚|罚款|罚没|没收|查处|通报|典型案例|案例|约谈|曝光|违法|不合格|"
                 r"侵害|侵权|整治|执法")
SKIP = re.compile(r"招聘|招标|采购|公告$|会议|调研|签署|会见|致辞|论坛|培训|表彰|公示名单")

ORG_RULES = [
    ("市场监管总局", r"市场监管总局|国家市场监督管理总局"),
    ("中央网信办", r"中央网信办|国家互联网信息办公室|国家网信办"),
    ("工业和信息化部", r"工业和信息化部|工信部"),
    ("公安部", r"公安部|公安机关"),
    ("人民法院", r"人民法院|法院|最高人民法院"),
    ("人民检察院", r"人民检察院|检察院"),
    ("地方市场监管局", r"省市场监督管理局|市市场监督管理局|区市场监督管理局|"
                        r"省市场监管局|市市场监管局|县市场监管局"),
]
LAW_RE = re.compile(r"《([^》]{2,40})》")
MONEY_RE = re.compile(r"(?:罚款|罚没款|没收违法所得|处罚款)[^\d]{0,6}"
                      r"([\d,，.]+\s*(?:万)?元)")
CASE_TYPES = [
    ("反不正当竞争", r"不正当竞争|虚假宣传|混淆行为|商业贿赂|有奖销售|刷单|好评返现"),
    ("价格违法", r"价格|明码标价|哄抬|囤积|低价倾销|虚构原价|标价之外"),
    ("食品安全", r"食品|餐饮|农残|过期|标签|添加剂|餐具|无证经营|保质期"),
    ("计量与质量", r"计量|缺斤短两|电子秤|净含量|质量不合格|抽检|假冒|伪劣"),
    ("广告违法", r"广告|绝对化用语|疗效|代言|虚假广告"),
    ("消费者权益", r"消费者|预付|退费|会员|格式条款|个人信息"),
    ("个人信息与数据", r"个人信息|隐私|数据|App|APP|SDK|账号注销|收集使用"),
    ("网络与平台", r"网络交易|平台|电子商务|直播|外卖|刷单炒信|网络餐饮"),
]


def curl(url, referer=None, timeout=45, tries=3):
    for i in range(tries):
        cmd = ["curl", "-sL", "-m", str(timeout), url, "-H", "User-Agent: " + UA]
        if referer:
            cmd += ["-H", "Referer: " + referer]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.stdout and len(p.stdout) > 300:
            return p.stdout
        time.sleep(0.8 * (i + 1))
    return None


def jpaas_list(col_url, maxpages=8):
    """jpaas 前端渲染栏目 → [(title, url, date)]。"""
    html = curl(col_url)
    if not html:
        return []
    m = re.search(r'queryData="([^"]+)"', html)
    if not m:
        return []
    qd = json.loads(m.group(1).replace("'", '"'))
    api = "https://" + col_url.split("/")[2] + qd.get(
        "unitUrl", "/api-gateway/jpaas-publish-server/front/page/build/unit")
    out, page, total = [], 1, None
    while page <= maxpages:
        d = dict(qd)
        d["paramJson"] = json.dumps({"pageNo": page, "pageSize": 24})
        raw = curl(api + "?" + urlencode(d), referer=col_url)
        if not raw:
            break
        try:
            inner = json.loads(raw)["data"]["html"]
        except Exception:
            break
        cnt = re.search(r'count="(\d+)"', inner)
        rowsn = re.search(r'rows="(\d+)"', inner)
        if total is None:
            total = int(cnt.group(1)) if cnt else 0
        per = int(rowsn.group(1)) if rowsn else 24
        items = re.findall(r'href="([^"]+)"[^>]*title="([^"]*)"', inner)
        items += [(u, t) for u, t in re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{6,80})\s*</a>', inner)]
        if not items:
            break
        before = len(out)
        for u, t in items:
            t = re.sub(r"\s+", " ", unescape(t)).strip()
            if not t or not u.startswith("/"):
                continue
            full = "https://" + col_url.split("/")[2] + u
            out.append({"title": t, "url": full})
        if len(out) == before or page * per >= (total or 0):
            break
        page += 1
        time.sleep(0.35)
    seen, uniq = set(), []
    for r in out:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        uniq.append(r)
    return uniq


def textify(html):
    s = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


def parse_case(html, title, url, org_hint=""):
    body = textify(html)
    d = (re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})", body) or None)
    dt = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}" if d else ""
    org = org_hint or ""
    for name, pat in ORG_RULES:
        if re.search(pat, body[:1500]) or re.search(pat, title):
            org = name
            break
    laws = []
    for x in LAW_RE.findall(body[:4000]):
        x = x.strip()
        if 2 <= len(x) <= 40 and x not in laws:
            laws.append(x)
    laws = laws[:6]
    money = ["".join(x.split()) for x in MONEY_RE.findall(body)[:3]]
    ctype = "其他"
    for name, pat in CASE_TYPES:
        if re.search(pat, title) or (len(re.findall(pat, body[:2500])) >= 3):
            ctype = name
            break
    # 事实摘要 = 正文中去掉机关/版权装饰后的前 220 字
    fact = re.sub(r"(打印|纠错|来源：|分享到|扫一扫在手机|版权所有).{0,40}", " ", body)
    fact = re.sub(r"\s+", " ", fact).strip()
    i = fact.find(title[:8]) if len(title) >= 8 else -1
    if i > 0:
        fact = fact[i:]
    return {
        "title": title, "url": url, "date": dt, "org": org, "type": ctype,
        "laws": laws, "fines": money, "fact": fact[:260],
    }


def main():
    full = "--full" in sys.argv
    maxpages = 8
    if "--pages" in sys.argv:
        maxpages = int(sys.argv[sys.argv.index("--pages") + 1])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cases = []
    if os.path.exists(OUT) and not full:
        cases = json.load(open(OUT, encoding="utf-8")).get("cases", [])
    have = {c["url"] for c in cases}

    cand = {}
    for label, col in COLS:
        rows = jpaas_list(col, maxpages)
        hit = [r for r in rows if HIT.search(r["title"]) and not SKIP.search(r["title"])]
        print(f"▸ {label}：列表 {len(rows)} 条，命中 {len(hit)} 条（新 {sum(1 for r in hit if r['url'] not in have)}）")
        for r in hit:
            cand.setdefault(r["url"], r)

    # 复用 App 违规通报批次（本身就是监管通报案例）
    ap = os.path.join(HERE, "sources", "appviol", "batches.json")
    if os.path.exists(ap):
        for b in json.load(open(ap, encoding="utf-8")).get("batches", []):
            if b.get("url"):
                cand.setdefault(b["url"], {"title": b.get("title", ""), "url": b["url"],
                                           "_preset": b})

    # 站点资讯流里已核验的处罚 / 通报类条目
    np_ = os.path.join(HERE, "sources", "news", "items.jsonl")
    if os.path.exists(np_):
        for line in open(np_, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                it = json.loads(line)
            except Exception:
                continue
            if it.get("kind") in ("处罚案例", "执法通报", "专项行动"):
                cand.setdefault(it.get("url", ""), {
                    "title": it.get("title", ""), "url": it.get("url", ""),
                    "_preset": {"title": it.get("title", ""), "url": it.get("url", ""),
                                "date": it.get("date", ""), "org": it.get("org", ""),
                                "categories": [], "kind": it.get("kind", "")}})

    todo = [(u, r) for u, r in cand.items() if u and u not in have]
    print(f"\n▸ 待解析 {len(todo)} 条（已有 {len(cases)} 条）")
    for i, (u, r) in enumerate(todo, 1):
        preset = r.get("_preset")
        if preset:
            cases.append({
                "title": preset.get("title", ""), "url": u,
                "date": preset.get("date", ""), "org": preset.get("org", ""),
                "type": ("个人信息与数据" if "App" in preset.get("title", "")
                         else "其他"),
                "laws": ["App违法违规收集使用个人信息行为认定方法"]
                if "App" in preset.get("title", "") else [],
                "fines": [],
                "fact": "、".join(preset.get("categories") or [])[:260],
                "kind": preset.get("kind", "监管通报"),
            })
            continue
        html = curl(u, referer=("https://www.samr.gov.cn/"
                                if "samr.gov.cn" in u else None), timeout=50)
        if not html:
            continue
        c = parse_case(html, r["title"], u,
                       org_hint=("市场监管总局" if "samr.gov.cn" in u else ""))
        c["kind"] = "行政处罚/通报"
        cases.append(c)
        if i % 15 == 0:
            print(f"  {i}/{len(todo)} …", flush=True)
        time.sleep(0.3)

    # 去重 + 排序
    seen, uniq = set(), []
    for c in sorted(cases, key=lambda x: x.get("date") or "", reverse=True):
        if not c.get("url") or c["url"] in seen:
            continue
        seen.add(c["url"])
        uniq.append(c)

    from collections import Counter
    stat = Counter(c.get("type", "其他") for c in uniq)
    orgs = Counter(c.get("org") or "未标注" for c in uniq)
    json.dump({
        "meta": {
            "updated": date.today().isoformat(),
            "count": len(uniq),
            "sources": [c[1] for c in COLS] + [
                "https://search.cac.gov.cn/cms/cmsadmin/infopub/gjjs.jsp"],
            "note": "案例来源为监管机关官网站内页面（曝光台、要闻、通报），"
                    "字段由正文解析得出，处罚幅度以官方原文为准。",
            "by_type": dict(stat), "by_org": dict(orgs),
        },
        "cases": uniq,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"\n✓ 写入 {OUT}：{len(uniq)} 条　{os.path.getsize(OUT)/1024:.0f} KB")
    print("  类型分布：", stat.most_common(8))
    print("  机关分布：", orgs.most_common(6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
