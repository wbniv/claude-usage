import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gio from 'gi://Gio';
import {ExtensionPreferences} from 'resource:///org/gnome/shell/extensions/prefs.js';

export default class ClaudeUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const page = new Adw.PreferencesPage({
            title: 'Claude Usage',
            icon_name: 'preferences-system-symbolic',
        });

        const group = new Adw.PreferencesGroup({
            title: 'Display',
            description: 'Data is fetched by ~/.local/share/claude-usage/fetch-usage.py',
        });
        page.add(group);

        // Poll interval
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
        group.add(pollRow);

        const infoGroup = new Adw.PreferencesGroup({title: 'Setup'});
        page.add(infoGroup);

        const infoRow = new Adw.ActionRow({
            title: 'First-time login',
            subtitle: 'Run: python3 ~/.local/share/claude-usage/fetch-usage.py',
        });
        infoGroup.add(infoRow);

        window.add(page);
    }
}
