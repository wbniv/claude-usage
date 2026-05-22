# `curl | bash` installer + pre-flight hardening

> Mirror of `~/SRC/indri.studio/docs/plans/2026-05-22-claude-usage-curlbash-installer.md`.
> The bootstrap script and `publish-local.sh` change live in the `indri.studio` repo; this repo owns the `install.sh` pre-flight checks and the `MANUAL.md` reframe.

## Context

`MANUAL.md` advertises two install paths: Option A (`.deb`) and Option B ("From source" — `git clone` + `./install.sh`). The label is misleading — `install.sh` doesn't compile anything; it copies JS + Python files into XDG paths, registers a systemd user unit + dock launcher, runs `glib-compile-schemas` (XML→binary) and `gen-js-defaults.py` codegen.

There's no one-liner installer today, and `install.sh` quietly assumes `glib-compile-schemas`, `systemctl --user`, and `gnome-shell` are present (it only hard-checks `rsync` and auto-installs `python3-cairo`/`pillow`).

This work adds a hosted `curl | bash` installer at `https://apt.indri.studio/install-claude-usage.sh` and closes the dep-check gaps in `install.sh` so every install path (clone / .deb / one-liner) fails fast and actionably on a misconfigured host.

## Changes in this repo

### `install.sh` — pre-flight checks

Insert a block immediately after the existing `rsync` check (around line 13), modelled on the Python-deps auto-install pattern below it. Runs before any file copy so a failure leaves the system untouched.

- **`glib-compile-schemas`** — `command -v` probe. On miss, distro-aware install hint (`sudo apt install libglib2.0-bin` / `sudo dnf install glib2` / `sudo pacman -S glib2`). **Hard-fail** — it's needed for both the extension schema (`:121`) and the user-glib schema (`:126`).
- **`systemctl --user`** — probe via `systemctl --user --version`. On miss, print "systemd-user not available — required for the data-fetch service" and exit.
- **`gnome-shell`** — parse `gnome-shell --version` (e.g. `GNOME Shell 50.0`). If absent or outside 45–50, **warn** (don't fail) — the script can still install the files; the user just won't see the panel indicator on an unsupported GNOME.

### `MANUAL.md` §Installation

- Relabel **Option B** from "From source" to "From a clone". Add a one-line clarification that there's no compilation — just file placement + service wiring (so the curl|bash route makes sense as the same wire-up).
- Add **Option C — One-liner**:
    ```bash
    curl -fsSL https://apt.indri.studio/install-claude-usage.sh | bash
    ```
    Same wire-up as Option B, no clone needed. The bootstrap fetches the latest release tarball and execs `install.sh`.

The existing "Pick one install method" warning at `MANUAL.md:84` already covers the source/.deb conflict; Option C falls under the same source side.

## Cross-repo (indri.studio)

- New `apt/installers/claude-usage.sh` — thin wrapper that resolves the latest GitHub release tag, fetches the tarball, and `exec`s `install.sh`.
- `apt/scripts/publish-local.sh` adds one line to stage the bootstrap into `public/install-claude-usage.sh`, which rides the existing rclone sync on every `apt-v*` tag.

## Verification (this repo's slice)

1. **`--help` short-circuits before pre-flight.**
    ```bash
    ./install.sh --help
    ```
    Should print usage and exit 0 without touching dependencies.

2. **Pre-flight hard-fails when `glib-compile-schemas` is hidden.**
    ```bash
    env -i PATH=/tmp HOME="$HOME" ./install.sh
    ```
    Expect actionable distro-aware message and non-zero exit.

3. **Bootstrap end-to-end (run after the indri.studio side ships).**
    ```bash
    curl -fsSL https://apt.indri.studio/install-claude-usage.sh | bash
    ```
    Expect same outcome as `./install.sh` from a clone.

4. **MANUAL preview.**
    ```bash
    task md -- MANUAL.md
    ```
