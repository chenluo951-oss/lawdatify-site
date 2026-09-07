#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端合规简报生成器（GitHub Actions / 任意 Linux 环境调用）

一次调用完成：检索监管动态 → LLM 生成内容 → 渲染 PDF/DOCX/HTML → QA 校验。

用法:
    python3 cloud/generate_report.py --kind daily  [--date 2026-09-08]
    python3 cloud/generate_report.py --kind weekly [--date 2026-09-07]

环境变量:
    LLM_PROVIDER   glm | gemini | siliconflow | openai   （默认 glm，国内永久免费、自带联网检索）
    LLM_API_KEY    必填
    LLM_MODEL     可选，默认按 provider 选免费模型
    TAVILY_API_KEY 仅当 provider=openai/siliconflow 且需联网检索时填（glm/gemini 自带检索，不需要）
    CBR_FONT_DIR  中文字体目录
    CBR_OUT_DIR   报告输出目录（默认 ./out）
    GEMINI_PROXY  可选，gemini 走代理时填 http://host:port

【设计要点：为什么是 JSON 而不是让 LLM 直接写 Python】

早期版本让 LLM 直接输出数据模块源码（几百行 Python 字面量），实测不可靠：
GLM-4-Flash 会在字符串值里写出英文引号、在值中间换行、写错括号类型，
甚至在重试时输出 Markdown 标题而非代码 —— 累计 7 轮运行、约 30 次生成均无法收敛。

现改为两段式：
  1) LLM 只输出 **JSON**（任务更简单、模型更擅长、容错面小）；
  2) 本地用 json / py_lit **确定性**生成 Python 模块 —— 语法恒正确，与模型写作水平无关。
两条降险的关键收益：
  - json.loads(s, strict=False) 天然容忍字符串内的裸换行（曾经的头号失败原因）；
  - META、六大领域名等机械字段由程序生成，既省 token 又不可能写错。
"""
import os
import re
import sys
import ast
import json
import argparse
import datetime
import subprocess
import urllib.request
import urllib.error
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "generator")
CLOUD = os.path.join(ROOT, "cloud")

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    # 必须用 -250414 版本：旧版 glm-4-flash 输出上限仅 4K，长输出会被从中间截断；
    # 新版上限 16K（同样免费）。
    "glm": "glm-4-flash-250414",
    "siliconflow": "Qwen/Qwen2.5-7B-Instruct",
    "openai": "gpt-4o-mini",
}
BASE_URLS = {
    "glm": "https://open.bigmodel.cn/api/paas/v4/",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openai": "https://api.openai.com/v1",
}

DOMAINS = [
    ("数据合规", "个人信息保护、数据出境、网络安全、App 违规收集、数据分类分级"),
    ("AI合规", "生成式 AI 备案、大模型安全、AI 生成内容标识、训练语料合规、智能体"),
    ("算法合规", "算法备案、算法推荐、调度决策、价格算法、劳动者权益"),
    ("平台合规", "平台责任、经营者资质、商户审核、反垄断与反不正当竞争、网络交易"),
    ("产品合规（食品安全）", "食品安全、监督抽检、农兽药残留、标签标识、冷链与前置仓经营许可"),
    ("价格合规", "明码标价、价格欺诈、虚构划线价、动态定价、促销合规"),
]
DOMAIN_NAMES = [d[0] for d in DOMAINS]


def log(*a):
    print("[cloud]", *a, flush=True)


def http_json(url, payload=None, headers=None, timeout=240, method=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    for k, v in (headers or {"Content-Type": "application/json"}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def gemini_generate(api_key, model, prompt, use_search=True, proxy=None):
    url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
           % (model, api_key))
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if use_search:
        body["tools"] = [{"google_search": {}}]
    if proxy:
        os.environ.setdefault("https_proxy", proxy)
        os.environ.setdefault("http_proxy", proxy)
    r = http_json(url, body)
    try:
        return r["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError("gemini 返回异常: %s" % json.dumps(r, ensure_ascii=False)[:600])


def openai_chat(base_url, api_key, model, prompt, timeout=600):
    r = http_json(
        base_url.rstrip("/") + "/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}],
         "temperature": 0.3, "max_tokens": int(os.environ.get("LLM_MAX_TOKENS") or 8192)},
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        timeout=timeout,
    )
    return r["choices"][0]["message"]["content"]


def glm_web_generate(api_key, model, prompt, timeout=600):
    """智谱 GLM 原生 web_search 工具：一次调用同时完成联网检索 + 生成。
    返回模型正文，并把检索到的来源链接（title/link）追加到文末，保证可溯源。

    max_tokens 超过该型号上限会被拒，这里自动降级重试。
    """
    url = BASE_URLS["glm"].rstrip("/") + "/chat/completions"
    base = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "tools": [{"type": "web_search",
                   "web_search": {"enable": True, "search_result": True}}],
    }
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key}
    cands = [int(os.environ.get("LLM_MAX_TOKENS") or 16384), 12288, 8192]
    last = None
    for mt in cands:
        body = dict(base)
        body["max_tokens"] = mt
        try:
            r = http_json(url, body, headers=headers, timeout=timeout)
        except urllib.error.HTTPError as e:
            err = ""
            try:
                err = e.read().decode("utf-8", "ignore")
            except Exception:
                pass
            last = err
            if "max_tokens" in err or "length" in err.lower():
                log("max_tokens=%d 被模型拒绝，自动降级" % mt)
                continue
            raise
        ch = (r.get("choices") or [{}])[0]
        if ch.get("finish_reason") == "length":
            # 输出被截断：交给上层「精简篇幅后重试」
            raise RuntimeError("GLM output truncated at max_tokens=%d" % mt)
        msg = ch.get("message", {})
        text = (msg.get("content") or "").strip()
        for w in (msg.get("web_search") or []):
            link = w.get("link") or w.get("url")
            title = w.get("title") or ""
            if link and link not in text:
                text += "\n[检索来源] %s - %s" % (title, link)
        return text
    raise RuntimeError("GLM request failed (max_tokens downgraded): %s" % (last or "")[:300])


def llm(prompt, use_search=False):
    p = (os.environ.get("LLM_PROVIDER") or "glm").lower()
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise SystemExit("缺少 LLM_API_KEY")
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(p, DEFAULT_MODELS["glm"])
    if p == "gemini":
        return gemini_generate(key, model, prompt, use_search,
                               os.environ.get("GEMINI_PROXY"))
    if p == "glm" and use_search:
        return glm_web_generate(key, model, prompt)
    return openai_chat(BASE_URLS.get(p, BASE_URLS["glm"]), key, model, prompt)


def tavily(api_key, query, max_results=8):
    r = http_json("https://api.tavily.com/search",
                  {"api_key": api_key, "query": query, "max_results": max_results,
                   "search_depth": "advanced", "include_answer": False},
                  timeout=120)
    out = []
    for it in r.get("results", []):
        out.append("- 标题：%s\n  来源：%s\n  日期：%s\n  链接：%s\n  摘要：%s" % (
            it.get("title", ""), it.get("url", "").split("/")[2] if it.get("url") else "",
            it.get("published_date", "") or "未标注", it.get("url", ""),
            (it.get("content", "") or "")[:400]))
    return "\n".join(out)


def collect_material(kind, start, end, queries):
    """检索素材。
    - gemini：模型自带 Google 搜索；
    - glm（智谱）：模型自带 web_search 工具，一次调用即检索+生成，无需额外搜索 API；
    - 其他 provider（openai/siliconflow）：用 Tavily 多轮检索（需 TAVILY_API_KEY）。
    """
    provider = (os.environ.get("LLM_PROVIDER") or "glm").lower()
    key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["glm"])
    material = []
    if provider == "gemini":
        for q in queries:
            log("检索(gemini+搜索):", q)
            try:
                material.append("## 查询：%s\n%s" % (
                    q, gemini_generate(key, model,
                                       "请检索 %s 至 %s 期间与「%s」相关的中国监管动态，"
                                       "列出 8-12 条，每条给出：发布日期、发布机构、文件/事件标题、"
                                       "官网原文深链 URL（必须是具体公告页，不能是官网首页）、100 字内要点。"
                                       % (start, end, q),
                                       use_search=True)))
            except Exception as e:
                log("  检索失败:", e)
        return "\n\n".join(material)
    if provider == "glm":
        for q in queries:
            log("检索(glm web_search):", q)
            try:
                material.append("## 查询：%s\n%s" % (
                    q, glm_web_generate(key, model,
                                       "你是合规检索助手。请检索 %s 至 %s 期间与中国「%s」相关的监管动态，"
                                       "列出 8-12 条，每条给出：发布日期、发布机构、文件/事件标题、"
                                       "官网原文深链 URL（必须是具体公告页，不能是官网首页根域名）、100 字内要点。"
                                       "优先采用官方网站与权威媒体来源。" % (start, end, q))))
            except Exception as e:
                log("  检索失败:", e)
        return "\n\n".join(material)
    tk = os.environ.get("TAVILY_API_KEY")
    if not tk:
        raise SystemExit("provider=%s 无内置检索，需要 TAVILY_API_KEY" % provider)
    for q in queries:
        log("检索(tavily):", q)
        try:
            material.append("## 查询：%s\n%s" % (q, tavily(tk, q)))
        except Exception as e:
            log("  检索失败:", e)
    return "\n\n".join(material)


# --------------------------------------------------------------------------
# 由程序确定性生成的机械字段（不让 LLM 参与，避免无谓出错与 token 消耗）
# --------------------------------------------------------------------------

def build_meta(kind, start, end):
    if kind == "daily":
        date_str = "%d年%d月%d日" % (start.year, start.month, start.day)
        return {
            "title": "合规资讯日报",
            "date_str": date_str,
            "header_text": "合规资讯日报 · 每日监管与合规动态",
            "subtitle": "— 昨日监管动态汇总 · 六大合规领域 · 朴朴超市业务专题 —",
            "brief_en": "DAILY COMPLIANCE BRIEF",
            "tagline": "每日监管与合规动态",
            "filename": "合规资讯简报_%s.pdf" % start.isoformat(),
            "sections": {
                "summary": "一、今日综述",
                "policy": "二、六大领域动态回顾",
                "penalties": "三、监管通报与处罚汇总",
                "pupu": "四、朴朴超市业务专题",
                "outlook": "五、明日前瞻",
            },
        }
    date_str = "%d年%d月%d日—%d月%d日" % (start.year, start.month, start.day,
                                       end.month, end.day)
    return {
        "title": "合规资讯周报",
        "date_str": date_str,
        "header_text": "合规资讯周报 · 每周监管与合规动态",
        "subtitle": "— 上周监管动态汇总 · 六大合规领域 · 朴朴超市业务专题 —",
        "brief_en": "WEEKLY COMPLIANCE BRIEF",
        "tagline": "每周监管与合规动态",
        "filename": "合规资讯周报_%s.pdf" % end.isoformat(),
        "sections": {
            "summary": "一、本周综述",
            "policy": "二、六大领域动态回顾",
            "penalties": "三、监管通报与处罚汇总",
            "pupu": "四、朴朴超市业务专题",
            "outlook": "五、下周前瞻",
        },
    }


def build_prompt(kind, period_label, start, end, material, retry_hint=""):
    """构造 JSON 生成提示。相比早期让模型写 Python 源码，JSON 任务的出错面小得多。"""
    dom = "\n".join("- %s：%s" % (a, b) for a, b in DOMAINS)
    shape = json.dumps({
        "summary": ["本期核心判断 1（120-220 字，含具体数据/文号/日期）"],
        "policy": {d: [{"title": "动态标题",
                        "meta": "日期 动作 ｜ 发布机构",
                        "content": "事实陈述（150-260 字，含量化数据与法条依据）",
                        "analysis": "对朴朴的影响与落点（180-320 字，写到可执行动作）",
                        "url": "https://发布机构官网/具体公告页.htm"}]
                   for d in DOMAIN_NAMES},
        "penalties": [["MM-DD", "处罚/发布机关", "事项标题", "违法事由", "处理结果", "https://官网/具体处罚决定书页面"]],
        "penalty_stats": ["本期处罚的结构性判断（100-180 字）"],
        "pupu_items": [["专题标题", "高/中高/中", "涉及业务环节", "风险分析", "①②③④编号的可执行建议"]],
        "matrix_rows": [["风险主题", "数据合规", "AI合规", "算法合规", "平台合规", "产品合规", "价格合规"]],
        "outlook": ["下期具体动作（60-160 字，动词开头）"],
    }, ensure_ascii=False, indent=1)
    return """你是朴朴超市（即时零售 / 前置仓生鲜电商）的法务合规专家，要产出一份%s的内容数据。

【报告期】%s（%s 至 %s）

【六大合规领域】
%s

【检索到的公开监管素材】（可能含噪声，只保留可核实的官方信息，剔除自媒体转述）
%s

【任务】输出**一个 JSON 对象**（可包在 ```json 围栏里，但不要输出任何解释文字）。结构如下：
%s

【字段说明】
- summary：4-6 条，本期核心判断，务必含具体数字、文号、日期、机构。
- policy：六大领域，每领域 2 条。content 写事实，analysis 必须落到「朴朴该做什么」的可执行动作，不要空话。
- penalties：4-8 条，每条 6 项。无处罚事项的领域可用监管动态/抽检通报条目代替，并在第 4 项注明「非处罚」。
- penalty_stats：3-5 条，对处罚数据的结构性归纳。
- pupu_items：4-5 条，每条 5 项，风险等级只能取 高/中高/中 三值。
- matrix_rows：6-8 行，每行 7 项：第 1 项为风险主题，后 6 项依次是六个领域的风险等级，取值只能为 高/中高/中/低/— 。
- outlook：4-6 条，下期具体动作，动词开头。

【硬性要求·会被程序自动校验】
1. **url 必须是发布机构官网的具体公告/通报/处罚决定书页面深链**，严禁 `https://www.samr.gov.cn/` 这类官网首页根域名。
   查不到确切深链的条目请直接不要写（本条会被自动丢弃，写了也白写）。
2. 全部使用简体中文，避免生僻字与繁体字（PDF 字体为 Noto CJK，缺字会导致 QA 失败）。
3. 数字、文号、法条引用必须准确，无法核实的宁可不写。
4. 每个字符串值写在一行内；确需换行请用 \\n 转义。
5. 篇幅务必控制：输出超长会被截断成不可解析的结果。
%s
""" % ("日报" if kind == "daily" else "周报", period_label, start, end, dom,
       material[:60000], shape, retry_hint)


# --------------------------------------------------------------------------
# JSON 解析与修复（比修复 Python 源码可靠得多）
# --------------------------------------------------------------------------

_JSON_CLOSE = {"{": "}", "[": "]"}


def _strip_fences(text):
    t = text.strip()
    m = re.search(r"```(?:json|JSON)?\s*(.*?)```", t, re.S)
    if m:
        return m.group(1).strip()
    return t


def _brace_slice(t):
    i = t.find("{")
    j = t.rfind("}")
    if i != -1 and j > i:
        return t[i:j + 1]
    return t


def _json_missing_closers(s):
    """忽略字符串内容做括号配对扫描，返回末尾还缺的闭括号序列。"""
    stack = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            i += 1
            while i < n:
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
        i += 1
    return "".join(_JSON_CLOSE[c] for c in reversed(stack))


def _one_fix(s, stage):
    """按 stage 施加一种修复。返回新串（无变化时返回原串）。"""
    if stage == 0:                                  # 尾随逗号：{"a":1,} -> {"a":1}
        return re.sub(r",(\s*[}\]])", r"\1", s)
    if stage == 1:                                  # 末尾缺失的闭括号，一次性补齐
        need = _json_missing_closers(s)
        if need:
            return s.rstrip().rstrip(",") + need
        return s
    if stage == 2:                                  # 字符串未闭合：补一个引号
        return s.rstrip() + '"'
    # stage >= 3：丢掉最后一行（多半是被截断的残缺元素），再补齐闭括号。
    # 宁可少一条内容，也要保住其余部分可解析。
    lines = s.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return s
    lines.pop()
    t = "\n".join(lines).rstrip().rstrip(",")
    return t + _json_missing_closers(t)


def parse_json_loose(text):
    """尽力把 LLM 输出解析成 dict。返回 (dict|None, 说明)。"""
    raw = _strip_fences(text)
    if not raw:
        return None, "empty output"
    cands = [raw, _brace_slice(raw)]
    for c in cands:
        obj, note = _try_parse(c)
        if obj is not None:
            return obj, note
    return None, "unparseable after all repairs"


def _try_parse(text):
    s = text.strip()
    if not s:
        return None, ""
    # strict=False：容忍字符串内裸换行/制表符（曾是 LLM 写 Python 时的头号失败原因，
    # 在 JSON 路径上只需这一个开关即可免疫）。
    for attempt in range(8):
        try:
            v = json.loads(s, strict=False)
            if isinstance(v, dict):
                return v, ("json.loads" if attempt == 0 else "json.loads+fix%d" % attempt)
            return None, "root is not an object"
        except json.JSONDecodeError as e:
            # 多个 JSON 对象粘连时，截断到第一个完整对象
            if "Extra data" in (e.msg or "") and e.pos:
                head = s[:e.pos].strip()
                try:
                    v = json.loads(head, strict=False)
                    if isinstance(v, dict):
                        return v, "trim extra data"
                except Exception:
                    pass
        except Exception:
            pass
        new = _one_fix(s, attempt)
        if new == s:
            continue
        s = new
    # 兜底：按 Python 字面量解析（比 JSON 宽松，允许单引号）
    try:
        v = ast.literal_eval(text.strip())
        if isinstance(v, dict):
            return v, "ast.literal_eval"
    except Exception:
        pass
    return None, ""


# --------------------------------------------------------------------------
# 内容规范化：结构补齐 + 深链校验
# --------------------------------------------------------------------------

_ROOT_ALLOW = {"beian.cac.gov.cn"}      # 算法备案查询系统，本身即合法入口


def deep_link_ok(u):
    """url 必须是官网具体页面的深链，不接受首页根域名。"""
    if not isinstance(u, str) or not u.startswith(("http://", "https://")):
        return False
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return False
    if not p.netloc:
        return False
    if p.netloc in _ROOT_ALLOW:
        return True
    return bool(p.path.strip("/")) or bool(p.query)


def _str_item(v, default=""):
    return v.strip() if isinstance(v, str) else default


def _pad(lst, n, filler="—"):
    lst = list(lst)[:n]
    return lst + [filler] * (n - len(lst))


def normalize(obj, start, end):
    """把任意"大致合规"的模型输出整理成渲染所需的严格结构。

    返回 (data, issues)；data 键：summary/policy/penalties/penalty_stats/
    pupu_items/matrix_rows/outlook。
    """
    issues = []
    period = "%s 至 %s" % (start.isoformat(), end.isoformat())

    def strlist(key, min_n, max_n):
        v = obj.get(key)
        out = [_str_item(x) for x in v if _str_item(x)] if isinstance(v, list) else []
        if len(out) < min_n:
            issues.append("%s 仅 %d 条（需 >=%d）" % (key, len(out), min_n))
        return out[:max_n]

    summary = strlist("summary", 1, 8)
    penalty_stats = strlist("penalty_stats", 0, 6)
    outlook = strlist("outlook", 1, 8)

    # ---- policy：接受 {域名: [条目]} 或 [[域名, [条目]], ...] 两种写法 ----
    pol_raw = obj.get("policy")
    pol_map = {}
    if isinstance(pol_raw, dict):
        pol_map = pol_raw
    elif isinstance(pol_raw, list):
        for row in pol_raw:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                pol_map[row[0]] = row[1]
            elif isinstance(row, dict) and "domain" in row:
                pol_map[row["domain"]] = row.get("items")
    policy = []
    dropped = 0
    for dom in DOMAIN_NAMES:
        items = pol_map.get(dom)
        if not isinstance(items, list):
            items = []
        clean = []
        for it in items:
            if not isinstance(it, dict):
                continue
            url = _str_item(it.get("url"))
            if not deep_link_ok(url):
                dropped += 1
                continue
            clean.append({
                "title": _str_item(it.get("title") or it.get("matter"), "（缺标题）"),
                "meta": _str_item(it.get("meta"), period),
                "content": _str_item(it.get("content") or it.get("summary")),
                "analysis": _str_item(it.get("analysis") or it.get("impact")),
                "url": url,
            })
        if not clean:
            clean.append({
                "title": "%s：本期内无满足深链溯源要求的官方重大动态" % dom,
                "meta": period + " ｜ —",
                "content": "本期内未检索到可在发布机构官网定位到具体公告页面的%s领域动态。"
                           "为避免引用不可核实来源，本条留空待核。" % dom,
                "analysis": "建议对该领域保持常规监测，待官方发布可溯源的具体公告后补充分析。",
                "url": "",
            })
        policy.append((dom, clean))
    if dropped:
        issues.append("丢弃 %d 条 policy（url 非深链）" % dropped)

    # ---- penalties：每条 6 项 ----
    pen_raw = obj.get("penalties")
    penalties = []
    pen_drop = 0
    if isinstance(pen_raw, list):
        for r in pen_raw:
            if not isinstance(r, (list, tuple)):
                continue
            r = list(r) + ["—"] * (6 - len(r)) if len(r) < 6 else list(r)[:6]
            r = [_str_item(x, "—") for x in r]
            if not deep_link_ok(r[5]):
                pen_drop += 1
                continue
            penalties.append(tuple(r))
    if pen_drop:
        issues.append("丢弃 %d 条 penalties（url 非深链）" % pen_drop)

    # ---- pupu_items：每条 5 项 ----
    pupu_raw = obj.get("pupu_items")
    pupu = []
    if isinstance(pupu_raw, list):
        for r in pupu_raw:
            if isinstance(r, dict):
                r = [r.get(k) for k in ("title", "level", "link", "analysis", "advice")]
            if not isinstance(r, (list, tuple)):
                continue
            pupu.append(tuple(_pad([_str_item(x, "—") for x in r], 5)))

    # ---- matrix_rows：每行 7 项（主题 + 六大领域等级）----
    mx_raw = obj.get("matrix_rows")
    matrix = []
    if isinstance(mx_raw, list):
        for r in mx_raw:
            if not isinstance(r, (list, tuple)):
                continue
            matrix.append(_pad([_str_item(x, "—") for x in r], 7))

    data = {
        "summary": summary,
        "policy": policy,
        "penalties": penalties,
        "penalty_stats": penalty_stats,
        "pupu_items": pupu,
        "matrix_rows": matrix,
        "outlook": outlook,
    }
    return data, issues


# --------------------------------------------------------------------------
# 确定性生成 Python 模块（语法恒正确，与 LLM 写作水平无关）
# --------------------------------------------------------------------------

def py_lit(v, ind=0):
    """把基础类型渲染成合法且可读的 Python 字面量。

    不用 json.dumps：它会输出 true/false/null 这类 Python 不认识的字面量。
    list 渲染成 [..]、tuple 渲染成 (..)；单元素 tuple 必须补尾随逗号，
    否则 (x) 只是「被括号包裹的 x」，结构会塌陷（曾导致 PENALTIES 退化为一维列表）。
    """
    sp = " " * ind
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return "True" if v else "False"
    if v is None:
        return "None"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        is_t = isinstance(v, tuple)
        open_c, close_c = ("(", ")") if is_t else ("[", "]")
        if not v:
            return "()" if is_t else "[]"
        inner = [py_lit(x, ind + 4) for x in v]
        one = open_c + ", ".join(inner) + ("," if (is_t and len(v) == 1) else "") + close_c
        if len(one) + ind <= 96:
            return one
        body = ",\n".join(" " * (ind + 4) + x for x in inner)
        return open_c + "\n" + body + "\n" + sp + close_c
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = [repr(k) + ": " + py_lit(val, ind + 4) for k, val in v.items()]
        one = "{" + ", ".join(items) + "}"
        if len(one) + ind <= 96:
            return one
        body = ",\n".join(" " * (ind + 4) + x for x in items)
        return "{\n" + body + "\n" + sp + "}"
    return repr(v)


def module_source(meta, data):
    """由 dict 生成数据模块源码。结构与 cloud/template_daily.py 完全一致。"""
    L = ["# -*- coding: utf-8 -*-",
         '"""%s %s 内容数据（六大合规领域）"""' % (meta["title"], meta["date_str"]),
         ""]
    L.append("META = " + py_lit(meta))
    L.append("")
    L.append("# 一、综述（核心观点框）")
    L.append("SUMMARY = " + py_lit(data["summary"]))
    L.append("")
    L.append("# 二、六大领域动态回顾")
    L.append("POLICY_DOMAINS = " + py_lit([(d, items) for d, items in data["policy"]]))
    L.append("")
    L.append("# 三、监管通报与处罚汇总")
    L.append("PENALTIES = " + py_lit([tuple(r) for r in data["penalties"]]))
    L.append("")
    L.append("PENALTY_STATS = " + py_lit(data["penalty_stats"]))
    L.append("")
    L.append("# 四、朴朴超市业务专题")
    L.append("PUPU_ITEMS = " + py_lit([tuple(r) for r in data["pupu_items"]]))
    L.append("")
    L.append("MATRIX_ROWS = " + py_lit(data["matrix_rows"]))
    L.append("")
    L.append("# 五、前瞻")
    L.append("OUTLOOK = " + py_lit(data["outlook"]))
    L.append("")
    L.append("DATA = {")
    for key, var in (("summary", "SUMMARY"), ("policy", "POLICY_DOMAINS"),
                     ("penalties", "PENALTIES"), ("penalty_stats", "PENALTY_STATS"),
                     ("pupu_items", "PUPU_ITEMS"), ("matrix_rows", "MATRIX_ROWS"),
                     ("outlook", "OUTLOOK")):
        L.append('    "%s": %s,' % (key, var))
    L.append("}")
    L.append("")
    return "\n".join(L)


def check_syntax(code):
    """写入前的语法自检。此路径理论上恒为 True（源码由程序生成）。"""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, "第 %d 行：%s" % (e.lineno or 0, e.msg)
    except Exception as e:
        return False, "解析异常：%s" % e


def validate_module(path, mod):
    env = os.environ.copy()
    env["PYTHONPATH"] = GEN
    code = (
        "import importlib,sys;m=importlib.import_module('%s');"
        "need=['META','DATA','PENALTIES','MATRIX_ROWS','OUTLOOK'];"
        "miss=[n for n in need if not hasattr(m,n)];"
        "print('MISS:' + ','.join(miss) if miss else 'OK');"
        "print('POLICY_GROUPS:' + str(len(m.DATA.get('policy',[]))));"
        "print('PENALTIES:' + str(len(m.PENALTIES)));"
    ) % mod
    r = subprocess.run([sys.executable, "-c", code], cwd=GEN, env=env,
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return ("OK" in out and "MISS:" not in out), out[-800:]


def render(mod, out_dir):
    env = os.environ.copy()
    env["PYTHONPATH"] = GEN
    env["CBR_OUT_DIR"] = out_dir
    os.makedirs(out_dir, exist_ok=True)
    scripts = [("gen_weekly_pdf.py", "简版PDF"), ("gen_weekly_docx.py", "简版DOCX"),
               ("gen_deep_pdf.py", "深度PDF"), ("gen_deep_docx.py", "深度DOCX"),
               ("gen_html.py", "HTML")]
    done = []
    for s, label in scripts:
        r = subprocess.run([sys.executable, os.path.join(GEN, s), mod], cwd=GEN, env=env,
                           capture_output=True, text=True)
        if r.returncode != 0:
            log("渲染失败", label, (r.stderr or r.stdout or "")[-400:])
        else:
            log("渲染完成", label)
            done.append(label)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=["daily", "weekly"])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    today = datetime.date.fromisoformat(a.date) if a.date else datetime.date.today()
    if a.kind == "daily":
        start = end = today - datetime.timedelta(days=1)
        period_label = "%s 日报" % start.isoformat()
    else:
        end = today - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=6)
        period_label = "%s 至 %s 周报" % (start.isoformat(), end.isoformat())

    out_dir = a.out or os.environ.get("CBR_OUT_DIR") or os.path.join(ROOT, "out")
    log("期次:", period_label, "| 输出:", out_dir)

    queries = ["%s %s %s 官方公告 通报" % (start, end, d[0]) for d in DOMAINS]
    if a.kind == "weekly":
        queries.append("%s %s 市场监管总局 网信办 工信部 政策发布" % (start, end))
    material = collect_material(a.kind, start.isoformat(), end.isoformat(), queries)
    if not material.strip():
        raise SystemExit("未检索到任何素材，终止（避免产出空报告）")

    meta = build_meta(a.kind, start, end)
    mod = "%s_data_%s" % (a.kind, start.strftime("%m%d"))
    mod_path = os.path.join(GEN, mod + ".py")

    ok = False
    hint = ""
    best = None                 # 记录内容最丰富的一次，作为兜底
    best_score = -1
    for attempt in (1, 2, 3):
        log("生成内容（第 %d 次）" % attempt)
        try:
            raw = llm(build_prompt(a.kind, period_label, start, end, material, hint))
        except Exception as e:
            log("生成请求失败:", e)
            hint = "上次的请求失败了，请精简篇幅后重试（summary 4 条、每领域 2 条、penalties 5 条、outlook 4 条）。"
            continue
        obj, note = parse_json_loose(raw)
        if obj is None:
            log("JSON 解析失败:", note)
            hint = "上次的输出无法被 JSON 解析（%s）。请只输出一个 JSON 对象，不要解释文字，" \
                   "并精简篇幅以保证输出完整。" % note
            continue
        log("JSON 解析成功（%s）" % note)
        data, issues = normalize(obj, start, end)
        for it in issues:
            log("  ·", it)
        # 内容量打分：用于在所有尝试都未通过硬性校验时挑最好的一次
        score = (len(data["summary"]) + len(data["penalties"]) + len(data["pupu_items"])
                 + len(data["outlook"]) + sum(len(v) for _, v in data["policy"]))
        if score > best_score:
            best, best_score = data, score
        # 硬性门槛：综述、处罚、前瞻都不能为空，且至少要有可用的 policy 条目
        usable_policy = sum(1 for _, items in data["policy"]
                            if items and items[0].get("url"))
        if not data["summary"] or not data["penalties"] or not data["outlook"]:
            hint = ("上次输出缺少必要字段（summary=%d / penalties=%d / outlook=%d，"
                    "带深链的 policy 条目=%d）。请补齐后重新输出完整 JSON："
                    "url 必须是发布机构官网的具体公告页深链，查不到就不要写该条。"
                    % (len(data["summary"]), len(data["penalties"]),
                       len(data["outlook"]), usable_policy))
            log("内容不完整，重试:", hint[:120])
            continue
        code = module_source(meta, data)
        syn_ok, syn_err = check_syntax(code)
        if not syn_ok:
            log("生成的模块语法异常（不应发生）:", syn_err)
            continue
        with open(mod_path, "w", encoding="utf-8") as f:
            f.write(code)
        ok, msg = validate_module(mod_path, mod)
        if ok:
            log("数据模块校验通过")
            break
        log("校验失败:", msg[-300:])
        hint = "上次输出经程序转换后字段不全，请重新输出完整 JSON，确保 7 个顶层键齐全。"

    if not ok:
        # 兜底：用内容最多的一次再写一遍（少几条内容总好过整期没有）
        if best is None:
            raise SystemExit("三次均未产出可解析的 JSON，终止")
        log("三次均未通过完整校验，改用内容最完整的一次兜底（评分 %d）" % best_score)
        code = module_source(meta, best)
        with open(mod_path, "w", encoding="utf-8") as f:
            f.write(code)
        ok, msg = validate_module(mod_path, mod)
        if not ok:
            raise SystemExit("兜底模块仍未通过校验: %s" % msg[-300:])

    done = render(mod, out_dir)
    files = sorted(f for f in os.listdir(out_dir) if start.strftime("%m%d") in f or mod in f)
    print(json.dumps({"module": mod, "period": period_label,
                      "rendered": done, "files": files}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
