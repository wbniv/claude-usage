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
        this._data = null;
        this._wasStale = false;

        this.connect('scroll-event', (_actor, event) => {
            const dir = event.get_scroll_direction();
            if ((dir === Clutter.ScrollDirection.UP ||
                 dir === Clutter.ScrollDirection.DOWN) && this._data) {
                const eligible = (this._data.meters || []).filter(m => this._isEligible(m));
                if (eligible.length < 2) return Clutter.EVENT_STOP;
                const cur = this._settings.get_string('panel-metric');
                const idx = eligible.findIndex(m => m.label === cur);
                const next = eligible[(idx + 1) % eligible.length];
                this._settings.set_string('panel-metric', next.label);
            }
            return Clutter.EVENT_STOP;
        });

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});

        this._icon = new St.Icon({
            gicon: Gio.icon_new_for_string(ext.path + '/icons/claude-22.png'),
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

        this._watchFile();
        this._loadData();
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
        } catch (_e) {}
    }

    _updateDisplay() {
        const d = this._data;
        const s = this._settings;
        const fontSize = s.get_uint('panel-font-size');
        const labelGap = s.get_uint('panel-label-spacing');

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

        const primary = this._getPrimary(d.meters);
        const pct = primary?.pct ?? (primary?.total
            ? Math.round((primary.count / primary.total) * 100) : 0);

        const panelColor = pct >= tCrit ? panelCrit : pct >= tWarn ? panelWarn : panelNorm;
        this._label.set_text(`${pct}%`);
        this._label.set_style(`font-size: ${fontSize}px; margin-left: ${labelGap}px; color: ${panelColor};`);

        const plan   = d.plan || 'Claude';
        const age    = d._timestamp ? Math.round((Date.now() / 1000 - d._timestamp) / 60) : null;
        const stale  = age !== null && age > 30;
        const ageStr = age !== null ? ` · ${age < 1 ? '<1' : age}m ago` : '';
        this._statusItem.label.set_text(`${stale ? '⚠ ' : ''}${plan}${ageStr}`);
        if (stale && !this._wasStale)
            Main.notify('Claude Usage',
                `No update in ${age} min. Open Chrome and click the extension icon, or run claude-usage-status to diagnose.`);
        this._wasStale = stale;

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
            const mpct   = row.meter.pct ?? 0;
            const active = !row.isSub && row.meter === primary;
            const prefix = active ? '● ' : '  ';
            const eligible = !row.isSub && this._isEligible(row.meter);
            const item     = new PopupMenu.PopupMenuItem(prefix + row.text, {reactive: eligible});
            if (eligible) {
                item.connect('activate', () => {
                    this._settings.set_string('panel-metric', row.meter.label);
                });
            }
            const color = row.isSub ? popupNorm : pctColor(mpct);
            item.label.set_style(`${style} color: ${color};`);
            this._metersSection.addMenuItem(item);
        }
    }

    _isEligible(m) {
        return m.pct !== undefined ||
               (m.count !== undefined && m.total !== undefined && m.total > 0);
    }

    _getPrimary(meters) {
        const label = this._settings.get_string('panel-metric');
        if (label) {
            const found = meters.find(m => m.label === label && this._isEligible(m));
            if (found) return found;
        }
        return meters.find(m => /all/i.test(m.label ?? '') && this._isEligible(m))
            || meters.find(m => this._isEligible(m))
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
