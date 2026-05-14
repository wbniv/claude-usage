const USAGE_URL = 'https://claude.ai/settings/usage';
const LOCAL_SERVER = 'http://127.0.0.1:7331/update';
const INTERVAL_MINUTES = 15;

async function fetchUsage() {
  let tab = null;
  try {
    // Open the usage page in a non-focused background tab
    tab = await chrome.tabs.create({ url: USAGE_URL, active: false });

    // Wait for the tab to finish loading
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('tab load timeout')), 30_000);
      chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
        if (tabId !== tab.id) return;
        if (info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          clearTimeout(timeout);
          resolve();
        }
      });
    });

    // Give React time to render the usage meters
    await new Promise(r => setTimeout(r, 3000));

    // Scrape usage data from the DOM
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const body = document.body.innerText;
        const lines = body.split('\n').map(l => l.trim());
        const meters = [];
        let plan = null;

        // Find plan label (e.g. "Max (5x)", "Pro", "Free")
        for (const line of lines) {
          if (/\b(Max|Pro|Free|Team)\b/.test(line) && line.length < 80) {
            plan = line;
            break;
          }
        }

        // Find start of usage section
        const startIdx = lines.findIndex(l => l === 'Plan usage limits');

        // Scan forward: each meter is [label, Resets..., N% used] on consecutive lines
        const endPattern = /^(Additional features|Last updated:|Extra usage)/;
        for (let i = (startIdx >= 0 ? startIdx : 0) + 1; i < lines.length; i++) {
          if (endPattern.test(lines[i])) break;
          const pctMatch = lines[i].match(/^(\d+)%\s*used$/i);
          if (!pctMatch) continue;
          const pct = parseInt(pctMatch[1]);
          const reset = i >= 1 ? lines[i - 1] : null;
          const label = i >= 2 ? lines[i - 2] : null;
          // Skip if label looks like a section header or empty
          if (!label || /^(Weekly limits|Plan usage limits|Learn more)/i.test(label)) continue;
          meters.push({
            pct,
            label,
            reset: reset && /[Rr]esets?/.test(reset) ? reset : null,
          });
        }

        return { meters, plan, timestamp: Date.now() };
      },
    });

    const data = result?.result;
    if (!data || !data.meters.length) {
      console.warn('Claude Usage: no meters extracted');
      return;
    }

    // Try the local server first; fall back to chrome.storage
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

// Schedule: run immediately on install, then every INTERVAL_MINUTES
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('fetch-usage', {
    delayInMinutes: 0,
    periodInMinutes: INTERVAL_MINUTES,
  });
});

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'fetch-usage') fetchUsage();
});

// Also run when the user clicks the toolbar icon
chrome.action.onClicked.addListener(() => fetchUsage());
