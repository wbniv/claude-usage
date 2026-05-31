// Pure-formatting unit tests for desktop/gnome/extension.js.
//
// extension.js can't be imported under node — its top-level `import … from
// 'gi://…'` / `resource:///…` statements have no node resolver. So we EXTRACT
// the pure popup helpers (bar / formatReset / formatRows — no GJS deps in their
// bodies) by brace-matching and run them via `new Function`. This is the first
// unit coverage of the popup row formatting (the 2026-05-30 review flagged
// extension.js as having no node-loadable test harness). If a helper is renamed,
// extraction fails loudly here.

import { describe, it, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '..', 'extension.js'), 'utf8');

// Extract a top-level `function name(…) {…}` by balanced braces.
function extract(decl) {
  const start = SRC.indexOf(decl);
  if (start < 0) throw new Error(`extension.js: '${decl}' not found (renamed?)`);
  let depth = 0, started = false;
  for (let j = start; j < SRC.length; j++) {
    if (SRC[j] === '{') { depth++; started = true; }
    else if (SRC[j] === '}') { depth--; if (started && depth === 0) return SRC.slice(start, j + 1); }
  }
  throw new Error(`extension.js: unbalanced braces extracting '${decl}'`);
}

let formatRows;
before(() => {
  // bar / formatReset close over the same `new Function` body scope.
  const body = [
    extract('function bar('),
    extract('function formatReset('),
    extract('function formatRows('),
    'return formatRows;',
  ].join('\n');
  formatRows = new Function(body)();
});

const postFor = (rows, label) => rows.find(r => r.meter.label === label).post;

describe('extension.js formatRows — reset / (not started) hint', () => {
  it('shows "(not started)" for a 0% session with no reset', () => {
    const rows = formatRows([{ label: 'Current session', pct: 0, reset: null }], 10);
    assert.equal(postFor(rows, 'Current session'), '  (not started)');
  });

  it('shows the reset (not the hint) once the session is used', () => {
    const rows = formatRows([{ label: 'Current session', pct: 8, reset: 'Resets in 4 hr 45 min' }], 10);
    const post = postFor(rows, 'Current session');
    assert.match(post, /resets in/);
    assert.doesNotMatch(post, /not started/);
  });

  it('shows the weekly reset normally (always present, never the hint)', () => {
    const rows = formatRows([{ label: 'All models', pct: 25, reset: 'Resets Tue 1:00 PM' }], 10);
    assert.match(postFor(rows, 'All models'), /resets/);
  });

  it('does NOT add the hint for a non-session 0% meter (Extra usage)', () => {
    const rows = formatRows([{ label: 'Extra usage', pct: 0, reset: null }], 10);
    assert.equal(postFor(rows, 'Extra usage'), '');
  });
});
