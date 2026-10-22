// Pre-paint theme bootstrap (ADR-081). External file because the landing CSP
// forbids inline scripts (script-src 'self', same shape as the dashboard,
// ADR-046). Dark is the site default: a stored choice wins, then the OS
// preference, then dark. localStorage is wrapped in try/catch because the page
// must never break when storage is blocked (private mode, sandboxed iframe).
(function() {
  var theme = 'dark';
  try {
    var v = localStorage.getItem('landing-theme');
    if (v === 'dark' || v === 'light') {
      theme = v;
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      theme = 'light';
    }
  } catch (e) {}
  document.documentElement.setAttribute('data-theme', theme);
})();
