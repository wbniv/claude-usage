# Claude Usage Indicator — User Manual

Shows your Claude.ai weekly usage percentage in the GNOME top panel and dock.

---

## What you see

**Top panel** (right side, next to Wi-Fi/battery):

```
  ✳ 74%
```

The ✳ is the Anthropic star logo icon. Color-coded: green below the warning threshold · amber at or above it · red at or above the critical threshold (defaults: 50% / 80%).

**Scroll** on the panel label to toggle between **All models** and **Sonnet only**.

**Click** the panel label to open the popup:

<img src="docs/popup-screenshot.png" width="564">

The `●` marks the metric shown in the panel label.

With extra usage enabled on your account, a second section appears:

<img src="docs/popup-extra-usage-screenshot.png" width="564">

**Dock icon** (once pinned — see Installation below):

<img src="docs/dock-icon-2rings-mockup.png" width="96">

- **Outer ring** — All models weekly usage (green → amber → red)
- **Inner ring** — Sonnet only weekly usage (blue by default); hidden entirely when Sonnet usage is 0%

**Hover** the dock icon to see a one-line summary tooltip:

<img src="docs/tooltip-screenshot.png" width="495">

Reset times show a countdown (`⏱h:mm`) when less than 24 h away, or a day + time otherwise. Sonnet is omitted from the tooltip when its usage is 0%.

The icon regenerates automatically on each data fetch.

---

## Installation

**Requirements:** Ubuntu 22.04+ · GNOME Shell 45–49 · Google Chrome (logged in to Claude.ai)

### Option A — Debian package

```bash
sudo dpkg -i claude-usage_1.0_all.deb
sudo apt-get install -f   # resolves any missing deps
claude-usage-setup        # run as yourself, not root
```

`claude-usage-setup` creates your config file, enables the systemd service, enables the GNOME extension, and installs the dock entry — all in one step.

### Option B — From source

```bash
git clone https://github.com/wbniv/claude-usage.git
cd claude-usage
./install.sh
```

`install.sh` installs Python deps (`python3-cairo`, `python3-pil`) via apt automatically if missing.

### Both paths — complete setup

**Load the Chrome extension:**

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select:
   - Source install: `chrome-extension/` inside the repo
   - .deb install: `/usr/share/claude-usage/chrome-extension/`

**Log out and back in** — activates the GNOME Shell extension.

**Pin the dock icon (one-time):**

1. Press Super → search "Claude Usage"
2. Right-click → **Add to Favorites**

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

All settings are stored in GSettings (dconf). Open the preferences UI:

```bash
gnome-extensions prefs claude-usage@indri.studio
```

Changes to colors, thresholds, bar width, and font sizes apply instantly — no restart needed.

You can also set any value from the command line:

```bash
gsettings set org.gnome.shell.extensions.claude-usage popup-color-normal '#0000ff'
gsettings set org.gnome.shell.extensions.claude-usage threshold-warning 60
gsettings reset org.gnome.shell.extensions.claude-usage popup-color-normal  # restore default
```

**All settings and defaults:**

| Setting | Default | Description |
|---------|---------|-------------|
| `poll-interval` | `5` | Minutes between re-reading the cache file |
| `weekly-color-green` | `#8cff8c` | Dock outer ring · below warning threshold |
| `weekly-color-amber` | `#ffe033` | Dock outer ring · ≥ warning threshold |
| `weekly-color-red` | `#ff5933` | Dock outer ring · ≥ critical threshold |
| `sonnet-color` | `#4dbfff` | Dock inner ring (hidden when Sonnet usage is 0%) |
| `popup-color-normal` | `#2a9a2a` | Popup text · below warning threshold |
| `popup-color-warning` | `#d07000` | Popup text · ≥ warning threshold |
| `popup-color-critical` | `#e03030` | Popup text · ≥ critical threshold |
| `threshold-warning` | `50` | % at which color flips to warning |
| `threshold-critical` | `80` | % at which color flips to critical |
| `bar-width` | `10` | █░ bar character count in popup |
| `panel-font-size` | `11` | Panel label font size (px) |
| `popup-font-size` | `10` | Popup meter row font size (px) |
| `popup-font-family` | `monospace` | Popup meter row font family |
| `panel-icon-size` | `16` | Panel icon pixel size (requires extension reload) |

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
gnome-extensions enable claude-usage@indri.studio
```

### Dock icon not updating after changing colors
Force a data fetch (Chrome toolbar icon) or re-run the icon generator directly:

```bash
# Source install:
python3 ~/.local/share/claude-usage/generate-icon.py
# .deb install:
python3 /usr/share/claude-usage/generate-icon.py
```

### Check or reset a setting

```bash
gsettings get org.gnome.shell.extensions.claude-usage popup-color-normal
gsettings reset org.gnome.shell.extensions.claude-usage popup-color-normal
gsettings reset-recursively org.gnome.shell.extensions.claude-usage  # restore all defaults
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
  packaging/          .deb and Chrome Web Store build scripts
  install.sh          Source install; run once per machine
  PRIVACY.md          Chrome Web Store privacy policy
  MANUAL.md           This file
```

---

## Uninstall

**Source install:**

```bash
./install.sh --uninstall
```

**.deb install:**

```bash
sudo apt remove claude-usage
rm -rf ~/.config/claude-usage   # optional: remove user config
```

Both: open `chrome://extensions`, remove Claude Usage Tracker, and log out.
