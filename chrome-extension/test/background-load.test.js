// AR-2 (pass-20): load-time smoke test for background.js.
//
// background.js has top-level calls (`restoreActionStatus();`, event-listener
// registrations) that run synchronously on every SW startup. A TDZ-violating
// `let` access pre-pass-20 produced an unhandled `ReferenceError` on every
// load — invisible to the previous tests because they only import scraper.js.
//
// This test executes the file in a sandboxed Node context with a Chrome API
// stub and asserts no exception is thrown during the synchronous load phase.

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BACKGROUND_JS = join(__dirname, '..', 'background.js');

describe('background.js — load-time invariants', () => {
  it('loads without throwing — TDZ + top-level call safety (AR-2 regression guard)', () => {
    const src = readFileSync(BACKGROUND_JS, 'utf8');

    // Strip ES-module syntax that background.js doesn't actually use today
    // (none currently, but defensive). The MV3 SW runtime uses classic
    // scripts; vm.Script matches that semantics.
    // Minimum chrome stub covering every API touched at module load.
    // Anything not on this list will surface a clear TypeError pointing at
    // the missing field — that's also a useful failure mode (catches missing
    // permission declarations) but only meaningful once load is stable.
    const noop = () => {};
    const listener = {addListener: noop, removeListener: noop};
    const chromeStub = {
      runtime: {
        getManifest: () => ({version: '0.0.0-test'}),
        onInstalled: listener,
        onStartup: listener,
      },
      alarms: {create: noop, onAlarm: listener},
      storage: {
        local: {
          get: async () => ({}),
          set: async () => {},
          remove: async () => {},
        },
      },
      action: {
        setTitle: async () => {},
        onClicked: listener,
      },
      tabs: {
        create: async () => ({id: 1}),
        get: async () => ({}),
        query: async () => [],
        remove: async () => {},
        onUpdated: listener,
        onActivated: listener,
      },
      webNavigation: {
        onCompleted: listener,
        onHistoryStateUpdated: listener,
      },
      scripting: {executeScript: async () => []},
      idle: {onStateChanged: listener},
    };

    const context = {
      chrome: chromeStub,
      console: {log: () => {}, warn: () => {}, error: () => {}},
      // background.js uses these globals:
      fetch: async () => ({ok: false, status: 0, text: async () => '', json: async () => ({})}),
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
      vm.runInContext(src, context, {filename: 'background.js'});
    } catch (e) {
      topLevelError = e;
    }

    assert.equal(topLevelError, null,
      `background.js threw at module load: ${topLevelError?.message}`);

    // Drain the microtask queue so any unhandled rejection from top-level
    // async calls (restoreActionStatus(), etc.) surfaces. BL-1 (pass-21):
    // remove the handler AFTER the drain — previously the finally above
    // removed it synchronously, before any rejection could fire, leaving
    // the assertion's diagnostic message unreachable.
    return new Promise((resolve) => setTimeout(() => {
      process.off('unhandledRejection', rejectionHandler);
      assert.equal(unhandledRejection, null,
        `background.js produced an unhandled rejection at load: ${unhandledRejection?.message}`);
      resolve();
    }, 50));
  });
});
