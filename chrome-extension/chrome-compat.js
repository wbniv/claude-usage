// Firefox compatibility shim. Loaded ONLY by the generated Firefox manifest
// (scripts/gen-firefox-manifest.py + packaging/build-firefox-zip.sh), never by
// chrome-extension/manifest.json — Chrome is unaffected.
//
// background.js calls chrome.* with `await` (in Chrome the chrome.* APIs return
// promises). Firefox's promise-based namespace is `browser.*`; its own `chrome.*`
// is callback-style, which would leave those `await`s hanging. Alias chrome ->
// browser before background.js runs so the SAME background.js works unchanged.
//
// IMPORTANT: Firefox defines BOTH `browser` (promises) AND a callback-style
// `chrome`. A conditional `chrome ??= browser` would see `chrome` already
// defined and NO-OP, leaving the callback API in place — every `await chrome.*`
// then resolves to `undefined` and the scrape silently never POSTs. So
// UNCONDITIONALLY prefer `browser` when it exists. On Chrome `browser` is
// undefined, so Chrome's own `chrome` is left untouched. The Firefox manifest
// lists this file FIRST in background.scripts so it runs before background.js's
// top-level chrome.runtime.getManifest().
if (globalThis.browser) globalThis.chrome = globalThis.browser;
