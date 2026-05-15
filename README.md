# Claude Usage Indicator

Real-time Claude.ai usage meters in the GNOME top panel and dock.

<img src="docs/dock-icon-2rings-mockup.png" width="96" align="right">

**Top panel** — star icon + color-coded percentage. Scroll to toggle between All models and Sonnet only.

**Dock icon** — two concentric rings:
- Outer ring: All models weekly usage (green → amber → red)
- Inner ring: Sonnet only (blue)
- Hover tooltip: `Claude Usage — 77% / 9%`

Click the panel indicator to expand all four meters:

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

Ring colors and settings live in `~/.config/claude-usage/config.json`:

```json
{
  "weekly_color_green": "#8cff8c",
  "weekly_color_amber": "#ffe033",
  "weekly_color_red":   "#ff5933",
  "sonnet_color":       "#4dbfff"
}
```

Edit by hand or open the GNOME preferences UI:

```bash
gnome-extensions prefs claude-usage@wbnorris.gmail.com
```

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
