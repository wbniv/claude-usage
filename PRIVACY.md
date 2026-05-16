# Privacy Policy — Claude Usage Tracker

**Last updated: 2026-05-15**

## What data is collected

The Claude Usage Tracker Chrome extension reads your Claude.ai usage meters from `claude.ai/settings/usage` using your existing logged-in browser session.

The data collected is:

- Usage percentages for each meter (All models, Sonnet only, etc.)
- Meter reset times
- Your Claude plan name (e.g. "Max", "Pro")

## Where data goes

All data stays on your own machine. It is sent only to `http://127.0.0.1:7331` — a local Python server running on your computer — and written under `~/.cache/claude-usage/`.

**No data is transmitted to any remote server, third party, or the extension developer.**

## What is stored

- `~/.cache/claude-usage/usage.json` — usage data, updated every 15 minutes
- `~/.cache/claude-usage/icon-{epoch}.png` — generated dock icon (filename rotates to bust the pixbuf cache)
- GSettings (`org.gnome.shell.extensions.claude-usage`) — user color and threshold preferences
- `chrome.storage.local` — fallback copy of the last fetch, used only when the local server is not running

## Permissions used

| Permission | Why |
|------------|-----|
| `tabs` | Open `claude.ai/settings/usage` in a background tab to read usage data |
| `scripting` | Inject a script into that tab to read the meter values from the DOM |
| `alarms` | Schedule a fetch every 15 minutes |
| `storage` | Store a fallback copy of usage data when the local server is unavailable |
| `https://claude.ai/*` | Access the usage page |
| `http://127.0.0.1:7331/*` | Post data to the local server |

## Contact

Will Norris — will@biohack.net
