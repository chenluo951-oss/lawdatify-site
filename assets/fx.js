/* ==========================================================================
   assets/fx.js —— 设计系统 v3.1「动态控制台」动效层（2026-09-18）

   用户诉求：「科技感不是改改颜色，能不能多加点特效」。
   设计约束（改这个文件前先读）：
     1) 只做**装饰性**动效：扫光带、跑光、数字滚动、滚动入场、指针高光、条形图生长、
        阅读进度条、导航毛玻璃。一律不承担信息表达 —— 关掉它页面必须仍然完整可读。
     2) **不改变任何布局尺寸**：只用 transform / opacity / background-position。
        首页首屏正文起点刚压到 730px，任何影响盒高的动效都会把正文顶下去。
     3) 优雅退化：所有动效由本脚本「自己加 class」才生效；脚本 404 / 报错 / 被 CSP 拦，
        页面回到静态态（CSS 里 .fx-rev / .fx-sweep 都不会被加上）。
     4) 尊重 prefers-reduced-motion（CSS 侧已整体关闭）。
     5) 幂等：重复执行不会重复注入。
   ========================================================================== */
(function () {
  "use strict";
  if (window.__fxOn) return;
  window.__fxOn = 1;

  var doc = document;
  var RM = false;
  try {
    RM = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (e) {}

  function $(s, c) { return (c || doc).querySelector(s); }
  function $$(s, c) {
    return Array.prototype.slice.call((c || doc).querySelectorAll(s));
  }
  function hasChild(parent, cls) {
    for (var i = 0; i < parent.children.length; i++) {
      if (parent.children[i].classList.contains(cls)) return true;
    }
    return false;
  }

  /* ---------- ① 顶部阅读进度条 ---------- */
  function progress() {
    if ($(".fx-prog")) return;
    var el = doc.createElement("div");
    el.className = "fx-prog";
    el.setAttribute("aria-hidden", "true");
    doc.body.appendChild(el);
    var raf = 0;
    function upd() {
      raf = 0;
      var h = doc.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      var p = max > 0 ? (h.scrollTop || doc.body.scrollTop || 0) / max : 0;
      el.style.width = (Math.max(0, Math.min(1, p)) * 100).toFixed(2) + "%";
    }
    function onScroll() { if (!raf) raf = window.requestAnimationFrame(upd); }
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    upd();
  }

  /* ---------- ② 深色面板：扫光带 + 底边跑光 ---------- */
  function sweeps() {
    $$(".hero,.pagehead,.up-hero,.pulse").forEach(function (p) {
      if (hasChild(p, "fx-sweep")) return;
      var s = doc.createElement("span");
      s.className = "fx-sweep";
      s.setAttribute("aria-hidden", "true");
      s.appendChild(doc.createElement("i"));   // 斜掠光带
      s.appendChild(doc.createElement("b"));   // 底边跑光
      p.insertBefore(s, p.firstChild);
    });
  }

  /* ---------- ③ 滚动入场（按 .wrap 的直接子块错峰） ---------- */
  function reveals() {
    if (RM) return;
    var host = $("main") || doc.body;
    var wrap = $(".wrap", host) || host;
    var cand = Array.prototype.slice.call(wrap.children).filter(function (el) {
      var t = el.tagName;
      return t !== "SCRIPT" && t !== "STYLE" && t !== "NOSCRIPT";
    });
    if (cand.length < 3) {
      cand = Array.prototype.slice.call(host.children).filter(function (el) {
        var t = el.tagName;
        return t !== "SCRIPT" && t !== "STYLE" && t !== "NOSCRIPT";
      });
    }
    if (!cand.length) return;
    cand.forEach(function (el) { el.classList.add("fx-rev"); });
    if (!("IntersectionObserver" in window)) {
      cand.forEach(function (el) { el.classList.add("fx-in"); });
      return;
    }
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("fx-in");
        io.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -5% 0px", threshold: 0.01 });
    cand.forEach(function (el, k) {
      if (k > 2) el.style.transitionDelay = Math.min(k - 2, 4) * 55 + "ms";
      io.observe(el);
    });
    // 兜底：观察器若因异常没回调（首屏块必须立刻可见），600ms 后无条件放行首两屏
    window.setTimeout(function () {
      if (!$(".fx-rev.fx-in")) cand.forEach(function (el) { el.classList.add("fx-in"); });
    }, 600);
  }

  /* ---------- ④ 指针跟随高光 ---------- */
  function spots() {
    $$(".pulse-row,.deck-col,.sp-card,.rg-top,.cs-sec").forEach(function (el) {
      if (el.classList.contains("fx-spot")) return;
      el.classList.add("fx-spot");
      el.addEventListener("pointermove", function (ev) {
        var r = el.getBoundingClientRect();
        el.style.setProperty("--mx", ((ev.clientX - r.left) / r.width * 100).toFixed(1) + "%");
        el.style.setProperty("--my", ((ev.clientY - r.top) / r.height * 100).toFixed(1) + "%");
      }, { passive: true });
    });
  }

  /* ---------- ⑤ 数字滚动计数 ----------
     只动「文本节点里的数字」，且动画结束一定把原字符串还原 —— 数字上挂的
     千分位、单位、前后缀一律不碰。带 id 的元素跳过：那些常由别的脚本改写
     （如 dash.js 的 #docCnt），抢着写会互相覆盖。 */
  var NUMSEL = [
    ".kpi-card b", ".pulse-main b", ".deck-n", ".ft-n", ".num-a",
    ".sp-k b", ".rd-count b", ".stat b", ".lb-n", ".pn-k b",
    ".ct-heat", ".up-sum b", ".sp-mx td.tt"
  ].join(",");

  function firstNumNode(el) {
    for (var n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && /\d/.test(n.nodeValue)) return n;
    }
    return null;
  }

  function countOne(el, dur) {
    var node = firstNumNode(el);
    if (!node) return;
    var raw = node.nodeValue;
    var m = raw.match(/\d[\d,]*/);
    if (!m) return;
    var target = parseInt(m[1].replace(/,/g, ""), 10);
    if (!isFinite(target) || target <= 0) return;
    var pre = raw.slice(0, m.index);
    var post = raw.slice(m.index + m[1].length);
    var grp = m[1].indexOf(",") >= 0;
    function fmt(v) {
      var s = String(v);
      return grp ? s.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : s;
    }
    var t0 = 0;
    el.classList.add("fx-tick");
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      node.nodeValue = pre + fmt(Math.round(target * e)) + post;
      if (p < 1) {
        window.requestAnimationFrame(step);
      } else {
        node.nodeValue = raw;          // 还原原始串，杜绝格式化误差
        el.classList.remove("fx-tick");
      }
    }
    window.requestAnimationFrame(step);
  }

  function counters() {
    if (RM) return;
    var els = $$(NUMSEL).filter(function (el) {
      if (el.id) return false;
      if (el.hasAttribute("data-fx-num") && el.getAttribute("data-fx-num") === "0") return false;
      return /\d/.test(el.textContent);
    });
    if (!els.length) return;
    // 上限 40 个：页面上的统计数字不会更多，多出来的（长表格）不动，避免长列表卡顿
    els = els.slice(0, 40);
    if (!("IntersectionObserver" in window)) {
      els.forEach(function (el) { countOne(el, 620); });
      return;
    }
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        countOne(e.target, 620);
      });
    }, { threshold: 0.15 });
    els.forEach(function (el) { io.observe(el); });
  }

  /* ---------- ⑥ 领域分布条形图：进入视口时从 0 生长 ---------- */
  function bars() {
    if (RM || !("IntersectionObserver" in window)) return;
    var els = $$(".dist-bar");
    if (!els.length) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        io.unobserve(el);
        var w = el.style.width;
        el.style.transition = "none";
        el.style.width = "0%";
        void el.offsetWidth;                 // 强制重排，让 0% 真正落位
        el.style.transition = "";
        window.requestAnimationFrame(function () { el.style.width = w; });
      });
    }, { threshold: 0.25 });
    els.forEach(function (el) { io.observe(el); });
  }

  /* ---------- ⑦ 导航：滚动后毛玻璃 ---------- */
  function navGlass() {
    var nav = $(".topnav");
    if (!nav) return;
    var last = null;
    function upd() {
      var s = window.pageYOffset || doc.documentElement.scrollTop || 0;
      var on = s > 24;
      if (on !== last) { nav.classList.toggle("fx-stuck", on); last = on; }
    }
    window.addEventListener("scroll", upd, { passive: true });
    upd();
  }

  function run() {
    try { progress(); } catch (e) {}
    try { sweeps(); } catch (e) {}
    try { navGlass(); } catch (e) {}
    try { spots(); } catch (e) {}
    try { counters(); } catch (e) {}
    try { bars(); } catch (e) {}
    try { reveals(); } catch (e) {}
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
