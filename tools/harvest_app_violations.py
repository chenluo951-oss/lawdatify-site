#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""移动应用违规治理专项 · 违规通报历史库

覆盖的官方通报源（全部为发布机关官网原文页，链接可直达）
------------------------------------------------------
① 工业和信息化部《关于侵害用户权益行为的APP（SDK）通报》
   栏目 https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html
   总第 1 批（2019-12）起连续编号，是该领域最完整的历史序列。
② 中央网信办《关于 N 款 App 个人信息收集使用问题的通报》
   通过网信办站内检索（search.cac.gov.cn）枚举，覆盖 2019 年以来的各期通报。
③ 市场监管总局 / 公安部 等联合通报（同批出现于上述两条序列内，按发布机关落库）。

技术要点
--------
· 工信部栏目页是前端渲染，列表来自 /api-gateway/jpaas-publish-server/front/page/build/unit
  （参数藏在页面 <script queryData="...">），分页靠追加 pageNo=N，返回 JSON 内 HTML。
· 网信办站内检索必须带 Referer: https://www.cac.gov.cn/，否则 403。
· 网信办通报名单以图片（PNG）内嵌，App 明细用 macOS Vision OCR 抽取（tools/vision_ocr）。

用法：
  python3 tools/harvest_app_violations.py            # 增量
  python3 tools/harvest_app_violations.py --full     # 全量重抓
  python3 tools/harvest_app_violations.py --no-ocr   # 只抓批次，不做明细 OCR
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from html import unescape
from urllib.parse import quote, urlencode

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(HERE, "sources", "appviol")
IMGDIR = os.path.join(HERE, "sources", ".cache", "appviol")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MIIT_API = "https://www.miit.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"


def curl(url, referer=None, out=None, timeout=60, tries=3):
    for i in range(tries):
        cmd = ["curl", "-sL", "-m", str(timeout), url, "-H", "User-Agent: " + UA]
        if referer:
            cmd += ["-H", "Referer: " + referer]
        if out:
            cmd += ["-o", out, "-w", "%{http_code}"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if out:
            if p.stdout.strip() == "200" and os.path.exists(out) and os.path.getsize(out) > 1000:
                return True
            time.sleep(1.0 * (i + 1))
            continue
        if p.stdout and len(p.stdout) > 200:
            return p.stdout
        time.sleep(1.0 * (i + 1))
    return None


def textify(html):
    s = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", "\n", s)
    s = unescape(s)
    return [re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip()]


# --------------------------------------------------------------- 工信部
MIIT_COLS = [
    ("tzgg", "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"),
    ("gzdt", "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/gzdt/index.html"),
]
MIIT_HIT = re.compile(r"侵害用户权益|APP（SDK）|APP通报|App通报|应用软件|智能终端|个人信息")


def miit_list(col_url, tag="当前栏目_list"):
    """工信部栏目列表（前端渲染，数据来自 jpaas build/unit 接口）。

    分页参数不是 pageNo 直传，而是嵌套 JSON：paramJson={"pageNo":N,"pageSize":R}
    （见 /cms_files/filemanager/script/ajax/page/page.js）—— 少了它接口只会重复返回第 1 页。
    """
    html = curl(col_url)
    if not html:
        return []
    m = re.search(r'queryData="([^"]+)"', html)
    if not m:
        return []
    qd = json.loads(m.group(1).replace("'", '"'))
    out, page = [], 1
    total = None
    while page <= 40:
        d = dict(qd)
        d["paramJson"] = json.dumps({"pageNo": page, "pageSize": 24})
        raw = curl(MIIT_API + "?" + urlencode(d), referer=col_url)
        if not raw:
            break
        try:
            inner = json.loads(raw)["data"]["html"]
        except Exception:
            break
        cnt = re.search(r'count="(\d+)"', inner)
        rowsn = re.search(r'rows="(\d+)"', inner)
        items = re.findall(
            r'href="([^"]*art_[^"]*)"[^>]*title="([^"]*)"[^>]*>\s*<i></i>.*?<span class="fr">([\d-]+)</span>',
            inner, re.S)
        if not items:
            break
        before = len(out)
        for u, t, dt in items:
            t = re.sub(r"\s+", " ", unescape(t)).strip()
            out.append({"title": t, "url": "https://www.miit.gov.cn" + u, "date": dt})
        if total is None:
            total = int(cnt.group(1)) if cnt else len(items)
        per = int(rowsn.group(1)) if rowsn else 24
        if len(out) == before or page * per >= (total or 0):
            break
        page += 1
        time.sleep(0.4)
    # 去重
    seen, uniq = set(), []
    for r in out:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        uniq.append(r)
    return uniq


# --------------------------------------------------------------- 网信办
CAC_QUERIES = [
    "App个人信息收集使用问题",
    "违法违规收集使用个人信息",
    "App违法违规收集使用个人信息",
    "SDK个人信息收集使用",
    "App专项治理",
    "侵害个人信息权益的违法违规App",
    "移动互联网应用程序个人信息",
    "小程序个人信息",
    "App个人信息保护",
    "用户权益 通报",
]
CAC_SEARCH = "https://search.cac.gov.cn/cms/cmsadmin/infopub/gjjs.jsp"
CAC_PARAMS = {"pubtype": "S", "pubpath": "portal",
              "templetid": "1563339473064626", "sort": "1",
              "webappcode": "A09", "searchdir": "A09"}
CAC_HIT = re.compile(r"App|APP|应用程序|小程序|SDK|移动互联网")
CAC_SKIP = re.compile(r"解读|答记者问|征求意见|宣传周|论坛|培训|招聘|招标")


def cac_search(kw, maxpage=6):
    out = []
    for page in range(1, maxpage + 1):
        params = dict(CAC_PARAMS)
        params["huopro"] = kw
        params["mustpro"] = ""
        params["notpro"] = ""
        params["inpro"] = ""
        params["page"] = page
        url = CAC_SEARCH + "?" + urlencode(params)
        html = curl(url, referer="https://www.cac.gov.cn/", timeout=45)
        if not html:
            break
        items = re.findall(
            r'<li class="list-item"><a href="([^"]+)"[^>]*>(.*?)</a>'
            r'<span class="search_time">([\d\-: ]+)</span>', html, re.S)
        if not items:
            break
        for u, t, dt in items:
            t = re.sub(r"<[^>]+>", "", unescape(t)).strip()
            t = re.sub(r"^»\s*", "", t)
            u = u if u.startswith("http") else "https:" + u
            out.append({"title": t, "url": u, "date": dt.strip()[:10], "q": kw})
        time.sleep(0.5)
    return out


# --------------------------------------------------------------- 批次解析
ORGS = [
    ("中央网信办", "中央网信办"),
    ("工业和信息化部", "工业和信息化部"),
    ("公安部", "公安部"),
    ("市场监管总局", "市场监管总局"),
    ("国家网信办", "国家互联网信息办公室"),
    ("国家互联网信息办公室", "国家互联网信息办公室"),
]
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "十一": 11, "十二": 12}


def batch_no(title):
    m = re.search(r"（?(\d{4})年第(\d+)批[，,]\s*总第(\d+)批", title)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None, None, None


def parse_batch(page_html, title, url, dt):
    lines = textify(page_html)
    body = " ".join(lines)
    # 涉及款数
    nums = [int(x) for x in re.findall(r"(\d{2,4})\s*款", body)]
    apps_n = max(nums) if nums else None
    # 问题类别：一、xxx（详见下表）
    cats = []
    for m in re.finditer(r"[（(]?([一二三四五六七八九十]{1,2})[）)]?、\s*([^。；;]{4,80}?)"
                         r"[（(]?(?:详见下表|见下表|名单见附表)?", body):
        c = re.sub(r"\s+", "", m.group(2))
        c = re.sub(r"^(?:关于|针对)", "", c)
        if 4 <= len(c) <= 60 and not re.search(r"通报|公告|依据|现将", c):
            cats.append(c)
    seen, uc = set(), []
    for c in cats:
        if c not in seen:
            seen.add(c)
            uc.append(c)
    uc = uc[:8]
    orgs = [full for k, full in ORGS if k in body[:1200]]
    imgs = re.findall(r'<img[^>]+src="([^"]+)"', page_html)
    imgs = [("https:" + i if i.startswith("//") else i) for i in imgs
            if re.search(r"rootimages|uploadimg|\.png|\.jpg", i, re.I)]
    imgs = [i for i in imgs if not re.search(r"logo|conac|QR-|search|fold|CAC\.png", i, re.I)]
    return {
        "title": title,
        "url": url,
        "date": dt,
        "org": orgs[0] if orgs else ("工业和信息化部" if "miit.gov.cn" in url else "中央网信办"),
        "orgs": orgs,
        "apps_count": apps_n,
        "categories": uc,
        "images": imgs,
        "kind": "App(SDK)通报" if "SDK" in title else "App通报",
    }


def ocr(img_path):
    """macOS Vision OCR → 行列表。"""
    exe = os.path.join(HERE, "tools", "vision_ocr")
    if not os.path.exists(exe):
        return []
    p = subprocess.run([exe, img_path, "--json"], capture_output=True, text=True)
    try:
        d = json.loads(p.stdout)
        return [x.get("text", "") for x in (d.get("lines") or [])]
    except Exception:
        return [x for x in p.stdout.splitlines() if x.strip()]


def main():
    full = "--full" in sys.argv
    no_ocr = "--no-ocr" in sys.argv
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(IMGDIR, exist_ok=True)

    meta_path = os.path.join(OUTDIR, "batches.json")
    old = {}
    if os.path.exists(meta_path) and not full:
        old = {b["url"]: b for b in json.load(open(meta_path, encoding="utf-8")).get("batches", [])}

    # 1) 枚举批次
    found = {}
    print("▸ 工业和信息化部（APP 侵害用户权益专项整治栏目）")
    for tag, col in MIIT_COLS:
        rows = miit_list(col)
        hit = [r for r in rows if MIIT_HIT.search(r["title"])]
        for r in hit:
            found[r["url"]] = r
        print(f"  {tag}: 列表 {len(rows)} 条，命中通报 {len(hit)} 条")
    print("▸ 中央网信办（站内检索枚举）")
    for kw in CAC_QUERIES:
        rows = cac_search(kw)
        hit = [r for r in rows
               if CAC_HIT.search(r["title"]) and not CAC_SKIP.search(r["title"])
               and re.search(r"通报|查处|治理|专项行动|问题", r["title"])]
        for r in hit:
            found.setdefault(r["url"], {"title": r["title"], "url": r["url"],
                                        "date": r["date"]})
        print(f"  «{kw}» 命中 {len(hit)}　累计 {len(found)}", flush=True)

    # 2) 抓正文
    print(f"\n▸ 抓取通报正文（共 {len(found)} 个批次）")
    batches = []
    for i, (u, r) in enumerate(sorted(found.items()), 1):
        if u in old and not full:
            b = old[u]
            batches.append(b)
            continue
        html = curl(u, referer="https://www." + ("cac.gov.cn/" if "cac.gov.cn" in u
                                                  else "miit.gov.cn/"), timeout=60)
        if not html:
            print(f"  ! 失败 {r['title'][:36]}")
            continue
        y, n, tot = batch_no(r["title"])
        b = parse_batch(html, r["title"], u, r.get("date") or "")
        b.update({"year": y, "batch_in_year": n, "batch_total": tot})
        batches.append(b)
        if i % 10 == 0:
            print(f"  {i}/{len(found)} …", flush=True)
        time.sleep(0.35)

    # 按日期排序
    batches.sort(key=lambda b: (b.get("date") or "", b.get("batch_total") or 0), reverse=True)

    # 3) 图片 OCR → App 明细（网信办通报的名单元）
    apps = []
    if not no_ocr:
        need = [b for b in batches if b.get("images") and
                ("cac.gov.cn" in b["url"] or "miit.gov.cn" in b["url"])]
        print(f"\n▸ OCR 抽取 App 明细（{len(need)} 个批次含名单图）")
        for k, b in enumerate(need, 1):
            for j, img in enumerate(b["images"][:12]):
                p = os.path.join(IMGDIR, re.sub(r"\W+", "_", b["url"])[-40:] + f"_{j}.png")
                if not os.path.exists(p):
                    if not curl(img, referer=b["url"], out=p, timeout=60):
                        continue
                lines = ocr(p)
                if not lines:
                    continue
                apps += rows_from_ocr(lines, b)
            if k % 10 == 0:
                print(f"  {k}/{len(need)}　明细累计 {len(apps)}", flush=True)

    payload = {
        "meta": {
            "updated": date.today().isoformat(),
            "batches": len(batches),
            "apps": len(apps),
            "sources": {
                "miit": "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html",
                "cac": "https://search.cac.gov.cn/cms/cmsadmin/infopub/gjjs.jsp",
            },
            "note": "批次信息取自发布机关官网通报页；App 明细由通报内嵌名单图 OCR 抽取，"
                    "原始表格以官方通报页图片为准。",
        },
        "batches": batches,
    }
    json.dump(payload, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    json.dump({"meta": payload["meta"], "apps": apps},
              open(os.path.join(OUTDIR, "apps.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"\n✓ 批次 {len(batches)}　App 明细 {len(apps)}　"
          f"{os.path.getsize(meta_path)/1024:.0f} KB")
    kinds = {}
    for b in batches:
        kinds[b["org"]] = kinds.get(b["org"], 0) + 1
    print("  按机关：", kinds)
    return 0


BAD_ROW = re.compile(r"^(序号|名称|应用|软件|企业|版本|所涉|问题|备注|序号\s|App|APP)$")


def rows_from_ocr(lines, batch):
    """把 OCR 行按“App名 + 开发者 + 问题”粗分组，输出可检索条目。

    名单图排版为多列表格，OCR 逐行给出单元格文本；这里以“含公司/有限/科技/网络”的
    单元格为锚点，向上就近取 App 名，向下就近取问题描述关键词。
    """
    rows = []
    org_pat = re.compile(r"(有限|科技|网络|信息|传媒|教育|文化|健康|集团|股份|公司)")
    prob_pat = re.compile(r"(收集|权限|注销|共享|第三方|告知|同意|规则|SDK|推送|定向|"
                          r"欺骗|误导|强制|频繁|超范围|未公开|未提供|未完整|非必要)")
    for i, ln in enumerate(lines):
        if not org_pat.search(ln) or len(ln) < 6 or len(ln) > 40:
            continue
        app = ""
        for j in range(i - 1, max(-1, i - 4), -1):
            c = lines[j]
            if 2 <= len(c) <= 24 and not org_pat.search(c) and not BAD_ROW.match(c):
                app = c
                break
        probs = []
        for j in range(i, min(len(lines), i + 5)):
            for m in prob_pat.findall(lines[j]):
                probs.append(m)
        if app:
            rows.append({"app": app, "dev": ln, "problems": sorted(set(probs)),
                         "batch": batch.get("title", ""), "date": batch.get("date", ""),
                         "url": batch.get("url", ""), "org": batch.get("org", "")})
    # 去重（同批次同名 App）
    seen, out = set(), []
    for r in rows:
        k = (r["batch"], r["app"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


if __name__ == "__main__":
    sys.exit(main())
