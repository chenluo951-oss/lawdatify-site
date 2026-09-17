#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_wx_archive.py —— 生成「官方公众号原文存档」页（kb/wx.html）。

为什么需要这一页
----------------
地方市场监管局与部分执法机关的大量执法通报、典型案例、专项行动公告，
**只在官方微信公众号发布，PC 官网没有对应页**（阳曲县、铜梁区、甘井子区均如此）。
这类内容本该算「官方原文」，但：
  · 微信对搜索引擎封闭（Bing 的 site:mp.weixin.qq.com 返回 0 条原链）；
  · 搜狗微信搜索只能拿到带 signature 的**临时链**，取不到 __biz/mid/idx/sn 永久链；
  · mp.weixin.qq.com 对 curl **一律返回 200**（无效链接也 200），不能用状态码判别有效性。
所以公众号内容**不做外链**（外链必然短命），改为**站内正文存档**——与标准正文存档同一范式。
本页把 sources/wx/*.json 的存档渲染成可阅读、可检索、可深链的页面。

体积控制（决定站点能不能长期跑下去）
------------------------------------
  · **绝不为每篇生成独立 HTML**：正文按 40 篇/片切分，只在该条被点开时才 fetch 对应分片；
  · 目录 kb/wx/index.json 只存元数据（十几 KB），首屏只加载它；
  · 单篇存档约 6 KB，比标准原版 PDF（均 1.2 MB/部）小三个数量级 —— 公众号内容
    **不是**站点容量瓶颈，见 tools/site_size.py 的红线体检。

产出
----
  kb/wx/index.json     目录（id/标题/机构/公众号/gh/日期/字数/分片/主题）
  kb/wx/p-NN.json      {id: 正文}，40 篇/片
  kb/wx.html           阅读器（搜索 + 机构筛选 + 点开阅读 + 复制/下载/打印）
  sources/wx/replaces.json   原二手来源 URL → 站内存档映射（供 build_topics 改写链接）
"""
import os, re, json, sys, html
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "sources", "wx")
OUT = os.path.join(HERE, "kb", "wx")
PAGE = os.path.join(HERE, "kb", "wx.html")
PER_PART = 40  # 仅用于未来可能的批量导出；正文按篇懒加载，不再分片

SKIP = {"accounts.json", "replaces.json"}

# 公众号号名 → 发布机构（发布机关官方号才登记；未登记则回落到号名并标「待核」）
ORG_HINT = {
    "gh_005460440220": "阳曲县市场监督管理局",
}


def esc(s):
    return html.unescape(str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unesc(s):
    return html.unescape(str(s or ""))


def load_articles():
    out = []
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".json") or fn in SKIP:
            continue
        p = os.path.join(SRC, fn)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:                                   # noqa: BLE001
            print(f"  ! 跳过 {fn}：{e}")
            continue
        if not (d.get("body") or "").strip():
            print(f"  ! 跳过 {fn}：无正文")
            continue
        out.append(d)
    return out


def norm_org(d):
    """机构名：优先显式 org，其次账号台账/号名推断，最后回落公众号名。"""
    org = (d.get("org") or "").strip()
    if org:
        return org
    org = ORG_HINT.get((d.get("gh") or "").strip(), "")
    if org:
        return org
    acct = (d.get("account") or "").strip()
    m = re.search(r"(.*?(?:管理局|监督管理局|委员会|人民政府|监管局|法院|检察院))", acct)
    return m.group(1) if m else acct


# 公众号模板尾巴：编辑署名串与「在看」引流语，不是正文内容。
# 只对末尾若干字符生效，避免误删正文中偶发的同类词。
RE_CREDIT = re.compile(r"(?:监制|编审|责编|编辑|审核|校对|排版|美编|制图|来源|原标题)"
                       r"\s*[：:]\s*[\u4e00-\u9fa5A-Za-z0-9·（）()]{1,16}")
RE_LOOK = re.compile(r"我就知道你\s*[“\"'‘]在看[”\"'’]|点亮?在?看\s*$|^\s*点分享\s*$", re.M)
TAIL_WINDOW = 300


def strip_tail(body):
    """剥掉公众号模板尾巴（署名串 / 互动引导），保留正文与评析。"""
    t = RE_LOOK.sub("", body)
    if len(t) > TAIL_WINDOW:
        head, tail = t[:-TAIL_WINDOW], t[-TAIL_WINDOW:]
        t = head + RE_CREDIT.sub("", tail)
    else:
        t = RE_CREDIT.sub("", t)
    t = re.sub(r"[ \t\u00a0]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ---------------------------------------------------------------- 正文渲染

RE_CASE = re.compile(r"^案例\s*[一二三四五六七八九十\d]+\s*[：:]")
RE_LAW = re.compile(r"《[^》]{2,60}》")
RE_ART = re.compile(r"第[一二三四五六七八九十百零〇\d]+条"
                    r"(?:第[一二三四五六七八九十百零〇\d]+款)?"
                    r"(?:第[一二三四五六七八九十百零〇\d]+项)?")


def paras(body):
    """把存档正文切成段落；「案例N：」起新段并标记为小标题。

    微信公众号正文常把「案例N：标题」与案情正文挤在同一行、中间无换行，因此需要
    两道断行：① 在 `案例N：` 前断；② 在「…案」与紧随其后的 `YYYY年M月` 之间断。
    """
    t = re.sub(r"\r\n?", "\n", body).strip()
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    # ① 案例标题前断行
    t = re.sub(r"(?<!^)(?<=\S)(案例\s*[一二三四五六七八九十\d]+\s*[：:])", r"\n\1", t)
    # ② 标题结尾的「…案」与案情起始的年份之间断行
    t = re.sub(r"(?<=案)(?=\d{4}\s*年\s*\d{1,2}\s*月)", "\n", t)
    lines = [x.strip() for x in t.split("\n")]
    out, buf = [], ""
    for ln in lines:
        if not ln:
            if buf:
                out.append(("p", buf)); buf = ""
            continue
        if RE_CASE.match(ln):
            if buf:
                out.append(("p", buf)); buf = ""
            out.append(("h", ln))
        else:
            buf = (buf + "\n" + ln) if buf else ln
    if buf:
        out.append(("p", buf))
    return out


def render_body(body):
    """段落 → HTML。法条名加品牌色、条款号加琥珀色，便于法务扫读。"""
    htmls = []
    for kind, tx in paras(body):
        tx = tx.replace("\n", "")
        safe = esc(tx)
        safe = RE_LAW.sub(lambda m: f'<span class="wx-law">{m.group(0)}</span>', safe)
        safe = RE_ART.sub(lambda m: f'<span class="wx-art">{m.group(0)}</span>', safe)
        if kind == "h":
            htmls.append(f'<p class="wx-h">{safe}</p>')
        else:
            htmls.append(f'<p class="wx-p">{safe}</p>')
    return "\n".join(htmls)


def render_html_body(html_body):
    """结构化正文（含原文排版与图片）→ HTML，仅对文本节点做法条/条款上色，不破坏标签。

    仅对「标签之外」的文本段上色：避免误改属性值；各文本段独立处理，跨段不会错位。
    """
    out = []
    for seg in re.split(r"(<[^>]+>)", html_body):
        if seg.startswith("<"):
            out.append(seg)
            continue
        s = RE_LAW.sub(lambda m: f'<span class="wx-law">{m.group(0)}</span>', seg)
        s = RE_ART.sub(lambda m: f'<span class="wx-art">{m.group(0)}</span>', s)
        out.append(s)
    return "".join(out)


# ---------------------------------------------------------------- 页面模板

CSS = """
.rd{display:grid;grid-template-columns:332px 1fr;gap:26px;align-items:start}
@media(max-width:960px){.rd{grid-template-columns:1fr}}
.rd-side{position:sticky;top:76px;background:#fff;border:1px solid var(--line);
  border-radius:14px;padding:14px;max-height:calc(100vh - 108px);display:flex;flex-direction:column}
.rd-box{width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid var(--line);
  border-radius:9px;font-size:14px;margin-bottom:10px;background:#fff;color:var(--ink);font-family:var(--sans)}
.rd-chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.rd-chip{font-size:12px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);
  background:#fff;color:var(--muted);cursor:pointer;white-space:nowrap;font-family:var(--sans)}
.rd-chip.on{background:var(--ink);border-color:var(--ink);color:#fff}
.rd-count{font-size:12.5px;color:var(--faint);margin:0 0 8px}
.rd-list{overflow:auto;flex:1;margin:0;padding:0;list-style:none}
.rd-list button{display:block;width:100%;text-align:left;background:none;border:0;cursor:pointer;
  padding:8px 10px;border-radius:8px;font-size:13.5px;line-height:1.5;color:inherit;font-family:var(--sans)}
.rd-list button:hover{background:rgba(127,127,127,.10)}
.rd-list button.on{background:#e8f0fa;box-shadow:inset 2px 0 0 var(--brand)}
.rd-list .lv{display:block;font-size:11.5px;color:var(--faint);margin-top:3px}
.rd-main{min-height:460px}
.rd-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:#fff;
  border:1px solid var(--line);border-radius:11px;padding:9px 12px;margin-bottom:16px}
.rd-seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.rd-seg button{border:0;background:#fff;color:var(--ink-2);font-size:13px;padding:6px 12px;
  cursor:pointer;font-family:var(--sans);border-right:1px solid var(--line)}
.rd-seg button:last-child{border-right:0}
.rd-seg button:hover{background:rgba(127,127,127,.08)}
.rd-note{background:#fff;border:1px solid var(--line);border-left:3px solid var(--brand);
  border-radius:10px;padding:12px 16px;font-size:13.5px;line-height:1.75;color:var(--ink-2);margin:0 0 18px}
.rd-splash{background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px 28px;
  font-size:14.5px;line-height:1.95;color:var(--ink-2)}
.rd-splash b{color:var(--ink)}
.rd-splash code{background:rgba(127,127,127,.12);padding:1px 6px;border-radius:5px;font-size:13px}
.paper{background:#fff;border:1px solid var(--line);border-radius:14px;
  padding:44px 52px 40px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
@media(max-width:760px){.paper{padding:26px 20px}}
.rd-meta{font-size:12.5px;color:var(--faint);border-top:1px dashed var(--line);
  margin-top:26px;padding-top:12px;line-height:1.8}
.wx-title{font-size:23px;font-weight:700;line-height:1.5;color:var(--ink);text-align:center;
  margin:0 0 8px;font-family:var(--serif,var(--sans))}
.wx-org{text-align:center;font-size:13.5px;color:var(--muted);margin:0 0 4px}
.wx-rule{border:0;border-top:1px solid var(--line);margin:22px 0 24px}
.wx-h{font-size:16.5px;font-weight:700;color:var(--ink);margin:26px 0 10px;line-height:1.7}
.wx-p{font-size:16px;line-height:2;color:var(--ink-2);margin:0 0 14px;text-indent:2em;text-align:justify}
.wx-law{color:var(--brand);font-weight:600}
.wx-art{color:#b45309;font-weight:600}
/* 结构化正文（含原文排版/图片）渲染样式 */
#wx-body{font-size:16px;line-height:2;color:var(--ink-2)}
#wx-body section{margin:0}
#wx-body p{margin:0 0 14px;text-indent:2em;text-align:justify}
#wx-body h1,#wx-body h2,#wx-body h3,#wx-body h4{font-size:17px;font-weight:700;
  color:var(--ink);margin:22px 0 10px;line-height:1.7}
#wx-body blockquote{margin:0 0 14px;padding:10px 16px;background:#f6f8fb;
  border-left:3px solid var(--brand);border-radius:8px;color:var(--muted)}
#wx-body ul,#wx-body ol{margin:0 0 14px;padding-left:1.6em}
#wx-body li{margin:4px 0}
#wx-body img{max-width:100%;height:auto;border-radius:10px;margin:16px auto;
  display:block;box-shadow:0 1px 3px rgba(0,0,0,.08);background:#f3f4f6}
#wx-body table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
#wx-body th,#wx-body td{border:1px solid var(--line);padding:7px 10px;text-align:left}
#wx-body hr{border:0;border-top:1px solid var(--line);margin:18px 0}
#wx-body a{color:var(--brand)}
#wx-body .wx-law{color:var(--brand);font-weight:600}
#wx-body .wx-art{color:#b45309;font-weight:600}
.wx-badge{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;
  background:#eaf6f3;color:#0f7b6c;border:1px solid #cfe8e2;margin-left:8px;vertical-align:middle;
  font-family:var(--sans)}
.rd-empty{color:var(--faint);text-align:center;padding:60px 0;font-size:14px}
@media print{.topnav,.subnav,.mod-bound,footer,.rd-side,.rd-bar,.wx-receipt{display:none!important}
  .rd{grid-template-columns:1fr}.paper{border:0;box-shadow:none;padding:0}}
"""

JS = r"""
(function(){
  var IX=[], CUR=null, ORG='', Q='', CACHE={}, TEXT='';
  var $=function(s){return document.querySelector(s)};
  /* 注意：索引里的 chars 是数字，转义函数必须先 String() —— 否则 (123).replace 抛 TypeError */
  var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})};

  /* 正文按篇懒加载：kb/wx/m/<id>.json 含 {html, text}，单篇约 8 KB。
     绝不在目录页内联全部正文，也不为每篇生成独立 HTML 页面。 */
  function loadBody(x){
    var box=document.getElementById('wx-body');
    if(!box) return;
    if(CACHE[x.id]){ box.innerHTML=CACHE[x.id].html; TEXT=CACHE[x.id].text||''; return; }
    box.innerHTML='<div class="rd-empty">正在载入原文…</div>';
    fetch('wx/m/'+x.id+'.json').then(function(r){return r.json()}).then(function(d){
      CACHE[x.id]=d;
      var el=document.getElementById('wx-body');
      if(el && CUR && CUR.id===x.id){ el.innerHTML=d.html; TEXT=d.text||''; }
    });
  }

  function render(){
    var box=$('#rd-main');
    if(!CUR){
      box.innerHTML='<div class="rd-splash"><b>左侧共 '+IX.length+' 篇官方公众号原文存档。</b><br>'+
        '这里存放的是<b>只在发布机关官方微信公众号发布、PC 官网无对应页</b>的执法通报与典型案例：'+
        '已按发布机关存档全文，可检索、可深链、可下载，不会因公众号链接失效而失联。<br>'+
        '点选任意一条即可在此阅读全文。可被外部直接定位：<code>wx.html#w-原文id</code>。</div>';
      return;
    }
    if(!CUR.__html){
      CUR.__html='<div class="wx-title">'+esc(CUR.title)+'</div>'+
        '<div class="wx-org">'+esc(CUR.org||'')+'<span class="wx-badge">官方公众号</span></div>'+
        '<hr class="wx-rule"><div id="wx-body"><div class="rd-empty">正在载入原文…</div></div>'+
        '<div class="rd-meta">'+
          (CUR.org?'发布机关：'+esc(CUR.org)+'　':'')+
          (CUR.account?'公众号：'+esc(CUR.account)+'　':'')+
          (CUR.gh?'gh：'+esc(CUR.gh)+'　':'')+
          (CUR.pub?'发布：'+esc(CUR.pub)+'　':'')+
          esc(CUR.chars||'')+' 字<br>'+
          '原文由发布机关官方微信公众号发布，本页为站内全文存档（公众号链接为临时地址、不可长期引用）。'+
        '</div>';
    }
    box.innerHTML='<div class="rd-bar"><div class="rd-seg">'+
      '<button id="wx-copy">复制全文</button>'+
      '<button id="wx-txt">下载 TXT</button>'+
      '<button id="wx-print">打印 / 存 PDF</button>'+
      '</div></div><div class="paper">'+CUR.__html+'</div>';
    $('#wx-copy').onclick=function(){ copy(TEXT); };
    $('#wx-txt').onclick=function(){ dl(TEXT); };
    $('#wx-print').onclick=function(){ window.print(); };
    loadBody(CUR);
  }

  function copy(t){
    if(!t) return;
    if(navigator.clipboard) navigator.clipboard.writeText(t).then(function(){ toast('已复制全文'); });
    else { var a=document.createElement('textarea'); a.value=t; document.body.appendChild(a);
           a.select(); document.execCommand('copy'); a.remove(); toast('已复制全文'); }
  }
  function dl(t){
    if(!t) return;
    var b=new Blob([t],{type:'text/plain;charset=utf-8'});
    var a=document.createElement('a');
    a.href=URL.createObjectURL(b);
    a.download=((CUR&&CUR.title)||'公众号原文')+'.txt';
    a.click(); URL.revokeObjectURL(a.href);
  }
  function toast(m){
    var d=document.createElement('div');
    d.textContent=m;
    d.style.cssText='position:fixed;left:50%;bottom:40px;transform:translateX(-50%);background:#1f2937;'+
      'color:#fff;font-size:13.5px;padding:9px 18px;border-radius:999px;z-index:99';
    document.body.appendChild(d);
    setTimeout(function(){ d.remove(); }, 1600);
  }

  function list(){
    var arr=IX.filter(function(x){
      if(ORG && x.org!==ORG) return false;
      if(!Q) return true;
      var hay=(x.title+' '+x.org+' '+x.account+' '+(x.topic||'')).toLowerCase();
      return hay.indexOf(Q.toLowerCase())>=0;
    });
    $('#rd-count').textContent='共 '+arr.length+' 篇'+(IX.length!==arr.length?('（全库 '+IX.length+' 篇）'):'');
    var ul=$('#rd-list');
    ul.innerHTML=arr.map(function(x){
      return '<li><button data-id="'+x.id+'"'+(CUR&&CUR.id===x.id?' class="on"':'')+'>'+
        esc(x.title)+'<span class="lv">'+esc(x.org||x.account)+' · '+esc(x.pub||'')+'</span></button></li>';
    }).join('')||'<li style="padding:12px;color:var(--faint);font-size:13px">没有匹配的存档</li>';
    ul.querySelectorAll('button').forEach(function(b){
      b.onclick=function(){ location.hash='w-'+b.dataset.id; };
    });
  }

  function chips(){
    var seen={}, arr=[];
    IX.forEach(function(x){ var k=x.org||x.account||'未标注';
      if(!seen[k]){ seen[k]=1; arr.push(k); } });
    arr.sort(function(a,b){ return a.localeCompare(b,'zh'); });
    var box=$('#rd-chips');
    box.innerHTML='<span class="rd-chip'+(ORG?'':' on')+'" data-org="">全部机构（'+IX.length+'）</span>'+
      arr.map(function(k){
        var n=IX.filter(function(x){return (x.org||x.account||'未标注')===k}).length;
        return '<span class="rd-chip'+(ORG===k?' on':'')+'" data-org="'+esc(k)+'">'+esc(k)+'（'+n+'）</span>';
      }).join('');
    box.querySelectorAll('.rd-chip').forEach(function(c){
      c.onclick=function(){ ORG=c.dataset.org; chips(); list(); };
    });
  }

  function find(id){ for(var i=0;i<IX.length;i++) if(IX[i].id===id) return IX[i]; return null; }

  function open(id){
    CUR=find(id);
    render();          /* render 内部已按需 loadBody，勿在此重复调用 */
    list();
  }

  fetch('wx/index.json').then(function(r){return r.json()}).then(function(d){
    IX=d.items||[];
    chips();
    function fromUrl(){
      var h=(location.hash||'').slice(1).replace(/^w-/,'');
      if(h) return h;
      try{ return new URLSearchParams(location.search).get('id')||''; }catch(e){ return ''; }
    }
    function sync(){
      try{
        var id=fromUrl();
        if(id) open(id); else { CUR=null; render(); }
        list();
      }catch(e){
        /* 出错时不留白屏：把原因显式写出来，便于定位（静态页无后端日志） */
        var b=$('#rd-main');
        if(b) b.innerHTML='<div class="rd-empty">页面脚本异常：'+
          esc((e&&e.message)||String(e))+'</div>';
        if(window.console) console.error(e);
      }
    }
    window.addEventListener('hashchange',sync);
    sync();
    $('#rd-q').addEventListener('input',function(e){ Q=e.target.value.trim(); list(); });
  });
})();
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>公众号原文存档 · 合规无终点</title>
<meta name="description" content="发布机关官方微信公众号发布的执法通报与典型案例全文存档：地方监管机构只在公众号发布、官网无对应页的内容，在此逐篇存档、可检索、可下载，不会因外链失效而失联。">
<link rel="stylesheet" href="../assets/style.css">
<style>@@CSS@@</style>
<!-- SOCIAL:START -->
<!-- SOCIAL:END -->
</head>
<body>

<nav class="topnav"><div class="inner">
  <a class="brand" href="../index.html">合规<span>无终点</span></a>
  <div class="navlinks">
    <a href="../index.html">首页</a>
    <a href="../news/index.html">合规动态</a>
    <a href="../analysis/index.html">法律分析</a>
    <a href="../manage/index.html">合规管理</a>
    <a href="../kb/index.html">合规知识库</a>
    <a href="../about.html">关于</a>
  </div>
</div></nav>
<!-- SUBNAV:START --><!-- SUBNAV:END -->

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 公众号原文存档</div>
  <h1>公众号原文存档</h1>
  <p>发布机关<b>官方微信公众号</b>发布的执法通报与典型案例，逐篇存档全文，可检索、可深链、可下载。<br>
     收录对象是<b>只在公众号发布、PC 官网没有对应页</b>的内容——这类来源无法提供长期有效的外部深链，故以站内原文存档方式溯源。</p>
</div></div>

<main class="wrap">
  <p class="rd-note">本站引源口径：立法、法规标准发布与生效、合规专项行动、监管处罚案例<b>只引官方原文</b>。
     微信公众号域名不含机构信息，故存档时逐篇核验发布账号主体（记录公众号名称与 <code>gh_</code> 永久唯一号）、
     保留发布日期与正文全文。公众号文章链接为带签名的临时地址、随时失效，因此本站<b>不提供微信外链</b>，
     以「发布机关 + 账号主体 + 发布日期 + 全文」作为可核验的溯源凭据。仅供个人学习研究，正式引用请以官方发布版本为准。</p>
  <div class="rd">
    <aside class="rd-side">
      <input id="rd-q" class="rd-box" type="search" placeholder="按标题、机构或主题检索">
      <div class="rd-chips" id="rd-chips"></div>
      <div class="rd-count" id="rd-count"></div>
      <ul class="rd-list" id="rd-list"></ul>
    </aside>
    <section class="rd-main" id="rd-main">
      <div class="rd-splash"><b>正在载入存档目录…</b></div>
    </section>
  </div>
</main>

<footer><div class="inner"></div></footer>
<script>@@JS@@</script>
</body>
</html>
"""


def main():
    arts = load_articles()
    if not arts:
        print("sources/wx/ 下没有可用的存档")
        return
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(OUT, "m"), exist_ok=True)

    arts.sort(key=lambda d: (d.get("pub") or "", d.get("fetched") or ""), reverse=True)

    items, replaces = [], {}
    for n, d in enumerate(arts):
        org = norm_org(d)
        items.append({
            "id": d["id"],
            "title": unesc(d.get("title") or ""),
            "org": org,
            "account": unesc(d.get("account") or ""),
            "gh": d.get("gh") or "",
            "pub": d.get("pub") or "",
            "chars": int(d.get("chars") or len(d.get("body") or "")),
            "topic": unesc(d.get("topic") or ""),
            "kind": d.get("kind") or "执法通报",
        })
        for u in (d.get("replaces") or []):
            replaces[u.strip()] = {"wx_id": d["id"], "title": unesc(d.get("title") or ""),
                                   "org": org, "pub": d.get("pub") or ""}

    # 单篇正文：{id}.json 含 {html, text}，约 8 KB/篇，按需懒加载。
    # 不为每篇生成独立 HTML 页面（那是站点体积失控的根源）。
    mdir = os.path.join(OUT, "m")
    for f in os.listdir(mdir):
        if f.endswith(".json") and f[:-5] not in {d["id"] for d in arts}:
            os.remove(os.path.join(mdir, f))
    used_imgs = set()
    for d in arts:
        html_body = (d.get("html_body") or "").strip()
        if html_body:
            # 结构化正文：先剥模板尾巴，再上色渲染；图片已是本地相对地址
            html_body = strip_tail(html_body)
            html = render_html_body(html_body)
            text = re.sub(r"[ \t\u00a0]+", " ", re.sub(r"<[^>]+>", "", html_body))
        else:
            # 旧版纯文本存档兜底（无 html_body 字段）
            body = strip_tail(d.get("body") or "")
            html = render_body(body)
            text = re.sub(r"[ \t\u00a0]+", " ", body)
        for im in re.findall(r'src="(img/[^"]+)"', html):
            used_imgs.add(os.path.basename(im))
        json.dump({"html": html, "text": text},
                  open(os.path.join(mdir, f"{d['id']}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    # 清理无正文引用的孤儿图片，避免站点体积无谓膨胀
    img_dir = os.path.join(OUT, "img")
    if os.path.isdir(img_dir):
        for fn in os.listdir(img_dir):
            if fn not in used_imgs:
                try:
                    os.remove(os.path.join(img_dir, fn))
                except OSError:
                    pass

    # 清掉早期分片方案留下的 p-NN.json（已改为单篇懒加载）
    for old in os.listdir(OUT):
        if re.match(r"p-\d+\.json$", old):
            os.remove(os.path.join(OUT, old))

    orgs = {}
    for it in items:
        orgs[it["org"]] = orgs.get(it["org"], 0) + 1

    json.dump({
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(items),
        "total_chars": sum(x["chars"] for x in items),
        "orgs": [{"org": k, "n": v} for k, v in sorted(orgs.items(), key=lambda x: -x[1])],
        "items": items,
    }, open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(replaces, open(os.path.join(SRC, "replaces.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    page = HTML.replace("@@CSS@@", CSS).replace("@@JS@@", JS)
    open(PAGE, "w", encoding="utf-8").write(page)

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(OUT) for f in fs)
    per = size / max(len(items), 1) / 1024
    print(f"公众号原文存档：{len(items)} 篇 / {sum(x['chars'] for x in items)} 字 / "
          f"页面体积 {size/1024:.1f} KB（{per:.1f} KB/篇，按需懒加载）")
    print(f"  → kb/wx.html + kb/wx/index.json + kb/wx/m/<id>.json（单篇正文）")
    print(f"  → sources/wx/replaces.json（{len(replaces)} 条原二手来源映射）")
    if replaces:
        for u, v in replaces.items():
            print(f"     {u[:66]} → #{v['wx_id']}")


if __name__ == "__main__":
    main()
