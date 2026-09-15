#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国家法律法规数据库（flk.npc.gov.cn）全量枚举 → sources/standards/flk_bulk.json

为什么需要它
------------
条目库原先靠人工录入法律法规（法律 39 / 行政法规 9 条），与 flk 实际收录量
（3 万余条）差了两个数量级——「法律法规库缺得太多」的根因就在这里。

flk 新版是 Vue SPA，页面抓不到数据，但它的 REST 接口对匿名请求开放：
  POST https://flk.npc.gov.cn/law-search/search/list
    {searchContent:"", pageSize:200, pageNum:n, sxx:[...]}   # searchContent 空 = 不过滤
返回 rows：bbbs / title / gbrq(公布日) / sxrq(施行日) / sxx(时效性) / flxz(法律性质) / zdjgName(制定机关)

权威深链格式（页面用 base64(bbbs) 作为 query）：
  https://flk.npc.gov.cn/detail2.html?<base64(bbbs)>

用法：
  python3 tools/harvest_flk_bulk.py            # 增量（只抓缺的年份段，默认全量对比）
  python3 tools/harvest_flk_bulk.py --full     # 强制全量重抓
"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "sources", "standards", "flk_bulk.json")

API = "https://flk.npc.gov.cn/law-search/search/list"
REF = "https://flk.npc.gov.cn/"
PAGE_SIZE = 200

# sxx 时效性：3=现行有效，4=尚未生效，1=已废止，2=已修改（flk 返回码，实测归纳）
SXX_NAME = {1: "已废止", 2: "已修改", 3: "现行有效", 4: "即将实施", 5: "尚未生效", 0: "未知"}

# 法律性质（flxz）——本地分类映射到条目库的 level 字段
LEVEL_MAP = {
    "宪法": "法律",
    "法律": "法律",
    "行政法规": "行政法规",
    "监察法规": "行政法规",
    "司法解释": "司法解释",
    "地方性法规": "地方性法规",
    "部门规章": "部门规章",
}

# 地方性法规只有命中这些主题词才收（3 万余条里绝大多数是地方性事务，与合规无关）
LOCAL_KEEP = (
    "数据|信息|网络|平台|电子商务|消费者|价格|食品|药品|计量|广告|市场|营商环境|"
    "人工智能|算法|信用|质量|安全|标准化|数字|隐私|个人信息|外卖|餐饮|配送|冷链|"
    "反不正当竞争|知识产权|合同|劳动|预付|会员|互联网|直播|快递|仓储|农贸|农产品|"
    "未成年人|老年人|无障碍|绿色|包装|节约|反食品浪费|检验检测|认证|特种设备"
)


def curl_json(url, payload, timeout=45, retry=3):
    for i in range(retry):
        try:
            p = subprocess.run(
                ["curl", "-s", "-m", str(timeout), "-X", "POST", url,
                 "-H", "Content-Type: application/json",
                 "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                 "-H", "Referer: " + REF,
                 "--data-binary", json.dumps(payload, ensure_ascii=False)],
                capture_output=True, text=True)
            d = json.loads(p.stdout)
            if isinstance(d, dict) and "rows" in d:
                return d
        except Exception:
            pass
        time.sleep(1.2 * (i + 1))
    return None


def detail_url(bbbs):
    b = base64.b64encode(bbbs.encode()).decode()
    return "https://flk.npc.gov.cn/detail2.html?" + b


def fetch_all():
    first = curl_json(API, {"searchRange": 1, "sxrq": [], "gbrq": [], "searchType": 1,
                            "sxx": [], "gbrqYear": [], "flfgCodeId": [], "zdjgCodeId": [],
                            "searchContent": "", "pageNum": 1, "pageSize": 1,
                            "sortTr": "f_bbrq_s;desc", "sort": True})
    if not first:
        print("✗ 接口不可达"); return []
    total = int(first.get("total") or 0)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"flk 收录总计 {total} 条 → {pages} 页（每页 {PAGE_SIZE}）")
    rows, seen = [], set()
    for pn in range(1, pages + 1):
        d = curl_json(API, {"searchRange": 1, "sxrq": [], "gbrq": [], "searchType": 1,
                            "sxx": [], "gbrqYear": [], "flfgCodeId": [], "zdjgCodeId": [],
                            "searchContent": "", "pageNum": pn, "pageSize": PAGE_SIZE,
                            "sortTr": "f_bbrq_s;desc", "sort": True})
        if not d:
            print(f"  ! 第 {pn} 页失败，跳过")
            continue
        for r in d.get("rows") or []:
            b = r.get("bbbs")
            if not b or b in seen:
                continue
            seen.add(b)
            rows.append(r)
        if pn % 10 == 0 or pn == pages:
            print(f"  {pn}/{pages} 页　累计 {len(rows)} 条")
        time.sleep(0.25)
    return rows


def normalize(r):
    return {
        "b": r.get("bbbs"),
        "t": (r.get("title") or "").strip(),
        "k": (r.get("flxz") or "").strip(),
        "p": (r.get("gbrq") or "")[:10],
        "i": (r.get("sxrq") or "")[:10],
        "s": int(r.get("sxx") or 0),
        "o": (r.get("zdjgName") or "").strip(),
    }


def main():
    full = "--full" in sys.argv
    old = {}
    if os.path.exists(OUT) and not full:
        try:
            d = json.load(open(OUT, encoding="utf-8"))
            old = {x["b"]: x for x in d.get("items", [])}
            print(f"已有 {len(old)} 条")
        except Exception:
            pass
    rows = fetch_all()
    if not rows:
        print("✗ 未取到数据，保留原文件"); return 1
    items = [normalize(r) for r in rows]
    items = [x for x in items if x["b"] and x["t"]]

    import re
    local_pat = re.compile(LOCAL_KEEP)
    keep, local_drop = [], 0
    for x in items:
        if "地方" in x["k"]:
            if local_pat.search(x["t"]):
                keep.append(x)
            else:
                local_drop += 1
        else:
            keep.append(x)

    import collections
    cnt = collections.Counter(x["k"] for x in keep)
    payload = {
        "meta": {
            "source": "国家法律法规数据库 flk.npc.gov.cn",
            "endpoint": API,
            "updated": date.today().isoformat(),
            "fetched_total": len(items),
            "kept": len(keep),
            "local_dropped": local_drop,
            "note": "bbbs 为 flk 主键；站点深链 = https://flk.npc.gov.cn/detail2.html?base64(bbbs)。"
                    "地方性法规仅保留命中合规主题词的条目。",
            "by_kind": dict(cnt),
        },
        "items": keep,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT) / 1024
    print(f"✓ 写入 {OUT}：{len(keep)} 条（原始 {len(items)}，地方性法规丢弃 {local_drop}）　{size:.0f} KB")
    for k, v in cnt.most_common():
        print(f"    {k}：{v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
