/* 数据看板交互层（2026-09-18）
 * ---------------------------------------------------------------
 * 用户诉求：「驾驶舱所有数字应该可以点击」。
 * 数字可点，必须**点到有用的地方**，否则只是把静态表格变成会跳的静态表格。
 * 本文件实现一条最短链路：矩阵 / 柱条里的任意一个数字 → 落到同一页的明细表并按
 * 该维度过滤 → 顶部出现可清除的条件条与命中数。零依赖，纯 hash 驱动。
 *
 * 约定
 *   data-flt="org=广东省通信管理局&y=2025"     可点数字（点它 = 设条件 + 滚到明细）
 *   data-docrow data-org=… data-y=…           明细行（过滤对象）
 *                data-k=… data-p=… data-c=… data-prob="… …"
 *   #f=<encodeURIComponent(查询串)>           过滤状态（可分享、可后退）
 */
(function () {
  var ROWS = null, BAR = null, TBL = null;
  var FIELDS = ["org", "y", "k", "p", "c", "prob"];
  var LABEL = { org: "发布主体", y: "年度", k: "文书类型", p: "属地", c: "名单载体", prob: "问题类型" };

  function enc(q) {
    var out = [];
    for (var i = 0; i < FIELDS.length; i++) {
      var k = FIELDS[i];
      if (q[k]) out.push(k + "=" + encodeURIComponent(q[k]));
    }
    return out.join("&");
  }
  function dec(s) {
    var q = {};
    (s || "").split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      var k = i < 0 ? kv : kv.slice(0, i);
      var v = i < 0 ? "" : decodeURIComponent(kv.slice(i + 1));
      if (FIELDS.indexOf(k) >= 0 && v) q[k] = v;
    });
    return q;
  }
  function hit(row, q) {
    for (var i = 0; i < FIELDS.length; i++) {
      var k = FIELDS[i];
      if (!q[k]) continue;
      var v = row.getAttribute("data-" + k) || "";
      if (k === "prob") {
        if ((" " + v + " ").indexOf(" " + q[k] + " ") < 0) return false;
      } else if (v !== q[k]) return false;
    }
    return true;
  }
  function collect() {
    if (ROWS) return ROWS;
    TBL = document.getElementById("docTbl");
    if (!TBL) return (ROWS = []);
    ROWS = [].slice.call(TBL.querySelectorAll("tbody tr[data-docrow]"));
    return ROWS;
  }

  function apply(q, scroll) {
    var rows = collect();
    if (!rows.length) return;
    var n = 0, first = null;
    rows.forEach(function (r) {
      var ok = hit(r, q);
      r.hidden = !ok;
      if (ok) { n++; if (!first) first = r; }
    });
    // 条件条
    if (!BAR) {
      BAR = document.createElement("div");
      BAR.id = "fltBar";
      BAR.className = "flt-bar";
      if (TBL.parentNode) TBL.parentNode.insertBefore(BAR, TBL);
    }
    var has = Object.keys(q).length > 0;
    if (!has) {
      BAR.hidden = true;
      BAR.innerHTML = "";
    } else {
      var chips = FIELDS.filter(function (k) { return q[k]; }).map(function (k) {
        return '<span class="fb-q">' + LABEL[k] + '：<b>' + q[k].replace(/[<>&]/g, "") + "</b></span>";
      }).join("");
      BAR.hidden = false;
      BAR.innerHTML = chips +
        '<span class="fb-n">命中 <b>' + n + "</b> / 全库 " + rows.length + " 份</span>" +
        '<a class="fb-x" href="#f=">清除筛选</a>';
    }
    // 计数与空态
    var cnt = document.getElementById("docCnt");
    if (cnt) cnt.textContent = n;
    var empty = document.getElementById("docEmpty");
    if (empty) empty.hidden = n > 0;
    if (has) {
      history.replaceState(null, "", "#f=" + enc(q));
      if (scroll && first) {
        first.classList.remove("flash-hit");
        void first.offsetWidth;
        first.classList.add("flash-hit");
        var y = first.getBoundingClientRect().top + window.scrollY - 90;
        window.scrollTo({ top: y, behavior: "smooth" });
      }
    } else if (location.hash) {
      history.replaceState(null, "", location.pathname + location.search);
    }
  }

  function boot() {
    var m = /(?:^|[#&])f=([^&]*)/.exec(location.hash || "");
    apply(dec(m ? m[1] : ""), false);

    document.addEventListener("click", function (e) {
      var el = e.target.closest ? e.target.closest("[data-flt]") : null;
      if (!el) return;
      e.preventDefault();
      apply(dec(el.getAttribute("data-flt")), true);
    });
    window.addEventListener("hashchange", function () {
      var mm = /(?:^|[#&])f=([^&]*)/.exec(location.hash || "");
      apply(dec(mm ? mm[1] : ""), false);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else { boot(); }
})();
