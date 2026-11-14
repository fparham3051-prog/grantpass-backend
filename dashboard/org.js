/* Applies the organization profile (org.config.json) to any page:
   - [data-org="name|shortName|legalName|leader.name|email|phone|..."] gets the text
   - [data-org-link="website|operations|clients|booking|freeCheckup"] gets the href
   - brand colors become CSS variables (--org-navy, --org-gold, ...)
   - [data-module="grantmaking"] etc. are hidden when that module is off
   The same file runs in the operations app and the InstitutionalOS pages,
   so a new organization changes one profile, not hundreds of strings. */
(function () {
  function get(obj, path) {
    return path.split('.').reduce(function (o, k) { return o && o[k] != null ? o[k] : undefined; }, obj);
  }
  function apply(cfg) {
    window.ORG = cfg;
    document.querySelectorAll('[data-org]').forEach(function (el) {
      var v = get(cfg.org, el.getAttribute('data-org'));
      if (typeof v === 'string' && v) el.textContent = v;
    });
    document.querySelectorAll('[data-org-link]').forEach(function (el) {
      var v = get(cfg.links || {}, el.getAttribute('data-org-link'));
      if (v) el.setAttribute('href', v);
    });
    var b = cfg.brand || {}, root = document.documentElement.style;
    ['navy', 'navyDeep', 'gold', 'goldLight', 'goldAccessible'].forEach(function (k) {
      if (b[k]) root.setProperty('--org-' + k.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); }), b[k]);
    });
    var mods = cfg.modules || {};
    document.querySelectorAll('[data-module]').forEach(function (el) {
      var key = el.getAttribute('data-module');
      if (mods[key] === false) { el.hidden = true; el.setAttribute('data-module-off', ''); }
    });
    document.dispatchEvent(new CustomEvent('org:ready', { detail: cfg }));
  }
  var src = document.currentScript && document.currentScript.getAttribute('data-config') || 'org.config.json';
  fetch(src, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; })
    .then(function (cfg) { if (cfg) apply(cfg); }).catch(function () {});
})();
