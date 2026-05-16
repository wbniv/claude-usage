# Claude Usage Indicator

Real-time Claude.ai usage meters in the GNOME top panel and dock.

<img src="docs/dock-icon-2rings-mockup.png" width="96" align="right">

**Top panel** — star icon + color-coded percentage. Scroll to toggle between All models and Sonnet only.

**Dock icon** — concentric rings + one-line hover tooltip:
- Outer ring: All models weekly usage (green → amber → red)
- Inner ring: Sonnet only (blue); hidden entirely when Sonnet usage is 0%
- Hover tooltip: `current 2% ⏱4:47   |   all 3% Tue 13:00   |   sonnet 5% Tue 13:00`

Click the panel indicator to expand all meters:

```
Max plan · 2m ago
──────────────────────────────────────────────────────────────
● All models                  1%  ░░░░░░░░░░  Resets Tue 1:00 PM
  Sonnet only                 2%  ░░░░░░░░░░  Resets Tue 1:00 PM
  Current session             8%  ████░░░░░░  Resets in 2h 50m
  Claude Design               0%  ░░░░░░░░░░
  Daily included routine runs  0/15
  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
  Extra usage                100%  ██████████  Resets Jun 1
  $4.11 spent · $0.90 balance
──────────────────────────────────────────────────────────────
Open Usage Page
```

The extra usage section only appears when you have extra usage enabled on your account.

---

## Requirements

- Ubuntu 22.04+ / GNOME Shell 45–49
- Google Chrome (logged in to Claude.ai)
- Python 3 with `python3-cairo` and `python3-pil`
- systemd user session

## Install

**Option A — Debian package** (recommended):

```bash
sudo dpkg -i claude-usage_1.0_all.deb
sudo apt-get install -f   # resolves any missing deps
claude-usage-setup        # per-user activation (run as yourself, not root)
```

**Option B — from source:**

```bash
git clone https://github.com/wbniv/claude-usage.git
cd claude-usage
./install.sh
```

`install.sh` installs Python deps via apt automatically.

**Both paths — load the Chrome extension:**

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `chrome-extension/` (source install) or `/usr/share/claude-usage/chrome-extension/` (.deb install)
4. Log out and back in
5. Super → search "Claude Usage" → right-click → **Add to Favorites** (pins the dock icon)

## How it works

```
claude.ai/settings/usage
    ↓  Chrome extension scrapes meters every 15 min
localhost:7331
    ↓  Python server writes JSON + regenerates dock icon
~/.cache/claude-usage.json
~/.cache/claude-usage-icon.png
    ↓  GNOME extension watches file, updates panel immediately
GNOME panel + dock
```

No API keys. No credentials stored. The Chrome extension uses your existing logged-in Claude.ai session.

## Configuration

All settings are stored in GSettings (dconf). Open the preferences UI:

```bash
gnome-extensions prefs claude-usage@wbnorris.gmail.com
```

Or set any value from the command line:

```bash
gsettings set org.gnome.shell.extensions.claude-usage popup-color-normal '#0000ff'
gsettings set org.gnome.shell.extensions.claude-usage threshold-warning 60
```

Changes to colors, thresholds, bar width, and font sizes apply instantly — no restart needed. (`panel-icon-size` requires reloading the extension.)

## Uninstall

**Source install:**
```bash
./install.sh --uninstall
```

**.deb install:**
```bash
sudo apt remove claude-usage
```

Then remove the Chrome extension from `chrome://extensions` and log out.

---

## Building packages

```bash
# Chrome Web Store zip
bash packaging/build-chrome-zip.sh   # → dist/claude-usage-chrome-1.0.zip

# Debian package
bash packaging/build-deb.sh          # → dist/claude-usage_1.0_all.deb
```

Upload the Chrome zip at [chrome.google.com/webstore/devconsole](https://chrome.google.com/webstore/devconsole) ($5 one-time developer fee). The privacy policy required for submission is in `PRIVACY.md`.
