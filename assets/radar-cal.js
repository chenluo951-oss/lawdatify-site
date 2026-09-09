/* lawdatify 合规日历组件（共享）——真正的月历网格
 *
 * 数据由页面内嵌：window.CAL_DATA = { domains:{...}, items:[...] }
 * 依赖样式：assets/style.css 中 .cal-* 系列与 .rd-item
 */
(function (global) {
  'use strict';

  var state = { y: 0, m: 0, dom: 'ALL', picked: null };
  var DOW = ['一', '二', '三', '四', '五', '六', '日'];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function iso(y, m, d) {
    return y + '-' + ('0' + m).slice(-2) + '-' + ('0' + d).slice(-2);
  }

  function todayIso() {
    var t = new Date();
    return iso(t.getFullYear(), t.getMonth() + 1, t.getDate());
  }

  var byDate = {};
  function index() {
    byDate = {};
    (window.CAL_DATA.items || []).forEach(function (it) {
      if (state.dom !== 'ALL' && it.domain !== state.dom) return;
      (byDate[it.date] = byDate[it.date] || []).push(it);
    });
  }

  function renderNav(mount) {
    var d = window.CAL_DATA;
    var chips = ['<button class="rd-fchip' + (state.dom === 'ALL' ? ' on' : '') +
      '" data-dom="ALL">全部</button>'];
    Object.keys(d.domains || {}).forEach(function (dm) {
      chips.push('<button class="rd-fchip' + (state.dom === dm ? ' on' : '') +
        '" data-dom="' + esc(dm) + '"><i class="cal-dot" style="background:' +
        d.domains[dm] + '"></i>' + esc(dm) + '</button>');
    });
    mount.querySelector('.cal-doms').innerHTML = chips.join('');
  }

  function renderGrid(mount) {
    var y = state.y, m = state.m;
    var first = new Date(y, m - 1, 1);
    var start = (first.getDay() + 6) % 7;          // 周一=0
    var dim = new Date(y, m, 0).getDate();         // 本月天数
    var prevDim = new Date(y, m - 1, 0).getDate();
    var today = todayIso();

    var rows = Math.ceil((start + dim) / 7);
    var h = [];
    for (var r = 0; r < rows; r++) {
      h.push('<div class="cal-row">');
      for (var c = 0; c < 7; c++) {
        var cellNo = r * 7 + c;
        var d, out = false;
        if (cellNo < start) { d = prevDim - start + 1 + cellNo; out = true; }
        else if (cellNo >= start + dim) { d = cellNo - start - dim + 1; out = true; }
        else { d = cellNo - start + 1; }
        var yy = y, mm = m;
        if (out && cellNo < start) { mm -= 1; if (mm === 0) { mm = 12; yy -= 1; } }
        if (out && cellNo >= start + dim) { mm += 1; if (mm === 13) { mm = 1; yy += 1; } }
        var key = iso(yy, mm, d);
        var evs = byDate[key] || [];
        var cls = 'cal-cell' + (out ? ' out' : '') + (key === today ? ' today' : '') +
          (key === state.picked ? ' picked' : '');
        h.push('<div class="' + cls + '" data-d="' + key + '">');
        h.push('<b class="cal-d">' + d + '</b>');
        if (evs.length) {
          h.push('<div class="cal-evs">');
          evs.slice(0, 2).forEach(function (it) {
            h.push('<a class="cal-ev" href="' + esc(it.url) +
              '" target="_blank" rel="noopener" title="' + esc(it.title) +
              '"><i style="background:' + (window.CAL_DATA.domains[it.domain] || '#999') +
              '"></i>' + esc(it.title) + '</a>');
          });
          if (evs.length > 2) {
            h.push('<span class="cal-more">+' + (evs.length - 2) + '</span>');
          }
          h.push('</div>');
          h.push('<span class="cal-badge">' + evs.length + '</span>');
        }
        h.push('</div>');
      }
      h.push('</div>');
    }
    mount.querySelector('.cal-body').innerHTML = h.join('');
    mount.querySelector('.cal-title').textContent = y + ' 年 ' + m + ' 月';
    var cnt = Object.keys(byDate).length;
    mount.querySelector('.cal-sub').textContent =
      (state.dom === 'ALL' ? '全部领域' : state.dom) + ' · 本月 ' +
      countMonth(y, m) + ' 个节点';
  }

  function countMonth(y, m) {
    var pre = iso(y, m, 1).slice(0, 7);
    var n = 0;
    Object.keys(byDate).forEach(function (k) {
      if (k.slice(0, 7) === pre) n += byDate[k].length;
    });
    return n;
  }

  function renderDetail(mount) {
    var box = mount.parentElement.querySelector('#calDetail');
    if (!box) return;
    if (!state.picked) { box.innerHTML = ''; return; }
    var evs = byDate[state.picked] || [];
    var head = '<div class="cal-detail-h">『' + state.picked + '』' +
      (evs.length ? evs.length + ' 个节点' : '无收录节点') +
      '<button class="cal-close" aria-label="关闭">×</button></div>';
    var rows = evs.map(function (it) {
      return '<div class="rd-item"><div class="rd-body">' +
        '<div class="rd-row"><span class="rd-badge ' + badge(it.type) + '">' +
        esc(it.type) + '</span><span class="rd-tags">' +
        '<span class="rd-tag">' + esc(it.domain || '') + '</span>' +
        '<span class="rd-tag tg-region">' + esc(it.regionName || it.region || '') +
        '</span></span></div>' +
        '<h3><a href="' + esc(it.url) + '" target="_blank" rel="noopener">' +
        esc(it.title) + '</a>' + srcTag(it.src) + '</h3>' +
        '<div class="rd-meta">' + esc(it.issuer || '') + '</div>' +
        '<p>' + esc(it.note || '') + '</p></div></div>';
    }).join('');
    box.innerHTML = head + (rows ||
      '<p class="rd-note">该日暂无已收录节点。收录标准见页面底部说明。</p>');
    var close = box.querySelector('.cal-close');
    if (close) close.addEventListener('click', function () {
      state.picked = null; renderDetail(mount); renderGrid(mount);
    });
  }

  function badge(t) {
    if (/意见|立法|草案/.test(t)) return 'b-blue';
    if (/截止|宽限|评估/.test(t)) return 'b-amber';
    if (/调查|执法|治理|检查/.test(t)) return 'b-red';
    if (/司法|规则|制度/.test(t)) return 'b-purple';
    return 'b-green';
  }
  function srcTag(s) {
    return s === 'official'
      ? '<span class="rd-src src-off">官方原文</span>'
      : '<span class="rd-src src-ana">专业解读</span>';
  }

  function init(mountSel) {
    var mount = document.querySelector(mountSel);
    if (!mount || !window.CAL_DATA) return;
    var t = new Date();
    state.y = t.getFullYear(); state.m = t.getMonth() + 1;

    index(); renderNav(mount); renderGrid(mount);

    mount.addEventListener('click', function (e) {
      var chip = e.target.closest('.cal-doms .rd-fchip');
      if (chip) {
        state.dom = chip.getAttribute('data-dom');
        index(); renderNav(mount); renderGrid(mount); renderDetail(mount);
        return;
      }
      if (e.target.closest('.cal-prev')) {
        state.m -= 1; if (state.m === 0) { state.m = 12; state.y -= 1; }
        renderGrid(mount); return;
      }
      if (e.target.closest('.cal-next')) {
        state.m += 1; if (state.m === 13) { state.m = 1; state.y += 1; }
        renderGrid(mount); return;
      }
      if (e.target.closest('.cal-today-btn')) {
        state.y = t.getFullYear(); state.m = t.getMonth() + 1;
        renderGrid(mount); return;
      }
      var cell = e.target.closest('.cal-cell');
      if (cell) {
        state.picked = cell.getAttribute('data-d');
        renderGrid(mount); renderDetail(mount);
        var box = mount.parentElement.querySelector('#calDetail');
        if (box) box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  }

  global.RadarCal = { init: init };
})(window);
