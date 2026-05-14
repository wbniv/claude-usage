# Claude Usage Panel Indicator

GNOME Shell top-panel indicator showing your Claude.ai weekly usage percentage in real time.

**What it shows:** the "All models" weekly limit bar from `claude.ai/settings/usage` — the same meters you see on the usage page, updated every 15 minutes.

```
  🤖 74%   ← panel label (color-coded green/amber/red)
```

Click the indicator to see all four meters:

```
Max plan · 2m ago
────────────────────────────────
Current session     29%  ███░░░░░░░  Resets in 3 hr 3 min
All models          74%  ████████░░  Resets Tue 12:59 PM
Sonnet only          4%  ░░░░░░░░░░  Resets Tue 12:59 PM
Claude Design       51%  █████░░░░░  Resets Tue 1:00 PM
────────────────────────────────
Open Usage Page
```

## Requirements

- GNOME Shell 45–49 (Wayland or X11)
- Google Chrome (with the bundled extension loaded)
- Python 3 (stdlib only — no pip installs)
- systemd (user session)

## Install

```bash
git clone git@github.com:wbniv/claude-usage.git
cd claude-usage
chmod +x install.sh
./install.sh
```

Then load the Chrome extension:

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select `chrome-extension/` inside this repo
4. Log out and back in to activate the GNOME panel indicator

## How it works

```
chrome.ai/settings/usage
        ↓  (Chrome extension, every 15 min)
localhost:7331
        ↓  (Python server → JSON file)
~/.cache/claude-usage.json
        ↓  (file monitor)
GNOME panel indicator
```

The Chrome extension opens the usage page in a background tab, waits for React to render, scrapes the meter values from the DOM, and POSTs them to a tiny local HTTP server. The GNOME extension watches the resulting JSON file and updates the panel label immediately.

No API keys. No credentials stored. The Chrome extension uses your existing logged-in Claude.ai session.

## Uninstall

```bash
./install.sh --uninstall
```

Then remove the Chrome extension from `chrome://extensions`.

## Redistribution

Currently a private repo. To share:

- **With individuals:** add them as GitHub collaborators, or share a zip of the repo
- **Public release:** change repo visibility, submit the GNOME extension to [extensions.gnome.org](https://extensions.gnome.org), submit the Chrome extension to the Chrome Web Store ($5 one-time developer fee)
