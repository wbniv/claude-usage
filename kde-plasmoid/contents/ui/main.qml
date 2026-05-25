import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as P5Support
import "lib/usage.js" as Usage

PlasmoidItem {
    id: root

    // Cache schema version this front end understands. Mirrors
    // extension.js:CACHE_SCHEMA — warn once if a writer used a newer shape.
    readonly property int cacheSchema: 1
    property bool schemaWarned: false

    // Parsed usage.json, or null until the first successful read.
    property var usageData: null

    // Snapshot of config, colors normalised to "#rrggbb" strings (KConfigXT
    // Color entries hand QML a QColor; usage.js wants strings). Re-evaluates
    // when any referenced configuration key changes.
    readonly property var cfg: ({
        tWarn: plasmoid.configuration.thresholdWarning,
        tCrit: Math.max(plasmoid.configuration.thresholdCritical,
                        plasmoid.configuration.thresholdWarning + 1),
        popupNorm: Usage.toHex(plasmoid.configuration.popupColorNormal),
        popupWarn: Usage.toHex(plasmoid.configuration.popupColorWarning),
        popupCrit: Usage.toHex(plasmoid.configuration.popupColorCritical),
        panelNorm: Usage.toHex(plasmoid.configuration.panelColorNormal),
        panelWarn: Usage.toHex(plasmoid.configuration.panelColorWarning),
        panelCrit: Usage.toHex(plasmoid.configuration.panelColorCritical),
        weeklyGreen: Usage.toHex(plasmoid.configuration.weeklyColorGreen),
        weeklyAmber: Usage.toHex(plasmoid.configuration.weeklyColorAmber),
        weeklyRed: Usage.toHex(plasmoid.configuration.weeklyColorRed),
        sonnet: Usage.toHex(plasmoid.configuration.sonnetColor),
        barWidth: plasmoid.configuration.barWidth,
        panelFontSize: plasmoid.configuration.panelFontSize,
        popupFontSize: plasmoid.configuration.popupFontSize,
        popupFontFamily: plasmoid.configuration.popupFontFamily,
        panelIconSize: plasmoid.configuration.panelIconSize,
        panelMetric: plasmoid.configuration.panelMetric
    })

    // The plasmoid reads the SAME cache the GNOME extension reads — it does
    // not hit the local HTTP port. A `cat` on a short interval is plenty given
    // the data only refreshes every few minutes. Resolving the path inside the
    // shell honours $XDG_CACHE_HOME exactly like server/usage-server.py.
    readonly property string cacheCmd:
        "cat \"${XDG_CACHE_HOME:-$HOME/.cache}/claude-usage/usage.json\" 2>/dev/null"

    P5Support.DataSource {
        id: cacheReader
        engine: "executable"
        connectedSources: []
        onNewData: function (sourceName, data) {
            var stdout = (data["stdout"] || "").trim();
            disconnectSource(sourceName);   // one-shot; the Timer re-runs it
            if (stdout.length === 0) return; // missing/empty cache — keep prior data
            try {
                var parsed = JSON.parse(stdout);
                var sv = parsed._schema;
                if (sv !== undefined && sv !== root.cacheSchema && !root.schemaWarned) {
                    console.warn("ClaudeUsage: cache _schema=" + sv +
                                 " but plasmoid expects " + root.cacheSchema +
                                 "; fields may be misread");
                    root.schemaWarned = true;
                }
                root.usageData = parsed;
            } catch (e) {
                console.warn("ClaudeUsage: failed to parse usage.json:", e);
            }
        }
    }

    Timer {
        interval: 5000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: cacheReader.connectSource(root.cacheCmd)
    }

    // A 30 s tick re-derives the tier so the icon goes stale/broken on the
    // absence-of-write signal (age) even when no fresh cache arrives — the
    // time-based half of extension.js's tier logic. Bumping `now` invalidates
    // the deriveTier bindings in the representations.
    property double now: Date.now()
    Timer {
        interval: 30000
        repeat: true
        running: true
        onTriggered: root.now = Date.now()
    }

    // Hover tooltip (port of tooltip.py:format_tooltip).
    toolTipMainText: "Claude Usage"
    toolTipSubText: {
        root.now; // re-evaluate on tick
        if (!usageData || !usageData.meters) return "No data yet";
        var s = Usage.tooltipSummary(usageData.meters);
        return s.length ? s : (usageData.plan || "Claude");
    }

    preferredRepresentation: compactRepresentation

    compactRepresentation: CompactRepresentation {
        usageData: root.usageData
        cfg: root.cfg
        nowTick: root.now
        onCycleMetric: function (label) { plasmoid.configuration.panelMetric = label; }
        onToggleExpanded: root.expanded = !root.expanded
    }

    fullRepresentation: FullRepresentation {
        usageData: root.usageData
        cfg: root.cfg
        nowTick: root.now
        onSelectMetric: function (label) { plasmoid.configuration.panelMetric = label; }
    }
}
