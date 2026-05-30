// BASE-2 (2026-05-30 review): offline-buffer supersede regression.
//
// A successful full-scrape post must drop the offline buffer (`claude_usage`).
// Otherwise a later fetchUsage flush re-posts the now-stale buffer and the
// server's ordering-blind merge regresses its _timestamp/meters to that older
// snapshot. (It also makes the flush's non-atomic remove() safe — a re-flushed
// buffer is never newer than the freshest confirmed post.)
//
// This drives scrapeAndPost() in a vm sandbox with a STATEFUL storage mock and
// a stubbed claude-usage server, and asserts the buffer is cleared on a
// successful post and (re)written when the post fails.

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(__dirname, '..', 'background.js'), 'utf8');

// Run background.js in a fresh context with a stateful storage mock and a
// stubbed server. `postOk` toggles the /update POST outcome. The server port
// is pre-seeded fresh so getServerUrl() returns it without probing.
function makeContext({ store = {}, postOk = true } = {}) {
  const storage = { serverPort: { port: 7331, cachedAt: Date.now() }, ...store };
  const local = {
    get: async (keys) => {
      if (keys == null) return { ...storage };
      const out = {};
      for (const k of (Array.isArray(keys) ? keys : [keys])) {
        if (k in storage) out[k] = storage[k];
      }
      return out;
    },
    set: async (obj) => { Object.assign(storage, obj); },
    remove: async (keys) => {
      for (const k of (Array.isArray(keys) ? keys : [keys])) delete storage[k];
    },
  };
  const noop = () => {};
  const listener = { addListener: noop, removeListener: noop };
  const updateResp = {
    ok: postOk, status: postOk ? 200 : 503,
    headers: { get: (k) => (k === 'x-claude-usage-server' ? '1.0.0' : null) },
    text: async () => '', json: async () => ({}),
  };
  const context = {
    chrome: {
      runtime: { getManifest: () => ({ version: '0.0.0-test' }), onInstalled: listener, onStartup: listener },
      alarms: { create: noop, onAlarm: listener },
      storage: { local },
      action: { setTitle: async () => {}, onClicked: listener },
      tabs: {
        create: async () => ({ id: 1 }), get: async () => ({}), query: async () => [],
        remove: async () => {}, onUpdated: listener, onActivated: listener,
      },
      webNavigation: { onCompleted: listener, onHistoryStateUpdated: listener, onErrorOccurred: listener },
      scripting: {
        executeScript: async () => [{ result: {
          meters: [{ pct: 5, label: 'Current session', reset_minutes: 100 }],
          plan: 'Pro', _timestamp: 999,
        } }],
      },
      idle: { onStateChanged: listener },
    },
    // Only /update POSTs hit the (stubbed) server; STATUS_URL / probes fail
    // fast so the test stays offline and quick.
    fetch: async (url) => {
      if (typeof url === 'string' && url.includes('/update')) return updateResp;
      throw new Error('stubbed: offline');
    },
    console: { log: noop, warn: noop, error: noop },
    AbortController: globalThis.AbortController,
    setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout,
    Date: globalThis.Date, Math: globalThis.Math, Object: globalThis.Object,
    Array: globalThis.Array, String: globalThis.String, Number: globalThis.Number,
    Boolean: globalThis.Boolean, JSON: globalThis.JSON, Promise: globalThis.Promise,
    Error: globalThis.Error, TextDecoder: globalThis.TextDecoder, TextEncoder: globalThis.TextEncoder,
    URL: globalThis.URL, URLSearchParams: globalThis.URLSearchParams,
  };
  vm.createContext(context);
  vm.runInContext(SRC, context, { filename: 'background.js' });
  return { context, storage };
}

describe('background.js — offline buffer supersede (BASE-2)', () => {
  it('clears a stale offline buffer after a successful full-scrape post', async () => {
    const { context, storage } = makeContext({
      store: {
        // A stale buffer left over from an earlier failed post.
        claude_usage: { meters: [{ pct: 1, label: 'old' }], _timestamp: 1, _buffered_at: 1 },
      },
      postOk: true,
    });
    await context.scrapeAndPost(1);
    assert.equal('claude_usage' in storage, false,
      'a successful post must drop the superseded offline buffer');
    assert.ok(storage._last_scrape_ts > 0, '_last_scrape_ts stamped on the scrape');
  });

  it('writes the offline buffer when the post fails', async () => {
    const { context, storage } = makeContext({ postOk: false });
    await context.scrapeAndPost(1);
    assert.equal('claude_usage' in storage, true,
      'a failed post must buffer the scrape for later flush');
    assert.equal(storage.claude_usage.meters[0].label, 'Current session',
      'buffer holds the just-scraped meters');
  });
});
