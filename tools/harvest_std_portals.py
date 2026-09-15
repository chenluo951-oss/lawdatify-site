#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准库批量补齐：全国标准信息公共服务平台（国标）+ 行业标准信息服务平台

用户 2026-09-15 指定的标准检索入口里，可程序化检索且给得出官方深链的是：
  · 全国标准信息公共服务平台  std.samr.gov.cn      → 国标 GB / GB/T / GB/Z
      POST /gb/search/gbQueryPage  {searchText,pageSize,pageNumber}
      深链 https://std.samr.gov.cn/gb/search/gbDetailed?id=<ID>
  · 行业标准信息服务平台      hbba.sacinfo.org.cn  → 行标 XX/T（食品 NY、卫生 WS、通信 YD…）
      POST /stdQueryList           {key,current,size}
      深链 https://hbba.sacinfo.org.cn/stdDetail/<pk>
  · 全国标准信息公共服务平台同时收录「行业标准」入口（std.samr 下行标走同一底座）

另外三类（网安标委 tc260.org.cn / 中国通信标准化协会 ccsa.org.cn / TAF 电信终端产业协会
taf.org.cn）里，TAF 已有 fetch_taf.py 在跑；tc260 与 CCSA 的公开检索页是 JS 渲染的前端
（无稳定 JSON 接口），其标准绝大多数本来就是 GB/T 与 YD/T，已被上面两个平台覆盖，
故不在此重复抓取，仅在来源清单（sources/seeds.json）中登记其官网检索入口。

用法：
  python3 tools/harvest_std_portals.py            # 全量关键词矩阵（默认）
  python3 tools/harvest_std_portals.py --keys A,B # 只跑部分关键词
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "sources", "standards", "std_portals.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 合规主题关键词矩阵（覆盖：数据/算法/AI/移动应用/平台/交易/广告/价格/食安/计量/包装/
# 餐饮外卖/配送用工/仓储冷链/消费者/检测认证/绿色/无障碍等全部站点领域）
KEYS = [
    # 数据与个人信息
    "个人信息", "隐私", "数据安全", "数据分类分级", "数据治理", "数据质量", "数据元",
    "重要数据", "核心数据", "数据出境", "跨境数据", "公共数据", "数据要素", "数据交易",
    "数据管理能力", "个人信息安全规范", "个人信息保护", "个人金融信息", "健康医疗数据",
    "未成年人网络", "儿童个人信息", "生物特征", "人脸识别", "声纹", "基因",
    # 网络与安全
    "网络安全", "网络数据", "关键信息基础设施", "网络安全等级保护", "信息安全",
    "信息安全技术", "密码", "加密", "漏洞", "渗透测试", "安全评估", "风险评估",
    "安全事件", "应急处置", "安全能力", "安全服务", "零信任", "可信计算",
    # 算法与人工智能
    "人工智能", "生成式", "深度合成", "大模型", "神经网络", "机器学习", "算法",
    "自动化决策", "智能推荐", "知识图谱", "智能语音", "计算机视觉", "自然语言处理",
    "人工智能安全", "算法评估", "智能体",
    # 移动应用与终端
    "移动互联网", "移动应用", "移动智能终端", "应用程序", "应用软件", "移动终端",
    "小程序", "软件开发工具包", "用户信息", "用户权益", "自启动", "通知推送", "应用商店",
    # 平台与网络交易
    "网络交易", "电子商务", "电子合同", "在线支付", "网络支付", "直播营销", "直播电商",
    "网络直播", "平台经济", "平台治理", "共享经济", "网络预约", "本地生活", "即时配送",
    "即时零售", "前置仓", "社区团购", "网络餐饮", "外卖", "餐饮", "餐饮服务",
    "食品经营", "餐饮具", "封签", "明厨亮灶", "食品安全",
    # 广告与价格
    "广告", "互联网广告", "广告标识", "价格", "明码标价", "促销", "折扣", "虚构原价",
    "计量", "净含量", "定量包装", "电子计价秤", "称重", "计量器具",
    # 食品与产品
    "食品", "食用农产品", "预包装食品", "食品标签", "营养标签", "食品添加剂",
    "食品追溯", "食品冷链", "冷冻食品", "冷藏", "冷库", "保鲜", "生鲜",
    "农产品质量", "农药残留", "兽药残留", "食品快检", "检验方法", "抽样检验",
    "产品质量", "产品安全", "缺陷产品", "召回", "质量管理", "质量信用",
    "特种设备", "冷链物流", "物流服务", "仓储", "货架",
    # 消费者与营销
    "消费者", "消费者权益", "投诉处理", "售后服务", "退换货", "无理由退货",
    "预付式消费", "会员", "自动续费", "有奖销售", "直销", "特许经营",
    # 用工与劳动力
    "新就业形态", "劳动者", "灵活用工", "人力资源", "职业健康", "劳动保护",
    # 供应链、信用与治理
    "信用", "信用评价", "企业信用", "合规管理", "合规", "反不正当竞争", "反垄断",
    "知识产权", "商业秘密", "合同", "标准化", "标准体系", "服务标准", "评价规范",
    # 绿色与环保
    "绿色包装", "塑料", "可降解", "过度包装", "食品浪费", "包装回收", "循环利用",
    "绿色产品", "碳排放", "环保",
    # 特殊人群与公共服务
    "无障碍", "适老化", "老年人", "残疾人", "社会责任", "应急管理", "公共安全",
]


def curl_json(url, data=None, timeout=60, retry=3):
    for i in range(retry):
        cmd = ["curl", "-s", "-m", str(timeout), url, "-H", "User-Agent: " + UA,
               "-H", "Accept: application/json, text/plain, */*"]
        if data is not None:
            cmd += ["-X", "POST",
                    "-H", "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
                    "--data", data]
        p = subprocess.run(cmd, capture_output=True, text=True)
        try:
            d = json.loads(p.stdout)
            return d
        except Exception:
            time.sleep(1.0 * (i + 1))
    return None


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ 国标
def gb_search(kw, page=1, size=200):
    from urllib.parse import quote
    d = curl_json("https://std.samr.gov.cn/gb/search/gbQueryPage",
                  data=f"searchText={quote(kw)}&pageSize={size}&pageNumber={page}&sortOrder=asc")
    if not d:
        return 0, []
    return int(d.get("total") or 0), (d.get("rows") or [])


def harvest_gb():
    out = {}
    for i, kw in enumerate(KEYS, 1):
        total, rows = gb_search(kw, 1)
        pages = (total + 199) // 200
        got = 0
        for pn in range(1, min(pages, 12) + 1):
            if pn == 1:
                rs = rows
            else:
                _, rs = gb_search(kw, pn)
            for r in rs:
                code = (r.get("C_STD_CODE") or "").strip()
                if not code:
                    continue
                out[code.replace(" ", "")] = {
                    "code": code,
                    "name": clean(r.get("C_C_NAME")),
                    "nature": (r.get("STD_NATURE") or "").strip(),   # 强制性 / 推荐性
                    "status": (r.get("STATE") or "").strip(),        # 现行 / 即将实施 / 废止
                    "pub": (r.get("ISSUE_DATE") or "")[:10],
                    "impl": (r.get("ACT_DATE") or "")[:10],
                    "url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=" + str(r.get("id") or ""),
                }
                got += 1
            time.sleep(0.3)
        print(f"  [{i}/{len(KEYS)}] 国标 «{kw}» 命中 {total}　累计 {len(out)}")
    return out


# ------------------------------------------------------------------ 行标
def hb_search(kw, page=1, size=100):
    d = curl_json("https://hbba.sacinfo.org.cn/stdQueryList",
                  data=f"key={kw}&current={page}&size={size}")
    if not d:
        return 0, []
    data = d.get("data") or d
    rows = data.get("records") or data.get("rows") or []
    total = int(data.get("total") or 0)
    return total, rows


def ms2date(v):
    """hbba 的时间字段是毫秒时间戳（int），统一转 YYYY-MM-DD。"""
    if not v:
        return ""
    try:
        v = int(v)
    except Exception:
        return str(v)[:10]
    if v > 10_000_000_000:      # 毫秒
        v //= 1000
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(v))
    except Exception:
        return ""


def harvest_hb():
    out = {}
    for i, kw in enumerate(KEYS, 1):
        total, rows = hb_search(kw, 1)
        if not rows:
            continue
        pages = (total + 99) // 100
        for pn in range(1, min(pages, 6) + 1):
            rs = rows if pn == 1 else hb_search(kw, pn)[1]
            for r in rs:
                code = str(r.get("code") or "").strip()
                pk = r.get("pk") or r.get("id")
                if not code or not pk:
                    continue
                out[code.replace(" ", "")] = {
                    "code": code,
                    "name": clean(r.get("chName") or r.get("chineseName") or ""),
                    "status": str(r.get("status") or "").strip(),
                    "pub": ms2date(r.get("issueDate") or r.get("pubDate")),
                    "impl": ms2date(r.get("actDate") or r.get("implementDate")),
                    "industry": str(r.get("industry") or "").strip(),
                    "dept": str(r.get("chargeDept") or "").strip(),
                    "url": "https://hbba.sacinfo.org.cn/stdDetail/" + str(pk),
                }
            time.sleep(0.3)
        print(f"  [{i}/{len(KEYS)}] 行标 «{kw}» 命中 {total}　累计 {len(out)}", flush=True)
    return out


def main():
    only = None
    if "--keys" in sys.argv:
        only = sys.argv[sys.argv.index("--keys") + 1].split(",")
    global KEYS
    if only:
        KEYS = only
    print(f"标准库批量补齐：{len(KEYS)} 个关键词　国标 + 行标")

    print("\n▸ 全国标准信息公共服务平台（国家标准）")
    gb = harvest_gb()
    print(f"  国标合计 {len(gb)} 条")

    print("\n▸ 行业标准信息服务平台")
    hb = harvest_hb()
    print(f"  行标合计 {len(hb)} 条")

    payload = {
        "meta": {
            "updated": date.today().isoformat(),
            "keys": len(KEYS),
            "gb": len(gb),
            "hb": len(hb),
            "sources": {
                "gb": "https://std.samr.gov.cn/gb/search/gbQueryPage",
                "hb": "https://hbba.sacinfo.org.cn/stdQueryList",
            },
            "note": "关键词矩阵批量检索所得：国标取自全国标准信息公共服务平台，行标取自行业标准信息服务平台，"
                    "深链直达该标准详情页。tc260（网安标委）与 CCSA（通信标协）公开页为前端渲染无稳定接口，"
                    "其标准已由 GB/T、YD/T 覆盖。",
        },
        "gb": gb,
        "hb": hb,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"\n✓ 写入 {OUT}：国标 {len(gb)} / 行标 {len(hb)}　{os.path.getsize(OUT) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
