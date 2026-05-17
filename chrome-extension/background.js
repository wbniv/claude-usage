const USAGE_URL = 'https://claude.ai/settings/usage';
const LOCAL_SERVER = 'http://127.0.0.1:7331/update';
const INTERVAL_MINUTES = 15;
const AUTO_DEBOUNCE_MS = 30_000;

let _fetching = false;

// Parse "Resets in X hr Y min" / "Resets in X min" / "Resets Tue 5:00 PM"
// into minutes-from-now. Returns null when the string doesn't match a
// known shape. Mirrors the parsing logic in gnome-extension/extension.js
// formatReset(); we run it server-side here so the cache file carries
// reset_minutes alongside the raw string for downstream consumers.
function parseResetMinutes(reset) {
  if (!reset) return null;
  let m;
  m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
  if (m) return parseInt(m[1]) * 60 + parseInt(m[2]);
  m = reset.match(/[Rr]esets? in (\d+) min/);
  if (m) return parseInt(m[1]);
  m = reset.match(/[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
  if (m) {
    const [, day, hStr, mnStr, ap] = m;
    let h = parseInt(hStr), mn = parseInt(mnStr);
    if (ap === 'PM' && h !== 12) h += 12;
    else if (ap === 'AM' && h === 12) h = 0;
    const now = new Date();
    const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
    let ahead = (wdMap[day] - now.getDay() + 7) % 7;
    if (ahead === 0) {
      const candidate = new Date(now);
      candidate.setHours(h, mn, 0, 0);
      if (candidate <= now) ahead = 7;
    }
    const target = new Date(now);
    target.setDate(now.getDate() + ahead);
    target.setHours(h, mn, 0, 0);
    return Math.floor((target - now) / 60000);
  }
  return null;
}

// Scrape claude.ai/settings/usage from the given tab (which must have
// finished loading) and POST the result to the local server. Used by
// both fetchUsage (own background tab) and the auto-scrape listener
// (any user tab on the usage page).
async function scrapeAndPost(tabId) {
  // Page-load `complete` fires before the React tree hydrates the
  // meters — give it a moment.
  await new Promise(r => setTimeout(r, 3000));

  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
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
        const pct   = Math.min(100, Math.max(0, parseInt(pctMatch[1])));
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
          const count = parseInt(countMatch[1]);
          const total = parseInt(countMatch[2]);
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
            pct   = Math.min(100, Math.max(0, parseInt(pctMatch[1])));
            reset = i >= 1 && /[Rr]esets?/.test(lines[i - 1]) ? lines[i - 1] : null;
            continue;
          }
          const balMatch = lines[i].match(/^(\$[\d,.]+)$/);
          if (balMatch && i + 1 < lines.length && /Current balance/i.test(lines[i + 1])) {
            balance = balMatch[1];
          }
        }
        if (pct !== null || spent !== null) {
          meters.push({label: 'Extra usage', pct: pct ?? 0, spent, balance, reset});
        }
      }

      return { meters, plan, _timestamp: Math.floor(Date.now() / 1000) };
    },
  });

  const data = result?.result;
  if (!data || !data.meters.length) {
    console.warn('Claude Usage: no meters extracted');
    return;
  }

  // Enrich meters with parsed reset_minutes so the server (which doesn't
  // parse strings) can track per-meter period lengths for pacing colors
  // and recompute the live tooltip countdown.
  for (const m of data.meters) {
    if (m.reset) m.reset_minutes = parseResetMinutes(m.reset);
  }

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
    await chrome.storage.local.set({ claude_usage: data });
  }

  // Record successful scrape time so the auto-scrape listener can
  // debounce repeated fires (page reload, multiple tabs, etc.).
  await chrome.storage.local.set({ _last_scrape_ts: Date.now() });
}

async function fetchUsage() {
  if (_fetching) return;
  _fetching = true;
  let tab = null;
  // Outer try/finally wraps the *entire* body so a throw from any await
  // (storage.get, tabs.query, tabs.create, scripting.executeScript, ...)
  // still resets _fetching. Inner try/catches handle graceful degradation
  // of individual operations.
  try {
    // Flush any data stored offline while the server was unavailable
    const { claude_usage: stored } = await chrome.storage.local.get('claude_usage');
    if (stored) {
      try {
        const r = await fetch(LOCAL_SERVER, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(stored),
        });
        if (r.ok) {
          await chrome.storage.local.remove('claude_usage');
          console.log('Claude Usage: flushed offline data to server');
        }
      } catch (_) {}
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

    tab = await chrome.tabs.create({ url: USAGE_URL, active: false });
    await chrome.storage.local.set({ _scrape_tabs: [tab.id] });

    await new Promise((resolve, reject) => {
      // Lifted to a const so both the timeout and the listener body can
      // reference it. Named-function-expression scoping rules would otherwise
      // leave `listener` undefined inside the setTimeout closure.
      const listener = (tabId, info) => {
        if (tabId !== tab.id) return;
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

    await scrapeAndPost(tab.id);
  } catch (err) {
    console.error('Claude Usage fetch failed:', err.message);
  } finally {
    if (tab) {
      try { await chrome.tabs.remove(tab.id); } catch (_) {}
      try { await chrome.storage.local.set({ _scrape_tabs: [] }); } catch (_) {}
    }
    _fetching = false;
  }
}

// Auto-scrape when the user opens claude.ai/settings/usage in any tab
// (popup "Open Usage Page" item, bookmark, link, address bar). Skips
// our own scrape tab and debounces against the last successful scrape
// so a page reload or a second usage tab doesn't double-fire.
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== 'complete') return;
  if (!tab.url || !tab.url.startsWith(USAGE_URL)) return;
  // Skip while toolbar/alarm scrape is running — that path includes its
  // own tabs.create which would otherwise fire this listener.
  if (_fetching) return;
  const { _scrape_tabs = [] } = await chrome.storage.local.get('_scrape_tabs');
  if (_scrape_tabs.includes(tabId)) return;
  const { _last_scrape_ts = 0 } = await chrome.storage.local.get('_last_scrape_ts');
  if (Date.now() - _last_scrape_ts < AUTO_DEBOUNCE_MS) return;
  _fetching = true;
  try {
    await scrapeAndPost(tabId);
  } catch (e) {
    console.warn('Claude Usage auto-scrape failed:', e.message);
  } finally {
    _fetching = false;
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('fetch-usage', {
    delayInMinutes: 0,
    periodInMinutes: INTERVAL_MINUTES,
  });
});

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'fetch-usage') fetchUsage();
});

chrome.action.onClicked.addListener(() => fetchUsage());
