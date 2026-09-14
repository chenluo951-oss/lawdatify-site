#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待回溯来源修复：把日报里落在商业媒体/二手转载上的来源链接，换成发布机构的
官方原文深链（政府门户 / 监管机构官网 / 处罚文书网 / 法院官网）。

用法：
    python3 tools/fix_pending_sources.py            # 预览
    python3 tools/fix_pending_sources.py --apply    # 落盘

改动范围（三处保持一致）：
  1) ~/.workbuddy/skills/compliance-report-generator/scripts/daily_data_*.py —— 源数据
  2) lawdatify-site/news/reports/*.html                                    —— 报告网页版
  3) lawdatify-site/news/index.html                                        —— 资讯流（随后由 build_topics 重建，这里先同步）
"""
import os
import re
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.expanduser(
    "~/.workbuddy/skills/compliance-report-generator/scripts")

# 旧 URL -> 官方原文深链
REPL = {
    # ① 42 款 App 违规收集个人信息（国家网络安全通报中心）→ 江苏网信网（江苏省网信办官网）
    "https://finance.sina.com.cn/stock/bxjj/2026-09-01/doc-iniqhsee1557691.shtml":
        "https://jswx.gov.cn/zhengce/zhifa/202609/t20260901_1355881.shtml",
    # ⑥ 同一份通报（光明网 9/9 报道）
    "https://m.gmw.cn/2026-09/09/content_1304561672.htm":
        "https://jswx.gov.cn/zhengce/zhifa/202609/t20260901_1355881.shtml",
    # ⑤ 陕西青峰峡悦豪假日酒店虚构划线价价格欺诈 → 中国市场监管行政处罚文书网
    "https://finance.sina.com.cn/stock/aigc/bwdt/sjzjxzcf/2026-09-01/doc-iniqhfqk1566527.shtml":
        "https://cfws.samr.gov.cn/detail.html?docid=55ecd601f3f949bcba8f5a2454588bbb",
    # ⑩ 北京市市场监管局打击劣质低价专项行动 → 北京市市场监督管理局官网
    "https://www.toutiao.com/article/7683336473453576754/":
        "https://scjgj.beijing.gov.cn/zwxx/scjgdt/202609/t20260909_4856116.html",
    # ⑪ 寻乌县售房未明码标价／公示价与成交价不符 → 中国市场监管行政处罚文书网
    "https://www.163.com/dy/article/L692KRVD05568W0A.html":
        "https://cfws.samr.gov.cn/detail.html?docid=0c9faf8de407452d93c425ba240bae7a",
    # ⑫ 长治市市场监管局双节价格提醒函 → 长治市人民政府官网
    "https://finance.sina.com.cn/wm/2026-09-09/doc-inirfqcu3695284.shtml":
        "https://www.changzhi.gov.cn/xxgkml/zfxxgkml/szfgzbm/czsscjdglj/czsrmzf/lzxx/202609/t20260909_3203811.shtml",
    # ⑬ 中央网信办举报中心 8 月数据 → 12377 官网通知公告
    "https://so.html5.qq.com/page/real/search_news?docid=70000021_0426aa25fe995752":
        "https://www.12377.cn/tzgg/2026/3ba51bdd_web.html",
    # ⑭ 最高法 2026 年反垄断典型案例 → 最高人民法院官网
    "https://www.toutiao.com/article/7683735523189326346/":
        "https://www.court.gov.cn/zixun/xiangqing/511451.html",
    # ⑮ 发改委+市监总局《关于重要工业品低价无序竞争成本核算有关事项的通知》
    #    （2026-09-03 印发，9/10 公开）→ 国家发展改革委官网原文
    "https://m.weibo.cn/status/5341696061867363":
        "https://gbdy.ndrc.gov.cn/gbdyzcjd/202609/t20260910_1407526.html",
}

# 新 URL 对应的分级（用于刷新 news/index.html 的来源标签）
NEW_TIER = {}
for _new in REPL.values():
    NEW_TIER[_new] = ("src-off", "官方原文",
                      "立法机关、监管机构、政府门户发布的原文")


def host_of(url):
    m = re.match(r"https?://([^/]+)/?", url)
    return m.group(1) if m else url


def targets():
    out = []
    # 1) 源数据
    out += sorted(glob.glob(os.path.join(SCRIPTS, "daily_data_*.py")))
    # 2) 报告网页版
    out += sorted(glob.glob(os.path.join(ROOT, "news", "reports", "*.html")))
    # 3) 资讯流
    p = os.path.join(ROOT, "news", "index.html")
    if os.path.exists(p):
        out.append(p)
    return out


def patch_index_html(text):
    """news/index.html 里除 href 外还有「显示域名」与「来源标签」两处需要同步。"""
    for old, new in REPL.items():
        if old not in text:
            continue
        text = text.replace('href="%s"' % old, 'href="%s"' % new)
        # 锚文本显示域名（旧域名 -> 新域名）
        old_host = host_of(old)
        new_host = host_of(new)
        text = text.replace(">%s <span" % old_host, ">%s <span" % new_host)
        # 来源标签升级为官方原文
        cls, label, desc = NEW_TIER[new]
        text = re.sub(
            r'(<span class="rd-src )src-\w+(" title=")[^"]*(">)二手转载(</span>)',
            lambda m: '%s%s%s%s%s%s%s' % (
                m.group(1), cls, m.group(2), desc, m.group(3), label, m.group(4)),
            text)
    return text


def main():
    apply = "--apply" in sys.argv
    total = 0
    for path in targets():
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        new = src
        if os.path.basename(path) == "index.html":
            new = patch_index_html(new)
        else:
            for old, nw in REPL.items():
                new = new.replace(old, nw)
        n = sum(src.count(o) for o in REPL)
        if new == src:
            continue
        total += n
        print("%-6s %-3d处  %s" % ("写入" if apply else "待改", n,
                                   os.path.relpath(path, ROOT)
                                   if path.startswith(ROOT)
                                   else os.path.relpath(path, SCRIPTS)))
        if apply:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
    print("\n合计 %d 处 %s" % (total, "已写入" if apply else "待写入（加 --apply 落盘）"))


if __name__ == "__main__":
    main()
