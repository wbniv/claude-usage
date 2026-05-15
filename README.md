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
- Python 3 with `python3-cairo` and `python3-pil` (installed automatically)
- systemd user session

## Install

```bash
git clone https://github.com/wbniv/claude-usage.git
cd claude-usage
./install.sh
```

Then load the Chrome extension:

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select the `chrome-extension/` folder inside this repo
4. Log out and back in (activates the GNOME panel indicator)
5. Find "Claude Usage" in the app grid → right-click → **Add to Favorites** (pins the dock icon)

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

```bash
./install.sh --uninstall
```

Then remove the Chrome extension from `chrome://extensions` and log out.

---

## Distribution

This is currently a private repo. Options for sharing:

| Path | Effort | Reach |
|------|--------|-------|
| Share repo URL / add collaborators | none | individuals |
| Make repo public | none | anyone technical |
| Chrome Web Store ($5 one-time fee) | low | Chrome users |
| GNOME Extensions (extensions.gnome.org) | medium | GNOME users (extension only — still needs Chrome ext + server) |
| `.deb` / Snap / Flatpak | high | broad Ubuntu audience, no manual steps |

For full self-contained distribution the `.deb` route is cleanest — it can bundle the Python server, install system deps, and register the systemd service. The Chrome extension would still need to be loaded separately (Chrome Web Store or Load unpacked).
