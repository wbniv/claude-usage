# Privacy Policy — Claude Usage Tracker

**Last updated: 2026-05-18**

## What data is collected

The Claude Usage Tracker Chrome extension reads your Claude.ai usage meters from `claude.ai/settings/usage` using your existing logged-in browser session.

The data collected is:

- Usage percentages for each meter (All models, Sonnet only, etc.)
- Meter reset times
- Your Claude plan name (e.g. "Max", "Pro")

## Where data goes

All data stays on your own machine. It is sent only to `http://127.0.0.1:<port>` — a local Python server running on your computer — and written under `~/.cache/claude-usage/`. The server picks the first free port in 7331-7340 and records its choice in `~/.cache/claude-usage/port`; the Chrome extension probes that range to discover it.

**No data is transmitted to any remote server, third party, or the extension developer.**

## What is stored

- `~/.cache/claude-usage/usage.json` — usage data, inferred per-meter period lengths (`_period_lengths`: integer minutes-per-meter-label, used for pacing-based color thresholds), consecutive-scrape-failure counter (`_scrape_fail_count`), and Anthropic public status-page snapshot (`_anthropic_status`: incident indicator + description). Updated every 7 minutes.
- `~/.local/share/icons/hicolor/{48,64,96,128,256}x{N}/apps/claude-usage.png` — generated dock icon, emitted at each hicolor size so the XDG icon-theme lookup always picks the live ring-painted version regardless of what size the dock requests
- GSettings (`org.gnome.shell.extensions.claude-usage`) — user color and threshold preferences
- `chrome.storage.local` — fallback copy of the last fetch, used only when the local server is not running

## Permissions used

| Permission | Why |
|------------|-----|
| `tabs` | Open `claude.ai/settings/usage` in a background tab to read usage data |
| `scripting` | Inject a script into that tab to read the meter values from the DOM |
| `alarms` | Schedule a fetch every 7 minutes |
| `storage` | Store a fallback copy of usage data when the local server is unavailable |
| `https://claude.ai/*` | Access the usage page |
| `https://status.claude.com/*` | Poll Anthropic's public status page for outage detection (no auth, no token cost) |
| `http://127.0.0.1:7331-7340/*` | Discover and post data to the local server (one of these ports, chosen at server startup) |

## Contact

Will Norris — will@biohack.net
