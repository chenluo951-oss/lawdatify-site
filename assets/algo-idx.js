/* 算法备案条目速查（按需加载，2026-09-18）
 * ---------------------------------------------------------------
 * 看板上的「算法备案 1,014 / 深度合成 7,764 / 生成式AI 1,846」如果点了没处去，
 * 就只是读数。本文件把这三类数字接到 10,624 条备案条目上：点数字 → 自动加载索引
 * （1.1 MB，首屏零成本）→ 按该维度过滤并列出条目。
 *
 * 约定
 *   #algoIdx data-idx="…/kb/algo-index.js"   结果容器
 *   [data-ai="s=算法备案&k=个性化推送类"]      可点数字（值即过滤条件）
 *   索引格式：行内 \t 分隔、行间 \n，字段 名称/主体/类别/序列/期次
 */
(function () {
  var RAW = null, ROWS = null, BOX = null, host = "", LIMIT = 300;
  var F = ["n", "sub", "c", "s", "per"];   // 名称 主体 类别 序列 期次
  var LB = { n: "名称", sub: "主体", c: "类别", s: "序列", per: "期次" };

  function box() {
    return BOX || (BOX = document.getElementById("algoIdx"));
  }
  function parse() {
    if (ROWS) return ROWS;
    ROWS = (RAW || "").split("\n").filter(Boolean).map(function (l) { return l.split("\t"); });
    return ROWS;
  }
  function dec(s) {
    var q = {};
    (s || "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i <= 0) return;
      q[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
    });
    return q;
  }
  function esc(s) { return String(s || "").replace(/[<>&]/g, ""); }

  function render(q, kw) {
    var rows = parse(), out = [], n = 0, total = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (q.s && r[3] !== q.s) continue;
      if (q.per && r[4] !== q.per) continue;
      if (q.c && r[2].indexOf(q.c) < 0) continue;
      if (q.n && r[0].indexOf(q.n) < 0) continue;
      if (q.sub && r[1].indexOf(q.sub) < 0) continue;
      if (kw) {
        var s = r.join(" ");
        if (s.toLowerCase().indexOf(kw.toLowerCase()) < 0) continue;
      }
      total++;
      if (out.length < LIMIT) out.push(r);
    }
    n = total;
    var b = box();
    if (!b) return;
    var chips = Object.keys(q).filter(function (k) { return q[k]; }).map(function (k) {
      return '<span class="fb-q">' + LB[k] + '：<b>' + esc(q[k]) + "</b></span>";
    }).join("");
    var rowsHtml = out.map(function (r) {
      return "<tr><td><b>" + esc(r[0]) + "</b></td><td>" + esc(r[1]) + "</td>"
        + '<td><span class="sp-tag">' + esc(r[3]) + "</span>"
        + '<span class="sp-src"> ' + esc(r[2]) + "</span></td>"
        + '<td class="sp-src">' + esc(r[4]) + "</td></tr>";
    }).join("");
    b.innerHTML =
      '<div class="flt-bar"' + (n ? "" : ' hidden') + ">" + chips +
        '<span class="fb-n">命中 <b>' + n + "</b> / 全库 " + rows.length + " 条</span>" +
        '<a class="fb-x" href="#" data-ai-x="1">清除条件</a></div>' +
      '<div class="ai-tool"><input id="aiKw" class="ai-kw" type="search" '
        + 'placeholder="在结果中检索名称 / 主体…" value="' + esc(kw) + '">'
        + '<span class="sp-src">' + (n > LIMIT
          ? "命中 " + n + " 条，此处显示前 " + LIMIT + " 条 —— 加关键词收窄"
          : "共 " + n + " 条") + "</span></div>" +
      '<div class="sp-wrap" style="max-height:min(70vh,760px)"><table class="sp-tbl">'
        + "<thead><tr><th>备案名称</th><th>主体</th><th>序列 / 类别</th><th>期次</th></tr>"
        + "</thead><tbody>" + (rowsHtml || '<tr><td colspan="4" class="sp-src">'
        + "无匹配条目</td></tr>") + "</tbody></table></div>";
    var inp = document.getElementById("aiKw");
    if (inp) {
      inp.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); render(q, inp.value.trim()); }
      });
    }
    var x = b.querySelector("[data-ai-x]");
    if (x) {
      x.addEventListener("click", function (e) {
        e.preventDefault();
        location.hash = "";
        render({}, "");
      });
    }
    var y = b.getBoundingClientRect().top + window.scrollY - 80;
    window.scrollTo({ top: y, behavior: "smooth" });
  }

  function ensure(cb) {
    if (RAW !== null) return cb();
    var s = document.createElement("script");
    var el = box();
    s.src = (el && el.getAttribute("data-idx")) || host || "../kb/algo-index.js";
    s.onload = s.onerror = function () {
      RAW = (window.ALGO_RAW || "");
      cb();
    };
    document.body.appendChild(s);
  }

  function boot() {
    document.addEventListener("click", function (e) {
      var el = e.target.closest ? e.target.closest("[data-ai]") : null;
      if (!el) return;
      e.preventDefault();
      var q = dec(el.getAttribute("data-ai"));
      ensure(function () { render(q, ""); });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else { boot(); }
})();
