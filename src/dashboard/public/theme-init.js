// Apply theme before first paint to prevent flash. Two modes only:
// Light (default) and Dark. A stored "system" or unknown value is Light.
// External file (ADR-046): the dashboard CSP forbids inline scripts, so the
// theme bootstrap that used to be an inline <script> in index.html lives here.
(function() {
  var theme = 'light';
  try {
    var v = localStorage.getItem('theme');
    theme = (v === 'dark' || v === 'light') ? v : 'light';
  } catch(e) {}
  document.documentElement.setAttribute('data-theme', theme);
})();
