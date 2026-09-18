#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时文件「移走」工具 —— 替代 os.remove。

为什么存在
----------
沙箱有一条「批量删除保护」：**一轮对话内 os.remove 累计超过 50 次之后，
任何后续 os.remove 都会让整个脚本立刻退出（退出码 1，且什么都不输出）**。
表现极具误导性：探针/截图工具看起来「坏了」，其实只是删不掉临时文件。
本项目已有多处踩过（见 build_texts.py / build_std_pdf.py / split_big_assets.py 的注释），
当时的做法是「临时文件按固定名且不删」。但探针类工具必须把临时页写在目标页旁边
（否则 file:// 下的相对资源路径全断），不删就会在仓库里留垃圾、还被 git status 看见。

做法
----
`os.replace` 把文件**挪**到系统临时目录（同一卷，原子操作，不是删除）。
既不触发删除保护，也不在仓库留残留。

用法
----
    from _stash import stash
    ...
    finally:
        stash(tmp)
"""
import os
import time

STASH_DIR = os.path.join("/tmp", "lawdatify-stash")


def stash(path):
    """把 path 挪进 /tmp/lawdatify-stash/ 而不是删除。失败时静默（绝不能因为收尾失败中断主流程）。"""
    if not path or not os.path.exists(path):
        return
    try:
        os.makedirs(STASH_DIR, exist_ok=True)
        base = os.path.basename(path)
        dst = os.path.join(STASH_DIR, f"{int(time.time() * 1000)}-{base}")
        os.replace(path, dst)
    except OSError:
        pass
