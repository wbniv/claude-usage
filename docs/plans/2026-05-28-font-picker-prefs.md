# Font Picker for Popup Font Preference

## Context

The "Popup Font" section in `prefs.js` used a plain `Adw.EntryRow` requiring the user to type a font family name by hand. Replacing it with `Gtk.FontDialogButton` (GTK 4.10+, available on GTK 4.20.1) following the same pattern already used for color pickers.

## Changes

**File:** `gnome-extension/prefs.js`

1. Add `import Pango from 'gi://Pango'`
2. Add `addFontRow()` helper — `Gtk.FontDialog` + `Gtk.FontDialogButton` with `level: Gtk.FontLevel.FAMILY` (family-only, no size/weight bleed)
3. Replace the `Adw.EntryRow` block in the Popup Font group with `addFontRow(...)`

No schema changes — `popup-font-family` remains a plain string key.

## Verification

1. `gnome-extensions prefs claude-usage@indri.studio` — prefs opens cleanly
2. Popup Font section shows a font button, not a text entry
3. Clicking opens system font picker (family-only)
4. Selection persists: `gsettings get org.gnome.shell.extensions.claude-usage popup-font-family`
5. `task build` — .deb builds without errors
