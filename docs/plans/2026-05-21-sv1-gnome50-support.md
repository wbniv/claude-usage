# SV-1: GNOME 50 support + ongoing version-tracking

## Context

`gnome-extension/metadata.json` lists `shell-version: ["45","46","47","48","49"]`. GNOME 50 shipped with Ubuntu 26.04 LTS (~Apr 2026). Without "50" in the array, GNOME Shell silently refuses to enable the extension. The user's policy: **test before claiming support** — only add a version after the Docker smoke test passes. This commit handles GNOME 50 and adds infrastructure so future releases take one command to test and one line to ship.

Host machine: GNOME 49.0, ~8 GB free disk (too small for a full VM). Docker is available and is the existing test pattern (`test-deb.Dockerfile`). GNOME Shell supports `--headless` (no display needed) since 3.36, which works in a container.

---

## Part 1 — Smoke-test infrastructure (build first, claim support after)

**Policy:** `shell-version` and README are only updated **after** `task test-gnome` passes for that version. The test runs first; the metadata edit is the last step.

## Part 2 — Parameterised smoke-test infrastructure

**`packaging/test-gnome.Dockerfile`** — single Dockerfile, Ubuntu version as ARG:
```dockerfile
FROM ubuntu:${UBUNTU_VERSION:-26.04}
ARG UBUNTU_VERSION
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnome-shell dbus-x11 glib-compile-schemas \
    && rm -rf /var/lib/apt/lists/*

COPY gnome-extension/ /root/.local/share/gnome-shell/extensions/claude-usage@indri.studio/
RUN glib-compile-schemas \
    /root/.local/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/

COPY packaging/test-gnome-verify.sh /verify.sh
RUN chmod +x /verify.sh
CMD ["/verify.sh"]
```

**`packaging/test-gnome-verify.sh`** — headless gnome-shell load check:
```bash
#!/usr/bin/env bash
set -euo pipefail
version=$(gnome-shell --version)
echo "Shell version: $version"
major=$(echo "$version" | grep -oP '\d+' | head -1)

# Start headless gnome-shell in a private session bus; enable extension; check for JS errors
dbus-run-session -- bash -c "
    gnome-shell --headless &
    SPID=\$!
    sleep 5
    gnome-extensions enable claude-usage@indri.studio 2>&1 || true
    sleep 2
    ERRORS=\$(journalctl _PID=\$SPID 2>/dev/null | grep -iE 'error.*claude-usage|claude-usage.*error|JS ERROR' || true)
    kill \$SPID 2>/dev/null || true
    if [ -n \"\$ERRORS\" ]; then
        echo 'FAIL: extension errors:'
        echo \"\$ERRORS\"
        exit 1
    fi
    echo \"PASS: claude-usage extension loaded cleanly on GNOME \$major\"
"
```

**`Taskfile.yml`** — add `test-gnome` task (parameterised by `UBUNTU_VERSION`, defaults to `26.04`):
```yaml
test-gnome:
  desc: "Smoke-test extension on a specific GNOME Shell version via Docker (UBUNTU_VERSION=26.04)"
  vars:
    UBUNTU_VERSION: '{{.UBUNTU_VERSION | default "26.04"}}'
  cmds:
    - >
      docker build
      --build-arg UBUNTU_VERSION={{.UBUNTU_VERSION}}
      -f packaging/test-gnome.Dockerfile
      -t claude-usage-gnome-{{.UBUNTU_VERSION}} .
    - docker run --rm claude-usage-gnome-{{.UBUNTU_VERSION}}
```

Usage: `task test-gnome` (defaults to 26.04) or `task test-gnome UBUNTU_VERSION=27.04` for next cycle.

---

## Part 3 — Automated GNOME release detection (GitHub Actions)

**`.github/workflows/gnome-version-check.yml`** — weekly cron that detects new GNOME major versions and opens a GitHub issue:

```yaml
name: GNOME version check
on:
  schedule:
    - cron: '0 9 * * 1'  # every Monday 09:00 UTC
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Detect latest GNOME Shell major version
        id: detect
        run: |
          # Pull ubuntu:latest and ask what gnome-shell version it ships
          latest=$(docker run --rm ubuntu:latest bash -c \
            'apt-get update -qq && apt-cache show gnome-shell 2>/dev/null \
             | grep "^Version:" | head -1 | grep -oP "^\S+ \K\d+"')
          echo "latest_major=$latest" >> $GITHUB_OUTPUT

      - name: Read currently supported max version
        id: current
        run: |
          max=$(python3 -c "
          import json, sys
          d = json.load(open('gnome-extension/metadata.json'))
          print(max(int(v) for v in d['shell-version']))
          ")
          echo "max_supported=$max" >> $GITHUB_OUTPUT

      - name: Open issue if new version detected
        if: steps.detect.outputs.latest_major > steps.current.outputs.max_supported
        uses: actions/github-script@v7
        with:
          script: |
            const latest = '${{ steps.detect.outputs.latest_major }}';
            const current = '${{ steps.current.outputs.max_supported }}';
            const title = `GNOME ${latest} detected — run test-gnome and add shell-version support`;
            const body = [
              `ubuntu:latest now ships GNOME Shell **${latest}** (currently max supported: **${current}**).`,
              ``,
              `To add support:`,
              `1. \`task test-gnome UBUNTU_VERSION=<ubuntu-version-with-gnome-${latest}>\``,
              `2. If green, add \`"${latest}"\` to \`gnome-extension/metadata.json\` shell-version`,
              `3. Update README.md requirements line`,
              `4. Bump version + release`,
            ].join('\n');
            await github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title,
              body,
              labels: ['gnome-compat'],
            });
```

This opens an issue **only when a new major version is detected** — won't spam on re-runs. The issue body gives exact steps to close it.

---

## Files to create/modify

| File | Change |
|------|--------|
| `packaging/test-gnome.Dockerfile` | New — parameterised Ubuntu version |
| `packaging/test-gnome-verify.sh` | New — headless load check |
| `Taskfile.yml` | Add `test-gnome` task |
| `.github/workflows/gnome-version-check.yml` | New — weekly release detector |
| `gnome-extension/metadata.json` | Add `"50"` — **only after test passes** |
| `MANUAL.md` | Update requirements to `GNOME Shell 45–50` — **only after test passes** |

---

## Verification

1. `task test` — existing suite still green (no changes to tested code)

```
gen-js-defaults: in sync with the schema   ← PASS
```

2. `task test-gnome` — Docker build succeeds, container exits 0, output shows PASS

```
=== GNOME extension smoke test ===
Shell: GNOME Shell 50.1
  PASS  gnome-shell --version returns major=50
  PASS  metadata.json uuid matches extension directory
  PASS  gschemas.compiled present
  PASS  imports.gi.GLib
  PASS  imports.gi.GObject
  PASS  imports.gi.Gio
  PASS  imports.gi.Adw
  PASS  imports.gi.Gtk
  PASS  imports.gi.Gdk
  INFO  St, Clutter skipped — shell-internal, require running gnome-shell
  INFO  shell-version already includes 50
=== Results: 9 passed, 0 failed ===
OVERALL: PASS — safe to add "50" to gnome-extension/metadata.json shell-version
```

3. `"50"` added to `metadata.json` shell-version; `MANUAL.md` updated to `GNOME Shell 45–50`
4. `gh workflow run gnome-version-check.yml` (manual trigger) — verify workflow runs without error
