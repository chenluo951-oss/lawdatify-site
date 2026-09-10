#!/usr/bin/env python3
"""
把本机「法规/标准原文库」同步到 GitHub 私有仓库 chenluo951-oss/lawdatify-standards。

为什么要私有：标准（尤其 GB/T 等推荐性国标）正文受版权保护，公开分发有法律风险；
法律、行政法规、规章属官方文件不受著作权保护，但混在同一目录里，一律按私有存档处理。
公开站点 lawdatify-site 只发布元数据 + 官方深链，不上传任何标准正文。

同步方式：GitHub Git Data API（create blob → create tree → create commit → update ref）。
沙箱里 git push 常被代理拦截，API 更稳；只做快进式全量快照，不做历史清理。

用法：
  python3 sync_standards_repo.py            # 同步本机标准库
  python3 sync_standards_repo.py --dry      # 只看会同步什么
"""
import os, re, sys, json, base64, hashlib, argparse, subprocess
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.expanduser("~/Documents/2.法规、 标准、指南等/0.站点标准库")
REPO = "chenluo951-oss/lawdatify-standards"
BRANCH = "main"
API = "https://api.github.com"
FETCHED = os.path.join(HERE, "sources", "standards", "fetched.json")


def pat():
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=HERE,
                         capture_output=True, text=True).stdout.strip()
    m = re.search(r"https://[^:]+:([^@]+)@", url)
    if not m:
        sys.exit("无法从 git remote 解析 PAT")
    return m.group(1)


def api(method, path, token, payload=None, raw=False):
    cmd = ["curl", "-s", "--max-time", "90", "-X", method,
           "-H", f"Authorization: Bearer {token}",
           "-H", "Accept: application/vnd.github+json",
           "-H", "Content-Type: application/json"]
    url = API + path
    if payload is not None and not raw:
        cmd += ["--data-binary", "@-"]
        r = subprocess.run(cmd + [url], input=json.dumps(payload, ensure_ascii=False),
                           capture_output=True, text=True)
    else:
        r = subprocess.run(cmd + [url], capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return {"_raw": r.stdout, "_err": r.stderr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if not os.path.isdir(STORE):
        sys.exit(f"本机标准库不存在：{STORE}（先跑 fetch_standards.py）")
    files = sorted(f for f in os.listdir(STORE) if f.lower().endswith((".txt", ".md")))
    if not files:
        sys.exit("本机标准库为空")

    token = pat()
    fetched = json.load(open(FETCHED, encoding="utf-8")) if os.path.exists(FETCHED) else {}

    # 空仓库无法直接 create blob，先用 Contents API 建首个提交引导出默认分支
    if not (api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}", token, raw=True) or {}).get("object"):
        boot = api("PUT", f"/repos/{REPO}/contents/README.md", token, {
            "message": "chore: 初始化私有标准库",
            "content": base64.b64encode("# lawdatify-standards\n".encode()).decode(),
            "branch": BRANCH})
        print("  初始化仓库：", "OK" if boot.get("commit") else str(boot)[:120])

    index = []
    tree = []
    for fn in files:
        p = os.path.join(STORE, fn)
        raw = open(p, "rb").read()
        content = raw.decode("utf-8", "ignore")
        meta = next((v for v in fetched.values()
                     if re.sub(r"[\\/:*?\"<>|]", "_", v["ref"]) + ".txt" == fn
                     or v.get("corpus_id") and False), {})
        index.append({
            "file": fn, "chars": len(content), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()[:16],
            "source_url": meta.get("url", ""), "cat": meta.get("cat", ""),
        })
        if a.dry:
            print(f"  将同步  {fn}  {len(raw)/1024:.1f} KB")
            continue
        b = api("POST", f"/repos/{REPO}/git/blobs", token,
                {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        if "sha" not in b:
            print(f"  blob 失败 {fn}: {str(b)[:120]}")
            continue
        tree.append({"path": "texts/" + fn, "mode": "100644", "type": "blob", "sha": b["sha"]})
        print(f"  ✓ {fn}  {len(raw)/1024:.1f} KB")

    if a.dry:
        return

    idx_bytes = json.dumps({"updated": date.today().isoformat(),
                            "source_dir": STORE, "items": index},
                           ensure_ascii=False, indent=1).encode("utf-8")
    b = api("POST", f"/repos/{REPO}/git/blobs", token,
            {"content": base64.b64encode(idx_bytes).decode(), "encoding": "base64"})
    tree.append({"path": "index.json", "mode": "100644", "type": "blob", "sha": b["sha"]})

    readme = (f"# lawdatify-standards\n\n法规与标准原文归档（本机标准库的 GitHub 私有镜像）。\n\n"
              f"- 更新时间：{date.today().isoformat()}\n"
              f"- 本机来源：`{STORE}`\n"
              f"- 抓取脚本：`fetch_standards.py`（站点仓库 lawdatify-site）\n"
              f"- 条目索引：`index.json`（含来源 URL 与 SHA256）\n\n"
              f"> 标准正文受版权保护，本仓库设为私有，仅作个人存档与版本留痕，不对外分发。\n"
              f"> 公开站点只发布元数据与发布机构官网深链。\n").encode("utf-8")
    b = api("POST", f"/repos/{REPO}/git/blobs", token,
            {"content": base64.b64encode(readme).decode(), "encoding": "base64"})
    tree.append({"path": "README.md", "mode": "100644", "type": "blob", "sha": b["sha"]})

    t = api("POST", f"/repos/{REPO}/git/trees", token, {"tree": tree})
    if "sha" not in t:
        sys.exit(f"tree 创建失败：{str(t)[:300]}")

    parent = None
    ref = api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}", token, raw=True)
    if isinstance(ref.get("object"), dict):
        parent = ref["object"]["sha"]
    payload = {"message": f"standards: 同步 {len(files)} 份原文 {date.today().isoformat()}",
               "tree": t["sha"]}
    if parent:
        payload["parents"] = [parent]
    c = api("POST", f"/repos/{REPO}/git/commits", token, payload)
    if "sha" not in c:
        sys.exit(f"commit 失败：{str(c)[:300]}")

    if parent:
        r = api("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}", token, {"sha": c["sha"]})
    else:
        r = api("POST", f"/repos/{REPO}/git/refs", token,
                {"ref": f"refs/heads/{BRANCH}", "sha": c["sha"]})
    if "object" not in r and r.get("ref") is None:
        sys.exit(f"ref 更新失败：{str(r)[:300]}")

    print(f"\n已同步 {len(files)} 份 → https://github.com/{REPO} (private) · commit {c['sha'][:8]}")


if __name__ == "__main__":
    main()
