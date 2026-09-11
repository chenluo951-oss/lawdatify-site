#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_audit.py —— 生成「合规审计」模块 kb/audit.html

能力：
  ① 从合规义务清单（sources/standards/duties.json，10 大类 / 47 场景 / 143 项义务）勾选审计范围；
  ② 生成审计任务，逐项填写审计进度、审计素材、审计结论、审计说明；
  ③ 汇总生成审计报告（含覆盖范围、结论分布、不符合项清单）与整改任务清单；
  ④ 数据存本机浏览器 localStorage，支持导出/导入 JSON 备份与导出报告 HTML。

产出：kb/audit.html（单页应用，零依赖，数据与页面同源，不联网）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DUTY_SRC = os.path.join(HERE, "sources", "standards", "duties.json")
OUT = os.path.join(HERE, "kb", "audit.html")

PAGE_CSS = """
.aud-lead{font-size:14.5px;color:var(--muted);line-height:1.95;margin:0 0 18px;max-width:880px}
.aud-steps{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.aud-step{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);
  border-radius:11px;padding:10px 16px;cursor:pointer;font-size:13.5px;color:var(--muted);
  font-family:var(--sans)}
.aud-step i{width:22px;height:22px;border-radius:50%;background:#eef2f7;color:var(--ink-2);
  display:flex;align-items:center;justify-content:center;font-size:12px;font-style:normal;font-weight:700}
.aud-step.on{border-color:var(--brand);color:var(--ink);box-shadow:0 0 0 3px #e8f0fa}
.aud-step.on i{background:var(--brand);color:#fff}
.aud-step.done i{background:var(--accent);color:#fff}
.aud-card{background:#fff;border:1px solid var(--line);border-radius:13px;padding:18px 20px;margin-bottom:14px}
.aud-card h3{margin:0 0 12px;font-size:15.5px;font-weight:800;color:var(--ink)}
.aud-row{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:12px}
.aud-f{flex:1;min-width:190px}
.aud-f label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:5px}
.aud-f input,.aud-f select,.aud-f textarea{width:100%;box-sizing:border-box;padding:8px 11px;
  border:1px solid var(--line);border-radius:8px;font-size:14px;font-family:var(--sans);
  color:var(--ink);background:#fff;outline:none}
.aud-f textarea{min-height:64px;line-height:1.75;resize:vertical}
.aud-f input:focus,.aud-f textarea:focus,.aud-f select:focus{border-color:var(--brand)}
.aud-btn{font-size:13px;padding:7px 15px;border-radius:8px;border:1px solid var(--line);background:#fff;
  color:var(--ink-2);cursor:pointer;font-family:var(--sans)}
.aud-btn:hover{border-color:var(--brand);color:var(--brand)}
.aud-btn.pri{background:var(--brand);border-color:var(--brand);color:#fff}
.aud-btn.pri:hover{background:#16406f;color:#fff}
.aud-btn.warn{border-color:#e8a33d;color:#8a3b12}
.aud-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.aud-chips{display:flex;flex-wrap:wrap;gap:6px}
.aud-chip{font-size:12.5px;padding:4px 11px;border-radius:999px;border:1px solid var(--line);
  background:#fff;color:var(--muted);cursor:pointer;font-family:var(--sans)}
.aud-chip.on{background:var(--ink);border-color:var(--ink);color:#fff}
.aud-cat{border:1px solid var(--line);border-radius:11px;margin-bottom:10px;overflow:hidden}
.aud-cat-h{display:flex;align-items:center;gap:10px;padding:12px 15px;background:#fafbfd;cursor:pointer}
.aud-cat-h b{font-size:14.5px;color:var(--ink)}
.aud-cat-h .n{font-size:12px;color:var(--faint);margin-left:auto}
.aud-scene{padding:4px 15px 12px 15px;border-top:1px solid var(--line-2)}
.aud-scene h4{margin:12px 0 7px;font-size:13px;color:var(--brand);letter-spacing:.3px}
.aud-d{display:flex;gap:9px;padding:8px 0;border-bottom:1px dashed var(--line-2);font-size:13.5px}
.aud-d:last-child{border-bottom:0}
.aud-d input[type=checkbox]{margin-top:4px;width:15px;height:15px;flex:0 0 auto;accent-color:#1b4f8a}
.aud-d .t{font-weight:600;color:var(--ink);line-height:1.6}
.aud-d .d{color:var(--muted);font-size:13px;line-height:1.8;margin-top:3px}
.aud-d .r{font-size:11.5px;padding:1px 8px;border-radius:999px;margin-left:6px;white-space:nowrap}
.r-高{background:#fdeaea;color:#b3261e}
.r-中{background:#fdf3e3;color:#9a6108}
.r-低{background:#eaf5ee;color:#20603a}
.aud-refs{font-size:11.5px;color:var(--faint);margin-top:4px}
.aud-art{font-size:12.5px;color:var(--ink-2);background:#fafbfd;border-left:3px solid var(--line);
  padding:7px 10px;border-radius:0 6px 6px 0;margin-top:6px;line-height:1.85;max-height:180px;overflow:auto}
.aud-stat{display:flex;flex-wrap:wrap;gap:22px;padding-bottom:14px;border-bottom:1px solid var(--line-2);margin-bottom:14px}
.aud-stat .it .v{font-size:24px;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.aud-stat .it .l{font-size:12px;color:var(--muted);margin-top:2px}
.aud-bar{height:9px;border-radius:5px;background:#eef2f7;overflow:hidden;display:flex;margin-bottom:6px}
.aud-bar i{display:block;height:100%}
.aud-task{border:1px solid var(--line);border-radius:11px;padding:13px 15px;margin-bottom:10px;background:#fff}
.aud-task-h{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px}
.aud-task-h .no{font-size:12px;color:var(--faint);font-variant-numeric:tabular-nums}
.aud-task-h .tt{font-size:14.5px;font-weight:700;color:var(--ink);flex:1;min-width:180px}
.aud-st{font-size:11.5px;padding:2px 9px;border-radius:999px;background:#eef2f7;color:var(--ink-2)}
.aud-st.done{background:#eaf5ee;color:#20603a}
.aud-st.bad{background:#fdeaea;color:#b3261e}
.aud-st.wip{background:#fdf3e3;color:#9a6108}
.aud-flex{display:flex;flex-wrap:wrap;gap:8px;margin-top:9px}
.aud-flex .aud-f{min-width:150px}
.aud-report{background:#fff;border:1px solid var(--line);border-radius:13px;padding:26px 30px}
.aud-report h2{font-size:20px;margin:0 0 6px;text-align:center;color:var(--ink)}
.aud-report .sub{text-align:center;font-size:12.5px;color:var(--muted);margin-bottom:18px}
.aud-report h3{font-size:14.5px;margin:22px 0 9px;padding-left:9px;border-left:3px solid var(--brand);
  color:var(--ink)}
.aud-report table{width:100%;border-collapse:collapse;font-size:12.5px}
.aud-report th,.aud-report td{border:1px solid var(--line);padding:7px 9px;text-align:left;
  line-height:1.75;vertical-align:top}
.aud-report th{background:#fafbfd;font-weight:700;color:var(--ink-2)}
.aud-empty{color:var(--faint);font-size:14px;padding:40px 0;text-align:center}
.aud-note{font-size:12.5px;color:var(--faint);line-height:1.9;margin:20px 0 0}
.view{display:none}.view.on{display:block}
@media print{
  .topnav,.subnav,.mod-bound,footer,.pagehead,.aud-steps,.aud-lead,.aud-note,.aud-tools,#toTop{display:none !important}
  .aud-report{border:0;padding:0}
  .wrap{max-width:100%;padding:0}
  @page{size:A4;margin:1.8cm}
}
"""

PAGE_JS = r"""
var DUTIES = __DUTIES__;
var LS_KEY = 'prm_audit_v1';
var S = { tasks: [], cur: null, sel: {}, view: 'scope' };

function $(s){ return document.querySelector(s); }
function $$(s){ return [].slice.call(document.querySelectorAll(s)); }
function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function uid(){ return 'A' + Date.now().toString(36) + Math.random().toString(36).slice(2,5); }
function today(){ var d=new Date(); return d.toISOString().slice(0,10); }

function save(){ try{ localStorage.setItem(LS_KEY, JSON.stringify({tasks:S.tasks, cur:S.cur})); }catch(e){} }
function load(){
  try{ var d=JSON.parse(localStorage.getItem(LS_KEY)||'{}');
    S.tasks=d.tasks||[]; S.cur=d.cur||null; }catch(e){ S.tasks=[]; S.cur=null; }
  if(!S.tasks.length){ S.tasks=[newTask('默认审计任务')]; S.cur=S.tasks[0].id; }
  if(!S.tasks.filter(function(t){return t.id===S.cur}).length) S.cur=S.tasks[0].id;
}
function curTask(){ return S.tasks.filter(function(t){return t.id===S.cur})[0]; }
function newTask(name){
  return { id: uid(), name: name||('合规审计任务 ' + today()), period: '', owner: '', dept: '',
           due: '', basis: '', created: today(), summary: '', items: {}, remark: '' };
}

/* ---------- 视图切换 ---------- */
function go(v){
  S.view=v;
  $$('.view').forEach(function(x){ x.className='view'; });
  $('#v-'+v).className='view on';
  $$('.aud-step').forEach(function(x){ x.className='aud-step'+(x.dataset.v===v?' on':''); });
  if(v==='run') renderRun();
  if(v==='report') renderReport();
  window.scrollTo({top:0,behavior:'smooth'});
}

/* ---------- ① 范围配置 ---------- */
var DM = {}; DUTIES.categories.forEach(function(c){ DM[c.id]=c.name; });

function renderScope(){
  var box=$('#aud-tree'); box.innerHTML='';
  DUTIES.categories.forEach(function(c){
    var total=0, checked=0;
    c.scenes.forEach(function(sc){ sc.duties.forEach(function(d,i){
      total++; if(S.sel[c.id+'|'+i]!==undefined && S.item(c.id,i)) {} }); });
    var cat = document.createElement('div'); cat.className='aud-cat';
    var done=0, seln=0;
    c.scenes.forEach(function(sc){ sc.duties.forEach(function(d,i){
      done++; if(S.sel[key(c.id,sc,d)]===1) seln++; }); });
    var h=document.createElement('div'); h.className='aud-cat-h';
    h.innerHTML='<input type="checkbox" '+(seln===done&&done?'checked':'')+'>'+
      '<b>'+esc(c.name)+'</b><span class="n">已选 '+seln+' / '+done+' 项</span>';
    h.querySelector('input').onclick=function(ev){
      ev.stopPropagation();
      var on=ev.target.checked;
      c.scenes.forEach(function(sc){ sc.duties.forEach(function(d,i){
        var k=key(c.id,sc,d); if(on) S.sel[k]=1; else delete S.sel[k]; }); });
      save(); renderScope();
    };
    cat.appendChild(h);
    var sd=document.createElement('div'); sd.className='aud-scene';
    c.scenes.forEach(function(sc){
      sd.innerHTML += '<h4>'+esc(sc.name)+'</h4>';
      sc.duties.forEach(function(d,i){
        var k=key(c.id,sc,d);
        var on=S.sel[k]===1?'checked':'';
        var arts=(d.articles||[]).map(function(a){
          return '<div class="aud-art"><b>'+esc(a.src||a.doc||'')+' '+esc(a.art||'')+'</b><br>'+esc(a.quote||'')+'</div>';
        }).join('');
        sd.innerHTML += '<label class="aud-d"><input type="checkbox" data-k="'+esc(k)+'" '+on+'>'+
          '<div><div class="t">'+esc(d.t)+'<span class="r r-'+esc(d.risk||'中')+'">'+(d.risk||'中')+'风险</span></div>'+
          '<div class="d">'+esc(d.d||'')+'</div>'+
          (d.refs&&d.refs.length?'<div class="aud-refs">依据：'+esc(d.refs.join(' · '))+'</div>':'')+
          arts+'</div></label>';
      });
    });
    cat.appendChild(sd);
    box.appendChild(cat);
  });
  box.querySelectorAll('input[data-k]').forEach(function(cb){
    cb.onchange=function(){ if(cb.checked) S.sel[cb.dataset.k]=1; else delete S.sel[cb.dataset.k];
      save(); updateSelCount(); };
  });
  updateSelCount();
}
function key(cid, sc, d){ return cid+'||'+sc.name+'||'+d.t; }
function selList(){
  var out=[];
  DUTIES.categories.forEach(function(c){
    c.scenes.forEach(function(sc){
      sc.duties.forEach(function(d){
        var k=key(c.id,sc,d);
        if(S.sel[k]===1) out.push({k:k, cid:c.id, cat:c.name, scene:sc.name, d:d});
      });
    });
  });
  return out;
}
function updateSelCount(){
  var n=selList().length;
  $('#aud-selcount').textContent='已选 '+n+' 项义务';
  $('#aud-ok-scope').disabled = n===0;
}
function quickScope(mode){
  var q=$('#aud-search').value.trim();
  DUTIES.categories.forEach(function(c){
    c.scenes.forEach(function(sc){
      sc.duties.forEach(function(d){
        var hit = q && ((d.t+d.d+(d.refs||[]).join('')).indexOf(q)>=0);
        var k=key(c.id,sc,d);
        if(mode==='all') S.sel[k]=1;
        else if(mode==='none') delete S.sel[k];
        else if(mode==='high'){ if(d.risk==='高') S.sel[k]=1; else delete S.sel[k]; }
        else if(mode==='find' && hit) S.sel[k]=1;
      });
    });
  });
  save(); renderScope();
}

/* ---------- ② 生成任务 ---------- */
function createTask(){
  var list=selList();
  if(!list.length){ alert('请先勾选需要审计的合规义务。'); return; }
  var t=newTask($('#aud-name').value.trim()||('合规审计任务 '+today()));
  t.period=$('#aud-period').value.trim(); t.owner=$('#aud-owner').value.trim();
  t.dept=$('#aud-dept').value.trim(); t.due=$('#aud-due').value;
  var refs={}; list.forEach(function(x){ (x.d.refs||[]).forEach(function(r){ refs[r]=1; }); });
  t.basis=Object.keys(refs).join('、');
  t.scope=list.map(function(x){ return {k:x.k, cid:x.cid, cat:x.cat, scene:x.scene, t:x.d.t,
    d:x.d.d, risk:x.d.risk||'中', refs:x.d.refs||[] }; });
  t.items={};
  t.scope.forEach(function(x){ t.items[x.k]={ status:'未开始', concl:'', mat:'', note:'' }; });
  S.tasks.push(t); S.cur=t.id; save(); go('run');
}

/* ---------- ③ 执行审计 ---------- */
var ST_CLS={'未开始':'','进行中':'wip','已完成':'done','不适用':''};
var CC_CLS={'符合':'done','基本符合':'wip','不符合':'bad','不适用':''};
function renderRun(){
  var t=curTask(); if(!t){ $('#aud-run').innerHTML='<div class="aud-empty">暂无审计任务。</div>'; return; }
  var items=t.scope||[];
  var st={}; items.forEach(function(x){ var it=t.items[x.k]||{}; var s=it.status||'未开始'; st[s]=(st[s]||0)+1; });
  var done=st['已完成']||0, total=items.length;
  var cc={}; items.forEach(function(x){ var c=(t.items[x.k]||{}).concl||''; if(c) cc[c]=(cc[c]||0)+1; });
  var bad=cc['不符合']||0;
  var html='<div class="aud-card">'+
   '<div class="aud-stat">'+
     '<div class="it"><div class="v">'+total+'</div><div class="l">审计项</div></div>'+
     '<div class="it"><div class="v">'+done+'</div><div class="l">已完成</div></div>'+
     '<div class="it"><div class="v">'+(total-done)+'</div><div class="l">待推进</div></div>'+
     '<div class="it"><div class="v" style="color:#b3261e">'+bad+'</div><div class="l">不符合项</div></div>'+
     '<div class="it"><div class="v">'+Math.round(done/Math.max(1,total)*100)+'%</div><div class="l">完成度</div></div>'+
   '</div>'+
   '<div class="aud-bar"><i style="width:'+(done/Math.max(1,total)*100)+'%;background:#20603a"></i>'+
     '<i style="width:'+(bad/Math.max(1,total)*100)+'%;background:#b3261e"></i>'+
     '<i style="width:'+(((total-done-bad)>0?(total-done-bad):0)/Math.max(1,total)*100)+'%;background:#e8a33d"></i></div>'+
   '<div class="aud-task-h"><span class="no">'+esc(t.id)+'</span>'+
     '<span class="tt">'+esc(t.name)+'</span>'+
     '<span class="aud-st">责任人 '+esc(t.owner||'待指定')+'</span>'+
     '<span class="aud-st">截止 '+esc(t.due||'待定')+'</span>'+
     '<span class="aud-st">'+esc(t.period||'审计期间未填')+'</span></div>'+
   '<div class="aud-tools">'+
     '<button class="aud-btn pri" onclick="go(\'report\')">生成审计报告</button>'+
     '<button class="aud-btn" onclick="go(\'scope\')">调整审计范围</button>'+
     '<button class="aud-btn" onclick="exportJSON()">导出任务 JSON</button>'+
     '<button class="aud-btn" onclick="exportReport()">导出报告 HTML</button>'+
   '</div></div>';
  items.forEach(function(x,i){
    var it=t.items[x.k]||{};
    html+='<div class="aud-task" data-k="'+esc(x.k)+'">'+
      '<div class="aud-task-h"><span class="no">'+(i+1)+'</span>'+
      '<span class="tt">'+esc(x.t)+'</span>'+
      '<span class="aud-st r-'+esc(x.risk)+'">'+esc(x.risk)+'风险</span>'+
      '<span class="aud-st '+esc(ST_CLS[it.status||'未开始'])+'">'+esc(it.status||'未开始')+'</span>'+
      (it.concl?'<span class="aud-st '+esc(CC_CLS[it.concl]||'')+'">'+esc(it.concl)+'</span>':'')+
      '</div>'+
      '<div class="aud-flex">'+
        '<div class="aud-f"><label>审计进度</label><select data-f="status">'+
          ['未开始','进行中','已完成','不适用'].map(function(o){
            return '<option'+(o===(it.status||'未开始')?' selected':'')+'>'+o+'</option>';}).join('')+
        '</select></div>'+
        '<div class="aud-f"><label>审计结论</label><select data-f="concl">'+
          ['','符合','基本符合','不符合','不适用'].map(function(o){
            return '<option value="'+o+'"'+(o===(it.concl||'')?' selected':'')+'>'+(o||'未判定')+'</option>';}).join('')+
        '</select></div>'+
      '</div>'+
      '<div class="aud-f"><label>审计素材（检查了哪些制度、系统、日志、截图、访谈记录）</label>'+
        '<textarea data-f="mat">'+esc(it.mat||'')+'</textarea></div>'+
      '<div class="aud-f" style="margin-top:9px"><label>审计说明 / 问题描述 / 整改要求</label>'+
        '<textarea data-f="note">'+esc(it.note||'')+'</textarea></div>'+
      '<div class="aud-flex">'+
        '<div class="aud-f"><label>整改责任人</label><input data-f="fowner" value="'+esc((it.fowner)||'')+'"></div>'+
        '<div class="aud-f"><label>整改期限</label><input type="date" data-f="fdue" value="'+esc((it.fdue)||'')+'"></div>'+
        '<div class="aud-f" style="flex:2"><label>整改措施</label><input data-f="faction" value="'+esc((it.faction)||'')+'"></div>'+
      '</div>'+
      '<div class="aud-refs" style="margin-top:8px">依据：'+esc((x.refs||[]).join(' · ')||'—')+
        (x.d?'<br>义务要点：'+esc(x.d):'')+'</div>'+
      '</div>';
  });
  $('#aud-run').innerHTML=html;
  $$('#aud-run [data-f]').forEach(function(el){
    el.onchange=el.oninput=function(){
      var k=el.closest('.aud-task').dataset.k;
      t.items[k]=t.items[k]||{}; t.items[k][el.dataset.f]=el.value; save();
      if(el.dataset.f==='status'||el.dataset.f==='concl') renderRun();
    };
  });
}

/* ---------- ④ 报告 ---------- */
function statOf(t){
  var items=t.scope||[], done=0, cc={};
  items.forEach(function(x){ var it=t.items[x.k]||{};
    if((it.status||'')==='已完成') done++;
    var c=it.concl||''; if(c) cc[c]=(cc[c]||0)+1; });
  return {total:items.length, done:done, cc:cc,
          bad:items.filter(function(x){ return (t.items[x.k]||{}).concl==='不符合'; })};
}
function renderReport(){
  var t=curTask(); if(!t){ $('#aud-report').innerHTML='<div class="aud-empty">暂无审计任务。</div>'; return; }
  $('#aud-report').innerHTML=reportHTML(t);
}
function reportHTML(t){
  var s=statOf(t), items=t.scope||[];
  var rows=items.map(function(x,i){
    var it=t.items[x.k]||{};
    var fix=(it.concl==='不符合'||it.concl==='基本符合')?'':''; 
    return '<tr><td>'+(i+1)+'</td><td>'+esc(x.cat)+'</td><td>'+esc(x.t)+
      '</td><td>'+esc(x.risk)+'</td><td>'+esc(it.status||'未开始')+
      '</td><td>'+esc(it.concl||'未判定')+'</td><td>'+esc(it.mat||'')+
      '</td><td>'+esc(it.note||'')+'</td></tr>';
  }).join('');
  var fixRows=items.filter(function(x){ var it=t.items[x.k]||{};
      return it.concl==='不符合'||it.concl==='基本符合'||it.status==='进行中'; })
    .map(function(x,i){ var it=t.items[x.k]||{};
      return '<tr><td>'+(i+1)+'</td><td>'+esc(x.t)+'</td><td>'+esc(it.concl||'待判定')+
        '</td><td>'+esc(it.note||'')+'</td><td>'+esc(it.fowner||'')+'</td><td>'+
        esc(it.fdue||'')+'</td><td>'+esc(it.faction||'')+'</td></tr>'; }).join('');
  return '<div class="aud-card">'+
    '<div class="aud-tools">'+
      '<button class="aud-btn pri" onclick="window.print()">打印 / 存为 PDF</button>'+
      '<button class="aud-btn" onclick="exportReport()">导出报告 HTML</button>'+
      '<button class="aud-btn" onclick="exportJSON()">导出任务 JSON</button>'+
    '</div></div>'+
    '<div class="aud-report">'+
      '<h2>'+esc(t.name)+'</h2>'+
      '<div class="sub">审计期间：'+esc(t.period||'—')+' ｜ 责任部门：'+esc(t.dept||'—')+
        ' ｜ 责任人：'+esc(t.owner||'—')+' ｜ 出具日期：'+today()+'</div>'+
      '<h3>一、审计范围与依据</h3>'+
      '<p style="font-size:13px;line-height:1.95">本次审计覆盖 '+s.total+' 项合规义务，'+
        '分属 '+new Set(items.map(function(x){return x.cat})).size+' 个主题大类。'+
        '主要依据：'+esc(t.basis||'—')+'。</p>'+
      '<h3>二、审计结论汇总</h3>'+
      '<p style="font-size:13px;line-height:1.95">已完成 '+s.done+' 项，完成度 '+
        Math.round(s.done/Math.max(1,s.total)*100)+'%。'+
        '结论分布：符合 '+(s.cc['符合']||0)+' 项 · 基本符合 '+(s.cc['基本符合']||0)+
        ' 项 · 不符合 '+(s.cc['不符合']||0)+' 项 · 不适用 '+(s.cc['不适用']||0)+
        ' 项 · 未判定 '+(s.total-(s.cc['符合']||0)-(s.cc['基本符合']||0)-(s.cc['不符合']||0)-(s.cc['不适用']||0))+' 项。</p>'+
      '<h3>三、逐项审计记录</h3>'+
      '<table><thead><tr><th>#</th><th>主题大类</th><th>合规义务</th><th>风险</th>'+
        '<th>进度</th><th>结论</th><th>审计素材</th><th>说明</th></tr></thead><tbody>'+
        (rows||'<tr><td colspan="8">无</td></tr>')+'</tbody></table>'+
      '<h3>四、整改任务清单</h3>'+
      (fixRows?('<table><thead><tr><th>#</th><th>不合规/观察项</th><th>结论</th><th>问题描述</th>'+
        '<th>责任人</th><th>期限</th><th>整改措施</th></tr></thead><tbody>'+fixRows+'</tbody></table>')
        :'<p style="font-size:13px;color:#6b7a8c">本次审计未产生不符合项与整改任务。</p>')+
      '<h3>五、总体意见</h3>'+
      '<p style="font-size:13px;line-height:1.95">'+esc(t.summary||
        '（请在本机编辑器中补充总体意见：对合规现状的总体判断、需要管理层关注的高风险事项、下一步工作建议。）')+'</p>'+
      '<p style="font-size:11.5px;color:#94a3b4;margin-top:22px;line-height:1.9">'+
        '本报告由站内合规审计模块生成，审计记录与结论由审计人员填写，数据保存在本机浏览器中。</p>'+
    '</div>';
}
function exportReport(){
  var t=curTask();
  dl(t.name+'_审计报告.html',
     '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+esc(t.name)+
     '</title><style>body{font-family:"PingFang SC","Microsoft YaHei",sans-serif;max-width:900px;'+
     'margin:36px auto;padding:0 20px;color:#16202c;line-height:1.8}'+
     'h2{text-align:center;font-size:22px}.sub{text-align:center;color:#6b7a8c;font-size:12.5px;margin-bottom:18px}'+
     'h3{font-size:15px;border-left:3px solid #1b4f8a;padding-left:9px;margin:24px 0 10px}'+
     'table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{border:1px solid #e6ebf2;padding:7px 9px;'+
     'vertical-align:top;text-align:left}th{background:#fafbfd}</style></head><body>'+
     reportHTML(t).replace(/<div class="aud-card">[\s\S]*?<\/div><\/div>/,'')+'</body></html>');
}
function exportJSON(){
  var t=curTask();
  dl(t.name+'_审计任务.json', JSON.stringify(t,null,1));
}
function dl(name,content){
  var a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([content],{type:'text/html;charset=utf-8'}));
  a.download=name; document.body.appendChild(a); a.click();
  setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); },900);
}

/* ---------- 任务管理 ---------- */
function renderTasks(){
  var box=$('#aud-tasks');
  box.innerHTML=S.tasks.map(function(t){
    var s=statOf(t);
    return '<div class="aud-task"><div class="aud-task-h">'+
      '<span class="tt">'+esc(t.name)+'</span>'+
      '<span class="aud-st">'+s.total+' 项</span>'+
      '<span class="aud-st done">完成 '+s.done+'</span>'+
      (s.bad.length?'<span class="aud-st bad">不符合 '+s.bad.length+'</span>':'')+
      '<span class="aud-st">'+esc(t.created)+'</span>'+
      '<button class="aud-btn" onclick="pick(\''+t.id+'\')">打开</button>'+
      '<button class="aud-btn warn" onclick="delTask(\''+t.id+'\')">删除</button>'+
      '</div></div>';
  }).join('')||'<div class="aud-empty">暂无审计任务。</div>';
}
function pick(id){ S.cur=id; save(); go('run'); }
function delTask(id){
  if(!confirm('确定删除该审计任务？删除后不可恢复。')) return;
  S.tasks=S.tasks.filter(function(t){return t.id!==id});
  if(!S.tasks.length) S.tasks=[newTask('默认审计任务')];
  if(S.cur===id) S.cur=S.tasks[0].id;
  save(); renderTasks();
}
function addTask(){ S.tasks.push(newTask()); S.cur=S.tasks[S.tasks.length-1].id; save(); renderTasks(); }
function importJSON(ev){
  var f=ev.target.files[0]; if(!f) return;
  var r=new FileReader();
  r.onload=function(){
    try{
      var d=JSON.parse(r.result);
      if(d.scope&&d.items){ S.tasks.push(d); S.cur=d.id; }
      else if(d.tasks){ d.tasks.forEach(function(t){S.tasks.push(t)}); S.cur=d.cur||S.tasks[0].id; }
      else throw 0;
      save(); renderTasks(); go('run');
    }catch(e){ alert('文件格式无法识别，请选择本模块导出的 JSON。'); }
  };
  r.readAsText(f); ev.target.value='';
}
function saveTaskMeta(){
  var t=curTask(); if(!t) return;
  t.name=$('#m-name').value.trim()||t.name; t.period=$('#m-period').value.trim();
  t.owner=$('#m-owner').value.trim(); t.dept=$('#m-dept').value.trim();
  t.due=$('#m-due').value; t.summary=$('#m-summary').value; save();
}

/* ---------- 初始化 ---------- */
load();
renderScope(); renderTasks();
$('#aud-ok-scope').onclick=createTask;
$('#aud-search').addEventListener('input',function(){});
document.querySelectorAll('.aud-step').forEach(function(b){ b.onclick=function(){ go(b.dataset.v); }; });
$$('.aud-chip[data-q]').forEach(function(b){ b.onclick=function(){ quickScope(b.dataset.q); }; });
['m-name','m-period','m-owner','m-dept','m-due','m-summary'].forEach(function(id){
  var el=document.getElementById(id); if(el) el.addEventListener('input',saveTaskMeta);
});
go('scope');
"""

PAGE_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>合规审计 · 合规无终点</title>
<meta name="description" content="从合规义务清单勾选审计范围，生成审计任务，逐项记录审计进度、审计素材与审计结论，一键输出审计报告与整改任务清单。">
<link rel="stylesheet" href="../assets/style.css">
<style>__CSS__</style>
</head>
<body>

<nav class="topnav"></nav>
<!-- SUBNAV:START --><!-- SUBNAV:END -->

<div class="pagehead"><div class="inner">
  <div class="crumb"><a href="../index.html">首页</a> / <a href="index.html">合规知识库</a> / 合规审计</div>
  <h1>合规审计</h1>
  <p>审计范围直接取自合规义务清单：勾选义务 → 生成审计任务 → 记录审计进度、审计素材与审计结论 → 输出审计报告与整改任务清单。</p>
</div></div>

<main class="wrap">
  <p class="aud-lead">共 __NCAT__ 个主题大类、__NSCENE__ 个业务场景、__NDUTY__ 项具体义务可供勾选。
     每个审计项都可回填审计素材（制度、系统、日志、截图、访谈记录）与审计结论，不符合项自动进入整改任务清单。</p>

  <div class="aud-steps">
    <div class="aud-step on" data-v="scope"><i>1</i>配置审计范围</div>
    <div class="aud-step" data-v="run"><i>2</i>执行审计</div>
    <div class="aud-step" data-v="report"><i>3</i>审计报告与整改</div>
  </div>

  <!-- ① 范围 -->
  <section class="view on" id="v-scope">
    <div class="aud-card">
      <h3>审计任务信息</h3>
      <div class="aud-row">
        <div class="aud-f"><label>任务名称</label><input id="aud-name" placeholder="如：2026 年第三季度个人信息保护专项审计"></div>
        <div class="aud-f"><label>审计期间</label><input id="aud-period" placeholder="如：2026-07-01 至 2026-09-30"></div>
      </div>
      <div class="aud-row">
        <div class="aud-f"><label>责任部门</label><input id="aud-dept" placeholder="如：法务合规部"></div>
        <div class="aud-f"><label>责任人</label><input id="aud-owner" placeholder="姓名"></div>
        <div class="aud-f"><label>完成期限</label><input type="date" id="aud-due"></div>
      </div>
      <div class="aud-tools">
        <button class="aud-btn pri" id="aud-ok-scope" disabled>生成审计任务</button>
        <span class="aud-st" id="aud-selcount">已选 0 项义务</span>
      </div>
    </div>

    <div class="aud-card">
      <h3>勾选审计范围</h3>
      <div class="aud-tools">
        <input class="aud-btn" id="aud-search" placeholder="按关键词筛选（如：个人信息、算法备案、价格）" style="min-width:260px;padding:7px 11px">
        <div class="aud-chips">
          <button class="aud-chip" data-q="all">全选</button>
          <button class="aud-chip" data-q="high">只选高风险</button>
          <button class="aud-chip" data-q="find">选命中关键词</button>
          <button class="aud-chip" data-q="none">清空</button>
        </div>
      </div>
      <div id="aud-tree"></div>
    </div>
  </section>

  <!-- ② 执行 -->
  <section class="view" id="v-run"><div id="aud-run"></div></section>

  <!-- ③ 报告 -->
  <section class="view" id="v-report">
    <div class="aud-card">
      <h3>任务信息与总体意见</h3>
      <div class="aud-row">
        <div class="aud-f"><label>任务名称</label><input id="m-name"></div>
        <div class="aud-f"><label>审计期间</label><input id="m-period"></div>
      </div>
      <div class="aud-row">
        <div class="aud-f"><label>责任部门</label><input id="m-dept"></div>
        <div class="aud-f"><label>责任人</label><input id="m-owner"></div>
        <div class="aud-f"><label>完成期限</label><input type="date" id="m-due"></div>
      </div>
      <div class="aud-f"><label>总体意见（会写入报告的第五部分）</label>
        <textarea id="m-summary" placeholder="对合规现状的总体判断、需要管理层关注的高风险事项、下一步工作建议"></textarea></div>
    </div>
    <div id="aud-report"></div>
  </section>

  <div class="aud-card" style="margin-top:18px">
    <h3>审计任务管理</h3>
    <div class="aud-tools">
      <button class="aud-btn" onclick="addTask()">新建空白任务</button>
      <label class="aud-btn" style="margin:0">导入任务 JSON
        <input type="file" accept=".json" onchange="importJSON(event)" style="display:none"></label>
    </div>
    <div id="aud-tasks"></div>
  </div>

  <p class="aud-note">数据保存在本机浏览器（localStorage），不会上传到任何服务器；换设备或清理浏览器数据前请先导出 JSON 备份，再用「导入任务 JSON」恢复。</p>
</main>

<footer></footer>
<script>__JS__</script>
</body>
</html>
"""


def main():
    d = json.load(open(DUTY_SRC, encoding="utf-8"))
    cats = d["categories"]
    # 精简：articles 的 quote 截到 400 字，控制页面体积
    slim = json.loads(json.dumps(d, ensure_ascii=False))
    for c in slim["categories"]:
        for sc in c.get("scenes", []):
            for du in sc.get("duties", []):
                for a in du.get("articles", []) or []:
                    if a.get("quote") and len(a["quote"]) > 400:
                        a["quote"] = a["quote"][:400] + "……"
                du.pop("rel", None)
    n_duty = sum(len(s.get("duties", [])) for c in cats for s in c.get("scenes", []))
    n_scene = sum(len(c.get("scenes", [])) for c in cats)
    js = PAGE_JS.replace("__DUTIES__", json.dumps(slim, ensure_ascii=False, separators=(",", ":")))
    html = (PAGE_TPL.replace("__CSS__", PAGE_CSS.strip())
            .replace("__JS__", js)
            .replace("__NCAT__", str(len(cats)))
            .replace("__NSCENE__", str(n_scene))
            .replace("__NDUTY__", str(n_duty)))
    open(OUT, "w", encoding="utf-8").write(html)
    print("合规审计页：kb/audit.html（%d 大类 / %d 场景 / %d 义务 / %.0f KB）"
          % (len(cats), n_scene, n_duty, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
