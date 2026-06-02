// Tests for usage-api.js — the claude.ai usage-API → meters[] mapping that
// replaces DOM scraping. Loads the classic script into a vm context (same
// technique as firefox-compat.test.js) and exercises its global functions.

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const USAGE_API = join(__dirname, '..', 'usage-api.js');

// Returns a mapper. Cross-realm objects built in the vm carry the vm's
// prototypes, so JSON-roundtrip into this realm for deepEqual — which also
// mirrors the JSON.stringify the POST does anyway.
function load() {
  const ctx = { Date, Math, Number, String, isFinite, isNaN };
  vm.createContext(ctx);
  vm.runInContext(readFileSync(USAGE_API, 'utf8'), ctx, { filename: 'usage-api.js' });
  return (api, nowMs) => JSON.parse(JSON.stringify(ctx.mapUsageResponse(api, nowMs)));
}

// The real /api/organizations/{org}/usage response captured 2026-06-02.
const NOW = Date.parse('2026-06-02T09:08:49Z');
const SAMPLE = {
  five_hour:        { utilization: 50.0, resets_at: '2026-06-02T11:50:00.966954+00:00' },
  seven_day:        { utilization: 15.0, resets_at: '2026-06-03T15:59:59.966973+00:00' },
  seven_day_oauth_apps: null,
  seven_day_opus:   null,
  seven_day_sonnet: { utilization: 0.0, resets_at: '2026-06-03T16:00:00.966980+00:00' },
  seven_day_cowork: null,
  tangelo:          null,
  extra_usage:      { is_enabled: false, monthly_limit: null, used_credits: null, utilization: null },
};

describe('usage-api — mapUsageResponse', () => {
  it('maps the real /usage sample to the expected meters[]', () => {
    const map = load();
    const meters = map(SAMPLE, NOW);

    // opus is null → skipped; extra_usage is disabled → skipped.
    assert.equal(meters.length, 3);
    const by = Object.fromEntries(meters.map(m => [m.label, m]));

    // five_hour → "Current session", 50%, ~2h41m (countdown form, TZ-independent).
    assert.deepEqual(by['Current session'], {
      pct: 50, label: 'Current session', reset_minutes: 161, reset: 'Resets in 2 hr 41 min',
    });

    // seven_day → "All models", 15%, ~30h51m → day/time form (assert format, not TZ).
    assert.equal(by['All models'].pct, 15);
    assert.equal(by['All models'].reset_minutes, 1851);
    assert.match(by['All models'].reset, /^Resets (Sun|Mon|Tue|Wed|Thu|Fri|Sat) \d{1,2}:\d{2} (AM|PM)$/);

    // seven_day_sonnet → "Sonnet only", 0% (consumers hide it themselves).
    assert.equal(by['Sonnet only'].pct, 0);
    assert.equal(by['Sonnet only'].label, 'Sonnet only');
    assert.ok(by['Sonnet only'].reset_minutes >= 1851);
  });

  it('produces server-valid meter fields (pct int 0-100, reset_minutes 0-44640)', () => {
    const map = load();
    for (const m of map(SAMPLE, NOW)) {
      assert.ok(Number.isInteger(m.pct) && m.pct >= 0 && m.pct <= 100, `pct ${m.pct}`);
      assert.ok(typeof m.label === 'string' && m.label.length > 0 && m.label.length <= 128);
      assert.ok(m.reset_minutes == null || (Number.isInteger(m.reset_minutes) && m.reset_minutes >= 0 && m.reset_minutes <= 44640));
      assert.ok(m.reset == null || (typeof m.reset === 'string' && m.reset.length <= 128));
    }
  });

  it('rounds utilization and clamps to [0,100]', () => {
    const map = load();
    const m = map({
      five_hour: { utilization: 49.6, resets_at: '2026-06-02T09:38:49Z' },
      seven_day: { utilization: 0.4,  resets_at: '2026-06-02T10:08:49Z' },
      seven_day_opus: { utilization: 250, resets_at: '2026-06-02T09:38:49Z' },
    }, NOW);
    const by = Object.fromEntries(m.map(x => [x.label, x.pct]));
    assert.equal(by['Current session'], 50);  // 49.6 → 50
    assert.equal(by['All models'], 0);         // 0.4 → 0
    assert.equal(by['Opus'], 100);             // 250 → clamp 100
  });

  it('uses the "M min" form under an hour and clamps far resets to 31 days', () => {
    const map = load();
    const [near] = map({ five_hour: { utilization: 10, resets_at: '2026-06-02T09:45:49Z' } }, NOW);  // 37 min
    assert.equal(near.reset_minutes, 37);
    assert.equal(near.reset, 'Resets in 37 min');

    const [far] = map({ five_hour: { utilization: 10, resets_at: '2099-01-01T00:00:00Z' } }, NOW);
    assert.equal(far.reset_minutes, 44640);  // capped at 31 days
  });

  it('maps extra_usage only when enabled', () => {
    const map = load();
    assert.equal(map({ extra_usage: { is_enabled: false } }, NOW).length, 0);
    const [ex] = map({ extra_usage: { is_enabled: true, utilization: 30, used_credits: 5, monthly_limit: 20 } }, NOW);
    assert.equal(ex.label, 'Extra usage');
    assert.equal(ex.pct, 30);
    assert.equal(ex.spent, '$5');
    assert.equal(ex.balance, '$20');
  });

  it('returns [] for a bad/empty response (treated as a failed scrape)', () => {
    const map = load();
    assert.deepEqual(map(null, NOW), []);
    assert.deepEqual(map('nope', NOW), []);
    assert.deepEqual(map({}, NOW), []);
    assert.deepEqual(map({ five_hour: null, seven_day: { utilization: null } }, NOW), []);
  });
});
