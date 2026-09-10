#!/usr/bin/env python3
"""
法规 / 标准原文抓取与本机归档（用户长期委托的「标准检索更新」任务的执行器）。

做什么：
1. 读 sources/standards/seeds.json，逐个到**发布机构官网**抓正文；
2. 正文存两份：
   - 本机标准库 ~/Documents/2.法规、 标准、指南等/0.站点标准库/*.txt（人可读、可检索）
   - 站点语料库 sources/library/corpus/*.txt + 索引（供 enrich_duties 抽条款、search_lib 全文检索）
3. 抓取结果写入 sources/standards/fetched.json（URL + 时间 + 字数），保证可溯源。

不做什么：不生成、不臆造正文；抓不到就记为 failed，等下个周期再试。

注意：沙箱里 python urllib 常被代理拦掉，本脚本统一走 curl 子进程。

用法：
  python3 fetch_standards.py            # 抓 seeds 里尚未入库的
  python3 fetch_standards.py --all      # 强制重抓
  python3 fetch_standards.py --dry      # 只列清单不抓
  python3 fetch_standards.py --check    # 只做 URL 可达性体检
"""
import os, re, sys, json, html, hashlib, subprocess, argparse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "sources", "library", "corpus")
IDX = os.path.join(CORPUS, "_index.json")
SEEDF = os.path.join(HERE, "sources", "standards", "seeds.json")
LOG = os.path.join(HERE, "sources", "standards", "fetched.json")
STORE = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# ---------------- 网络 ----------------

def curl(url, timeout=30, head=False):
    cmd = ["curl", "-sIL" if head else "-sL", "--max-time", str(timeout), "-A", UA,
           "-H", "Accept-Language: zh-CN,zh;q=0.9"]
    if head:
        cmd += ["-o", "/dev/null", "-w", "%{http_code}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    except Exception as e:
        return ""
    return r.stdout.decode("utf-8", "ignore")


TAG_STRIP = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
TAG = re.compile(r"(?s)<[^>]+>")


def html_to_text(raw):
    raw = TAG_STRIP.sub(" ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|td)>", "\n", raw)
    txt = html.unescape(TAG.sub("", raw))
    txt = re.sub(r"[ \t\r　]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n", txt).strip()


def pick_main(text):
    lines = [l.strip() for l in text.split("\n")]
    blocks, cur = [], []
    for l in lines:
        if len(l) < 2:
            if len(cur) > 3:
                blocks.append("\n".join(cur))
            cur = []
        else:
            cur.append(l)
    if len(cur) > 3:
        blocks.append("\n".join(cur))
    return max(blocks, key=len) if blocks else text


# ---------------- 语料库 ----------------

def load_idx():
    if os.path.exists(IDX):
        return json.load(open(IDX, encoding="utf-8"))
    return {"updated": "", "items": {}}


def add_to_corpus(idx, title, ref, cat, text, url):
    os.makedirs(CORPUS, exist_ok=True)
    did = hashlib.md5(title.encode("utf-8")).hexdigest()[:12]
    open(os.path.join(CORPUS, did + ".txt"), "w", encoding="utf-8").write(text)
    idx["items"][did] = {
        "id": did, "code": ref, "name": title, "cat": cat,
        "pub": "", "impl": "", "toc": [], "src": url,
        "chars": len(text), "head": text[:600],
    }
    idx["updated"] = date.today().isoformat()
    return did


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    seeds = json.load(open(SEEDF, encoding="utf-8"))["seeds"]
    if a.check:
        for s in seeds:
            print(f"  {curl(s['url'], head=True):>4s}  {s['ref']}")
        return

    os.makedirs(STORE, exist_ok=True)
    idx = load_idx()
    have = {d.get("name", "") for d in idx["items"].values()}
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {}

    ok = skip = fail = 0
    for s in seeds:
        ref, title, url, cat = s["ref"], s["title"], s["url"], s.get("cat", "法律")
        if not a.all and title in log and title in have:
            print(f"  已有  {ref}")
            skip += 1
            continue
        if a.dry:
            print(f"  待抓  {ref}  {url}")
            continue
        raw = curl(url)
        txt = pick_main(html_to_text(raw)) if raw else ""
        if len(txt) < 800:
            print(f"  失败  {ref}（正文 {len(txt)} 字，可能非正文页或抓取被拦）")
            log.setdefault(title, {})["last_fail"] = date.today().isoformat()
            fail += 1
            continue
        fn = re.sub(r"[\\/:*?\"<>|]", "_", title) + ".txt"
        open(os.path.join(STORE, fn), "w", encoding="utf-8").write(txt)
        did = add_to_corpus(idx, title, ref, cat, txt, url)
        log[title] = {"ref": ref, "url": url, "corpus_id": did, "cat": cat,
                      "chars": len(txt), "fetched": date.today().isoformat()}
        print(f"  抓到  {ref}  {len(txt)} 字")
        ok += 1

    json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n抓到 {ok} · 跳过 {skip} · 失败 {fail}")
    print("本机标准库：", STORE)


if __name__ == "__main__":
    main()
