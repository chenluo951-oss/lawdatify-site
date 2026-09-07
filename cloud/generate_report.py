#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端合规简报生成器（GitHub Actions / 任意 Linux 环境调用）

一次调用完成：检索监管动态 → LLM 生成数据模块 → 渲染 PDF/DOCX/HTML → QA 校验。

用法:
    python3 cloud/generate_report.py --kind daily  [--date 2026-09-08]
    python3 cloud/generate_report.py --kind weekly [--date 2026-09-07]

环境变量:
    LLM_PROVIDER   glm | gemini | siliconflow | openai   （默认 glm，国内永久免费、自带联网检索）
    LLM_API_KEY    必填
    LLM_MODEL     可选，默认按 provider 选免费模型
    TAVILY_API_KEY 仅当 provider=openai/siliconflow 且需联网检索时填（glm/gemini 自带检索，不需要）
    CBR_FONT_DIR  中文字体目录，需含 song/kaiti/qihei/heiti/songb 五个 .ttf
    CBR_OUT_DIR   报告输出目录（默认 ./out）
    GEMINI_PROXY  可选，gemini 走代理时填 http://host:port

说明:
    - glm（智谱 GLM-4-Flash）永久免费、国内直连，且 chat 接口原生支持 web_search 工具，
      因此「检索 + 生成」只需一个 key，无需额外搜索 API（Tavily 之类）。
    - gemini 同样自带 Google 搜索，但用户所在地区无法开通，故默认改为 glm。
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "generator")
CLOUD = os.path.join(ROOT, "cloud")

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "glm": "glm-4-flash",
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
    ("AI 合规", "生成式 AI 备案、大模型安全、AI 生成内容标识、训练语料合规、智能体"),
    ("算法合规", "算法备案、算法推荐、调度决策、价格算法、劳动者权益"),
    ("平台合规", "平台责任、经营者资质、商户审核、反垄断与反不正当竞争、网络交易"),
    ("产品合规", "食品安全、监督抽检、农兽药残留、标签标识、冷链与前置仓经营许可"),
    ("价格合规", "明码标价、价格欺诈、虚构划线价、动态定价、促销合规"),
]


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

    稳健性处理：
    1) max_tokens 若超过该型号上限会被拒，自动降级重试（各型号上限 4K~16K 不等）；
    2) finish_reason=length 表示输出被截断，抛可识别异常交由上层「精简后重试」。
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
    # 不显式给足长度，中文数据模块（数百行）极易在半途被截断成未闭合字符串
    cands = [int(os.environ.get("LLM_MAX_TOKENS") or 8192), 4096, 2048]
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
            raise RuntimeError("GLM 输出被 max_tokens(%d) 截断，内容不完整" % mt)
        msg = ch.get("message", {})
        text = (msg.get("content") or "").strip()
        for w in (msg.get("web_search") or []):
            link = w.get("link") or w.get("url")
            title = w.get("title") or ""
            if link and link not in text:
                text += "\n[检索来源] %s — %s" % (title, link)
        return text
    raise RuntimeError("GLM 请求失败（max_tokens 已降级仍不可用）: %s" % (last or "")[:300])


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
                                       "优先采用官方网站与权威媒体来源。"
                                       % (start, end, q))))
            except Exception as e:
                log("  检索失败:", e)
        return "\n\n".join(material)
    # openai / siliconflow 等无内置检索的 provider → Tavily
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


def build_prompt(kind, period_label, start, end, material, template, retry_hint=""):
    dom = "\n".join("- %s：%s" % (a, b) for a, b in DOMAINS)
    return """你是朴朴超市（即时零售 / 前置仓生鲜电商）的法务合规专家，要产出一份%s的内部合规简报数据。

【报告期】%s（%s 至 %s）

【六大合规领域】
%s

【检索到的公开监管素材】（可能含噪声，只保留可核实的官方信息，剔除自媒体转述）
%s

【输出要求】
1. 严格按下方《模板》的 Python 结构与字段名输出一个完整数据模块，**只输出一个 ```python 代码块**，不要任何解释文字。
2. 字段规范：
   - META 中的期次/日期与本次报告期一致；title/date_str 用中文。
   - policy：按六大领域分组，每条含 date、title、summary、impact（对朴朴的业务影响）、url。
   - penalties：监管通报与处罚，每条含日期、被处罚主体、事由、依据、结果、url。
   - pupu_items：站在朴朴业务视角的专题分析（3-5 条），每条含主题、风险点、涉及业务环节、应对建议。
   - matrix_rows：风险热力矩阵，含风险主题、等级（高/中/低）、涉及环节、分析、建议。
   - outlook：前瞻要点。
3. 【硬性要求·会被自动校验】
   - **所有 url 必须是发布机构官网的具体公告/通报/处罚决定书页面深链**，严禁使用 `https://www.samr.gov.cn/` 这类官网首页根域名；找不到确切深链就不要写该条。
   - 全部使用简体中文，不要出现生僻字与繁体字（PDF 字体为 Noto CJK，缺字会 QA 失败）。
   - 数字、文号、法条引用必须准确，无法核实的宁可不写。
   - 内容要具体到"朴朴该做什么"，不要空话。
4. 篇幅：policy 每领域 2-4 条；penalties 3-6 条；确保信息密度，不要注水。
%s

【模板】（照此结构，替换内容；不要改字段名与文件的整体组织方式）
```python
%s
```
""" % ("日报" if kind == "daily" else "周报", period_label, start, end, dom,
       material[:60000], retry_hint, template)


def extract_code(text):
    m = re.search(r"```python\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*(.*?)```", text, re.S)
    return m.group(1).strip() if m else text.strip()


def check_syntax(code):
    """写入前先做语法预检。返回 (是否通过, 可读错误)。
    出错时把「行号 + 该行原始内容」一并返回，便于回喂给模型修正。"""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        lines = code.splitlines()
        ln = e.lineno or 0
        snippet = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
        return False, ("第 %d 行语法错误：%s；该行内容：%s"
                       % (ln, e.msg, snippet[:120]))
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

    template_path = os.path.join(CLOUD, "template_daily.py" if a.kind == "daily" else "template_weekly.py")
    template = open(template_path, encoding="utf-8").read()

    mod = "%s_data_%s" % (a.kind, start.strftime("%m%d"))
    mod_path = os.path.join(GEN, mod + ".py")

    ok = False
    hint = ""
    for attempt in (1, 2, 3):
        log("生成数据模块（第 %d 次）" % attempt)
        try:
            raw = llm(build_prompt(a.kind, period_label, start, end, material, template, hint))
        except Exception as e:
            log("生成请求失败:", e)
            hint = ("上次生成失败（%s）。请主动精简内容以保证一次性输出完整："
                    "policy 每领域 2 条、penalties 3 条、pupu_items 3 条、"
                    "matrix_rows 6-8 行、outlook 4-6 条；每条 summary/analysis 控制在 80 字内。"
                    % str(e)[:150])
            continue
        code = extract_code(raw)
        # 先做语法预检，避免把坏代码写进文件再靠 import 才发现
        syn_ok, syn_err = check_syntax(code)
        if not syn_ok:
            log("语法预检失败:", syn_err)
            hint = ("上次输出的 Python 代码有语法错误：%s。"
                    "请重新输出【完整】的数据模块代码：所有字符串字面量必须用成对引号闭合；"
                    "字符串内部不要直接换行（改用 \\n 或拆成多段拼接）；"
                    "必须一次性输出完整，不要中途截断。" % syn_err)
            continue
        with open(mod_path, "w", encoding="utf-8") as f:
            f.write(code)
        ok, msg = validate_module(mod_path, mod)
        if ok:
            log("数据模块校验通过")
            break
        log("校验失败:", msg)
        hint = "上次输出未通过校验（%s），请修正后重新输出完整代码。" % msg[-200:]

    if not ok:
        raise SystemExit("数据模块两次生成均未通过校验，终止")

    done = render(mod, out_dir)
    files = sorted(f for f in os.listdir(out_dir) if start.strftime("%m%d") in f or mod in f)
    print(json.dumps({"module": mod, "period": period_label,
                      "rendered": done, "files": files}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
