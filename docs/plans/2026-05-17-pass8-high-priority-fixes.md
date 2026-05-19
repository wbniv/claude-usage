# Pass-8 High-Priority Fixes

## P8-4 — Scroll returns `EVENT_STOP` unconditionally (`extension.js:130`)

When no data is loaded or scroll direction isn't UP/DOWN, the event is consumed silently. Return `EVENT_PROPAGATE` when the condition isn't met:

```javascript
        this.connect('scroll-event', (_actor, event) => {
            const dir = event.get_scroll_direction();
            if ((dir === Clutter.ScrollDirection.UP ||
                 dir === Clutter.ScrollDirection.DOWN) && this._data) {
                const eligible = (this._data.meters || []).filter(m => this._isSelectable(m));
                if (eligible.length < 2) return Clutter.EVENT_STOP;
                const cur = this._settings.get_string('panel-metric');
                let idx = eligible.findIndex(m => m.label === cur);
                if (idx === -1) idx = 0;
                const delta = dir === Clutter.ScrollDirection.UP ? -1 : 1;
                const next = eligible[(idx + delta + eligible.length) % eligible.length];
                this._settings.set_string('panel-metric', next.label);
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
```

This also fixes **P8-5** (idx=−1 default to 0) in the same block.

## P8-6 — Icon-path race: tick clobbers `generate-icon.py`'s `Icon=` (`tooltip.py:92`)

The 60 s tick does a full read-modify-write of the `.desktop` file preserving `Icon=`. If `generate-icon.py` writes a new `Icon=` between the tick's read and replace, the tick's write overwrites it with the old (now deleted) path.

Fix: split `update_desktop` into two paths:
- When `icon_path is None` (tick path): only rewrite the `Name=` line using `re.sub` on the raw text — no full read-parse-write, just a targeted substitution.
- When `icon_path` is set (`generate-icon.py` path): keep the existing full rewrite (both `Name=` and `Icon=`).

```python
def update_desktop(meters, icon_path=None, scrape_ts=None):
    if not DESKTOP.exists():
        return
    name = format_tooltip(meters, anchor_ts=scrape_ts).replace('\n', r'\n')
    if icon_path is None:
        # Tick path: targeted Name=-only substitution avoids clobbering Icon=
        # written by a concurrent generate-icon.py invocation.
        text = DESKTOP.read_text()
        new_text = re.sub(r'^Name=.*$', f'Name={name}', text, flags=re.MULTILINE)
        if new_text == text:
            return
        tmp = DESKTOP.with_suffix(f'.desktop.tmp.{os.getpid()}.{time.time_ns()}')
        tmp.write_text(new_text)
        tmp.replace(DESKTOP)
    else:
        # generate-icon.py path: full rewrite to update both Name= and Icon=.
        lines = DESKTOP.read_text().splitlines()
        out = []
        for line in lines:
            if line.startswith('Name='):
                out.append(f'Name={name}')
            elif line.startswith('Icon='):
                out.append(f'Icon={icon_path}')
            elif line.startswith('#'):
                out.append(line)
            elif line.startswith('[') or '=' in line or line == '':
                out.append(line)
        tmp = DESKTOP.with_suffix(f'.desktop.tmp.{os.getpid()}.{time.time_ns()}')
        tmp.write_text('\n'.join(out) + '\n')
        tmp.replace(DESKTOP)
```

## Critical files
- `gnome-extension/extension.js:118–131` (P8-4 + P8-5)
- `server/tooltip.py:92–124` (P8-6)

---

# Pass-8 Critical Fixes — COMPLETE (commit `1c3d102`)

All three criticals from `docs/investigations/2026-05-17-code-review-pass8.md` fixed:

| ID | Fix |
|----|-----|
| P8‑1 | `_menuOpenId` stored; disconnected in `destroy()` — `extension.js:169,454` |
| P8‑2 | Alarm listener made `async`/`await` — `background.js:360` |
| P8‑3 | Click listener made `async`/`await` — `background.js:364` |

Pending install: `sudo dpkg -i dist/claude-usage_0.10.7_all.deb`

---

# CQ8 — Prefix tooltip with "Claude Usage  ✴  " for Activities search

**Date:** 2026-05-17  
**Status:** Complete (committed `84949aa`)

`server/tooltip.py:89`:
```python
return 'Claude Usage   ✴   ' + '   |   '.join(parts) if parts else 'Claude Usage'
```

Tooltip reads: `Claude Usage  ✴  current 72% ⏱1:23   |   all 45% Mon 09:00`  
Pending: `sudo dpkg -i dist/claude-usage_0.10.7_all.deb` to install.
