# GitHub Actions CI

**Date:** 2026-05-17  
**Status:** Complete  
**Triggered by:** Pass 4–7 recurring observation — no CI on tag push

## Scope

Add a `release.yml` GitHub Actions workflow triggered on `v*.*.*` tag push. The workflow builds the `.deb` and Chrome zip, runs the smoke test, and creates the GitHub release. The local `task release` becomes a lightweight preflight (checks + tag push only) that hands off to CI.

## Changes

| File | Change |
|------|--------|
| `.github/workflows/release.yml` | New — CI workflow triggered on `v*.*.*` tag push |
| `Taskfile.yml` | Strip `deps: [build, build-chrome-zip, test-deb]` and `gh release create` from `release` task; update `desc:` |

## Workflow Design

**Runner:** `ubuntu-latest` (Docker preinstalled for smoke test)  
**Permissions:** `contents: write` (for `gh release create`)

**Docker image caching:** The prebaked `claude-usage-test:latest` image (all apt deps baked in) is saved to `/tmp/test-image.tar` and cached via `actions/cache`, keyed on `packaging/control` + `packaging/test-deb.Dockerfile`. Cache hit → `docker load` + `task build` + inline docker run (~10 s). Cache miss → `task build-test-image` (~7 min) + save tar + same test run.

The workflow inlines the docker run command rather than calling `task test-deb-fast`, because go-task's `sources:` checksum has no baseline in a fresh CI environment and would unconditionally rebuild the image even after a cache restore.

**`task release` after this change:** Runs only the preflight shell block (branch/dirty/tag-exists/version-sync checks), then `git push origin main`, `git tag`, `git push origin TAG`. No local build or gh CLI call.

## Verification

1. **YAML syntax check** — `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`

2. **Taskfile check** — `grep 'gh release' Taskfile.yml` returns nothing

3. **Live tag push** — bump versions to `0.10.7` in `packaging/control` and `chrome-extension/manifest.json`, commit, run `task release`:
   - Tag `v0.10.7` appears on GitHub
   - Actions → Release workflow run appears and goes green (~7 min cold / ~10 s warm)
   - Release page shows `.deb` and `.zip` attachments with auto-generated notes

## Outcome

`.github/workflows/release.yml` created. `Taskfile.yml` `release` task stripped of build/test/publish deps.

**Syntax check:**
```
(pending live run)
```

**`grep 'gh release' Taskfile.yml`:**
```
(pending verification)
```
