#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页内联脚本语法自检 —— 用 node --check 逐块校验，抓「整页 JS 被截断」这类致命错误。

为什么需要它
------------
2026-09-17 的故障：unify_chrome.py 往页面注入法条悬浮卡脚本时，用的是
「替换**第一个** </body>」。而 kb/texts.html / manage/audit.html 里，
**第一个 `</body>` 出现在内联 `<script>` 的 JS 字符串字面量里**
（Word 导出模板 `'</body></html>'`）。于是注入的标签连同自带的 `</script>`
一起插进了字符串中间 —— HTML 解析器在 JS 字符串中途就闭合了整段内联脚本，
剩下的代码成了语法错误，**整页 JS 全死**（原文库列表空白、点「读原文」无反应）。

这类故障页面「HTTP 200、HTML 结构正常、preflight 现有 A/B/C/D 全过」，
只有真的解析一遍 JS 才能发现。所以用 node --check 逐块过一遍。

用法
----
    python3 tools/js_syntax_check.py            # 全站（PAGES 清单）
    python3 tools/js_syntax_check.py kb/texts.html
退出码非 0 表示存在语法错误（preflight 会据此报错）。
"""

import os
import re
import subprocess
import sys
import tempfile

try:
    from _stash import stash          # 直接运行 tools/xxx.py 时，本目录在 sys.path[0]
except ImportError:                   # 被当包导入时
    from tools._stash import stash

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

NODE = "/Users/luochen/.workbuddy/binaries/node/versions/22.22.2-2/bin/node"

# 内联脚本：只取没有 src 属性的 <script>…</script>
SCRIPT_RE = re.compile(r'<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>', re.S | re.I)


def pages():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "uc", os.path.join(HERE, "unify_chrome.py"))
        uc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(uc)
        return list(uc.PAGES)
    except Exception:
        out = []
        for dirpath, _dirs, files in os.walk(HERE):
            if any(x in dirpath for x in ('.git', '_qa', 'node_modules', 'sources')):
                continue
            for f in files:
                if f.endswith('.html'):
                    out.append(os.path.relpath(os.path.join(dirpath, f), HERE))
        return sorted(out)


def check_page(rel):
    """返回 [(块序号, 首行, 错误信息)]"""
    path = os.path.join(HERE, rel)
    if not os.path.exists(path):
        return None
    s = open(path, encoding="utf-8").read()
    bad = []
    blocks = 0
    for i, m in enumerate(SCRIPT_RE.finditer(s), 1):
        attrs, code = m.group(1) or "", m.group(2) or ""
        if re.search(r'type\s*=\s*["\']?(?!text/javascript|module)', attrs, re.I):
            continue          # JSON-LD 之类不是 JS
        if not code.strip():
            continue
        blocks += 1
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(code)
            tmp = fh.name
        try:
            r = subprocess.run([NODE, "--check", tmp], capture_output=True, text=True,
                               timeout=60)
            if r.returncode != 0:
                err = (r.stderr or "").strip().splitlines()
                # node --check 输出形如：<路径>:435 / 代码行 / ^ / SyntaxError: …
                # 真正有用的是最后那行「XXXError: 说明」，不能取首行（首行是路径）。
                msg = next((x.strip() for x in err
                            if re.match(r'^[A-Za-z]*Error:', x.strip())), '')
                if not msg:
                    msg = next((x.strip() for x in err if x.strip() and tmp not in x), '')
                where = next((x for x in err if tmp in x), '')
                line = ''
                mm = re.search(r':(\d+)\s*$', where.strip())
                if mm:
                    line = f'（脚本第 {mm.group(1)} 行）'
                bad.append((i, line, (msg or '未知错误')[:150]))
        finally:
            stash(tmp)
    return blocks, bad


def main():
    args = [a for a in sys.argv[1:]]
    rels = args or pages()
    total_bad = 0
    print(f"页内联脚本语法自检：{len(rels)} 个页面")
    for rel in rels:
        r = check_page(rel)
        if r is None:
            print(f"  {rel:<28} 跳过（不存在）")
            continue
        blocks, bad = r
        if bad:
            total_bad += len(bad)
            print(f"  ✗ {rel:<28} {blocks} 块，语法错误 {len(bad)} 处")
            for i, line, msg in bad[:4]:
                print(f"      第 {i} 块{line}：{msg}")
        else:
            print(f"  ✓ {rel:<28} {blocks} 块全部通过")
    print(f"\n{'✗' if total_bad else '✓'} 合计语法错误 {total_bad} 处")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
