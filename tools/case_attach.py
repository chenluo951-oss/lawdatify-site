#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""处罚公示页的**文书附件**解析（Word / PDF / Excel）。

为什么必须有它
--------------
各地市监局、法院、部委的「行政处罚公示」详情页有相当一部分是**空壳页**：
网页正文只有标题 + 附件下载链接，处罚事实、依据、罚款金额全在附件里。
实测（2026-09-17）：
  · 青岛市局「处罚文书送达公告」→ 页面正文 0 字，3 个 .docx/.xls 附件
  · 泸州市局「行政处罚决定书」  → 页面正文只有案由一句，决定书正文在 .pdf 里
不解析附件，这两类站点的「处罚事由 / 依据 / 罚款」三列必然全空，
页面上就会出现用户看到的「事由：见原文」「主体：—」。

能力边界（按格式分派，别乱猜）
--------------------------
| 格式          | 魔数/判据        | 解析器                                  |
|---------------|------------------|-----------------------------------------|
| PDF 带文字层  | `%PDF`           | pymupdf(fitz) → 退化 pdfplumber → pypdf  |
| PDF 扫描件    | `%PDF` 且取不到字 | 无（宁留空，不塞 OCR 错字）             |
| DOCX          | `PK` + word/     | python-docx（段落 + 表格）              |
| XLSX          | `PK` + xl/       | openpyxl（逐 sheet 逐行）               |
| DOC / XLS(旧) | `\\xd0\\xcf\\x11\\xe0`   | macOS `textutil`（零依赖）              |
| 其它          | —                | 跳过并记一条原因                        |

⚠️ 附件 URL 常常是**相对路径**（`./P0202609...docx`），必须 urljoin 补全。
⚠️ 部分政务站下载附件要求带 Referer（本模块默认把详情页 URL 当 Referer 传）。
⚠️ 只读不写：附件一律下到临时目录，不落进站点仓库（避免仓库体积与版权问题）。
"""
import os
import re
import subprocess
import sys
import tempfile
from html import unescape
from urllib.parse import urljoin

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 附件链接：按扩展名 + 政务站惯用的 appendix/attachment 标记两条线找
_EXT = r"(?:pdf|docx?|xlsx?|wps|et|ofd|rtf)"
_ATTR = re.compile(
    r"<a\b[^>]*?(?:appendix|attachment|data-appendix)[^>]*>|<a\b[^>]*?href=\"[^\"]*\.(?:%s)(?:\?[^\"]*)?\"[^>]*>" % _EXT,
    re.I)
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_TITLE = re.compile(r"""title\s*=\s*["']([^"']{2,120})["']""", re.I)
_ANCHOR_TEXT = re.compile(r">([^<]{2,160})<")


def _hdr(referer):
    h = ["-A", UA, "-H", "Accept-Language: zh-CN,zh;q=0.9"]
    if referer:
        h += ["-H", "Referer: " + referer]
    return h


def attach_links(html, page_url):
    """返回 [(绝对URL, 文件名)]，按页面出现顺序去重。"""
    out, seen = [], set()
    for m in _ATTR.finditer(html or ""):
        tag = m.group(0)
        hm = _HREF.search(tag)
        if not hm:
            continue
        href = unescape(hm.group(1)).strip()
        if href.lower().startswith(("javascript:", "#", "mailto:")):
            continue
        ext = re.search(r"\.(%s)(?:\?|$)" % _EXT, href, re.I)
        if not ext:
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        name = ""
        tm = _TITLE.search(tag)
        if tm:
            name = unescape(tm.group(1)).strip()
        if not name:
            am = _ANCHOR_TEXT.search(tag)
            if am:
                name = unescape(am.group(1)).strip()
        if not name:
            name = os.path.basename(url.split("?")[0])
        out.append((url, name))
    return out


def fetch(url, referer=None, timeout=45, tries=2):
    """下载到内存（bytes）。返回 (bytes, err)。"""
    last = ""
    for _ in range(tries):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
            tmp = tf.name
        try:
            cmd = ["curl", "-sL", "-m", str(timeout), "-o", tmp,
                   "-w", "%{http_code}"] + _hdr(referer) + [url]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
            code = (r.stdout or "").strip()[-3:]
            if code == "200":
                with open(tmp, "rb") as f:
                    return f.read(), ""
            last = "http=" + (code or "000")
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return b"", last


# ── 各格式解析 ──────────────────────────────────────────────

def _pdf_text(b):
    """PDF 取文字层。三级退化；取不到就认了（宁留空不塞 OCR 错字）。"""
    txt = ""
    try:
        # pymupdf 新版把入口改成 `pymupdf`，旧的 `fitz` 会打 FutureWarning
        try:
            import pymupdf as _pdf
        except ImportError:
            import fitz as _pdf
        with _pdf.open(stream=b, filetype="pdf") as d:
            txt = "\n".join(pg.get_text("text") for pg in d)
    except Exception:  # noqa: BLE001
        txt = ""
    if len(re.sub(r"\s", "", txt)) >= 20:
        return txt
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(b)) as d:
            t2 = "\n".join((p.extract_text() or "") for p in d.pages)
        if len(re.sub(r"\s", "", t2)) >= 20:
            return t2
    except Exception:  # noqa: BLE001
        pass
    try:
        import io
        from pypdf import PdfReader
        t3 = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(b)).pages)
        if len(re.sub(r"\s", "", t3)) >= 20:
            return t3
    except Exception:  # noqa: BLE001
        pass
    return txt


def _docx_text(b):
    import io
    import docx
    d = docx.Document(io.BytesIO(b))
    parts = [p.text for p in d.paragraphs]
    for tb in d.tables:                      # 决定书常把「当事人/事实/依据」放在表里
        for row in tb.rows:
            cells = [c.text.strip() for c in row.cells]
            # 合并单元格会让同一段文字重复出现，逐行去重
            uniq = []
            for c in cells:
                if c and (not uniq or uniq[-1] != c):
                    uniq.append(c)
            if uniq:
                parts.append(" ｜ ".join(uniq))
    return "\n".join(x for x in parts if x and x.strip())


def _xlsx_text(b):
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append("【" + (ws.title or "sheet") + "】")
        for row in ws.iter_rows(values_only=True):
            cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
            if cells:
                parts.append(" ｜ ".join(cells))
    try:
        wb.close()
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


def _xls_text(b):
    """旧版 .xls（OLE2/BIFF）：textutil **不支持** Excel，必须走 xlrd。

    实测青岛市局「拟吊销营业执照的企业名单.xls」是 OLE2 的 BIFF8，
    textutil 转出来是空串 → 名单式附件全丢。xlrd 2.x 只读 .xls，正好。
    """
    import io
    import xlrd
    bk = xlrd.open_workbook(file_contents=b)
    parts = []
    for sh in bk.sheets():
        parts.append("【" + (sh.name or "sheet") + "】")
        for i in range(sh.nrows):
            cells = []
            for v in sh.row_values(i):
                s = str(v).strip()
                if s and s != "0.0":
                    cells.append(s)
            if cells:
                parts.append(" ｜ ".join(cells))
    return "\n".join(parts)


def _ole_text(b, suffix):
    """旧版 .doc/.xls：.xls 走 xlrd，.doc 交给 textutil（macOS 内置，零依赖）。"""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(b)
        p = tf.name
    try:
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", p],
                           capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass


def _is_zip(b):
    return b[:2] == b"PK"


def _is_ole(b):
    return b[:4] == b"\xd0\xcf\x11\xe0"


def parse_bytes(b, name=""):
    """按**魔数**分派解析器（不信扩展名——实测有 OLE2 的 .doc 挂着 .docx 名）。"""
    if not b or len(b) < 200:
        return "", "empty"
    low = (name or "").lower()
    if b[:5] == b"%PDF" or low.endswith(".pdf"):
        t = _pdf_text(b)
        return t, ("" if t.strip() else "pdf_no_text_layer")
    if _is_ole(b):
        if re.search(r"\.(xls|et)\b", low) or b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k" in b[:4096]:
            try:
                return _xls_text(b), ""
            except Exception as e:  # noqa: BLE001
                return "", "xls:" + type(e).__name__
        return _ole_text(b, ".doc"), ""
    if _is_zip(b):
        import io
        import zipfile
        try:
            names = zipfile.ZipFile(io.BytesIO(b)).namelist()
        except Exception:  # noqa: BLE001
            return "", "zip_broken"
        if any(n.startswith("xl/") for n in names):
            try:
                return _xlsx_text(b), ""
            except Exception as e:  # noqa: BLE001
                return "", "xlsx:" + type(e).__name__
        if any(n.startswith("word/") for n in names):
            try:
                return _docx_text(b), ""
            except Exception as e:  # noqa: BLE001
                return "", "docx:" + type(e).__name__
        return "", "zip_unknown"
    return "", "unknown_type"


def _lcs_len(a, b):
    """最长公共子串长度（够用即可：附件名与主体名都短，O(n*m) 无压力）。"""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _match_attachments(links, hint):
    """按主体名把附件与记录对上。

    ⚠️ 一个详情页可能挂**多份**决定书：泸州 `content_1156367` 一页挂了两份
    「行政处罚决定书（清幽泉）.pdf」「行政处罚决定书（肖鹏案）.pdf」，采集侧按表行
    把它们拆成了两条记录。若两条都无差别地把两份 PDF 读进来，两条记录会拿到
    **彼此的决定书正文**（内容错配 + 大面积重复）。
    判据：主体名与附件名的最长公共子串 >= min(3, len(主体名))。
    """
    if not hint or len(links) <= 1:
        return links
    thr = min(3, len(hint))
    hits, rest = [], []
    for u, n in links:
        (hits if _lcs_len(hint, n) >= thr else rest).append((u, n))
    # 只有一个附件能对上 → 只用它；多个对得上就都用（一案多份文书）
    return hits if hits else links


_PAGENO = re.compile(r"第\s*\d+\s*页\s*[,，、]?\s*共\s*\d+\s*页|[-—]\s*\d+\s*[-—]\s*$", re.M)
_WS = re.compile(r"[ \t\u3000\u2002\u2003\u00a0\u200b]+")
# 公文页眉/页脚里的固定件：邮箱（政务站常写成 `qdamr#qd.shandong.cn(请将#换成@)`）、
# 地址与电话行、「本文书一式N份」这类套话。
_HEADFOOT = re.compile(
    r"[\w.+-]+\s*(?:@|#)\s*[\w.-]+(?:\.\w{2,6})?(?:\(请将#换成@\)|（请将#换成@）)?|"
    r"请将#换成@|本(?:文书|告知书|决定书)一式[一二三四五六七八九十\d]+份[^。]{0,40}。?|"
    r"(?:联系)?(?:电话|邮箱|传真|地址)\s*[:：]\s*[^\s，。]{0,40}"
)


def clean_attach_text(s, max_chars=900):
    """附件正文的**轻量**清洗。

    ⚠️ 这里绝不能用 `case_text_clean.clean_fact()`：那套规则是为**网页**壳设计的
    （面包屑 / 字号控件 / 附件名列表 / 页脚备案号），套到本地文书上会**吃掉正文**。
    实测青岛一条 docx 文案被 `(?:附件|相关链接)\\s*[:：][^。]{0,120}` 从「附件：拟吊销
    营业执照的企业名单」一路吃到 120 字外，送达公告与告知书两大段全没了，摘要只剩
    「2026年9月4日 本文书一式三份，一份送达，一份归档」。

    只做三件事：去 PDF 页码、压空白、**按段落去重**（一页挂多份文书时内容大量重叠）。
    """
    t = _PAGENO.sub(" ", s or "")
    t = _HEADFOOT.sub(" ", t)
    t = _WS.sub(" ", t)
    # 纯名单表（「序号 ｜ 企业名称 ｜ 统一社会信用代码 ｜ 地址」几十行）当正文没有多少
    # 阅读价值，留着会把「处罚事由」变成一张流水表 → 只留开头几家，正文另有叙述时不触发。
    if re.search(r"(?:序号\s*｜\s*(?:企业名称|当事人)|统一社会信用代码\s*｜)", t):
        t = t[:320]
        max_chars = min(max_chars, 320)
    out, seen = [], set()
    for line in t.split("\n"):
        line = line.strip(" \u2002\u2003\u00a0")
        if not line:
            continue
        k = re.sub(r"\s", "", line)
        # 短行（标题、文号、「当事人：」）允许重复出现；长段重复的只留一次
        if len(k) >= 14:
            if k in seen:
                continue
            seen.add(k)
        out.append(line)
    return " ".join(out)[:max_chars]


def attach_text(page_html, page_url, referer=None, max_files=4, max_chars=6000,
                name_pref=r"处罚|决定书|告知书|裁决|名单", hint="", cache=None):
    """抓详情页的全部文书附件并抽文字。

    hint ：本条记录的主体名（有多个附件时用来挑出属于本条的那份）。
    cache：{附件URL: (正文, 错误)}，同一页拆出多条记录时复用，避免重复下载。
    返回 dict：
      text   合并后的附件正文（按 max_chars 截断）
      links  附件链接列表（绝对 URL，可直接作为「文书原文件」给用户点）
      files  每个附件的解析情况（name / url / ext / chars / err）
    """
    links = attach_links(page_html, page_url)
    if not links:
        return {"text": "", "links": [], "files": []}
    links = _match_attachments(links, hint)
    # 有正式文书时就把「拟吊销企业名单.xls」这类附表摘出去：名单是同一批企业的
    # 名称/统一社会信用代码长表，拼进「处罚事由」只会把公告正文冲成一张表，
    # 对判读「因何事被罚」毫无帮助。没有文书、只有名单时才退而用它。
    docs = [x for x in links if not re.search(r"名单|明细|列表|台账|汇总表", x[1])]
    if docs:
        links = docs
    # 名字像正规文书的排前面（避免先被「附件1：流程图」之类占满额度）
    pref = re.compile(name_pref)
    links.sort(key=lambda x: 0 if pref.search(x[1]) else 1)
    chunks, files = [], []
    used = 0
    for url, name in links[:max_files]:
        if cache is not None and url in cache:
            t, perr = cache[url]
        else:
            b, err = fetch(url, referer=referer or page_url)
            if err:
                t, perr = "", err
            else:
                t, perr = parse_bytes(b, name)
                t = re.sub(r"[ \t\u3000]+", " ", t or "").strip()
            if cache is not None:
                cache[url] = (t, perr)
        files.append({"name": name, "url": url, "ext": os.path.splitext(url)[1],
                      "chars": len(re.sub(r"\s", "", t)), "err": perr})
        if t:
            chunks.append(t)
            used += len(t)
            if used >= max_chars:
                break
    text = "\n".join(chunks)[:max_chars]
    return {"text": text, "links": [u for u, _ in links], "files": files}


if __name__ == "__main__":
    # 自检：直接传详情页 URL
    for u in sys.argv[1:]:
        hb, e = fetch(u)
        if e:
            print(f"✗ {u}  {e}")
            continue
        html = hb.decode("utf-8", "ignore")
        r = attach_text(html, u)
        print(f"▸ {u}")
        print(f"  附件 {len(r['links'])} 个，取到正文 {len(re.sub(r'\\s', '', r['text']))} 字")
        for f in r["files"]:
            print(f"    - {f['name'][:56]:58} {f['chars']:>6}字 {f['err'] or 'ok'}")
        if r["text"]:
            print("  正文预览：", re.sub(r"\s+", " ", r["text"])[:180])
