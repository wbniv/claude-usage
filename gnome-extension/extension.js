import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CACHE_FILE = GLib.get_home_dir() + '/.cache/claude-usage/usage.json';
const USAGE_URL  = 'https://claude.ai/settings/usage';

function formatReset(reset) {
    if (!reset) return '';
    let m;
    m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
    if (m) return `resets in ⏱${m[1]}:${m[2].padStart(2, '0')}`;
    m = reset.match(/[Rr]esets? in (\d+) min/);
    if (m) return `resets in ⏱0:${m[1].padStart(2, '0')}`;
    m = reset.match(/[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
    if (m) {
        const [, day, hStr, mnStr, ap] = m;
        let h = parseInt(hStr), mn = parseInt(mnStr);
        if (ap === 'PM' && h !== 12) h += 12;
        else if (ap === 'AM' && h === 12) h = 0;
        const now = new Date();
        const wdMap = {Sun:0, Mon:1, Tue:2, Wed:3, Thu:4, Fri:5, Sat:6};
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
        if (mins < 24 * 60)
            return `resets in ⏱${Math.floor(mins / 60)}:${(mins % 60).toString().padStart(2, '0')}`;
        return `resets ${day} ${h.toString().padStart(2, '0')}:${mn.toString().padStart(2, '0')}`;
    }
    return reset;
}

function bar(pct, width = 10) {
    const filled = Math.round((pct / 100) * width);
    return '█'.repeat(Math.max(0, filled)) + '░'.repeat(Math.max(0, width - filled));
}

// pacing_pct = pct / fraction_elapsed — "% you'd hit by reset at this
// burn rate" with no cap. 100 = on pace, > 100 = over pace. Falls back
// to raw pct when reset_minutes/period unknown or fraction_elapsed is
// too small to trust (early in the period). Used only for color
// decisions; displayed numbers stay raw.
function pacingPct(meter, periodLens) {
    const pct = meter.pct;
    if (typeof pct !== 'number' || pct === 0) return pct ?? 0;
    const rm = meter.reset_minutes;
    const period = periodLens?.[meter.label];
    if (rm == null || !period) return pct;
    const fraction = 1 - rm / period;
    if (fraction <= 0.01) return pct;
    return pct / fraction;
}

function formatRows(meters, barWidth) {
    const maxLen = Math.max(0, ...meters.map(m => (m.label || '').length));
    const maxCol2 = Math.max(4, ...meters.map(m =>
        (m.count !== undefined && m.total !== undefined)
            ? `${m.count}/${m.total}`.length
            : `${m.pct ?? 0}%`.length));
    const rows = [];
    for (const m of meters) {
        const label = (m.label || '').padEnd(maxLen);
        const isExtra = m.spent !== undefined;
        let text;
        if (m.count !== undefined && m.total !== undefined) {
            const col2 = `${m.count}/${m.total}`.padStart(maxCol2);
            const col3 = ' '.repeat(barWidth);
            text = `${label}  ${col2}  ${col3}`;
        } else {
            const pct = m.pct ?? 0;
            const col2 = `${pct}%`.padStart(maxCol2);
            const col3 = bar(pct, barWidth);
            const col4 = m.reset ? `  ${formatReset(m.reset)}` : '';
            text = `${label}  ${col2}  ${col3}${col4}`;
        }
        rows.push({text, meter: m, isSub: false, isExtra});
        if (m.spent !== undefined || m.balance !== undefined) {
            const parts = [];
            if (m.spent)   parts.push(`${m.spent} spent`);
            if (m.balance) parts.push(`${m.balance} balance`);
            if (parts.length)
                rows.push({text: parts.join(' · '), meter: m, isSub: true, isExtra: true});
        }
    }
    return rows;
}

const ClaudeIndicator = GObject.registerClass(
class ClaudeIndicator extends PanelMenu.Button {
    _init(ext) {
        super._init(0.0, 'Claude Usage');
        this._ext = ext;
        this._settings = ext.getSettings('org.gnome.shell.extensions.claude-usage');
        this._monitor = null;
        this._settingsId = null;
        this._tickId = null;
        this._data = null;
        this._lastTier = 'normal';
        // Two gicons held to allow O(1) swap between normal and red-tinted panel
        // icons per tier without re-allocating per-update.
        this._iconNormal = Gio.icon_new_for_string(ext.path + '/icons/claude-22.png');
        this._iconRed    = Gio.icon_new_for_string(ext.path + '/icons/claude-22-red.png');

        this.connect('scroll-event', (_actor, event) => {
            const dir = event.get_scroll_direction();
            if ((dir === Clutter.ScrollDirection.UP ||
                 dir === Clutter.ScrollDirection.DOWN) && this._data) {
                const eligible = (this._data.meters || []).filter(m => this._isSelectable(m));
                if (eligible.length < 2) return Clutter.EVENT_STOP;
                const cur = this._settings.get_string('panel-metric');
                const idx = eligible.findIndex(m => m.label === cur);
                const delta = dir === Clutter.ScrollDirection.UP ? -1 : 1;
                const next = eligible[(idx + delta + eligible.length) % eligible.length];
                this._settings.set_string('panel-metric', next.label);
            }
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
            style: `font-size: ${this._settings.get_uint('panel-font-size')}px; margin-left: ${this._settings.get_uint('panel-label-spacing')}px;`,
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
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open) {
                this._stopFlash();
                this._flashSuppressed = true;
            }
        });

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
        const candidates = [
            GLib.get_home_dir() + '/.local/share/claude-usage/generate-icon.py',
            '/usr/share/claude-usage/generate-icon.py',
        ];
        const script = candidates.find(p =>
            Gio.File.new_for_path(p).query_exists(null));
        if (!script) return;
        try {
            Gio.Subprocess.new(
                ['python3', script, '--tier', tier],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
            );
        } catch (_) {}
    }

    _watchFile() {
        try {
            const f = Gio.File.new_for_path(CACHE_FILE);
            this._monitor = f.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._monitor.connect('changed', (_m, _f, _of, event) => {
                if (event === Gio.FileMonitorEvent.CHANGES_DONE_HINT ||
                    event === Gio.FileMonitorEvent.CREATED) {
                    this._loadData();
                }
            });
        } catch (e) {
            logError(e, 'ClaudeUsage: file monitor failed');
        }
    }

    _loadData() {
        try {
            const f = Gio.File.new_for_path(CACHE_FILE);
            const [ok, contents] = f.load_contents(null);
            if (!ok) return;
            const text = new TextDecoder().decode(contents);
            this._data = JSON.parse(text);
            this._updateDisplay();
        } catch (e) {
            logError(e, 'ClaudeUsage: failed to read cache');
        }
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
            this._label.set_style(`font-size: ${fontSize}px; margin-left: ${labelGap}px;`);
            this._statusItem.label.set_text('No data yet');
            this._metersSection.removeAll();
            return;
        }

        // Hoist threshold + colour reads so we don't pay 10–20 GSettings IPC
        // calls per render. They're already invalidated by 'changed' (which
        // re-runs _updateDisplay), so a per-render snapshot is correct.
        const tWarn = s.get_uint('threshold-warning');
        const tCrit = s.get_uint('threshold-critical');
        const popupNorm = s.get_string('popup-color-normal');
        const popupWarn = s.get_string('popup-color-warning');
        const popupCrit = s.get_string('popup-color-critical');
        const panelNorm = s.get_string('panel-color-normal');
        const panelWarn = s.get_string('panel-color-warning');
        const panelCrit = s.get_string('panel-color-critical');
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
        const anyCrit = d.meters.some(m => pacingPct(m, periodLens) >= tCrit);
        const labelColor = anyCrit ? panelCrit : panelColor;
        this._label.set_text(`${pct}%`);
        this._label.set_style(`font-size: ${fontSize}px; margin-left: ${labelGap}px; color: ${labelColor};`);

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
                const critMeter = d.meters.find(m => pacingPct(m, periodLens) >= tCrit);
                Main.notify('Claude Usage',
                    `⚠ ${critMeter?.label ?? 'A meter'} is at ${Math.round(pacingPct(critMeter, periodLens))}% pacing`);
                this._lastCritNotifyTs = now;
            }
            if (!this._flashSuppressed) this._startFlash();
        }
        this._anyCrit = anyCrit;

        const plan   = d.plan || 'Claude';
        const age    = d._timestamp ? Math.round((Date.now() / 1000 - d._timestamp) / 60) : null;
        const ageStr = age !== null ? ` · ${age < 1 ? '<1' : age}m ago` : '';

        // Tier: highest-confidence active failure signal.
        //   broken — Anthropic outage confirmed, OR scrape-fail count >= 2, OR age > 20 min
        //   stale  — age > 10 min
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
            reason = `⚠ No data in ${age} min · run claude-usage-status`;
        } else if (age !== null && age > 10) {
            tier = 'stale';
            reason = `🕐 No update in ${age} min`;
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
        this._statusItem.label.set_text(reason || `${plan}${ageStr}`);

        // Tier transition: notify on entry to stale/broken, spawn dock-icon
        // regen with the new tier. Recovery to normal also regens so the
        // dock clears the stale/red override. Notifications are rate-limited
        // to 1 per 5 min so a flapping signal (Chrome misses an alarm, catches
        // up, misses, catches up) doesn't pile toasts on top of the persistent
        // icon-color signal.
        if (tier !== this._lastTier) {
            if (tier === 'stale' || tier === 'broken') {
                const now = Date.now();
                if (now - (this._lastNotifyTs || 0) > 5 * 60 * 1000) {
                    Main.notify('Claude Usage', reason || `Status: ${tier}`);
                    this._lastNotifyTs = now;
                }
                this._spawnIconRegen(tier);
            } else if (this._lastTier === 'stale' || this._lastTier === 'broken') {
                this._spawnIconRegen('normal');
            }
            this._lastTier = tier;
        }

        const barWidth  = s.get_uint('bar-width');
        const popupSize = s.get_uint('popup-font-size');
        const popupFont = s.get_string('popup-font-family');
        const style     = `font-family: ${popupFont}; font-size: ${popupSize}px;`;

        const visibleMeters = d.meters.filter(m =>
            !(m.label?.toLowerCase().includes('sonnet') && (m.pct ?? 0) === 0));
        const rows = formatRows(visibleMeters, barWidth);

        // Popup: separator widget before extra section
        this._metersSection.removeAll();
        let sawExtra = false;
        for (const row of rows) {
            if (row.isExtra && !sawExtra) {
                this._metersSection.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                sawExtra = true;
            }
            const active = !row.isSub && row.meter === primary;
            const prefix = active ? '✴ ' : '  ';
            const eligible = !row.isSub && this._isEligible(row.meter);
            const item     = new PopupMenu.PopupMenuItem(prefix + row.text, {reactive: eligible});
            if (eligible) {
                item.connect('activate', () => {
                    this._settings.set_string('panel-metric', row.meter.label);
                });
            }
            const color = row.isSub ? popupNorm : pctColor(pacingPct(row.meter, periodLens));
            item.label.set_style(`${style} color: ${color};`);
            this._metersSection.addMenuItem(item);
        }
    }

    _startFlash() {
        this._stopFlash();
        let vis = false;
        this._flashId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            this._label.opacity = vis ? 255 : 30;
            vis = !vis;
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopFlash() {
        if (this._flashId) {
            GLib.source_remove(this._flashId);
            this._flashId = null;
        }
        this._label.opacity = 255;
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
        }
        return meters.find(m => /all/i.test(m.label ?? '') && this._isSelectable(m))
            || meters.find(m => this._isSelectable(m))
            || meters[0]
            || null;
    }

    destroy() {
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = null;
        }
        if (this._monitor) {
            this._monitor.cancel();
            this._monitor = null;
        }
        if (this._tickId) {
            GLib.source_remove(this._tickId);
            this._tickId = null;
        }
        if (this._flashId) {
            GLib.source_remove(this._flashId);
            this._flashId = null;
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
