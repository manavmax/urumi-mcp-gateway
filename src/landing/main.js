// Landing page behaviour (ADR-080/081/082). No framework, no dependencies.
// 1. Theme toggle: dark-first, stored in try/catch localStorage, pre-paint set
//    by theme-init.js so this only handles the switch itself.
// 2. Live links: dashboard.<apex> and store.<apex> are derived from the apex
//    host the page is served on (the same convention the Helm values use), so
//    the static page carries no hardcoded hostname. Optional overrides come
//    from window.LANDING (dashboardUrl / storeUrl) in features.js.
// 3. The code card shows the real /mcp URL of this deployment.
// 4. "Beyond the brief" renders only items with enabled:true; the section
//    stays hidden while none are. The video block appears only when videoUrl
//    is set, as a link out (never an embed: zero external requests, ADR-080).
(function () {
  "use strict";
  var cfg = window.LANDING || {};
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
    var nodes = document.querySelectorAll(sel);
    for (var i = 0; i < nodes.length; i++) nodes[i].href = url;
  }
  if (cfg.repoUrl) setHrefs("[data-repo]", cfg.repoUrl);
  setHrefs("[data-link-dashboard]", dashUrl);
  setHrefs("[data-link-store]", storeUrl);

  var gw = document.querySelector("[data-gateway-url]");
  if (gw && dashUrl) {
    gw.textContent = dashUrl.replace(/\/+$/, "") + "/mcp";
  }

  var beyond = document.getElementById("beyond");
  if (beyond) {
    var enabled = (cfg.features || []).filter(function (f) { return f && f.enabled; });
    if (enabled.length) {
      var list = document.getElementById("beyond-list");
      enabled.forEach(function (f) {
        var card = document.createElement("article");
        card.className = "feature";
        var h = document.createElement("h3");
        h.textContent = f.title || "";
        var ul = document.createElement("ul");
        ul.className = "feature-list";
        var li = document.createElement("li");
        var strong = document.createElement("strong");
        strong.textContent = f.title || "";
        li.appendChild(strong);
        li.appendChild(document.createTextNode(" " + (f.body || "")));
        ul.appendChild(li);
        card.appendChild(h);
        card.appendChild(ul);
        list.appendChild(card);
      });
      beyond.hidden = false;
    }
  }

  var video = document.getElementById("video");
  if (video && cfg.videoUrl) {
    var slot = document.getElementById("video-slot");
    var a = document.createElement("a");
    a.className = "video-link";
    a.href = cfg.videoUrl;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.innerHTML =
      '<span class="play"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg></span>' +
      "Watch the demo video" +
      "<span>opens on the host site, this page loads nothing external</span>";
    slot.appendChild(a);
    video.hidden = false;
  }

  var toggle = document.getElementById("themeToggle");
  function label(t) {
    if (toggle) {
      toggle.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme");
    }
  }
  label(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
      var next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("landing-theme", next); } catch (e) { /* storage blocked */ }
      label(next);
    });
  }
})();
