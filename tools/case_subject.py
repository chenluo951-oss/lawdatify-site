# -*- coding: utf-8 -*-
"""从案例正文/标题里提取「被处罚主体」。

## 为什么要单独一层

案例库的数据来自三类页面，主体的书写方式完全不同：

1. **行政处罚决定书 / 信息公开表**（地方市监局）：页面里就有
   `当事人：XX有限公司`，直接可摘；
2. **典型案例通报**（总局、省市局）：没有「当事人」标签，主体散落在案情叙述里
   （`张家港市市场监管局查处苏州观心健康科技有限公司虚假宣传案。该公司……`），
   只能靠**组织形式后缀**（有限公司/商行/大药房/餐饮店…）反推；
3. **App 违规通报**（工信部/网信办）：主体就是 App 名与运营企业，正文里常写
   `XX App（开发者：XX科技有限公司）`。

所以这里做**四路兜底**，按可信度从高到低：

    A. 显式标签  当事人/被处罚单位/行政相对人：XXX
    B. 案件标题  标题里的组织名（个案标题几乎必含主体）
    C. 正文首个组织名
    D. 一文多案  取首个 + 计数，展示成「XXX 等 N 家」

⚠️ 反查过的一个坑：if 先去组织后缀找，再去标签找（顺序反了会怎样）——
标签值可能是「张某某」这种自然人，而后缀反推只会给企业名。两类都要留，
所以 A 路命中即返回（自然人也是合法主体），B/C 路才做后缀反推。
"""

import re

# ── A 路：显式标签 ─────────────────────────────────────────────
_LABEL = re.compile(
    r"(?:当事人(?:名称|姓名)?|被处罚(?:单位|人|者|对象)|被检查(?:单位|人)|"
    r"行政相对人|违法行为人|涉案(?:单位|企业|主体|当事人)|涉事(?:单位|企业|主体)|"
    r"处罚对象|被申请人)\s*[:：]\s*"
    r"([^\s，。；、：:，。]{2,40})"
)

# 标签值里的**非主体**写法（占位符 / 泛指 / 页面噪声）
_BAD_VALUE = re.compile(
    r"^(?:无|不详|未知|待定|略|见附件|见下文|详见|其他|若干|自然人|个人|"
    r"某公司|某单位|某企业|该公司|该单位|上述|相关|有关|当事人|不详。|—|-|/)"
)

# ── 机构名先屏蔽 ───────────────────────────────────────────────
# ⚠️ 必做，否则「安徽省蚌埠市市场监督管理局」会被后缀「市场/局」反推成
# 「安徽省蚌埠市市场」这种半截机关名当主体（实测高频误报）。
_AGENCY = re.compile(
    r"[\u4e00-\u9fa5]{2,14}?(?:市场监督管理局|市场监督管理所|市场监管管理局|"
    r"市场监督管理局|市场监督局|市场监管局|监督管理局|管理局|监管局|市监局|"
    r"人民政府|管理委员会|互联网信息办公室|网信办|通信管理局|"
    r"工业和信息化厅|工业和信息化局|人民法院|人民检察院|知识产权局|"
    r"药品监督管理局|综合行政执法|行政执法局|发展和改革委员会|"
    r"商务厅|委员会|办公厅|办公室|法院|检察院)"
)

# ── B/C 路：组织形式后缀反推 ───────────────────────────────────
# ⚠️ 后缀必须是**组织形式**本身。「科技/商贸/贸易/实业/投资/企业/集团/服务/
# 中心/市场」这类是**弱后缀**，实测会把「监管局查处苏州观心健康科技」这种
# 半截串当成主体名（懒惰量词最短匹配停在「科技」）→ 一律不进表；
# 要出现就与「有限公司」等强后缀组合出现。
_ORG_SUF = (
    "股份有限公司|有限责任公司|有限公司|有限合伙|股份公司|分公司|子公司|公司|"
    "个体工商户|个体经营户|个人独资企业|合伙企业|"
    "商行|商店|商厦|商城|超市|生活超市|便利店|连锁店|分店|专卖店|旗舰店|网店|"
    "门市部|经营部|批发部|销售部|服务部|售后部|"
    "药店|大药房|药房|医药馆|诊所|医院|门诊部|卫生院|"
    "餐饮店|饭店|餐厅|酒店|宾馆|旅馆|旅店|招待所|小吃店|早餐店|快餐店|"
    "食品店|副食店|水果店|生鲜店|蔬菜店|甜品店|奶茶店|烘焙店|面包店|"
    "美容店|美发店|理发店|养生馆|按摩店|足浴店|游泳馆|健身房|影院|影城|"
    "学校|幼儿园|托育|协会|商会|学会|基金会|事务所|研究院|"
    "工厂|制造厂|食品厂|加工厂|农场|养殖场|合作社|"
    "批发市场|农贸市场|交易市场|工作室|直播间"
)

# 主体名本体：必须以中文/字母开头（避免从「9月7日」这种数字串开始匹配）
_NAME = re.compile(
    r"([\u4e00-\u9fa5A-Za-z（(][\u4e00-\u9fa5A-Za-z0-9（）()·\-—]{1,29}?"
    r"(?:" + _ORG_SUF + r"))"
)

# 名字开头混进了动词/连接词（「监管局查处苏州观心健康科技有限公司」「涉及XX公司」）
# ⚠️ **只切开头，不能写成 `.*?(?:…)`**：那样「和/为/是/及/在」这些单字会把
# 「苏州和记食品有限公司」从中间截断成「记食品有限公司」（实测事故）。
_PREFIX_CUT = re.compile(
    r"^(?:(?:涉及|查获|查处|查办|发现|制止|标示|通报|曝光|公布|责令|立案|整治|"
    r"处理|约谈|移送|用于|所属|直属|上述|相关|有关|对|向|给|在|与|及|其|该|本|经|由)+)"
)

# 名字里不应出现这些词（泛指 / 指代 / 计数 / 半截机构名）
_BAD_IN = re.compile(
    r"两家|一家|多家|几家|数家|经营单位|实际控制|当事人|该公司|该单位|上述|相关|有关|"
    r"某公司|等单位|等部门|及其他|等其他"
)

# 名字前带这些字，说明是泛指/承接词，不是具体主体
_BAD_ORG = re.compile(
    r"^(?:该|本|上述|相关|有关|涉案|涉事|各|全|多家|个别|一些|部分|所有|"
    r"当事人|被处罚|被检查|某某|某|旗下|其|和|与|及|对|向|在|等)"
)

# 脱敏名（`******`、`***代理事务所`）不作为主体展示
_MASKED = re.compile(r"[*＊]{2,}")

# 脱敏占位（`******代理事务所`、`有限公司`）：整段带邻居一起挖掉，
# 否则 `******` 后面的残片会被后缀规则反推成「代理事务所」「有限公司」这种垃圾主体
_MASK_RUN = re.compile(r"[*＊]{1,}[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{0,22}")

# App / SDK 通报的主体：应用名
_APP = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9·\-]{2,20}?)\s*(?:App|APP|app|应用软件|小程序)")
_APP_STOP = re.compile(r"^(?:该|本|上述|相关|有关|涉案|其他|以下|部分|多个|一批|"
                       r"侵害|存在|涉及|违规|通报|应用|软件|手机|用户|这些|部分)")
_APP_DEV = re.compile(r"(?:开发者|运营者|运营主体|开发运营|公司名称|企业名称|主体)\s*[:：]\s*"
                      r"([^\s，。；、：:]{2,40})")

# A 路命中后仍要看一眼：值里带这些词说明抓歪了
_BAD_LABEL_TAIL = re.compile(r"(?:的|了|等|并|和|与|及)$")


def _clean_value(v):
    v = re.sub(r"\s+", "", v or "")
    v = v.strip("（()）.:：、,，;；”\"'’“")
    return v


def _ok_label(v):
    if not v or len(v) < 2 or len(v) > 40:
        return False
    if _BAD_VALUE.search(v) or _BAD_IN.search(v):
        return False
    if _BAD_LABEL_TAIL.search(v):
        return False
    # 标签值出现「XX法」「XX条例」说明抓到法条了
    if re.search(r"(?:法|条例|办法|规定|标准|通知|公告)$", v):
        return False
    return True


def _dedupe(names):
    """去重：被更长名字完全包含的短名丢掉（「观心科技」vs「苏州观心健康科技有限公司」）。"""
    out = []
    for n in sorted(set(names), key=len, reverse=True):
        if not any(n in o and n != o for o in out):
            out.append(n)
    return out


def org_names(text):
    """正文里出现的组织名（按出现顺序去重）。机构名与脱敏段先屏蔽再反推。"""
    t = _AGENCY.sub(" ", text or "")
    t = _MASK_RUN.sub(" ", t)
    found = []
    for m in _NAME.finditer(t):
        n = _PREFIX_CUT.sub("", m.group(1))
        # 括号没闭合的（「…（锡山区东港小吴饭店」）→ 砍到括号前
        if "（" in n and "）" not in n.split("（", 1)[1]:
            n = n.split("（", 1)[0]
        n = _clean_value(n)
        if len(n) < 5 or len(n) > 30:
            continue
        # 只剩后缀残片（「有限公司」「代理事务所」）→ 丢
        if len(n) <= 6 and re.match(r"^(?:有限|股份|责任|代理|事务|合伙)", n):
            continue
        if _MASKED.search(n) or _BAD_IN.search(n) or _BAD_ORG.search(n):
            continue
        if n not in found:
            found.append(n)
    return _dedupe(found)


def _from_title(title):
    """标题里的主体：标题几乎必含主体，且很少用指代词。"""
    return (org_names(title) or [""])[0]


# 集合类标题：一条公示里打包了多起案件
_COLLECTION = re.compile(r"典型案例|通报|批次|曝光|第[一二三四五六七八九十\d]{1,3}批|公布|"
                         r"专项行动|铁拳|守护|集中|案例汇编|名单")


def extract_subject(fact, title="", limit=3):
    """返回 (主体名, 主体数量)。

    主体数量用于「一文多案」：通报一批案例时，表格里给首个主体 +
    「等 N 家」，避免把 20 家企业名塞进单元格。只有**集合类标题**
    才计多主体，否则一条一案（正文里出现的其他企业名是干扰项）。
    """
    fact = fact or ""
    title = title or ""

    # A 路：显式标签（自然人 / 企业都认）
    m = _LABEL.search(fact) or _LABEL.search(title)
    if m:
        v = _clean_value(m.group(1))
        if _ok_label(v) and not _MASKED.search(v):
            rest = org_names(fact)
            n = (len(rest) + 1) if (_COLLECTION.search(title) and len(rest) > limit) else 1
            return v, n

    # App / SDK 通报：主体是应用名，运营企业在「开发者：」里
    if re.search(r"App|APP|应用软件|小程序", title) or re.search(r"开发者\s*[:：]", fact):
        md = _APP_DEV.search(fact)
        if md:
            v = _clean_value(md.group(1))
            if _ok_label(v) and not _MASKED.search(v):
                return v, 1
        for m in _APP.finditer(fact):
            v = _clean_value(m.group(1))
            if len(v) >= 2 and not _APP_STOP.search(v):
                return v, 1
        return "", 0

    # 专利侵权纠纷行政裁决：主体写在「请求人」里
    m = re.search(r"请求人\s*[:：]?\s*([^\s，。；、：:]{2,40})", fact)
    if m and _ok_label(_clean_value(m.group(1))):
        return _clean_value(m.group(1)), 1

    # B 路：标题里的组织名；C 路：正文里的组织名
    name = _from_title(title)
    names = org_names(fact)
    if not name and names:
        name = names[0]

    if name:
        n = 1
        if _COLLECTION.search(title):
            others = [x for x in names if x != name]
            if len(others) > limit:
                n = len(others) + 1
        return name, n

    # 兜底 1：自然人标题（「肖鹏销售侵犯“郎”注册商标专用权的商品案」）
    m = re.match(r"^([\u4e00-\u9fa5]{2,4})(?:销售|生产|经营|购进|使用|发布|未|无照|擅自)", title)
    if m and _ok_label(m.group(1)):
        return m.group(1), 1
    # 兜底 2：正文里的「对 XX 作出处罚」
    m = re.search(r"对([\u4e00-\u9fa5]{2,4})(?:作出|予以|处以|下达)", fact)
    if m and _ok_label(m.group(1)):
        return m.group(1), 1
    return "", 0


def format_subject(name, n):
    """表格用的展示串。"""
    if not name:
        return ""
    if n and n > 1:
        return f"{name} 等 {n} 家"
    return name


if __name__ == "__main__":
    import json
    import os
    import collections

    HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(os.path.join(HERE, "sources", "cases", "cases.json"), encoding="utf-8"))
    cs = d["cases"]
    hit = 0
    multi = 0
    cnt = collections.Counter()
    for c in cs:
        nm, n = extract_subject(c.get("fact"), c.get("title"))
        if nm:
            hit += 1
            if n > 1:
                multi += 1
        else:
            cnt[c.get("kind")] += 1
    print(f"命中 {hit}/{len(cs)}　多主体 {multi}")
    print("未命中按 kind：", cnt.most_common())
    for c in cs[:15]:
        nm, n = extract_subject(c.get("fact"), c.get("title"))
        print(f"  · {format_subject(nm, n) or '（空）':<34} | {c['title'][:36]}")
    print("—— 决定书类样本 ——")
    k = 0
    for c in cs:
        if c.get("kind") == "行政处罚决定书" and k < 10:
            nm, n = extract_subject(c.get("fact"), c.get("title"))
            print(f"  · {format_subject(nm, n) or '（空）':<34} | {c['title'][:40]}")
            k += 1
