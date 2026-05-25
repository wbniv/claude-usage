# Phase 2 — Foundry Linux devbox container image

## Context

**Why now:** Phases 0 (curl-bash installer) and 1 (signed apt repos on R2) are complete. Phase 2 ships `ghcr.io/foundry-linux/devbox:26.04` — a Distrobox-compatible OCI image with the full WF authoring + retro-porting stack preinstalled. Users get a one-`distrobox create` working environment without touching their host OS; per-game work goes into ephemeral Distroboxen layered on top.

**What's already decided** (this conversation, 2026-05-21):

- **Scope:** base image only. The `wf-game-create` per-game tooling has been **deferred to its own follow-up plan** (to be written separately, e.g. `docs/plans/2026-05-21-phase-2-per-game-tooling.md`). Users can still create per-game Distroboxen by hand (`distrobox create -i ghcr.io/foundry-linux/devbox:26.04 -n wf-<game>`) until that helper ships.
- **Image contents — metapackages only (excluding `-dev` / `-development` suffixed Foundry/WF names) + a curated Ubuntu universe game-dev set:**

  **From `apt.foundrylinux.org`:**
  `foundry-linux-retro-tools` (transitively brings the standalone-binary packages `f9dasm`, `ghidra`, `libvgm`, `vgmstream` plus Ubuntu's `mame`, `mame-tools`, `dasm`, `cc65`, `z80dasm`, `z80asm`, `radare2`, `binwalk`, `sox`, `binutils-m68k-linux-gnu`, `xa65`). Excluded: `foundry-linux-android-development`, `foundry-linux-ios-development`.

  **From `apt.worldfoundry.org`:**
  `worldfoundry`, `worldfoundry-cli`, `worldfoundry-blender` (transitively brings the 10 WF CLIs, `wf-blender`, `blender-asset-finder`, `blender-asset-finder-cli`, and the regular Ubuntu `blender` package). Excluded: `worldfoundry-development`.

  **From Ubuntu 26.04 universe — curated game-dev additions:**
  - Retro emulators not covered by `mame`: `dosbox-x`, `scummvm`, `fceux`, `mednafen`, `stella`, `hatari`, `fs-uae`, `openmsx`, `openmsx-data`, `frotz`
  - Game-dev frameworks + headers: `tiled`, `love`, `libsdl2-dev`, `libsdl3-dev`, `libsfml-dev`, `liballegro5-dev`, `libtcod-dev`, `glslang-tools`, `spirv-cross`, `spirv-tools`
  - Trackers + chiptune: `milkytracker`, `schism`, `furnace`, `openmpt123`
  - Pixel art: `mtpaint`, `grafx2`
  - Image CLI: `imagemagick`, `graphicsmagick`

  **Explicit:** `blender` itself (pulled transitively via `worldfoundry-blender`, but listed for visibility / manual-installed marker).

  **From Cloudsmith:** `task`.

  **Deliberately excluded** (per user direction):
  - Anything in Ubuntu multiverse — `vice`, `atari800`, `fbzx`, `mame-extra`, `vcmi`, `openrct2`, `fheroes2`, `exult`, etc. — categorized separately.
  - Free games + their massive data packs (`0ad` + 3.5 GB data, `supertuxkart` + 770 MB data, `flightgear` + ~3 GB data, etc.).
  - Heavy DAWs and console emulators (`ardour` 62 MB, `dolphin-emu` 68 MB, `pcsx2` 50 MB, `yuzu` 39 MB, `retroarch-assets` 116 MB).
  - General raster/vector art (`krita` 98 MB, `gimp` 33 MB, `inkscape` 107 MB) — too heavy for default; users `apt install` if needed.
- **Source location:** monorepo subdir `foundry-devbox/` mirrored to `github.com/foundry-linux/foundry-devbox` via `task devbox-sync`, matching the existing `foundry-apt/` pattern. GHCR publish triggered by tag push on the remote.

**Image size — ~3.3 GB uncompressed:**

```
ghcr.io/foundry-linux/devbox:26.04
────────────────────────────────────────────────────────────────
ubuntu:26.04 base                                       250 MB
worldfoundry  +  worldfoundry-cli  +  worldfoundry-blender
  ├─ blender 4.2+ (regular Ubuntu universe pkg)         555 MB
  ├─ wf-blender add-on + blender-asset-finder add-on      1 MB
  └─ 10 WF CLIs (cdpack, iffcomp, levcomp, …)             4 MB
foundry-linux-retro-tools
  ├─ ghidra + openjdk-21-jdk                          1.40 GB
  ├─ mame + mame-tools                                  500 MB
  ├─ blender-asset-finder-cli                            <1 MB
  └─ dasm/cc65/z80*/radare2/binwalk/sox/m68k/etc.        60 MB
Ubuntu universe game-dev additions                    ~500 MB
  ├─ retro emulators (dosbox-x, scummvm, fceux,
  │  mednafen, stella, hatari, fs-uae, openmsx,
  │  openmsx-data, frotz)                              215 MB
  ├─ game-dev frameworks + SDL/SFML/Allegro/tcod
  │  headers + Vulkan shader tools                     245 MB
  ├─ trackers (milkytracker, schism, furnace,
  │  openmpt123) + pixel art (mtpaint, grafx2)          35 MB
  └─ image CLI (imagemagick, graphicsmagick)             6 MB
task                                                    15 MB
────────────────────────────────────────────────────────────────
TOTAL                                                  ~3.3 GB
```

The Ubuntu universe additions cost ~500 MB on top of the bare ~2.8 GB Foundry-stack base. Everything in the universe-additions set is small individually — `scummvm` is the largest at 119 MB, followed by `furnace` at 26 MB and `spirv-tools` at 23 MB. Excluded from default: Ubuntu multiverse retro emulators (`vice`, `atari800`, `fbzx`), heavy emulators (`dolphin-emu`, `pcsx2`, `yuzu`), large DAWs (`ardour`), free-game data packs (multi-GB).

**Outcome:** `distrobox create -i ghcr.io/foundry-linux/devbox:26.04 -n foundry && distrobox enter foundry` drops the user into a working WF env in under a minute.

## Layout

```
foundry-devbox/                              # NEW monorepo subdir
  Dockerfile                                 # ubuntu:26.04 → worldfoundry stack + retro-tools + blender + task
  Taskfile.yml                               # build, run, push (local dev tasks)
  README.md
  .github/workflows/publish.yml              # tag-driven GHCR publish (built on the mirrored remote)
  test/
    smoke-test.sh                            # `docker run` the local image; assert tools on PATH
```

Top-level `Taskfile.yml` gains two tasks (mirroring the existing `sync` / `release` for foundry-apt):

- `task devbox-sync` — archive `foundry-devbox/` from HEAD, overlay on a fresh clone of `foundry-linux/foundry-devbox`, commit + push if anything changed.
- `task devbox-release TAG=v0.x.y` — tag the remote and trigger CI.

Reuse the **already-fixed sync detection** from `Taskfile.yml:30-37` (`git status --porcelain`, not `git diff --quiet`) so new files actually propagate — that fix landed in commit `3e85f90` for foundry-apt's sync.

## Critical files

- **Reuse:** `foundry-apt/.github/workflows/publish.yml` (tag-trigger + `dry_run` input pattern, secrets pattern), `Taskfile.yml:19-50` (sync/release tasks template), `foundry-linux-setup/install-foundry-linux-dev.sh:85-103` (exact `apt install` sequence to mirror in the Dockerfile), `foundry-linux-setup/setup-foundry-apt-source.sh` / `setup-worldfoundry-apt-source.sh` (key+source format).
- **Reference (read-only):** `docs/investigations/2026-05-16-foundry-linux-distro-proposal.md:562-591` (original Channel 2 spec — Dockerfile sketch + GHCR rationale). The per-game container pattern (§763-836) is the subject of the companion plan in `docs/plans/2026-05-21-phase-2-per-game-tooling.md`.

## Dockerfile (single-stage, ~3.3 GB)

```dockerfile
# ghcr.io/foundry-linux/devbox:26.04
#
# Distrobox-compatible OCI image for World Foundry game-dev and retro-porting.
# Base MUST be ubuntu:26.04 — matches the apt suite ("resolute") and the
# distribution we ship. Host's KDE renders GUI; no Plasma needed inside.

FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=all

# Layer 1: apt bootstrap + both Foundry-family apt sources
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
 && install -d /etc/apt/keyrings \
 && curl -fsSL https://apt.foundrylinux.org/key.gpg \
      | gpg --dearmor -o /etc/apt/keyrings/foundry.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/foundry.gpg] https://apt.foundrylinux.org resolute main" \
      > /etc/apt/sources.list.d/foundry.list \
 && curl -fsSL https://apt.worldfoundry.org/key.gpg \
      | gpg --dearmor -o /etc/apt/keyrings/worldfoundry.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/worldfoundry.gpg] https://apt.worldfoundry.org stable main" \
      > /etc/apt/sources.list.d/worldfoundry.list \
 && apt-get update

# Layer 2: Foundry/WF metapackages (the big layer — ~2.5 GB)
#
# Rule for picking what goes in this layer: metapackages only, excluding
# names ending in -dev or -development. This image is for game authoring +
# retro porting + play; engine compilation belongs to a maintainer-tier
# image so the default pull stays light.
#
# Transitive expansion (apt resolves these; comments are for readers):
#   worldfoundry           = worldfoundry-cli + worldfoundry-blender
#   worldfoundry-cli       = cdpack iffcomp iffdump levcomp lvldump oaddump
#                            oas2oad textile blender-asset-finder-cli prep
#   worldfoundry-blender   = wf-blender + blender-asset-finder + blender
#   foundry-linux-retro-tools
#                          = mame mame-tools dasm cc65 z80dasm z80asm
#                            radare2 binwalk sox binutils-m68k-linux-gnu
#                            xa65 f9dasm libvgm vgmstream ghidra
RUN apt-get install -y --no-install-recommends \
        worldfoundry \
        worldfoundry-cli \
        worldfoundry-blender \
        blender \
        foundry-linux-retro-tools

# Layer 3: curated Ubuntu universe game-dev additions (~500 MB)
#
# Adds capability the Foundry/WF metapackages don't cover:
#   - retro emulators for systems mame doesn't handle well (DOS, ScummVM
#     adventure engines, NES dedicated, Atari ST/STE, Amiga, Atari 2600,
#     MSX, PCE/Lynx via mednafen, Z-code/Infocom, Nintendo DS)
#   - 2D/3D game-dev frameworks + SDK headers (LÖVE/Lua, SDL2/3, SFML,
#     Allegro 5, libtcod) — having headers means contributors can build
#     small games inside the box without further apt
#   - shader-pipeline tooling (Vulkan glslang, SPIR-V cross/tools)
#   - chiptune trackers (MilkyTracker, Schism, Furnace) + module player
#   - pixel-art paint (mtpaint, grafx2)
#   - image-CLI utilities (ImageMagick, GraphicsMagick) for asset
#     pipelines
#
# Deliberately excluded: Ubuntu multiverse retro emulators (vice/atari800/
# fbzx — separate licensing tier), heavy emulators (dolphin/pcsx2/yuzu),
# large DAWs (ardour/rosegarden), full art suites (krita/gimp/inkscape),
# and free-game data packs (0ad/supertuxkart/widelands — multi-GB).
RUN apt-get install -y --no-install-recommends \
        dosbox-x scummvm fceux mednafen stella hatari fs-uae \
        openmsx openmsx-data frotz desmume \
        tiled love libsdl2-dev libsdl3-dev libsfml-dev \
        liballegro5-dev libtcod-dev \
        glslang-tools spirv-cross spirv-tools \
        milkytracker schism furnace openmpt123 \
        mtpaint grafx2 \
        imagemagick graphicsmagick

# Layer 4: task runner (Cloudsmith repo)
RUN curl -1sLf 'https://dl.cloudsmith.io/public/task/task/setup.deb.sh' | bash \
 && apt-get install -y task

# Layer 5: Distrobox conveniences (sudo for rootless mode, libvte for terminal
# integration, bash-completion + man-db for usability)
RUN apt-get install -y --no-install-recommends \
        sudo libvte-2.91-0 bash-completion man-db \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="Foundry Linux devbox" \
      org.opencontainers.image.description="Distrobox-compatible WF authoring + retro-porting environment for Ubuntu 26.04" \
      org.opencontainers.image.source="https://github.com/foundry-linux/foundry-devbox" \
      org.opencontainers.image.licenses="GPL-2.0-or-later"

CMD ["/bin/bash"]
```

**Layer ordering rationale:** apt-source plumbing is tiny and stable (rarely re-pulled); the big WF + retro-tools install is its own layer so layer cache hits when only the apt sources or task version change. `task` (Cloudsmith) gets its own layer because its version changes more often than the WF stack.

## GHCR publish workflow (lives in `foundry-devbox/.github/workflows/publish.yml`)

```yaml
name: Build and publish devbox image

on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Build only; do not push to GHCR'
        type: boolean
        default: false

permissions:
  contents: read
  packages: write

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        if: ${{ !inputs.dry_run }}
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/build-push-action@v6
        with:
          context: .
          push: ${{ !inputs.dry_run }}
          tags: |
            ghcr.io/foundry-linux/devbox:26.04
            ghcr.io/foundry-linux/devbox:${{ github.ref_name }}
            ghcr.io/foundry-linux/devbox:latest
          cache-from: type=gha
          cache-to:   type=gha,mode=max

      - name: Smoke-check image
        if: ${{ !inputs.dry_run }}
        run: |
          docker pull ghcr.io/foundry-linux/devbox:26.04
          for tool in \
              mame chdman ghidra ghidra-headless blender \
              vgmstream-cli f9dasm vgm-player vgm2wav task \
              cdpack iffcomp levcomp \
              dosbox-x scummvm fceux mednafen stella hatari fs-uae \
              openmsx frotz desmume \
              tiled love sdl2-config sdl3-config milkytracker \
              schism furnace mtpaint grafx2 \
              glslangValidator spirv-cross spirv-val \
              magick gm; do
            docker run --rm -e PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/usr/games:/bin:/sbin \
              ghcr.io/foundry-linux/devbox:26.04 \
              bash -c "command -v $tool" || { echo "MISSING: $tool" >&2; exit 1; }
          done
```

Note: `/usr/games` in PATH inside the image (or via the run command above) — this is the lesson from `test-retro-tools-e2e-inner.sh`, where `mame` lives at `/usr/games/mame` per Debian games convention.

## Local Taskfile (`foundry-devbox/Taskfile.yml`)

```yaml
version: '3'
tasks:
  build:
    desc: "Build the image locally (no push)"
    cmds: [docker build -t ghcr.io/foundry-linux/devbox:local .]
  run:
    desc: "Shell into the locally-built image"
    cmds: [docker run --rm -it ghcr.io/foundry-linux/devbox:local]
  smoke:
    desc: "Smoke-check tools on PATH in the locally-built image"
    cmds: [bash test/smoke-test.sh]
```

## Verification

Run each step; paste raw output in a code block below it, then PASS/FAIL.

1. **Local build succeeds and image is the expected size.**
   ```
   task -d foundry-devbox build
   docker images ghcr.io/foundry-linux/devbox:local --format '{{.Size}}'
   ```
   Expected: build exits 0; size between 3.0 GB and 3.6 GB (target ~3.3 GB).

2. **Smoke test — all tools on PATH inside the locally-built image.**
   ```
   bash foundry-devbox/test/smoke-test.sh
   ```
   Expected: prints `✓ <tool>` for each of the full check list (Foundry stack: `mame`, `chdman`, `ghidra`, `ghidra-headless`, `blender`, `vgmstream-cli`, `f9dasm`, `vgm-player`, `vgm2wav`, `task`, `cdpack`, `iffcomp`, `levcomp`; universe emulators: `dosbox-x`, `scummvm`, `fceux`, `mednafen`, `stella`, `hatari`, `fs-uae`, `openmsx`, `frotz`, `desmume`; game-dev frameworks: `tiled`, `love`, `sdl2-config`, `sdl3-config`; trackers/art: `milkytracker`, `schism`, `furnace`, `mtpaint`, `grafx2`; shader/image: `glslangValidator`, `spirv-cross`, `spirv-val`, `magick`, `gm`). Final line "N/N tools verified" with N≈35.

3. **Sync to the mirror remote.**
   ```
   task devbox-sync
   ```
   Expected: clones `foundry-linux/foundry-devbox`, overlays `foundry-devbox/`, commits + pushes (if not already up to date).

4. **Tag a release and confirm CI publishes.**
   ```
   task devbox-release TAG=v0.0.1
   gh run watch --repo foundry-linux/foundry-devbox
   ```
   Expected: workflow green; both build job and smoke step pass.

5. **Pull the published image and run a Distrobox.**
   ```
   docker pull ghcr.io/foundry-linux/devbox:26.04
   distrobox create -i ghcr.io/foundry-linux/devbox:26.04 -n foundry-test
   distrobox enter foundry-test -- bash -c 'mame -version && blender --version && task --version'
   distrobox rm -f foundry-test
   ```
   Expected: each command prints a real version line and exits 0.

6. **Universe game-dev additions usable.**
   ```
   distrobox enter foundry-test -- bash -c 'dosbox-x -version; furnace --version; tiled --version; love --version 2>&1 | head -1; sdl2-config --version; glslangValidator --version | head -1; magick -version | head -1'
   ```
   Expected: each emits a recognisable version banner; non-zero exits are OK as long as the binary launches.

## Out of scope (follow-up plans)

- **Per-game tooling** (`wf-game-create`, per-game Distrobox scaffolding, asset isolation, per-game Claude permissions, ROM library conventions) from proposal §763-836 — its own plan file to be created next.
- Maintainer-tier image (`:26.04-maintainer` with android-development + ios-development; +2.5 GB) — deferred until someone actually needs the NDK preinstalled.
- Ubuntu **multiverse** retro emulators (`vice`, `atari800`, `fbzx`, `mame-extra`, `vcmi`, `openrct2`, `fheroes2`, `exult`) — separate licensing tier; layer in via a `:26.04-multiverse` variant or document as `apt install`-after-entry if/when wanted.
- `apt.worldfoundry.org`'s builder Dockerfile still being `debian:bookworm-slim` (sibling-repo concern, already flagged earlier; not blocking Phase 2 since the metapackages we install are arch:all).
- A `release-sniper` companion image for Steam builds (proposal §587; explicitly its own initiative).
