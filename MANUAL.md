# Claude Usage Indicator — User Manual

Shows your Claude.ai weekly usage percentage in the GNOME top panel and dock.

---

## What you see

**Top panel** (right side, next to Wi-Fi/battery):

```
  ✳ 74%
```

The ✳ is the Anthropic star logo icon. Color-coded: green < 50 % · amber 50–79 % · red ≥ 80 %

**Scroll** on the panel label to toggle between **All models** and **Sonnet only**.

**Click** the panel label to open the popup:

```
Max plan · 2m ago
────────────────────────────────────────────────
  Current session     29%  ███░░░░░░░  Resets in 3 hr 3 min
● All models          74%  ████████░░  Resets Tue 12:59 PM
  Sonnet only          4%  ░░░░░░░░░░  Resets Tue 12:59 PM
  Claude Design       51%  █████░░░░░  Resets Tue 1:00 PM
────────────────────────────────────────────────
Open Usage Page
```

The `●` marks the metric shown in the panel label.

**Dock icon** (once pinned — see Installation below):

<img src="docs/dock-icon-2rings-mockup.png" width="96">

- **Outer ring** — All models weekly usage (green → amber → red)
- **Inner ring** — Sonnet only weekly usage (blue by default)
- **Hover tooltip** — shows `Claude Usage — 77% / 9%`

The icon regenerates automatically on each data fetch.

---

## Installation

**Requirements:** Ubuntu 22.04+ · GNOME Shell 45–49 · Google Chrome (logged in to Claude.ai)

**Step 1 — Run the installer:**

```bash
git clone https://github.com/wbniv/claude-usage.git
cd claude-usage
./install.sh
```

This installs the GNOME extension, local server, systemd service, dock entry, and config file.
Python dependencies (`python3-cairo`, `python3-pil`) are installed automatically via apt if missing.

**Step 2 — Load the Chrome extension:**

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select the `chrome-extension/` folder inside this repo

**Step 3 — Log out and back in.**

This activates the GNOME Shell extension. The panel indicator appears immediately on login.

**Step 4 — Pin the dock icon (one-time):**

1. Press Super → search "Claude Usage"
2. Right-click the icon → **Add to Favorites**

The dock icon stays pinned across all future logins.

---

## After every login

Nothing to do. Everything starts automatically:

| Component | How it starts |
|-----------|--------------|
| Local data server | systemd user service (`claude-usage-fetch.service`) |
| Chrome extension | Persists in Chrome across restarts |
| GNOME panel indicator | Loaded by GNOME Shell from enabled-extensions list |

---

## Day-to-day use

**Data updates every 15 minutes** — the Chrome extension opens `claude.ai/settings/usage` in a background tab, scrapes the meters, and writes `~/.cache/claude-usage.json`. The panel indicator updates immediately when the file changes.

**Force an immediate refresh:** click the Claude Usage Tracker icon in the Chrome toolbar.

**Check the raw data:**

```bash
cat ~/.cache/claude-usage.json
```

---

## Configuration

Ring colors and other settings live in:

```
~/.config/claude-usage/config.json
```

Edit by hand, or open the GNOME preferences UI:

```bash
gnome-extensions prefs claude-usage@wbnorris.gmail.com
```

The prefs window has color pickers for all four ring states. Changes apply immediately — the dock icon regenerates as soon as you close the color dialog.

**Default config:**

```json
{
  "weekly_color_green": "#8cff8c",
  "weekly_color_amber": "#ffe033",
  "weekly_color_red":   "#ff5933",
  "sonnet_color":       "#4dbfff"
}
```

| Key | Ring | When |
|-----|------|------|
| `weekly_color_green` | Outer | All models < 50% |
| `weekly_color_amber` | Outer | All models 50–79% |
| `weekly_color_red`   | Outer | All models ≥ 80% |
| `sonnet_color`       | Inner | always |

---

## Troubleshooting

### Panel shows `--`
The cache file doesn't exist yet. Click the Chrome extension toolbar icon to trigger a fetch.

### Panel shows stale data ("Xm ago" is large)
The Chrome extension may not be running. Open Chrome → `chrome://extensions` → confirm Claude Usage Tracker is enabled. Click its toolbar icon to force a fetch.

### Server not running
```bash
systemctl --user status claude-usage-fetch.service
systemctl --user restart claude-usage-fetch.service
```

### Chrome extension errors
`chrome://extensions` → Claude Usage Tracker → **Errors**. Clear them, then click the toolbar icon to retry.

### Panel indicator missing after login
```bash
gnome-extensions list --enabled | grep claude-usage
# If not listed:
gnome-extensions enable claude-usage@wbnorris.gmail.com
```

### Dock icon not updating after editing config.json
Force a data fetch (Chrome toolbar icon) or re-run the icon generator directly:

```bash
python3 ~/.local/share/claude-usage/generate-icon.py
```

---

## Repo layout

```
claude-usage/
  chrome-extension/   Chrome extension (load via chrome://extensions → Load unpacked)
  gnome-extension/    GNOME Shell 45–49 panel + dock indicator
  server/             Local HTTP server + dock icon generator
  systemd/            User service definition
  desktop/            Dock launcher entry template
  install.sh          Installs everything; run once per machine
  MANUAL.md           This file
```

---

## Uninstall

```bash
./install.sh --uninstall
```

Then open `chrome://extensions` and remove Claude Usage Tracker. Log out and back in to clear the panel indicator.
