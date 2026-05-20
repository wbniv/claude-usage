# Pacing visualization — tick mark + over-pace highlight

Date: 2026-05-20
Status: planning

## Goal

Make pacing (burn rate vs time-elapsed) visible spatially on both surfaces, not
just numerically encoded in row/label color. Combines option-1 (tick mark) for
under-pace headroom display with option-3 (two-tone fill) for over-pace
highlighting.

## Visual rules

For a bar of width `N` representing `pct` of a period, given
`elapsed_frac = (period − reset_minutes) / period`:

- `fill = round(pct × N / 100)`
- `elapsed_pos = round(elapsed_frac × N)`

Three cases:

1. **Under-pace** (`fill < elapsed_pos`):
   `█ × fill`, `░` to `elapsed_pos−1`, `┊` at `elapsed_pos`, `░` to end.
   Tick marks "where you'd be at sustainable burn".
   Example (pct 9, elapsed 43 %, N 10): `█░░░┊░░░░░`

2. **On-pace** (`fill == elapsed_pos`):
   `█ × fill`, `░` to end. No tick needed (boundary is the fill edge).
   Example (pct 50, elapsed 50 %, N 10): `█████░░░░░`

3. **Over-pace** (`fill > elapsed_pos`):
   `█ × elapsed_pos` in **normal** tier color,
   `█ × (fill − elapsed_pos)` in **warn/crit** tier color,
   `░` to end. No tick — boundary visible via color change.
   Example (pct 80, elapsed 50 %, N 10): `█████` + `███` (hot) + `░░`

Floor: when `elapsed < max(15, period × 0.05)`, suppress tick & two-tone
(matches the existing `pacing_pct` floor — early-period noise is hidden).

## Dock-icon equivalent

Same grammar, applied to each colored ring:

- **Under-pace:** arc 0 → `fill_angle` + thin radial tick at `elapsed_angle`.
- **On-pace:** arc 0 → `fill_angle` (which equals `elapsed_angle`).
- **Over-pace:** arc 0 → `elapsed_angle` in normal color, then
  `elapsed_angle` → `fill_angle` in warn/crit color.

## Surfaces

1. `scripts/popup-preview.py` — HTML+CSS, per-segment `<span>` (prototype first;
   fast iteration without Wayland logout cycle).
2. `gnome-extension/extension.js` — Pango markup on PopupMenuItem labels (the
   row text uses `clutter_text.set_markup`).
3. `server/generate-icon.py` — Cairo, second arc segment + radial tick line.

## Order of work

1. Prototype in `popup-preview.py` and eyeball at multiple pacing states.
2. Port bar logic to `extension.js` (Pango markup), keeping `formatRows` pure
   so it can be unit-tested independently.
3. Add the same tier-aware arc + tick to `generate-icon.py`.
4. Tests for bar-segment composition (under/on/over) — pure-function rendering
   only, no GNOME runtime.

## Verification

1. `python3 scripts/popup-preview.py` → browser shows three meters with:
   - All Models (under-pace, weekly): tick visible in the empty zone.
   - Sonnet (under-pace, tiny fill): tick visible toward the right.
   - Session (over-pace, ≫ 50 %): two-tone fill, no tick.

2. Pure-function bar composition for canonical pacing states (width=10):

   ```text
   under-pace (pct=9, e=43%)       bar=█░░░┊░░░░░  role=N...T.....
   on-pace    (pct=50, e=50%)      bar=█████┊░░░░  role=NNNNNT....
   over-pace  (pct=80, e=50%)      bar=████████░░  role=NNNNNHHH..
   over-pace  (pct=100, e=50%)     bar=██████████  role=NNNNNHHHHH
   floor      (pct=50, e=None)     bar=█████░░░░░  role=NNNNN.....
   zero       (pct=0,  e=30%)      bar=░░░┊░░░░░░  role=...T......
   at-100%    (pct=100,e=100%)     bar=██████████  role=NNNNNNNNNN
   ```

   N=on_pace █, H=over_pace █ (tier-colored), T=tick ┊, .=empty ░ — PASS

3. After porting to `extension.js`, install the rebuilt `.deb`; click dock
   icon → real popup matches preview output character-for-character.
4. Dock icon screenshot shows the two-tone over-pace arc on the outer ring.
5. `task test` passes (`lint-pacing-parity` catches drift; new bar-rendering
   tests added under `server/tests/test_pacing.py` or a sibling file).

## Non-goals

- Reworking the panel label colors — those still flip on `pacing_pct` tier as
  today.
- Adding a separate reference bar / outer dock ring (the user's option 2) —
  the tick achieves the same information without the extra row/ring.
- Changing thresholds — `threshold-warning` / `threshold-critical` still drive
  the warn/crit tier colors used for the over-pace segment.
