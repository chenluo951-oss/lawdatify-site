#!/usr/bin/env python3
"""公众号原文获取器 —— 解决「地方监管局只在公众号发布、PC 官网无对应页」的溯源问题。

背景
----
地方市场监管局的典型案例、专项行动、价格提醒告诫，相当一部分**只在官方微信
公众号发布**，PC 官网没有对应页。这类内容按引源口径属「官方原文」（公众号是
发布机关自己的渠道），但：

  · 微信对搜索引擎封闭：Bing 的 site:mp.weixin.qq.com 返回 0 条原链；
    通用搜索能拿到正文全文，却不给 URL。
  · mp.weixin.qq.com 对 curl **一律返回 200**（无效链接也是 200，正文里写「参数错误」），
    所以不能用 HTTP 状态码判断文章是否有效。
  · 搜狗微信搜索是目前唯一可自动化的入口：结果页给 /link?url=… 中转链，中转页把
    目标 URL 拆成若干 `url += '…'` 片段（反爬），拼接后即得 mp.weixin.qq.com 临时链，
    curl 跟随即可拿到含 `id="js_content"` 的完整正文。

本工具做三件事
--------------
  1. search  按「机构名 + 关键词」在搜狗微信搜索检索，列出候选文章；
  2. fetch   给定公众号链接，抓取并解析 标题 / 公众号 gh 号 / 作者 / 发布时间 / 正文；
  3. grab    一步到位：检索 → 取第 N 条 → 抓正文 → 落盘 sources/wx/<id>.json。

落盘产物是**站内正文存档**：链接会失效、公众号会改名，但存档不会。
条目里同时记下 gh_ 号与 __biz（公众号的永久唯一标识），作为「这是发布机关自己
的号」的凭据 —— 供 sources_tier.py 判定 wechat-official 时使用。

用法
----
  python3 tools/fetch_wechat.py search --query "阳曲县市场监督管理局 网络餐饮"
  python3 tools/fetch_wechat.py fetch  --url "https://mp.weixin.qq.com/s/xxxx"
  python3 tools/fetch_wechat.py grab   --query "铜梁区 食品安全 典型案例" --pick 0 \
                                       --account "铜梁市场监管" --apply

注意
----
· 搜狗有反爬（antispider / 验证码），**必须低频串行**，一次任务别超过十来次检索；
  命中验证码就停下等一会儿，不要重试轰炸。
· 只用 curl 发请求：本机 python 的 urllib 会被沙箱代理拦截，误判为「全部失效」。
· 正文仅作本机学习研究存档，正式引用以公众号原文为准。
"""

import argparse
import hashlib
import html as htmlmod
import json
import os
import re
import random
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WX_DIR = os.path.join(HERE, "sources", "wx")
ACCOUNTS = os.path.join(WX_DIR, "accounts.json")

CST = timezone(timedelta(hours=8))
UA_PC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_WX = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.44")

# 反爬绕过：UA 池轮换（搜狗会按 UA 指纹限流），每次请求随机取一个。
UA_POOL = [
    UA_PC,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


def pick_ua():
    return random.choice(UA_POOL)


def prime_cookie(cookie="/tmp/.sogou_wx.cookie"):
    """先 GET 搜狗首页，刷新 SNUID/SUV cookie，降低 antispider 命中率。

    搜狗微信搜索的 antispider 多数由「cookie 里缺有效 SNUID」或「同一 SNUID 请求过频」
    触发。每次检索前先打一次首页把 cookie jar 刷新鲜，命中反爬时再刷一次后有限重试。
    """
    try:
        curl("https://weixin.sogou.com/", referer="https://www.sogou.com/",
             save_cookie=cookie, ua=pick_ua(), timeout=20)
    except Exception:  # noqa: BLE001
        pass
    return cookie


SOGOU = "https://weixin.sogou.com/weixin"


def curl(url, referer=None, cookie=None, save_cookie=None, ua=UA_PC, timeout=30):
    """只用 curl：python urllib 被沙箱代理拦截，会误判全失效。

    `-g` 关闭 curl 自身的 glob 展开；搜狗中转链里带**未编码的空格**（它的 query
    参数直接拼原文），不编码 curl 会报 `URL rejected: Malformed input`。
    """
    url = (url or "").strip().replace(" ", "%20")
    cmd = ["curl", "-g", "-sS", "-L", "--compressed", "-A", ua,
           "--max-time", str(timeout)]
    if referer:
        cmd += ["-e", referer]
    if cookie and os.path.exists(cookie):
        cmd += ["-b", cookie]
    if save_cookie:
        cmd += ["-c", save_cookie]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        return p.stdout.decode("utf-8", "ignore")
    except Exception as e:                                   # noqa: BLE001
        return f"__ERR__ {e}"


def sogou_search(query, cookie="/tmp/.sogou_wx.cookie", _retries=1):
    """搜狗微信搜索 → [(标题, 中转链, 公众号名, 日期)]。

    反爬绕过：每次检索前先 prime_cookie 刷新 SNUID；命中 antispider 时刷新 cookie
    并退避后有限重试一次（绝不连环轰炸，否则连 IP 一起封、反而补不齐）。
    """
    from urllib.parse import quote
    prime_cookie(cookie)
    html = curl(f"{SOGOU}?type=2&query={quote(query)}",
                referer="https://weixin.sogou.com/", save_cookie=cookie, ua=pick_ua())
    if "__ERR__" in html[:20]:
        return [], html[:200]
    if re.search(r"antispider|请输入验证码|访问过于频繁", html):
        if _retries > 0:
            prime_cookie(cookie)
            time.sleep(random.uniform(10, 18))
            return sogou_search(query, cookie, _retries - 1)
        return [], "搜狗反爬（antispider/验证码）—— 停一会儿再试，不要重试轰炸"

    out = []
    for blk in re.findall(r'<li id="sogou_vr_11002601_box_\d+".*?</li>', html, re.S):
        m = re.search(r'href="(/link\?url=[^"]+)"', blk)
        t = re.search(r'<h3>\s*<a[^>]*>(.*?)</a>', blk, re.S)
        a = re.search(r'<span class="all-time-y2">(.*?)</span>', blk, re.S)
        d = re.search(r"timeConvert\('(\d+)'\)", blk)
        if not m:
            continue
        out.append({
            "title": clean(re.sub(r"<[^>]+>", "", t.group(1))) if t else "",
            "relay": m.group(1).replace("&amp;", "&"),
            "account": clean(re.sub(r"<[^>]+>", "", a.group(1))) if a else "",
            "ts": int(d.group(1)) if d else 0,
        })
    return out, None


def resolve(relay, cookie="/tmp/.sogou_wx.cookie", _retries=1):
    """中转链 → 文章 HTML。返回 (html, 链接, 错误)。

    两种情形都要处理：① 中转页把目标 URL 拆成若干 `url += '…'` 片段（反爬），
    拼接后需再请求一次；② 中转页直接 302/200 给了文章本体（含 js_content）。
    反爬绕过：命中 antispider 时刷新 SNUID cookie 并退避后有限重试一次（绝不连环轰炸）。
    """
    prime_cookie(cookie)
    html = curl("https://weixin.sogou.com" + relay,
                referer="https://weixin.sogou.com/", cookie=cookie, ua=pick_ua())
    if re.search(r'id="js_content"|var msg_title', html):
        return html, "", None
    frags = re.findall(r"url \+= '([^']*)'", html) or \
        re.findall(r'url \+= "([^"]*)"', html)
    url = "".join(frags).replace("\\/", "/").strip()
    if url.startswith("http") and "mp.weixin.qq.com" in url:
        art = curl(url, referer="https://weixin.sogou.com/", ua=UA_WX)
        if re.search(r'id="js_content"|var msg_title', art):
            return art, url, None
        return "", url, "拼接出的链接未返回正文（临时链可能已过期）"
    if re.search(r"antispider|请输入验证码|访问过于频繁", html):
        if _retries > 0:
            prime_cookie(cookie)
            time.sleep(random.uniform(8, 15))
            return resolve(relay, cookie, _retries - 1)
        return "", "", "中转页命中反爬（已重试仍被挡，稍后再跑此条）"
    return "", "", f"未能拼出目标链（片段数 {len(frags)}）"


def _slice_div(html, start):
    """从 start 处的 '<div' 开始做配对计数，返回完整 <div>…</div>。"""
    i, depth = start, 0
    for m in re.finditer(r"<div\b|</div>", html[start:]):
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                return html[start:start + m.end()]
        else:
            depth += 1
        i = start + m.end()
    return html[start:start + 60000]


def parse_article(html):
    """解析公众号文章：标题 / gh 号 / 作者 / 时间 / 正文。"""
    def one(p, n=1):
        m = re.search(p, html, re.S)
        return m.group(n).strip() if m else ""

    title = one(r"var msg_title = '(.*?)'\.html", 1) or \
        one(r'var msg_title = "(.*?)"\.html', 1) or \
        one(r'<meta property="og:title" content="([^"]*)"')
    title = clean(title)
    gh = one(r'var user_name = "([^"]*)"') or one(r'var user_name = \'([^\']*)\'')
    author = one(r'var author = "([^"]*)"') or one(r'var author = \'([^\']*)\'')
    ts = one(r'var ct = "(\d+)"') or one(r'var create_time = "(\d+)"')

    body = ""
    m = re.search(r'<div[^>]*id="js_content"', html)
    if m:
        seg = _slice_div(html, m.start())
        seg = re.sub(r"<script.*?</script>", "", seg, flags=re.S)
        seg = re.sub(r"<style.*?</style>", "", seg, flags=re.S)
        seg = re.sub(r"<br\s*/?>", "\n", seg)
        seg = re.sub(r"</p>|</section>|</li>", "\n", seg)
        seg = re.sub(r"<[^>]+>", "", seg)
        body = clean(seg)
    return {"title": title, "gh": gh, "author": author,
            "ts": int(ts) if ts.isdigit() else 0, "body": body}


def clean(s):
    s = htmlmod.unescape(s or "")
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = re.sub(r"[ \t\u00a0\u3000]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def biz_of(url):
    m = re.search(r"[?&]__biz=([^&#]+)", url or "")
    from urllib.parse import unquote
    return unquote(m.group(1)) if m else ""


def load_accounts():
    if os.path.exists(ACCOUNTS):
        try:
            return json.load(open(ACCOUNTS, encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            pass
    return {"_note": "公众号身份台账：gh 号 / __biz → 认证主体。"
                     "供 sources_tier.py 判定 wechat-official 与人工核对使用。",
            "accounts": {}}


def save_accounts(d):
    os.makedirs(WX_DIR, exist_ok=True)
    json.dump(d, open(ACCOUNTS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def record_account(art, url, account_hint=""):
    acc = load_accounts()
    key = art["gh"] or biz_of(url)
    if not key:
        return None
    ent = acc["accounts"].setdefault(key, {})
    ent["gh"] = art["gh"] or ent.get("gh", "")
    ent["biz"] = biz_of(url) or ent.get("biz", "")
    ent["name"] = account_hint or art.get("author") or ent.get("name", "")
    ent["seen"] = ent.get("seen", 0) + 1
    ent["last"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    ent.setdefault("verified", False)
    save_accounts(acc)
    return key


def save_article(art, url, query="", account_hint=""):
    os.makedirs(WX_DIR, exist_ok=True)
    key = art["gh"] or biz_of(url) or hashlib.sha1(
        (art["title"] or url).encode("utf-8")).hexdigest()[:12]
    aid = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    pub = ""
    if art["ts"]:
        pub = datetime.fromtimestamp(art["ts"], CST).strftime("%Y-%m-%d")
    rec = {
        "id": aid,
        "title": art["title"],
        "account": account_hint,
        "gh": art["gh"],
        "biz": biz_of(url),
        "author": art["author"],
        "pub": pub,
        "chars": len(art["body"]),
        "body": art["body"],
        "origin_url": url,
        "origin_kind": "mp.weixin.qq.com（搜狗微信搜索中转取得）",
        "query": query,
        "fetched": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        "note": "正文取自发布机关官方微信公众号，仅作本机学习研究存档；"
                "正式引用以公众号原文为准。",
    }
    path = os.path.join(WX_DIR, aid + ".json")
    json.dump(rec, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return path, rec


def cmd_search(a):
    rows, err = sogou_search(a.query)
    if err:
        print(f"检索失败：{err}")
        return 1
    print(f"检索「{a.query}」→ {len(rows)} 条候选\n")
    for i, r in enumerate(rows[:a.limit]):
        d = datetime.fromtimestamp(r["ts"], CST).strftime("%Y-%m-%d") if r["ts"] else "?"
        print(f"[{i}] {d}  {r['account'] or '?'}")
        print(f"     {r['title'][:88]}")
    if not rows:
        print("（无结果：换个关键词，或该号未被搜狗收录）")
    return 0


def cmd_fetch(a):
    art = parse_article(curl(a.url, ua=UA_WX))
    if not art["body"]:
        print("未解析到正文。可能原因：链接已过期（搜狗临时链有效期短）、"
              "需在微信内打开、或文章已删除。")
        return 1
    print(f"标题   : {art['title']}")
    print(f"公众号 : {a.account or art['author']}（gh={art['gh'] or '-'}）")
    print(f"发布   : {datetime.fromtimestamp(art['ts'], CST):%Y-%m-%d} "
          if art["ts"] else "发布   : ?")
    print(f"正文   : {len(art['body'])} 字\n{'-'*60}")
    print(art["body"][:a.preview])
    if a.apply:
        record_account(art, a.url, a.account)
        path, _ = save_article(art, a.url, account_hint=a.account)
        print(f"\n已存档 → {os.path.relpath(path, HERE)}")
    return 0


def cmd_grab(a):
    rows, err = sogou_search(a.query)
    if err:
        print(f"检索失败：{err}")
        return 1
    if not rows:
        print("（无候选）")
        return 1
    for i, r in enumerate(rows[:a.limit]):
        d = datetime.fromtimestamp(r["ts"], CST).strftime("%Y-%m-%d") if r["ts"] else "?"
        print(f"[{i}] {d}  {r['account'] or '?'}  {r['title'][:70]}")
    pick = rows[a.pick]
    print(f"\n选中 [{a.pick}] {pick['title']}\n  {pick['account']}  {pick['relay'][:50]}…")
    body_html, target, err = resolve(pick["relay"])
    if err:
        print(f"取链失败：{err}")
        return 1
    art = parse_article(body_html)
    if not art["body"]:
        print("未解析到正文（链接可能已过期，重跑一次即可）。")
        return 1
    print(f"\n标题   : {art['title']}")
    print(f"公众号 : {a.account or pick['account'] or art['author']}（gh={art['gh'] or '-'}）")
    print(f"正文   : {len(art['body'])} 字")
    if a.apply:
        record_account(art, target, a.account or pick["account"])
        path, rec = save_article(art, target, query=a.query,
                                 account_hint=a.account or pick["account"])
        print(f"已存档 → {os.path.relpath(path, HERE)}（{rec['pub']} / {rec['chars']} 字）")
    else:
        print("\n（预览模式，未落盘；加 --apply 生效）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="公众号原文获取器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="按机构+关键词检索")
    s.add_argument("--query", required=True)
    s.add_argument("--limit", type=int, default=8)
    s.set_defaults(func=cmd_search)

    f = sub.add_parser("fetch", help="抓取给定公众号链接的正文")
    f.add_argument("--url", required=True)
    f.add_argument("--account", default="")
    f.add_argument("--preview", type=int, default=1500)
    f.add_argument("--apply", action="store_true")
    f.set_defaults(func=cmd_fetch)

    g = sub.add_parser("grab", help="检索 → 取第 N 条 → 抓正文 → 落盘")
    g.add_argument("--query", required=True)
    g.add_argument("--pick", type=int, default=0)
    g.add_argument("--limit", type=int, default=8)
    g.add_argument("--account", default="")
    g.add_argument("--apply", action="store_true")
    g.set_defaults(func=cmd_grab)

    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
