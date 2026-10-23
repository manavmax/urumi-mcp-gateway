// Urumi Gateway landing page behaviour. No framework, no dependencies.
// Spec: docs/LANDING_DESIGN.md sections 6, 7 and 10. Config: features.js.
// Everything is progressive enhancement: the page reads fully with JS off
// and shows final values under prefers-reduced-motion.
(function () {
  "use strict";
  var cfg = window.LANDING || {};
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  /* ---------- helpers ---------- */
  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
  function onStart(el, fn) {
    if (!el) return;
    if ("IntersectionObserver" in window) {
      var seen = false;
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting && !seen) { seen = true; obs.disconnect(); fn(e.target); }
        });
      }, { threshold: 0.15 });
      obs.observe(el);
    } else fn(el);
  }
  function now() { return performance.now(); }
  function two(n) { return String(n).padStart(2, "0"); }
  function stamp() {
    var d = new Date();
    return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
  }
  function visibleEl(el) { return !!(el && el.getBoundingClientRect().width > 0); }

  // toast: bottom centre, 2 seconds
  var toastBox = $("#toasts");
  function toast(msg) {
    if (!toastBox) return;
    var t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    toastBox.appendChild(t);
    setTimeout(function () { t.remove(); }, 2000);
  }

  /* ---------- theme toggle (stored choice wins) ---------- */
  var toggle = $("#themeToggle");
  function themeLabel() {
    if (!toggle) return;
    var light = document.documentElement.getAttribute("data-theme") === "light";
    toggle.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
  }
  themeLabel();
  if (toggle) toggle.addEventListener("click", function () {
    var light = document.documentElement.getAttribute("data-theme") === "light";
    var next = light ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("landing-theme", next); } catch (e) {}
    themeLabel();
  });

  /* ---------- announcement bar: dismissible, remembered ---------- */
  var announce = $("#announce");
  try { if (announce && localStorage.getItem("landing-announce-dismissed") === "1") announce.hidden = true; } catch (e) {}
  var announceClose = $("#announceClose");
  if (announceClose) announceClose.addEventListener("click", function () {
    announce.hidden = true;
    try { localStorage.setItem("landing-announce-dismissed", "1"); } catch (e) {}
  });

  /* ---------- nav: blur + shrink after 8px, mobile overlay sheet ---------- */
  var nav = $("#nav");
  function onScroll() { if (nav) nav.classList.toggle("scrolled", window.scrollY > 8); }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  var navToggle = $("#navToggle"), sheet = $("#navSheet"), sheetClose = $("#navSheetClose");
  var desktop = window.matchMedia("(min-width: 900px)");
  var sheetOpen = false, sheetTimer = null, lastFocus = null;

  function setSheet(open) {
    if (!navToggle || !sheet) return;
    if (open === sheetOpen) return;
    if (open && desktop.matches) return; // the sheet cannot open at desktop widths
    sheetOpen = open;
    navToggle.setAttribute("aria-expanded", String(open));
    navToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    document.documentElement.classList.toggle("nav-open", open);
    if (open) {
      lastFocus = document.activeElement;
      sheet.hidden = false;
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          sheet.classList.add("open");
          // focus must land after the sheet becomes visible, or it is dropped
          var first = sheetClose || $(".sheet-links a", sheet);
          if (first) first.focus();
        });
      });
    } else {
      sheet.classList.remove("open");
      clearTimeout(sheetTimer);
      sheetTimer = setTimeout(function () { sheet.hidden = true; }, reduced ? 0 : 320);
      if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
    }
  }
  if (navToggle) {
    navToggle.addEventListener("click", function () { setSheet(!sheetOpen); });
    sheet.addEventListener("click", function (e) {
      if (e.target.closest("a")) setSheet(false);
    });
  }
  if (sheetClose) sheetClose.addEventListener("click", function () { setSheet(false); });
  document.addEventListener("keydown", function (e) {
    if (!sheetOpen) return;
    if (e.key === "Escape") { setSheet(false); return; }
    if (e.key !== "Tab") return;
    var focusables = $$('a[href], button:not([disabled])', sheet)
      .filter(function (el) { return el.offsetParent !== null; });
    if (!focusables.length) return;
    var first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  if (desktop.addEventListener) {
    desktop.addEventListener("change", function (e) {
      if (e.matches) { // resized to desktop: close instantly, never render there
        clearTimeout(sheetTimer);
        sheetOpen = false;
        sheet.classList.remove("open");
        sheet.hidden = true;
        document.documentElement.classList.remove("nav-open");
        if (navToggle) navToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* ---------- scroll-spy: sliding highlight in the nav pill group ---------- */
  var spyLinks = $$(".nav-links a[data-spy]");
  var glide = $("#navGlide");
  function positionGlide(link) {
    if (!glide || !link) return;
    glide.style.width = link.offsetWidth + "px";
    glide.style.transform = "translateX(" + link.offsetLeft + "px)";
    glide.classList.add("in");
  }
  if (spyLinks.length && "IntersectionObserver" in window) {
    var activeSpy = null;
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var id = entry.target.id;
        var link = $('.nav-links a[data-spy="' + id + '"]');
        if (!link || link === activeSpy) return;
        activeSpy = link;
        spyLinks.forEach(function (a) {
          var on = a === link;
          a.classList.toggle("active", on);
          if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
        });
        positionGlide(link);
      });
    }, { rootMargin: "-40% 0px -52% 0px", threshold: 0 });
    ["how", "features", "security", "kubernetes", "docs"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) spy.observe(el);
    });
    var rsTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(rsTimer);
      rsTimer = setTimeout(function () { if (activeSpy) positionGlide(activeSpy); }, 120);
    });
    // webfont swap changes link widths after first layout; reposition once ready
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () { if (activeSpy) positionGlide(activeSpy); });
    }
  }

  /* ---------- live links + derived gateway URL ---------- */
  var host = window.location.hostname;
  var proto = window.location.protocol === "https:" ? "https:" : "http:";
  var port = window.location.port ? ":" + window.location.port : "";
  function subUrl(sub, override) {
    if (override) return override;
    if (!host) return null;
    return proto + "//" + sub + "." + host + port;
  }
  var dashUrl = subUrl("dashboard", cfg.dashboardUrl);
  var storeUrl = subUrl("store", cfg.storeUrl);
  function setHrefs(sel, url) {
    if (!url) return;
    $$ (sel).forEach(function (n) { n.href = url; });
  }
  if (cfg.repoUrl) setHrefs("[data-repo]", cfg.repoUrl);
  setHrefs("[data-link-dashboard]", dashUrl);
  setHrefs("[data-link-store]", storeUrl);

  // gateway URL: explicit config wins, else dashboard.<apex>/mcp
  var gwUrl = cfg.gatewayUrl || (dashUrl ? dashUrl.replace(/\/+$/, "") + "/mcp" : null);
  $$("[data-gateway-url]").forEach(function (n) { if (gwUrl) n.textContent = gwUrl; });

  // data-driven store claim
  var catalog = $("[data-store-catalog]");
  if (catalog) {
    var n = cfg.storeProductCount;
    catalog.textContent = typeof n === "number" && n > 0 ? n + "-product" : "";
  }

  /* ---------- copy: buttons, tool chips; label flips 1.5s; toast ---------- */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () { legacyCopy(text); });
    }
    legacyCopy(text);
    return Promise.resolve();
  }
  function legacyCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  }
  function bindCopy(btn, getText) {
    if (!btn) return;
    var label = $(".copy-label", btn);
    btn.addEventListener("click", function () {
      copyText(getText()).then(function () {
        if (label) {
          label.textContent = "Copied";
          setTimeout(function () { label.textContent = "Copy"; }, 1500);
        }
        toast("Copied to clipboard");
      });
    });
  }
  $$(".copy-btn[data-copy]").forEach(function (btn) {
    var pane = $('#pane-' + btn.getAttribute("data-copy"));
    bindCopy(btn, function () {
      var code = pane && $("code", pane);
      return code ? code.textContent : "";
    });
  });
  $$(".tool-chips li").forEach(function (li) {
    li.addEventListener("click", function () {
      copyText(li.textContent).then(function () { toast("Copied " + li.textContent); });
    });
  });

  /* ---------- client tabs: 160ms cross fade ---------- */
  $$(".client-tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      var key = tab.getAttribute("data-tab");
      $$(".client-tab").forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.setAttribute("tabindex", on ? "0" : "-1");
      });
      $$("[data-pane]").forEach(function (p) {
        var mine = p.getAttribute("data-pane") === key;
        if (mine) {
          p.hidden = false;
          if (!reduced) {
            p.classList.add("swap");
            requestAnimationFrame(function () {
              requestAnimationFrame(function () { p.classList.remove("swap"); });
            });
          }
        } else {
          p.hidden = true;
        }
      });
    });
  });

  /* ---------- beyond the brief + video (features.js) ---------- */
  var beyond = $("#beyond");
  if (beyond) {
    var enabled = (cfg.features || []).filter(function (f) { return f && f.enabled; });
    if (enabled.length) {
      var list = $("#beyond-list");
      enabled.forEach(function (f) {
        var card = document.createElement("article");
        card.className = "card";
        card.setAttribute("data-io", "");
        var tag = document.createElement("p");
        tag.className = "card-tag";
        tag.textContent = "queued";
        var h = document.createElement("h3");
        h.textContent = f.title || "";
        var p = document.createElement("p");
        p.className = "card-lead";
        p.textContent = f.body || "";
        card.appendChild(tag); card.appendChild(h); card.appendChild(p);
        list.appendChild(card);
      });
      beyond.hidden = false;
    }
  }
  var video = $("#video");
  if (video && cfg.videoUrl) {
    var slot = $("#video-slot");
    var a = document.createElement("a");
    a.className = "video-link";
    a.href = cfg.videoUrl;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.innerHTML =
      '<span class="play"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg></span>' +
      "Watch the demo video" +
      "<span>opens on the host site; this page loads nothing external</span>";
    slot.appendChild(a);
    video.hidden = false;
  }

  /* ---------- entrance reveals, staggered 60ms ---------- */
  var ioEls = $$("[data-io]");
  if (!reduced && "IntersectionObserver" in window) {
    var reveal = new IntersectionObserver(function (entries) {
      var batch = entries.filter(function (e) { return e.isIntersecting; });
      batch.forEach(function (e, i) {
        var el = e.target;
        el.style.transitionDelay = (i * 60) + "ms";
        el.classList.add("io-in");
        el.classList.remove("io-pre");
        reveal.unobserve(el);
        setTimeout(function () { el.style.transitionDelay = ""; }, 700 + i * 60);
      });
    }, { threshold: 0.15 });
    ioEls.forEach(function (el) { el.classList.add("io-pre"); reveal.observe(el); });
  }

  /* ---------- card spotlight (pointer devices only) ---------- */
  if (finePointer) $$("[data-spot]").forEach(function (card) {
    card.addEventListener("pointermove", function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - r.left) + "px");
      card.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  /* ---------- hero typing terminal: 28ms/char, 5s pause, loops ---------- */
  // The HTML carries the final state; JS hides it, types, then reveals.
  var termText = $("#termText"), termCall = $("#termCall"), termAnswer = $("#termAnswer");
  var PROMPT = "What orders came in today?";
  function terminalLoop() {
    if (!termText || reduced) return;
    termText.textContent = "";
    termCall.style.visibility = "hidden";
    termAnswer.style.visibility = "hidden";
    var i = 0;
    var iv = setInterval(function () {
      termText.textContent = PROMPT.slice(0, ++i);
      if (i >= PROMPT.length) {
        clearInterval(iv);
        setTimeout(function () {
          termCall.style.visibility = "visible";
          setTimeout(function () {
            termAnswer.style.visibility = "visible";
            setTimeout(terminalLoop, 5000);
          }, 600);
        }, 350);
      }
    }, 28);
  }
  onStart($("#terminal"), terminalLoop);

  /* ---------- steps: track draws; widgets ---------- */
  var steps = $("#steps");
  if (steps) onStart(steps, function () { steps.classList.add("track-in"); });

  // 01: typing URL field
  var typeUrl = $("#typeUrl");
  if (typeUrl) {
    var urlText = gwUrl || "https://dashboard.example.com/mcp";
    if (reduced) typeUrl.textContent = urlText;
    else onStart(typeUrl, function () {
      var i = 0;
      var iv = setInterval(function () {
        typeUrl.textContent = urlText.slice(0, ++i);
        if (i >= urlText.length) clearInterval(iv);
      }, 34);
    });
  }

  // 02: key reveals once, then masks again
  var keyText = $("#keyText"), keyBtn = $("#keyReveal");
  var KEY_FULL = "urumi_sk_9f3e7a1c44b8d2f6";
  var KEY_MASK = "urumi_sk_••••••••••••••••";
  if (keyBtn && keyText) keyBtn.addEventListener("click", function () {
    keyText.textContent = KEY_FULL;
    keyBtn.setAttribute("aria-label", "Sample key revealed; it will be masked again");
    setTimeout(function () { keyText.textContent = KEY_MASK; keyBtn.setAttribute("aria-label", "Reveal the sample key once"); }, 3000);
  });

  // 03: tool call line appears when in view
  var wCall = $("#wCall");
  if (wCall && !reduced) {
    wCall.style.opacity = "0";
    onStart(wCall, function () {
      wCall.style.transition = "opacity var(--slow) var(--std)";
      wCall.style.opacity = "1";
    });
  }

  /* ---------- diagram replay: steps light 400ms apart ---------- */
  // Each node lights 400ms after the previous one; the connecting path
  // lights together with the node it leads to. Final state = all lit.
  function playDiagram(root) {
    var nodes = $$("[data-step]", root);
    var paths = $$(".dpath", root);
    nodes.forEach(function (n) { n.classList.remove("lit"); });
    paths.forEach(function (p) { p.classList.remove("lit"); });
    var step = 0;
    var iv = setInterval(function () {
      if (step > 0 && paths[step - 1]) paths[step - 1].classList.add("lit");
      if (step >= nodes.length) {
        if (paths[step - 1] && paths.length > step) paths[step].classList.add("lit");
        clearInterval(iv);
        return;
      }
      nodes[step].classList.add("lit");
      step++;
    }, 400);
  }
  [$("#tourWide"), $("#tourTall")].forEach(function (svg) {
    if (!svg) return;
    if (reduced) {
      $$("[data-step]", svg).forEach(function (n) { n.classList.add("lit"); });
      $$(".dpath", svg).forEach(function (p) { p.classList.add("lit"); });
    } else {
      onStart(svg, function () { playDiagram(svg); });
    }
  });
  var replay = $("#diagramReplay");
  if (replay) replay.addEventListener("click", function () {
    var wide = $("#tourWide"), tall = $("#tourTall");
    var svg = visibleEl(wide) ? wide : tall;
    if (svg && !reduced) playDiagram(svg);
  });

  /* ---------- fleet: count-up + sparkline draw ---------- */
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  $$(".stat-num[data-count]").forEach(function (el) {
    var target = parseFloat(el.getAttribute("data-count"));
    var fmt = el.getAttribute("data-format");
    var suffix = el.getAttribute("data-suffix") || "";
    function render(v) {
      var s;
      if (fmt === "int") s = Math.round(v).toLocaleString("en-US");
      else if (fmt === "pct") s = v.toFixed(1) + "%";
      else s = String(Math.round(v));
      el.textContent = s + suffix;
    }
    if (reduced || !("IntersectionObserver" in window)) { render(target); return; }
    var started = false;
    onStart(el, function () {
      if (started) return;
      started = true;
      var t0 = now();
      function tick() {
        var p = Math.min(1, (now() - t0) / 1200);
        render(target * easeOut(p));
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  });
  var spark = $("#sparkLine");
  if (spark && !reduced) {
    var len = spark.getTotalLength();
    spark.style.strokeDasharray = len;
    spark.style.strokeDashoffset = len;
    var area = $(".spark-area");
    if (area) area.style.opacity = "0";
    onStart(spark, function () {
      spark.style.transition = "stroke-dashoffset 1200ms cubic-bezier(0.2,0.7,0.2,1)";
      if (area) { area.style.transition = "opacity 1200ms cubic-bezier(0.2,0.7,0.2,1)"; area.style.opacity = "1"; }
      requestAnimationFrame(function () { spark.style.strokeDashoffset = "0"; });
    });
  }

  /* ---------- streaming audit rows: 2.5s, last 5, pause on hover ---------- */
  var auditBody = $("#auditBody");
  if (auditBody && !reduced) {
    var POOL = [
      ["alice", "woo__list_orders", "118 ms", "ok"],
      ["bob", "notes__search_notes", "64 ms", "ok"],
      ["alice", "time__convert_time", "12 ms", "ok"],
      ["bob", "woo__update_order_status", "—", "permission denied"],
      ["bob", "woo__get_order", "210 ms", "error"],
      ["alice", "notes__create_note", "31 ms", "ok"],
      ["bob", "time__get_current_time", "9 ms", "ok"]
    ];
    var BADGE = { "ok": "badge-ok", "error": "badge-err", "permission denied": "badge-warn" };
    var paused = false, pi = 0;
    var panel = auditBody.closest(".panel");
    if (panel) {
      panel.addEventListener("pointerenter", function () { paused = true; });
      panel.addEventListener("pointerleave", function () { paused = false; });
    }
    function two(n) { return String(n).padStart(2, "0"); }
    function streamRow() {
      if (paused) return;
      var ev = POOL[pi++ % POOL.length];
      var d = new Date();
      var tr = document.createElement("tr");
      tr.className = "new";
      var time = two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
      tr.innerHTML =
        '<td class="mono">' + time + "</td><td>" + ev[0] + '</td><td class="mono">' + ev[1] +
        '</td><td class="mono">' + ev[2] + '</td><td><span class="badge ' + BADGE[ev[3]] + '">' + ev[3] + "</span></td>";
      auditBody.insertBefore(tr, auditBody.firstChild);
      while (auditBody.children.length > 5) auditBody.removeChild(auditBody.lastChild);
    }
    setInterval(streamRow, 2500);
  }

  /* ---------- break it yourself simulation ---------- */
  var sim = $("#sim");
  if (sim) {
    var selected = "woo";
    var revoked = false;
    var disabled = {};
    var state = { woo: "ok", time: "ok", notes: "ok" }; // ok | dead | restarting | disabled
    var TOOL_POOLS = {
      woo: ["woo__list_orders", "woo__get_product", "woo__list_orders", "woo__update_order_status"],
      time: ["time__get_current_time", "time__convert_time"],
      notes: ["notes__create_note", "notes__search_notes"]
    };
    var USERS = ["alice", "bob"];
    var log = $("#simLog"), countEl = $("#simCount"), issueBtn = $("#simIssue");
    var liIndex = {};
    $$("#simCombined li").forEach(function (li) { liIndex[li.getAttribute("data-tool")] = li; });

    function enabledServers() {
      return Object.keys(state).filter(function (s) { return state[s] !== "dead" && state[s] !== "disabled"; });
    }
    function refreshCount() {
      // the combined list in the DOM is the source of truth
      var count = $$("#simCombined li").filter(function (li) { return li.style.display !== "none"; }).length;
      countEl.textContent = String(count);
    }
    function setStatus(name, cls, text) {
      var card = $('.sim-server[data-server="' + name + '"]', sim);
      var chip = $(".sim-status", card);
      chip.className = "sim-status " + cls;
      chip.textContent = text;
    }
    function logRow(html, cls) {
      if (!log) return;
      var li = document.createElement("li");
      if (cls) li.className = cls;
      li.innerHTML = html;
      log.insertBefore(li, log.firstChild);
      while (log.children.length > 5) log.removeChild(log.lastChild);
    }
    function stamp() {
      var d = new Date();
      return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
    }
    function sampleCall() {
      var live = enabledServers();
      if (!live.length) return;
      var srv = live[Math.floor(Math.random() * live.length)];
      var tool = TOOL_POOLS[srv][Math.floor(Math.random() * TOOL_POOLS[srv].length)];
      var user = USERS[Math.floor(Math.random() * USERS.length)];
      if (revoked) {
        logRow('<span>' + stamp() + "</span><span>" + user + "</span><span>" + tool + '</span><span class="l-err">401 unauthorized</span>', "log-401 new");
        return;
      }
      logRow('<span>' + stamp() + "</span><span>" + user + "</span><span>" + tool + '</span><span class="l-ok">200 ok</span>', "new");
    }
    setInterval(sampleCall, 2200);
    logRow('<span>14:02:11</span><span>alice</span><span>woo__list_orders</span><span class="l-ok">200 ok</span>');

    $$(".sim-server", sim).forEach(function (card) {
      card.addEventListener("click", function () {
        $$(".sim-server", sim).forEach(function (c) {
          c.classList.remove("is-selected");
          c.setAttribute("aria-pressed", "false");
        });
        card.classList.add("is-selected");
        card.setAttribute("aria-pressed", "true");
        selected = card.getAttribute("data-server");
      });
    });

    var restartTimers = {};
    $("#simKill").addEventListener("click", function () {
      if (state[selected] !== "ok") return;
      state[selected] = "dead";
      var card = $('.sim-server[data-server="' + selected + '"]', sim);
      card.classList.add("is-dead");
      setTimeout(function () {
        setStatus(selected, "status-dead", "Unreachable");
        card.classList.add("is-shaking");
        setTimeout(function () { card.classList.remove("is-shaking"); }, 450);
        var tool = TOOL_POOLS[selected][0];
        logRow('<span>' + stamp() + "</span><span>alice</span><span>" + tool + '</span><span class="l-err">error: unreachable</span>', "new");
      }, 600);
      clearTimeout(restartTimers[selected]);
      restartTimers[selected] = setTimeout(function () {
        state[selected] = "restarting";
        setStatus(selected, "status-warn", "restarting…");
        restartTimers[selected] = setTimeout(function () {
          state[selected] = "ok";
          setStatus(selected, "status-ok", "Connected");
          card.classList.remove("is-dead");
          logRow('<span>' + stamp() + "</span><span>system</span><span>" + selected + '</span><span class="l-ok">back online</span>', "new");
        }, 2500);
      }, 6000);
    });

    $("#simDisable").addEventListener("click", function () {
      if (state[selected] === "disabled") return;
      state[selected] = "disabled";
      disabled[selected] = true;
      var card = $('.sim-server[data-server="' + selected + '"]', sim);
      card.classList.add("is-disabled");
      setStatus(selected, "status-warn", "Disabled");
      TOOL_POOLS[selected].forEach(function (t) {
        var li = liIndex[t];
        if (li) { li.classList.add("gone"); setTimeout(function () { li.style.display = "none"; refreshCount(); }, 260); }
      });
      // the rest of the woo-only tools also leave the list when woo is disabled
      if (selected === "woo") $$("#simCombined li[data-tool^='woo__']").forEach(function (li) {
        li.classList.add("gone"); setTimeout(function () { li.style.display = "none"; refreshCount(); }, 260);
      });
      setTimeout(refreshCount, 300);
    });

    $("#simRevoke").addEventListener("click", function () {
      revoked = true;
      if (issueBtn) issueBtn.hidden = false;
      logRow('<span>' + stamp() + "</span><span>system</span><span>key revoked</span><span>—</span>", "new");
    });
    if (issueBtn) issueBtn.addEventListener("click", function () {
      revoked = false;
      issueBtn.hidden = true;
      logRow('<span>' + stamp() + "</span><span>system</span><span>new key issued</span><span class=\"l-ok\">calls accepted</span>", "new");
    });

    $("#simReset").addEventListener("click", function () {
      revoked = false;
      if (issueBtn) issueBtn.hidden = true;
      Object.keys(restartTimers).forEach(function (k) { clearTimeout(restartTimers[k]); });
      ["woo", "time", "notes"].forEach(function (s) {
        state[s] = "ok";
        disabled[s] = false;
        var card = $('.sim-server[data-server="' + s + '"]', sim);
        card.classList.remove("is-dead", "is-disabled");
        setStatus(s, "status-ok", "Connected");
      });
      $$("#simCombined li").forEach(function (li) {
        li.classList.remove("gone");
        li.style.display = "";
      });
      countEl.textContent = "13";
      if (log) log.innerHTML = "";
      logRow('<span>' + stamp() + "</span><span>system</span><span>simulation reset</span><span class=\"l-ok\">ready</span>");
    });
  }

  /* ---------- hero graphic: packets, tilt, visibility pause ---------- */
  var heroVisual = $("#heroVisual");
  if (heroVisual && !reduced) {
    var running = false, visible = false, inDoc = !document.hidden;
    function shouldBeRunning() { return visible && inDoc; }
    function setRunning(v) {
      if (v === running) return;
      running = v;
      if (v) startPackets();
    }
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        setRunning(shouldBeRunning());
      }, { threshold: 0.05 }).observe(heroVisual);
    } else { visible = true; }
    document.addEventListener("visibilitychange", function () {
      inDoc = !document.hidden;
      setRunning(shouldBeRunning());
    });

    // packets travel client -> hub -> upstream, then back in violet
    var wide = $("#hvWide"), tall = $("#hvTall");
    function activeSvg() {
      if (visibleEl(wide)) return wide;
      if (visibleEl(tall)) return tall;
      return null;
    }
    var journeyCount = 0;
    function pathsFor(svg, kind) {
      var out = [];
      if (kind === "c") {
        ["p-c0", "p-c1", "p-c2"].forEach(function (id) {
          var el = $("#" + (svg === tall ? id.replace("p-", "t-") : id), svg);
          if (el) out.push({ path: el });
        });
      } else {
        for (var i = 0; i < 4; i++) {
          var el = $("#" + (svg === tall ? "t-u" + i : "p-u" + i), svg);
          if (el) out.push({ path: el, flash: (svg === tall ? "hvT" : "hvU") + i });
        }
      }
      return out;
    }
    function makeCircle(svg, cls) {
      var holder = svg === wide ? $("#hvPackets", svg) : $("#hvPacketsTall", svg);
      if (!holder) return null;
      var halo = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      halo.setAttribute("r", "8");
      halo.setAttribute("class", cls + " pkt-halo");
      halo.setAttribute("opacity", "0");
      var core = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      core.setAttribute("r", "4");
      core.setAttribute("class", cls);
      core.setAttribute("opacity", "0");
      holder.appendChild(halo);
      holder.appendChild(core);
      return {
        setCls: function (c) {
          core.setAttribute("class", c);
          halo.setAttribute("class", c + " pkt-halo");
        },
        moveTo: function (x, y, op) {
          core.setAttribute("cx", x); core.setAttribute("cy", y); core.setAttribute("opacity", op);
          halo.setAttribute("cx", x); halo.setAttribute("cy", y); halo.setAttribute("opacity", op * 0.3);
        },
        remove: function () { core.remove(); halo.remove(); }
      };
    }
    function legAnim(mover, path, reverse, dur, cls, done) {
      var t0 = now();
      if (cls) mover.setCls(cls);
      var len = path.getTotalLength();
      function frame() {
        if (!running) { done && done(true); return; }
        var p = Math.min(1, (now() - t0) / dur);
        var e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2; // easeInOut
        var pt = path.getPointAtLength((reverse ? 1 - e : e) * len);
        var op = p < 0.08 ? p / 0.08 : p > 0.92 ? (1 - p) / 0.08 : 1;
        mover.moveTo(pt.x, pt.y, op);
        if (p < 1) requestAnimationFrame(frame);
        else done && done(false);
      }
      requestAnimationFrame(frame);
    }
    function journey(svg, cis, uis, holderId) {
      var c = makeCircle(svg, "pkt-out");
      if (!c) return;
      var ci = cis[Math.floor(Math.random() * cis.length)];
      var ui = uis[Math.floor(Math.random() * uis.length)];
      legAnim(c, ci.path, false, 800, "pkt-out", function (stopped) {
        if (stopped) { c.remove(); return; }
        legAnim(c, ui.path, false, 1000, "pkt-out", function (stopped2) {
          if (stopped2) { c.remove(); return; }
          var grp = $("#" + ui.flash, svg);
          if (grp) { grp.classList.add("flash"); setTimeout(function () { grp.classList.remove("flash"); }, 450); }
          legAnim(c, ui.path, true, 1000, "pkt-ret", function (stopped3) {
            if (stopped3) { c.remove(); return; }
            legAnim(c, ci.path, true, 800, "pkt-ret", function () { c.remove(); });
          });
        });
      });
    }
    function startPackets() {
      var svg = activeSvg();
      if (!svg) return;
      var cis = pathsFor(svg, "c"), uis = pathsFor(svg, "u");
      if (svg === wide) {
        journey(svg, cis, uis);
        setTimeout(function () { if (running) journey(svg, cis, uis); }, 1400);
      } else {
        journey(svg, cis, uis);
      }
      setTimeout(function () { if (running) startPackets(); }, 4000);
    }
    setRunning(shouldBeRunning());

    // plane tilt follows the pointer with easing (max ~6 degrees overall)
    if (finePointer) {
      var tx = 0, ty = 0, cx = 0, cy = 0, rafId = null;
      heroVisual.addEventListener("pointermove", function (e) {
        var r = heroVisual.getBoundingClientRect();
        tx = ((e.clientX - r.left) / r.width - 0.5) * 2;
        ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
        if (!rafId) tiltFrame();
      });
      heroVisual.addEventListener("pointerleave", function () { tx = 0; ty = 0; if (!rafId) tiltFrame(); });
      function tiltFrame() {
        cx += (tx - cx) * 0.08;
        cy += (ty - cy) * 0.08;
        heroVisual.style.setProperty("--tiltX", cx.toFixed(3));
        heroVisual.style.setProperty("--tiltY", cy.toFixed(3));
        if (Math.abs(tx - cx) > 0.002 || Math.abs(ty - cy) > 0.002) rafId = requestAnimationFrame(tiltFrame);
        else rafId = null;
      }
    }
  }
})();
