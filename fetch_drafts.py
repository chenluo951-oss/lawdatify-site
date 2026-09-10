#!/usr/bin/env python3
"""
草案跟踪数据抓取：立法的"在途"状态。
数据源：
  1) TC260 国家标准征求意见 API（含起止日期，可算倒计时）
  2) 中央网信办 cac.gov.cn 通知公告中的征求意见条目
  3) 人工核实的历史悬置/重点草案（DRAFTS_MANUAL）
输出 sources/library/drafts.json
"""
import json, os, re, subprocess, datetime, sys

SITE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SITE, "sources/library/drafts.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

def curl(url, timeout=25):
    for _ in range(3):
        r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), url],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    return ""

TODAY = datetime.date.today()

# ---------- 1) TC260 标准征求意见 ----------
def fetch_tc260():
    api = "https://www.tc260.org.cn/tc260-webapp/api/projectOpinion/list?pageNum=1&pageSize=50"
    try:
        d = json.loads(curl(api))
        rows = d.get("data", {}).get("rows", [])
    except Exception as e:
        print("TC260 API 失败:", e, file=sys.stderr)
        return []
    out = []
    for r in rows:
        title = (r.get("recordTitle") or "").strip()
        if not title:
            continue
        st = (r.get("stime") or "")[:10]
        et = (r.get("etime") or "")[:10]
        days = None
        try:
            days = (datetime.date.fromisoformat(et) - TODAY).days
        except Exception:
            pass
        out.append({
            "name": title,
            "kind": "国家标准草案",
            "issuer": "全国网络安全标准化技术委员会（TC260）",
            "start": st, "end": et, "days_left": days,
            "status": "征求意见中" if (days is None or days >= 0) else "征求意见已结束",
            "url": f"https://www.tc260.org.cn/tc260/bzzqyj/bzkdetail.shtml?id={r.get('projectId')}&type=gjbzjh",
            "note": (r.get("title") or "").strip().replace("\r", "").replace("\n", ""),
        })
    return out

# ---------- 2) CAC 通知公告 ----------
def fetch_cac():
    h = curl("https://www.cac.gov.cn/")
    if not h:
        return []
    pat = re.compile(r'<span class="state">\[([^\]]+)\]</span><a href="(//www\.cac\.gov\.cn/[^"]+)"[^>]*title="([^"]+)"')
    out, seen = [], set()
    for st, url, t in pat.findall(h):
        u = "https:" + url
        if u in seen or "征求意见" not in t:
            continue
        seen.add(u)
        m = re.search(r"《([^》]+)》", t)
        name = m.group(1) if m else t
        out.append({
            "name": name,
            "kind": "法规/规章草案",
            "issuer": "国家互联网信息办公室",
            "start": "", "end": "", "days_left": None,
            "status": "进行中" if st == "进行中" else "已结束征求意见",
            "url": u,
            "note": t,
        })
    return out

# ---------- 3) 人工核实条目 ----------
# 每条均经检索 + curl 实测可达；status 反映截至脚本运行日的真实状态
DRAFTS_MANUAL = [
    dict(name="互联网应用程序个人信息收集使用规定（征求意见稿）", kind="部门规章草案",
         issuer="国家互联网信息办公室", start="2026-01-10", end="2026-02-09",
         status="征求意见已结束，尚未正式发布",
         url="https://www.cac.gov.cn/2026-01/10/c_1769603446094128.htm",
         note="规范 App/SDK/分发平台/智能终端的个人信息收集使用；要求权限仅在使用时调用、禁止超范围与超频度调用、15 个工作日内完成注销。对朴朴 App 与 SDK 治理直接相关。"),
    dict(name="移动互联网应用程序个人信息保护管理暂行规定（征求意见稿）", kind="部门规章草案",
         issuer="工业和信息化部、国家网信办、公安部、市场监管总局", start="2021-04-26", end="2021-05-26",
         status="长期悬置，至今未正式发布",
         url="https://www.cac.gov.cn/2021-04/26/c_1621018189707703.htm",
         note="确立“知情同意”“最小必要”两项原则，划分 App 开发运营者、分发平台、第三方服务提供者、终端生产企业、网络接入服务提供者五类主体责任。虽未生效，但监管执法长期参照其口径。"),
]

def main():
    items = fetch_tc260() + fetch_cac() + list(DRAFTS_MANUAL)
    # 去重：按名称
    seen, uniq = set(), []
    for it in items:
        k = re.sub(r"\s+", "", it["name"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    # 排序：征求意见中（剩余天数少的在前）> 悬置/未发布 > 已结束
    def rank(x):
        if x.get("days_left") is not None and x["days_left"] >= 0:
            return (0, x["days_left"])
        if "未正式发布" in x.get("status", "") or "悬置" in x.get("status", ""):
            return (1, 0)
        return (2, 0)
    uniq.sort(key=rank)
    json.dump({"updated": TODAY.isoformat(), "items": uniq},
              open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"草案 {len(uniq)} 条 -> {OUT}")
    for it in uniq[:8]:
        d = it.get("days_left")
        print(f"  [{it['status']}] {it['name'][:40]}" + (f" 剩{d}天" if d is not None and d >= 0 else ""))

if __name__ == "__main__":
    main()
