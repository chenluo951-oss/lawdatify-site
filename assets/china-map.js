/* 中国省级监管态势地图（下钻视图，共享组件）
 *
 * 用法：
 *   ChinaView.render({
 *     mount: '#geoMap',                 // 复用世界地图容器
 *     dataUrl: '../sources/radar/china.json',
 *     onProvClick: function(name, count){},  // 点击省级要素回调
 *     onReady: function(){}
 *   });
 *
 * 合规说明：省界取自 DataV.GeoAtlas（含南海诸岛与九段线要素；台湾省、香港、澳门
 * 为独立省级要素，均属中国）。Albers 等积圆锥投影的示意性视图，非地理精确边界，
 * 不承担划界意义；运行时不请求任何在线地图服务。
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

  var lastData = null;

  function render(opts) {
    var mount = document.querySelector(opts.mount);
    if (!mount) return;
    fetch(opts.dataUrl)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        lastData = data;
        var provs = data.provinces || [];
        var h = [];
        h.push('<svg class="geo-svg cn-svg" viewBox="' + esc(data.viewBox) +
               '" role="img" aria-label="中国省级监管动态分布地图（示意）">');
        provs.forEach(function (p) {
          if (!p.name || p.name === '南海诸岛') {
            // 南海诸岛与九段线：仅描边示意，保证地图完整规范
            h.push('<path class="cn-sjxt" d="' + p.path + '"/>');
            return;
          }
          var n = (p.items || []).length;
          h.push('<g class="cgeo ' + HEAT[heat(n)] + (n ? ' cn-has' : '') +
                 '" data-name="' + esc(p.name) + '" tabindex="0" role="button" aria-label="' +
                 esc(p.short) + ' ' + n + ' 条动态">');
          h.push('<path d="' + p.path + '"/>');
          h.push('</g>');
        });
        h.push('</svg>');
        mount.innerHTML = h.join('');

        mount.addEventListener('click', function (e) {
          var g = e.target.closest('.cgeo');
          if (!g) return;
          var name = g.getAttribute('data-name');
          var p = lastData.provinces.find(function (x) { return x.name === name; });
          var n = p && p.items ? p.items.length : 0;
          if (opts.onProvClick) opts.onProvClick(name, n);
        });
        mount.addEventListener('keydown', function (e) {
          if (e.key !== 'Enter' && e.key !== ' ') return;
          var g = e.target.closest('.cgeo');
          if (!g) return;
          e.preventDefault();
          g.dispatchEvent(new Event('click', { bubbles: true }));
        });
        mount.addEventListener('mousemove', function (e) {
          var g = e.target.closest('.cgeo');
          if (!g) { ensureTip().style.display = 'none'; return; }
          var name = g.getAttribute('data-name');
          var p = lastData.provinces.find(function (x) { return x.name === name; });
          var n = p && p.items ? p.items.length : 0;
          var extra = p && p.items && p.items[0] ? p.items[0].title : '';
          moveTip(e, '<b>' + esc(p ? p.short : name) + '</b>' +
            (n ? '<span>' + n + ' 条地方动态</span>' : '<span>暂无收录的地方动态</span>') +
            (extra ? '<i>' + esc(extra) + '</i>' : ''));
        });
        mount.addEventListener('mouseleave', function () {
          ensureTip().style.display = 'none';
        });

        if (opts.onReady) opts.onReady(lastData);
      })
      .catch(function () {
        mount.innerHTML = '<p class="rd-note">中国地图加载失败，请刷新重试。</p>';
      });
  }

  global.ChinaView = { render: render, heat: heat };
})(window);
