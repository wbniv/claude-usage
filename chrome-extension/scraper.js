// Pure scraping functions extracted from the executeScript func in background.js.
// background.js inlines equivalent copies inside the injected func (which runs in
// the page context and cannot import). Keep both in sync when changing parsing logic.

export function isHydrated(textContent) {
  return /\d+%\s*used/i.test(textContent);
}

// Parse "Resets in X hr Y min" / "Resets in X min" / "Resets Tue 5:00 PM"
// into minutes-from-now. Returns null when the string doesn't match.
export function parseResetMinutes(reset) {
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
    if (h < 1 || h > 12 || mn < 0 || mn > 59) return null;
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
    return Math.min(Math.floor((target - now) / 60000), 60 * 24 * 31);
  }
  return null;
}

// Parse claude.ai/settings/usage page text into structured usage data.
// `textContent`        — document.body.textContent of the usage page
// `extraToggleChecked` — aria-checked state of the Extra usage toggle
export function doScrape(textContent, extraToggleChecked = false) {
  const lines = textContent.split('\n').map(l => l.trim()).filter(l => l.length > 0);
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
  if (extraStart >= 0 && extraToggleChecked) {
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
}
