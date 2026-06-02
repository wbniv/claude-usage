# Security policy

## Reporting

Please report security issues privately to **will@biohack.net** rather than
opening a public GitHub issue. I'll acknowledge within a few days and aim to
ship a fix in the next release cycle.

If the issue is also exploitable in the upstream `claude.ai/settings/usage`
page itself, please report to Anthropic first; this project only reads the
page Anthropic serves you.

## Threat model

`claude-usage` is a desktop-side telemetry mirror for Anthropic's
`claude.ai/settings/usage` page. The pieces and their trust assumptions:

| Component | Reads | Writes | Trust assumption |
|-----------|-------|--------|------------------|
| Browser extension (MV3, Chrome/Firefox) | `claude.ai/settings/usage` page DOM (in your browser profile) | localhost ports 7331-7340 | Runs in your browser profile; sees only what your browser profile already sees. |
| Local HTTP server (`usage-server.py`) | POSTs from the browser ext over 127.0.0.1 | `~/.cache/claude-usage/usage.json` (mode 0600), `~/.local/share/applications/claude-usage.desktop`, `~/.local/share/icons/hicolor/<size>/apps/claude-usage.png` | Runs under your UID. Bound to 127.0.0.1 only. |
| GNOME extension | The cache JSON file | GNOME panel widgets only | Runs inside gnome-shell under your UID. |
| KDE plasmoid | The cache JSON file | KDE panel widgets only | Runs inside plasmashell under your UID. |

### In scope

- **Remote attackers** reaching the local HTTP server from outside the
  loopback interface. The server binds to `127.0.0.1`; this should be
  unreachable from outside the host, but a bug that ever caused it to bind
  `0.0.0.0` would be a security finding.
- **Drive-by web pages** issuing cross-origin fetches to the loopback ports.
  The server returns `Access-Control-Allow-Origin` only for
  `chrome-extension://...` or `moz-extension://...` requests; a web page Origin
  gets no CORS headers and the browser will block reading the response. The presence of the
  server is still observable via probe (yes/no, plus version), but contents
  are not exfiltrable to a web page.
- **Validator bypass** that lets a malicious POST persist arbitrary keys or
  values into the cache. The validator whitelists top-level keys, bounds
  string lengths, type-checks numerics, and caps list/dict sizes; any path
  past it is a finding.

### Out of scope (explicitly)

- **Same-user processes.** The loopback IPC's `/hello` handshake +
  `X-Claude-Usage-Server` response header are a *signature*, not access
  control: any other process running as your UID can bind 7331 first,
  respond with the right shape, and intercept the browser ext's POSTs.
  Mitigation today is OS-level process isolation (Flatpak sandboxes,
  browser sub-process separation, etc.). A future release may move to a
  UNIX domain socket under `$XDG_RUNTIME_DIR` with auth tokens, but the
  current architecture trusts everything running as you.
- **Persisted credentials.** The project stores none. Authentication to
  `claude.ai` lives in the user's browser profile cookie jar, which is
  the browser's responsibility.
- **Anthropic-side data.** What `claude.ai` chooses to expose on the
  `/settings/usage` page is Anthropic's call; this project only reads it.

## Data flow

See `PRIVACY.md` for the full data inventory. In brief:

```
claude.ai/settings/usage  (your browser session, your account)
        │
        ▼  scrape via scripting.executeScript (no creds leave the browser)
Browser extension (background)
        │
        ▼  HTTP POST to 127.0.0.1:7331-7340 (signature handshake, no auth)
usage-server.py
        │
        ├─▶ ~/.cache/claude-usage/usage.json  (0600, user-only)
        ├─▶ ~/.local/share/applications/claude-usage.desktop  (Name= tooltip)
        └─▶ ~/.local/share/icons/hicolor/*/apps/claude-usage.png  (live icon)
                │
                ▼  monitored by the panel frontend
        GNOME extension (Gio.FileMonitor) → gnome-shell renders panel + popup
        KDE plasmoid   (Plasma5Support DataSource) → plasmashell renders panel + popup
```

No outbound network calls other than:
1. `https://claude.ai/settings/usage` — the page you're already authenticated to.
2. `https://status.claude.com/api/v2/summary.json` — Anthropic's public
   status page, polled every scrape cycle to surface known outages in the
   broken-tier indicator. No auth, no identifying data sent.

## Known limitations

- **IPC-1 (pass-17):** loopback handshake has no authentication. Documented
  above; not actively exploited but worth knowing.
- **L-2 (pass-17):** scraper anchors on English page strings. A
  locale-translated `claude.ai/settings/usage` would cause the scraper to
  return empty meters; the `_parse_failure: 'locale_or_layout'` signal
  surfaces this in `claude-usage-status`. Not a security issue, but
  affects diagnostic clarity.
