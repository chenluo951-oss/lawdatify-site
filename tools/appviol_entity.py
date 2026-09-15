#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App 违规通报库 —— 实体消解（entity resolution）与事件模型
================================================================================
【为什么不能「仅按应用名称去重」】
  旧实现 key = 归一化后的应用名，丢了运营者。后果两头都错：
    · 过度合并：不同公司的同名应用被并成一个（实测「一键抠图大师」在安徽歌谷与
      上海兖扬名下各出现过 → 被当成同一款）；
    · 合并不足：PDF 提取把公司名拦腰插了空格（「杭州幻象引擎网络技术有 限公司」），
      同一家公司在库里成了两个主体（实测 823 条明细受影响）。
  两种错误都会污染「涉及应用数」这个对外口径。

【本模块的两层结构】
  ① 实体层  app_uid —— 怎么认定「这是同一款应用」
       证据链：归一化应用名 + 运营者主干。
       · 仅「空格 / 全半角 / 标点 / 装饰后缀(APP·安卓版·手机版)」差异 → 同一实体
       · 名称微差（前缀包含或编辑距离小）且运营者主干相同 → 同一实体（记 alias）
       · 同名但运营者主干不同 → **不合并**，各算一款，并打 `name_collision`
         （这是「同名不同主体」，仿冒/蹭名风险，本身就是治理情报）
       · 中方与外方名称并存（「索罗特信息科技江苏有限公司」vs
         「Solot Information Technology Jiangsu Co., Ltd.」）→ 不强行合并，
         打 `cross_lang` 并同时保留两种署名，供人工判读
  ② 事件层  incident —— 一次通报 = 一个事件
       事件键 = (文书 id, 应用) 去重后，再按 (机构, 批次号) 收拢；
       完全重复的行（同一机构同一批次把同一应用列两遍）只计 1 次。
       保留的是**同一应用在不同机构 / 不同批次 / 不同时间**被再次通报的那些事件 ——
       这才是「重复上榜」，是治理信号而不是噪声。

【由此得到治理指标】
  n_incidents 被通报次数 · n_orgs 涉事机构数 · span_days 首末间隔
  relapse_gaps 相邻两次间隔（天）· escalated 是否由「通报」升级为「下架」
  new_probs 再次被通报时新增的问题类目（老问题没改，还添了新问题）
================================================================================
"""
import re
from collections import Counter, defaultdict

# ------------------------------------------------------------------ 文本清洗
FULL2HALF = {ord(c): ord(c) - 0xFEE0 for c in
             "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
             "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}
FULL2HALF[ord("　")] = ord(" ")


def clean(s):
    """清掉 PDF 提取产生的字符间插入空格，并做全角归一。

    判据：空格两侧都是 CJK 字符 → 视作断行残留，删除（「有限公 司」→「有限公司」）。
    中英之间的空格保留（「vivo 应用商店」有意义）。
    """
    s = (s or "").translate(FULL2HALF)
    s = re.sub(r"[\u3000\t]+", " ", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


# ------------------------------------------------------------------ 应用名归一
# 纯装饰性后缀：去掉不改变产品身份。功能性版本词（司机版/商家版/企业版/极速版）
# 一律**保留** —— 那是不同产品，合了会错。
DECO = re.compile(r"(?:[（(【\[][^）)】\]]*[）)】\]]|\bapp\b|app|安卓版|手机版|移动版|客户端)+$",
                  re.I)
PUNCT = re.compile(r"[\s\-—_·・、,\.:：;；'\"“”‘’/\\|!！?？~～@#￥$%^&*+=<>《》【】\[\]（）(){}]")


def app_key(s):
    """应用名归一键：小写 + 去标点 + 去装饰后缀。用于识别「同一个名字的不同写法」。"""
    s = clean(s).lower()
    s = PUNCT.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = DECO.sub("", s)
    return s


# ------------------------------------------------------------------ 运营者归一
DEV_SUFFIX = re.compile(
    r"(?:股份|责任|集团|控股|科技|网络|信息|技术|文化|传媒|数字|智能|电子|商贸|"
    r"实业|投资|管理|服务|咨询|发展|有限|公司|企业|工作室|中心|厂|店|行|社|部)+$")


def dev_norm(s):
    """运营者名的强归一键：清洗 + 去括号附注 + 去公司类型后缀 + 去标点。"""
    s = clean(s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    s = PUNCT.sub("", s).lower()
    prev = None
    while prev != s:
        prev = s
        s = DEV_SUFFIX.sub("", s)
    return s


def dev_main(s):
    """运营者主干：再去掉行政区域前缀，用于跨地区表述的对齐（「北京XX」↔「XX」）。

    仅在「强归一键相同」或「一方是另一方后缀」时使用，避免把
    「北京星河」与「上海星河」错并（那是两家不同公司）。
    """
    s = dev_norm(s)
    s = re.sub(r"^(?:中国|北京|上海|天津|重庆|广州|深圳|杭州|南京|成都|武汉|西安|"
               r"苏州|长沙|郑州|青岛|厦门|福州|合肥|济南|沈阳|大连|宁波|无锡|"
               r"广东省?|浙江省?|江苏省?|山东省?|河南省?|四川省?|福建省?|湖北省?|"
               r"湖南省?|安徽省?|江西省?|陕西省?|河北省?|山西省?|辽宁省?|吉林省?|"
               r"黑龙江省?|云南省?|贵州省?|甘肃省?|青海省?|海南省?|台湾省?|"
               r"内蒙古|广西|西藏|宁夏|新疆|香港|澳门)", "", s)
    return s


def has_cjk(s):
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def lev(a, b, cap=8):
    """截断编辑距离（超 cap 直接返回 cap+1，省算力）。"""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, lb + 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
        if min(dp) > cap:
            return cap + 1
    return dp[lb]


def same_owner(a, b):
    """判两个运营者署名是否同一主体。返回 (是否同一, 依据)。"""
    if not a or not b:
        return False, ""
    na, nb = dev_norm(a), dev_norm(b)
    if not na or not nb:
        return False, ""
    if na == nb:
        return True, "identical"
    ma, mb = dev_main(a), dev_main(b)
    if ma and mb and ma == mb:
        # 主干相同但强归一键不同 → 一般也是同一家（如「北京X科技」vs「X」）
        return True, "main"
    # 中文名 vs 外文名：不合并，另标记
    if has_cjk(a) != has_cjk(b):
        return False, "cross_lang"
    # 前缀包含（「广州幻象引擎网络技术」vs「广州幻象引擎」）
    sh, lo = (ma, mb) if len(ma) <= len(mb) else (mb, ma)
    if sh and len(sh) >= 3 and (lo.startswith(sh) or lo.endswith(sh)):
        return True, "prefix"
    # 编辑距离小 + 主干够长
    if ma and mb and min(len(ma), len(mb)) >= 4 and lev(ma, mb, 2) <= 2:
        return True, "fuzzy"
    return False, ""


def same_app_name(a, b):
    """判两个应用名是否同一款产品名（用于同名不同写法的归并）。"""
    ka, kb = app_key(a), app_key(b)
    if not ka or not kb:
        return False, ""
    if ka == kb:
        return True, "identical"
    sh, lo = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(sh) >= 3 and lo.startswith(sh):
        return True, "prefix"
    if min(len(ka), len(kb)) >= 5 and lev(ka, kb, 1) <= 1:
        return True, "fuzzy"
    return False, ""


# ------------------------------------------------------------------ 并查集
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra
            return True
        return False


# ------------------------------------------------------------------ 主入口
def _day(d):
    return d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or "") else ""


def resolve(docs):
    """输入文书列表 → 输出 {apps, stats}。apps 为实体消解 + 事件模型后的应用清单。"""
    # ---------- 1. 拍平明细为「记录」 ----------
    recs = []
    for d in docs:
        date = _day(d.get("date"))
        for e in d.get("entries") or []:
            app_raw = clean(e.get("app") or "")
            if len(app_key(app_raw)) < 2:
                continue
            recs.append({
                "app": app_raw,
                "dev": clean(e.get("dev") or ""),
                "ver": clean(e.get("ver") or ""),
                "probs": [p for p in (e.get("probs") or []) if p],
                "doc": d["id"],
                "title": d.get("title") or "",
                "url": d.get("url") or "",
                "org": d.get("org") or "",
                "scope": d.get("scope") or "",
                "date": date,
                "year": date[:4] if date else (d.get("date") or "")[:4],
                "prec": d.get("date_precision") or ("day" if date else "none"),
                "kind": d.get("notice_kind") or "",
                "carrier": d.get("carrier") or "",
                "batch_total": d.get("total_batch"),
                "batch_year": d.get("batch_year"),
                "batch_seq": d.get("seq_batch"),
                "province": d.get("province") or "",
            })

    # ---------- 2. 事件级去重（同文书同应用只计一次） ----------
    ev, seen = [], set()
    for r in recs:
        k = (r["doc"], app_key(r["app"]))
        if k in seen:
            # 同一份文书里重复列了同一应用：问题取并集
            for x in ev:
                if (x["doc"], app_key(x["app"])) == k:
                    for p in r["probs"]:
                        if p not in x["probs"]:
                            x["probs"].append(p)
                    break
            continue
        seen.add(k)
        ev.append(r)
    n_dup_rows = len(recs) - len(ev)

    # ---------- 3. 实体消解 ----------
    # 策略：**以应用名为锚，运营者只用于否决**。
    #   同一应用名之下，若运营者署名能聚成 ≥2 个互不相同的主体 → 按主体拆开
    #   （这是「同名不同主体」：可能是山寨蹭名，也可能是通报方署名不统一）；
    #   否则该应用名下的全部记录合成一款（含运营者为空的记录，避免同一款被拆碎）。
    uf = UF()
    by_name = defaultdict(list)
    for i, r in enumerate(ev):
        by_name[app_key(r["app"])].append(i)

    collision, cross_lang = {}, {}
    for k, idxs in by_name.items():
        # 3a. 非空署名的两两同主体判定（并查集聚类）
        dev_idx = defaultdict(list)
        for i in idxs:
            if ev[i]["dev"]:
                dev_idx[dev_norm(ev[i]["dev"])].append(i)
        keys = list(dev_idx)
        ouf = UF()
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                ok, how = same_owner(keys[a], keys[b])
                if ok:
                    ouf.union(keys[a], keys[b])
        clusters = defaultdict(list)
        for kk in keys:
            clusters[ouf.find(kk)].append(kk)
        collision[k] = len(clusters)
        if len(clusters) > 1:
            langs = {has_cjk(ev[dev_idx[kk][0]]["dev"]) for kk in keys}
            cross_lang[k] = 1 if len(langs) > 1 else 0

        if len(clusters) <= 1:
            # 单一主体（或无署名）→ 该应用名下全部记录合并
            for i in idxs[1:]:
                uf.union(idxs[0], i)
        else:
            # 多主体 → 按主体分组；无署名的记录跟随规模最大的主簇
            big = max(clusters.values(), key=lambda ks: sum(len(dev_idx[x]) for x in ks))
            anchor = dev_idx[big[0]][0]
            for kk in big[1:]:
                for i in dev_idx[kk]:
                    uf.union(anchor, i)
            for cl in clusters.values():
                for kk in cl:
                    if kk in big:
                        continue
                    root_i = dev_idx[kk][0]
                    for i in dev_idx[kk]:
                        uf.union(root_i, i)
            for i in idxs:
                if not ev[i]["dev"]:
                    uf.union(anchor, i)

    # 3b. 应用名微差（「高考优填报 志愿」↔「高考优填报志愿」）+ 同一运营者 → 合并
    by_owner = defaultdict(list)
    for i, r in enumerate(ev):
        nv = dev_norm(r["dev"])
        if nv:
            by_owner[nv].append(i)
    for nv, idxs in by_owner.items():
        names = defaultdict(list)
        for i in idxs:
            names[app_key(ev[i]["app"])].append(i)
        ks = list(names)
        for a in range(len(ks)):
            for b in range(a + 1, len(ks)):
                ok, how = same_app_name(ks[a], ks[b])
                if ok:
                    for i in names[ks[b]]:
                        uf.union(names[ks[a]][0], i)

    # ---------- 4. 组装实体 ----------
    groups = defaultdict(list)
    for i in range(len(ev)):
        groups[uf.find(i)].append(i)

    apps = []
    for root, idxs in groups.items():
        rows = [ev[i] for i in idxs]
        name_cnt = Counter(r["app"] for r in rows)
        rep_name = name_cnt.most_common(1)[0][0]
        dev_cnt = Counter(r["dev"] for r in rows if r["dev"])
        rep_dev = dev_cnt.most_common(1)[0][0] if dev_cnt else ""

        # 事件收拢：同 (机构, 年份, 批次) 视为一次事件
        # ⚠️ 必须带年份：省局标题只写「（2023年第四批）」，不同年的「第四批」是不同事件
        evmap = {}
        for r in rows:
            if r["batch_total"]:
                bk = f'总第{r["batch_total"]}批'
            elif r["batch_seq"]:
                y = r["batch_year"] or r["year"] or ""
                bk = f'{y}年第{r["batch_seq"]}批'
            else:
                bk = ""
            ek = (r["org"], bk) if bk else (r["org"], r["doc"])
            c = evmap.get(ek)
            if not c:
                evmap[ek] = {"org": r["org"], "date": r["date"], "year": r["year"],
                             "kind": r["kind"], "batch": bk, "doc": r["doc"],
                             "prec": r["prec"], "url": r["url"],
                             "probs": list(r["probs"])}
            else:
                for p in r["probs"]:
                    if p not in c["probs"]:
                        c["probs"].append(p)
                if r["date"] and (not c["date"] or r["date"] < c["date"]):
                    c["date"] = r["date"]
        inc = sorted(evmap.values(), key=lambda x: (x["date"] or "9999", x["org"]))

        orgs = sorted({x["org"] for x in inc if x["org"]})
        dates = [x["date"] for x in inc if x["date"]]
        first, last = (dates[0], dates[-1]) if dates else ("", "")
        # ⚠️ 间隔只用**精确到日**的相邻事件算：省局有 107 份文书只能定位到「年」，
        # 其日期统一落在 01-01，一并参与计算会把间隔中位数压成 0 天（实测踩过）。
        gaps = []
        pdays = [x for x in inc if x.get("prec") == "day" and x["date"]]
        for a, b in zip(pdays, pdays[1:]):
            try:
                from datetime import date as _d
                ya, ma, da = map(int, a["date"].split("-"))
                yb, mb, db = map(int, b["date"].split("-"))
                gaps.append((_d(yb, mb, db) - _d(ya, ma, da)).days)
            except Exception:
                pass

        all_probs = []
        for x in inc:
            for p in x["probs"]:
                if p not in all_probs:
                    all_probs.append(p)
        first_probs = inc[0]["probs"] if inc else []
        last_probs = inc[-1]["probs"] if inc else []
        new_probs = [p for p in last_probs if p not in first_probs]

        kinds = [x["kind"] for x in inc]
        escalated = 1 if ("下架处置" in kinds and any(
            k in kinds for k in ("批次通报", "整改复核"))) else 0
        reviewed = 1 if "整改复核" in kinds else 0

        devs = [d for d, _ in dev_cnt.most_common()]
        langs = {has_cjk(d) for d in devs}
        member_keys = {app_key(r["app"]) for r in rows}
        # 分层事件计数：把「通报 / 复核 / 下架」拆开，避免把同一次治理链条的
        # 三个环节当成三次独立通报 —— 这是「重复上榜」口径的关键。
        kc = Counter(x["kind"] for x in inc)
        n_notice = kc.get("批次通报", 0) + kc.get("年度汇总", 0) + kc.get("专项行动", 0) \
            + kc.get("测评评议", 0)
        n_close = kc.get("下架处置", 0)
        n_fix = kc.get("整改复核", 0)
        apps.append({
            "app": rep_name,
            "ak": app_key(rep_name),
            "aliases": sorted(set(r["app"] for r in rows) - {rep_name}),
            "dev": rep_dev,
            "dev_aliases": [d for d in devs if d != rep_dev],
            "n_rows": len(rows),
            "n_incidents": len(inc),
            "n_notice": n_notice,
            "n_fix": n_fix,
            "n_close": n_close,
            "incidents": inc,
            "docs": sorted({r["doc"] for r in rows}),
            "orgs": orgs,
            "n_orgs": len(orgs),
            "probs": all_probs,
            "probs_first": first_probs,
            "probs_last": last_probs,
            "new_probs": new_probs,
            "first": first,
            "last": last,
            "span_days": gaps and sum(gaps) or 0,
            "relapse_gaps": gaps,
            "escalated": escalated,
            "reviewed": reviewed,
            "name_collision": 1 if any(collision.get(k, 0) > 1 for k in member_keys) else 0,
            "cross_lang": 1 if any(cross_lang.get(k) for k in member_keys) else 0,
            "no_owner": 1 if not rep_dev else 0,
            "provinces": sorted({r["province"] for r in rows if r["province"]}),
        })

    apps.sort(key=lambda a: (-a["n_incidents"], a["app"]))

    stats = {
        "rows_raw": len(recs),
        "rows_dedup_in_doc": len(ev),
        "dup_rows_removed": n_dup_rows,
        "apps": len(apps),
        "apps_repeat": sum(1 for a in apps if a["n_incidents"] > 1),
        "apps_repeat_notice": sum(1 for a in apps if a["n_notice"] > 1),
        "apps_multi_org": sum(1 for a in apps if a["n_orgs"] > 1),
        "apps_name_collision": sum(1 for a in apps if a["name_collision"]),
        "apps_cross_lang": sum(1 for a in apps if a["cross_lang"]),
        "apps_no_owner": sum(1 for a in apps if a["no_owner"]),
        "apps_escalated": sum(1 for a in apps if a["escalated"]),
        "apps_reviewed": sum(1 for a in apps if a["reviewed"]),
        "apps_closed": sum(1 for a in apps if a["n_close"]),
        "incidents": sum(a["n_incidents"] for a in apps),
        "incidents_notice": sum(a["n_notice"] for a in apps),
        "incidents_fix": sum(a["n_fix"] for a in apps),
        "incidents_close": sum(a["n_close"] for a in apps),
        "relapse_gap_median": _median([g for a in apps for g in a["relapse_gaps"]]),
    }
    return apps, stats


def _median(xs):
    if not xs:
        return 0
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


if __name__ == "__main__":
    import json, os, sys
    HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(HERE, "sources", "appviol", "docs.json")
    if len(sys.argv) > 1:
        p = sys.argv[1]
    docs = json.load(open(p, encoding="utf-8"))["docs"]
    apps, st = resolve(docs)
    print(json.dumps(st, ensure_ascii=False, indent=1))
    print("\n--- 通报次数 TOP 12 ---")
    for a in apps[:12]:
        print(f"  {a['n_incidents']}次 {len(a['orgs'])}机构 {a['app'][:22]:<24}"
              f"{a['dev'][:20]:<22}升级={a['escalated']} 新增问题={len(a['new_probs'])}")
    print("\n--- 同名不同主体（治理情报）---")
    for a in [x for x in apps if x["name_collision"]][:8]:
        print(f"  {a['app']}｜主署名 {a['dev']}｜其他署名 {a['dev_aliases'][:2]}")
    print("\n--- 中外文并存 ---")
    for a in [x for x in apps if x["cross_lang"]][:6]:
        print(f"  {a['app']}｜{a['dev']}｜{a['dev_aliases'][:2]}")
