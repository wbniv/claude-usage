// FF-1: Firefox compat-shim load test.
//
// background.js calls chrome.* with `await` (Chrome's chrome.* return promises).
// Under Firefox the promise namespace is browser.*; chrome-compat.js aliases
// chrome -> browser so the SAME background.js works unchanged. This test loads
// chrome-compat.js then background.js in a context where `chrome` is undefined
// and only `browser` exists (the Firefox-before-shim shape), and asserts a clean
// synchronous load with no unhandled rejection — the Firefox twin of
// background-load.test.js's Chrome-path guard.

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const COMPAT_JS = join(__dirname, '..', 'chrome-compat.js');
const BACKGROUND_JS = join(__dirname, '..', 'background.js');

describe('Firefox compat shim — chrome-compat.js', () => {
  it('aliases chrome→browser so background.js loads clean under the Firefox API shape', () => {
    const noop = () => {};
    const listener = { addListener: noop, removeListener: noop };
    // The Firefox (promise-based) extension API, exposed ONLY as `browser` —
    // same surface as background-load.test.js's chromeStub.
    const browserStub = {
      runtime: {
        getManifest: () => ({ version: '0.0.0-test' }),
        onInstalled: listener,
        onStartup: listener,
      },
      alarms: { create: noop, onAlarm: listener },
      storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } },
      action: { setTitle: async () => {}, onClicked: listener },
      tabs: {
        create: async () => ({ id: 1 }), get: async () => ({}), query: async () => [],
        remove: async () => {}, onUpdated: listener, onActivated: listener,
      },
      webNavigation: { onCompleted: listener, onHistoryStateUpdated: listener },
      scripting: { executeScript: async () => [] },
      idle: { onStateChanged: listener },
    };

    const context = {
      // No `chrome` key — the shim must create it from `browser`.
      browser: browserStub,
      console: { log: () => {}, warn: () => {}, error: () => {} },
      fetch: async () => ({ ok: false, status: 0, text: async () => '', json: async () => ({}) }),
      AbortController: globalThis.AbortController,
      setTimeout: globalThis.setTimeout,
      clearTimeout: globalThis.clearTimeout,
      Date: globalThis.Date,
      Math: globalThis.Math,
      Object: globalThis.Object,
      Array: globalThis.Array,
      String: globalThis.String,
      Number: globalThis.Number,
      Boolean: globalThis.Boolean,
      JSON: globalThis.JSON,
      Promise: globalThis.Promise,
      Error: globalThis.Error,
      TextDecoder: globalThis.TextDecoder,
      TextEncoder: globalThis.TextEncoder,
      URL: globalThis.URL,
      URLSearchParams: globalThis.URLSearchParams,
    };

    let topLevelError = null;
    let unhandledRejection = null;
    const rejectionHandler = (e) => { unhandledRejection = e; };
    process.on('unhandledRejection', rejectionHandler);
    try {
      vm.createContext(context);
      // Order matters: the shim must run before background.js's top-level
      // chrome.runtime.getManifest() — mirrors the Firefox manifest's
      // background.scripts: ["chrome-compat.js", "background.js"] order.
      vm.runInContext(readFileSync(COMPAT_JS, 'utf8'), context, { filename: 'chrome-compat.js' });
      assert.equal(context.chrome, browserStub,
        'chrome-compat.js must alias chrome → browser when only browser exists');
      vm.runInContext(readFileSync(BACKGROUND_JS, 'utf8'), context, { filename: 'background.js' });
    } catch (e) {
      topLevelError = e;
    }

    assert.equal(topLevelError, null,
      `Firefox load threw at module load: ${topLevelError?.message}`);

    // Drain the microtask queue so any unhandled rejection from top-level async
    // calls surfaces (same technique as background-load.test.js).
    return new Promise((resolve) => setTimeout(() => {
      process.off('unhandledRejection', rejectionHandler);
      assert.equal(unhandledRejection, null,
        `Firefox load produced an unhandled rejection at load: ${unhandledRejection?.message}`);
      resolve();
    }, 50));
  });
});
