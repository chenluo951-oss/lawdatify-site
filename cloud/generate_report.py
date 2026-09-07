#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端合规简报生成器（GitHub Actions / 任意 Linux 环境调用）

一次调用完成：检索监管动态 → LLM 生成数据模块 → 渲染 PDF/DOCX/HTML → QA 校验。

用法:
    python3 cloud/generate_report.py --kind daily  [--date 2026-09-08]
    python3 cloud/generate_report.py --kind weekly [--date 2026-09-07]

环境变量:
    LLM_PROVIDER   gemini | glm | siliconflow | openai   （默认 gemini）
    LLM_API_KEY    必填
    LLM_MODEL     可选，默认按 provider 选免费模型
    TAVILY_API_KEY 非 gemini 检索时必填（Tavily 每月 1000 次免费）
    CBR_FONT_DIR  中文字体目录，需含 song/kaiti/qihei/heiti/songb 五个 .ttf
    CBR_OUT_DIR   报告输出目录（默认 ./out）
    GEMINI_PROXY  可选，gemini 走代理时填 http://host:port
"""
import os
import re
import sys
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
         "temperature": 0.3},
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        timeout=timeout,
    )
    return r["choices"][0]["message"]["content"]


def llm(prompt, use_search=False):
    p = (os.environ.get("LLM_PROVIDER") or "gemini").lower()
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise SystemExit("缺少 LLM_API_KEY")
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(p, DEFAULT_MODELS["gemini"])
    if p == "gemini":
        return gemini_generate(key, model, prompt, use_search,
                               os.environ.get("GEMINI_PROXY"))
    return openai_chat(BASE_URLS.get(p, "https://api.openai.com/v1"), key, model, prompt)


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
    """检索素材。gemini 直接让模型带 Google 搜索出结果；其他 provider 用 Tavily 多轮检索。"""
    provider = (os.environ.get("LLM_PROVIDER") or "gemini").lower()
    material = []
    if provider == "gemini":
        for q in queries:
            log("检索(gemini+搜索):", q)
            try:
                material.append("## 查询：%s\n%s" % (
                    q, gemini_generate(os.environ["LLM_API_KEY"],
                                       os.environ.get("LLM_MODEL") or DEFAULT_MODELS["gemini"],
                                       "请检索 %s 至 %s 期间与「%s」相关的中国监管动态，"
                                       "列出 8-12 条，每条给出：发布日期、发布机构、文件/事件标题、"
                                       "官网原文深链 URL（必须是具体公告页，不能是官网首页）、100 字内要点。"
                                       % (start, end, q),
                                       use_search=True)))
            except Exception as e:
                log("  检索失败:", e)
        return "\n\n".join(material)
    tk = os.environ.get("TAVILY_API_KEY")
    if not tk:
        raise SystemExit("非 gemini 模式需要 TAVILY_API_KEY")
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
    for attempt in (1, 2):
        log("生成数据模块（第 %d 次）" % attempt)
        raw = llm(build_prompt(a.kind, period_label, start, end, material, template, hint))
        code = extract_code(raw)
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
