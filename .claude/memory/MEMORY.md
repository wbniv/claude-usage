# Memory Index

- [1-sentence summaries; targeted lookups before broad exploration](feedback_token_economy.md) — grep/find first; Explore agent only if that fails; 1 sentence end-of-turn, not 2
- [After build, show install command with ./](feedback_post_build_instructions.md) — `sudo dpkg -i ./dist/claude-usage_<VERSION>_all.deb` — apt needs `./` prefix or it misreads as package name
- [Logout is disruptive — exhaust static checks first](feedback_logout_disruption.md) — never suggest logout/login as an easy step; run all verifiable checks before recommending it
- [Read project docs before debugging](feedback_read_docs_first.md) — README.md and MANUAL.md document the architecture; read them before assuming how anything works
- [Render PNG popup preview instead of logout/login](feedback_popup_preview_render.md) — when extension.js changes need Wayland reload, render a PIL mockup using live data + GSettings instead of asking user to log out
- [Next session: test .deb install](project_deb_test.md) — source install removed, v0.9 .deb built, user logging out to test clean .deb install + selectable panel metric feature
- [Use semver patch bumps for small fixes](feedback_semver_patch_bumps.md) — 0.9 → 0.9.1, not 0.10
- [No PRs on this solo repo](feedback_no_pr_solo_repo.md) — "push" means push the branch/merge to main; only open a PR if explicitly asked
- [Public email is will@biohack.net](user_email_preference.md) — use for Maintainer/contact fields, not wbnorris@gmail.com
- [QEMU runs ≥1024x768](feedback_qemu_resolution.md) — set virtio-gpu xres/yres (prefer 1280x800) for all VM boots; default mode is too cramped

<!-- BEGIN GLOBAL MEMORY (managed by claude-housekeeping; do not edit) -->

## User (inherited from ~)

- [User profile](user_profile.md) — Will's role, setup, and desktop/dev preferences
- [Mammouth.ai subscription](user_mammouth_subscription.md) — €20/mo Mammouth.ai Standard: multi-model API (GPT-4o, Claude, Gemini, Mistral, Llama) at api.mammouth.ai/v1

## Project (inherited from ~)

- [Home/SRC layout post-reformat](home_src_layout.md) — Projects moved ~/SRC/<name> → ~/<name> post-reformat; projects.json + hook-runner still assume ~/SRC (hook-runner patched via symlink)
- [Laptop comparison investigation](laptop-comparison-investigation.md) — 32GB eBay laptop compare; deliverable done in docs/investigations; open TODO = send #7 pick link (phone/Trello/email all blocked)

## Feedback (inherited from ~)

- [Host tooling is dbox-only](host-tooling-dbox-only.md) — no node/terraform on host, only podman; use bin/dbox
- [Setup flows are tasks](setup-flows-are-tasks.md) — provisioning always via task setup/scripts/setup.sh, never manual instructions
- [Always Astro + Tailwind](feedback_always_astro_tailwind.md) — Always scaffold Astro + Tailwind 4 + @theme tokens even when design is undecided; path choice is infra, not framework
- [Bangkok cost estimates](feedback_bangkok_cost_estimates.md) — Default lower on Bangkok cost estimates; verify against Lalamove/Grab/Makro/local norms, not Western/expat-tier defaults
- [Commit scope](feedback_commit_scope.md) — "Commit the others" means the files just enumerated, not everything git status shows; auto-mode doesn't expand scope
- [Excluded providers](feedback_excluded_providers.md) — Don't recommend Facebook/Meta (except WhatsApp) or Oracle as providers anywhere; Oracle's "Always Free" ARM tier is mostly fictional (capacity-starved)
- [Legacy encoding edit corruption](feedback_legacy_encoding_edit_corruption.md) — Edit/Write round-trip through UTF-8 and silently corrupt non-UTF-8 high bytes (CP437, Latin-1, etc.) into U+FFFD; edit byte-safely (sed/perl/python) on legacy-encoded files
- [Markdown renderer drops autolinks](feedback_md_renderer_no_autolinks.md) — md-to-pdf.sh silently drops `<url>` autolinks; always use `[url](url)` form
- [Don't speculate](feedback_no_speculation.md) — Verify before advising: RDAP for domains, file reads for config, the screenshot already on screen — don't list generic "common causes" when state is fetchable
- [Node 24 everywhere](feedback_node24_everywhere.md) — Always use Node 24 on all supported platforms; confirmed: GitHub Actions, Codemagic.io
- [Prefer the proper fix](feedback_prefer_proper_fix.md) — When offering fix-scope options, default to the proper/architectural one. Don't lead with the minimal fix as "recommended"
- [Public vs internal surfaces](feedback_public_vs_internal_surfaces.md) — Public marketing pages (colophon, homepage) describe visible craft — never internal infra (repo URLs, predecessor projects, deploy pipeline, IaC paths)
- [Run task md](feedback_run_task_md.md) — After writing/editing any .md file, run `task md -- {filename}` to preview in browser; never run on non-markdown files
- [Seed, don't clone](feedback_seed_dont_clone.md) — Seeding a new site from an existing one + swapping wordmark/color isn't enough — the source's visual fingerprint carries through. Ship distinctive elements with the seed, not after
- [Tooling choices](feedback_tooling_choices.md) — Prefer hand-rolled over integration libs when Will already does the pattern manually (e.g., PWA); convert content to Markdown upfront, not "start HTML, migrate later"
- [Use task tracking](feedback_use_task_tracking.md) — Reach for TaskCreate/TaskUpdate proactively on multi-step work; don't wait for the auto-reminder
- [Wayland keybindings](feedback_wayland_keybindings.md) — How held modifiers combine with ydotool on GNOME Wayland; architecture for tab switching across apps
- [WezTerm Flatpak CLI](feedback_wezterm_flatpak.md) — Use flatpak enter + GUI socket (not flatpak run or mux socket) for WezTerm CLI access
- [Audit-deferrals hook force-adds TODO](audit-deferrals-hook-force-adds-todo.md) — audit-plan-deferrals used to git-add the whole TODO.md into a plan commit — FIXED in python-tui-lib 4f88186
- [Close net-negative findings, don't defer](close-net-negative-findings-not-defer.md) — When a measurement shows a change is net-negative, close it as a recorded negative result — don't carry it as deferred/future work
- [Investigations on throwaway branches](investigations-on-throwaway-branches.md) — Run exploratory/measurement work on disposable git branches/worktrees, never on main's working copy
- [No false-choice questions](no-false-choice-questions.md) — Don't pose AskUserQuestion forks where all options collapse to the same next action or one is the obvious default — just act and state it
- [Fix inaccuracies as you find them](fix-inaccuracies-as-you-find-them.md) — Stale counts, colliding numbers, contradictory docs: fix in the same pass and say so; don't report-and-ask

<!-- END GLOBAL MEMORY -->
