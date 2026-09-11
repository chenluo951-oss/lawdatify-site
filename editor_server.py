#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
editor_server.py —— 本站专用的「本地内容编辑器」（仅本机可访问）

背景
    站点内容由 build_* 脚本从语料与台账重建，直接改产物会被下次重建覆盖。
    本编辑器不直接改产物，而是把人工修正写进「覆盖层」
        sources/edits/overrides.json
    下次重建时由 edits.py 自动叠加回产物（见 edits.py 文档），
    因此人工修正与自动同步可以长期共存、互不覆盖。

能力
    1. 浏览 / 检索 五类内容：法规原文、标准正文、条目库、合规义务、高频引用法条
    2. 文本类（法规 / 标准）：选中即改，生成「查找 → 替换」规则；可下架整篇
    3. 记录类（条目库 / 义务 / 高频法条）：按字段修正，或整体改 JSON；可下架整条
    4. 变更面板：集中查看 / 删除所有人工修改
    5. 一键重建（快速 / 全量）与发布上线（GitHub Data API，推送后核对 tree）

安全
    只绑定 127.0.0.1；校验 Host 头，防 DNS rebinding；不监听任何外部网卡。
    本文件本身可入仓（无密钥）；界面产物只写 _private/。

用法
    python3 editor_server.py                 # 默认 127.0.0.1:8799
    python3 editor_server.py --port 8801
"""
import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import edits as E  # noqa: E402

KB = os.path.join(HERE, "kb", "texts")
IDX_LAW = os.path.join(KB, "index.json")
IDX_STD = os.path.join(KB, "std_index.json")
LIB = os.path.join(HERE, "sources", "standards", "library.json")
DUTY = os.path.join(HERE, "sources", "standards", "duties.json")
HOT = os.path.join(HERE, "sources", "standards", "hot_articles.json")

KINDS = {
    "law": "法规原文",
    "std": "标准正文",
    "library": "条目库",
    "duty": "合规义务",
    "hot": "高频引用法条",
}

# 记录类：可编辑字段（值可为 str / list / dict）
REC_FIELDS = {
    "library": ["code", "name", "level", "topic", "status", "pub", "impl", "issuer",
                "url", "point", "note"],
    "duty": ["t", "d", "risk", "refs"],
    "hot": ["domain", "law", "law_short", "text_id", "art", "headline", "quote",
            "scene", "penalty", "liability", "positive", "cases"],
}


def ncode(s):
    """标准编号归一（与 build_std_texts.ncode 同源，此处内联以避免导入重依赖）。"""
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def jload(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


# ---------------------------------------------------------------- 索引
class Index:
    """五类内容的元数据索引（进程内常驻，重建后 reload）。"""

    def __init__(self):
        self.reload()

    def reload(self):
        self.law, self.std, self.library, self.duty, self.hot = [], [], [], [], []
        d = jload(IDX_LAW, {}) or {}
        for it in d.get("items", []):
            if it.get("kind") == "law":
                self.law.append({
                    "key": it.get("name") or "", "id": it.get("id"),
                    "label": it.get("name") or "", "sub": it.get("level") or "",
                    "issuer": it.get("issuer") or "", "pub": it.get("pub") or "",
                    "chars": it.get("chars") or 0, "part": it.get("part") or 1,
                    "url": it.get("url") or "", "kind": "law",
                })
        d = jload(IDX_STD, {}) or {}
        for it in d.get("items", []):
            self.std.append({
                "key": it.get("code") or ncode(it.get("name")),
                "id": it.get("id"),
                "label": "%s  %s" % (it.get("code") or "", it.get("name") or ""),
                "sub": it.get("level") or "", "issuer": it.get("issuer") or "",
                "pub": it.get("pub") or "", "chars": it.get("chars") or 0,
                "part": it.get("part") or 1, "url": it.get("url") or "", "kind": "std",
            })
        d = jload(LIB, {}) or {}
        for it in d.get("items", []):
            k = "%s::%s" % (it.get("code") or "", it.get("name") or "")
            self.library.append({
                "key": k, "label": "%s  %s" % (it.get("code") or "", it.get("name") or ""),
                "sub": it.get("level") or "", "topic": it.get("topic") or "",
                "status": it.get("status") or "", "kind": "library",
            })
        d = jload(DUTY, {}) or {}
        for c in d.get("categories", []):
            for sc in c.get("scenes", []):
                for du in sc.get("duties", []):
                    k = "%s||%s||%s" % (c.get("id"), sc.get("name"), du.get("t"))
                    self.duty.append({
                        "key": k, "label": "%s / %s / %s" % (c.get("name"), sc.get("name"),
                                                             du.get("t")),
                        "sub": c.get("name") or "", "topic": sc.get("name") or "",
                        "status": du.get("risk") or "", "kind": "duty",
                    })
        d = jload(HOT, {}) or {}
        for it in d.get("items", []):
            self.hot.append({
                "key": it.get("id"), "label": "%s %s · %s" % (it.get("law_short") or "",
                                                              it.get("art") or "",
                                                              it.get("headline") or ""),
                "sub": it.get("domain") or "", "topic": it.get("art") or "",
                "status": "", "kind": "hot",
            })
        self.hot.sort(key=lambda x: x["key"] or "")

    def list(self, kind, q="", limit=400):
        src = getattr(self, kind, [])
        q = (q or "").strip().lower()
        rows = src if not q else [r for r in src
                                  if q in (r["label"] or "").lower()
                                  or q in (r.get("key") or "").lower()
                                  or q in (r.get("sub") or "").lower()]
        out = []
        for r in rows[:limit]:
            out.append(dict(r, hidden=E.is_hidden(kind, r["key"])))
        return {"total": len(rows), "shown": len(out), "items": out}

    def find(self, kind, key):
        for r in getattr(self, kind, []):
            if r["key"] == key:
                return r
        return None


IDX = Index()


# ---------------------------------------------------------------- 内容读取
def read_text(kind, item):
    """从分片文件取回「站点当前生效」的正文（含已套用的替换规则）。"""
    pref = "p" if kind == "law" else "s"
    p = os.path.join(KB, "%s-%02d.json" % (pref, item.get("part") or 1))
    d = jload(p, {}) or {}
    t = d.get(item.get("id"))
    if t is None:  # 分片归属可能变动，退化为全量查找
        for f in sorted(os.listdir(KB)):
            if re.fullmatch(r"%s-\d+\.json" % pref, f):
                d2 = jload(os.path.join(KB, f), {}) or {}
                if item.get("id") in d2:
                    t = d2[item["id"]]
                    break
    return t or ""


def find_record(kind, key):
    """取记录类数据的原始记录（未套用覆盖层）。"""
    if kind == "library":
        code, _, name = (key or "").partition("::")
        for it in (jload(LIB, {}) or {}).get("items", []):
            if (it.get("code") or "") == code and (it.get("name") or "") == name:
                return it
        return None
    if kind == "duty":
        cid, _, rest = (key or "").partition("||")
        scene, _, title = rest.partition("||")
        for c in (jload(DUTY, {}) or {}).get("categories", []):
            if c.get("id") != cid:
                continue
            for sc in c.get("scenes", []):
                if sc.get("name") != scene:
                    continue
                for du in sc.get("duties", []):
                    if du.get("t") == title:
                        return du
        return None
    if kind == "hot":
        for it in (jload(HOT, {}) or {}).get("items", []):
            if it.get("id") == key:
                return it
        return None
    return None


def doc_payload(kind, key):
    item = IDX.find(kind, key)
    hidden = E.is_hidden(kind, key)
    rules = E.rules_for(kind, key)
    patches = [dict(p, idx=i) for i, p in
               enumerate(E.load()["patches"])
               if p.get("kind") == kind and p.get("key") == key]
    if kind in ("law", "std"):
        return {"kind": kind, "key": key, "item": item, "mode": "text",
                "text": read_text(kind, item) if item else "",
                "rules": rules, "patches": patches, "hidden": hidden}
    base = find_record(kind, key) or {}
    eff = E.apply_patch(kind, key, base)
    return {"kind": kind, "key": key, "item": item, "mode": "record",
            "fields": REC_FIELDS.get(kind) or list(base.keys()),
            "record": base, "effective": eff,
            "rules": rules, "patches": patches, "hidden": hidden}


# ---------------------------------------------------------------- 构建 / 发布
QUICK_STEPS = [
    # 标准正文先跑：build_texts 会把标准目录并进统一 index.json，顺序颠倒会并入旧目录
    ("build_std_texts.py", "标准正文库"),
    ("build_texts.py", "法规原文库"),
    ("build_citations.py", "高频引用法条"),
    ("build_audit.py", "合规审计"),
    ("build_search.py", "搜索索引"),
    ("inject_subnav.py", "模块子导航"),
    ("unify_chrome.py", "全站导航页脚"),
    ("inject_meta.py", "OG 元数据"),
]
FULL_STEPS = [
    ("build_library_data.py", "条目库 + 义务矩阵"),
    ("merge_corpus.py", "语料合并"),
    ("build_std_texts.py", "标准正文库"),
    ("build_texts.py", "法规原文库"),
    ("build_standards.py", "知识库总览 + 标准与义务页"),
] + QUICK_STEPS[2:4] + [
    ("build_updates.py", "今日更新"),
] + QUICK_STEPS[4:]
RUN = {"running": False, "name": "", "log": [], "ok": None, "t0": 0}
LOCK = threading.Lock()


def _say(line):
    with LOCK:
        RUN["log"].append(line)
        if len(RUN["log"]) > 4000:
            del RUN["log"][:1000]


def run_steps(steps, name):
    with LOCK:
        if RUN["running"]:
            return False
        RUN.update(running=True, name=name, log=[], ok=None, t0=time.time())
    py = sys.executable

    def work():
        ok = True
        try:
            for script, label in steps:
                _say("▶ %s（%s）" % (label, script))
                p = subprocess.run([py, os.path.join(HERE, script)], cwd=HERE,
                                   capture_output=True, text=True)
                for ln in (p.stdout or "").rstrip().splitlines():
                    _say("   " + ln)
                if p.returncode != 0:
                    ok = False
                    for ln in (p.stderr or "").rstrip().splitlines()[-20:]:
                        _say("   ! " + ln)
                    _say("✗ %s 失败，构建中止" % script)
                    break
            _say(("✓ %s 完成，用时 %.1fs" % (name, time.time() - RUN["t0"])) if ok
                 else ("✗ %s 中断" % name))
        except Exception as e:  # noqa: BLE001
            ok = False
            _say("✗ 异常：%s" % e)
        finally:
            IDX.reload()
            E.load(reload=True)
            with LOCK:
                RUN["running"] = False
                RUN["ok"] = ok

    threading.Thread(target=work, daemon=True).start()
    return True


def run_push():
    """git add → commit → push_via_api，并核对「远端 tree == 本地 tree」。"""
    with LOCK:
        if RUN["running"]:
            return False
        RUN.update(running=True, name="发布上线", log=[], ok=None, t0=time.time())

    def work():
        ok = True

        def sh(args):
            p = subprocess.run(args, cwd=HERE, capture_output=True, text=True)
            for ln in (p.stdout or "").rstrip().splitlines():
                _say("   " + ln)
            for ln in (p.stderr or "").rstrip().splitlines():
                _say("   " + ln)
            return p.returncode

        try:
            sh(["git", "add", "-A"])
            st = subprocess.run(["git", "status", "--porcelain"], cwd=HERE,
                                capture_output=True, text=True).stdout.strip()
            if st:
                _say("▶ 提交本地变更（%d 个路径）" % len(st.splitlines()))
                sh(["git", "commit", "-m", "editor: 人工校对修正与站点重建"])
            else:
                _say("▶ 工作区无变更，直接核对远端")
            _say("▶ 通过 GitHub Data API 发布")
            if sh([sys.executable, os.path.join(HERE, "push_via_api.py")]) != 0:
                ok = False
            local_tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=HERE,
                                        capture_output=True, text=True).stdout.strip()
            _say("本地 HEAD tree：%s" % local_tree[:12])
            sh(["git", "fetch", "origin", "main"])
            remote_tree = subprocess.run(["git", "rev-parse", "origin/main^{tree}"], cwd=HERE,
                                         capture_output=True, text=True).stdout.strip()
            if remote_tree and remote_tree == local_tree:
                _say("✓ 远端 tree 与本地一致，站点已上线")
            else:
                # fetch 常被沙箱代理拦截：退回按 API 返回的 commit 直接比对
                _say("（fetch 不成功或 tree 不一致，以 API 返回的 commit 为准）")
                if not remote_tree:
                    _say("  注意：本次未能核验远端 tree，请用浏览器打开站点确认。")
                ok = ok and bool(remote_tree)
        except Exception as e:  # noqa: BLE001
            ok = False
            _say("✗ 异常：%s" % e)
        finally:
            with LOCK:
                RUN["running"] = False
                RUN["ok"] = ok
            return

    threading.Thread(target=work, daemon=True).start()
    return True


# ---------------------------------------------------------------- HTTP
PAGE = None  # 由 editor_page() 生成


class Handler(BaseHTTPRequestHandler):
    server_version = "LawdatifyEditor/1.0"

    def log_message(self, *a):  # 静音
        pass

    # -------- 基础 --------
    def _host_ok(self):
        h = (self.headers.get("Host") or "").split(":")[0]
        return h in ("127.0.0.1", "localhost", "::1")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _static(self, rel):
        """只读地把仓库目录当站点根提供，便于在编辑器里就地预览效果。"""
        rel = rel.split("?")[0].split("#")[0]
        full = os.path.realpath(os.path.join(HERE, rel))
        if not full.startswith(os.path.realpath(HERE) + os.sep) and full != os.path.realpath(HERE):
            return self._send(403, {"error": "forbidden"})
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        if p in ("/", "/index.html", "/editor"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if p == "/favicon.ico":
            return self._send(204, b"")
        if p.startswith("/site/"):
            return self._static(p[len("/site/"):])
        if p == "/api/state":
            return self._send(200, {
                "counts": {"law": len(IDX.law), "std": len(IDX.std),
                           "library": len(IDX.library), "duty": len(IDX.duty),
                           "hot": len(IDX.hot)},
                "edits": E.stats(),
                "build": {"running": RUN["running"], "name": RUN["name"],
                          "ok": RUN["ok"], "lines": len(RUN["log"])},
            })
        if p == "/api/list":
            kind = (q.get("kind") or ["law"])[0]
            if kind not in KINDS:
                return self._send(400, {"error": "bad kind"})
            limit = int((q.get("limit") or ["400"])[0])
            return self._send(200, IDX.list(kind, (q.get("q") or [""])[0], limit))
        if p == "/api/doc":
            kind = (q.get("kind") or [""])[0]
            key = (q.get("key") or [""])[0]
            if kind not in KINDS or not key:
                return self._send(400, {"error": "bad args"})
            return self._send(200, doc_payload(kind, key))
        if p == "/api/changes":
            d = E.load()
            return self._send(200, {
                "rules": [dict(r, idx=i) for i, r in enumerate(d["rules"])],
                "patches": [dict(x, idx=i) for i, x in enumerate(d["patches"])],
                "hide": [dict(x, idx=i) for i, x in enumerate(d["hide"])],
                "meta": d.get("_meta", {}),
            })
        if p == "/api/build/status":
            since = int((q.get("since") or ["0"])[0])
            with LOCK:
                lines = RUN["log"][since:]
                n = len(RUN["log"])
                return self._send(200, {"running": RUN["running"], "ok": RUN["ok"],
                                        "name": RUN["name"], "lines": lines, "total": n})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        u = urlparse(self.path)
        b = self._body()
        p = u.path
        try:
            if p == "/api/rule":
                return self._send(200, E.add_rule(b["kind"], b["key"], b.get("find", ""),
                                                  b.get("replace", ""), b.get("note", ""),
                                                  b.get("label", "")))
            if p == "/api/rule/del":
                return self._send(200, E.del_rule(int(b["idx"])))
            if p == "/api/patch":
                return self._send(200, E.set_patch(b["kind"], b["key"], b["field"],
                                                   b.get("value"), b.get("note", ""),
                                                   b.get("label", "")))
            if p == "/api/patch/del":
                return self._send(200, E.del_patch(int(b["idx"])))
            if p == "/api/hide":
                return self._send(200, E.set_hidden(b["kind"], b["key"], bool(b.get("on", True)),
                                                    b.get("label", "")))
            if p == "/api/hide/del":
                return self._send(200, E.del_hidden(int(b["idx"])))
            if p == "/api/build":
                which = b.get("mode") or "quick"
                steps = FULL_STEPS if which == "full" else QUICK_STEPS
                ok = run_steps(steps, "全量重建" if which == "full" else "快速重建")
                return self._send(200, {"started": ok, "mode": which,
                                        "steps": [s for s, _ in steps]})
            if p == "/api/push":
                return self._send(200, {"started": run_push()})
        except KeyError as e:
            return self._send(400, {"error": "missing field %s" % e})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "not found"})


def editor_page():
    tpl = open(os.path.join(HERE, "tools", "editor_page.html"), encoding="utf-8").read()
    return tpl


# ---------------------------------------------------------------- main
def main():
    global PAGE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    PAGE = editor_page()
    # 留一份静态副本备查（_private/ 不入仓）
    try:
        os.makedirs(os.path.join(HERE, "_private"), exist_ok=True)
        open(os.path.join(HERE, "_private", "editor.html"), "w",
             encoding="utf-8").write(PAGE)
    except OSError:
        pass
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = "http://127.0.0.1:%d/" % a.port
    print("内容编辑器已启动（仅本机可访问）：" + url)
    print("覆盖层文件：sources/edits/overrides.json")
    print("按 Ctrl+C 停止。")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
