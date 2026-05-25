import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import "lib/usage.js" as Usage

Item {
    id: full

    property var usageData: null
    property var cfg: ({})
    property double nowTick: 0
    signal selectMetric(string label)

    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.minimumHeight: Kirigami.Units.gridUnit * 10
    Layout.preferredWidth: Kirigami.Units.gridUnit * 24
    Layout.preferredHeight: contentColumn.implicitHeight + Kirigami.Units.largeSpacing * 2

    readonly property var meters: usageData ? (usageData.meters || []) : []
    readonly property var periodLens: usageData ? (usageData._period_lengths || {}) : {}
    readonly property var tierInfo: { nowTick; return Usage.deriveTier(usageData); }
    readonly property var primary: Usage.getPrimary(Usage.visibleMeters(meters), cfg.panelMetric)

    function esc(s) {
        return ("" + s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                       .replace(/ /g, " ");
    }

    // Port of extension.js:formatRows + the per-character pacing markup. Returns
    // [{markup, label, eligible, isExtra, isSub}] for the Repeater below.
    function buildRows() {
        var c = full.cfg;
        if (!c || c.tWarn === undefined) return [];
        var vis = Usage.visibleMeters(full.meters);
        var maxLen = 0, maxCol2 = 4;
        for (var i = 0; i < vis.length; i++) {
            var m = vis[i];
            maxLen = Math.max(maxLen, (m.label || "").length);
            var col2len = (m.count !== undefined && m.total !== undefined)
                ? (m.count + "/" + m.total).length : ((m.pct || 0) + "%").length;
            maxCol2 = Math.max(maxCol2, col2len);
        }
        var pad = function (s, n, end) {
            s = "" + s;
            while (s.length < n) s = end ? s + " " : " " + s;
            return s;
        };
        var rows = [];
        var width = c.barWidth || 10;
        for (var j = 0; j < vis.length; j++) {
            var mt = vis[j];
            var label = pad(mt.label || "", maxLen, true);
            var active = (mt === full.primary);
            var prefix = active ? "✴ " : "  ";
            var pacing = Usage.pacingPct(mt, full.periodLens);
            var rowColor = Usage.colorFor("empty", pacing, c);
            var isExtra = mt.spent !== undefined;
            var markup;
            if (mt.count !== undefined && mt.total !== undefined) {
                var col2c = pad(mt.count + "/" + mt.total, maxCol2, false);
                markup = "<font color=\"" + rowColor + "\">" + esc(prefix + label + "  " + col2c) + "</font>";
            } else {
                var pct = mt.pct || 0;
                var col2 = pad(pct + "%", maxCol2, false);
                var pre = prefix + label + "  " + col2 + "  ";
                var ef = Usage.elapsedFraction(mt, full.periodLens);
                var segs = Usage.pacingSegments(pct, ef, width);
                var barMarkup = "";
                for (var k = 0; k < segs.length; k++)
                    barMarkup += "<font color=\"" + Usage.colorFor(segs[k].role, pacing, c) + "\">" + segs[k].c + "</font>";
                var post = mt.reset ? ("  " + Usage.formatReset(mt.reset)) : "";
                markup = "<font color=\"" + rowColor + "\">" + esc(pre) + "</font>"
                       + barMarkup
                       + "<font color=\"" + rowColor + "\">" + esc(post) + "</font>";
            }
            rows.push({ markup: markup, label: mt.label, eligible: Usage.isEligible(mt), isExtra: isExtra, isSub: false });

            if (mt.spent !== undefined || mt.balance !== undefined) {
                var parts = [];
                if (mt.spent) parts.push(mt.spent + " spent");
                if (mt.balance) parts.push(mt.balance + " balance");
                if (parts.length)
                    rows.push({ markup: "<font color=\"" + c.popupNorm + "\">" + esc(parts.join(" · ")) + "</font>",
                                label: mt.label, eligible: false, isExtra: true, isSub: true });
            }
        }
        return rows;
    }

    readonly property var rows: { nowTick; cfg; usageData; return buildRows(); }
    readonly property int meterOpacityPct: tierInfo.tier === "broken" ? 31 : tierInfo.tier === "stale" ? 55 : 100

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        PlasmaExtras.Heading {
            level: 5
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: {
                full.nowTick;
                if (!full.usageData || !full.meters.length) return "No data yet";
                if (full.tierInfo.reason) return full.tierInfo.reason;
                var plan = full.usageData.plan || "Claude";
                var age = (typeof full.usageData._timestamp === "number")
                    ? Math.round((Date.now() / 1000 - full.usageData._timestamp) / 60) : null;
                return age !== null ? (plan + " · " + (age < 1 ? "<1" : age) + "m ago") : plan;
            }
        }

        Repeater {
            model: full.rows
            delegate: PlasmaComponents.Label {
                required property var modelData
                Layout.fillWidth: true
                textFormat: Text.RichText
                text: modelData.markup
                opacity: full.meterOpacityPct / 100
                font.family: full.cfg.popupFontFamily || "monospace"
                font.pixelSize: full.cfg.popupFontSize || 10
                MouseArea {
                    anchors.fill: parent
                    enabled: modelData.eligible && !modelData.isSub
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: full.selectMetric(modelData.label)
                }
            }
        }

        Item { Layout.fillHeight: true }

        PlasmaComponents.Button {
            Layout.fillWidth: true
            icon.name: "view-statistics"
            text: "Open Usage Page"
            onClicked: Qt.openUrlExternally("https://claude.ai/settings/usage")
        }
    }
}
