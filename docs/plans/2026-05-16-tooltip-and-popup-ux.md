# Tooltip & Popup UX Refinements — 2026-05-16

## Goals

1. **Dock tooltip**: single-line format with smart time display
2. **Panel popup**: apply same time formatting to reset strings
3. **Sonnet visibility**: hide when pct = 0 in both dock tooltip and popup
4. **Time format**: 24-hour everywhere; locale-aware if determinable

---

## Dock tooltip format

Single line, pipe-separated:

```
current xx% ⏱h:mm | all yy% Tue 13:00 | sonnet zz% ⏱h:mm
```

Rules:
- Show `current` (session), `all` (all models), `sonnet` (sonnet only)
- Omit `sonnet` entirely when its pct = 0
- Time display (see Time Format section below)

## Panel popup reset format

Each row ends with the reset info. Old format was the raw string from the page
(`Resets Tue 1:00 PM`, `Resets in 47 min`). New format:

```
Resets ⏱0:30       ← countdown when < 24 h remaining
Resets Tue 13:00   ← day + 24-hour time when >= 24 h remaining
```

## Time format rules

Given a reset string from the page:

| Source string | Remaining | Display |
|---|---|---|
| `Resets in X hr Y min` | < 24 h (always) | `⏱X:YY` |
| `Resets in X min` | < 24 h (always) | `⏱0:XX` |
| `Resets Day H:MM AM/PM` | < 24 h | `⏱H:MM` |
| `Resets Day H:MM AM/PM` | ≥ 24 h | `Day HH:MM` (24 h) |

24-hour format is used throughout. If locale detection is added later, prefer
`locale.nl_langinfo(locale.T_FMT)` in Python / `Intl.DateTimeFormat` with
`hour12: false` in JS as the toggle point.

## Implementation

### `server/generate-icon.py`
- `parse_reset(reset)` → `(is_countdown: bool, display: str) | None`
  - countdown: `⏱h:mm` prefix added by caller
  - day: `Day HH:MM` (24 h, zero-padded hour)
- `format_tooltip(meters)` builds single-line string

### `gnome-extension/extension.js`
- `formatReset(reset)` — JS equivalent of `parse_reset`, returns formatted string
  with `Resets` prefix, e.g. `Resets ⏱0:47` or `Resets Tue 13:00`
- Used in `formatRows()` replacing raw `m.reset` in `col4`
- `visibleMeters` filter in `_updateDisplay` strips sonnet when pct = 0

## Verification

1. Hover dock icon → tooltip shows single-line with correct time format — PASS (confirmed by user)
2. Session reset < 24 h → shows `⏱h:mm` — PASS
3. Weekly reset ≥ 24 h → shows `Day HH:MM` in 24-hour format — PASS
4. Sonnet pct = 0 → row absent from popup and absent from dock tooltip — PASS
5. Sonnet pct > 0 → row present in popup and in dock tooltip — PASS
6. Open panel popup → reset strings show `Resets ⏱h:mm` or `Resets Day HH:MM` — PASS (requires logout/login to reload ES module)

## Addendum — dock icon ring changes (2026-05-16)

Additional fixes applied after initial implementation:

- **Sonnet ring trough suppressed**: `draw_ring` now accepts `track=True/False`;
  inner ring is always drawn without a trough (`track=False`) so only the colored
  arc appears — no grey background circle.
- **Sonnet ring hidden at 0%**: entire inner `draw_ring` call skipped when
  `sonnet_pct == 0`; no arc and no trough rendered.
- **Tooltip separator spacing**: widened from ` | ` to `   |   ` (3 spaces each side).
- **`sawExtra` bug**: missing `let` declaration caused `ReferenceError` in strict-mode
  ES module, silently cleared the popup meter section after `removeAll()`.
