const USAGE_URL = 'https://claude.ai/settings/usage';
const STATUS_URL   = 'https://status.claude.com/api/v2/summary.json';
const INTERVAL_MINUTES = 7;
const AUTO_DEBOUNCE_MS = 30_000;
// RD-1 (pass-26 deferred → pass-29): minimum gap between two
// idle-wake-driven fetches. Equal to INTERVAL_MINUTES so the wake
// handler only fires when the alarm would have been overdue anyway —
// lock/unlock and screensaver dim cycles no longer burn a claude.ai
// page-load each, while CI-2's "wake from suspend refreshes the panel"
// purpose is preserved (any suspend longer than the alarm period
// triggers a fresh scrape on resume).
const WAKE_MIN_INTERVAL_MS = INTERVAL_MINUTES * 60 * 1000;
const NEAR_MIN  = 2;   // switch to 1-min cadence when reset is this many minutes away
const RETRY_CAP = 20;  // give up aggressive polling after this many 1-min attempts (~20 min)

// Local server discovery. The server tries to bind 7331 first and falls back
// through 7340 if something else is squatting on 7331. We probe the range via
// GET /hello, cache the winning port in chrome.storage.local, and re-probe on
// POST failure. host_permissions in manifest.json must cover every port in
// PROBE_PORTS — MV3 match patterns don't support port wildcards.
const PROBE_PORTS = Array.from({ length: 10 }, (_, i) => 7331 + i);
const PROBE_TIMEOUT_MS = 500;
// L-3 (pass-15 §11): TTL was 1 h, which forced a re-probe burst every ~9 scrapes
// even when nothing changed. The POST-path isOurs header check already catches
// port-move scenarios within one scrape cycle, so the TTL is only a long-tail
// safety net — 24 h matches real-world port stability better.
const PORT_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

async function probePorts() {
  // Race all ports concurrently. Fastest /hello response with the right
  // signature wins. Returns null if nothing on the range answers.
  // Manual AbortController + setTimeout instead of AbortSignal.timeout()
  // for parity with fetchAnthropicStatus and to avoid the Chrome <102
  // silent-breakage path (TypeError: AbortSignal.timeout is not a function).
  // Validates both `app` and `version` so a local impersonator with the
  // right app string but wrong shape can't win the race.
  //
  // PRT-1 (pass-26): use Promise.any() for a true first-to-resolve race
  // instead of Promise.all() + .find(), which returned the lowest-index
  // port regardless of which responded fastest. A slow squatter on 7331
  // that takes 490 ms no longer beats a real server on 7332 that answered
  // in 5 ms.
  const probes = PROBE_PORTS.map(port => new Promise(async (resolve, reject) => {
    const ctl = new AbortController();
    const timer = setTimeout(() => { ctl.abort(); reject(new Error('timeout')); }, PROBE_TIMEOUT_MS);
    try {
      const r = await fetch(`http://127.0.0.1:${port}/hello`, { signal: ctl.signal });
      if (!r.ok) { reject(new Error('not ok')); return; }
      const j = await r.json();
      if (j && j.app === 'claude-usage' && typeof j.version === 'string') {
        resolve(port);
      } else {
        reject(new Error('bad response'));
      }
    } catch (e) {
      reject(e);
    } finally {
      clearTimeout(timer);
    }
  }));
  try {
    return await Promise.any(probes);
  } catch (_) {
    return null;
  }
}

async function getServerUrl({ forceProbe = false } = {}) {
  if (!forceProbe) {
    const { serverPort } = await chrome.storage.local.get('serverPort');
    if (serverPort?.port && (Date.now() - serverPort.cachedAt) < PORT_CACHE_TTL_MS) {
      return `http://127.0.0.1:${serverPort.port}/update`;
    }
  }
  const port = await probePorts();
  if (port === null) return null;
  await chrome.storage.local.set({ serverPort: { port, cachedAt: Date.now() } });
  console.log(`Claude Usage: probed and cached server port ${port}`);
  return `http://127.0.0.1:${port}/update`;
}

// ── module-scope mutable flags (declared here for TDZ-safety) ───────────────
//
// AR-2 (pass-20): these declarations live ABOVE setActionStatus /
// restoreActionStatus because restoreActionStatus() is called at module
// top-level and reads `_fetching` synchronously. With the declarations
// below the call site, the `let` would be in the Temporal Dead Zone at
// read time → ReferenceError → unhandled rejection → AT-2 broken on every
// SW wake.

let _fetching = false;
// AS-1 (pass-26 deferred → pass-29): two-phase mutex for
// _autoScrapeIfEligible. `_evaluating` is held only during the
// eligibility-check phase (storage.get + predicates); `_fetching` is the
// actual scrape mutex. fetchUsage checks ONLY `_fetching`, so an alarm
// arriving during an in-progress eligibility check that is about to bail
// is no longer starved for the next 7-min cycle. R-1 (pass-16) is
// preserved because `_evaluating` is acquired synchronously before the
// first await — two simultaneous events still can't race through the
// storage.get.
let _evaluating = false;
// One-shot guard for the tabs.query swallow in fetchUsage. If Chrome ever
// tightens permission semantics so tabs.query throws, we'd otherwise silently
// fall back to the background-tab path forever — log once per SW lifetime.
let _tabQueryWarned = false;


// ── observable error state (O-1, pass-17) ───────────────────────────────────
//
// Default-title says "click to refresh now"; this rewrites it after every
// postUpdate outcome so the user can hover the toolbar icon and see whether
// the last cycle succeeded — and if not, why. First line of triage when the
// GNOME panel goes grey: hover the Chrome icon.
/**
 * Update the toolbar-icon tooltip after every postUpdate outcome.
 *
 * Per-kind arg semantics (OT-2, pass-19):
 *   kind='ok'             — uses meterCount
 *   kind='partial'        — no other args; tooltip points at `claude-usage-status`
 *   kind='rejected'       — uses errorMsg (the 4xx body); points at the server journal
 *   kind='unavailable'    — no other args; points at the systemd unit
 *   kind='recovered'      — no other args; offline buffer was flushed
 *   kind='scrape-failed'  — uses errorMsg (scrape exception); shown verbatim
 *
 * errorMsg is capped at 80 chars (AT-1, pass-18) to prevent oversized tooltips.
 */
async function setActionStatus(kind, meterCount, errorMsg) {
  if (typeof chrome === 'undefined' || !chrome.action) return;
  const stamp = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  // CAP-1 (pass-23): same UTF-16 surrogate-split hazard UT-1 fixed in
  // fetchAnthropicStatus's trunc(). cap() trims errorMsg for the toolbar
  // tooltip — `errorMsg` is a server 4xx body or a scrape exception, both
  // ASCII today, but locking in code-point-aware semantics keeps the bug
  // class from re-emerging if anything ever produces a multibyte error.
  const cap = s => {
    if (typeof s !== 'string') return s;
    const cps = [...s];
    return cps.length > 80 ? cps.slice(0, 77).join('') + '...' : s;
  };
  let title;
  if (kind === 'ok') {
    title = `Claude Usage: OK · ${meterCount} meters · last fetch ${stamp}`;
  } else if (kind === 'partial') {
    // OT-3 (pass-19): drop `(see _parse_failure)` — _parse_failure is an
    // internal cache key name end users can't act on. Point at the actual
    // triage tool instead.
    title = `Claude Usage: ⚠ no meters scraped at ${stamp}\n`
          + `Run claude-usage-status for diagnosis`;
  } else if (kind === 'rejected') {
    title = `Claude Usage: ⚠ local server rejected payload (${cap(errorMsg)}) at ${stamp}\n`
          + `Check: journalctl --user-unit=claude-usage-fetch.service`;
  } else if (kind === 'unavailable') {
    title = `Claude Usage: ⚠ local server unreachable at ${stamp}\n`
          + `Check: systemctl --user status claude-usage-fetch.service`;
  } else if (kind === 'recovered') {
    title = `Claude Usage: ✓ offline buffer flushed at ${stamp}`;
  } else if (kind === 'scrape-failed') {
    title = `Claude Usage: ⚠ scrape failed (${cap(errorMsg)}) at ${stamp}`;
  } else {
    title = `Claude Usage: ⚠ ${kind} at ${stamp}`;
  }
  try {
    await chrome.action.setTitle({title});
    // AT-2 (pass-18): MV3 SWs are ephemeral — setTitle reverts to
    // manifest.default_title on SW dormancy. Persist so restoreActionStatus()
    // can re-apply on next SW wake; otherwise the O-1 hover value evaporates
    // between cycles.
    await chrome.storage.local.set({_last_action_title: title});
  } catch (_) {}
}


// AT-2 (pass-18): re-apply the last tooltip on SW startup. Called at
// top-level so every SW wake (cold start, alarm fire after dormancy)
// restores observable state.
//
// AR-1 (pass-19): guard against the race where the SW wake that triggers
// us is the same wake that's about to call setActionStatus. Without the
// guard, the worst-case interleaving is: restore's storage.get resolves
// → fresh setActionStatus runs and writes → restore's later setTitle
// overwrites with the stale title. We check `_fetching` both before and
// after the storage read so a live fetch's setActionStatus wins.
async function restoreActionStatus() {
  if (typeof chrome === 'undefined' || !chrome.action) return;
  if (_fetching) return;
  try {
    const {_last_action_title} = await chrome.storage.local.get('_last_action_title');
    if (_last_action_title && !_fetching) {
      await chrome.action.setTitle({title: _last_action_title});
    }
  } catch (_) {}
}
restoreActionStatus();


// POST to the local server with auto-rediscovery. On network error, 5xx, or
// a response missing the claude-usage signature header (squatter on the
// cached port), invalidate the cache and re-probe once. 4xx WITH the signature
// is treated as a real server response (validator rejection) — return the
// Response so callers can decide whether to discard the payload. Throws only
// if all attempts fail.
//
// PR-2 (pass-26): retry up to 3 times (0 s, 1 s, 3 s back-off) so a sub-5 s
// server restart during a .deb upgrade doesn't strand the buffered scrape
// until the next 7-minute alarm tick. The first attempt is immediate (no
// delay) so fast success is not penalised.
async function postUpdate(body) {
  const payload = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
  // PRT-1 (pass-26): validate the header value is semver-shaped, not just
  // present. A squatter that adds an arbitrary x-claude-usage-server header
  // but not a valid version string is now rejected. Mirrors the /hello check.
  // Reject any response without our signature header. The PROBE path validates
  // via GET /hello at discovery; this header is the in-band POST check that
  // catches a squatter that took our cached port between probe and POST. With
  // host_permissions for 127.0.0.1, all response headers are readable from
  // the SW — no CORS exposure dance needed.
  const isOurs = r => {
    const v = r.headers.get('x-claude-usage-server');
    return typeof v === 'string' && /^\d+\.\d+\.\d+/.test(v);
  };

  let lastErr;
  for (const delay of [0, 1000, 3000]) {
    if (delay) await new Promise(r => setTimeout(r, delay));

    let url = await getServerUrl();
    if (url) {
      try {
        const r = await fetch(url, payload);
        // PR-1 (pass-15 §9): any well-formed response from our server (signature
        // header present) is real — including 5xx. The previous 4xx-only branch
        // would re-probe on a hypothetical 5xx-with-signature, wasting 10
        // parallel /hello fetches. Defense in depth — the server today never
        // emits 5xx (its catch-all returns 400), but the asymmetry was wrong.
        if (r.status < 600 && isOurs(r)) return r;
      } catch (e) {
        lastErr = e; /* network error or wrong-server — fall through to re-probe */
      }
    }
    url = await getServerUrl({ forceProbe: true });
    if (!url) {
      lastErr = new Error('claude-usage server not found on probe range');
      continue;
    }
    try {
      const r = await fetch(url, payload);
      if (!isOurs(r)) {
        lastErr = new Error('server response missing claude-usage signature');
        continue;
      }
      return r;
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr ?? new Error('claude-usage server not found on probe range');
}

// Stamped on every POST so the server can detect version skew. Chrome does
// not auto-reload unpacked extensions on .deb upgrade — without this, a user
// can sit on a stale extension forever with no visible signal.
const EXT_VERSION = chrome.runtime.getManifest().version;
// _fetching and _tabQueryWarned declarations moved above setActionStatus
// (AR-2, pass-20). Required for restoreActionStatus's top-level call to
// read _fetching without hitting the TDZ.

// Poll Anthropic's public Statuspage. JSON, no auth, doesn't burn tokens.
// Returns the compact subset the GNOME extension uses to compute the broken
// tier; null on network/parse failure (treated as "no signal", not "no outage").
// 5 s timeout via AbortController — a slow statuspage during a co-incident
// outage shouldn't hold `_fetching` open and block the next scrape cycle.
async function fetchAnthropicStatus() {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 5000);
    try {
        const resp = await fetch(STATUS_URL, { signal: ctl.signal });
        if (!resp.ok) return null;
        const j = await resp.json();
        const claudeAi = (j.components || []).find(c => c.name === 'claude.ai');
        // AS-1 (pass-17): Statuspage `description` is free-form prose that
        // routinely exceeds the server's MAX_STR_LEN=128 bound. Without this
        // truncate, the server rejects the entire POST → cache never updates
        // → BROKEN tier during the exact outage the field exists to surface.
        // 120 leaves 8 chars of headroom under the validator's cap.
        // UT-1 (pass-18, fixed post-pass-21): code-point-aware truncation.
        // `String.prototype.slice` cuts by UTF-16 code unit — if Anthropic
        // ever ships an emoji or CJK character that lands a surrogate pair
        // across position 117, the result is invalid UTF-16 (lone surrogate).
        // Spreading into an array and slicing iterates by code point. Today
        // Statuspage is English ASCII so this is theoretical; locks in
        // correctness if localisation ever ships.
        const trunc = s => {
            if (typeof s !== 'string') return s;
            const cps = [...s];
            return cps.length > 120 ? cps.slice(0, 117).join('') + '...' : s;
        };
        return {
            indicator: j.status?.indicator ?? null,
            description: trunc(j.status?.description ?? null),
            claude_ai_component_status: claudeAi?.status ?? null,
        };
    } catch (_) {
        return null;
    } finally {
        clearTimeout(timer);
    }
}

async function getFailCount() {
    const { _scrape_fail_count = 0 } = await chrome.storage.local.get('_scrape_fail_count');
    return _scrape_fail_count;
}

async function setFailCount(n) {
    await chrome.storage.local.set({ _scrape_fail_count: n });
}

// Schedule (or cancel) the fetch-on-reset alarm based on fresh meter data.
// Called at the end of every successful scrapeAndPost so all trigger paths
// (periodic alarm, idle-wake, tab-focus, manual click) feed it.
async function scheduleResetRefresh(meters) {
    const { _reset_watch: watch, _reset_retry_count: retryCount = 0 } =
        await chrome.storage.local.get(['_reset_watch', '_reset_retry_count']);

    // Stand-down: confirm the reset happened against the persisted watch state.
    if (watch) {
        const watched = meters.find(m => m.label === watch.label);
        if (watched) {
            const pctCleared = (watched.pct ?? 0) < 100;
            const freshPeriod = typeof watched.reset_minutes === 'number' &&
                watched.reset_minutes > watch.reset_minutes;
            if (pctCleared || freshPeriod) {
                await chrome.alarms.clear('fetch-on-reset');
                await chrome.storage.local.remove(['_reset_watch', '_reset_retry_count']);
                return;
            }
        }
    }

    // Find the soonest 100% meter with a known reset distance.
    const maxed = meters
        .filter(m => (m.pct ?? 0) >= 100 && typeof m.reset_minutes === 'number')
        .sort((a, b) => a.reset_minutes - b.reset_minutes);

    if (maxed.length === 0) {
        await chrome.alarms.clear('fetch-on-reset');
        await chrome.storage.local.remove(['_reset_watch', '_reset_retry_count']);
        return;
    }

    const m = maxed[0];

    if (m.reset_minutes > NEAR_MIN) {
        // Far from reset: one-shot alarm 1 min before predicted reset.
        await chrome.storage.local.set({
            _reset_watch: { label: m.label, reset_minutes: m.reset_minutes, ts: Date.now() },
        });
        await chrome.storage.local.remove('_reset_retry_count');
        chrome.alarms.create('fetch-on-reset', { when: Date.now() + (m.reset_minutes - 1) * 60_000 });
    } else {
        // At boundary: 1-min repeating alarm until reset confirmed or backstop.
        const newCount = retryCount + 1;
        if (newCount > RETRY_CAP) {
            await chrome.alarms.clear('fetch-on-reset');
            await chrome.storage.local.remove(['_reset_watch', '_reset_retry_count']);
            return;
        }
        await chrome.storage.local.set({
            _reset_watch: { label: m.label, reset_minutes: m.reset_minutes, ts: Date.now() },
            _reset_retry_count: newCount,
        });
        chrome.alarms.create('fetch-on-reset', { periodInMinutes: 1 });
    }
}

// Parse "Resets in X hr Y min" / "Resets in X min" / "Resets Tue 5:00 PM"
// into minutes-from-now. Returns null when the string doesn't match a
// known shape. Mirrors the parsing logic in desktop/gnome/extension.js
// formatReset(); we run it server-side here so the cache file carries
// reset_minutes alongside the raw string for downstream consumers.
function parseResetMinutes(reset) {
  if (!reset) return null;
  let m;
  // BASE-6 (2026-05-30 review): cap at 31 days like the weekday branch below —
  // an outlier (claude.ai glitch) over the server's reset_minutes bound (44640)
  // would otherwise get the whole POST rejected by the validator.
  m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
  if (m) return Math.min(parseInt(m[1], 10) * 60 + parseInt(m[2], 10), 60 * 24 * 31);
  m = reset.match(/[Rr]esets? in (\d+) min/);
  if (m) return Math.min(parseInt(m[1], 10), 60 * 24 * 31);
  m = reset.match(/[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
  if (m) {
    const [, day, hStr, mnStr, ap] = m;
    let h = parseInt(hStr, 10), mn = parseInt(mnStr, 10);
    if (h < 1 || h > 12 || mn < 0 || mn > 59) return null;
    if (ap === 'PM' && h !== 12) h += 12;
    else if (ap === 'AM' && h === 12) h = 0;
    const now = new Date();
    const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
    if (!(day in wdMap)) return null;
    let ahead = (wdMap[day] - now.getDay() + 7) % 7;
    if (ahead === 0) {
      const candidate = new Date(now);
      candidate.setHours(h, mn, 0, 0);
      if (candidate <= now) ahead = 7;
    }
    const target = new Date(now);
    target.setDate(now.getDate() + ahead);
    target.setHours(h, mn, 0, 0);
    return Math.min(Math.floor((target - now) / 60000), 60 * 24 * 31);
  }
  return null;
}

// Scrape claude.ai/settings/usage from the given tab (which must have
// finished loading) and POST the result to the local server. Used by
// both fetchUsage (own background tab) and the auto-scrape listener
// (any user tab on the usage page).
async function scrapeAndPost(tabId) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    // Returns a Promise so executeScript waits for React hydration before
    // scraping. MutationObserver resolves as soon as a "% used" text node
    // appears; a 30 s deadline fires the scrape unconditionally as a fallback.
    func: () => new Promise(resolve => {
      function isHydrated() {
        // SC-2 (pass-15 §6): match the predicate to the consumer. textContent
        // sees hidden DOM + <script>/<style> bodies; innerText is layout-aware
        // and matches what doScrape actually reads. Using textContent here
        // could resolve hydration against hidden React placeholder text while
        // doScrape then returns zero meters from the still-empty rendered DOM.
        return /\d+%\s*used/i.test(document.body.innerText);
      }

      function doScrape() {
        const body = document.body.innerText;
        const lines = body.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        const meters = [];
        let plan = null;

        // Plan label (e.g. "Max (5x)", "Pro", "Free", "Team").
        // Anchor on full-line equality so banners like "Pro tip:" don't hijack the field.
        for (const line of lines) {
          const pm = line.match(/^(?:Plan:\s*)?(Max(?:\s*\([^)]+\))?|Pro|Free|Team)$/);
          if (pm && line.length < 40) { plan = pm[1]; break; }
        }

        // ── Section 1: Plan usage limits ─────────────────────────────────
        const planStart = lines.findIndex(l => l === 'Plan usage limits');
        const planEnd   = lines.findIndex((l, i) =>
          i > planStart && /^(Additional features|Last updated:|Extra usage)/.test(l));
        const planRange = [planStart >= 0 ? planStart + 1 : 0, planEnd >= 0 ? planEnd : lines.length];

        for (let i = planRange[0]; i < planRange[1]; i++) {
          const pctMatch = lines[i].match(/^(\d+)%\s*used$/i);
          if (!pctMatch) continue;
          const pct   = Math.min(100, Math.max(0, parseInt(pctMatch[1], 10)));
          const reset = i >= 1 && /[Rr]esets?/.test(lines[i - 1]) ? lines[i - 1] : null;
          const label = i >= 2 ? lines[i - 2] : null;
          if (!label || /^(Weekly limits|Plan usage limits|Learn more)/i.test(label)) continue;
          meters.push({pct, label, reset});
        }

        // ── Section 2: Additional features ───────────────────────────────
        const addlStart = lines.findIndex(l => /^Additional features$/i.test(l));
        const addlEnd   = lines.findIndex((l, i) =>
          i > addlStart && /^(Extra usage|Last updated:)/.test(l));
        if (addlStart >= 0) {
          const end = addlEnd >= 0 ? addlEnd : lines.length;
          for (let i = addlStart + 1; i < end; i++) {
            const countMatch = lines[i].match(/^(\d+)\s*\/\s*(\d+)$/);
            if (!countMatch) continue;
            const count = parseInt(countMatch[1], 10);
            const total = parseInt(countMatch[2], 10);
            const pct   = Math.min(100, total > 0 ? Math.round(count / total * 100) : 0);
            const label = i >= 2 ? lines[i - 2] : null;
            if (!label || /^(Additional features|Learn more)/i.test(label)) continue;
            meters.push({count, total, pct, label, reset: null});
          }
        }

        // ── Section 3: Extra usage ────────────────────────────────────────
        const extraStart = lines.findIndex(l => l === 'Extra usage');
        const extraToggleEl = document.querySelector('[role="switch"][aria-label="Extra usage"]');
        const extraOn = extraToggleEl?.getAttribute('aria-checked') === 'true';
        if (extraStart >= 0 && extraOn) {
          let spent = null, balance = null, pct = null, reset = null;
          for (let i = extraStart + 1; i < lines.length; i++) {
            if (/^Last updated:/.test(lines[i])) break;
            const spentMatch = lines[i].match(/^(\$[\d,.]+)\s*spent$/i);
            if (spentMatch) { spent = spentMatch[1]; continue; }
            const pctMatch = lines[i].match(/^(\d+)%\s*used$/i);
            if (pctMatch) {
              pct   = Math.min(100, Math.max(0, parseInt(pctMatch[1], 10)));
              reset = i >= 1 && /[Rr]esets?/.test(lines[i - 1]) ? lines[i - 1] : null;
              continue;
            }
            const balMatch = lines[i].match(/^(\$\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)$/);
            if (balMatch && i + 1 < lines.length && /Current balance/i.test(lines[i + 1])) {
              balance = balMatch[1];
            }
          }
          if (pct !== null || spent !== null) {
            meters.push({label: 'Extra usage', pct: pct ?? 0, spent, balance, reset});
          }
        }

        // L-2 (pass-17, tightened pass-18 PF-1): anchor on `\d+\s*%\s*used`
        // — the actual meter pattern — not bare `\d+%`. Avoids false
        // positives from marketing copy, footers, and login interstitials.
        const text = document.body.innerText;
        const _parse_failure = (meters.length === 0 && /\d+\s*%\s*used/i.test(text))
            ? 'locale_or_layout' : null;
        return {
            meters, plan,
            _timestamp: Math.floor(Date.now() / 1000),
            ...(_parse_failure && { _parse_failure }),
        };
      }

      if (isHydrated()) { resolve(doScrape()); return; }

      const deadline = setTimeout(() => { observer.disconnect(); resolve(doScrape()); }, 30_000);
      const observer = new MutationObserver(() => {
        if (!isHydrated()) return;
        clearTimeout(deadline);
        observer.disconnect();
        resolve(doScrape());
      });
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }),
  });

  const data = result?.result;

  // DIFF-2 (2026-05-30 review): stamp the scrape time as soon as the scrape
  // executes — BEFORE the empty-meters early return below — so a persistently
  // failing scrape (logged out, or a claude.ai DOM change → zero meters) still
  // debounces idle-wake and auto-scrape. Previously this ran only on the
  // success path, so a logged-out user re-scraped on every screen unlock.
  await chrome.storage.local.set({ _last_scrape_ts: Date.now() });

  // Fetch Anthropic's status page in parallel — included in every POST
  // (full or partial) so the GNOME extension can flag confirmed outages.
  const anthropic_status = await fetchAnthropicStatus();

  if (!data || !data.meters.length) {
    console.warn('Claude Usage: no meters extracted');
    // Partial update: increment scrape-fail counter, push the new count
    // and the status-page result to the server. Server's merge logic
    // preserves last-known meters/plan/_timestamp. Always include
    // _anthropic_status (even when null) so the cache clears a stale
    // outage flag once the incident resolves.
    const fails = (await getFailCount()) + 1;
    await setFailCount(fails);
    const partial = {
      _scrape_fail_count: fails,
      _anthropic_status: anthropic_status,
      _ext_version: EXT_VERSION,
    };
    // LP-1 (pass-19): the scraper sets `_parse_failure` exactly when
    // meters is empty AND the page text looks like it should have had
    // meters (the `\d+\s*%\s*used` heuristic). The partial POST below
    // is the only path that fires when scraping returned no meters, so
    // it's the only path that can carry the signal to the server cache.
    // Without this propagation, the L2-2 consumer in claude-usage-status
    // never sees the field — the whole feature was dead before this fix.
    const partial_with_pf = data?._parse_failure
        ? { ...partial, _parse_failure: data._parse_failure }
        : partial;
    try { await postUpdate(partial_with_pf); } catch (_) {}
    // OT-1 (pass-18): empty-meters path — tell the user the scrape ran
    // but found nothing parseable. Distinguishes from the success path's
    // "OK · N meters" so the hover triage isn't misleading.
    await setActionStatus('partial');
    return;
  }

  if (!data.plan) console.warn('Claude Usage: plan tier not recognized; status bar will show "Claude"');

  // Enrich meters with parsed reset_minutes so the server (which doesn't
  // parse strings) can track per-meter period lengths for pacing colors
  // and recompute the live tooltip countdown.
  for (const m of data.meters) {
    if (m.reset) m.reset_minutes = parseResetMinutes(m.reset);
  }

  // Successful scrape — reset the fail counter, attach status-page result.
  // _anthropic_status may be null (statuspage fetch failed or timed out);
  // include it anyway so the server's merge clears any stale outage flag
  // that would otherwise outlive its incident.
  await setFailCount(0);
  data._scrape_fail_count = 0;
  data._anthropic_status = anthropic_status;
  data._ext_version = EXT_VERSION;

  try {
    const resp = await postUpdate(data);
    if (!resp.ok) throw new Error(`server ${resp.status}`);
    console.log(`Claude Usage: sent ${data.meters.length} meters to local server`);
    // O-1 (pass-17): observable error state. Hovering the toolbar icon now
    // shows the last outcome, so a stale GNOME panel can be triaged from
    // inside Chrome without opening the SW DevTools.
    await setActionStatus('ok', data.meters.length);
    // BASE-2 (2026-05-30 review): a successful full-scrape post supersedes any
    // offline buffer, so drop it. Otherwise a later fetchUsage could flush the
    // now-stale buffer and the server's ordering-blind merge would regress its
    // _timestamp/meters to that older snapshot. This also makes the flush's
    // non-atomic remove() safe — a re-flushed buffer is never newer than the
    // freshest confirmed post.
    await chrome.storage.local.remove('claude_usage');
  } catch (e) {
    // 4xx with the claude-usage signature means the server is up but rejected
    // the payload (validator caught something). Route the user to the journal,
    // not to "is the server running" — they're different diagnostics.
    if (e.message?.startsWith('server 4')) {
      console.warn('Claude Usage: server rejected POST:', e.message,
                   '— see journalctl --user-unit=claude-usage-fetch.service');
      await setActionStatus('rejected', null, e.message);
    } else {
      console.warn('Claude Usage: local server unavailable, buffering offline:', e.message);
      await setActionStatus('unavailable', null, e.message);
    }
    await chrome.storage.local.set({ claude_usage: { ...data, _buffered_at: Date.now() } });
  }

  await scheduleResetRefresh(data.meters);
}

async function fetchUsage() {
  if (_fetching) return;
  _fetching = true;
  let createdTab = null;
  // Outer try/finally wraps the *entire* body so a throw from any await
  // (storage.get, tabs.query, tabs.create, scripting.executeScript, ...)
  // still resets _fetching. Inner try/catches handle graceful degradation
  // of individual operations.
  try {
    // Flush any data stored offline while the server was unavailable
    const { claude_usage: stored } = await chrome.storage.local.get('claude_usage');
    if (stored) {
      // Discard buffered data older than 24 h — it's stale and not worth
      // sending; the next live scrape will produce fresh data.
      if (Date.now() - (stored._buffered_at || 0) > 86_400_000) {
        console.warn('Claude Usage: discarding expired offline buffer');
        await chrome.storage.local.remove('claude_usage');
      } else {
        try {
          const r = await postUpdate(stored);
          if (r.ok) {
            await chrome.storage.local.remove('claude_usage');
            console.log('Claude Usage: flushed offline data to server');
            // OT-1 (pass-18): tell the user the buffered data was delivered.
            await setActionStatus('recovered');
          } else if (r.status >= 400 && r.status < 500) {
            // 4xx means the buffered payload is malformed (e.g. validator
            // rejected it after a server update tightened the schema).
            // Discard so we stop retrying forever; the next fresh scrape
            // will write valid data.
            console.warn('Claude Usage: discarding malformed offline buffer:', r.status);
            await chrome.storage.local.remove('claude_usage');
          }
        } catch (_) {}
      }
    }

    // Recover any orphan scrape tab from a previous fetch killed mid-scrape
    // (SW suspension between tabs.create and the finally's tabs.remove).
    // Match by tab ID — not by URL — so we never close a tab the user
    // opened themselves at the same URL.
    try {
      const { _scrape_tabs = [], _scrape_tab_pending = null } =
          await chrome.storage.local.get(['_scrape_tabs', '_scrape_tab_pending']);
      for (const id of _scrape_tabs) {
        try { await chrome.tabs.remove(id); } catch (_) {}
      }
      // BASE-3 (2026-05-30 review): if a prior fetch set the pending marker but
      // died in the gap between tabs.create and persisting the id below, the
      // id-based sweep above can't find the orphan. When the marker is stale
      // (older than the 30 s load timeout, so it can't be a create still in
      // flight), close orphaned BACKGROUND scrape tabs by URL. Restricted to
      // active:false so a tab the user is actively viewing is never touched;
      // the stale-marker guard confines the rare false-positive (a user's own
      // background usage tab) to the SW-death-mid-create window.
      if (_scrape_tab_pending && Date.now() - _scrape_tab_pending > 30_000) {
        try {
          const orphans = await chrome.tabs.query(
              { url: 'https://claude.ai/settings/usage*', active: false });
          for (const t of orphans) { try { await chrome.tabs.remove(t.id); } catch (_) {} }
        } catch (_) {}
      }
      if (_scrape_tabs.length || _scrape_tab_pending) {
        await chrome.storage.local.set({ _scrape_tabs: [], _scrape_tab_pending: null });
      }
    } catch (_) {}

    // Prefer an already-loaded user tab — skips the tab-create + page-load
    // round trip entirely (the slowest part of a scrape cycle). executeScript
    // runs in an isolated world, so the user's tab is read, not modified.
    // Fall through to a background tab if no candidate is fully loaded.
    let scrapeTabId = null;
    try {
      const candidates = await chrome.tabs.query({ url: 'https://claude.ai/settings/usage*' });
      const reusable = candidates.find(t =>
        t.status === 'complete' && (t.url || '').split(/[?#]/)[0] === USAGE_URL);
      if (reusable) scrapeTabId = reusable.id;
    } catch (e) {
      if (!_tabQueryWarned) {
        console.warn('Claude Usage: tabs.query failed, falling back to background tab:', e.message);
        _tabQueryWarned = true;
      }
    }

    if (scrapeTabId === null) {
      // BASE-3 (2026-05-30 review): record intent BEFORE create so a SW death
      // between create and the id-persist below is still recoverable by the
      // sweep's pending-marker path above.
      await chrome.storage.local.set({ _scrape_tab_pending: Date.now() });
      createdTab = await chrome.tabs.create({ url: USAGE_URL, active: false });
      scrapeTabId = createdTab.id;
      await chrome.storage.local.set({ _scrape_tabs: [scrapeTabId], _scrape_tab_pending: null });

      await new Promise((resolve, reject) => {
        // Lifted to consts so the timeout, the load listener, and the
        // navigation-error listener can all reference each other.
        const cleanup = () => {
          chrome.tabs.onUpdated.removeListener(listener);
          chrome.webNavigation.onErrorOccurred.removeListener(errListener);
          clearTimeout(timeout);
        };
        const listener = (tabId, info, tab) => {
          if (tabId !== createdTab.id) return;
          if (info.status === 'complete') {
            cleanup();
            // TC-1 (pass-26): error pages (502, DNS failure, corporate proxy)
            // also fire status='complete'. The onErrorOccurred listener below
            // is the primary guard; this URL check is a cheap belt-and-
            // suspenders. DIFF-3 (2026-05-30 review): tab.url is hidden for the
            // chrome-error:// origin now that the broad 'tabs' permission is
            // gone (host_permissions doesn't cover it), so the URL check alone
            // can no longer detect a failed nav.
            const url = tab?.url || '';
            if (url.startsWith('chrome-error://') || url.startsWith('chrome://')) {
              reject(new Error(`navigation failed: ${url}`));
              return;
            }
            resolve();
          }
        };
        // DIFF-3 (2026-05-30 review): detect navigation failure directly via
        // webNavigation (an already-granted permission), independent of whether
        // tab.url is exposed. Main frame (frameId 0) on a claude.ai navigation.
        const errListener = (details) => {
          if (details.tabId !== createdTab.id || details.frameId !== 0) return;
          cleanup();
          reject(new Error(`navigation failed: ${details.error || 'unknown'}`));
        };
        const timeout = setTimeout(() => {
          cleanup();
          reject(new Error('tab load timeout'));
        }, 30_000);
        chrome.tabs.onUpdated.addListener(listener);
        chrome.webNavigation.onErrorOccurred.addListener(
          errListener, { url: [{ hostEquals: 'claude.ai' }] });
      });
    }

    await scrapeAndPost(scrapeTabId);
  } catch (err) {
    console.error('Claude Usage fetch failed:', err.message);
    // Page never loaded / tab create failed / executeScript threw —
    // bump the counter and push a status-only POST so the GNOME extension
    // can flag the tier even though no scrape data exists for this cycle.
    try {
      const fails = (await getFailCount()) + 1;
      await setFailCount(fails);
      const anthropic_status = await fetchAnthropicStatus();
      // Always include _anthropic_status (may be null) so the server clears
      // any stale outage flag from a prior cycle.
      const partial = {
        _scrape_fail_count: fails,
        _anthropic_status: anthropic_status,
        _ext_version: EXT_VERSION,
      };
      console.warn('Claude Usage: reporting error to local server');
      await postUpdate(partial);
      // OT-1 (pass-18): scrape itself threw — surface the cause + count.
      await setActionStatus('scrape-failed', null, String(err?.message ?? err));
    } catch (_) {}
  } finally {
    if (createdTab) {
      try { await chrome.tabs.remove(createdTab.id); } catch (_) {}
      try { await chrome.storage.local.set({ _scrape_tabs: [], _scrape_tab_pending: null }); } catch (_) {}
    }
    _fetching = false;
  }
}

// Shared guard for both auto-scrape paths below. Checks URL, debounce,
// and in-flight state before handing off to scrapeAndPost.
//
// AS-1 (pass-26 deferred → pass-29): two-phase mutex.
//   Phase 1 — eligibility: acquire `_evaluating` synchronously, run the
//     storage-backed eligibility check. Releases `_evaluating` whether
//     eligibility passes or fails.
//   Phase 2 — scrape: acquire `_fetching` synchronously after Phase 1
//     commits, run scrapeAndPost.
// Critical contract:
//   (a) `_evaluating` is acquired synchronously before the storage.get
//       so two simultaneous events can't both race through it (R-1).
//   (b) `_fetching` is acquired synchronously inside Phase 1's try block,
//       guarded by `if (_fetching) return` to honour any concurrent
//       alarm-fired fetchUsage.
//   (c) fetchUsage checks ONLY `_fetching`, never `_evaluating` — that's
//       what eliminates AS-1's alarm starvation during ineligible fires.
async function _autoScrapeIfEligible(tabId, url) {
  if (url.split(/[?#]/, 1)[0] !== USAGE_URL) return;
  if (_evaluating || _fetching) return;
  _evaluating = true;
  try {
    const { _scrape_tabs = [], _last_scrape_ts = 0 } =
        await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);
    if (_scrape_tabs.includes(tabId)) return;
    if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
    if (_fetching) return;
    _fetching = true;
  } finally {
    _evaluating = false;
  }
  try {
    await scrapeAndPost(tabId);
  } catch (e) {
    console.warn('Claude Usage auto-scrape failed:', e.message);
  } finally {
    _fetching = false;
  }
}

// Auto-scrape on hard navigation (address bar, bookmark, new tab, page reload).
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== 'complete') return;
  if (!tab.url) return;
  await _autoScrapeIfEligible(tabId, tab.url);
});

// Auto-scrape on SPA navigation (claude.ai sidebar → Settings → Usage).
// tabs.onUpdated never fires `status: complete` for history.pushState;
// webNavigation.onHistoryStateUpdated covers that path.
chrome.webNavigation.onHistoryStateUpdated.addListener(
  async ({ tabId, url }) => { await _autoScrapeIfEligible(tabId, url); },
  { url: [{ hostEquals: 'claude.ai' }] }
);

// Auto-scrape when an already-loaded Usage tab gets focused — covers the
// "GNOME popup opened the URL but Chrome focused an existing tab" path,
// where no onUpdated/historyStateUpdated event fires. AUTO_DEBOUNCE_MS
// prevents excessive scraping on normal tab-switching.
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status !== 'complete' || !tab.url) return;
    await _autoScrapeIfEligible(tabId, tab.url);
  } catch (_) {}
});

// Direct fetchUsage() on install/reload and browser startup — MV3 alarm
// scheduling adds seconds of latency before the first fire, on top of the
// tab-load + hydration wait inside fetchUsage. Calling directly skips that
// scheduling delay so reloading the extension visibly updates the panel.
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('fetch-usage', {
    delayInMinutes: INTERVAL_MINUTES,
    periodInMinutes: INTERVAL_MINUTES,
  });
  fetchUsage();
});

chrome.runtime.onStartup.addListener(() => {
  // Recreate the alarm even though MV3 alarms normally persist across browser
  // restarts — wiped registries (profile corruption, uninstall/reinstall
  // sequences, storage quota purges) still recover next startup.
  chrome.alarms.create('fetch-usage', {
    delayInMinutes: INTERVAL_MINUTES,
    periodInMinutes: INTERVAL_MINUTES,
  });
  fetchUsage();
});

// CI-2 (pass-17): chrome.alarms does NOT catch up on suspend/resume — one
// fetch per resume, not one per missed period. After a laptop sleeps for
// hours the GNOME panel hits BROKEN tier on wake until the first post-wake
// fetch lands. Listen for the OS coming back to active and fire immediately.
// "active" fires on screen unlock / wake-from-suspend. The `idle` permission
// is required for chrome.idle.* to be defined.
//
// RD-1 (pass-26 deferred → pass-29): 'active' also fires on every screen
// unlock and screensaver-dim recovery, not just wake-from-suspend.
// Without a debounce, a user who locks their screen ten times during a
// workday pays ten background tab loads + ten Statuspage hits.
// WAKE_MIN_INTERVAL_MS gates against `_last_scrape_ts`; storage errors
// fall through so the CI-2 wake-from-suspend purpose is preserved even
// if storage is wedged.
if (chrome.idle && chrome.idle.onStateChanged) {
  chrome.idle.onStateChanged.addListener(async state => {
    if (state !== 'active') return;
    try {
      const { _last_scrape_ts = 0 } =
          await chrome.storage.local.get('_last_scrape_ts');
      if (Date.now() - _last_scrape_ts < WAKE_MIN_INTERVAL_MS) return;
    } catch (_) { /* fall through to fire */ }
    fetchUsage();
  });
}

chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name === 'fetch-usage' || alarm.name === 'fetch-on-reset') await fetchUsage();
});

chrome.action.onClicked.addListener(async () => { await fetchUsage(); });
