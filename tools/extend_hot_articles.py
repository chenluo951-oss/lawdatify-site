#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extend_hot_articles.py —— 批量扩写「高频引用法条」（kb/citations.html 的数据源）

为什么要「自动」而不是「手写」
------------------------------
`hot_articles.json` 里那 33 条是手工精写的（场景/正面示例都是业务语言），质量最高但不
可能手写 300 条。这个脚本的做法是把**能自动保证准确的部分**从官方原文里机器抽取：

  能被机器保证 100% 准确的：quote（条文原文，逐字取自站内原文库）、
                             penalty / liability（法律责任条款，取自同一部法的罚则条）、
                             cases（真实案例，取自案例库并带上官方深链）；
  只能模板化的：             scene（合规场景）/ positive（正面示例）—— 用「领域模板 +
                             本条自己的义务对象」拼，读起来仍然贴着这一条，不是万能话术。

产出写到 `sources/standards/hot_articles_auto.json`，**不覆盖手工文件**；
`build_citations.py` 把两份合并（手工优先，重复 (law, art) 以手工为准）。

选条规则（把「高频」落到实处，不是随机抽）
------------------------------------------
① 法域打分：法律名命中合规关键词（食品/广告/价格/竞争/消费者/网络交易/个人信息/
   数据/网络安全/算法/人工智能/产品质量/特种设备/计量/认证/商标/专利/药品/化妆品/
   医疗器械/市场主体/信用/行政处罚/反垄断/公平竞争…）；
② 案例库实证：该法在 `sources/cases/cases.json` 里被引用的次数（真实处罚依据）；
③ 每条法内取 罚则条（含「罚款/没收/责令/吊销」，最多 3 条）
   + 义务条（含「应当/不得/禁止」，最多 4 条）。

用法：
  python3 tools/extend_hot_articles.py                 # 生成/覆盖 auto 文件
  python3 tools/extend_hot_articles.py --target 300    # 目标总条数（默认 300）
  python3 tools/extend_hot_articles.py --dry           # 只统计不写盘
  python3 tools/extend_hot_articles.py --show 安 全生产  # 抽查若干法条效果
"""
import argparse
import hashlib
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

HOT = os.path.join(HERE, "sources", "standards", "hot_articles.json")
AUTO = os.path.join(HERE, "sources", "standards", "hot_articles_auto.json")
CASES = os.path.join(HERE, "sources", "cases", "cases.json")
TEXT_INDEX = os.path.join(HERE, "kb", "texts", "index.json")
TEXT_PARTS = os.path.join(HERE, "kb", "texts")
FLK_JSONL = os.path.join(HERE, "sources", "flk_texts", "texts.jsonl")

# ---------------------------------------------------------------- 法域判定
# 顺序敏感：先匹配到的赢（越具体的放前面）
DOMAIN_RULES = [
    ("food", "食品与产品质量合规",
     r"食品安全|食品|食用农产品|餐饮|保健食品|酒类|乳品|粮食|农兽药|生猪屠宰"),
    ("drug", "药品与医疗器械合规",
     r"药品|疫苗|医疗器械|化妆品|执业药师"),
    ("ad", "广告与营销合规", r"广告|商业宣传|促销|直销|传销|拍卖"),
    # ⚠️ 消保法以前被并进 price 域，结果「经营者应当听取消费者意见」这类义务条
    # 配的场景文案全是划线价/促销价，一眼对不上。凡是规则里同时写了「价格」与
    # 「消费者权益」，就该拆成两个域，别为了少一个筛选项把文案串到别的法上。
    ("consumer", "消费者权益与预付合规",
     r"消费者权益|消费者|预付|合同行政|旅游|学生用品"),
    ("price", "价格合规", r"价格|收费|明码标价"),
    ("comp", "竞争与反垄断合规",
     r"反不正当竞争|反垄断|公平竞争|经营者集中|垄断|招标投标|政府采购"),
    ("ip", "知识产权合规", r"商标|专利|著作权|地理标志|集成电路布图|植物新品种"),
    ("pi", "个人信息保护合规", r"个人信息|隐私|人脸识别|儿童个人"),
    ("data", "数据安全合规", r"数据安全|数据出境|数据交易|重要数据|测绘|地理信息"),
    ("net", "网络安全合规", r"网络安全|关键信息基础设施|密码|漏洞|计算机信息系统"),
    ("algo", "算法合规", r"算法|深度合成|推荐|互联网信息服务|深度伪造"),
    ("ai", "AI 合规", r"人工智能|生成式|大模型|智能体"),
    ("platform", "平台治理合规",
     r"电子商务|网络交易|平台|互联网信息服务|网络直播|社交电商|网络餐饮"),
    ("qual", "质量与特种设备合规",
     r"产品质量|特种设备|工业产品|缺陷|召回|燃气|消防|危险化学品|标准化|计量|"
     r"认证认可|检验检测|纤维|棉花|设备监理"),
    ("biz", "市场主体与信用合规",
     r"市场主体登记|企业信息公示|信用|无证无照|公司登记|个体工商户|年报|"
     r"经营异常|严重违法失信"),
    ("admin", "行政处罚与执法程序",
     r"行政处罚|行政强制|行政许可|行政复议|行政诉讼法|执法|听证|裁量"),
]
DEFAULT_DOMAIN = ("biz", "市场主体与信用合规")

# 义务/责任语汇
# ⚠️ 罚则关键词**必须是强证据**，裸的「取消」是个陷阱：「经营者应当听取消费者对其
# 提供的商品或者服务的意见，接受消费者的监督」里，「接**取消**费者的监督」会被
# 子串命中，于是消保法第十七/三十/三十二条被当成罚则条收进「违反本条的处罚」。
# （元凶是 findall 带分组时返回 [('', '')] 这种真值，`len(...) >= 1` 照样放行。）
# 规则：能给对象的一律带对象（取消其 / 取消资格 / 取消许可 / 取消备案）。
PEN_KW = re.compile(
    r"罚款|没收违法所得|没收非法财物|没收违法财物|"
    r"责令(?:改正|停产|停业|关闭|停止|限期)|"
    r"吊销(?:营业)?执照|吊销(?:相关)?许可证|"
    r"暂停(?:相关)?业务|暂停(?:业务|执业)|从业限制|终身禁业|"
    r"取消其|取消(?:资格|许可|备案|资质|指定)")
DUTY_KW = re.compile(r"应当|不得|禁止|必须|须")
# 适用范围条 / 定义条 —— 选进「高频法条」是纯噪声
SCOPE_RE = re.compile(r"制定(本法|本条例|本规定)|在中华人民共和国境内|本法所称|"
                      r"本条例所称|本规定所称|适用本法|依照本法")
DEF_RE = re.compile(r"^.{0,30}(是指|包括下列|分为下列)")
# 规范的客体是政府自身（不是经营者）的条款
GOV_RE = re.compile(r"^(各级|县级以上|国务院|国家|地方各级|本市|省|自治区|直辖市|"
                    r"有关部门|市场监督管理|监督检查)[^。；]{0,14}"
                    r"(人民政府|部门|机关|机构|政府)")
# 主体是消费者本人 / 全社会 —— 权利宣示，不是经营者义务
CONSUMER_RE = re.compile(r"^(消费者(?:享有|有权)|保护消费者的合法权益是全社会)")

# 领域场景模板：{law} 法规名简称、{obj} 本条的义务/规制对象
SCENE_TPL = {
    "food": "从采购验收、贮存温控、标签标识到临期与到期处置，任一环节的实际动作与本条要求对不上，"
            "就会在抽检、飞行检查或消费者投诉中被直接认定为违法；食品安全类处罚以「货值金额」为基数计算，"
            "货值越大罚得越重。",
    "drug": "许可资质、进销存台账、追溯码与不良反应报告缺一项即构成独立违法；"
            "药品、医疗器械、化妆品的处罚起点普遍高于一般商品，且可对直接负责的个人一并处罚。",
    "ad": "商品页、详情页、直播口播、短视频、私域社群与门店物料都是广告载体，"
          "宣传用语一旦被消费者或职业举报人抓取即按广告违法立案；"
          "宣传语、数据来源、对比依据要能当场上交。",
    "consumer": "门店告示、App/小程序页面、客服话术、售后规则都在消费者权益的规制范围内，"
                "「可以自行解释」的内部口径一旦落到对外页面就是违法；"
                "退换货、临期与破损处理、会员权益变更、自动续费是投诉与举报最集中的四个点，"
                "处理与否、多久处理、有没有留痕都会被调取。",
    "price": "划线价、促销价、会员价、满减凑单、赠品与运费都属于价格标示的规制范围；"
             "结算价与标示价不一致、优惠规则未同步更新，是最常见的立案口径。",
    "comp": "与同行、供应商、渠道商的每一次互动都可能是竞争法评价的对象，"
            "促销、排他、二选一、数据与算法都在射程内；虚假宣传与商业诋毁是投诉举报最集中的两个入口。",
    "ip": "选品、上架、包装、宣传与自有品牌开发都要过知识产权这一关，"
          "商标授权链、专利与外观权属、平台责任要能逐级追到文件；侵权判断不看主观意图，看权属与使用事实。",
    "pi": "会员体系、门店设备、App/小程序、客服与售后都在处理个人信息，"
          "同一件业务往往同时踩到「告知同意」「最小必要」「单独同意」三条线；"
          "个人信息保护影响评估与合规审计是监管看的第一份材料。",
    "data": "既涉及数据处理活动本身，也涉及与第三方（物流、支付、SaaS、营销服务商）的数据交互；"
            "分类分级、出境评估、对外提供合同是检查必看项。",
    "net": "网络安全义务以「谁运营谁负责」落点，"
           "漏洞管理、日志留存、等级保护测评与应急预案是形式审查的四个抓手。",
    "algo": "需要在备案、公示、评估与用户可关闭/可拒绝四条上闭环；"
            "备案信息与实际运行的算法不一致，是监管通报里最常见的口径。",
    "ai": "生成式与人工智能相关服务要落到内容标识、训练数据来源、用户告知与投诉渠道；"
          "上线前先确认备案（登记）与标识义务是否已履行。",
    "platform": "平台规则直接影响平台内经营者与消费者的权利义务，"
                "规则公示、资质核验、交易记录保存与纠纷处理是四个固定检查面。",
    "qual": "直接关系人身财产安全，进货查验、出厂检验、型式试验、维保记录与事故报告缺一不可；"
            "涉及许可目录内产品的，无证生产销售是单独一条违法。",
    "biz": "登记事项、年报公示、经营场所与实际经营是否一致，是监管的基础信息面；"
           "公示信息隐瞒真实情况会被列入经营异常名录并对外展示。",
    "admin": "处罚能否成立取决于程序：管辖、调查取证、告知听证、说理与送达，"
             "任一步骤缺失都可能导致处罚被撤销或变更；裁量基准决定了同案如何同罚。",
}
POS_TPL = {
    "food": "把本条要求拆成门店/仓配日检清单上的勾选项，逐项留痕（验收单、温控记录、标签照片、处置记录），"
            "并指定一人一岗负责抽查签字。",
    "drug": "把许可、台账、追溯与报告四类材料做成「一柜一册」按批次归档；关键岗位持证与在岗情况每月核对一次。",
    "ad": "建立「新品上线前广告用语双人复核」卡点：宣传语、数据、对比依据三者缺一不上线；"
          "对外投放素材全部留存来源与授权文件。",
    "consumer": "把对外承诺（退换货、临期处置、会员权益、自动续费）整理成一页「承诺清单」，"
                "由业务与法务共同确认后再上线，并保证门店端与线上端口径完全一致；"
                "每条投诉按「受理—处理—回复—归档」走完并留存记录。",
    "price": "上线价格前做一次「标示价—结算价—优惠规则」三联核对，把核对结果与生效时间一起留档；"
             "促销规则变动同样走一遍。",
    "comp": "把与渠道商、供应商的往来（价格、返利、排他、数据）集中到一个台账，"
            "涉及排他或限制条件的条款先过法务；对同行的评价性表述一律不作事实陈述。",
    "ip": "建立选品准入清单：进店前核验商标注册证/授权链、外观与专利检索结论，"
          "并把权利人信息留档到可追溯的一级来源。",
    "pi": "为每个收集场景建一页「四列表」：收集目的—使用场景—必要性论证—最小范围替代方案；"
          "未过这四列的权限和字段不进版本。",
    "data": "先做数据分类分级台账，再按级别定对外提供与出境的评估与合同流程；"
            "与第三方签署的数据条款统一模板并留痕。",
    "net": "把漏洞发现—修复—复测做成闭环工单并保留日志与测评报告；应急预案每年实操演练一次并留记录。",
    "algo": "上线前完成备案（或登记）、页面公示与「关闭/拒绝」入口三项核对，并把算法基本信息纳入变更评审。",
    "ai": "对生成内容做「可识别标识 + 用户提示 + 投诉入口」三件套检查，训练数据来源与授权文件按数据集归档。",
    "platform": "平台规则修改前公示并留痕，入驻商家资质按类目做定期复核，交易与纠纷记录按法定期限保存。",
    "qual": "把进货查验、检验报告、维保与事故记录做成「一机一档」，涉及目录内产品的先确认证书与标示齐备。",
    "biz": "登记信息、许可信息与年报内容每年自查一次，变更事项在法定期限内办理并留痕。",
    "admin": "制作「立案—告知—听证—决定—送达」节点表，每案按节点存档，重点保留告知与陈述申辩的处理记录。",
}


def norm_name(s):
    return re.sub(r"[《》〈〉「」『』\s]", "", s or "").replace("中华人民共和国", "")


def domain_of(law):
    for did, dname, pat in DOMAIN_RULES:
        if re.search(pat, law):
            return did
    return DEFAULT_DOMAIN[0]


def load_corpus():
    """法规名（归一后）→ {name, id, text, level, issuer, pub, impl, status, url}"""
    corpus = {}
    try:
        idx = json.load(open(TEXT_INDEX, encoding="utf-8"))["items"]
    except Exception:
        idx = []
    meta = {}
    parts = {}
    for x in idx:
        meta[x["id"]] = x
        parts.setdefault(x.get("part"), None)
    for p in sorted(glob.glob(os.path.join(TEXT_PARTS, "p-*.json"))):
        try:
            parts.update(json.load(open(p, encoding="utf-8")))
        except Exception:
            continue
    for x in idx:
        t = parts.get(x["id"])
        if not t:
            continue
        corpus.setdefault(norm_name(x["name"]), {
            "name": x["name"], "id": x["id"], "text": t,
            "level": x.get("level") or x.get("code") or "",
            "issuer": x.get("issuer") or "", "pub": x.get("pub") or "",
            "impl": x.get("impl") or "", "status": x.get("status") or "",
            "url": x.get("url") or ""})
    # 补充 flk 全量语料里不在站内原文库的（只用来取条文，不挂站内锚点）
    if os.path.exists(FLK_JSONL):
        for line in open(FLK_JSONL, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = norm_name(r.get("t"))
            if k and k not in corpus and r.get("x"):
                corpus[k] = {"name": r.get("t"), "id": "", "text": r["x"],
                             "level": r.get("k") or "", "issuer": r.get("o") or "",
                             "pub": r.get("p") or "", "impl": r.get("i") or "",
                             "status": r.get("s") or "", "url": ""}
    return corpus


# 合规主干法：无论在案例库里被引多少次，都必须进高频法条（见 main 里的加权说明）。
# 用**短名**匹配（`中华人民共和国XX法` 归一化后会掉「中华人民共和国」，但保留「法」）。
CORE_LAWS = (
    "食品安全法", "电子商务法", "广告法", "价格法", "消费者权益保护法",
    "反不正当竞争法", "反垄断法", "产品质量法", "个人信息保护法", "数据安全法",
    "网络安全法", "行政处罚法", "市场主体登记管理条例", "网络交易监督管理办法",
    "互联网广告管理办法", "明码标价和禁止价格欺诈规定", "药品管理法",
    "化妆品监督管理条例", "医疗器械监督管理条例", "特种设备安全法", "计量法",
    "标准化法", "商标法", "专利法", "食品安全法实施条例", "价格违法行为行政处罚规定",
)

# ⚠️ 收进来就是「一眼假」的法规，逐类挡掉（实测都出现过）：
#  ① 军队系统法规（读者是经营者，不是部队）；
#  ② 修正案/修改决定 —— 语料是「对第X条作如下修改」的差异文本，条文被切得七零八落
#     （实测引文成了「第一款、第二十五条、第二十六条…」）；
#  ③ 刑法总则 —— 按关键词能捞到「犯罪构成要件/附加刑种类/没收财产」，对合规毫无用处；
#  ④ 规范**行政机关**自己的程序规定（移送、复议、执法程序），义务主体不是经营者；
#  ⑤ 地方实施性法规（上海市实施《…》办法）—— 不普适，不该出现在全国口径的清单里；
#  ⑥ 专利代理/商标代理等**中介资质**条例 —— 管的是代理机构，不是经营者的经营行为。
EXCLUDE_LAWS = re.compile(
    r"中国人民解放军|解放军|军队|"
    r"关于修改《|关于废止《|修正案$|"
    r"^中华人民共和国刑法$|"
    r"行政执法机关移送|行政复议法|行政许可法|行政强制法|行政诉讼法|"
    r"^[北京上海天津重庆广州深圳浙江省江苏省广东省山东省]|"
    r"专利代理条例|商标代理|"
    r"香港特别行政区|澳门特别行政区"
)


# ⚠️ 条号必须**在行首**才算条文标题。正文里到处是引用式条号
# （「违反本法第九条规定的，处…」），用无锚定的 `第X条` 会把引用处的后半句
# 当成那一条的正文，而且因为「取更长的那个」，真正的条文反而被覆盖掉
# （实测反不正当竞争法第九条就这样变成了罚则条的半句话）。
ART_RE = re.compile(r"(?m)^[ \t\u3000]*第([一二三四五六七八九十百千零〇\d]+)条")

# ⚠️ 站内原文库有部分条目源自**官方 PDF 拼接**，正文里夹着页眉页脚。
# 这些字样会被当成「条文原文」逐字引用出去（实测电子商务法第五条引文尾部
# 挂着「第67页,共1715页」），必须在这里清掉，不能指望下游。
PDF_CHROME = re.compile(
    r"第\s*\d+\s*页\s*[,，]?\s*共\s*\d+\s*页"
    r"|\bPage\s*\d+\s*(?:of|/)\s*\d+\b"
    r"|^\s*共\s*\d+\s*页\s*$"


)


def split_articles(text):
    """把整部法切成 {「第X条」: 正文}。"""
    t = re.sub(r"\r\n?", "\n", text or "")
    # 目录区会先列一遍条号，找到「第一章/第二章…」正文起点后就好了 —— 直接按「第X条」切，
    # 目录里的条号后面不跟正文，切出来的段会极短，下面按长度过滤即可。
    marks = list(ART_RE.finditer(t))
    out, seen = {}, set()
    for i, m in enumerate(marks):
        art = "第" + m.group(1) + "条"
        end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
        body = t[m.end():end].strip()
        # 目录行：「第一条 ……… 1」这种只有条名，长度短且带省略号
        if len(body) < 12 or re.match(r"^[\s…\.．\-—]*\d*$", body):
            continue
        body = re.split(r"\n第[一二三四五六七八九十百千]+[章节]\s", body)[0].strip()
        # 清掉 PDF 页眉页脚残留，再压缩空白（引文逐字展示，多一个空格都看得出来）
        body = PDF_CHROME.sub(" ", body)
        body = re.sub(r"[ \t\u3000]+", "", body)
        body = re.sub(r"\n{2,}", "\n", body).strip()
        if art in seen:
            # 同一部法里条号唯一；重复出现只可能是目录或引用，保留更长的那个
            if len(body) > len(out.get(art, "")):
                out[art] = body
            continue
        seen.add(art)
        out[art] = body
    return out


def art_no(art):
    cn = "零一二三四五六七八九十"
    m = re.match(r"第([一二三四五六七八九十百千零〇\d]+)条", art or "")
    if not m:
        return 0
    s = m.group(1)
    if s.isdigit():
        return int(s)
    # 中文数字 → int（够用到 千）
    num = 0
    unit = {"十": 10, "百": 100, "千": 1000}
    cur = 0
    for ch in s:
        if ch in cn and ch not in unit:
            cur = cn.index(ch)
        elif ch in unit:
            num += (cur or 1) * unit[ch]
            cur = 0
    return num + cur


def fine_phrase(t):
    """从条文里抽出「罚款幅度」短语（页面 headline 用它做一句话要旨）。"""
    m = re.search(r"(?:并处|处|可以处|处以|给予)[^。；]{0,12}?"
                  r"((?:[\d,，\.]+|[一二三四五六七八九十百千万亿]+)"
                  r"(?:万元|元|亿)?(?:以上|以下)?[^。；]{0,30}?罚款)", t)
    if m:
        s = m.group(1).strip()
        return ("处" + s) if not s.startswith("处") else s
    m = re.search(r"((?:[\d,，\.]+|[一二三四五六七八九十百千万亿]+)"
                  r"(?:万元|元)(?:以上)?(?:[\d,，\.]+|[一二三四五六七八九十百千万亿]+)"
                  r"(?:万元|元)?以下(?:的)?罚款)", t)
    return ("处" + m.group(1)) if m else ""


def brief(s, n):
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"^[，。；、：]+", "", s)
    if len(s) <= n:
        return s
    cut = s[:n]
    m = re.search(r"[，；、。：]$", cut)
    return (cut[:-1] if m else cut) + "…"


def headline_of(law, art, body):
    """卡片标题。

    ⚠️ 不能无脑取第一句：很多条第一句是权利宣示或背景（「国家保护公民…使用网络的
    权利」），真正的义务在后面几款。义务条改成**取第一句含「应当/不得/禁止」的句子**，
    取不到才退回第一句。
    """
    fp = fine_phrase(body)
    if fp:
        return brief(f"违反本条的处罚：{fp}", 46)
    sents = [s for s in re.split(r"[。；]", body) if s.strip()]
    for s in sents:
        if DUTY_KW.search(s) and not GOV_RE.match(s.strip()) \
                and not CONSUMER_RE.match(s.strip()):
            return brief(f"义务要求：{s}", 46)
    first = sents[0] if sents else body
    return brief(first, 46)


def subject_of(body):
    """抽本条规制的对象（用于场景模板的 {obj}）。"""
    m = re.search(r"^([^\u4e00-\u9fa5]{0,2}[\u4e00-\u9fa5]{2,14}?"
                  r"(?:者|人|单位|机构|企业|平台|经营者|生产者|销售者|组织))", body)
    if m:
        return m.group(1)
    m = re.search(r"(食品生产经营者|生产经营者|网络交易经营者|电子商务经营者|"
                  r"平台内经营者|电子商务平台经营者|个人(?:信息)处理者|数据处理者|"
                  r"特种设备使用单位|特种设备生产单位|医疗器械经营企业|药品上市许可持有人|"
                  r"广告主|广告经营者|广告发布者|集中交易市场开办者|餐饮服务提供者|"
                  r"市场监督管理部门|经营者|生产者|销售者|用人单位)", body)
    return m.group(1) if m else "本条涉及的行为"


def pick_articles(arts):
    """从一部法的 {条号:正文} 里挑「罚则条 + 义务条」。

    ⚠️ 义务条**不能只看「应当」**：总则里的适用范围条（「在中华人民共和国境内从事
    下列活动，应当遵守本法」）和定义条（「本法所称…是指…」）都含「应当/所称」，
    被选进来会得到一堆零信息量的卡。这类先按 SCOPE_RE / DEF_RE 排除。
    """
    items = [(art_no(k), k, v) for k, v in arts.items() if art_no(k) > 0]
    items.sort()
    norm = [(n, a, re.sub(r"\s+", "", b)) for n, a, b in items]
    pen, duty = [], []
    for n, art, body in norm:
        if not (18 <= len(body) <= 1400):
            continue
        if not PEN_KW.search(body):
            continue
        # 罚则条：必须给出「罚款/没收/责令…」的具体后果
        if len(PEN_KW.findall(body)) >= 1 and len(pen) < 3:
            pen.append((n, art, body))
    for n, art, body in norm:
        if not (30 <= len(body) <= 700):
            continue
        if not DUTY_KW.search(body):
            continue
        if SCOPE_RE.search(body[:60]) or DEF_RE.search(body[:60]):
            continue
        if any(a == art for _n, a, _b in pen):
            continue
        # ⚠️ 只写「政府/部门应当如何」的条款对企业没有可执行性，收进来就是噪声
        if GOV_RE.match(body):
            continue
        # ⚠️ 主体是**消费者本人**或「全社会」的条款（权利宣示 / 共同责任），
        # 不是经营者义务：`消费者享有…的权利`、`保护消费者的合法权益是全社会的共同责任`。
        # 判据卡在句首，避免误伤「消费者因不符合食品安全标准的食品受到损害的，可以…」
        # 这类真正有维权价值的条款。
        if CONSUMER_RE.match(body):
            continue
        # 只有「应当遵守本法」式空转的不收
        if re.search(r"^(应当|必须)(遵守|依照)本法", body):
            continue
        duty.append((n, art, body))
        if len(duty) >= 5:
            break
    return pen, duty


def find_penalty_for(law_arts, art_no_val):
    """在同一部法的罚则里找提到「违反本法第X条」的那一条。"""
    key = f"第{art_no_val}条"
    for art, body in law_arts.items():
        b = re.sub(r"\s+", "", body)
        if key in b and PEN_KW.search(b) and len(b) >= 20:
            return art, b
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--show", default="")
    a = ap.parse_args()

    hot = json.load(open(HOT, encoding="utf-8"))
    manual = hot["items"]
    have = {(norm_name(x["law"]), x["art"]) for x in manual}

    corpus = load_corpus()
    print(f"语料库：{len(corpus)} 部法规有正文")

    cases = json.load(open(CASES, encoding="utf-8"))["cases"]
    law_cases = {}
    for c in cases:
        for l in (c.get("laws") or []):
            law_cases.setdefault(norm_name(l), []).append(c)
    print(f"案例库：{len(cases)} 条，覆盖 {len(law_cases)} 部法规")

    # 候选法：语料里有正文 + 名字命中合规领域规则的
    cands = []
    for key, rec in corpus.items():
        if len(rec["text"]) < 800:
            continue
        if not re.search(r"法$|条例$|办法$|规定$|规则$|准则$|决定$", rec["name"]):
            continue
        if EXCLUDE_LAWS.search(rec["name"]):
            continue
        did = domain_of(rec["name"] if not re.search(
            r"^(中华人民共和国)?[\u4e00-\u9fa5]{2,4}$", rec["name"]) else rec["name"])
        scored = len(re.findall(
            r"食品|广告|价格|竞争|消费者|电子商务|网络交易|个人信息|数据|网络安全|"
            r"算法|人工智能|产品质量|特种设备|计量|认证|商标|专利|药品|化妆品|"
            r"医疗器械|市场主体|信用|行政处罚|反垄断|公平竞争|召回|平台|直播|"
            r"外卖|餐饮|预付|合同|计量|标准", rec["name"]))
        nc = len(law_cases.get(key, []))
        if scored == 0 and nc == 0:
            continue
        # ⚠️ 只按「被引案例数」排序会有个坑：**电商/平台/价格这类主干法在案例库里的
        # 被引数未必高**（案例摘要提到「电子商务法」时往往写简称或压根不点名），
        # 排到 cutoff 之后就被整部丢掉 —— 实测电子商务法曾因此一条都不进。
        # 给「合规主干法」加固定加权，保证它们一定入选。
        core = 20 if any(p in key for p in CORE_LAWS) else 0
        cands.append((-(nc * 3 + scored + core), key, rec))
    cands.sort()
    print(f"候选法规 {len(cands)} 部（按被引案例数 ×3 + 名称关键词 + 主干法加权排序）")

    gen, stat = [], []
    for _score, key, rec in cands:
        if len(hot["items"]) + len(gen) >= a.target:
            break
        arts = split_articles(rec["text"])
        if len(arts) < 3:
            continue
        pen, duty = pick_articles(arts)
        if not pen and not duty:
            continue
        did = domain_of(rec["name"])
        dname = dict((d[0], d[1]) for d in DOMAIN_RULES)[did]
        law_full = rec["name"]
        law_short = re.sub(r"^中华人民共和国", "", law_full)
        picked = [(x, "pen") for x in pen] + [(x, "duty") for x in duty]
        picked.sort(key=lambda p: p[0][0])
        n_made = 0
        for (nval, art, body), role in picked:
            if (norm_name(law_full), art) in have:
                continue
            # 事实/责任：优先用条文自身；义务条再去同法罚则里找对应条款
            pen_art, pen_body = ("", "")
            if role == "duty":
                pen_art, pen_body = find_penalty_for(arts, nval)
            # 处罚标准：义务条去同法罚则里找对应条款；罚则条本身就是处罚条文，
            # 再填一遍「处罚标准」只会和上面的条文原文重复，故留空。
            penalty = brief(pen_body, 300) if (role == "duty" and pen_body) else ""
            liability = ""
            if re.search(r"构成犯罪的|依法追究刑事责任", body + pen_body):
                liability = brief(re.search(
                    r"[^。；]{0,60}(?:构成犯罪的|依法追究刑事责任)[^。；]{0,60}",
                    body + pen_body).group(0), 220)
            # ⚠️ id 必须**带上法规**，否则「XX法第十四条」与「XX法实施条例第十四条」
            # 会撞出同一个 `food-14-auto` —— 页面里重复 id、锚点互相跳错。
            # 法规名是中文，用 md5 前 5 位做短后缀（确定性、无冲突、锚点长度可控）。
            sid = (f"{did}-{re.sub(r'[^0-9]', '', str(nval)) or nval}"
                   f"-{hashlib.md5(key.encode('utf-8')).hexdigest()[:5]}-auto")
            cases_here = [c for c in law_cases.get(key, [])
                          if c.get("url")][:2]
            cs = []
            for c in cases_here:
                cs.append({
                    "kind": "行政处罚" if c.get("kind") == "行政处罚" else
                            (c.get("kind") or "行政监管"),
                    "title": c.get("title") or "",
                    "org": c.get("agency") or c.get("org") or "",
                    "date": c.get("date") or "",
                    "no": c.get("caseno") or c.get("no") or "",
                    "url": c.get("url"),
                    "result": brief(c.get("fact") or "", 150),
                    "summary": brief(c.get("fact") or "", 260),
                })
            gen.append({
                "id": sid,
                "domain": did,
                "law": law_full,
                "law_short": law_short,
                "text_id": rec.get("id") or "",
                "art": art,
                "headline": headline_of(law_full, art, body),
                "quote": body if len(body) <= 760 else body[:760] + "……",
                "scene": SCENE_TPL.get(did, ""),
                "penalty": penalty,
                "liability": liability,
                "positive": POS_TPL.get(did, ""),
                "cases": cs,
                "_auto": {"domain": dname, "role": role, "penalty_art": pen_art,
                          "law_level": rec.get("level"), "law_url": rec.get("url")},
            })
            n_made += 1
        if n_made:
            stat.append((rec["name"], len(arts), n_made))

    print(f"\n生成 {len(gen)} 条，合计 {len(manual) + len(gen)} 条（手工 {len(manual)}）")
    if a.show:
        shown = 0
        for x in gen:
            if a.show not in x["law"]:
                continue
            print("-" * 70)
            print(f"{x['law']} · {x['art']}   [{x['domain']}]")
            print("headline:", x["headline"])
            print("quote   :", x["quote"][:140], "…")
            print("penalty :", (x["penalty"][:140] or "（无）"))
            print("cases   :", len(x["cases"]),
                  (x["cases"][0]["title"][:50] if x["cases"] else ""))
            shown += 1
            if shown >= 5:
                break
    if a.dry:
        return
    out = {"_meta": hot.get("_meta", {}), "domains": hot["domains"],
           "_note": "本文件由 tools/extend_hot_articles.py 从站内原文库自动生成，"
                    "请勿手改；条文原文逐字取自官方全文，场景/示例为领域模板。",
           "items": gen}
    json.dump(out, open(AUTO, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"✓ 写出 {AUTO}（{os.path.getsize(AUTO)/1024/1024:.1f} MB）")
    print("\n前 20 部法：")
    for name, na, nm in stat[:20]:
        print(f"   {nm:>2} 条  {name}（共 {na} 条）")


if __name__ == "__main__":
    main()
