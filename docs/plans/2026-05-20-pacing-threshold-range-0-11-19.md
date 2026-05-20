# 2026-05-20 — Pacing-aware threshold range → 0.11.19

## Symptom

`gsettings set org.gnome.shell.extensions.claude-usage threshold-critical 150`
returns "The provided value is outside of the valid range" and leaves the
setting unchanged at 90.

## Root cause

`gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml`:

```xml
<key name="threshold-warning" type="u">
  <default>70</default>
  <summary>Pacing % (pct ÷ fraction-of-period-elapsed) at which color flips to warning</summary>
  <range min="1" max="99"/>
</key>
<key name="threshold-critical" type="u">
  <default>90</default>
  <summary>Pacing % (pct ÷ fraction-of-period-elapsed) at which color flips to critical</summary>
  <range min="1" max="99"/>
</key>
```

The schema cap of 99 dates from when the summary said the value was a raw-percentage threshold. Since the pacing pivot in 0.11.x, both summaries now describe a **pacing-%** value — and `pacingPct` returns `pct / fraction_elapsed` uncapped, so values above 100 are normal and expected (e.g. a Pro user mid-week at 13 % paces to 150 %). The range cap no longer matches the value semantics.

## Fix

Bump both `<range>` upper bounds:

```xml
<range min="1" max="500"/>
```

500 covers all realistic pacing scenarios — at 500 % you'd exhaust the whole bucket in 1/5 of the period, which is already off-the-charts. Higher caps don't add real expressive power; they just make the prefs slider numerically silly.

## Why widen both, not just critical

A user who wants `critical = 150` likely wants `warning = 100` (= "you're past linear pace") rather than the legacy default `warning = 70`. Letting both span the new range keeps the relationship adjustable.

## Files changed

1. `gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml` — `max="99"` → `max="500"` on both keys (2-line change).
2. `packaging/control` — `Version: 0.11.18` → `0.11.19`.
3. `chrome-extension/manifest.json` — `"version": "0.11.18"` → `"0.11.19"` (release-task parity guard).
4. `TODO.md` — move to Done after verification.

Default values stay 70/90 — existing users keep current behavior unless they actively raise the cap.

## Verification

1. `task test` — pre-existing 44+ pytest pass; lint passes. (No schema test exists; the change is pure XML range widening.)
2. After install:
   - `gsettings set ... threshold-critical 150` succeeds (was the failing case).
   - `gsettings set ... threshold-critical 600` still errors (new cap holds).
   - `claude-usage-status` continues to report `✓ v0.11.19`.
3. Visual: panel label color drops from red → orange because Current All Models pacing (~150 %) no longer exceeds the new critical threshold.

## Out of scope

- Adding `[verify]` for the schema migration on existing users — the default values are unchanged, the range is being widened (not narrowed), so existing GSettings values remain valid.
- Updating the prefs UI to expose this setting visually — that's separate scope; gsettings CLI is sufficient.
- Auto-migrating users who hit the old cap — n=1, that's the user landing this fix.
