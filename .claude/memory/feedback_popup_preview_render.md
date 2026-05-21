---
name: feedback_popup_preview_render
description: Render a PNG preview of the GNOME extension popup to avoid logout/login cycle when validating UI changes
metadata: 
  node_type: memory
  type: feedback
  originSessionId: eafa738a-bed5-49c0-a952-1c8eeb07fcb1
---

When extension.js changes require a GNOME Shell logout/login to take effect (Wayland), render a PNG mockup instead of asking the user to log out.

**Why:** GNOME Shell on Wayland can't hot-reload extensions via `gnome-extensions disable/enable` for JS code changes. A full logout/login is disruptive and slow.

**How to apply:** Write a Python script (in-line or temp file) that:
1. Reads `~/.cache/claude-usage.json` for live data
2. Reads GSettings via `Gio.Settings.new('org.gnome.shell.extensions.claude-usage')` for current config
3. Re-implements the JS logic (`formatRows`, `formatReset`, `pctColor`, `bar`) in Python
4. Renders a GNOME-styled popup PNG using PIL (`ImageFont.truetype`, `ImageDraw.rounded_rectangle`)
5. Saves to `/tmp/popup-preview.png` and sends with `SendUserFile`

Fonts available: `/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf` (monospace rows — use this, NOT UbuntuMono; DejaVu has ⏱ U+23F1 and block chars █░), `UbuntuSans[wdth,wght].ttf` (UI labels). Render at 28pt for crisp output.

Use `SURFACE=(50,50,50)`, `BG=(40,40,40)`, `SEP=(80,80,80)` to approximate Yaru-dark popup colours.

Do this proactively whenever extension.js display logic changes without first asking the user to log out.
