# `.deb` Install Smoke Test

**Date:** 2026-05-16
**Status:** Planned

## Context

Pass-4 code review (`docs/investigations/2026-05-16-code-review-pass4.md`,
§"The .deb code path is the consistent weak point") observed that nearly every
new bug from passes 3 and 4 clustered on the `.deb` install path: missing
diagnostic script (P4-3), broken icon-regen lookup (P4-2), schema not landing
in the system glib dir (P3-5), wrong initial dock icon path (P3-3). Each fix
was easy in isolation, but the *pattern* — `.deb`-only regressions slipping
past because nobody installs the package between releases — is what needs
closing.

Pass-4 explicitly recommended a CI smoke test that builds, installs, verifies,
and removes the `.deb` in a clean container so every release tag exercises the
real install path. The current audit found:

- All P4 numbered bugs and code-quality items are fixed (committed as a single
  pass-4 fixes commit alongside this plan).
- The pass-4 A+ recommendation — `.deb` install smoke test — is still missing.

Docker is already available locally (`docker --version` → 29.5.0). The project
has no GitHub Actions config, so the smoke test belongs in `Taskfile.yml` where
it can be invoked manually before `task release`.

## Scope

Add one new `test-deb` task to `Taskfile.yml`. No other files change.

## Implementation

Insert after `build-chrome-zip` (around line 22):

```yaml
  test-deb:
    desc: Build, install, verify, and remove the .deb in a clean Ubuntu 24.04 container
    deps: [build]
    cmds:
      - |
        docker run --rm -v "$PWD/dist:/dist:ro" ubuntu:24.04 bash -c '
          set -euo pipefail
          export DEBIAN_FRONTEND=noninteractive
          apt-get update -qq
          apt-get install -y /dist/claude-usage_{{.VERSION}}_all.deb
          # Shipped binaries
          test -x /usr/bin/claude-usage-setup
          test -x /usr/bin/claude-usage-status
          # Shipped server
          test -f /usr/share/claude-usage/generate-icon.py
          test -f /usr/share/claude-usage/usage-server.py
          # Extension + compiled schema in both locations
          test -f /usr/share/gnome-shell/extensions/claude-usage@indri.studio/extension.js
          test -f /usr/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/gschemas.compiled
          test -f /usr/share/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
          # Desktop entry, icons, systemd unit
          test -f /usr/share/applications/claude-usage.desktop
          test -f /usr/share/pixmaps/claude-usage.png
          test -f /usr/share/icons/hicolor/64x64/apps/claude-usage.png
          test -f /usr/lib/systemd/user/claude-usage-fetch.service
          # CLI smoke + script-syntax sanity
          /usr/bin/claude-usage-status -h >/dev/null
          python3 -m py_compile /usr/share/claude-usage/generate-icon.py
          python3 -m py_compile /usr/share/claude-usage/usage-server.py
          bash -n /usr/bin/claude-usage-setup
          # Removal must clear the system-wide schema (postrm)
          apt-get remove -y claude-usage
          test ! -f /usr/share/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
          echo "OK"
        '
```

### Design decisions

**Ubuntu 24.04, not 22.04.** MANUAL.md targets "Ubuntu 22.04+", but the
package's `Depends: gnome-shell (>= 45)` would refuse to install on 22.04
(ships gnome-shell 42). 24.04 ships gnome-shell 46. Either the dep floor or
the manual claim should be reconciled — flagged as a follow-up, out of scope
here.

**Use `apt-get install` not `dpkg -i`.** This validates the `Depends:`
declaration end-to-end. The cost is pulling `gnome-shell` (~500 MB cold) into
the container; ~5–10 min cold, ~2–3 min warm. Acceptable for a pre-release
manual gate.

**Use `{{.VERSION}}` interpolation, not a wildcard.** `claude-usage_*.deb`
would match stale older versions accumulated in `dist/`. The interpolation
keys off `packaging/control`'s `Version:` field — same source of truth as
`build` and `release`.

**Why `postinst` doesn't break the test.** The new auto-`claude-usage-setup`
block (`packaging/postinst:15-29`) only fires when `SUDO_USER` is set and a
D-Bus session bus socket exists. In the container neither is true (apt-get
runs as root with no SUDO_USER), so postinst takes the fallback "print
instructions" path. Correct behavior, no test failure.

### Deferred (intentional)

- **Wire `test-deb` into `release` as `deps:`.** Forces every release to pass
  the smoke test. Defer until the task has run a few times against current
  main and proven stable.
- **Drop `gnome-shell (>= 45)` floor (or fix MANUAL's "22.04+").** Separate
  concern, not a regression.

## Verification

1. Test runs end-to-end against current code.
    ```
    task test-deb
    ```
    Expected: builds `dist/claude-usage_0.9.5_all.deb` if not already present,
    pulls `ubuntu:24.04`, installs, prints `OK`, exits 0. Cold: ~5–10 min.
    Warm: ~2–3 min.

2. Test actually catches a `.deb`-shipping regression. Temporarily comment out
    the `install -m 755 "$REPO_DIR/scripts/claude-usage-status.sh" \
    "$PKG/usr/bin/claude-usage-status"` line in `packaging/build-deb.sh:75`,
    rerun `task test-deb`. Expected: fails at
    `test -x /usr/bin/claude-usage-status`. Revert.

3. Test actually catches a `postrm` regression. Temporarily comment out line 6
    of `packaging/postrm` (the `rm -f /usr/share/glib-2.0/schemas/...` line),
    rebuild + rerun. Expected: fails at the post-removal `test ! -f`. Revert.

4. Sanity: stale debs in `dist/` don't pollute the test. `grep '^Version:' \
    packaging/control` should print `Version: 0.9.5`, and the install line in
    the container expands to `claude-usage_0.9.5_all.deb`.
