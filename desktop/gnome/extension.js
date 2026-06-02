import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// JS-1 (pass-18, post-pass-21): single source of truth for gschema defaults.
// Generated from desktop/gnome/schemas/<schema>.xml by scripts/gen-js-defaults.py;
// CI sync check via `task lint-js-defaults` (which runs the generator with --check).
import {DEFAULTS as SCHEMA_DEFAULTS} from './_defaults.js';

const CACHE_DIR          = GLib.get_user_cache_dir() + '/claude-usage';
const CACHE_FILE         = CACHE_DIR + '/usage.json';
const NOTIF_TS_FILE      = CACHE_DIR + '/notif-ts';
const NOTIF_CRIT_TS_FILE = CACHE_DIR + '/notif-crit-ts';
const USAGE_URL          = 'https://claude.ai/settings/usage';
// EXT-2 (pass-29): status.anthropic.com 302-redirects to status.claude.com (the
// canonical Statuspage host, used by background.js + lint-security-doc.py). Point
// the user link straight at the direct host — both work today, but this matches
// the rest of the codebase and survives retirement of the anthropic.com vanity host.
const STATUS_URL         = 'https://status.claude.com/';

// Source install puts generate-icon.py under ~/.local/share; .deb under /usr/share.
// Resolve once at module load — the script location doesn't change at runtime.
// Mirrors the candidate-list probe in prefs.js + server/generate-icon.py.
const _ICON_SCRIPT_CANDIDATES = [
    GLib.get_home_dir() + '/.local/share/claude-usage/generate-icon.py',
    '/usr/share/claude-usage/generate-icon.py',
];
const ICON_SCRIPT = _ICON_SCRIPT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || null;

// Cache schema version this build understands. A future bump to the on-disk
// shape should also bump this; readers log a warning on unknown versions so
// half-state bugs from old-reader/new-writer combos are visible.
const CACHE_SCHEMA = 1;

function formatReset(reset) {
    if (!reset || typeof reset !== 'string') return '';
    let m;
    m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
    if (m) {
        // BASE-4 (2026-05-30 review): normalise total minutes so "1 hr 90 min"
        // rolls over to 2:30, never "1:90". Mirrors server/tooltip.py::parse_reset.
        const t = parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
        return `resets in ⏱${Math.floor(t / 60)}:${(t % 60).toString().padStart(2, '0')}`;
    }
    m = reset.match(/[Rr]esets? in (\d+) min/);
    if (m) {
        const t = parseInt(m[1], 10);
        return `resets in ⏱${Math.floor(t / 60)}:${(t % 60).toString().padStart(2, '0')}`;
    }
    m = reset.match(/[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
    if (m) {
        const [, day, hStr, mnStr, ap] = m;
        let h = parseInt(hStr, 10), mn = parseInt(mnStr, 10);
        if (ap === 'PM' && h !== 12) h += 12;
        else if (ap === 'AM' && h === 12) h = 0;
        const now = new Date();
        const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
        if (!(day in wdMap)) return reset;
        let ahead = (wdMap[day] - now.getDay() + 7) % 7;
        if (ahead === 0) {
            const candidate = new Date(now);
            candidate.setHours(h, mn, 0, 0);
            if (candidate <= now) ahead = 7;
        }
        const target = new Date(now);
        target.setDate(now.getDate() + ahead);
        target.setHours(h, mn, 0, 0);
        const mins = Math.floor((target - now) / 60000);
        if (mins < 12 * 60)
            return `resets in ⏱${Math.floor(mins / 60)}:${(mins % 60).toString().padStart(2, '0')}`;
        return `resets ${day} ${h.toString().padStart(2, '0')}:${mn.toString().padStart(2, '0')}`;
    }
    return reset;
}

function liveRemaining(meter, ts) {
    if (!meter || typeof meter.reset_minutes !== 'number') return null;
    const elapsed = ts ? Math.max(0, Math.floor((Date.now() / 1000 - ts) / 60)) : 0;
    return Math.max(0, meter.reset_minutes - elapsed);
}

function fmtCountdown(mins) {
    if (mins >= 24 * 60) {
        const d = Math.floor(mins / 1440);
        const h = Math.floor((mins % 1440) / 60);
        return `⏱${d}d ${h}h`;
    }
    return `⏱${Math.floor(mins / 60)}:${(mins % 60).toString().padStart(2, '0')}`;
}

function bar(pct, width = 10) {
    const filled = Math.max(0, Math.min(width, Math.round((pct / 100) * width)));
    return '█'.repeat(filled) + '░'.repeat(width - filled);
}

function fmtAge(min) {
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60);
    const m = min % 60;
    return m > 0 ? `${h} h ${m} min` : `${h} h`;
}

// pacing_pct = pct / fraction_elapsed — "% you'd hit by reset at this
// burn rate" with no cap. 100 = on pace, > 100 = over pace. Falls back
// to raw pct when reset_minutes/period unknown or too few minutes have
// elapsed for one user action to be statistical noise. Used only for
// color decisions; displayed numbers stay raw.
//
// Kept in sync by hand with server/generate-icon.py:pacing_pct.
function pacingPct(meter, periodLens) {
    const pct = meter.pct;
    if (typeof pct !== 'number' || pct === 0) return pct ?? 0;
    const rm = meter.reset_minutes;
    const period = periodLens?.[meter.label];
    if (rm == null || !period) return pct;
    const elapsed = period - rm;
    // Floor = max(15 min, 5% of period). WP-1 (pass-16 §6): the flat 15-min
    // floor was right for the 5h session bucket (15/300 = 5% elapsed → solid
    // denominator) but for 7d weekly buckets it meant any usage > ~0.14% in
    // the first 16 min paced > critical. Scaling 5% of the period gives the
    // weekly bucket an ~8.4h suppression window — long enough that one
    // browsing session early in the week doesn't flag the whole label red.
    // Session bucket: max(15, 295*0.05=14.75) = 15 — no change from 0.11.14.
    if (elapsed < Math.max(15, period * 0.05)) return pct;
    return pct / (elapsed / period);
}

// Pacing-viz (post-pass-21 port from scripts/popup-preview.py):
//   • Under-pace → tick `┊` at the elapsed-fraction position in the bar
//   • On-pace    → tick at the fill/empty boundary
//   • Over-pace  → on-pace blocks in popupNorm, over-pace blocks in tier color
// Floor mirrors pacingPct: when elapsed < max(15, period*0.05), no tick / no two-tone.

function elapsedFraction(meter, periodLens) {
    // EF-1 (pass-23): null-meter guard matching the Python twin
    // (generate-icon.py:elapsed_fraction). Sole caller passes a valid
    // meter today; the guard is defensive symmetry.
    if (!meter) return null;
    const rm = meter.reset_minutes;
    const period = periodLens?.[meter.label];
    if (rm == null || !period) return null;
    const elapsed = period - rm;
    if (elapsed < Math.max(15, period * 0.05)) return null;
    return elapsed / period;
}

function pacingSegments(pct, elapsedFrac, width) {
    pct = Math.max(0, Math.min(100, pct ?? 0));
    const fillFrac = pct / 100;
    // PVS-1 (pass-26): decide over-pace on raw fractions BEFORE rounding.
    // When fillFrac and elapsedFrac round to the same cell index, the old
    // code emitted a tick (on-pace signal) even when fillFrac > elapsedFrac.
    // E.g. pct=51, elapsedFrac=0.5, width=10 → both round to 5 → old code
    // showed a tick instead of over_pace cells.
    const overPaceRaw = elapsedFrac != null && fillFrac > elapsedFrac;
    const fill = Math.round(fillFrac * width);
    const elapsedPos = elapsedFrac != null
        ? Math.min(Math.round(elapsedFrac * width), width)
        : null;
    const segs = [];
    for (let i = 0; i < width; i++) {
        if (i < fill) {
            // When overPaceRaw and fill === elapsedPos (both rounded to the
            // same cell), color ALL filled cells over_pace — no split is
            // possible when the seam falls on the exact cell boundary.
            const overHere = overPaceRaw &&
                (elapsedPos == null || fill === elapsedPos || i >= elapsedPos);
            segs.push({c: '█', role: overHere ? 'over_pace' : 'on_pace'});
        } else {
            // Tick is suppressed when over-pace; only emit when under/on-pace.
            if (!overPaceRaw && elapsedPos != null && i === elapsedPos && fill <= elapsedPos) {
                segs.push({c: '┊', role: 'tick'});
            } else {
                segs.push({c: '░', role: 'empty'});
            }
        }
    }
    return segs;
}

function colorFor(role, pacing, cfg) {
    if (role === 'on_pace') return cfg.popupNorm;
    if (role === 'over_pace') return pacing >= cfg.tCrit ? cfg.popupCrit : cfg.popupWarn;
    if (role === 'tick') return '#888';
    // 'empty' and the row's surrounding text — tier color.
    if (pacing >= cfg.tCrit) return cfg.popupCrit;
    if (pacing >= cfg.tWarn) return cfg.popupWarn;
    return cfg.popupNorm;
}

function pangoEscape(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatRows(meters, barWidth, ts) {
    const maxLen = Math.max(0, ...meters.map(m => (m.label || '').length));
    const maxCol2 = Math.max(4, ...meters.map(m =>
        (m.count !== undefined && m.total !== undefined)
            ? `${m.count}/${m.total}`.length
            : `${m.pct ?? 0}%`.length));
    const rows = [];
    for (const m of meters) {
        const label = (m.label || '').padEnd(maxLen);
        const isExtra = m.spent !== undefined;
        // Returned fields:
        //   text — plain-text fallback (markup consumers ignore)
        //   pre  — everything before the bar (label + col2 padding)
        //   post — everything after the bar (reset hint or '')
        //   barWidth — segment count; null when there's no bar (count rows)
        // The renderer composes per-character markup over the bar between
        // pre and post. Pacing-viz port (post-pass-21).
        if (m.count !== undefined && m.total !== undefined) {
            const col2 = `${m.count}/${m.total}`.padStart(maxCol2);
            const pre = `${label}  ${col2}  `;
            const filler = ' '.repeat(barWidth);
            rows.push({text: pre + filler, pre, post: '', barWidth: null,
                       meter: m, isSub: false, isExtra});
        } else {
            const pct = m.pct ?? 0;
            const col2 = `${pct}%`.padStart(maxCol2);
            const pre = `${label}  ${col2}  `;
            const col3 = bar(pct, barWidth);
            // A 0%/unused "Current session" has no reset string — its rolling
            // window hasn't started — so show "(not started)" rather than a
            // blank tail. Weekly/extra meters always carry a reset, so this
            // only ever fires for the session bucket.
            const live = liveRemaining(m, ts);
            const post = live !== null
                ? `  resets in ${fmtCountdown(live)}`
                : m.reset
                ? `  ${formatReset(m.reset)}`
                : (pct === 0 && /session/i.test(m.label || '') ? '  (not started)' : '');
            rows.push({text: pre + col3 + post, pre, post, barWidth,
                       meter: m, isSub: false, isExtra});
        }
        if (m.spent !== undefined || m.balance !== undefined) {
            const parts = [];
            if (m.spent)   parts.push(`${m.spent} spent`);
            if (m.balance) parts.push(`${m.balance} balance`);
            if (parts.length)
                rows.push({text: parts.join(' · '), pre: parts.join(' · '),
                           post: '', barWidth: null,
                           meter: m, isSub: true, isExtra: true});
        }
    }
    return rows;
}

const ClaudeIndicator = GObject.registerClass(
class ClaudeIndicator extends PanelMenu.Button {
    _init(ext) {
        super._init(0.0, 'Claude Usage');
        this._ext = ext;
        this._settings = ext.getSettings('org.indri.claude-usage');
        this._monitor = null;
        this._settingsId = null;
        this._tickId = null;
        this._data = null;
        this._lastTier = 'normal';
        // Two gicons held to allow O(1) swap between normal and red-tinted panel
        // icons per tier without re-allocating per-update.
        this._iconNormal = Gio.icon_new_for_string(ext.path + '/icons/claude-22.png');
        this._iconRed    = Gio.icon_new_for_string(ext.path + '/icons/claude-22-red.png');

        // Debounce GSettings writes — every set_string fires `changed`
        // synchronously, which re-runs _updateDisplay (full popup rebuild +
        // pacing recompute). Trackpad inertia produces 10-20 ticks per swipe;
        // batching to one write at the end of the burst removes the CPU spike
        // without losing visual feedback (label snaps to final position).
        this.connect('scroll-event', (_actor, event) => {
            const dir = event.get_scroll_direction();
            if (!((dir === Clutter.ScrollDirection.UP || dir === Clutter.ScrollDirection.DOWN) && this._data))
                return Clutter.EVENT_PROPAGATE;
            const eligible = (this._data.meters || []).filter(m => this._isSelectable(m));
            // S-1 (pass-17): if there's nothing to cycle, don't swallow the
            // event — let it propagate so other consumers (future Shell
            // scroll semantics, coexisting extensions) aren't blocked.
            if (eligible.length < 2) return Clutter.EVENT_PROPAGATE;
            // Use the pending target if a debounce is in flight so consecutive
            // ticks chain through eligible meters; else read the committed setting.
            const cur = this._pendingMetric ?? this._settings.get_string('panel-metric');
            let idx = eligible.findIndex(m => m.label === cur);
            if (idx === -1) idx = 0;
            const delta = dir === Clutter.ScrollDirection.UP ? -1 : 1;
            this._pendingMetric = eligible[(idx + delta + eligible.length) % eligible.length].label;
            if (this._scrollTimer) GLib.source_remove(this._scrollTimer);
            this._scrollTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, () => {
                this._scrollTimer = null;
                const label = this._pendingMetric;
                this._pendingMetric = null;
                if (!this._destroyed) this._settings.set_string('panel-metric', label);
                return GLib.SOURCE_REMOVE;
            });
            return Clutter.EVENT_STOP;
        });

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});

        this._icon = new St.Icon({
            gicon: this._iconNormal,
            icon_size: this._settings.get_uint('panel-icon-size'),
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._label = new St.Label({
            text: '--',
            y_align: Clutter.ActorAlign.CENTER,
            style: `font-size: ${this._settings.get_uint('panel-font-size')}px; margin-start: ${this._settings.get_uint('panel-label-spacing')}px;`,
        });

        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._statusItem = new PopupMenu.PopupMenuItem('Loading…', {reactive: false});
        this.menu.addMenuItem(this._statusItem);

        this._metersSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._metersSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const openItem = new PopupMenu.PopupMenuItem('Open Usage Page');
        openItem.connect('activate', () => {
            Gio.AppInfo.launch_default_for_uri(USAGE_URL, null);
        });
        this.menu.addMenuItem(openItem);

        this._settingsId = this._settings.connect('changed', () => this._updateDisplay());

        // Stop flashing when the user opens the popup — they're now looking at
        // the meters. Suppress restart until critical clears and re-enters.
        this._menuOpenId = this.menu.connect('open-state-changed', (_menu, open) => {
            if (open) {
                this._stopFlash();
                this._flashSuppressed = true;
            }
        });

        this._anyCrit = false;
        this._flashSuppressed = false;
        this._statusItemLinked = false;
        this._statusItemActivateId = null;
        try {
            const [ok, bytes] = GLib.file_get_contents(NOTIF_TS_FILE);
            this._lastNotifyTs = ok ? (parseInt(new TextDecoder().decode(bytes), 10) || 0) : 0;
        } catch (_) {
            this._lastNotifyTs = 0;
        }
        try {
            const [ok, bytes] = GLib.file_get_contents(NOTIF_CRIT_TS_FILE);
            this._lastCritNotifyTs = ok ? (parseInt(new TextDecoder().decode(bytes), 10) || 0) : 0;
        } catch (_) {
            this._lastCritNotifyTs = 0;
        }
        this._watchFile();
        this._loadData();

        // Time-based stale/broken can't be triggered by cache-write events —
        // they're absence-of-write signals. A 30 s tick re-runs _updateDisplay
        // so the icon flips to ghosted grey at the 10 min threshold and red
        // at the 20 min threshold even when no fresh POST arrives.
        this._tickId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
            this._updateDisplay();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _spawnIconRegen(tier) {
        // Spawn generate-icon.py with an explicit tier override so the dock
        // icon reflects the GNOME extension's time-based tier (the script
        // itself only sees the cache and can't know how stale it is).
        if (!ICON_SCRIPT) return;
        try {
            Gio.Subprocess.new(
                ['python3', ICON_SCRIPT, '--tier', tier],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
            );
        } catch (_) {}
    }

    _watchFile() {
        try {
            const f = Gio.File.new_for_path(CACHE_FILE);
            this._monitor = f.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._monitorChangedId = this._monitor.connect('changed', (_m, _f, _of, event) => {
                if (event === Gio.FileMonitorEvent.CHANGES_DONE_HINT ||
                    event === Gio.FileMonitorEvent.CREATED) {
                    this._loadData();
                }
            });
        } catch (e) {
            console.error('ClaudeUsage: file monitor failed, retrying in 30 s', e);
            // Store the source ID so destroy() can cancel a pending retry —
            // otherwise the callback fires on a torn-down wrapper, leaking a
            // GFileMonitor and throwing on set_text against a disposed St.Label.
            this._retryId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 30, () => {
                this._retryId = null;
                this._watchFile();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _loadData() {
        // Guard the call site and the async callback against extension disable
        // mid-read: load_contents_async queues the callback on the main loop,
        // which then fires after destroy() has torn down our widgets and would
        // throw on set_text against a disposed St.Label.
        if (this._destroyed) return;
        const f = Gio.File.new_for_path(CACHE_FILE);
        // L-3 (pass-17): pass a Cancellable so destroy() can stop the I/O,
        // not just no-op the callback. Tiny cache file makes the difference
        // microscopic, but the pattern stays consistent with the rest of
        // the file's async-cleanup discipline.
        this._loadCancellable?.cancel();
        this._loadCancellable = new Gio.Cancellable();
        f.load_contents_async(this._loadCancellable, (_obj, result) => {
            if (this._destroyed) return;
            try {
                const [ok, contents] = f.load_contents_finish(result);
                if (!ok) return;
                const text = new TextDecoder().decode(contents);
                this._data = JSON.parse(text);
                // Warn once per session if the cache was written by a writer with
                // a schema version this reader doesn't understand. Older writers
                // omit _schema entirely — treat absence as v0, which we accept.
                const sv = this._data._schema;
                if (sv !== undefined && sv !== CACHE_SCHEMA && !this._schemaWarned) {
                    console.warn(`ClaudeUsage: cache _schema=${sv} but extension expects ${CACHE_SCHEMA}; fields may be misread`);
                    this._schemaWarned = true;
                }
                this._updateDisplay();
            } catch (e) {
                // CE-1 (pass-18): cancellation is the normal path when a
                // new _loadData fires while the previous read is in flight
                // (file monitor coalescing). Don't log it as an error —
                // it would spam journalctl on every rapid file change.
                if (e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    return;
                console.error('ClaudeUsage: failed to read cache', e);
                // EVC-1 (pass-26): surface a hint when the cache is unreadable
                // and we have no prior data — without this the popup shows
                // "No data yet" forever with no diagnostic.
                if (!this._data && this._statusItem)
                    this._statusItem.label.set_text(
                        '⚠ Cache unreadable — check journalctl --user -f');
            }
        });
    }

    _updateDisplay() {
        const d = this._data;
        const s = this._settings;
        const fontSize = s.get_uint('panel-font-size');
        const labelGap = s.get_uint('panel-label-spacing');
        // Live update: settings 'changed' fires _updateDisplay so a slider
        // tweak in prefs flows through without an extension reload.
        this._icon.set_icon_size(s.get_uint('panel-icon-size'));

        if (!d || !d.meters || d.meters.length === 0) {
            this._label.set_text('--');
            this._label.set_style(`font-size: ${fontSize}px; margin-start: ${labelGap}px;`);
            this._statusItem.label.set_text('No data yet');
            this._metersSection.removeAll();
            return;
        }

        // Hoist threshold + colour reads so we don't pay 10–20 GSettings IPC
        // calls per render. They're already invalidated by 'changed' (which
        // re-runs _updateDisplay), so a per-render snapshot is correct.
        const tWarn = s.get_uint('threshold-warning');
        // DR-1 (pass-17): clamp tCrit > tWarn even if the user set them via
        // gsettings CLI in the wrong order. Without this the color ladder
        // inverts silently (warning tier becomes unreachable).
        const tCrit = Math.max(s.get_uint('threshold-critical'), tWarn + 1);
        // L-7 (pass-17): popup-font-family is regex-validated (line 468);
        // colors weren't. A `gsettings set ... popup-color-normal '#fff;
        // background: red'` would inject CSS into St.set_style. Fall back to
        // schema defaults if the value isn't a clean #rrggbb.
        const safeColor = (v, fallback) =>
            /^#[0-9a-fA-F]{6}$/.test(v) ? v : fallback;
        const popupNorm = safeColor(s.get_string('popup-color-normal'),  SCHEMA_DEFAULTS.popup_color_normal);
        const popupWarn = safeColor(s.get_string('popup-color-warning'), SCHEMA_DEFAULTS.popup_color_warning);
        const popupCrit = safeColor(s.get_string('popup-color-critical'),SCHEMA_DEFAULTS.popup_color_critical);
        const panelNorm = safeColor(s.get_string('panel-color-normal'),  SCHEMA_DEFAULTS.panel_color_normal);
        const panelWarn = safeColor(s.get_string('panel-color-warning'), SCHEMA_DEFAULTS.panel_color_warning);
        const panelCrit = safeColor(s.get_string('panel-color-critical'),SCHEMA_DEFAULTS.panel_color_critical);
        const pctColor = p => p >= tCrit ? popupCrit : p >= tWarn ? popupWarn : popupNorm;
        const periodLens = d._period_lengths || {};

        const primary = this._getPrimary(d.meters);
        const pct = primary?.pct ?? (primary?.total
            ? Math.round((primary.count / primary.total) * 100) : 0);

        // pacing drives the COLOR; raw `pct` still drives the displayed text.
        const panelPacing = primary ? pacingPct(primary, periodLens) : pct;
        const panelColor = panelPacing >= tCrit ? panelCrit : panelPacing >= tWarn ? panelWarn : panelNorm;
        // If any meter is critical (even a non-primary one), force label red so
        // the user gets a signal even when watching a different metric.
        // L-8 (pass-17): scans the UNFILTERED list intentionally — we want a
        // crit signal from popup-hidden meters too (e.g. a Sonnet meter with
        // non-zero pct that's pacing > tCrit). Today Sonnet-0% rows yield
        // pacingPct=0 (short-circuit at line 88), so the visibility-filter
        // case is functionally inert; the intent is to alarm on anything.
        const anyCrit = d.meters.some(m => pacingPct(m, periodLens) >= tCrit);
        const labelColor = anyCrit ? panelCrit : panelColor;
        // Countdown: any meter at 100% shows ⏱<time-to-reset> for the soonest resetter.
        const maxedMeters = d.meters.filter(m =>
            (m.pct ?? 0) >= 100 && typeof m.reset_minutes === 'number');
        if (maxedMeters.length > 0) {
            const ts = d._timestamp ?? null;
            maxedMeters.sort((a, b) =>
                (liveRemaining(a, ts) ?? 0) - (liveRemaining(b, ts) ?? 0));
            this._label.set_text(fmtCountdown(liveRemaining(maxedMeters[0], ts) ?? 0));
        } else {
            this._label.set_text(`${pct}%`);
        }
        this._label.set_style(`font-size: ${fontSize}px; margin-start: ${labelGap}px; color: ${labelColor};`);

        // Flash management: blink the panel label when any meter enters critical.
        // Stops when the popup is opened (user has seen it), resets when pacing clears.
        if (!anyCrit) {
            if (this._anyCrit) {
                this._stopFlash();
                this._flashSuppressed = false;
            }
        } else if (!this._anyCrit) {
            const now = Date.now();
            if (now - (this._lastCritNotifyTs || 0) > 5 * 60 * 1000) {
                let critPacing = 0;
                const critMeter = d.meters.find(m => {
                    const p = pacingPct(m, periodLens);
                    if (p >= tCrit) { critPacing = p; return true; }
                    return false;
                });
                // N-1 (pass-16 §11): "is at 605% pacing" reads weirdly to
                // users who don't have a frame for the metric. Reframe as a
                // forecast — "on pace for X% by reset" — and cap the displayed
                // number at 200 since anything beyond is just noise.
                const paceDisplay = critPacing > 200 ? '>200' : Math.round(critPacing);
                Main.notify('Claude Usage',
                    `⚠ ${critMeter.label} on pace for ${paceDisplay}% by reset`);
                this._lastCritNotifyTs = now;
                try { GLib.file_set_contents(NOTIF_CRIT_TS_FILE, String(now)); } catch (_) {}
            }
            if (!this._flashSuppressed) this._startFlash();
        }
        this._anyCrit = anyCrit;

        const plan   = d.plan || 'Claude';
        // BASE-6 (2026-05-30 review): clamp to ≥ 0 so a _timestamp slightly in
        // the future (a backward clock step / NTP correction between scrape and
        // read) shows "<1m ago" rather than a negative age; it self-heals once
        // the clock catches up.
        const age    = d._timestamp ? Math.max(0, Math.round((Date.now() / 1000 - d._timestamp) / 60)) : null;
        const ageStr = age !== null ? ` · ${age < 1 ? '<1' : age}m ago` : '';

        // Tier: highest-confidence active failure signal.
        //   broken — Anthropic outage confirmed, OR scrape-fail count >= 2, OR age > 20 min
        //   stale  — age > 15 min
        //   normal — otherwise
        const astat = d._anthropic_status || {};
        const sfc   = d._scrape_fail_count || 0;
        let tier = 'normal';
        let reason = null;
        if (astat.indicator && astat.indicator !== 'none') {
            tier = 'broken';
            reason = `⚠ Anthropic reports: ${astat.description || astat.indicator}`;
        } else if (astat.claude_ai_component_status && astat.claude_ai_component_status !== 'operational') {
            tier = 'broken';
            reason = `⚠ claude.ai status: ${astat.claude_ai_component_status}`;
        } else if (sfc >= 2) {
            tier = 'broken';
            reason = `⚠ ${sfc} scrape attempts failed · run claude-usage-status`;
        } else if (age !== null && age > 20) {
            tier = 'broken';
            reason = `⚠ No data in ${fmtAge(age)} · run claude-usage-status`;
        } else if (age !== null && age > 15) {
            // 15 min ≈ one full Chrome alarm cycle (7 min) plus jitter. Tighter
            // thresholds produce spurious "No update" toasts when MV3 dormancy
            // slows an alarm; pass-13 A-2 raised this from 10 → 15.
            tier = 'stale';
            reason = `🕐 No update in ${fmtAge(age)}`;
        }

        // Per-tier panel icon + label. Drop the ⚠ glyph prefix from the
        // label — the icon's color change is the strong signal now.
        if (tier === 'broken') {
            this._icon.gicon = this._iconRed;
            this._icon.opacity = 255;
        } else if (tier === 'stale') {
            this._icon.gicon = this._iconNormal;
            this._icon.opacity = 100;   // ~40% — ghosted
        } else {
            this._icon.gicon = this._iconNormal;
            this._icon.opacity = 255;
        }
        // Make _statusItem a clickable link only when Anthropic itself reports
        // a problem — scrape-failure and age-timeout broken cases are local
        // issues where status.claude.com wouldn't have relevant information.
        const wantLink = tier === 'broken' &&
            ((astat.indicator && astat.indicator !== 'none') ||
             (astat.claude_ai_component_status && astat.claude_ai_component_status !== 'operational'));
        // Append ↗ when the row is a link so it's visually distinct from plain status text.
        this._statusItem.label.set_text(
            (reason || `${plan}${ageStr}`) + (wantLink ? ' ↗' : ''));
        if (wantLink !== this._statusItemLinked) {
            this._statusItem.reactive = wantLink;
            if (wantLink) {
                this._statusItemActivateId = this._statusItem.connect('activate', () => {
                    Gio.AppInfo.launch_default_for_uri(STATUS_URL, null);
                    this.menu.close();
                });
            } else if (this._statusItemActivateId) {
                this._statusItem.disconnect(this._statusItemActivateId);
                this._statusItemActivateId = null;
            }
            this._statusItemLinked = wantLink;
        }

        // Tier transition: notify on entry to stale/broken, spawn dock-icon
        // regen with the new tier. Recovery to normal also regens so the
        // dock clears the stale/red override. Notifications are rate-limited
        // to 1 per 5 min so a flapping signal (Chrome misses an alarm, catches
        // up, misses, catches up) doesn't pile toasts on top of the persistent
        // icon-color signal.
        if (tier !== this._lastTier) {
            // Only toast on broken — stale's icon-ghosting is already a visible
            // signal and a toast on top of every MV3-jitter-induced stale tick
            // adds noise without info. All transitions still regen the dock icon.
            if (tier === 'broken') {
                const now = Date.now();
                if (now - (this._lastNotifyTs || 0) > 5 * 60 * 1000) {
                    // DIFF-1 (2026-05-30 review): getSystemSource() and the
                    // object-form Notification ctor are GNOME 46+. metadata.json
                    // still declares "45", where the old code threw — wedging
                    // _updateDisplay every tick (no icon regen, no meter render).
                    // Feature-detect for the rich (action-button) path; fall back
                    // to a plain Main.notify on 45. The try/catch is belt-and-
                    // suspenders so a notify failure can never again skip the
                    // _lastNotifyTs/_spawnIconRegen/_lastTier tail below.
                    try {
                        if (typeof MessageTray.getSystemSource === 'function') {
                            const _src = MessageTray.getSystemSource();
                            const _notif = new MessageTray.Notification({
                                source: _src,
                                title: 'Claude Usage',
                                body: reason || 'Service disruption detected',
                                isTransient: true,
                            });
                            // EXT-1 (pass-29): only offer "View Status Page" for an
                            // Anthropic-reported outage — same gate as the popup
                            // status-item link (wantLink). For local-only broken
                            // causes (scrape-fail, age-timeout) the status page has
                            // no relevant info, so the action button would mislead.
                            if (wantLink) {
                                _notif.addAction('View Status Page', () => {
                                    Gio.AppInfo.launch_default_for_uri(STATUS_URL, null);
                                });
                            }
                            _src.addNotification(_notif);
                        } else {
                            Main.notify('Claude Usage', reason || 'Service disruption detected');
                        }
                    } catch (e) {
                        console.warn('claude-usage: notification failed:', e.message);
                    }
                    this._lastNotifyTs = now;
                    try { GLib.file_set_contents(NOTIF_TS_FILE, String(now)); } catch (_) {}
                }
                this._spawnIconRegen(tier);
            } else if (tier === 'stale') {
                this._spawnIconRegen(tier);
            } else if (this._lastTier === 'stale' || this._lastTier === 'broken') {
                this._spawnIconRegen('normal');
            }
            this._lastTier = tier;
        }

        const barWidth  = s.get_uint('bar-width');
        const popupSize = s.get_uint('popup-font-size');
        const rawFont   = s.get_string('popup-font-family');
        const popupFont = /^[\w\s,'"-]+$/.test(rawFont) ? rawFont : 'monospace';
        const style     = `font-family: ${popupFont}; font-size: ${popupSize}px;`;
        const meterOpacity = tier === 'broken' ? 80 : tier === 'stale' ? 140 : 255;

        const visibleMeters = d.meters.filter(m =>
            !(m.label?.toLowerCase().includes('sonnet') && (m.pct ?? 0) === 0));
        const rows = formatRows(visibleMeters, barWidth, d._timestamp);

        // UX-1 (pass-26): skip removeAll() + rebuild when the popup is open
        // and data hasn't changed. Without this, every 30 s tick destroyed
        // and recreated all PopupMenuItems even while the user was reading —
        // causing visible flicker and lost hover state.
        const _menuFp = JSON.stringify({
            ts: d._timestamp, tier, barWidth, popupSize, rawFont,
            popupNorm, popupWarn, popupCrit, tWarn, tCrit,
            primary: primary?.label ?? '',
            meterKey: visibleMeters.map(m =>
                // EXT-3 (pass-29): include count/total/spent/balance so a held-open
                // popup refreshes a count/extra row that changes while pct rounds
                // to the same value (e.g. 100/201 → 100/200, both 50%).
                `${m.label}:${m.pct ?? 0}:${m.reset_minutes ?? ''}:${m.count ?? ''}/${m.total ?? ''}:${m.spent ?? ''}:${m.balance ?? ''}`).join(','),
        });
        if (this._lastMenuFp === _menuFp && this.menu.isOpen) return;
        this._lastMenuFp = _menuFp;
        // Popup: separator widget before extra section
        this._metersSection.removeAll();
        let sawExtra = false;
        const cfg = {tWarn, tCrit, popupNorm, popupWarn, popupCrit};
        for (const row of rows) {
            if (row.isExtra && !sawExtra) {
                this._metersSection.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                sawExtra = true;
            }
            const active = !row.isSub && row.meter === primary;
            const prefix = active ? '✴ ' : '  ';
            const eligible = !row.isSub && this._isEligible(row.meter);
            const item     = new PopupMenu.PopupMenuItem(prefix + row.text, {reactive: eligible});
            item.opacity = meterOpacity;
            if (eligible) {
                item.connect('activate', () => {
                    this._settings.set_string('panel-metric', row.meter.label);
                });
            }
            // Pacing-viz markup (post-pass-21 port). Sub-rows render in
            // popupNorm; bar cells get per-character colors via Pango spans;
            // surrounding text (prefix/label/col2/reset) gets the row's
            // tier color.
            const pacing = pacingPct(row.meter, periodLens);
            const rowColor = row.isSub ? popupNorm : colorFor('empty', pacing, cfg);
            let markup;
            if (row.isSub || row.barWidth == null) {
                markup = `<span foreground="${rowColor}">${pangoEscape(prefix + row.text)}</span>`;
            } else {
                const ef = elapsedFraction(row.meter, periodLens);
                const segs = pacingSegments(row.meter.pct ?? 0, ef, row.barWidth);
                const barMarkup = segs.map(s =>
                    `<span foreground="${colorFor(s.role, pacing, cfg)}">${s.c}</span>`
                ).join('');
                markup = `<span foreground="${rowColor}">${pangoEscape(prefix + row.pre)}</span>`
                       + barMarkup
                       + `<span foreground="${rowColor}">${pangoEscape(row.post)}</span>`;
            }
            item.label.clutter_text.set_markup(markup);
            // set_style retains font sizing/family; color is overridden by
            // markup spans above, so we drop `color:` from the style string.
            item.label.set_style(style);
            this._metersSection.addMenuItem(item);
        }
    }

    _startFlash() {
        this._stopFlash();
        let vis = false;
        // Pass-17 L-1: guard widget write on _destroyed. Same pattern as every
        // other long-lived async source in this file. Window is microseconds
        // — destroy() removes the source, but a tick already dispatched to
        // the main loop can fire before _label is disposed.
        this._flashId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            if (this._destroyed) return GLib.SOURCE_REMOVE;
            this._label.opacity = vis ? 255 : 30;
            vis = !vis;
            return GLib.SOURCE_CONTINUE;
        });
    }

    // LC-3 (pass-19): reachable from three contexts —
    //   • normal flash-state transition (_anyCrit cleared)
    //   • _startFlash (cleans up any previous flash before starting a new one)
    //   • destroy() (via LC-2; _destroyed is already true here)
    // The L-6 guard handles the destroy case; the cleanup is idempotent
    // (no-op when _flashId is null).
    _stopFlash() {
        if (this._flashId) {
            GLib.source_remove(this._flashId);
            this._flashId = null;
        }
        // L-6 sibling: same _destroyed guard for the cleanup write.
        if (!this._destroyed) this._label.opacity = 255;
    }

    _isEligible(m) {
        return m.pct !== undefined ||
               (m.count !== undefined && m.total !== undefined && m.total > 0);
    }

    // _isSelectable: which meters can be the panel's primary metric. Layers
    // the Sonnet-0% popup-hide rule on top of structural eligibility so the
    // panel doesn't show "0%" for a meter the popup has filtered out.
    _isSelectable(m) {
        if (m.label?.toLowerCase().includes('sonnet') && (m.pct ?? 0) === 0) return false;
        return this._isEligible(m);
    }

    _getPrimary(meters) {
        const label = this._settings.get_string('panel-metric');
        if (label) {
            const found = meters.find(m => m.label === label && this._isSelectable(m));
            if (found) return found;
            // Defer the clear via idle_add — GSettings dispatches the 'changed'
            // signal synchronously inside set_string(), which would re-enter
            // _updateDisplay() and trigger a duplicate render in the same tick.
            // Guarded so a clear in flight doesn't queue a second clear.
            // LC-1 (pass-17): store the source ID so destroy() can cancel it.
            // L-9 (pass-17), LL-1 (pass-18): two ordering invariants inside
            // this callback are load-bearing for re-entrance correctness:
            //   • `_clearMetricIdleId = null` MUST come BEFORE set_string —
            //     set_string fires 'changed' synchronously and re-enters
            //     _updateDisplay → _getPrimary; clearing the id first means
            //     re-entry can't see a stale handle.
            //   • `_clearingMetric = false` MUST also come BEFORE set_string —
            //     otherwise the re-entrant _getPrimary skips its own clear,
            //     locking the orphan-recovery path forever.
            if (!this._clearingMetric) {
                this._clearingMetric = true;
                this._clearMetricIdleId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                    this._clearMetricIdleId = null;
                    if (this._destroyed) return GLib.SOURCE_REMOVE;
                    this._clearingMetric = false;
                    this._settings.set_string('panel-metric', '');
                    return GLib.SOURCE_REMOVE;
                });
            }
        }
        return meters.find(m => /all/i.test(m.label ?? '') && this._isSelectable(m))
            || meters.find(m => this._isSelectable(m))
            || meters[0]
            || null;
    }

    destroy() {
        // Set first so any async callback racing the cancel-and-disconnect
        // dance below sees _destroyed === true and bails before touching
        // disposed widgets.
        this._destroyed = true;
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = null;
        }
        if (this._monitor) {
            // LC-1 (pass-26): disconnect the changed signal before cancel so
            // any already-queued main-loop dispatch can't fire against a
            // disposed indicator. Small per-session-lock leak without this.
            if (this._monitorChangedId) {
                this._monitor.disconnect(this._monitorChangedId);
                this._monitorChangedId = null;
            }
            this._monitor.cancel();
            this._monitor = null;
        }
        if (this._tickId) {
            GLib.source_remove(this._tickId);
            this._tickId = null;
        }
        // LC-2 (pass-18): _stopFlash() already source_remove's _flashId and
        // carries L-6's _destroyed guard for the opacity write. Inlining a
        // partial copy here drifted from the helper.
        this._stopFlash();
        if (this._retryId) {
            GLib.source_remove(this._retryId);
            this._retryId = null;
        }
        if (this._scrollTimer) {
            GLib.source_remove(this._scrollTimer);
            this._scrollTimer = null;
        }
        // LC-1 (pass-17): the orphan-panel-metric clearer's idle source.
        if (this._clearMetricIdleId) {
            GLib.source_remove(this._clearMetricIdleId);
            this._clearMetricIdleId = null;
        }
        // L-3 (pass-17): cancel the in-flight cache read.
        if (this._loadCancellable) {
            this._loadCancellable.cancel();
            this._loadCancellable = null;
        }
        if (this._menuOpenId) {
            this.menu.disconnect(this._menuOpenId);
            this._menuOpenId = null;
        }
        if (this._statusItemActivateId) {
            this._statusItem.disconnect(this._statusItemActivateId);
            this._statusItemActivateId = null;
        }
        super.destroy();
    }
});

export default class ClaudeUsageExtension extends Extension {
    enable() {
        this._indicator = new ClaudeIndicator(this);
        Main.panel.addToStatusArea('claude-usage', this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
