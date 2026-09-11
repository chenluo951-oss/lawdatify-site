#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引源分级与合规校验（全站唯一口径）。

为什么需要它
------------
站点的每一条内容都要能「点进去看到发布机构自己的说法」。只靠人工记住
「这条要引官网」，随着条目变多一定会漏；所以把口径固化成代码：

    official   官方账号 / 官方原文
               立法机关、监管机构、政府门户的官网或公众号原文。
               例：npc.gov.cn、cac.gov.cn（网信中国/网信浙江/网安局）、
               samr.gov.cn、miit.gov.cn、mohrss.gov.cn、nhc.gov.cn、
               mofcom.gov.cn、court.gov.cn，境外为 ec.europa.eu、ftc.gov、
               oag.ca.gov、pdpc.gov.sg、meity.gov.in 等。

    gov-media  官方媒体
               人民日报、新华社、央视、光明日报、中新社、经济日报、央广、
               澎湃新闻、中国网、求是、科技日报等。

    academic   官方学术机构 / 协会组织
               中国信通院、TC260、标准信息平台、高校（.edu.cn）、
               中消协、中国互联网协会、行业协会等。

    other      其他（商业媒体、律所与厂商博客、二手转载）

硬规则（构建期强制）
--------------------
**立法 / 法规标准发布与生效 / 合规专项行动 / 监管处罚案例** 这四类，
必须落在 `official`。命中不了就在构建时打印违规清单；`strict=True` 时直接
终止构建，防止二手转载被当成一手依据发到站点上。

合规资讯（动态、解读、趋势）允许 `gov-media` 与 `academic`；
`other` 会被标为「二手转载」并列入待替换清单。

用法
----
    from sources_tier import tier_of, tier_tag, audit_sources

    tier_of("https://www.samr.gov.cn/zw/...")        # -> "official"
    tier_tag("https://www.samr.gov.cn/zw/...")       # -> HTML badge
    audit_sources(items, kind_key="type", strict=False)
"""

from urllib.parse import urlparse

TIER_ORDER = ("official", "gov-media", "academic", "other")

TIER_LABEL = {
    "official": "官方原文",
    "gov-media": "官方媒体",
    "academic": "专业机构",
    "other": "二手转载",
}

TIER_CLASS = {
    "official": "src-off",
    "gov-media": "src-media",
    "academic": "src-aca",
    "other": "src-oth",
}

TIER_DESC = {
    "official": "立法机关、监管机构、政府门户发布的原文",
    "gov-media": "人民日报、新华社、央视、澎湃等官方媒体",
    "academic": "官方学术机构、标准化组织与行业协会",
    "other": "商业媒体、机构博客或二手转载",
}

# ---------------------------------------------------------------- 官方来源
# 命中即 official。先用具体域名，再用后缀规则兜底（gov.cn / .gov / .go.jp …）
OFFICIAL_HOSTS = {
    # 中国：立法机关
    "npc.gov.cn", "flk.npc.gov.cn",
    # 中国：网信 / 工信 / 市场监管 / 人社 / 卫健 / 商务 / 司法
    "cac.gov.cn", "beian.cac.gov.cn", "12377.cn",
    "miit.gov.cn", "samr.gov.cn", "openstd.samr.gov.cn",
    "mohrss.gov.cn", "nhc.gov.cn", "zwfw.nhc.gov.cn",
    "mofcom.gov.cn", "trb.mofcom.gov.cn",
    "court.gov.cn", "spp.gov.cn", "mps.gov.cn", "moj.gov.cn",
    "ndrc.gov.cn", "mof.gov.cn", "mot.gov.cn", "moa.gov.cn",
    "most.gov.cn", "customs.gov.cn", "nea.gov.cn", "nmpa.gov.cn",
    "stats.gov.cn", "sasac.gov.cn", "gov.cn", "www.gov.cn",
    # 境外监管机构
    "ec.europa.eu", "digital-strategy.ec.europa.eu", "eur-lex.europa.eu",
    "edpb.europa.eu", "europa.eu",
    "ftc.gov", "oag.ca.gov", "ico.org.uk", "www.gov.uk",
    "pdpc.gov.sg", "meity.gov.in", "gov.br", "www.gov.br",
    "oecd.org", "un.org", "unesco.org", "europol.europa.eu",
}

OFFICIAL_SUFFIX = (
    "gov.cn", ".gov", ".gob.", ".gouv.", ".go.jp", ".go.kr",
    ".gov.uk", ".gov.au", ".gov.sg", ".gov.in", ".gov.br",
    ".gov.za", ".gov.ae", ".gov.hk", ".gov.mo",
)

# ---------------------------------------------------------------- 官方媒体
GOV_MEDIA_HOSTS = {
    "people.com.cn", "www.people.com.cn", "cpc.people.com.cn", "politics.people.com.cn",
    "xinhuanet.com", "www.xinhuanet.com", "news.cn", "www.news.cn",
    "cctv.com", "news.cctv.com", "cnr.cn", "www.cnr.cn",
    "gmw.cn", "www.gmw.cn", "chinanews.com.cn", "www.chinanews.com.cn",
    "ce.cn", "www.ce.cn", "china.com.cn", "www.china.com.cn",
    "qstheory.cn", "www.qstheory.cn", "stdaily.com", "www.stdaily.com",
    "thepaper.cn", "www.thepaper.cn", "jfdaily.com", "www.jfdaily.com",
    "chinapeace.gov.cn",
}

# ---------------------------------------------------------------- 学术 / 协会
ACADEMIC_HOSTS = {
    "caict.ac.cn", "www.caict.ac.cn",              # 中国信息通信研究院
    "tc260.org.cn", "www.tc260.org.cn",            # 全国信息安全标准化技术委员会
    "cnis.ac.cn", "www.cnis.ac.cn",
    "sacinfo.org.cn", "www.sacinfo.org.cn",        # 国家标准信息公共服务平台
    "isc.org.cn", "www.isc.org.cn",                # 中国互联网协会
    "cybersac.cn", "www.cybersac.cn",              # 中国网络空间安全协会
    "cca.org.cn", "www.cca.org.cn",                # 中国消费者协会
    "chinawuliu.com.cn", "www.chinawuliu.com.cn",  # 中国物流与采购联合会
    "ccas.com.cn", "www.ccas.com.cn",              # 中国烹饪协会
    "chinacpi.org", "www.chinacpi.org",
    "cagp.org.cn", "www.cagp.org.cn",
    "ssrn.com", "arxiv.org", "papers.ssrn.com",
}

ACADEMIC_SUFFIX = (".edu.cn", ".edu", ".ac.cn", ".ac.uk", ".org.cn")


def _host(url):
    try:
        h = urlparse((url or "").strip()).netloc.lower()
    except Exception:
        return ""
    if h.startswith("www."):
        h = h[4:]
    return h


def tier_of(url, declared=None):
    """按 URL 主机判定来源层级；`declared` 为数据里已有的 src 字段（兼容旧值）。"""
    h = _host(url)
    if not h:
        return {"official": "official", "analysis": "academic"}.get(declared or "", "other")

    for cand in (h, "www." + h):
        if cand in OFFICIAL_HOSTS:
            return "official"
        if cand in GOV_MEDIA_HOSTS:
            return "gov-media"
        if cand in ACADEMIC_HOSTS:
            return "academic"

    if h.endswith(OFFICIAL_SUFFIX) or any(s in h for s in ("gov.cn", "europa.eu")):
        return "official"
    # 官方媒体的子域名（m.gmw.cn / wlaq.gmw.cn / m.thepaper.cn …）也要归到同一层级
    if any(s in h for s in ("people.com.cn", "xinhuanet.com", "news.cn", "cctv.com",
                            "gmw.cn", "ce.cn", "thepaper.cn", "cnr.cn",
                            "chinanews.com.cn", "qstheory.cn", "stdaily.com")):
        return "gov-media"
    if h.endswith(ACADEMIC_SUFFIX):
        return "academic"
    return "other"


def tier_tag(url, declared=None, with_title=True):
    """渲染一枚来源层级徽章（class 已在 assets/style.css 定义）。"""
    t = tier_of(url, declared)
    title = f' title="{TIER_DESC[t]}"' if with_title else ""
    return f'<span class="rd-src {TIER_CLASS[t]}"{title}>{TIER_LABEL[t]}</span>'


# ---------------------------------------------------------------- 硬规则校验
# 这几类内容只接受 official
STRICT_KINDS = (
    "立法", "法律", "行政法规", "部门规章", "地方性法规", "规章",
    "条例", "办法", "规定", "决定", "通知", "公告",
    "草案", "征求意见", "修正", "修订", "施行", "生效", "发布", "印发",
    "标准", "国家标准", "行业标准", "团体标准",
    "专项行动", "专项整治", "执法", "整治", "治理", "检查", "约谈", "通报",
    "处罚", "罚款", "行政处罚", "处罚决定", "判决", "判例", "典型案例",
)

# 这几类允许官方媒体 / 专业机构（属"资讯"而非"依据"）
SOFT_KINDS = ("动态", "解读", "评论", "趋势", "观察", "综述", "简报", "资讯", "观点")


def _kind_of(item, kind_key):
    if kind_key is None:
        return ""
    if isinstance(kind_key, (list, tuple)):
        return " ".join(str(item.get(k, "") or "") for k in kind_key)
    return str(item.get(kind_key, "") or "")


def classify_rule(kind_text):
    """返回 'strict' | 'soft' | 'unknown'。"""
    if any(k in kind_text for k in SOFT_KINDS):
        return "soft"
    if any(k in kind_text for k in STRICT_KINDS):
        return "strict"
    return "unknown"


def audit_sources(items, kind_key="type", url_key="url", name_key="title",
                  id_key=None, strict=False, label=""):
    """校验一组条目的来源层级。

    返回违规清单 [{name, url, tier, rule, kind}]。
    `strict=True` 且存在 strict 类违规时抛 SystemExit。
    """
    bad = []
    for it in items:
        if not isinstance(it, dict):
            continue
        url = it.get(url_key) or ""
        if not url:
            continue
        rule = classify_rule(_kind_of(it, kind_key))
        if rule == "soft":
            continue
        tier = tier_of(url, it.get("src"))
        if tier == "official":
            continue
        if rule == "strict" or tier == "other":
            bad.append({
                "name": str(it.get(name_key) or it.get(id_key) or ""),
                "url": url,
                "tier": tier,
                "rule": rule,
                "kind": _kind_of(it, kind_key).strip(),
            })

    if bad:
        head = f"引源校验{'（' + label + '）' if label else ''}"
        must = [b for b in bad if b["tier"] == "other"]
        sugg = [b for b in bad if b["tier"] != "other"]
        print(f"  {head}：{len(bad)} 条需要处理"
              f"（必须替换为官方原文 {len(must)} / 建议回溯官方原文 {len(sugg)}）")
        for b in must + sugg:
            mark = "✗" if b["tier"] == "other" else "△"
            print(f"    {mark} [{TIER_LABEL[b['tier']]}] {b['name'][:36]}  {b['url'][:66]}")
        if strict and must:
            raise SystemExit(
                f"{head}未通过：立法/标准/专项行动/监管处罚类必须引用官方账号原文。")
    else:
        print(f"  引源校验{'（' + label + '）' if label else ''}：通过")
    return bad


def tier_tally(items, url_key="url"):
    tally = {t: 0 for t in TIER_ORDER}
    for it in items:
        if isinstance(it, dict) and it.get(url_key):
            tally[tier_of(it[url_key], it.get("src"))] += 1
    return tally


if __name__ == "__main__":
    demo = [
        ("https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_x.html", "官方"),
        ("https://www.gov.cn/zhengce/content/202403/content_6940158.htm", "政府门户"),
        ("https://www.thepaper.cn/newsDetail_forward_1", "官方媒体"),
        ("https://www.caict.ac.cn/kxyj/", "学术机构"),
        ("https://cn-sec.com/archives/5418009.html", "二手"),
        ("https://artificialintelligenceact.eu/implementation-timeline/", "二手"),
    ]
    for u, note in demo:
        print(f"{tier_of(u):<10} {TIER_LABEL[tier_of(u)]:<6} {note:<8} {u}")
