#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App 违规通报库 —— 发布日期回填 + 批次号抽取
================================================================================
【为什么要做】
  省局站点的 jpaas 列表接口 `paramJson` 只返回 {title, url}，**不返回发布日期**
  → 564 份省局文书中 561 份 `date` 为空。而「按年统计通报量」是治理分析的地基，
  没有日期整个分析维度就是废的。

【日期从哪来 · 多源仲裁】
  jpaas 页面里同日期的信号有四处，可靠性不同：
    ① 标题里的年份     「（2023年第四批）」——发布机关自己写的正式编号年，**最权威**
    ② `<meta name="PubDate" content="2023-11-30 17:49">` —— jpaas 统一字段，实测命中 ~99%，
                        但**站点迁移会被批量刷成同一天**（如 hbca 多份都是 2023-05-13），
                        须做「同日批量」检测后降级
    ③ 正文「发布时间：2023-11-30」—— 与 ② 同源，作为 ② 缺失时的备份
    ④ URL 路径 `/art/2023/art_xxx.html` —— **只是栏目归档年份，与发布年常不一致**
                        （实测 hbca 一份 urlYear=2021 而实际 PubDate=2023-05-13），
                        仅作最后兜底，且只精确到年

  仲裁优先级：标题年份 > PubDate/正文（非迁移日）> URL 年份 > PubDate（迁移日）
  冲突时以标题年份为准并打 `date_conflict` 标记 —— 这本身就是「文书被重新发布过」的证据。

【输出】
  就地更新 `sources/appviol/docs.json`，为每份文书补：
    date / date_src / date_precision / date_conflict
    total_batch（总第 N 批）/ year_batch（YYYY 年第 N 批）/ seq_batch + batch_year
    quarter（第 N 季度，若有）
  小结落盘 `sources/appviol/date_audit.json` 供页面透明披露回填质量。

用法：
  python tools/backfill_appviol_dates.py            # 只补缺失的（增量）
  python tools/backfill_appviol_dates.py --refetch  # 全部重取
  python tools/backfill_appviol_dates.py --sleep 0.5
================================================================================
"""
import json, os, re, subprocess, sys, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(HERE, "sources", "appviol")
DOCS = os.path.join(OUTDIR, "docs.json")
AUDIT = os.path.join(OUTDIR, "date_audit.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn2int(s):
    """中文数字 → 整数（支持 十/十二/二十/二十三/一百零五 等）。已是数字则直接转。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if not all(c in CN_DIGIT for c in s):
        return None
    total, section, has = 0, 0, False
    for c in s:
        v = CN_DIGIT[c]
        if v == 10:
            section = (section or 1) * 10
            has = True
        else:
            section = section + v
            has = True
    total += section
    return total if has else None


# ---------------------------------------------------------------- 批次抽取
RE_TOTAL = re.compile(r"总\s*第\s*([一二三四五六七八九十百零〇\d]+)\s*批")
RE_YEARB = re.compile(r"(20\d{2})\s*年\s*第\s*([一二三四五六七八九十百零〇\d]+)\s*批")
RE_SEQ = re.compile(r"第\s*([一二三四五六七八九十百零〇\d]+)\s*批")
RE_QUART = re.compile(r"第\s*([一二三四五六七八九十\d]+)\s*季度")


def parse_batch(title):
    """从标题抽批次三重口径。省局标题不写「总第」，只有「（2023年第四批）」。"""
    t = title or ""
    total = yearb = seq = q = None
    m = RE_TOTAL.search(t)
    if m:
        total = cn2int(m.group(1))
    m = RE_YEARB.search(t)
    if m:
        yearb = (int(m.group(1)), cn2int(m.group(2)))
    m = RE_SEQ.search(t)
    if m:
        seq = cn2int(m.group(1))
    m = RE_QUART.search(t)
    if m:
        q = cn2int(m.group(1))
    return {"total_batch": total,
            "year_batch": yearb[1] if yearb else None,
            "batch_year": yearb[0] if yearb else None,
            "seq_batch": seq,
            "quarter": q}


# ---------------------------------------------------------------- 抓取
def fetch(url, timeout=25):
    try:
        r = subprocess.run(["curl", "-s", "-L", "-A", UA, "--max-time", str(timeout), url],
                           capture_output=True)
        return r.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


RE_PUB = re.compile(r'name="PubDate"\s+content="(\d{4}-\d{2}-\d{2})', re.I)
RE_BODY = re.compile(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})")
RE_URLY = re.compile(r"/art/(\d{4})/")
# cac.gov.cn 的文章 URL 自带完整发布日期（/2026-06/11/c_xxx.htm）——比 PubDate 还准，
# 且无需联网。国家网信办的 12 份文书全站无日期（站点不输出 PubDate），靠这条补齐。
RE_URLDAY = re.compile(r"/(\d{4})-(\d{2})/(\d{2})/")


def url_day(url):
    m = RE_URLDAY.search(url or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def probe(full_id, url):
    """取候选日期三源。"""
    h = fetch(url)
    pub = RE_PUB.search(h)
    body = RE_BODY.search(h)
    uy = RE_URLY.search(url)
    return {
        "pub": pub.group(1) if pub else "",
        "body": body.group(1) if body else "",
        "url_year": uy.group(1) if uy else "",
        "len": len(h),
    }


def main():
    argv = sys.argv[1:]
    refetch = "--refetch" in argv
    sleep = float(argv[argv.index("--sleep") + 1]) if "--sleep" in argv else 0.35

    data = json.load(open(DOCS, encoding="utf-8"))
    docs = data["docs"]

    # ---------- 第一步：批次号（离线，全部文书） ----------
    n_batch = 0
    for d in docs:
        b = parse_batch(d.get("title") or "")
        for k, v in b.items():
            if v is not None:
                if d.get(k) != v:
                    d[k] = v
                n_batch += 1
    print(f"▸ 批次号抽取：{n_batch} 个字段落位")
    c_tot = sum(1 for d in docs if d.get("total_batch"))
    c_yb = sum(1 for d in docs if d.get("year_batch"))
    c_sq = sum(1 for d in docs if d.get("seq_batch"))
    print(f"  总第N批 {c_tot} ｜ YYYY年第N批 {c_yb} ｜ 第N批 {c_sq}")

    # ---------- 第二步：日期回填（带缓存，避免重跑再抓一遍） ----------
    todo = [d for d in docs if d.get("url") and (refetch or not d.get("date"))]
    print(f"\n▸ 日期回填：{sum(1 for d in docs if not d.get('date'))} 份缺日期，"
          f"需处理 {len(todo)} 份")
    cache_path = os.path.join(OUTDIR, ".dateprobe.json")
    probe_cache = {}
    if os.path.exists(cache_path):
        try:
            probe_cache = json.load(open(cache_path, encoding="utf-8"))
        except Exception:
            probe_cache = {}
    miss = [d for d in todo if d["url"] not in probe_cache]
    print(f"　缓存命中 {len(todo)-len(miss)} 份，本次实抓 {len(miss)} 份")
    for i, d in enumerate(miss, 1):
        probe_cache[d["url"]] = probe(d["id"], d["url"])
        if i % 40 == 0 or i <= 3:
            print(f"  [{i}/{len(miss)}] {d.get('title','')[:38]}", flush=True)
        if i % 100 == 0:                  # 中途落盘：即使后面崩了也不用重抓
            json.dump(probe_cache, open(cache_path, "w", encoding="utf-8"),
                      ensure_ascii=False)
        time.sleep(sleep)
    if miss:
        json.dump(probe_cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)

    # ---------- 第三步：迁移日检测 ----------
    # 判据（比「频次高」精准）：同一域名下同一天出现 ≥3 份，且其中**标题自带年份的
    # 比例过半与 PubDate 年份不一致** —— 一个机构不可能在一天里集中发布跨越多个年度
    # 的不同批次通报，这种情况只能是站点迁移/改版把时间批量刷成了同一天。
    # 仅在标题普遍不带年份时，才退回「≥4 份且占比 ≥40%」的弱判据。
    def title_year(d):
        ty = d.get("batch_year")
        if ty:
            return str(ty)
        m2 = re.search(r"(20\d{2})\s*年", d.get("title") or "")
        return m2.group(1) if m2 else ""

    by_dom = defaultdict(lambda: defaultdict(list))
    for d in docs:
        p = probe_cache.get(d.get("url"))
        if p and p.get("pub"):
            m = re.match(r"https?://([^/]+)", d["url"])
            by_dom[m.group(1) if m else "?"][p["pub"]].append(d)

    migrate = {}
    for dom, days in by_dom.items():
        tot = sum(len(v) for v in days.values())
        for day, ds in sorted(days.items(), key=lambda kv: -len(kv[1])):
            if len(ds) < 3:
                continue
            ty = [x for x in (title_year(d) for d in ds) if x]
            bad = [x for x in ty if x != day[:4]]
            hit = (len(ty) >= 2 and len(bad) / len(ty) >= 0.5) or \
                  (len(ty) < 2 and len(ds) >= max(4, tot * 0.4))
            if hit:
                migrate[dom] = day
                break
    if migrate:
        print(f"\n▸ 检出站点迁移日（PubDate 不可信）：")
        for k, v in sorted(migrate.items()):
            ds = by_dom[k][v]
            ty = [x for x in (title_year(d) for d in ds) if x]
            print(f"   {k:<26} {v}　{len(ds)}/{sum(len(x) for x in by_dom[k].values())} 份"
                  f"　标题年冲突 {sum(1 for x in ty if x != v[:4])}/{len(ty)}")

    # ---------- 第三步之二：同年塌缩检测 ----------
    # 「同日」只能抓到把多份文书刷成**同一天**的站点。还有一类站点是把整站文书的
    # PubDate 刷成**同一年**的不同日期（广东实测：87 份 PubDate 全在 2026 年，
    # 而 URL 归档年是 2020—2026 分散分布）→ 这种「同日」判据抓不到，年份统计会全错。
    # 判据：该域名 ≥70% 的 PubDate 落在同一**年**，且 URL 归档年 ≥3 个不同年份。
    year_collapse = set()
    for dom, days in by_dom.items():
        pubs, urls = Counter(), Counter()
        for day, ds in days.items():
            pubs[day[:4]] += len(ds)
            for d in ds:
                m3 = RE_URLY.search(d.get("url") or "")
                if m3:
                    urls[m3.group(1)] += 1
        tot = sum(pubs.values())
        if tot >= 5 and len(urls) >= 3 and max(pubs.values()) / tot >= 0.7:
            year_collapse.add(dom)
    if year_collapse:
        print(f"\n▸ 检出「同年塌缩」（PubDate 年份不可信，改用 URL 归档年）：")
        for k in sorted(year_collapse):
            pubs = Counter()
            urls = Counter()
            for day, ds in by_dom[k].items():
                pubs[day[:4]] += len(ds)
                for d in ds:
                    m3 = RE_URLY.search(d.get("url") or "")
                    if m3:
                        urls[m3.group(1)] += 1
            print(f"   {k:<26} PubDate {dict(pubs.most_common(3))}"
                  f"　URL 归档年 {len(urls)} 个 {dict(sorted(urls.items())[:6])}")

    # ---------- 第四步：仲裁并写回 ----------
    # 主判据：**标题年 == PubDate 年 → PubDate 可信，取精确到日**（标题年与页面日互相
    # 印证）；两者不一致 → 页面日很可能是迁移日或被重新发布，只保留标题年。
    stat = Counter()
    for d in docs:
        # ⚠️ 关键保护：没有探测数据但**已有日期**的文书一律保留原判 ——
        # 那批是首次采集时直接从页面正文/列表页取到的日期（工信部 58 批序列、
        # 网信办公告等），比事后从 PubDate 推的更可信。重算会把它降级成「仅到年」。
        if d["url"] not in probe_cache:
            if d.get("date"):
                d.setdefault("date_src", "harvest")
                d.setdefault("date_precision", "day")
                stat["kept:" + d["date_src"]] += 1
                continue
            p = {"pub": "", "body": "", "url_year": ""}
        else:
            p = probe_cache[d["url"]]
        m = re.match(r"https?://([^/]+)", d["url"] or "")
        dom = m.group(1) if m else "?"
        mig = migrate.get(dom)
        pub = p["pub"] or ""
        body = p["body"] or ""
        if pub and pub == mig:
            pub = ""                      # 迁移日作废
        if body and body == mig:
            body = ""
        t_year = title_year(d)
        uy = p["url_year"]
        ud = url_day(d["url"])

        day = pub or body
        if t_year and day and day[:4] == t_year:
            final, src, prec, conf = day, ("pubdate" if pub else "body"), "day", 0
        elif t_year and ud and ud[:4] == t_year:
            # 标题年与 URL 归档日互相印证 → 取精确到日（比只落标题年更有用）
            final, src, prec, conf = ud, "url-day", "day", 0
        elif t_year and day:
            final, src, prec, conf = t_year + "-01-01", "title-year", "year", 1
        elif t_year:
            final, src, prec, conf = t_year + "-01-01", "title-year", "year", 0
        elif dom in year_collapse and uy:
            # 该站点 PubDate 年份整体塌缩 → 只信 URL 归档年；若两者同年则月日仍可用
            if day and day[:4] == uy:
                final, src, prec, conf = day, "pubdate", "day", 0
            else:
                final, src, prec, conf = uy + "-01-01", "url-path", "year", 1
        elif day:
            final, src, prec, conf = day, ("pubdate" if pub else "body"), "day", 0
        elif ud:
            final, src, prec, conf = ud, "url-day", "day", 0
        elif uy:
            final, src, prec, conf = uy + "-01-01", "url-path", "year", 0
        else:
            final, src, prec, conf = "", "none", "none", 0

        d["date"] = final
        d["date_src"] = src
        d["date_precision"] = prec
        if conf:
            d["date_conflict"] = 1
        elif "date_conflict" in d:
            d.pop("date_conflict", None)
        stat[src] += 1

    # ---------- 汇总 ----------
    have = sum(1 for d in docs if d.get("date"))
    exact = sum(1 for d in docs if d.get("date_precision") == "day")
    audit = {
        "updated": time.strftime("%Y-%m-%d"),
        "documents": len(docs),
        "with_date": have,
        "exact_day": exact,
        "year_only": sum(1 for d in docs if d.get("date_precision") == "year"),
        "by_source": dict(stat),
        "migrate_days": migrate,
        "year_collapse": sorted(year_collapse),
        "conflicts": sum(1 for d in docs if d.get("date_conflict")),
        "note": "省局 jpaas 列表接口不返回发布日期；日期由「标题年份 > 页面 PubDate > "
                "URL 归档年」仲裁得到。PubDate 为站点批量迁移日的域名已降级。"
                "precision=year 表示只精确到年，年度统计可用、月度统计不可用。",
    }
    json.dump({"meta": audit, "docs": docs}, open(DOCS, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump(audit, open(AUDIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n✓ 有日期 {have}/{len(docs)}　精确到日 {exact}　仅到年 {audit['year_only']}")
    print(f"  来源 {dict(stat)}")
    print(f"  年份冲突（标题年≠页面年）{audit['conflicts']} 份")
    yr = Counter((d.get("date") or "")[:4] for d in docs if d.get("date"))
    print(f"  年度分布 {sorted(yr.items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
