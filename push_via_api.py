#!/usr/bin/env python3
"""当 git push 被沙箱网络拦截时，用 GitHub Git Data API 推送本地待提交的变更。

为什么需要它：本机的出站代理会间歇性拦截 git-over-HTTPS（表现为
"Empty reply from server" / "Failed to connect to github.com port 443"），
但 api.github.com 通常仍然可达。这时可以用 REST API 构造一次等价的 commit。

原理：
  1. 取本地相对远端 main 的变更清单（A/M/D）
  2. 为新增/修改的文件创建 blob
  3. 以远端 main 的 tree 为 base_tree 建新 tree（删除的路径传 sha=null）
  4. 创建 commit（父提交 = 当前远端 main）并快进 refs/heads/main

限制：只做快进（不 force），因此无法用它抹除历史；历史上已含的文件
需要另行用 git filter-repo 清理。
"""

import base64
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "chenluo951-oss/lawdatify-site"
BRANCH = "main"


def get_pat():
    """从 remote origin 里取 PAT（本机 remote URL 内嵌了 token）。"""
    url = subprocess.run(["git", "-C", HERE, "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    # remote 形如 https://<user>:<PAT>@github.com/owner/repo.git
    # 也可能没有用户名，两种都要能取到 token
    if "@" in url and "://" in url:
        userinfo = url.rsplit("@", 1)[0].split("://")[-1]
        return userinfo.split(":", 1)[1] if ":" in userinfo else userinfo
    return os.environ.get("GITHUB_PAT", "")


def api(method, path, data=None, raw=False):
    pat = get_pat()
    cmd = ["curl", "-s", "--max-time", "45", "-X", method,
           "-H", f"Authorization: Bearer {pat}",
           "-H", "Accept: application/vnd.github+json",
           "-H", "X-GitHub-Api-Version: 2022-11-28",
           f"https://api.github.com{path}"]
    if data is not None:
        tmp = f"/tmp/_gh_body.json"
        with open(tmp, "w") as f:
            json.dump(data, f)
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{tmp}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if raw:
        return r.stdout
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_err": r.stdout[:300], "_stderr": r.stderr[:200]}


def git(*args):
    return subprocess.run(["git", "-C", HERE] + list(args),
                          capture_output=True, text=True).stdout


def main():
    status = git("status", "-sb").splitlines()[0]
    print("当前分支状态:", status)
    # 不做 "ahead" 提前返回：本脚本按「远端树 vs 本地文件」做快照同步，幂等。
    # 本地 commit 与否都能发布 —— 发布的是当前工作区的实际内容。

    ref = api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
    if "object" not in ref:
        print("无法获取远端 ref:", ref)
        return 1
    base_sha = ref["object"]["sha"]
    print("远端 main:", base_sha[:8])

    # 对比「远端树」与「本地文件」，不依赖本地 origin/main 是否最新
    # （fetch 也可能被同一代理拦掉，导致 origin/main 过时引发 422 BadObjectState）
    remote = api("GET", f"/repos/{REPO}/git/trees/{BRANCH}?recursive=1")
    remote_files = {t["path"] for t in remote.get("tree", [])
                    if t.get("type") == "blob"}
    print(f"远端文件 {len(remote_files)} 个")

    EXCLUDE_DIRS = (".git", "_private", "_quarantine", "__pycache__", "node_modules")
    local_files = {}
    for dp, dn, fn in os.walk(HERE):
        dn[:] = [d for d in dn if d not in EXCLUDE_DIRS]
        for x in fn:
            if x in (".DS_Store",):
                continue
            full = os.path.join(dp, x)
            rel = os.path.relpath(full, HERE)
            local_files[rel] = full
    print(f"本地待发布文件 {len(local_files)} 个")

    tree_entries = []
    to_delete = sorted(remote_files - set(local_files))
    for rel in to_delete:
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": None})
    failed = 0
    for rel, full in sorted(local_files.items()):
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        blob = api("POST", f"/repos/{REPO}/git/blobs",
                   {"content": content, "encoding": "base64"})
        if "sha" not in blob:
            print(f"  blob 创建失败 {rel}: {blob}")
            failed += 1
            if failed > 2:
                return 1
            continue
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": blob["sha"]})
    print(f"待写入 {len(tree_entries)} 个路径（删除 {len(to_delete)} / "
          f"新增或修改 {len(local_files)}）")
    for rel in to_delete[:8]:
        print("    删除:", rel)

    # 不带 base_tree：tree 即完整快照，重复运行幂等
    tree = api("POST", f"/repos/{REPO}/git/trees", {"tree": tree_entries})
    if "sha" not in tree:
        print("tree 创建失败:", tree)
        return 1

    try:
        last_msg = subprocess.run(["git", "-C", HERE, "log", "-1", "--pretty=%B"],
                               capture_output=True, text=True).stdout.strip()
    except Exception:
        last_msg = "sync via API"
    new_commit = api("POST", f"/repos/{REPO}/git/commits",
                     {"message": last_msg, "tree": tree["sha"], "parents": [base_sha]})
    if "sha" not in new_commit:
        print("commit 创建失败:", new_commit)
        return 1
    print("新 commit:", new_commit["sha"][:8])

    upd = api("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}",
              {"sha": new_commit["sha"], "force": False})
    if "object" in upd:
        print("✓ 已快进 refs/heads/main →", new_commit["sha"][:8])
        print("接下来请把本地对齐远端：git fetch origin && git reset --soft origin/main")
        return 0
    print("更新 ref 失败:", upd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
