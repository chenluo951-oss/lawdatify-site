/* art-card.js —— 法条悬浮卡（对标北大法宝「法宝之窗」）
 * 2026-09-17 P1-1：页面里的《XX 法》第 X 条，鼠标悬停即浮出该条原文、官方原文入口
 * 与引用它的案例链接，不用跳页、不丢阅读上下文。
 *
 * 数据（kb/arts.js，366 KB）**按需加载**：先扫文本，页面里真的存在可解析的引用时
 * 才去拉数据 —— 首页这类没有法条引用的页面不会白付这 366 KB。
 *
 * 设计约束：
 *   · 只对**构建期真的解析出条文**的引用挂浮层（键不存在就原样保留文字，绝不弹空卡）。
 *   · 零依赖，不改动任何页面自有脚本；注入的 DOM 全部带 ak-/artref 前缀。
 *   · 不绑定数百个监听：事件委托 + 一次性文本节点扫描 + 增量 MutationObserver。
 *   · 卡片可停留（鼠标能移进卡片点链接），Esc / 滚动 / 缩放即关闭。
 */
(function () {
  var ARTS = null, loading = false, waiters = [];

  // ---- 站点根路径：从样式表 href 反推，兼容根目录 / kb/ / news/ / analysis/ / manage/
  var link = document.querySelector('link[href*="assets/style.css"]');
  var ROOT = link ? link.getAttribute('href').replace(/assets\/style\.css.*$/, '') : '';
  var me = document.currentScript;
  // 数据文件路径由构建期写进 data-arts（带版本号，便于改名/缓存失效）；
  // 没有该属性时退回 kb/arts.js。
  var DATA_URL = (me && me.getAttribute('data-arts')) || (ROOT + 'kb/arts.js');
  var TEXTS = ROOT + 'kb/texts.html';
  var CASES = ROOT + 'kb/cases.html';

  var RX = /《([^》\n]{2,60})》(第[一二三四五六七八九十百千零〇0-9]+条)/g;
  var SKIP = { A: 1, SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1, CODE: 1, PRE: 1, SVG: 1,
               H1: 1, H2: 1, H3: 1, BUTTON: 1, SELECT: 1, OPTION: 1, FIGCAPTION: 1 };
  var SKIP_CLS = ['topnav', 'subnav', 'foot', 'ak-pop', 'lv-t', 'artref',
                  'cs-q', 'lb-q', 'prac-fig', 'lb-toclist', 'pagehead'];

  function nkey(name) {
    var s = String(name || '').replace(/[\s\u3000《》]/g, '');
    s = s.replace(/^中华人民共和国/, '');
    s = s.replace(/[（(][^）)]{0,12}(修订|修正|草案|征求意见稿)[）)]$/, '');
    return s.length < 3 ? '' : s;
  }
  function keyOf(law, art) {
    var k = nkey(law);
    return k ? k + '|' + art : '';
  }
  function esc(v) {
    return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ---- 数据按需加载
  function ensureArts(cb) {
    if (ARTS) { cb(); return; }
    waiters.push(cb);
    if (loading) return;
    loading = true;
    var s = document.createElement('script');
    s.src = DATA_URL;
    s.async = true;
    s.onload = s.onerror = function () {
      ARTS = window.LD_ARTS || {};
      var q = waiters; waiters = [];
      loading = false;
      q.forEach(function (f) { try { f(); } catch (e) { /* 静默 */ } });
    };
    document.head.appendChild(s);
  }

  function skipNode(n) {
    for (var p = n.parentNode; p && p.nodeType === 1; p = p.parentNode) {
      if (SKIP[p.tagName]) return true;
      var c = p.className;
      if (typeof c === 'string' && c) {
        for (var i = 0; i < SKIP_CLS.length; i++) {
          if (c.indexOf(SKIP_CLS[i]) > -1) return true;
        }
      }
      if (p === document.body) break;
    }
    return false;
  }

  // ---- 找出候选文本节点（此时不需要数据）
  function candidates(root) {
    if (!root || !root.nodeType) return [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var jobs = [], n;
    while ((n = walker.nextNode())) {
      var t = n.nodeValue;
      if (!t || t.length < 6 || t.indexOf('第') < 0 || t.indexOf('》') < 0) continue;
      RX.lastIndex = 0;
      if (!RX.test(t)) continue;
      if (skipNode(n)) continue;
      jobs.push(n);
    }
    return jobs;
  }

  // ---- 把候选节点里的引用包成 .artref（只在有条文数据时）
  function wrapNodes(jobs) {
    var hits = 0;
    jobs.forEach(function (node) {
      if (!node.isConnected) return;
      var t = node.nodeValue, out = document.createDocumentFragment(), last = 0, m, ok = false;
      RX.lastIndex = 0;
      while ((m = RX.exec(t))) {
        var k = keyOf(m[1], m[2]);
        if (!k || !ARTS[k]) continue;
        ok = true;
        if (m.index > last) out.appendChild(document.createTextNode(t.slice(last, m.index)));
        var sp = document.createElement('span');
        sp.className = 'artref';
        sp.setAttribute('data-ak', k);
        sp.title = '悬停查看条文原文';
        sp.textContent = m[0];
        out.appendChild(sp);
        last = m.index + m[0].length;
        hits++;
      }
      if (!ok) return;
      if (last < t.length) out.appendChild(document.createTextNode(t.slice(last)));
      node.parentNode.replaceChild(out, node);
    });
    return hits;
  }

  function scan(root) {
    var jobs = candidates(root);
    if (!jobs.length) return;
    ensureArts(function () { wrapNodes(jobs); });
  }

  // ---- 浮层
  var pop = document.createElement('div');
  pop.className = 'ak-pop';
  pop.setAttribute('role', 'tooltip');
  pop.hidden = true;
  document.body.appendChild(pop);
  var curKey = null, showT = null, hideT = null;

  function fill(k) {
    var a = ARTS[k]; if (!a) return false;
    var law = a[2] || '', art = k.split('|')[1] || '';
    var st = a[5] || '', impl = a[6] || '', ncase = a[4] || 0, rows = a[7] || [];
    var h = '<div class="ak-hd"><b>' + esc(law) + '</b><span class="ak-art">' + esc(art)
      + '</span><em class="ak-st">' + esc(st) + (impl ? ' · 施行 ' + esc(impl) : '')
      + '</em></div>';
    h += '<div class="ak-q">' + esc(a[0] || '') + '</div>';
    if (rows.length) {
      h += '<div class="ak-cs-h">引用本条的案例 ' + ncase + ' 条</div><ul class="ak-cs">';
      rows.forEach(function (c) {
        h += '<li><a href="' + CASES + '#' + esc(c[0]) + '" target="_blank" rel="noopener">'
          + esc(c[1] || '（未标注标题）') + '</a><em>' + esc(c[2] || '') + ' · ' + esc(c[3] || '')
          + '</em></li>';
      });
      if (ncase > rows.length) h += '<li class="ak-more">此处只列前 ' + rows.length + ' 条</li>';
      h += '</ul>';
    }
    h += '<div class="ak-ft">';
    h += '<a href="' + TEXTS + '#' + esc(a[1]) + '|' + esc(art) + '" target="_blank" '
      + 'rel="noopener">在本站原文库中定位</a>';
    if (a[3]) h += '<a href="' + esc(a[3]) + '" target="_blank" rel="noopener">官方发布页 &#8599;</a>';
    h += '<span class="ak-cav">条文逐字取自我站官方原文库；引用前请核对现行有效版本</span>';
    h += '</div>';
    pop.innerHTML = h;
    return true;
  }

  function place(el) {
    var r = el.getBoundingClientRect();
    pop.style.visibility = 'hidden';
    pop.hidden = false;
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - w - 12));
    var top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) {
      var up = r.top - h - 8;
      top = up > 8 ? up : Math.max(8, window.innerHeight - h - 8);
    }
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
    pop.style.visibility = '';
  }

  function show(el) {
    if (!ARTS) { scan(el); return; }
    var k = el.getAttribute('data-ak');
    if (!k || !ARTS[k]) return;
    if (curKey !== k) { if (!fill(k)) return; curKey = k; }
    pop.hidden = false;
    place(el);
    el.classList.add('artref-on');
  }

  function hide() {
    pop.hidden = true;
    curKey = null;
    var on = document.querySelector('.artref-on');
    if (on) on.classList.remove('artref-on');
  }

  document.addEventListener('mouseover', function (e) {
    var el = e.target.closest ? e.target.closest('.artref') : null;
    if (!el) return;
    if (hideT) { clearTimeout(hideT); hideT = null; }
    if (showT) clearTimeout(showT);
    showT = setTimeout(function () { show(el); }, 170);
  }, true);

  document.addEventListener('mouseout', function (e) {
    var el = e.target.closest ? e.target.closest('.artref') : null;
    if (!el) return;
    if (showT) { clearTimeout(showT); showT = null; }
    hideT = setTimeout(hide, 240);   // 留出鼠标从词条移到浮层点链接的时间
  }, true);

  pop.addEventListener('mouseenter', function () {
    if (hideT) { clearTimeout(hideT); hideT = null; }
  });
  pop.addEventListener('mouseleave', function () { hideT = setTimeout(hide, 160); });

  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('.artref') : null;
    if (!el) return;
    e.preventDefault();
    if (curKey && !pop.hidden) hide(); else show(el);
  });

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });
  window.addEventListener('scroll', function () { if (!pop.hidden) hide(); }, true);
  window.addEventListener('resize', hide);

  // ---- 首次扫描 + 动态列表增量扫描（法规库列表、案例筛选都是 JS 渲染的）
  function boot() {
    scan(document.body);
    var pend = [], t = null;
    var mo = new MutationObserver(function (recs) {
      recs.forEach(function (r) {
        for (var i = 0; i < r.addedNodes.length; i++) {
          var x = r.addedNodes[i];
          if (x.nodeType === 1 && x.className !== 'ak-pop') pend.push(x);
        }
      });
      if (!pend.length) return;
      if (t) clearTimeout(t);
      t = setTimeout(function () {
        var list = pend; pend = [];
        list.forEach(function (x) { if (x.isConnected) scan(x); });
      }, 260);
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
