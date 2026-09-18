#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""移动应用违规治理专项 · 违规通报历史库（多源版）

谁在通报 —— 本库覆盖的发布主体（全部为发布机关官网原文页）
======================================================
⚠️ 监管层级（2026-09-18 用户明确，本库与页面一律按此口径呈现）
   顶层监管部门只有三个：**网信办（国家互联网信息办公室）/ 公安部 / 工业和信息化部**。
   其余机构都是这三个部门的**技术支撑 / 检测支撑单位**，不是与三部并列的「国家监管主体」：
     · 国家互联网应急中心（CNCERT/CC）        —— 中央网信办直属事业单位
     · 国家计算机病毒应急处理中心（病毒中心）  —— 受公安部委托开展 App/SDK 检测通报
     · 公安部第三研究所检测中心               —— 公安部三所下属，2026 年起对外通报 App
   把它们与三个部门平铺成一层，会让「谁在管」这张表失去治理含义。

【顶层部门 ①：国家网信办】
②（编号沿用历史顺序）中央网信办《关于 N 款 App（和 M 款 SDK）个人信息收集使用问题的通报》
   经网信办站内检索枚举（search.cac.gov.cn，必须带 Referer）。
   名单载体：**内嵌 PNG 图片** → macOS Vision OCR + 按 y 坐标聚类还原表行。

【顶层部门 ②：工业和信息化部】
① 工业和信息化部信息通信管理局《关于侵害用户权益行为的 APP（SDK）通报》
   栏目 https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html
   2019-12 起连续编号，总第 1 批→当前，是该领域最完整的国家序列。
   名单载体：正文无表，**附件为 PDF**，经 pdfjs viewer iframe 内嵌
   （`/cms_files/filemanager/.../attach/YYYYM/<hash>.pdf`）→ pdfplumber 提表格。

【顶层部门 ③：公安部（网安局）及其技术支撑单位】
③ 公安部 · 国家计算机病毒应急处理中心（技术支撑）
   受公安部委托以计算机病毒防治产品实验室名义开展 App/SDK 检验检测与通报处置；
   列表无稳定 PC 栏目，本站未接入，仅登记。
④ 公安部第三研究所检测中心（技术支撑）
   《中心检测发现 N 款违法违规收集使用个人信息的移动应用》
   栏目 http://www.mstl.org.cn/html/news/index.html（静态分页 index_N，共 4 页）
   正文内嵌《应用名》(版本x, 来源)，并按「1、问题类别。涉及 N 款如下：」分节
   → 分节解析可同时拿到问题类型；发布时间在「发布时间：YYYY-MM-DD」。
   ⚠️ 该站只挂出 2026-06 / 2026-07 / 2026-09 三期（更早的 54 款、37 款两期
   已从站点列表中撤下），故本序列起始于 2026-06，不代表该中心只发过这三期。

【国家层面 · 协会 / 机构】
⑤ 中国互联网协会（ISC）App 个人信息收集使用专家评议；
⑥ 中国网络空间安全协会（CSAC）App 整改通告；
⑦ 中国消费者协会（CCA）App 个人信息测评；
⑧ 全国信息安全标准化技术委员会（TC260）、中国网络安全审查认证和市场监管大数据中心（ISCCC）
   负责评估要点与技术标准，其发布的规则文件进「法规/标准」侧。

【地方层面 · 监管部门】
⑨ 28 个省级通信管理局（`{abbr}ca.miit.gov.cn`；河北、海南无独立子站）
   **每省自成一套属地通报序列**，是国家序列之外独立且互不重叠的一路。
   名单载体：**页面内 HTML 表格**（免 OCR，质量最高），
   栏目列表经 jpaas build/unit 接口翻页（参数见 tools/prov_ca_discover.py）。

统计口径（重要）
--------------
本库里「数量」有三个层次，页面必须分开陈述、不可混用：
  · 通报文书数 documents        —— 一份通报 = 一条文书（按 url 去重）
  · 通报条目数 entries          —— 文书 × 应用，同一应用被多份文书点名会被计多次
  · 去重涉及应用数 unique_apps  —— 按「应用名 + 运营者」归并后的唯一应用数
⚠️ 「年度汇总 / 整改复核 / 下架处置」类文书会重复列出已在批次通报中出现过的应用，
   若把文书数量或条目数当作「被通报的应用数」就会重复计数。因此：
   - `notice_kind` 区分：批次通报 / 整改复核 / 下架处置 / 年度汇总 / 专项行动 / 测评评议；
   - `unique_apps` 才是对外可引用的「涉及应用数」；
   - 页面同时给出「重复上榜」口径（同一应用出现在多份文书中的比例）。

用法：
  python3 tools/harvest_app_violations.py                 # 增量（已有文书跳过）
  python3 tools/harvest_app_violations.py --full          # 全量重抓
  python3 tools/harvest_app_violations.py --no-ocr        # 跳过网信办图片 OCR
  python3 tools/harvest_app_violations.py --only prov     # 只跑省局（miit|cac|prov）
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from html import unescape
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from appviol_entity import resolve   # noqa: E402  实体消解 + 事件模型（去重口径的唯一实现）

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(HERE, "sources", "appviol")
IMGDIR = os.path.join(HERE, "sources", ".cache", "appviol")
PDFDIR = os.path.join(HERE, "sources", ".cache", "appviol_pdf")
PROVCOL = os.path.join(OUTDIR, "prov_columns.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MIIT_API = "https://www.miit.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"


# ------------------------------------------------------------------ 基础
def curl(url, referer=None, out=None, timeout=60, tries=2):
    for i in range(tries):
        cmd = ["curl", "-sSL", "-m", str(timeout), "-H", "User-Agent: " + UA]
        if referer:
            cmd += ["-H", "Referer: " + referer]
        if out:
            cmd += ["-o", out, "-w", "%{http_code}"]
        cmd.append(url)
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore")
        if out:
            if (p.stdout or "").strip() == "200" and os.path.exists(out) \
                    and os.path.getsize(out) > 1200:
                return True
            time.sleep(1.0 * (i + 1))
            continue
        if p.stdout and len(p.stdout) > 200:
            return p.stdout
        time.sleep(0.8 * (i + 1))
    return None


def textify(html):
    s = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", "\n", s)
    s = unescape(s)
    return [re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip()]


def docid(url):
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------- 明细字段归一
# 明细表头 → 标准字段名（各省/各源表头不统一）
FIELD_MAP = [
    ("应用名称", "app"), ("App名称", "app"), ("APP名称", "app"), ("名称", "app"),
    ("应用开发者", "dev"), ("开发者", "dev"), ("运营者", "dev"), ("主办者", "dev"),
    ("企业名称", "dev"), ("备案主体", "dev"), ("开发者名称", "dev"),
    ("应用版本", "ver"), ("版本信息", "ver"), ("版本号", "ver"), ("版本", "ver"),
    ("应用来源", "store"), ("分发平台", "store"), ("来源", "store"),
    ("所涉问题", "probs"), ("问题类型", "probs"), ("问题项", "probs"),
    ("主要问题", "probs"), ("问题", "probs"), ("涉及问题", "probs"),
    ("APP备案号", "reg"), ("备案号", "reg"), ("备案编号", "reg"),
    ("属地", "region"), ("归属地", "region"), ("省份", "region"),
    ("类型", "type"), ("编号", "no"), ("序号", "no"),
]

# 问题表述 → 标准类目。依据《App 违法违规收集使用个人信息行为认定方法》
# 的六类认定行为 + 近年地方局高频表述（自启动、SDK、未成年人等）。
PROB_RULES = [
    ("未公开收集使用规则", r"未公开|未公示|未明示.{0,6}(?:规则|政策)|隐私政策.{0,4}难以访问|"
                       r"未(?:以显著方式|通过弹窗).{0,12}提示|默认选择同意"),
    ("未经同意收集使用", r"未经(?:用户)?同意|未取得.{0,8}同意|未(?:经)?征得"),
    ("超范围收集/违规收集", r"超范围|违规收集|无关场景|超出必要|超权限收集|"
                       r"收集与(?:其)?提供服务无关"),
    ("强制频繁过度索取权限", r"强制.{0,4}(?:索取|获取|授权)|频繁.{0,6}索(?:取|要)|"
                       r"过度索(?:取|要)|非必要.{0,4}权限|捆绑"),
    ("定向推送/个性化推荐", r"定向推送|个性化(?:推荐|推送)|广告.{0,4}推送"),
    ("账号注销难", r"注销(?:功能|渠道|难)|未提供有效.{0,6}注销|账号注销"),
    ("欺骗误导强迫用户", r"欺骗|误导|强迫|诱导"),
    ("频繁自启动/关联启动", r"自启动|关联启动|相互唤醒"),
    ("SDK 违规收集", r"SDK"),
    ("未成年人个人信息", r"未成年人|不满十四周岁|儿童个人信息"),
    ("投诉举报/权利请求渠道缺失", r"投诉举报|权利请求|更正.{0,4}删除|未响应用户"),
    ("安全技术措施缺失", r"未(?:对个人信息)?(?:采取)?加密|去标识化|明文(?:存储|传输)"),
    ("未完整准确告知", r"未完整|未准确|不一致|未逐.{0,2}列出"),
    ("第三方共享/转让未告知", r"共享|转让|第三方.{0,6}(?:告知|同意)|委托处理"),
    ("信息窗口/弹窗跳转", r"信息窗口|弹窗|跳转|摇一摇|开屏广告|无法关闭"),
    ("违规使用个人信息", r"违规使用|滥用|超出.{0,4}约定范围"),
]


def norm_prob(s):
    s = re.sub(r"\s+", "", s or "")
    for label, pat in PROB_RULES:
        if re.search(pat, s):
            return label
    return None


def probs_of(cell):
    """一个单元格里常含多个问题项（『违规收集个人信息;强制索取权限』）。

    ⚠️ 拆分会产生残渣：如「APP强制、频繁、过度索取权限」会被 、 切成
    「APP强制」「频繁」「过度索取权限」。若同一单元格里已有命中标准类目的项，
    就不再保留那些过短的自由文本碎片，否则统计里会出现 'APP强制' / 'APP 强制' 这类噪声。
    """
    if not cell:
        return []
    parts = re.split(r"[;；\n、,，]|(?<=[）)])(?=\d|[（(])|(?<=。）)", cell)
    labeled, raw = [], []
    for p in parts:
        p = re.sub(r"^[（(]?[一二三四五六七八九十\d]{1,2}[）)]?[、．.]?\s*", "", p.strip())
        p = re.sub(r"\s+", "", p)
        if len(p) < 3:
            continue
        lab = norm_prob(p)
        if lab:
            if lab not in labeled:
                labeled.append(lab)
        elif len(p) >= 6 and p not in raw:
            raw.append(p)
    out = labeled + ([] if labeled else [r[:26] for r in raw])
    return out


# ------------------------------------------------------------ 文书分类
def notice_kind(title, body):
    s = title + " " + body[:600]
    # 个人署名文章（「韩煜：移动App…」）不是监管通报 —— 挂在网信办站上，容易混进通报统计
    if re.match(r"^[\u4e00-\u9fff]{2,4}[：:]", title) and not re.match(
            r"^(关于|通知|公告|解读|答记者问|一图)", title):
        return "行业观点"
    if re.search(r"下架|禁搜|关停|予以下架", title):
        return "下架处置"
    if re.search(r"整改情况|复测|复核|回头看|整改完成|完成整改", title):
        return "整改复核"
    if re.search(r"年度|全年|年度汇总|情况汇总", title) and re.search(r"通报|名单|汇总", title):
        return "年度汇总"
    if re.search(r"专项行动", title + body[:300]) and re.search(r"公告$", title.strip()):
        return "专项行动"
    if re.search(r"测评|评估|评议|检测报告", title):
        return "测评评议"
    return "批次通报"


# ------------------------------------------------------------ 机构命名口径
# ⚠️ 网信办系统「一个机构两块牌子」：中央网络安全和信息化委员会办公室（中央网信办）
#    与国家互联网信息办公室（国家网信办）是**同一机构**的两块牌子；对外发布通报表时
#    常以「中央网信办秘书局」「国家互联网信息办公室秘书局」署名。秘书局只是它的
#    发文机构，不是另一个发布主体（用户 2026-09-15 明确：「网信办秘书局就是国家网信办」）。
#    所以本库全国层面**只立「国家网信办」一个主体**，不把中央 / 国家 / 秘书局写成三家，
#    否则机构 × 年度矩阵会把同一个机关的通报量摊薄成三份，看着像三个小机构。
CAC_NATIONAL = "国家网信办"

# 省级网信办的全称（用于把国家站转载的地方通报归回属地主体）
# ⚠️ 不能只取有独立通管局站点的省份：海南、河北等没有通信管理局子站，
#    但其网信办通报会挂到 cac.gov.cn 上（实测浙江 2 份、海南 2 份）。
CAC_PROV_SHORT = {
    "北京": "北京市", "天津": "天津市", "上海": "上海市", "重庆": "重庆市",
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
    "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
    "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
    "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
    "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
    "甘肃": "甘肃省", "青海": "青海省", "台湾": "台湾省",
    "内蒙古": "内蒙古自治区", "广西": "广西壮族自治区", "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
}

PROV_NAMES = {
    "bj": "北京市", "tj": "天津市", "sh": "上海市", "cq": "重庆市", "sx": "山西省",
    "nm": "内蒙古自治区", "ln": "辽宁省", "jl": "吉林省", "hlj": "黑龙江省",
    "js": "江苏省", "zj": "浙江省", "ah": "安徽省", "fj": "福建省", "jx": "江西省",
    "sd": "山东省", "hn": "河南省", "hb": "湖北省", "gd": "广东省",
    "gx": "广西壮族自治区", "sc": "四川省", "gz": "贵州省", "yn": "云南省",
    "xz": "西藏自治区", "shx": "陕西省", "gs": "甘肃省", "qh": "青海省",
    "nx": "宁夏回族自治区", "xj": "新疆维吾尔自治区",
}


def org_scope(title, body, url, fallback=""):
    """判定发布主体（机关名）与属地范围。

    ⚠️ 绝不能靠「正文里出现了哪个机关名」判断——所有通报正文都写
    「根据中央网信办、工业和信息化部、公安部联合发布的…」，按关键词扫会把
    工信部的通报统统标成公安部。判定优先级：域名 > 标题首部机关名 > 正文**落款**。
    """
    low = url.lower()
    # 0) 公安部技术支撑单位的独立站点（域名即主体，必须先判）
    #    ⚠️ 正文首句会写「根据公安部、中央网信办、工业和信息化部联合发布的…」，
    #       若走关键词扫描会把这份通报记到三部头上（见本函数开头警告）。
    if "mstl.org.cn" in low:
        return "公安部第三研究所检测中心", "国家"
    # 1) 标题首部机关名 / 联合发布（比域名更准：川渝联合通报同时挂在两个省局站上，
    #    只看域名会被拆成两个单一省份）
    m = re.search(r"^([\u4e00-\u9fff]{2,14}?(?:省|市|自治区)通信管理局)", title)
    if m:
        return m.group(1), "地方"
    m = re.search(r"^([\u4e00-\u9fff]{2,14}?(?:省|市|自治区)"
                  r"(?:互联网信息办公室|网信办))", title)
    if m:
        return m.group(1), "地方"
    if re.search(r"川渝", title):
        return "四川省通信管理局、重庆市通信管理局", "地方"
    # 2) 省局域名定属地（省局通报标题里有时不带局名）
    for ab, nm in PROV_NAMES.items():
        if ab + "ca.miit.gov.cn" in low:
            return nm + "通信管理局", "地方"
    # 3) 部委官网域名
    if "miit.gov.cn" in low:
        return "工业和信息化部 · 信息通信管理局", "国家"
    # 4) 其余（网信办站）看正文落款——落款在末尾
    #    秘书局三个变体一律归「国家网信办」（同一机构两块牌子，见文件头机构命名口径）
    tail = body[-900:]
    for pat, org in ((r"公安部网安局|公安部网络安全保卫局", "公安部 · 网安局"),
                     (r"中央网信办秘书局|国家互联网信息办公室秘书局|网信办秘书局"
                      r"|国家互联网信息办公室|中央网信办|国家网信办", CAC_NATIONAL)):
        if re.search(pat, tail):
            return org, "国家"
    for kw, org in (("计算机病毒", "国家计算机病毒应急处理中心"),
                    ("工业和信息化部", "工业和信息化部 · 信息通信管理局"),
                    ("公安部", "公安部 · 网安局"),
                    ("中央网信办", CAC_NATIONAL),
                    ("国家网信办", CAC_NATIONAL)):
        if kw in title:
            return org, "国家"
    # 5) 省级网信办转载的属地通报（标题以省名开头，如「浙江关于微记账等38款App…」
    #    「海南网信办通报13款APP…」）。
    #    ⚠️ 必须排在 cac.gov.cn 兜底**之前**，否则国家站上的地方通报会被吞成国家主体
    #    （实测浙江 2 份、海南 2 份被误记到国家层面，属地统计因此缺失）。
    for k in (4, 3, 2):
        if title[:k] in CAC_PROV_SHORT:
            return CAC_PROV_SHORT[title[:k]] + "互联网信息办公室", "地方"
    # 6) 兜底：cac.gov.cn 上的国家层面通报 = 国家网信办（含其秘书局发文）
    if "cac.gov.cn" in low:
        return CAC_NATIONAL, "国家"
    return (fallback or "未知主体"), "其他"


# --------------------------------------------------------- 明细：HTML 表
def html_tables(html):
    """页面内 HTML 表格 → [(header, rows)]。"""
    out = []
    for m in re.finditer(r"<table.*?</table>", html, re.S | re.I):
        tb = m.group(0)
        raw = re.findall(r"<tr.*?</tr>", tb, re.S | re.I)
        if len(raw) < 3:
            continue
        rows = []
        for r in raw:
            cs = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)
            if not cs:
                continue
            rows.append([re.sub(r"<[^>]+>", "", unescape(c)).replace("\xa0", " ").strip()
                         for c in cs])
        rows = [r for r in rows if any(r)]
        if len(rows) >= 3:
            out.append(rows)
    return out


def looks_like_header(row):
    """判断一行是否为名单表表头（区分「表头」与「续表首行的数据」）。"""
    s = "".join(row)
    return bool(re.search(r"(应用|APP|App|软件|名称)", s)
                and re.search(r"(序号|开发者|运营者|主办者|问题|版本|来源|平台|备案)", s))


def parse_rows(header, rows):
    """按表头映射字段，产出明细条目。"""
    idx = {}
    for i, h in enumerate(header):
        hh = re.sub(r"\s+", "", h)
        for k, f in FIELD_MAP:
            if f in idx:
                continue
            if hh == k or hh.endswith(k) or k in hh:
                idx[f] = i
                break
    if "app" not in idx:
        return []
    ent = []
    for r in rows:
        def g(f):
            i = idx.get(f)
            return (r[i].strip() if i is not None and i < len(r) else "")
        app = g("app")
        if not app or len(app) < 2 or len(app) > 60:
            continue
        if re.search(r"^(序号|应用名称|名称|App|APP)$", app):
            continue
        ent.append({"app": app, "dev": g("dev"), "ver": g("ver"),
                    "store": g("store"), "probs": probs_of(g("probs")),
                    "region": g("region")})
    return ent


# ------------------------------------------------------------ 明细：PDF
def is_pdf(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"%PDF"
    except OSError:
        return False


def pdf_tables(path):
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            for tb in pg.extract_tables() or []:
                rows = [[re.sub(r"\s+", " ", (c or "")).strip() for c in r] for r in tb]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 3:
                    out.append(rows)
            txt = pg.extract_text() or ""
            out.append(txt)
    return out


# ---------------------------------------------------------- 明细：OCR
def ocr_boxes(img_path):
    exe = os.path.join(HERE, "tools", "vision_ocr")
    if not os.path.exists(exe):
        return []
    p = subprocess.run([exe, img_path, "--json"], capture_output=True,
                       text=True, encoding="utf-8", errors="ignore")
    try:
        return (json.loads(p.stdout) or {}).get("lines") or []
    except Exception:
        return []


def ocr_table(lines, ncol):
    """把 OCR 框按 y 聚类成行、按 x 分列，还原名单表。

    网信办名单图是规则 6 列表格（编号/名称/类型/运营者/版本号/主要问题），
    Vision OCR 给的是带归一化坐标的文本块 → 行内按 x 排序即得列序。
    """
    if not lines:
        return []
    ys = sorted(lines, key=lambda z: z.get("y") or 0)
    rows, cur, cur_y = [], [], None
    for z in ys:
        y = z.get("y") or 0
        if cur_y is None or abs(y - cur_y) <= 0.022:
            cur.append(z)
            cur_y = y if cur_y is None else (cur_y + y) / 2
        else:
            rows.append(cur)
            cur, cur_y = [z], y
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        cells = [c.get("text", "") for c in sorted(r, key=lambda z: z.get("x") or 0)]
        cells = [c.strip() for c in cells if c.strip()]
        if len(cells) >= 3:
            out.append(cells)
    return out


# ================================================================ 源
def miit_docs():
    """工信部 APP 侵害用户权益专项整治栏目（tzgg + gzdt）。"""
    cols = ["https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html",
            "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/gzdt/index.html"]
    hit = re.compile(r"侵害用户权益|APP（SDK）|App通报|应用软件|个人信息")
    out = {}
    for col in cols:
        html = curl(col)
        if not html:
            continue
        m = re.search(r'queryData="([^"]+)"', html)
        if not m:
            continue
        qd = json.loads(m.group(1).replace("'", '"'))
        page, per, total = 1, 24, None
        while page <= 40:
            d = dict(qd)
            d["paramJson"] = json.dumps({"pageNo": page, "pageSize": per})
            raw = curl(MIIT_API + "?" + urlencode(d), referer=col)
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
                break
            for u, t, dt in items:
                t = re.sub(r"\s+", " ", unescape(t)).strip()
                if hit.search(t):
                    out["https://www.miit.gov.cn" + u] = {"title": t, "date": dt}
            cnt = re.search(r'rows="(\d+)"', inner)
            if cnt:
                per = int(cnt.group(1)) or per
            c2 = re.search(r'count="(\d+)"', inner)
            total = int(c2.group(1)) if c2 else total
            if total and page * per >= total:
                break
            page += 1
            time.sleep(0.3)
    return [dict(v, url=u) for u, v in out.items()]


CAC_QUERIES = ["App个人信息收集使用问题", "违法违规收集使用个人信息",
               "移动应用违法违规收集使用个人信息", "SDK个人信息收集使用",
               "侵害个人信息权益的违法违规App", "移动互联网应用程序个人信息",
               "小程序个人信息", "App个人信息保护", "用户权益 通报"]
CAC_SEARCH = "https://search.cac.gov.cn/cms/cmsadmin/infopub/gjjs.jsp"
CAC_PARAMS = {"pubtype": "S", "pubpath": "portal", "templetid": "1563339473064626",
              "sort": "1", "webappcode": "A09", "searchdir": "A09"}
CAC_SKIP = re.compile(r"解读|答记者问|征求意见|宣传周|论坛|培训|招聘|招标|回眸|"
                      r"一图|图解|案例集|知识|指南")


def cac_docs():
    out = {}
    for kw in CAC_QUERIES:
        for page in (1, 2, 3):
            q = dict(CAC_PARAMS, huopro=kw, mustpro="", notpro="", inpro="", page=page)
            html = curl(CAC_SEARCH + "?" + urlencode(q),
                        referer="https://www.cac.gov.cn/", timeout=45)
            if not html:
                break
            items = re.findall(
                r'<li class="list-item"><a href="([^"]+)"[^>]*>(.*?)</a>'
                r'<span class="search_time">([\d\-: ]+)</span>', html, re.S)
            if not items:
                break
            n = 0
            for u, t, dt in items:
                t = re.sub(r"^»\s*", "", re.sub(r"<[^>]+>", "", unescape(t))).strip()
                if not re.search(r"App|APP|应用|小程序|SDK", t) or CAC_SKIP.search(t):
                    continue
                if not re.search(r"通报|查处|治理|问题|下架", t):
                    continue
                u = u if u.startswith("http") else "https:" + u
                out.setdefault(u, {"title": t, "date": dt.strip()[:10]})
                n += 1
            if n == 0 and page > 1:
                break
            time.sleep(0.4)
    return [dict(v, url=u) for u, v in out.items()]


MSTL_BASE = "http://www.mstl.org.cn"
MSTL_LIST = "/html/news/index%s.html"
MSTL_HIT = re.compile(r"违法违规收集使用个人信息|移动应用.{0,6}个人信息")


def mstl_docs():
    """公安部第三研究所检测中心（公安部技术支撑单位）App 违规通报。

    站点形态：静态分页 `index.html` / `index_2.html` …，页脚给「共 N 条记录 当前页次 x/M」。
    只收 App 违规通报，其余（认证、标准宣贯、满意度调查）一律不取。
    """
    out = {}
    # ⚠️ 必须带 Referer：该站对无来源的直连列表请求会返回空 / 403，
    #    表现为「候选文书 0 份」——不是站点下线，也不是筛选规则问题。
    html = curl(MSTL_BASE + MSTL_LIST % "", referer=MSTL_BASE + "/")
    if not html:
        return []
    m = re.search(r"当前页次\s*\d+\s*/\s*(\d+)\s*页", html)
    pages = int(m.group(1)) if m else 1
    pages = max(1, min(pages, 20))
    for p in range(1, pages + 1):
        h = html if p == 1 else curl(MSTL_BASE + MSTL_LIST % ("_" + str(p)),
                                    referer=MSTL_BASE + "/")
        if not h:
            continue
        for u, t in re.findall(
                r'href="(/html/news/detail_[^"]+)"[^>]*title="([^"]*)"', h):
            t = re.sub(r"\s+", " ", unescape(t)).strip()
            if not MSTL_HIT.search(t):
                continue
            # 路径自带日期：detail_YYYY_MM/DD/<id>.html
            d = re.search(r"detail_(\d{4})_(\d{2})/(\d{2})/", u)
            date = f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else ""
            out[MSTL_BASE + u] = {"title": t, "date": date}
        time.sleep(0.2)
    return [dict(v, url=u) for u, v in out.items()]


def prov_docs():
    if not os.path.exists(PROVCOL):
        return []
    d = json.load(open(PROVCOL, encoding="utf-8"))
    seen, out = set(), []
    for r in d.get("provinces", []):
        for x in r.get("docs", []):
            if x["url"] in seen:
                continue
            seen.add(x["url"])
            out.append(dict(x, province=r["province"]))
    return out


# ============================================================== 抓正文
RE_ATTACH_PDF = re.compile(r'/cms_files/filemanager/[0-9A-Za-z]+/attach/[^"\']*?\.pdf', re.I)
RE_CAC_IMG = re.compile(
    r'(?:https?:)?//www\.cac\.gov\.cn/rootimages/(?:uploadimg/)?[^"\']+\.(?:png|jpg|jpeg)',
    re.I)
# 公安部/病毒中心式：正文内嵌《应用名》(版本x, 来源)
RE_INLINE_APP = re.compile(r"《([^》]{2,40})》\s*(?:[（(]([^）)]{0,60})[）)])?")


_LAW_SUFFIX = re.compile(r"(条例|规定|办法|法|通知|公告|决定|意见|指南|标准|细则|"
                         r"方案|规则|规划|纲要|清单|目录|名录|要求|规范|守则)$")


def _inline_entries(text, lo=2, hi=40):
    """正文内嵌《应用名》(版本, 来源) 抽取（公安部 / 病毒中心 / 省局下架通报）。
    ---------------------------------------------------------------
    ⚠️ 「法条引用」与「以『法』结尾的应用名」形状完全相同：
       《网络安全法》 与 《复真书法》（版本 4.4.3，华为应用市场）都命中后缀规则。
       只按后缀剔除会误杀真实应用——实测三所检测中心「40 款」通报只收 38 款
       （丢的正是《复真书法》《不厌书法》）。
       判据：**带版本 / 来源括号的一律视为应用**；不带括号的才按法条后缀剔除，
       但若同名在本篇别处带括号出现过，仍视为应用。
    """
    hits = RE_INLINE_APP.findall(text)
    with_ver = {a.strip() for a, v in hits if (v or "").strip()}
    out = []
    for app, ver in hits:
        n, v = app.strip(), (ver or "").strip()
        if not (lo <= len(n) <= hi):
            continue
        if not v and n not in with_ver and _LAW_SUFFIX.search(n):
            continue
        if re.search(r"中华人民共和国|国务院|委员会", n):
            continue
        out.append({"app": n, "dev": "", "ver": v, "store": "",
                    "probs": [], "region": ""})
    return out


def mstl_entries(html):
    """公安部三所检测中心通报：按「N、问题类别。涉及 M 款如下：」分节抽明细。

    与纯正文内嵌不同，这里的**问题类别是以小标题给出**的（同一款应用可能出现在多节里），
    因此逐节解析才能把 probs 落到每条明细上 —— 否则该序列在「问题类型 × 年度」里全空。
    """
    i = html.find('id="articlebody"')
    if i < 0:
        return []
    seg = html[i:i + 300000]
    # ⚠️ 不要按第一个 "</div>" 截断：正文段落很长，截断会把最后几节整段丢掉
    #    （实测 42 款通报表因此只抽出 38 款）。改为在**页脚标记**处停。
    ps = [re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", x))).strip()
          for x in re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S)]
    out, cur = [], None
    for t in ps:
        if re.match(r"^(返回列表|联系我们|廉洁承诺)", t) or "版权所有" in t:
            break
        m = re.match(r"^(\d+)[、.．]\s*([^。]{4,90})。\s*涉及\s*(\d+)\s*款", t)
        if m:
            # ⚠️ norm_prob 对未收录表述返回 None —— 不能因此把整节丢掉
            #    （实测「未列明向第三方提供…」「在申请打开…权限时未同步告知」两节
            #     共 14 次点名被静默丢弃，42 款只抽出 38 款）。留原文兜底。
            cur = norm_prob(m.group(2)) or m.group(2)[:24]
            continue
        if not cur:
            continue
        for e in _inline_entries(t):
            e["probs"] = [cur]
            out.append(e)
    return out


def parse_doc(url, meta, ocr=True):
    ref = ("https://www.cac.gov.cn/" if "cac.gov.cn" in url else
           MSTL_BASE + "/" if "mstl.org.cn" in url else "https://www.miit.gov.cn/")
    html = curl(url, referer=ref, timeout=60)
    if not html:
        return None
    title = meta.get("title") or ""
    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = re.sub(r"\s+", " ", unescape(m.group(1))).strip() if m else ""
    body = " ".join(textify(html))
    org, scope = org_scope(title, body, url, meta.get("org", ""))
    kind = notice_kind(title, body)
    nums = [int(x) for x in re.findall(r"(\d{1,4})\s*款", body)]
    declared = max(nums) if nums else None

    entries, carrier = [], "text"
    # 1) 页面内 HTML 表格（省局主力）
    for tb in html_tables(html):
        header = tb[0]
        e = parse_rows(header, tb[1:])
        if e:
            entries += e
            carrier = "html-table"
    # 2) 工信部：附件 PDF
    if not entries:
        m = RE_ATTACH_PDF.search(html)
        if m:
            p = os.path.join(PDFDIR, docid(url) + ".pdf")
            os.makedirs(PDFDIR, exist_ok=True)
            # ⚠️ 必须校验魔数：早期用错 URL 下载到的 HTML 错误页（20+KB）会一直躺在缓存里，
            # 只按体积判断会把它当 PDF 解析并静默吞掉异常。
            if not is_pdf(p):
                curl("https://www.miit.gov.cn" + m.group(0), referer=url, out=p)
            if is_pdf(p):
                try:
                    hdr = None
                    for tb in pdf_tables(p):
                        if isinstance(tb, str):
                            continue
                        # ⚠️ 附件 PDF 的名单表跨页拆成多张：只有首张带表头，后续首行即数据。
                        # 早先直接用 tb[0] 当表头 → 续表整张丢弃（总第55批 24 条只出 10 条）。
                        if looks_like_header(tb[0]):
                            hdr, data = tb[0], tb[1:]
                        elif hdr and len(tb[0]) >= len(hdr) - 1:
                            data = tb
                        else:
                            continue
                        e = parse_rows(hdr, data)
                        if e:
                            entries += e
                            carrier = "pdf"
                except Exception:
                    pass
    # 3) 网信办：名单图 OCR
    if not entries and ocr and not meta.get("no_ocr"):
        imgs = [("https:" + u if u.startswith("//") else u)
                for u in dict.fromkeys(RE_CAC_IMG.findall(html))]
        imgs = [i for i in imgs if not re.search(r"logo|conac|QR-|CAC\.png", i, re.I)]
        os.makedirs(IMGDIR, exist_ok=True)
        for j, img in enumerate(imgs[:14]):
            p = os.path.join(IMGDIR, docid(url) + f"_{j}.png")
            if not os.path.exists(p) and not curl(img, referer=url, out=p):
                continue
            for cells in ocr_table(ocr_boxes(p), 6):
                e = ocr_entry(cells)
                if e:
                    entries.append(e)
        if entries:
            # ⚠️ 质检门禁：名单图版式差异很大，OCR 偶尔会把整张表聚成**一行**
            # （probs 里塞进上百个词，app 名变成「序号」）。这种结果必须丢弃，
            # 否则会给库里塞一个叫「序号」的假应用。判据：条目 ≥3 且单条问题数中位数 ≤8。
            npm = sorted(len(e.get("probs") or []) for e in entries)
            med = npm[len(npm) // 2] if npm else 0
            if len(entries) < 3 or med > 8:
                print(f"  ! 名单图 OCR 聚类异常已丢弃（{len(entries)} 条 / 中位问题数 {med}）：{url}")
                entries = []
            else:
                carrier = "image-ocr"
    # 3.5) 公安部三所检测中心：分节抽取（带问题类别）
    if not entries and "mstl.org.cn" in url:
        entries = mstl_entries(html)
        if entries:
            carrier = "inline-text"
    # 4) 正文内嵌《应用名》(版本, 来源)（公安部 / 病毒中心式，以及省局下架通报的正文点名）
    if not entries:
        entries = _inline_entries(body, lo=2, hi=30)
        if entries:
            carrier = "inline-text"

    # 同文书内去重（⚠️ 同一款应用可能被分节列多次：**合并 probs 而不是丢弃**，
    #    否则「问题类型」只留下第一处，公安部三所序列的问题分布会系统性偏窄）
    seen, uniq = {}, []
    for e in entries:
        k = re.sub(r"[\s（）()【】]", "", e["app"])
        if k in seen:
            old = seen[k]
            old.setdefault("probs", [])
            for p in (e.get("probs") or []):
                if p and p not in old["probs"]:
                    old["probs"].append(p)
            if not old.get("ver") and e.get("ver"):
                old["ver"] = e["ver"]
            continue
        seen[k] = e
        uniq.append(e)

    batches = re.search(r"（?(\d{4})年第(\d+)批[，,]\s*总第(\d+)批", title)
    return {
        "id": docid(url), "title": title, "url": url,
        "date": (meta.get("date") or "").strip()[:10],
        "org": org, "scope": scope, "notice_kind": kind,
        "declared": declared, "entries": uniq, "n_entries": len(uniq),
        "carrier": carrier,
        "batch_total": int(batches.group(3)) if batches else None,
        "province": meta.get("province", ""),
    }


def ocr_entry(cells):
    """OCR 还原出的一行 → 明细条目（列序：编号/名称/类型/运营者/版本/问题）。"""
    cells = [c for c in cells if c]
    if len(cells) < 4:
        return None
    # 去掉首个纯序号
    if re.fullmatch(r"\d{1,4}", cells[0]):
        cells = cells[1:]
    if len(cells) < 3:
        return None
    app = cells[0]
    if len(app) < 2 or len(app) > 40:
        return None
    dev = next((c for c in cells[1:4] if re.search(
        r"有限|科技|网络|信息|传媒|教育|文化|健康|集团|股份|公司|中心|大学|医院", c)), "")
    ver = next((c for c in cells if re.fullmatch(r"[vV]?[\d.]+[A-Za-z0-9._-]*", c)), "")
    probs = []
    for c in cells:
        for l in probs_of(c):
            if l not in probs:
                probs.append(l)
    return {"app": app, "dev": dev, "ver": ver, "store": "", "probs": probs,
            "region": ""}


# ================================================================ 主流程
# 去重逻辑已抽到 `appviol_entity.resolve()`（实体消解 + 事件模型），此处不再自持一份：
# 旧实现只按归一化后的应用名做 key，既会把不同公司的同名产品并成一款，
# 又会因 PDF 提取插入的空格把同一家公司拆成两个主体。详见 appviol_entity.py 头部注释。


def main():
    argv = sys.argv[1:]
    full = "--full" in argv
    # --refresh：**覆盖重写存量**（不新增站点、不动范围，只把已在库的文书重新解析一遍）。
    # 改了正文抽取规则时用，例如「以『法』结尾的 App 名被法条后缀规则误杀」
    # 这类解析器修复——必须重解析才有新明细，重抓 / 重跑聚合都不解决。
    # 配 --only mstl 用时只重解析该站，其余文书从旧库合并回来，不会丢。
    refresh = "--refresh" in argv
    ocr = "--no-ocr" not in argv
    only = ""
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]

    os.makedirs(OUTDIR, exist_ok=True)
    docs_path = os.path.join(OUTDIR, "docs.json")
    # ⚠️ --full 是「全量重抓」：候选清单本身就是全集，故不读旧库（读旧库会让
    #    已经下线的文书永远留在库里）。但它与 --only 同用时候选只剩一个站，
    #    再丢掉旧库 = 把其它站的文书整库删掉 —— 故凡带 --only 一律读旧库，
    #    旧文书随后会被合并回来（见下方「已有文书补齐」）。
    load_old = (not full) or bool(only)
    old = {}
    if os.path.exists(docs_path) and load_old:
        try:
            for d in json.load(open(docs_path, encoding="utf-8")).get("docs", []):
                old[d["url"]] = d
        except Exception:
            old = {}

    # --reorg：机构命名 / 归属口径变更后，离线按「标题 + 域名」重算文书发布主体。
    # 文书里不存正文，落款分支本就不参与（这些文书都是走域名兜底判定的），故不必重抓全网。
    # 典型场景：把「中央网信办 · 秘书局」统一为国家网信办、把国家站上的地方通报归回属地。
    if "--reorg" in argv:
        from collections import Counter as _C
        docs = list(old.values())
        hit = []
        for d in docs:
            if "cac.gov.cn" not in (d.get("url") or ""):
                continue
            org, scope = org_scope(d.get("title") or "", "", d.get("url") or "",
                                   d.get("org") or "")
            kind = notice_kind(d.get("title") or "", "")
            if (org, scope) != (d.get("org") or "", d.get("scope") or ""):
                hit.append((d.get("org"), org, d.get("title", "")))
                d["org"], d["scope"] = org, scope
            if kind != d.get("notice_kind"):
                print(f"  ~ 类型 {d.get('notice_kind')} → {kind}　{d.get('title','')[:34]}")
                d["notice_kind"] = kind
        docs.sort(key=lambda d: (d.get("date") or "", d["title"]), reverse=True)
        meta = json.load(open(docs_path, encoding="utf-8")).get("meta") or {}
        orgs = _C(d["org"] for d in docs)
        meta["by_scope"] = dict(_C(d["scope"] for d in docs))
        meta["top_orgs"] = dict(orgs.most_common(30))
        meta["org_naming"] = (CAC_NATIONAL + " = 中央网信办 = 国家互联网信息办公室"
                              "（同一机构两块牌子；秘书局为其发文机构，不另立发布主体）")
        json.dump({"meta": meta, "docs": docs},
                  open(docs_path, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print(f"✓ 重算发布主体：改动 {len(hit)} 份 / 共 {len(docs)} 份")
        for a, b, t in hit:
            print(f"  · {a} → {b}　{t[:36]}")
        print(f"  机构分布 {dict(orgs.most_common(8))}")
        return 0

    # --apps-only：文书库已就绪，只按新的实体消解 / 事件口径重算 apps.json。
    # 改了去重逻辑但不想重抓全网时用（重抓 652 份要十几分钟）。
    if "--apps-only" in argv:
        docs = list(old.values())
        docs.sort(key=lambda d: (d.get("date") or "", d["title"]), reverse=True)
        apps_list, est = resolve(docs)
        apath = os.path.join(OUTDIR, "apps.json")
        json.dump({"meta": {"updated": date.today().isoformat(), **est},
                   "apps": apps_list},
                  open(apath, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print(f"✓ 仅重算应用库：文书 {len(docs)}　明细行 {est['rows_raw']}"
              f"　事件 {est['incidents']}　去重应用 {est['apps']}"
              f"　重复出现 {est['apps_repeat']}　跨年度相关 {est.get('apps_multi_org',0)}")
        print(f"  文件 {os.path.getsize(apath)/1024/1024:.2f} MB")
        return 0

    cand = []
    if only in ("", "miit"):
        print("▸ 工业和信息化部（国家序列 · 附件 PDF）")
        for r in miit_docs():
            cand.append(r)
    if only in ("", "cac"):
        print("▸ 中央网信办 / 公安部 / 病毒中心（站内检索）")
        for r in cac_docs():
            cand.append(r)
    if only in ("", "prov"):
        pd = prov_docs()
        print(f"▸ 省级通信管理局（属地序列 · 页面 HTML 表格）{len(pd)} 份")
        for r in pd:
            cand.append(r)
    if only in ("", "mstl"):
        print("▸ 公安部第三研究所检测中心（公安部技术支撑单位）")
        for r in mstl_docs():
            cand.append(r)

    urls, seen = [], set()
    for r in cand:
        u = r.get("url") or r.get("u")
        if not u or u in seen:
            continue
        seen.add(u)
        urls.append(dict(r, url=u))
    # ✚ --refresh：**要重解析谁，本来就由旧库决定**，不该受列表页是否可达影响。
    #   把旧库里属于本次范围的文书补进候选（列表页改版 / 频控 / 下线都不再是阻塞）。
    if refresh:
        hosts = {"mstl": ("mstl.org.cn",), "miit": ("miit.gov.cn",),
                 "cac": ("cac.gov.cn",), "prov": ("miit.gov.cn",)}.get(only)
        added = 0
        for u, d in old.items():
            if hosts is not None and not any(x in u for x in hosts):
                continue
            if u in seen:
                continue
            seen.add(u)
            urls.append({"url": u, "title": d.get("title") or ""})
            added += 1
        print(f"↻ 存量重解析候选 {added} 份（按旧库补入，不依赖列表页）")
    print(f"\n候选文书 {len(urls)} 份；已有 {len(old)} 份")

    todo = [r for r in urls if full or refresh or r["url"] not in old]
    print(f"本次待抓 {len(todo)} 份\n")

    docs = []
    for i, r in enumerate(todo, 1):
        try:
            d = parse_doc(r["url"], r, ocr=ocr)
        except Exception as ex:
            d = None
            if i <= 5:
                print(f"  ! {r.get('title','')[:36]} {ex}")
        if d:
            docs.append(d)
        elif r["url"] in old:
            docs.append(old[r["url"]])
        if i % 25 == 0 or i <= 3:
            n = sum(x["n_entries"] for x in docs)
            print(f"  [{i}/{len(todo)}] 明细累计 {n} 条  "
                  f"{r.get('title','')[:34]}", flush=True)
        time.sleep(0.15)
    # 已有文书补齐
    got = {d["url"] for d in docs}
    docs += [v for k, v in old.items() if k not in got]

    docs.sort(key=lambda d: (d.get("date") or "", d["title"]), reverse=True)
    apps_list, est = resolve(docs)

    from collections import Counter
    kinds = Counter(d["notice_kind"] for d in docs)
    carriers = Counter(d["carrier"] for d in docs)
    levels = Counter(d["scope"] for d in docs)
    orgs = Counter(d["org"] for d in docs)
    prob = Counter()
    for a in apps_list:
        for p in a["probs"]:
            prob[p] += 1

    meta = {
        "updated": date.today().isoformat(),
        "documents": len(docs),
        "entries": sum(d["n_entries"] for d in docs),
        # ---- 实体消解结果（对外引用口径）
        "unique_apps": est["apps"],
        "repeat_apps": est["apps_repeat"],
        "apps_repeat_notice": est["apps_repeat_notice"],
        "apps_multi_org": est["apps_multi_org"],
        "apps_name_collision": est["apps_name_collision"],
        "apps_cross_lang": est["apps_cross_lang"],
        "apps_no_owner": est["apps_no_owner"],
        "apps_escalated": est["apps_escalated"],
        "incidents": est["incidents"],
        "incidents_notice": est["incidents_notice"],
        "incidents_fix": est["incidents_fix"],
        "incidents_close": est["incidents_close"],
        "rows_raw": est["rows_raw"],
        "relapse_gap_median": est["relapse_gap_median"],
        "docs_with_entries": sum(1 for d in docs if d["entries"]),
        "by_kind": dict(kinds),
        "by_carrier": dict(carriers),
        "by_scope": dict(levels),
        "org_naming": CAC_NATIONAL + " = 中央网信办 = 国家互联网信息办公室"
                      "（同一机构两块牌子；秘书局为其发文机构，不另立发布主体）",
        "top_orgs": dict(orgs.most_common(30)),
        "date_range": [min((d["date"] for d in docs if d["date"]), default=""),
                       max((d["date"] for d in docs if d["date"]), default="")],
        "note": "去重不只看应用名：先按「归一化应用名 + 运营者主干」做实体消解"
                "（同名不同主体不合并、中英署名不强行合并），再按（机构 · 年份 · 批次）"
                "做事件去重，最后按文书类型拆开批次通报 / 整改复核 / 下架处置。"
                "unique_apps 是唯一可对外引用的「涉及应用数」。",
    }
    json.dump({"meta": meta, "docs": docs},
              open(docs_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    apath = os.path.join(OUTDIR, "apps.json")
    json.dump({"meta": meta, "apps": apps_list},
              open(apath, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"\n✓ 文书 {len(docs)}　明细行 {est['rows_raw']}　事件 {est['incidents']}"
          f"　去重应用 {est['apps']}")
    print(f"  重复被通报 {est['apps_repeat']}（其中纯通报≥2次 {est['apps_repeat_notice']}、"
          f"跨机构 {est['apps_multi_org']}）")
    print(f"  同名不同主体 {est['apps_name_collision']}　中外文并存 {est['apps_cross_lang']}"
          f"　无运营者署名 {est['apps_no_owner']}")
    print(f"  事件分层 通报 {est['incidents_notice']} / 复核 {est['incidents_fix']}"
          f" / 下架 {est['incidents_close']}　再犯间隔中位 {est['relapse_gap_median']} 天")
    print(f"  文书类型 {dict(kinds)}")
    print(f"  明细载体 {dict(carriers)}")
    print(f"  高频问题 {prob.most_common(8)}")
    print(f"  文件 apps.json {os.path.getsize(apath)/1024/1024:.2f} MB"
          f"　docs.json {os.path.getsize(docs_path)/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
