// Firefox compatibility shim. Loaded ONLY by the generated Firefox manifest
// (scripts/gen-firefox-manifest.py + packaging/build-firefox-zip.sh), never by
// chrome-extension/manifest.json — Chrome is unaffected.
//
// background.js calls chrome.* with `await` (in Chrome the chrome.* APIs return
// promises). Firefox's promise-based namespace is `browser.*`; its own `chrome.*`
// is callback-style, which would leave those `await`s hanging. Alias chrome ->
// browser before background.js runs so the SAME background.js works unchanged.
//
// No-op on Chrome (`chrome` is already defined) and on Firefox >=121 service
// worker builds (likewise). The Firefox manifest lists this file FIRST in
// background.scripts so it runs before background.js's top-level
// chrome.runtime.getManifest().
globalThis.chrome ??= globalThis.browser;
