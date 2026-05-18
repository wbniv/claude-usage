const USAGE_URL = 'https://claude.ai/settings/usage';
const LOCAL_SERVER = 'http://127.0.0.1:7331/update';
const STATUS_URL   = 'https://status.claude.com/api/v2/summary.json';
const INTERVAL_MINUTES = 7;
const AUTO_DEBOUNCE_MS = 30_000;

// Stamped on every POST so the server can detect version skew. Chrome does
// not auto-reload unpacked extensions on .deb upgrade — without this, a user
// can sit on a stale extension forever with no visible signal.
const EXT_VERSION = chrome.runtime.getManifest().version;

let _fetching = false;

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
        return {
            indicator: j.status?.indicator ?? null,
            description: j.status?.description ?? null,
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

// Parse "Resets in X hr Y min" / "Resets in X min" / "Resets Tue 5:00 PM"
// into minutes-from-now. Returns null when the string doesn't match a
// known shape. Mirrors the parsing logic in gnome-extension/extension.js
// formatReset(); we run it server-side here so the cache file carries
// reset_minutes alongside the raw string for downstream consumers.
function parseResetMinutes(reset) {
  if (!reset) return null;
  let m;
  m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
  if (m) return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
  m = reset.match(/[Rr]esets? in (\d+) min/);
  if (m) return parseInt(m[1], 10);
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
    // appears; a 10 s deadline fires the scrape unconditionally as a fallback.
    func: () => new Promise(resolve => {
      function isHydrated() {
        return /\d+%\s*used/i.test(document.body.textContent);
      }

      function doScrape() {
        const body = document.body.textContent;
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

        return { meters, plan, _timestamp: Math.floor(Date.now() / 1000) };
      }

      if (isHydrated()) { resolve(doScrape()); return; }

      const deadline = setTimeout(() => { observer.disconnect(); resolve(doScrape()); }, 10_000);
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
    try {
      await fetch(LOCAL_SERVER, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(partial),
      });
    } catch (_) {}
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
    const resp = await fetch(LOCAL_SERVER, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error(`server ${resp.status}`);
    console.log(`Claude Usage: sent ${data.meters.length} meters to local server`);
  } catch (e) {
    console.warn('Claude Usage: local server unavailable, using chrome.storage', e.message);
    await chrome.storage.local.set({ claude_usage: { ...data, _buffered_at: Date.now() } });
  }

  // Record successful scrape time so the auto-scrape listener can
  // debounce repeated fires (page reload, multiple tabs, etc.).
  await chrome.storage.local.set({ _last_scrape_ts: Date.now() });
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
          const r = await fetch(LOCAL_SERVER, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(stored),
          });
          if (r.ok) {
            await chrome.storage.local.remove('claude_usage');
            console.log('Claude Usage: flushed offline data to server');
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
      const { _scrape_tabs = [] } = await chrome.storage.local.get('_scrape_tabs');
      for (const id of _scrape_tabs) {
        try { await chrome.tabs.remove(id); } catch (_) {}
      }
      if (_scrape_tabs.length) await chrome.storage.local.set({ _scrape_tabs: [] });
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
    } catch (_) {}

    if (scrapeTabId === null) {
      createdTab = await chrome.tabs.create({ url: USAGE_URL, active: false });
      scrapeTabId = createdTab.id;
      await chrome.storage.local.set({ _scrape_tabs: [scrapeTabId] });

      await new Promise((resolve, reject) => {
        // Lifted to a const so both the timeout and the listener body can
        // reference it. Named-function-expression scoping rules would otherwise
        // leave `listener` undefined inside the setTimeout closure.
        const listener = (tabId, info) => {
          if (tabId !== createdTab.id) return;
          if (info.status === 'complete') {
            chrome.tabs.onUpdated.removeListener(listener);
            clearTimeout(timeout);
            resolve();
          }
        };
        const timeout = setTimeout(() => {
          chrome.tabs.onUpdated.removeListener(listener);
          reject(new Error('tab load timeout'));
        }, 30_000);
        chrome.tabs.onUpdated.addListener(listener);
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
      await fetch(LOCAL_SERVER, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(partial),
      });
    } catch (_) {}
  } finally {
    if (tab) {
      try { await chrome.tabs.remove(tab.id); } catch (_) {}
      try { await chrome.storage.local.set({ _scrape_tabs: [] }); } catch (_) {}
    }
    _fetching = false;
  }
}

// Shared guard for both auto-scrape paths below. Checks URL, debounce,
// and in-flight state before handing off to scrapeAndPost.
async function _autoScrapeIfEligible(tabId, url) {
  // Exact match on path, ignoring query string / fragment.
  if (url.split(/[?#]/, 1)[0] !== USAGE_URL) return;
  if (_fetching) return;
  const { _scrape_tabs = [], _last_scrape_ts = 0 } =
      await chrome.storage.local.get(['_scrape_tabs', '_last_scrape_ts']);
  if (_scrape_tabs.includes(tabId)) return;
  if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
  _fetching = true;
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
  fetchUsage();
});

chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name === 'fetch-usage') await fetchUsage();
});

chrome.action.onClicked.addListener(async () => { await fetchUsage(); });
