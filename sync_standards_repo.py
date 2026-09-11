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


def git_blob_sha(data: bytes) -> str:
    """GitHub blob sha 就是 git 的对象哈希：sha1('blob <len>\\0' + content)。
    本地算得出来，就能和远端树逐文件比对，命中即复用，不再重复上传。"""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def remote_tree(token):
    """取远端当前树：path -> blob sha。"""
    ref = api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}", token, raw=True)
    sha = (ref.get("object") or {}).get("sha") if isinstance(ref.get("object"), dict) else None
    if not sha:
        return {}
    t = api("GET", f"/repos/{REPO}/git/trees/{sha}?recursive=1", token, raw=True)
    return {e["path"]: e["sha"] for e in (t.get("tree") or []) if e.get("type") == "blob"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--full", action="store_true", help="忽略复用，全部重传")
    a = ap.parse_args()

    if not os.path.isdir(STORE):
        sys.exit(f"本机标准库不存在：{STORE}（先跑 harvest.py / fetch_standards.py）")
    # 递归收集（含 TAF标准/ 等子目录），保留相对路径
    files = []
    for root, _dirs, fns in os.walk(STORE):
        for fn in fns:
            if fn.lower().endswith((".txt", ".md", ".pdf", ".docx")):
                rel = os.path.relpath(os.path.join(root, fn), STORE)
                files.append(rel.replace(os.sep, "/"))
    files = sorted(files)
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

    remote = {} if a.full else remote_tree(token)
    index, tree = [], []
    reuse = upload = 0
    for fn in files:
        p = os.path.join(STORE, fn)
        raw = open(p, "rb").read()
        meta = next((v for v in fetched.values()
                     if re.sub(r"[\\/:*?\"<>|]", "_", v["ref"]) + ".txt" == fn), {})
        bsha = git_blob_sha(raw)
        index.append({
            "file": fn, "chars": len(raw.decode("utf-8", "ignore")), "bytes": len(raw),
            "blob_sha": bsha[:16], "sha256": hashlib.sha256(raw).hexdigest()[:16],
            "source_url": meta.get("url", ""), "cat": meta.get("cat", ""),
        })
        if a.dry:
            flag = "复用" if remote.get("texts/" + fn) == bsha else "上传"
            print(f"  [{flag}] {fn}  {len(raw)/1024:.1f} KB")
            continue
        old = remote.get("texts/" + fn)
        if old == bsha:
            tree.append({"path": "texts/" + fn, "mode": "100644", "type": "blob", "sha": old})
            reuse += 1
            continue
        b = api("POST", f"/repos/{REPO}/git/blobs", token,
                {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        if "sha" not in b:
            print(f"  blob 失败 {fn}: {str(b)[:120]}")
            continue
        tree.append({"path": "texts/" + fn, "mode": "100644", "type": "blob", "sha": b["sha"]})
        upload += 1
        print(f"  ↑ {fn}  {len(raw)/1024:.1f} KB")

    # 远端有、本机已无 → 从树里去掉（传 sha: null）
    for pth in remote:
        if pth.startswith("texts/") and pth[6:] not in files:
            tree.append({"path": pth, "mode": "100644", "type": "blob", "sha": None})
            print(f"  ✗ 移除 {pth[6:]}")

    if a.dry:
        return

    idx_bytes = json.dumps({"updated": date.today().isoformat(),
                            "source_dir": STORE, "count": len(files),
                            "items": index},
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
    payload = {"message": f"standards: 同步 {len(files)} 份原文 {date.today().isoformat()}"
                          f"（新增/更新 {upload}）", "tree": t["sha"]}
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

    print(f"\n已同步 {len(files)} 份（复用 {reuse} · 上传 {upload}）"
          f" → https://github.com/{REPO} (private) · commit {c['sha'][:8]}")


if __name__ == "__main__":
    main()
