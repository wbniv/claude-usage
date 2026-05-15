import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {ExtensionPreferences} from 'resource:///org/gnome/shell/extensions/prefs.js';

const CONFIG_PATH = GLib.get_home_dir() + '/.config/claude-usage/config.json';
const ICON_SCRIPT = GLib.get_home_dir() + '/.local/share/claude-usage/generate-icon.py';

const COLOR_DEFAULTS = {
    weekly_color_green: '#8cff8c',
    weekly_color_amber: '#ffe033',
    weekly_color_red:   '#ff5933',
    sonnet_color:       '#4dbfff',
};

function readConfig() {
    try {
        const [ok, contents] = Gio.File.new_for_path(CONFIG_PATH).load_contents(null);
        if (ok)
            return {...COLOR_DEFAULTS, ...JSON.parse(new TextDecoder().decode(contents))};
    } catch (_) {}
    return {...COLOR_DEFAULTS};
}

function writeConfig(cfg) {
    try {
        GLib.mkdir_with_parents(GLib.path_get_dirname(CONFIG_PATH), 0o755);
        const bytes = new TextEncoder().encode(JSON.stringify(cfg, null, 2) + '\n');
        Gio.File.new_for_path(CONFIG_PATH).replace_contents(
            bytes, null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
    } catch (e) {
        console.warn('ClaudeUsage: failed to write config:', e);
    }
}

function regenIcon() {
    try {
        Gio.Subprocess.new(['python3', ICON_SCRIPT], Gio.SubprocessFlags.NONE);
    } catch (_) {}
}

export default class ClaudeUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const cfg = readConfig();

        const page = new Adw.PreferencesPage({
            title: 'Claude Usage',
            icon_name: 'preferences-system-symbolic',
        });

        // ── Display ──────────────────────────────────────────────────────────
        const displayGroup = new Adw.PreferencesGroup({
            title: 'Display',
            description: 'Data is fetched by the Claude Usage Tracker Chrome extension',
        });
        page.add(displayGroup);

        const adj = new Gtk.Adjustment({
            lower: 1, upper: 60, step_increment: 1,
            value: settings.get_uint('poll-interval'),
        });
        const pollRow = new Adw.SpinRow({
            title: 'File re-read interval',
            subtitle: 'Minutes between re-reading the cache file',
            adjustment: adj,
        });
        adj.connect('value-changed', () => {
            settings.set_uint('poll-interval', Math.round(adj.get_value()));
        });
        displayGroup.add(pollRow);

        // ── Dock Icon Colors ─────────────────────────────────────────────────
        const colorGroup = new Adw.PreferencesGroup({
            title: 'Dock Icon Colors',
            description: 'Ring colors saved to ~/.config/claude-usage/config.json',
        });
        page.add(colorGroup);

        const colorDefs = [
            {key: 'weekly_color_green', title: 'Weekly — low',  subtitle: 'Outer ring · < 50%'},
            {key: 'weekly_color_amber', title: 'Weekly — mid',  subtitle: 'Outer ring · 50–79%'},
            {key: 'weekly_color_red',   title: 'Weekly — high', subtitle: 'Outer ring · ≥ 80%'},
            {key: 'sonnet_color',       title: 'Sonnet ring',   subtitle: 'Inner ring'},
        ];

        for (const def of colorDefs) {
            const row = new Adw.ActionRow({title: def.title, subtitle: def.subtitle});
            const dialog = new Gtk.ColorDialog({title: def.title, modal: true});
            const btn = new Gtk.ColorDialogButton({dialog, valign: Gtk.Align.CENTER});
            const rgba = new Gdk.RGBA();
            rgba.parse(cfg[def.key] ?? '#ffffff');
            btn.set_rgba(rgba);
            btn.connect('notify::rgba', () => {
                const c = btn.get_rgba();
                cfg[def.key] = '#' + [c.red, c.green, c.blue]
                    .map(v => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
                writeConfig(cfg);
                regenIcon();
            });
            row.add_suffix(btn);
            row.set_activatable_widget(btn);
            colorGroup.add(row);
        }

        // ── Setup ────────────────────────────────────────────────────────────
        const infoGroup = new Adw.PreferencesGroup({title: 'Setup'});
        page.add(infoGroup);

        infoGroup.add(new Adw.ActionRow({
            title: 'Chrome extension',
            subtitle: 'Load unpacked from: ~/.local/share/claude-usage/chrome-extension/',
        }));
        infoGroup.add(new Adw.ActionRow({
            title: 'Config file',
            subtitle: CONFIG_PATH,
        }));

        window.add(page);
    }
}
