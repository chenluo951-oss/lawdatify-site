#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prune_policy.py —— 资讯条目「保留 / 清理」判定（**已停用 · 仅作历史留档**）。

⛔ 停用说明（2026-09-15，用户决定）
----------------------------------
用户原话：「**如果不占用负载，那就别删了**」。
实测结论：资讯 HTML 经 gzip 后线上实际传输量很小（台账页 2.04MB → 257KB，
资讯页 212KB → 58KB），**资讯条目根本不占负载**——已部署体积的 91%（277MB / 304MB）
是 `kb/std/` 里的标准原版 PDF。既然不占负载，就没有清理内容的理由。

因此：
- **本模块与 `tools/prune_low_value.py` 已停用**，不要再调用、不要给条目打 `pruned` 标记、
  不要维护 `sources/news/pruned_blacklist.json`；每周日的清理自动化任务已删除。
- 构建侧对 `pruned` 的过滤（`build_topics.load_native` / `build_updates`）与采集侧的黑名单闸门
  （`tools/collect_news.py`）**保留但处于休眠态**：当前 **0 条**被标记，黑名单文件不存在，
  全站没有任何一条内容因本策略而缺席。
- 容量问题只允许用「大件 PDF 外部化 / 按需加载」这类**不减少内容**的手段解决；
  体检用 `tools/site_size.py`（已并入每周一 08:00 的内容完善巡检，只观测不删除）。

以下为停用前的原始口径（留档备查）
----------------------------------
为避免网站内容无限膨胀、无法负载，**每周清理一次**，把「行业政策性、与合规关联不大」的
内容清掉；而下面这些「合规导向、知识积累」的内容**绝对不能删**：

    监管专项 · 处罚通报 · 司法案例 · 专业分析 · 法律法规 · 标准文件 · 指引指南

设计要点
--------
1. **作用域只有资讯条目**（`sources/news/items.jsonl`）。法律法规 / 标准文件 / 指引指南
   分别存放在 `sources/standards/`、`kb/std/`、`sources/library/`、`kb/wx/`，
   本策略**一律不碰**（渲染层也不会因本策略少掉任何一条依据类内容）。
2. **拿不准就保留**：只有「命中行业政策性信号」**且**「完全没有合规锚点」才判清理；
   只要命中任一保留信号（含 kind 属合规导向、来源为专业机构、有站内原文存档、
   含本站实质分析），一律保留。
3. **只打标记，不物理删除**：命中清理的条目在行内加 `pruned: true` + `prune_reason`，
   随时可 `tools/prune_low_value.py --restore-all` 回滚，数据零丢失。
4. **黑名单防复活**：清理过的标题 / 链接记入 `sources/news/pruned_blacklist.json`，
   采集器（`tools/collect_news.py`）据此拒收，避免次日又把同一条抓回来（否则每周白清）。

对外接口
--------
    classify(row, today=None, min_age_days=...) -> (action, reason, score)   # action: keep|prune
    keep_reason(row) / industry_signals(text)                                # 供调试
    load_blacklist() / save_blacklist() / blacklist_hit(title, url)
"""
import json
import os
import re
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BLACKLIST = os.path.join(HERE, "sources", "news", "pruned_blacklist.json")

# 新条目保护期：刚入库的条目不动（避免误清当日重要内容 / 采编流程尚未走完）
DEFAULT_MIN_AGE_DAYS = 30
# analysis 达到此长度视为「本站实质分析」→ 知识积累，保留
ANALYSIS_KEEP_LEN = 180

# ---------------------------------------------------------------- 保留信号
# 「合规导向、知识积累」类 kind —— 用户明示绝对不能删的类别
KEEP_KINDS = {
    "新规发布", "处罚案例", "专项行动", "标准动态", "立法进程", "司法动态",
    "执法通报", "专题述评", "深度分析", "法律分析", "政策问答", "指引指南",
    "监管专项", "专项治理", "国际动态",
}

# 文本（标题 + 要点）命中即保留的合规锚点。分组名用于报告可读性。
KEEP_RX = [
    ("法规标准", r"法律|法规|条例|办法|规定|规则|标准|规范|准则|司法解释|实施细则"
                 r"|国家标准|行业标准|团体标准|地方标准|GB\s*[/\s]*T?\s*\d|强制性"),
    ("指引指南", r"指引|指南|问答|清单|合规管理|操作手册|实务手册|工作指引|合规指引|自查表"),
    ("监管专项", r"专项行动|专项整治|专项治理|专项检查|清朗|集中治理|执法行动|百日行动"
                 r"|整治行动|专项执法|联合检查|监督检查"),
    ("处罚通报", r"处罚|罚款|罚没|没收|行政处罚|查处|通报|曝光|约谈|责令|典型案例|警示"),
    ("司法案例", r"判决|裁定|案例|人民法院|法院|人民检察院|检察院|诉讼|公益诉讼|司法"),
    ("立法进程", r"征求意见|草案|立法|审议|修订|通过|施行|生效|废止"),
    ("数据/AI/算法义务", r"个人信息|隐私|数据安全|数据出境|数据跨境|算法|生成式|人工智能"
                          r"|大模型|智能体|备案|安全评估|等级保护|关键信息基础设施|自动化决策"),
    ("业务核心义务", r"食品安全|食品标识|抽检|快检|保质期|临期|召回|餐饮|冷链|价格"
                      r"|明码标价|促销|折扣|广告|虚假宣传|不正当竞争|消费者权益|计量|电子秤"
                      r"|过度包装|禁塑|绿色"),
]

# 来源档位属「专业机构 / 研究号」→ 专业分析与同行解读，保留
PROTECT_TIERS = {"academic", "research"}
# 站内原文存档 / 国家级法律法规数据库 → 知识积累入口，保留
KEEP_URL_HOSTS = ("flk.npc.gov.cn",)

# ---------------------------------------------------------------- 清理信号
# 「行业政策性、与合规关联不大」的表征。仅在**完全没有**上面的保留信号时才生效。
INDUSTRY_RX = [
    ("产业发展", r"产业发展|产业规划|发展规划|规划纲要|产业政策|促消费|提振消费|消费季"
                 r"|消费券|补贴|奖补|财政扶持|扶持政策|专项资金|招商引资"),
    ("试点示范", r"试点城市|示范城市|示范区|示范点|试点名单|示范基地|先进典型|评选|评比"
                 r"|表彰|授牌|标杆|典型案例评选"),
    ("会展活动", r"论坛|峰会|博览会|交易会|展销|推介会|发布会|座谈会|研讨会|调研|走访"
                 r"|考察|开放日|宣传活动"),
    ("内部事务", r"人事|任免|招聘|招录|预算|决算|统计公报|经济运行|年度报告|工作要点"
                 r"|工作总结|工作计划|值班|党建|党风廉政"),
]


def _text(row):
    return ((row.get("title") or "") + " " + (row.get("points") or "")).strip()


def keep_reason(row):
    """返回保留原因；None 表示未命中任何保留信号（可进入清理判定）。"""
    kind = (row.get("kind") or "").strip()
    if kind in KEEP_KINDS:
        return f"kind={kind}（合规导向类别）"
    txt = _text(row)
    hits = [name for name, rx in KEEP_RX if re.search(rx, txt)]
    if hits:
        return "命中合规锚点：" + "/".join(hits)
    if (row.get("tier") or "").strip() in PROTECT_TIERS:
        return "来源为专业机构/研究号（专业分析）"
    if (row.get("wx_id") or "").strip():
        return "有站内公众号原文存档（知识积累）"
    url = row.get("url") or ""
    if any(h in url for h in KEEP_URL_HOSTS):
        return "国家级法律法规数据库条目"
    if len(row.get("analysis") or "") >= ANALYSIS_KEEP_LEN:
        return "含本站实质分析"
    return None


def industry_signals(text):
    return [name for name, rx in INDUSTRY_RX if re.search(rx, text or "")]


def age_days(row, today=None):
    """条目距今天数；无法解析日期返回 None（视为未知，按保护期处理）。"""
    d = (row.get("date") or row.get("collected") or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return None
    try:
        return ((today or date.today()) - datetime.strptime(d, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def classify(row, today=None, min_age_days=DEFAULT_MIN_AGE_DAYS):
    """判定单条：返回 (action, reason, score)。action ∈ {"keep", "prune"}。

    优先级：硬保留 → 专业来源/存档/实分析保留 → 保护期 → 行业政策性且无锚点才清理。
    """
    if row.get("pruned"):
        return "keep", "已在清理名单（勿重复判定）", 0
    kr = keep_reason(row)
    if kr:
        return "keep", kr, 90
    sig = industry_signals(_text(row))
    if not sig:
        return "keep", "无明确行业政策性标签（拿不准则保留）", 60
    age = age_days(row, today)
    if age is None:
        return "keep", "日期不可解析（按保护期保留）", 70
    if age < min_age_days:
        return "keep", f"新条目（{age} 天 < {min_age_days} 天保护期）", 70
    return "prune", "行业政策性（" + "/".join(sig) + "）且无合规锚点", -10


# ---------------------------------------------------------------- 黑名单
def norm_title(t):
    """标题归一化：只留中日韩文字与字母数字（与采集器判重口径一致）。"""
    return re.sub(r"[\W_]+", "", (t or "").lower(), flags=re.UNICODE)


def load_blacklist():
    try:
        d = json.load(open(BLACKLIST, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("_meta", {"desc": "资讯条目清理黑名单：采集器据此拒收，防止清理过的条目"
                                   "次日又被抓回（否则每周白清一次）。人工复核后可删除对应键恢复。",
                           "updated": "", "count": 0})
    d.setdefault("titles", {})
    return d


def save_blacklist(d):
    os.makedirs(os.path.dirname(BLACKLIST), exist_ok=True)
    d["_meta"]["updated"] = date.today().isoformat()
    d["_meta"]["count"] = len(d["titles"])
    json.dump(d, open(BLACKLIST, "w", encoding="utf-8"), ensure_ascii=False, indent=2, sort_keys=True)


def blacklist_hit(title, url=""):
    """该标题/链接是否在清理黑名单中。"""
    d = load_blacklist()
    key = norm_title(title)
    if key and key in d["titles"]:
        return d["titles"][key]
    for rec in d["titles"].values():
        if url and rec.get("url") and rec["url"] == url:
            return rec
    return None
