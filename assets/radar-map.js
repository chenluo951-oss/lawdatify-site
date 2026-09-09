/* lawdatify 全球监管地图组件（共享）
 *
 * 用法：
 *   RadarMap.render({
 *     mount: '#geoMap',            // 容器选择器
 *     geoUrl: '../sources/radar/geo.json',
 *     counts: {CN: 6, EU: 2},      // 辖区动态条数（页面内嵌提供）
 *     names: {CN: '中国', ...},    // 辖区中文名
 *     tipExtra: {CN: '6 条动态 · 最近 08-07'},  // 可选，tooltip 附加行
 *     onSelect: function(code){},  // 点击辖区回调
 *     selected: null               // 初始选中
 *   });
 *
 * 合规说明：底图为 Natural Earth 110m 公开数据的等距圆柱（Miller）投影
 * 示意性视图；中国（含台湾地区、港澳）在数据生成阶段已合并为同一色块，
 * 不单独着色、不单独标注。运行时不请求任何在线地图服务。
 */
(function (global) {
  'use strict';

  var HEAT = { 0: 'hv0', 1: 'hv1', 2: 'hv2', 3: 'hv3' };

  function heat(n) { return n >= 5 ? 3 : n >= 3 ? 2 : n >= 1 ? 1 : 0; }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var tip = null;

  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'geo-tip';
    tip.setAttribute('aria-hidden', 'true');
    document.body.appendChild(tip);
    return tip;
  }

  function moveTip(e, html) {
    var t = ensureTip();
    t.innerHTML = html;
    t.style.display = 'block';
    var pad = 14;
    var x = e.clientX + pad, y = e.clientY + pad;
    var r = t.getBoundingClientRect();
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - pad;
    t.style.left = x + 'px';
    t.style.top = y + 'px';
  }

  function render(opts) {
    var mount = document.querySelector(opts.mount);
    if (!mount) return;
    fetch(opts.geoUrl)
      .then(function (r) { return r.json(); })
      .then(function (geo) {
        var counts = opts.counts || {};
        var names = opts.names || {};
        var vb = geo.viewBox;

        var h = [];
        h.push('<svg class="geo-svg" viewBox="0 0 ' + vb[0] + ' ' + vb[1] +
               '" role="img" aria-label="全球监管动态分布地图（示意）">');
        h.push('<g class="geo-other">');
        for (var i = 0; i < geo.other.length; i++) {
          h.push('<path d="' + geo.other[i] + '"/>');
        }
        h.push('</g>');

        var groups = geo.groups;
        Object.keys(groups).forEach(function (code) {
          var m = groups[code];
          var n = counts[code] || 0;
          var cls = 'geo ' + HEAT[heat(n)] + (n ? ' geo-has' : '');
          h.push('<g class="' + cls + '" data-code="' + esc(code) +
                 '" tabindex="0" role="button" aria-label="' +
                 esc(names[code] || code) + ' ' + n + ' 条动态">');
          for (var j = 0; j < m.zones.length; j++) {
            h.push('<path d="' + m.zones[j].d + '"/>');
          }
          if (m.anchor) {
            h.push('<circle class="geo-dot" cx="' + m.anchor[0] +
                   '" cy="' + m.anchor[1] + '" r="' + (n ? 7 : 4.5) + '"/>');
          }
          h.push('</g>');
        });
        h.push('</svg>');
        mount.innerHTML = h.join('');

        var sel = opts.selected || null;
        function applySel() {
          mount.querySelectorAll('.geo.on').forEach(function (g) {
            g.classList.remove('on');
          });
          if (sel) {
            var g = mount.querySelector('.geo[data-code="' + sel + '"]');
            if (g) g.classList.add('on');
          }
        }

        mount.addEventListener('click', function (e) {
          var g = e.target.closest('.geo');
          if (!g) return;
          var code = g.getAttribute('data-code');
          if (!(counts[code] > 0)) return;
          sel = (sel === code) ? null : code;
          applySel();
          if (opts.onSelect) opts.onSelect(sel);
        });
        mount.addEventListener('keydown', function (e) {
          if (e.key !== 'Enter' && e.key !== ' ') return;
          var g = e.target.closest('.geo');
          if (!g) return;
          e.preventDefault();
          g.dispatchEvent(new Event('click', { bubbles: true }));
        });
        mount.addEventListener('mousemove', function (e) {
          var g = e.target.closest('.geo');
          if (!g) { ensureTip().style.display = 'none'; return; }
          var code = g.getAttribute('data-code');
          var n = counts[code] || 0;
          var extra = opts.tipExtra && opts.tipExtra[code];
          moveTip(e, '<b>' + esc(names[code] || code) + '</b>' +
            (n ? '<span>' + n + ' 条动态</span>' : '<span>暂无收录动态</span>') +
            (extra ? '<i>' + esc(extra) + '</i>' : ''));
        });
        mount.addEventListener('mouseleave', function () {
          ensureTip().style.display = 'none';
        });

        applySel();
        if (opts.onReady) opts.onReady();
      })
      .catch(function (e) {
        mount.innerHTML = '<p class="rd-note">地图加载失败，请刷新重试。</p>';
      });
  }

  global.RadarMap = { render: render, heat: heat };
})(window);
