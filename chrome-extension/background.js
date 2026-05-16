const USAGE_URL = 'https://claude.ai/settings/usage';
const LOCAL_SERVER = 'http://127.0.0.1:7331/update';
const INTERVAL_MINUTES = 15;

async function fetchUsage() {
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

  let tab = null;
  try {
    tab = await chrome.tabs.create({ url: USAGE_URL, active: false });

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(listener);
        reject(new Error('tab load timeout'));
      }, 30_000);
      chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
        if (tabId !== tab.id) return;
        if (info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          clearTimeout(timeout);
          resolve();
        }
      });
    });

    await new Promise(r => setTimeout(r, 3000));

    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const body = document.body.innerText;
        const lines = body.split('\n').map(l => l.trim()).filter(l => l.length > 0);
        const meters = [];
        let plan = null;

        // Plan label (e.g. "Max (5x)", "Pro", "Free")
        for (const line of lines) {
          if (/\b(Max|Pro|Free|Team)\b/.test(line) && line.length < 80) {
            plan = line;
            break;
          }
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
  } catch (err) {
    console.error('Claude Usage fetch failed:', err.message);
  } finally {
    if (tab) {
      try { await chrome.tabs.remove(tab.id); } catch (_) {}
    }
  }
}

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
