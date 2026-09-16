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
    # 「通知公告 > 行政处罚案件」——总局本级作出的行政处罚决定书（反垄断、经营者集中
    # 为主）。2026-09-16 补：此前案例库只覆盖了曝光台与要闻，这条最权威的本级决定书
    # 来源一直没接上。
    ("市场监管总局·行政处罚案件", "https://www.samr.gov.cn/fldes/tzgg/xzcf/index.html"),
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
    # 《反垄断法》与《反不正当竞争法》是两部法、两套执法，混成一类会让
    # 「垄断协议 / 经营者集中」这类总局本级案子被归到错误的法律体系下。
    ("反垄断", r"垄断|经营者集中|滥用市场支配地位|排除、限制竞争"),
    # 「知识产权」必须排在「计量与质量」之前：后者的「假冒」会抢走
    # 「销售假冒注册商标的商品案」这类本属商标法的案子。
    ("知识产权", r"商标|专利|著作权|知识产权|地理标志|非正常专利申请|注册商标|"
              r"侵犯商业秘密|版权|盗版"),
    ("价格违法", r"价格|明码标价|哄抬|囤积|低价倾销|虚构原价|标价之外"),
    ("食品安全", r"食品|餐饮|农残|过期|标签|添加剂|餐具|无证经营|保质期|"
              r"食用农产品|肉制品|水产品|糕点|茶叶|蔬菜|水果|生鲜|预包装"),
    ("计量与质量", r"计量|缺斤短两|电子秤|净含量|质量不合格|抽检|假冒|伪劣|"
                r"特种设备|产品质量|伪造产地|冒用|工业产品|强制性认证"),
    ("广告违法", r"广告|绝对化用语|疗效|代言|虚假广告"),
    ("移动应用与个人信息", r"app|应用程序|小程序|sdk|权限|摇一摇|开屏|预置|"
                    r"应用分发|应用商店|个人信息|隐私|账号注销|收集使用|"
                    r"过度索权|强制授权|用户权益"),
    ("数据与网络安全", r"数据安全|网络安全|等级保护|漏洞|关键信息基础设施|"
                  r"数据出境|重要数据|勒索|攻击|泄露"),
    ("网络与平台", r"网络交易|平台|电子商务|直播|外卖|网络餐饮|即时配送|"
                r"刷单炒信|平台责任|二选一"),
    # 地市市监公示里占比很高的一类：年报/经营异常名录/吊销营业执照（《公司法》第 260 条、
    # 《企业信息公示暂行条例》），既不属食品也不属价格，此前全部落到兜底「其他」。
    ("登记与信用监管", r"年度报告|年报|经营异常名录|吊销营业执照|注销登记|"
                  r"企业登记|市场主体登记|长期停业|未开业"),
    ("消费者权益", r"消费者|预付|退费|会员|格式条款|不公平条款|七日无理由"),
]


PROVINCES = ["北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
             "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
             "广东", "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
             "青海", "宁夏", "新疆", "内蒙古"]

# 省级区划 + 主要城市。用于校验「XX网信办」里真的抓到了地名 ——
# 正则挑出的片段必须落在白名单内，否则说明它吃进了机关名
# （曾把「市场监管总局会同中央网信办」的地名识别成「监管总局会同中央」）。
PLACES = set(PROVINCES) | {
    "深圳", "广州", "杭州", "宁波", "南京", "苏州", "无锡", "成都", "武汉", "西安",
    "青岛", "大连", "厦门", "济南", "郑州", "长沙", "合肥", "福州", "昆明", "南昌",
    "贵阳", "兰州", "太原", "石家庄", "沈阳", "长春", "哈尔滨", "呼和浩特",
    "银川", "西宁", "乌鲁木齐", "拉萨", "南宁", "海口", "温州", "佛山", "东莞"}

# 同一机构不同牌子 → 一个名字。中央网信办 / 国家网信办 / 国家互联网信息办公室
# 是同一套班子的三块牌子，分开列会让「按机关找案例」这件事失效。
ORG_ALIAS = {
    "中央网信办": "国家网信办",
    "国家互联网信息办公室": "国家网信办",
    "中央网络安全和信息化委员会办公室": "国家网信办",
}


def _org_by_title(title, org):
    """按标题校正发布机关（未做同机构别名归一，见 fix_org）。

    ⚠️ 2026-09-16 修：案例库的 org 字段有一部分来自站点资讯流的自动解析，实测有
    **实质错标** —— 浙江 / 海南 / 山东网信办发布的 App 通报被统一标成
    「国家互联网信息办公室」；地方市场监管局发布的「铁拳」「春雷」典型案例被标成
    「人民法院」「人民检察院」。机关归属写错会直接误导读者去错的门投诉、找错依据，
    因此改为**以标题为准**校正：标题里点名了哪家机关就归哪家，判不出才沿用原值。
    幂等，可反复执行。
    """
    t = (title or "").strip()
    o = (org or "").strip()

    # 0) 市场监管总局牵头的（如「市场监管总局会同中央网信办…约谈平台」）——
    #    牵头机关才是发布主体，这一步必须排在做网信判断之前，否则会被
    #    「标题里有『网信办』」抢走，甚至把「监管总局会同中央」当成地名。
    if re.match(r"^\s*(国家市场监督管理总局|市场监管总局)", t):
        return "市场监管总局"

    # 1) 标题点名了网信机构 —— 判出地名就归地方网信办，否则归国家网信办
    if re.search(r"网信办|互联网信息办公室", t):
        m = re.search(r"([\u4e00-\u9fa5]{2,8}?)(?:省|市|自治区|自治州|区|县)?"
                      r"(?:委)?(?:互联网信息办公室|网信办)", t)
        place = re.sub(r"^(关于|据|由|经|通知|通报)", "", (m.group(1) if m else "").strip())
        place = re.sub(r"(省|市|自治区|自治州)$", "", place)
        # 地名必须落在白名单里，否则说明正则吃进了机关名（如「监管总局会同中央」）
        if place in PLACES:
            return f"{place}网信办"
        return "国家网信办"

    # 2) 标题以省份 / 直辖市开头且是网信类内容（如「浙江关于微记账等 38 款 App…通报」）
    for p in PROVINCES:
        if t.startswith(p) and re.search(r"app|小程序|个人信息|隐私", t, re.I):
            return f"{p}网信办"

    # 3) 市场监管系统（⚠️ 不要用「专项整治」当关键词：它不专属市监系统，
    #    曾把工信部的「关于开展APP侵害用户权益专项整治工作的解读」误抢过来）
    if re.search(r"市场监管总局|国家市场监督管理总局", t):
        return "市场监管总局"
    if re.search(r"市场监管局|市场监督管理局|工商局|铁拳|春雷|双随机|守护消费", t):
        return "地方市场监管局"

    # 4) 司法系统（标题明确点到法院 / 检察院时才归）
    if re.search(r"人民法院|检察院", t):
        return "人民法院" if "法院" in t else "人民检察院"

    # 5) 工信系统
    if re.search(r"工业和信息化部|工信部|通信管理局|通管局", t):
        return "工业和信息化部"

    # 6) 公安系统
    if re.search(r"公安", t):
        return "公安部"

    # 7) 国家 / 中央网信办（标题无地方限定）
    if re.search(r"国家网信办|中央网信办", t):
        return "国家网信办"

    return o or "未标注"


def fix_org(title, org):
    """发布机关最终值 = 按标题校正 + 同机构不同牌子归一（幂等）。"""
    v = _org_by_title(title, org)
    return ORG_ALIAS.get(v, v)


def guess_type(*parts):
    """按规则表判定案例类型（首个命中即停）。

    ⚠️ 2026-09-16 修：预置来源（App 违规通报批次、站点资讯流）此前用一行
    硬编码 `"个人信息与数据" if "App" in title else "其他"` —— 只认标题里
    正好写着「App」，于是「关于侵害用户权益行为的APP通报」（全大写）之类
    全部掉进兜底，308 条里「其他」一度占 119 条（39%）。现在统一走本规则表，
    且正则用 re.I（APP / App / app 一视同仁）。
    """
    t = " ".join(p for p in parts if p)
    for name, pat in CASE_TYPES:
        if re.search(pat, t, re.I):
            return name
    return "其他"


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
            t = re.sub(r"<[^>]+>", "", unescape(t))   # 标题里常带 <br/> 换行标签
            t = re.sub(r"\s+", " ", t).strip()
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

    # 地市监局官网的行政处罚公示（tools/harvest_local_amr.py 采集）
    # 一条「案件信息公开表」会被拆成 N 条案例，url 带 #c<序号> 锚点，仍然直达官网原文。
    lp = os.path.join(HERE, "sources", "cases", "local_amr.jsonl")
    local_n, local_urls, local_rows = 0, set(), []
    if os.path.exists(lp):
        for line in open(lp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except Exception:
                continue
            if not c.get("url"):
                continue
            local_urls.add(c["url"])
            local_rows.append(c)
    # ⚠️ cases.json 是**增量累积**的（以现有文件为底）。地市采集侧的质量闸门把某条记录
    # 剔除后，案例库里那份副本不会自动消失 —— 必须按 local_amr.jsonl 做一次镜像同步：
    # 「出自地市监采集但已不在 jsonl 里」的记录一并删掉，否则标题含「统一社会信用代码」
    # 这类垃圾会永久留在案例库里。
    if local_urls:
        keep = [c for c in cases
                if not ((c.get("org") or "") == "地方市场监管局"
                        and c.get("agency") and c.get("url") not in local_urls)]
        if len(keep) != len(cases):
            print(f"▸ 地市监采集侧已剔除 {len(cases) - len(keep)} 条，案例库同步移除")
        cases = keep
    # ⚠️ 还有一层：**已存在的记录也要用本地库的版本覆盖**。
    # cases.json 的增量语义是「有就跳过」，于是改进解析规则后用 `--refresh` 重采出来的
    # 新标题永远进不了案例库（本地 jsonl 已经是新标题，案例库里还是旧的半截案由）。
    idx = {c["url"]: i for i, c in enumerate(cases) if c.get("url")}
    for c in local_rows:
        j = idx.get(c["url"])
        if j is not None:
            cases[j] = c
        else:
            idx[c["url"]] = len(cases)
            cases.append(c)
            local_n += 1
    have = {c["url"] for c in cases}
    print(f"▸ 地市监官网处罚公示：并入 {local_n} 条（本地库 {len(local_rows)} 条，"
          f"覆盖刷新 {len(local_rows) - local_n} 条）")

    todo = [(u, r) for u, r in cand.items() if u and u not in have]
    print(f"\n▸ 待解析 {len(todo)} 条（已有 {len(cases)} 条）")
    for i, (u, r) in enumerate(todo, 1):
        preset = r.get("_preset")
        if preset:
            _t = preset.get("title", "")
            if SKIP.search(_t):
                # 预置来源（App 通报批次 / 站点资讯流）此前不做噪声过滤，
                # 把「…工作的解读」「评《…》出台」这类评论文章也当案例收了进来。
                continue
            _cats = "、".join(preset.get("categories") or [])
            cases.append({
                "title": _t, "url": u,
                "date": preset.get("date", ""), "org": preset.get("org", ""),
                "type": guess_type(_t, _cats),
                "laws": (["App违法违规收集使用个人信息行为认定方法"]
                         if re.search(r"app|个人信息|用户权益", _t, re.I) else []),
                "fines": [],
                "fact": _cats[:260],
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

    # 把此前落到兜底「其他」的条目按现行规则表重新归类。
    # 只补不覆盖：已有明确分类的条目保持不动，避免用标题回判劣化正文判定的结果。
    reclassified = 0
    for c in uniq:
        if (c.get("type") or "其他") == "其他":
            nt = guess_type(c.get("title", ""), c.get("fact", ""))
            if nt != "其他":
                c["type"] = nt
                reclassified += 1
    if reclassified:
        print(f"  重新归类 {reclassified} 条（原落兜底「其他」）")

    # 历史类别名归并：「个人信息与数据」是旧名，与现行的
    # 「移动应用与个人信息」语义重叠（案例库中这类内容基本都是 App 通报），
    # 不归并的话页面上会并排出现两个意思一样的分类。
    RENAME = {"个人信息与数据": "移动应用与个人信息"}
    renamed = 0
    for c in uniq:
        old = c.get("type")
        if old in RENAME:
            c["type"] = RENAME[old]
            renamed += 1
    if renamed:
        print(f"  类别归并 {renamed} 条（{ '、'.join(RENAME) } → { '、'.join(set(RENAME.values())) }）")

    # 发布机关校正（以标题为准，幂等）
    org_fixed = 0
    for c in uniq:
        n = fix_org(c.get("title", ""), c.get("org", ""))
        if n != (c.get("org") or ""):
            c["org"] = n
            org_fixed += 1
    if org_fixed:
        print(f"  校正发布机关 {org_fixed} 条")

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
