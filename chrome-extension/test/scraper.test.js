import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { isHydrated, parseResetMinutes, doScrape } from '../scraper.js';

// ── isHydrated ────────────────────────────────────────────────────────────────

describe('isHydrated', () => {
  it('returns true when text contains "N% used"', () => {
    assert.equal(isHydrated('Claude.ai All models\n85% used'), true);
  });
  it('returns true for 0% used', () => {
    assert.equal(isHydrated('0% used'), true);
  });
  it('returns false for empty string', () => {
    assert.equal(isHydrated(''), false);
  });
  it('returns false when "used" has no leading digits', () => {
    assert.equal(isHydrated('used'), false);
  });
  it('returns false for unrelated page content', () => {
    assert.equal(isHydrated('Loading…'), false);
  });
});

// ── parseResetMinutes ─────────────────────────────────────────────────────────

describe('parseResetMinutes', () => {
  it('returns null for null', () => assert.equal(parseResetMinutes(null), null));
  it('returns null for empty string', () => assert.equal(parseResetMinutes(''), null));
  it('returns null for unrecognised string', () => assert.equal(parseResetMinutes('Tomorrow'), null));

  it('"Resets in 2 hr 15 min" → 135', () => {
    assert.equal(parseResetMinutes('Resets in 2 hr 15 min'), 135);
  });
  it('"resets in 2 hr 0 min" → 120 (case-insensitive)', () => {
    assert.equal(parseResetMinutes('resets in 2 hr 0 min'), 120);
  });
  it('"Resets in 30 min" → 30', () => {
    assert.equal(parseResetMinutes('Resets in 30 min'), 30);
  });
  it('"resets in 1 min" → 1 (case-insensitive)', () => {
    assert.equal(parseResetMinutes('resets in 1 min'), 1);
  });
  it('caps an over-long "Resets in 99999 hr 0 min" at 31 days (BASE-6)', () => {
    assert.equal(parseResetMinutes('Resets in 99999 hr 0 min'), 60 * 24 * 31);
  });
  it('caps an over-long "Resets in 99999 min" at 31 days (BASE-6)', () => {
    assert.equal(parseResetMinutes('Resets in 99999 min'), 60 * 24 * 31);
  });

  // Weekday form — result is time-dependent; verify it's in [1, 10080] minutes
  const WEEK_MINS = 7 * 24 * 60;
  for (const str of [
    'Resets Tue 3:00 PM',
    'Resets Mon 11:30 AM',
    'Resets Fri 8:00 PM',
  ]) {
    it(`"${str}" → positive integer ≤ 1 week`, () => {
      const result = parseResetMinutes(str);
      assert.ok(typeof result === 'number' && Number.isInteger(result),
        `expected integer, got ${result}`);
      assert.ok(result >= 1 && result <= WEEK_MINS,
        `expected 1–${WEEK_MINS}, got ${result}`);
    });
  }

  // 12:00 PM = noon (no +12); 12:00 AM = midnight (h→0)
  it('"Resets Tue 12:00 PM" → positive integer (noon, no +12)', () => {
    const result = parseResetMinutes('Resets Tue 12:00 PM');
    assert.ok(result !== null && result >= 1 && result <= WEEK_MINS);
  });
  it('"Resets Tue 12:00 AM" → positive integer (midnight, h=0)', () => {
    const result = parseResetMinutes('Resets Tue 12:00 AM');
    assert.ok(result !== null && result >= 1 && result <= WEEK_MINS);
  });

  // 31-day cap — any weekday result must be ≤ 60 * 24 * 31
  const MONTH_MINS = 60 * 24 * 31;
  it('weekday result is always ≤ 31-day cap', () => {
    for (const str of ['Resets Mon 12:00 AM', 'Resets Sun 11:59 PM', 'Resets Sat 6:00 PM']) {
      const result = parseResetMinutes(str);
      assert.ok(result !== null && result <= MONTH_MINS,
        `expected ≤ ${MONTH_MINS}, got ${result}`);
    }
  });

  // Invalid ranges
  it('"Resets Tue 13:00 PM" → null (hour > 12)', () => {
    assert.equal(parseResetMinutes('Resets Tue 13:00 PM'), null);
  });
  it('"Resets Tue 0:00 PM" → null (hour < 1)', () => {
    assert.equal(parseResetMinutes('Resets Tue 0:00 PM'), null);
  });
  it('"Resets Tue 5:99 PM" → null (minute > 59)', () => {
    assert.equal(parseResetMinutes('Resets Tue 5:99 PM'), null);
  });
});

// ── doScrape helpers ──────────────────────────────────────────────────────────

// Build a minimal usage-page text fixture from parts.
function makePageText({ plan = '', section1 = [], section2 = [], section3 = null } = {}) {
  const lines = [];
  if (plan) lines.push(plan);
  if (section1.length) {
    lines.push('Plan usage limits');
    lines.push(...section1);
  }
  if (section2.length) {
    lines.push('Additional features');
    lines.push(...section2);
  }
  if (section3 !== null) {
    lines.push('Extra usage');
    lines.push(...section3);
  }
  lines.push('Last updated: just now');
  return lines.join('\n');
}

// ── doScrape — plan detection ─────────────────────────────────────────────────

describe('doScrape — plan detection', () => {
  it('detects "Pro"', () => {
    const { plan } = doScrape(makePageText({ plan: 'Pro' }));
    assert.equal(plan, 'Pro');
  });
  it('detects "Max (5x)"', () => {
    const { plan } = doScrape(makePageText({ plan: 'Max (5x)' }));
    assert.equal(plan, 'Max (5x)');
  });
  it('detects "Free"', () => {
    const { plan } = doScrape(makePageText({ plan: 'Free' }));
    assert.equal(plan, 'Free');
  });
  it('detects "Team"', () => {
    const { plan } = doScrape(makePageText({ plan: 'Team' }));
    assert.equal(plan, 'Team');
  });
  it('does not capture "Pro tip: upgrade now" (too long / no exact match)', () => {
    const { plan } = doScrape('Pro tip: upgrade now\nPlan usage limits\n');
    assert.equal(plan, null);
  });
  it('returns null when no plan line present', () => {
    const { plan } = doScrape(makePageText({}));
    assert.equal(plan, null);
  });
});

// ── doScrape — Section 1 ─────────────────────────────────────────────────────

describe('doScrape — Section 1 (Plan usage limits)', () => {
  it('extracts a single meter with reset', () => {
    const text = makePageText({
      plan: 'Pro',
      section1: [
        'Claude.ai All models',
        'Resets in 2 hr 30 min',
        '85% used',
      ],
    });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 1);
    assert.equal(meters[0].label, 'Claude.ai All models');
    assert.equal(meters[0].pct, 85);
    assert.equal(meters[0].reset, 'Resets in 2 hr 30 min');
  });

  it('extracts two meters', () => {
    const text = makePageText({
      section1: [
        'Claude.ai All models',
        'Resets in 1 hr 0 min',
        '60% used',
        'Claude.ai Sonnet',
        'Resets in 1 hr 0 min',
        '40% used',
      ],
    });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 2);
    assert.equal(meters[0].label, 'Claude.ai All models');
    assert.equal(meters[1].label, 'Claude.ai Sonnet');
  });

  it('clamps pct > 100 to 100', () => {
    const text = makePageText({
      section1: ['Claude.ai All models', 'Resets in 1 hr 0 min', '150% used'],
    });
    const { meters } = doScrape(text);
    assert.equal(meters[0].pct, 100);
  });

  it('clamps pct < 0 to 0 (defensive)', () => {
    // parseInt on negative patterns would still be caught by the regex,
    // but confirm clamp works if it somehow slips through.
    const text = 'Plan usage limits\nMy meter\nResets in 1 min\n0% used\n';
    const { meters } = doScrape(text);
    assert.ok(meters[0].pct >= 0);
  });

  it('sets reset to null when no reset line precedes pct', () => {
    // Need label at i-2 and non-reset at i-1 so the meter isn't filtered.
    const text = makePageText({
      section1: ['Claude.ai All models', 'Claude.ai Sonnet', '50% used'],
    });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 1);
    assert.equal(meters[0].reset, null);
  });

  it('filters out "Weekly limits" label', () => {
    const text = makePageText({
      section1: ['Weekly limits', 'Resets in 1 hr', '90% used'],
    });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 0);
  });

  it('filters out "Learn more" label', () => {
    const text = makePageText({
      section1: ['Learn more', 'Resets in 1 hr', '90% used'],
    });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 0);
  });

  it('returns empty meters for empty page', () => {
    const { meters, plan } = doScrape('');
    assert.equal(meters.length, 0);
    assert.equal(plan, null);
  });
});

// ── doScrape — Section 2 ─────────────────────────────────────────────────────

describe('doScrape — Section 2 (Additional features)', () => {
  it('extracts count/total ratio correctly', () => {
    const text = makePageText({
      section2: ['Projects', 'Learn more', '100 / 200'],
    });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 1);
    assert.equal(meters[0].count, 100);
    assert.equal(meters[0].total, 200);
    assert.equal(meters[0].pct, 50);
    assert.equal(meters[0].reset, null);
  });

  it('sets pct to 0 when total is 0 (no divide-by-zero)', () => {
    const text = makePageText({
      section2: ['Projects', 'Learn more', '0 / 0'],
    });
    const { meters } = doScrape(text);
    assert.equal(meters[0].pct, 0);
  });

  it('skips section entirely when "Additional features" header absent', () => {
    const text = makePageText({ section1: ['My meter', 'Resets in 1 min', '10% used'] });
    const { meters } = doScrape(text);
    assert.equal(meters.length, 1);
    assert.equal(meters[0].label, 'My meter');
  });

  it('filters out "Additional features" as label', () => {
    // If the count row appears at index < 2 from the section header it has no
    // usable label — the label would resolve to "Additional features" and get filtered.
    const text = 'Additional features\n100 / 200\nLast updated: now\n';
    const { meters } = doScrape(text);
    assert.equal(meters.length, 0);
  });
});

// ── doScrape — Section 3 ─────────────────────────────────────────────────────

describe('doScrape — Section 3 (Extra usage)', () => {
  it('includes Extra usage meter when toggle is on', () => {
    const text = makePageText({
      section3: [
        '$10.50 spent',
        'Resets in 5 min',
        '30% used',
        '$89.50',
        'Current balance',
      ],
    });
    const { meters } = doScrape(text, true);
    const extra = meters.find(m => m.label === 'Extra usage');
    assert.ok(extra, 'Extra usage meter should be present');
    assert.equal(extra.pct, 30);
    assert.equal(extra.spent, '$10.50');
    assert.equal(extra.balance, '$89.50');
    assert.equal(extra.reset, 'Resets in 5 min');
  });

  it('skips Extra usage section when toggle is off (default)', () => {
    const text = makePageText({
      section3: ['$10.50 spent', '30% used'],
    });
    const { meters } = doScrape(text, false);
    assert.ok(!meters.find(m => m.label === 'Extra usage'));
  });

  it('skips Extra usage section when toggle arg is omitted', () => {
    const text = makePageText({ section3: ['30% used'] });
    const { meters } = doScrape(text);
    assert.ok(!meters.find(m => m.label === 'Extra usage'));
  });

  it('omits Extra usage meter when neither pct nor spent is present', () => {
    const text = makePageText({ section3: ['Some other line'] });
    const { meters } = doScrape(text, true);
    assert.ok(!meters.find(m => m.label === 'Extra usage'));
  });

  it('includes meter when only spent is present (pct defaults to 0)', () => {
    const text = makePageText({ section3: ['$5.00 spent'] });
    const { meters } = doScrape(text, true);
    const extra = meters.find(m => m.label === 'Extra usage');
    assert.ok(extra);
    assert.equal(extra.pct, 0);
    assert.equal(extra.spent, '$5.00');
  });

  it('stops parsing at "Last updated:" boundary', () => {
    const text = [
      'Extra usage',
      '$5.00 spent',
      'Last updated: just now',
      '99% used',  // should NOT be picked up — past the boundary
    ].join('\n');
    const { meters } = doScrape(text, true);
    const extra = meters.find(m => m.label === 'Extra usage');
    assert.ok(extra);
    assert.equal(extra.pct, 0);  // 99% was after boundary; pct still null → defaults to 0
  });
});


// ── doScrape — _parse_failure signal (PF-2, pass-19) ──────────────────────────
//
// PF-1 (pass-18) tightened the predicate from `/\d+\s*%/` to
// `/\d+\s*%\s*used/i`. Without these tests, a regression that loosens or
// breaks the predicate lands green. The signal is the panel-grey
// troubleshooting hint surfaced by claude-usage-status.

describe('doScrape — _parse_failure', () => {
  it('emits locale_or_layout when meters is empty but page has "% used" text', () => {
    // Page text has a usage-shaped meter but doesn't match the English
    // section anchors (`Plan usage limits` etc.) — simulating a locale
    // where Anthropic has translated the section headers.
    const text = [
      'Some translated header',
      '85% used',
      'Some translated footer',
    ].join('\n');
    const { meters, _parse_failure } = doScrape(text);
    assert.equal(meters.length, 0);
    assert.equal(_parse_failure, 'locale_or_layout');
  });

  it('matches the spaced form "5 % used"', () => {
    const text = 'Foo\n5 % used\nBar';
    const { _parse_failure } = doScrape(text);
    assert.equal(_parse_failure, 'locale_or_layout');
  });

  it('matches case-insensitive "Used"', () => {
    const text = 'Foo\n42% Used\nBar';
    const { _parse_failure } = doScrape(text);
    assert.equal(_parse_failure, 'locale_or_layout');
  });

  it('does NOT fire on marketing copy with "% off" (no "used")', () => {
    const text = 'Save 20% off our annual plans';
    const { meters, _parse_failure } = doScrape(text);
    assert.equal(meters.length, 0);
    assert.equal(_parse_failure, undefined,
      '_parse_failure should be omitted, not set, when only marketing % is present');
  });

  it('does NOT fire when meters are present (regardless of other % text)', () => {
    const text = makePageText({
      plan: 'Pro',
      section1: [
        'Claude.ai Current session',
        'Resets in 1 hr 0 min',
        '50% used',
      ],
      section3: ['Save 50% off this week'],  // marketing % present too
    });
    const { meters, _parse_failure } = doScrape(text, true);
    assert.ok(meters.length > 0);
    assert.equal(_parse_failure, undefined);
  });
});
