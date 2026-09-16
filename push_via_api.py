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

**务必带 base_tree 并分批**：早期实现是「不带 base_tree、一次性提交全量快照」，
路径数一过 300 就会撞上 GitHub 的 `We couldn't respond to your request in time`（tree 创建超时）。
现在只提交「真正变化的路径」，且每批 ≤TREE_BATCH 条，用上一批的 tree sha 串成下一批的
base_tree，最终仍得到完整的树。

限制：只做快进（不 force），因此无法用它抹除历史；历史上已含的文件
需要另行用 git filter-repo 清理。

用法：
  python3 push_via_api.py            # 推送（幂等：按远端树 vs 本地文件比对）
  python3 push_via_api.py --check    # 与远端对账：比对内容（tree），见 check() 注释
"""

import base64
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "chenluo951-oss/lawdatify-site"
BRANCH = "main"
TREE_BATCH = 120      # 单次 POST /git/trees 的路径上限（超了会被 GitHub 判超时）
TREE_RETRY = 3
BLOB_RETRY = 3        # 建 blob 的重试次数（见 api_retry 注释：沙箱代理会间歇性空响应）


def api_retry(method, path, data=None, attempts=BLOB_RETRY, label=""):
    """带重试的 api() 调用。

    ⚠️ 为什么建 blob 也要重试（2026-09-16 实测）：本机出站代理会**间歇性**返回空响应
    `{'_err': '', '_stderr': ''}`，与文件体积无关 —— 实测同一批里 0.5MB 甚至 0.0MB 的文件
    会失败，而 2MB 的正常通过。批量推送动辄上百个 blob，不做重试就会有几十个路径静默落空、
    整次提交只上线一半（表现为「远端 tree 对不上」）。
    重试是安全幂等的：POST /git/blobs 重复创建同一内容只会得到同一个 sha。
    """
    r = {}
    for i in range(attempts):
        r = api(method, path, data)
        if isinstance(r, dict) and "sha" in r:
            return r
        if "_err" not in r:
            return r          # 是明确的业务错误（如 422），重试无意义，交给调用方处理
        if i < attempts - 1:
            print(f"    ↳ {label} 第 {i + 1} 次网络空响应，重试…")
            time.sleep(1.5 * (i + 1))
    return r


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


# --- 与远端对账（--check）------------------------------------------------
# 为什么不做「历史对齐」：API 推送产生的 commit 在 GitHub 侧生成，其**对象字节无法可靠还原**
# ——实测按 tree/parent/author/committer/message 逐字节重建，sha 仍不相等（GitHub 的服务端
# 身份与消息规范化不可见），因此本地 ref 与远端不可能自动重合。
# 正确的同步判据是**内容**而不是 commit sha：
#   --check  比对「远端 HEAD 的 tree」与「本地 HEAD 的 tree」，一致即视为已同步（退出码 0/1），
#            并把 refs/remotes/origin/<br> 指向远端 HEAD，让 git status 反映真实关系。
# 以后网络恢复时，`git fetch && git reset --soft origin/main` 可一次性把 sha 也对齐。


def _remote_head():
    ref = api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
    if "object" not in ref:
        print("无法获取远端 ref:", str(ref)[:200])
        return None
    return ref["object"]["sha"]


def remote_tree(sha):
    return (api("GET", f"/repos/{REPO}/git/commits/{sha}").get("tree") or {}).get("sha")


def check():
    head = _remote_head()
    if not head:
        return 1
    rt = remote_tree(head)
    if not rt:
        print("取远端 tree 失败")
        return 1
    git("update-ref", f"refs/remotes/origin/{BRANCH}", head)
    # ⚠️ 必须用「索引树」而不是 `HEAD^{tree}` 来比对。
    # 本脚本发布的是**当前工作区内容**（走 API 建 blob，不产生本地 commit），
    # 所以本地 HEAD 永远落后于远端、`HEAD^{tree}` 恒不相等 → 用它会得到「永远误报不一致」。
    # 索引树才是本次推送真正对齐的那棵树；先 `git add -A` 让索引 == 工作区。
    git("add", "-A")
    lt = git("write-tree").strip()
    print(f"远端 {head[:8]} tree {rt[:8]} ｜ 本地索引 tree {lt[:8]}")
    if rt == lt:
        print("✓ 内容一致：线上 == 本地（commit sha 不同是 API 推送的已知副作用，不影响上线）")
        return 0
    print("✗ 内容不一致：本地有未推送的改动，请重跑推送后再核")
    return 1


def main():
    status = git("status", "-sb").splitlines()[0]
    print("当前分支状态:", status)
    # 先把工作区同步进索引：脚本按「索引里的路径 + 工作区的内容」建 blob，
    # 索引落后会让索引 sha 与实际上传内容不一致，进而让 --check 误报。
    git("add", "-A")
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

    # 只发布「git 已跟踪」的文件：语料库、私有文档、本地产物一律不外传
    # （os.walk 会把 gitignore 的 4000+ 语料库文件也算进来，进而触发沙箱敏感内容拦截）
    raw = subprocess.run(["git", "-C", HERE, "ls-files", "-s", "-z"],
                         capture_output=True).stdout.decode("utf-8", "surrogateescape")
    local_entries = []          # (mode, blob_sha, path)
    for rec in raw.split("\0"):
        if not rec:
            continue
        meta, tab, path = rec.partition("\t")
        if not tab:
            continue
        parts = meta.split()
        if len(parts) < 2:
            continue
        mode, sha = parts[0], parts[1]
        if mode not in ("100644", "100755"):
            continue
        local_entries.append((mode, sha, path))
    print(f"本地跟踪文件 {len(local_entries)} 个")

    remote_map = {t["path"]: t["sha"] for t in remote.get("tree", [])
                  if t.get("type") == "blob"}
    local_paths = {p for _, _, p in local_entries}

    tree_entries = []           # 只放「变化」的路径：删除 + 新增/改写
    to_delete = sorted(set(remote_map) - local_paths)
    for rel in to_delete:
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": None})

    # blob sha 相同 = 内容一致 → 远端树里本来就有，交给 base_tree 继承，不进本次请求
    reused = changed = failed = 0
    for mode, sha, path in sorted(local_entries, key=lambda x: x[2]):
        if remote_map.get(path) == sha:
            reused += 1
            continue
        full = os.path.join(HERE, path)
        size = os.path.getsize(full)
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        blob = api_retry("POST", f"/repos/{REPO}/git/blobs",
                         {"content": content, "encoding": "base64"}, label=path)
        if "sha" not in blob:
            # ⚠️ 这里是**静默损坏**的高发点：GitHub 建 blob 对单文件体积敏感，
            # 超限时只返回 {'_err': '', '_stderr': ''}，不报错、不带原因。
            # 若失败路径仍写进新树，就会出现「页面已上线、数据文件 404」。
            # 处置：① 大声报出来（含体积）② 不计入本次树（远端保留旧版本，不会损坏）
            # ③ 最后以非 0 退出，让自动化看得见。
            failed += 1
            print(f"  ✗ blob 创建失败（{size/1048576:.1f}MB）{path}")
            print(f"     ↳ 该文件未写入本次提交，远端保留旧版本（不是 404）。"
                  f"单文件过大时请改用切片（tools/split_big_assets.py）或加入 .gitignore。")
            print(f"     原始响应：{blob}")
            continue
        tree_entries.append({"path": path, "mode": mode,
                             "type": "blob", "sha": blob["sha"]})
        changed += 1
    print(f"待写入 {len(tree_entries)} 个路径（删除 {len(to_delete)} / "
          f"新建 blob {changed} / 复用 {reused}）")
    for rel in to_delete[:8]:
        print("    删除:", rel)

    if not tree_entries:
        print("远端已是最新，无需改动。")
        return 0

    # base_tree = 远端 main 的树；分批提交，每批以上一批的结果为新的 base_tree
    commit_obj = api_retry("GET", f"/repos/{REPO}/git/commits/{base_sha}", label="取远端 commit")
    cur_tree = (commit_obj.get("tree") or {}).get("sha")
    if not cur_tree:
        print("无法取得远端 tree:", str(commit_obj)[:200])
        return 1

    for i in range(0, len(tree_entries), TREE_BATCH):
        batch = tree_entries[i:i + TREE_BATCH]
        tree = {}
        for attempt in range(TREE_RETRY):
            tree = api("POST", f"/repos/{REPO}/git/trees",
                       {"base_tree": cur_tree, "tree": batch})
            if "sha" in tree:
                break
            print(f"  建 tree 第 {attempt + 1} 次失败，重试… {str(tree)[:140]}")
        if "sha" not in tree:
            print("tree 创建失败:", tree)
            return 1
        cur_tree = tree["sha"]
        print(f"  已提交 {min(i + TREE_BATCH, len(tree_entries))}/"
              f"{len(tree_entries)} 条路径 → tree {cur_tree[:8]}")
    tree = {"sha": cur_tree}

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
        # 让本地也知道远端真实位置（否则 git status 永远显示 ahead，且与远端 sha 不符）
        git("update-ref", f"refs/remotes/origin/{BRANCH}", new_commit["sha"])
        print("已更新 refs/remotes/origin/main；内容对账请跑 --check")
        if failed:
            print(f"⚠️ 有 {failed} 个文件因体积超限未推送（远端保留旧版本）。"
                  f"本次提交成功，但请处置后再跑一次，否则该文件长期停留在旧版本。")
            return 1
        return 0
    print("更新 ref 失败:", upd)
    return 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    sys.exit(main())
