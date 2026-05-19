# formatReset: switch to day/time at >12 h instead of >24 h

## Context

`formatReset()` in `gnome-extension/extension.js` formats the "resets in …" string shown after
each meter bar. When the reset target is computed from a day/time string (e.g. "Resets Mon 3:00 PM"),
it shows `⏱h:mm` countdown when the reset is < 24 hours away, and falls back to
`resets Day HH:MM` when ≥ 24 hours away. The user wants the day/time format to appear earlier —
at > 12 hours — so countdowns longer than half a day show a concrete timestamp instead of a large
`⏱13:00`-style number.

## File modified

### `gnome-extension/extension.js` — line ~60 inside `formatReset()`

```js
// before
if (mins < 24 * 60)

// after
if (mins < 12 * 60)
```

No version bump — this bundles into the uncommitted 0.11.9 changes already on disk.

## Verification

1. `node --check gnome-extension/extension.js` — JS parses cleanly.
2. Logic: reset 13 h away (780 min): `780 < 720` → false → day/time shown. Reset 11 h away
   (660 min): `660 < 720` → true → `⏱11:00` shown.
