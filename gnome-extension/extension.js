import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CACHE_FILE = GLib.get_home_dir() + '/.cache/claude-usage.json';
const USAGE_URL = 'https://claude.ai/settings/usage';

function bar(pct, width = 10) {
    const filled = Math.round((pct / 100) * width);
    return '█'.repeat(Math.max(0, filled)) + '░'.repeat(Math.max(0, width - filled));
}

function pctColor(pct) {
    if (pct >= 80) return '#e03030';
    if (pct >= 50) return '#d07000';
    return '#2a9a2a';
}

const ClaudeIndicator = GObject.registerClass(
class ClaudeIndicator extends PanelMenu.Button {
    _init(ext) {
        super._init(0.0, 'Claude Usage');
        this._ext = ext;
        this._settings = ext.getSettings('org.gnome.shell.extensions.claude-usage');
        this._monitor = null;
        this._timerId = null;
        this._data = null;
        this._showSonnet = false;

        // Scroll wheel toggles panel label between All models / Sonnet only
        this.connect('scroll-event', (_actor, event) => {
            const dir = event.get_scroll_direction();
            if (dir === Clutter.ScrollDirection.UP || dir === Clutter.ScrollDirection.DOWN) {
                this._showSonnet = !this._showSonnet;
                if (this._data) this._updateDisplay();
            }
            return Clutter.EVENT_STOP;
        });

        // Panel box: icon + label
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});

        this._icon = new St.Icon({
            gicon: Gio.icon_new_for_string(ext.path + '/icons/claude-22.png'),
            icon_size: 16,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._label = new St.Label({
            text: '--',
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-size: 11px; margin-left: 4px;',
        });

        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        // Popup menu
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

        this._watchFile();
        this._loadData();

        const intervalSecs = this._settings.get_uint('poll-interval') * 60;
        this._timerId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, intervalSecs,
            () => { this._loadData(); return GLib.SOURCE_CONTINUE; }
        );
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
        } catch (_e) {
            // File absent or parse error — stay in current state
        }
    }

    _updateDisplay() {
        const d = this._data;
        if (!d || !d.meters || d.meters.length === 0) {
            this._label.set_text('--');
            this._label.set_style('font-size: 11px; margin-left: 4px;');
            this._statusItem.label.set_text('No data yet');
            this._metersSection.removeAll();
            return;
        }

        const weekly = d.meters.filter(m => m.label && !m.label.toLowerCase().includes('session'));
        const allModels = weekly.find(m => m.label?.toLowerCase().includes('all')) || weekly[0];
        const sonnet   = weekly.find(m => m.label?.toLowerCase().includes('sonnet'));
        const session  = d.meters.find(m => m.label?.toLowerCase().includes('session'));

        // Toggle: scroll wheel switches panel label between All models / Sonnet only
        const primary = (this._showSonnet && sonnet) ? sonnet : (allModels || d.meters[0]);

        const pct = primary?.pct ?? 0;
        const color = pctColor(pct);

        this._label.set_text(`${pct}%`);
        this._label.set_style(`font-size: 11px; margin-left: 4px; color: ${color};`);

        const plan = d.plan || 'Claude';
        const age = d._timestamp
            ? Math.round((Date.now() / 1000 - d._timestamp) / 60)
            : null;
        const ageStr = age !== null ? ` · ${age < 1 ? '<1' : age}m ago` : '';
        this._statusItem.label.set_text(`${plan}${ageStr}`);

        this._metersSection.removeAll();
        for (const m of d.meters) {
            const mpct = m.pct ?? 0;
            const barStr = bar(mpct);
            const reset = m.reset ? `  ${m.reset}` : '';
            const label = m.label || 'Usage';
            const active = m === primary;
            const bullet = active ? '●' : ' ';
            const line = `${bullet} ${label.padEnd(17)} ${String(mpct).padStart(3)}%  ${barStr}${reset}`;
            const item = new PopupMenu.PopupMenuItem(line, {reactive: false});
            item.label.set_style(`font-family: monospace; font-size: 10px; color: ${pctColor(mpct)};`);
            this._metersSection.addMenuItem(item);
        }
    }

    destroy() {
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = null;
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
