# Time-adjusted color thresholds

**Date:** 2026-05-17
**Status:** Planned

## Context

Today, meter colors (panel label, popup rows, dock-icon ring) flip based
on *raw* percentage used: green below `threshold-warning` (50), amber
from 50–80, red above `threshold-critical` (80). That's a static
reading: at 50% used you're amber regardless of whether you blew
through it in one day or it's been a steady week.

Change requested: factor in time-remaining so colors reflect
**projected end-of-period usage** at the current burn rate. Apply the
existing warning/critical thresholds to the projection, not to raw pct.
Bump default thresholds to **70 / 90** to align with the new semantics
("warn when projected to hit 70%, critical at 90%"). The adjusted
values are internal only — popup still shows raw `23%` text, only the
color changes.

- **Surfaces:** all three (panel, popup, dock ring).
- **Period length:** inferred from observed reset distances (no
  hardcoded period-by-meter table).

## Math

Per meter, per render:

```
fraction_elapsed = 1 − (reset_minutes / period_minutes)
pacing_pct       = pct / fraction_elapsed
```

`pacing_pct` is "% you'd hit by reset at your current burn rate" — on
pace = 100, half pace = 50, double pace = 200. Uncapped on purpose:
nothing visible today depends on the cap (thresholds are < 100 so any
value ≥ 100 is critical anyway), and keeping the full range preserves
the option to add a fourth tier later (e.g. "way-over-pace" highlight)
without changing the math.

Use `pacing_pct` for color decisions. Fall back to raw `pct` when:

- `reset_minutes` couldn't be parsed for this meter
- `period_minutes` isn't yet inferred (first observation of this label)
- `fraction_elapsed <= 0.01` (less than 1% into the period — pacing is
  too noisy to be useful that early)
- `pct == 0` (no signal — short-circuit before division)

Until enough history accumulates per label, behavior matches raw-pct.
After a few weeks of running, every label has an accurate period
inferred and the projection takes over.

## Period-length inference

Stored per `meter.label` in the cache JSON as a new top-level field
`_period_lengths` (object: label → minutes).

Update rule (server-side, on each POST):

```python
for m in meters:
    rm = m.get('reset_minutes')
    if rm is None: continue
    period_lengths[m['label']] = max(period_lengths.get(m['label'], 0), rm)
```

`reset_minutes` ranges from 0 (just before reset) to `period_minutes`
(just after reset). Over many observations the max converges to the
true period.

Convergence cost:

- Session meters (5 hours): converges within hours.
- Weekly meters (7 days): converges over a week or two of usage.

During convergence the inferred period is too small → fraction_elapsed
too large → pacing_pct under-stated. Acceptable transient state, no
correctness violation.

**On naming:** "pacing" not "projection" because we don't cap and we
don't pretend the number IS the end-of-period pct — it's the pacing
ratio scaled by 100. 100 = on pace, anything above = over pace.

## Files to modify

| File | Change |
|---|---|
| `chrome-extension/background.js` | Add `parseResetMinutes(resetStr)` helper; emit `reset_minutes` on each meter |
| `server/usage-server.py` | Accept optional `reset_minutes` in `_validate`; track `_period_lengths`; persist in cache JSON |
| `gnome-extension/extension.js` | Add `pacingPct(meter, periodLens)`; use adjusted pct for panel + popup color decisions |
| `server/generate-icon.py` | Read `_period_lengths`; new `pacing_pct`; pass adjusted pct to `ring_color` |
| `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml` | `threshold-warning` 50 → 70, `threshold-critical` 80 → 90 |
| `MANUAL.md` | Update threshold defaults; add paragraph on pacing semantics + the per-meter period inference behavior |
| `PRIVACY.md` | Note the new `_period_lengths` field in the cache JSON (no new personal data — just minutes-per-label numbers) |
| `packaging/control`, `chrome-extension/manifest.json` | Version 0.9.10 → 0.10.0 |

## Implementation

### `chrome-extension/background.js`

New top-level helper (ports the parser in
`gnome-extension/extension.js:15-45` `formatReset()`):

```javascript
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
```

After the scrape returns `data` (post-`scripting.executeScript`, before
the POST), enrich each meter:

```javascript
for (const m of data.meters) {
  if (m.reset) m.reset_minutes = parseResetMinutes(m.reset);
}
```

### `server/usage-server.py`

Add to `_validate` alongside the existing field checks:

```python
rm = m.get('reset_minutes')
if rm is not None and (isinstance(rm, bool) or not isinstance(rm, int) or rm < 0):
    return f"meters[{i}].reset_minutes must be a non-negative integer or null"
```

In the POST handler, after validation and before the atomic write:

```python
# Accumulate period lengths across writes — the max reset_minutes ever
# observed per label converges to the true period.
period_lengths = {}
if OUTPUT.exists():
    try:
        prev = json.loads(OUTPUT.read_text())
        period_lengths = prev.get('_period_lengths', {})
    except Exception:
        pass
for meter in body.get('meters', []):
    rm = meter.get('reset_minutes')
    label = meter.get('label')
    if rm is None or not label:
        continue
    period_lengths[label] = max(period_lengths.get(label, 0), rm)
body['_period_lengths'] = period_lengths
```

### `gnome-extension/extension.js`

New top-level helper alongside `bar` and `formatReset`:

```javascript
function pacingPct(meter, periodLens) {
    const pct = meter.pct;
    if (typeof pct !== 'number' || pct === 0) return pct ?? 0;
    const rm = meter.reset_minutes;
    const period = periodLens?.[meter.label];
    if (rm == null || !period) return pct;
    const fraction = 1 - rm / period;
    if (fraction <= 0.01) return pct;
    return pct / fraction;
}
```

In `_updateDisplay()`:

- Pull `_period_lengths` once:
  `const periodLens = d._period_lengths || {};`
- Panel label color: keep `pct = primary?.pct ...` for the displayed
  `${pct}%` text, but feed `pacingPct(primary, periodLens)` into the
  `pct >= tCrit ? panelCrit : ...` decision.
- Popup row color: replace `pctColor(mpct)` with
  `pctColor(pacingPct(row.meter, periodLens))`.

`formatRows` (lines 52-84) is untouched — it produces the raw `%` text
and the bar from raw pct.

### `server/generate-icon.py`

In `main()`, after parsing the cache JSON:

```python
period_lens = data.get('_period_lengths', {})
```

New helper near `ring_color`:

```python
def pacing_pct(meter, period_lens):
    pct = meter.get('pct')
    if not isinstance(pct, int) or pct == 0:
        return pct or 0
    rm = meter.get('reset_minutes')
    period = period_lens.get(meter.get('label'))
    if rm is None or not period:
        return pct
    fraction = 1 - rm / period
    if fraction <= 0.01:
        return pct
    return pct / fraction
```

Switch `find` to also return the meter object so `pacing_pct` can
read `reset_minutes`/`label`:

```python
find_meter = lambda kw: next(
    (m for m in meters if kw in (m.get('label') or '').lower()), None)
all_m    = find_meter('all')
sonnet_m = find_meter('sonnet')
all_pct    = pacing_pct(all_m, period_lens) if all_m else 0
sonnet_pct = pacing_pct(sonnet_m, period_lens) if sonnet_m else 0
```

`ring_color` already takes `pct`; no signature change.

### Schema defaults

`gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml`:

- `threshold-warning`: `<default>50</default>` → `<default>70</default>`
- `threshold-critical`: `<default>80</default>` → `<default>90</default>`

### `MANUAL.md`

Two changes:

1. Settings table rows for `threshold-warning` / `threshold-critical`:
   default `50` → `70`, `80` → `90`. Description update:
   `% at which color flips to warning` → `% projected at reset at
   which color flips to warning`.

2. Short paragraph (above the settings table or under "Day-to-day
   use") explaining the pacing semantics: "Colors reflect your current
   *pacing*, not raw % used. The number that drives color is `pct ÷
   fraction-of-period-elapsed` — so 50% used halfway through a week is
   "on pace for 100%" and shows red, while 80% used near the end of a
   week is "on pace for ~90%" and shows amber. Per-meter periods are
   inferred over time from observed reset distances; until enough
   history accumulates, colors fall back to raw % used."

### `PRIVACY.md`

The cache file gets a new top-level field `_period_lengths` — an
object mapping meter labels (e.g. `"All models"`) to integers
(maximum minutes-to-reset ever observed). No new personal data;
it's a tiny inference artifact. Update the storage list under
**What is stored** to reflect this:

> - `~/.cache/claude-usage/usage.json` — usage data + inferred
>   per-meter period lengths, updated every 15 minutes

## Verification

1. **Syntax sanity**
    - `node --check chrome-extension/background.js`
    - `node --check gnome-extension/extension.js`
    - `python3 -c 'import ast; ast.parse(open("server/usage-server.py").read())'`
    - `python3 -c 'import ast; ast.parse(open("server/generate-icon.py").read())'`

2. **`pacingPct` unit verification** via node REPL — match the math
   in this plan:

    ```javascript
    // [pct, reset_min, period_min, expected]
    const tests = [
      [25, 60,  120, 50],   // 50% elapsed, on pace for 50% → pacing 50
      [50, 60,  120, 100],  // 50% elapsed, on pace for 100% → pacing 100
      [80, 12,  120, 88.89],// 90% elapsed → pacing 88.9
      [20, 108, 120, 200],  // 10% elapsed → pacing 200 (uncapped, was 100 pre-revision)
      [5,  0,   120, 5],    // fraction 1 → raw
      [5,  120, 120, 5],    // fraction 0 → fallback raw (epsilon guard)
      [0,  60,  120, 0],    // pct 0 → 0
    ];
    ```

3. **Cache schema check** — after one POST cycle, confirm
   `~/.cache/claude-usage/usage.json` contains `_period_lengths`:

    ```bash
    jq . ~/.cache/claude-usage/usage.json
    ```

4. **Cold-start fallback** — wipe the cache file, observe one POST:
   colors should match raw-pct behavior (no period inferred yet, or
   `period == reset_minutes` so `fraction_elapsed = 0` triggers the
   guard).

5. **`.deb` install** — `task test-deb-fast` confirms version bump
   doesn't break the install path; doesn't exercise the color math.

6. **Live extension** — reload the Chrome extension at 0.10.0, restart
   the usage-server. To visually confirm color logic without disrupting
   the session, render a PIL mockup using live cache data + GSettings
   (per project convention — extension.js changes need gnome-shell
   reload which is disruptive on Wayland).

## Post-implementation: tooltip refresh + countdown live-recompute

(Captured here because the tooltip refresh built on the `reset_minutes`
field this plan introduced — they share the same scrape→cache→consumer
data path.)

Shipped as `feat(tooltip): 60 s dock-launcher tooltip refresh` at
0.10.1: `server/tooltip.py` (new) hosts `parse_reset` / `format_tooltip`
/ `update_desktop` shared between `generate-icon.py` (15 min full
regen) and a new 60 s daemon thread in `usage-server.py` (in-process
tooltip rewrite, no subprocess). Verified end-to-end: after restart
the `.desktop` mtime updated exactly 60 s later.

**Post-deploy discovery + fix (0.10.2):** the 60 s tick updated the
file mtime but the **countdown digits didn't change** — `parse_reset`
for the `"Resets in X hr Y min"` form just re-parsed the literal
numbers from the frozen scrape string, producing the same output
forever. The day/time form (`"Resets Tue 5 PM"`) ticked down correctly
because it uses `datetime.now()` live.

Fix: extend `parse_reset(reset, reset_minutes=None, anchor_ts=None)`.
When both kwargs are supplied (and the form is countdown-style),
recompute as `reset_minutes - floor((now - anchor_ts) / 60)`. Floor-
divide so the countdown only decrements after a full minute passes
(scrape-time + 0 s shows the scraped value, not value-1 from FP drift).
Threaded `anchor_ts` through `format_tooltip(meters, anchor_ts=None)`
and `update_desktop(meters, icon_path=None, scrape_ts=None)`. Callers
in `usage-server.py` (tick) and `generate-icon.py` (15 min regen)
both pass `data.get('_timestamp')`.

This is why this fix belongs in the same plan as
`_period_lengths`/`reset_minutes`: it reuses `reset_minutes` (added
here for pacing) as the snapshot value that the live-countdown
recompute subtracts from. Without `reset_minutes` in the cache the
tooltip would have had to re-parse the string each tick — same bug.



`MANUAL.md` and `PRIVACY.md` updates are part of the implementation
commit, not a separate pass — see the corresponding sections above.
After verification passes:

1. **Flip plan status.** `**Status:** Planned` → `Implemented` in the
   header.

2. **Paste verification evidence.** Under each numbered step in the
   Verification section, add a code block with the raw command
   output and a `PASS` / `FAIL` line (per project convention — plans
   are contract + evidence; keep step text verbatim, don't summarize).

3. **Re-preview MANUAL.md.** `task md -- MANUAL.md` after the
   in-implementation MANUAL changes land, and tighten the new
   pacing paragraph if it reads awkwardly next to the surrounding
   sections.
