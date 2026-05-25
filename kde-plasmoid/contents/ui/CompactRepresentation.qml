import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import "lib/usage.js" as Usage

MouseArea {
    id: compact

    property var usageData: null
    property var cfg: ({})
    property double nowTick: 0

    // Emitted on scroll — main.qml writes plasmoid.configuration.panelMetric.
    signal cycleMetric(string label)
    // Toggle the popup on click (we own the MouseArea, so wire it explicitly).
    signal toggleExpanded()

    Layout.minimumWidth: row.implicitWidth
    Layout.preferredWidth: row.implicitWidth

    acceptedButtons: Qt.LeftButton
    onClicked: toggleExpanded()

    // ── derived state ────────────────────────────────────────────────────
    readonly property var meters: usageData ? (usageData.meters || []) : []
    readonly property var periodLens: usageData ? (usageData._period_lengths || {}) : {}
    readonly property var tierInfo: { nowTick; return Usage.deriveTier(usageData); }

    function findMeter(kw) {
        for (var i = 0; i < meters.length; i++)
            if ((meters[i].label || "").toLowerCase().indexOf(kw) !== -1) return meters[i];
        return null;
    }

    readonly property var primary: Usage.getPrimary(Usage.visibleMeters(meters), cfg.panelMetric)
    readonly property int primaryPct: {
        if (!primary) return 0;
        if (primary.pct !== undefined) return primary.pct;
        if (primary.total) return Math.round((primary.count / primary.total) * 100);
        return 0;
    }
    readonly property string labelColor: {
        if (!primary || !cfg.tWarn) return cfg.panelNorm || "#ffffff";
        var anyCrit = meters.some(function (m) { return Usage.pacingPct(m, periodLens) >= cfg.tCrit; });
        var pacing = Usage.pacingPct(primary, periodLens);
        if (anyCrit || pacing >= cfg.tCrit) return cfg.panelCrit;
        if (pacing >= cfg.tWarn) return cfg.panelWarn;
        return cfg.panelNorm;
    }

    opacity: tierInfo.tier === "stale" ? 0.45 : 1.0

    onUsageDataChanged: ring.requestPaint()
    onCfgChanged: ring.requestPaint()
    onNowTickChanged: ring.requestPaint()

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: cfg.panelLabelSpacing !== undefined ? cfg.panelLabelSpacing : 6

        Item {
            id: ringBox
            Layout.fillHeight: true
            Layout.preferredWidth: height
            implicitWidth: Kirigami.Units.iconSizes.medium
            implicitHeight: Kirigami.Units.iconSizes.medium

            Canvas {
                id: ring
                anchors.fill: parent
                renderStrategy: Canvas.Threaded

                function drawRing(ctx, cx, cy, radius, thick, pct, color, elapsedFrac, overColor) {
                    var start = -Math.PI / 2;
                    // Track
                    ctx.beginPath();
                    ctx.lineWidth = thick;
                    ctx.strokeStyle = Qt.rgba(0, 0, 0, 0.25);
                    ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
                    ctx.stroke();
                    if (pct <= 0) return;
                    var fillAngle = start + 2 * Math.PI * (pct / 100);
                    ctx.lineCap = "butt";
                    if (elapsedFrac === null || elapsedFrac === undefined) {
                        ctx.beginPath();
                        ctx.strokeStyle = color;
                        ctx.arc(cx, cy, radius, start, fillAngle);
                        ctx.stroke();
                        return;
                    }
                    var elapsedAngle = start + 2 * Math.PI * elapsedFrac;
                    var overPacing = (pct / 100) > elapsedFrac;
                    if (overPacing && overColor) {
                        ctx.beginPath(); ctx.strokeStyle = color;
                        ctx.arc(cx, cy, radius, start, elapsedAngle); ctx.stroke();
                        ctx.beginPath(); ctx.strokeStyle = overColor;
                        ctx.arc(cx, cy, radius, elapsedAngle, fillAngle); ctx.stroke();
                        return;
                    }
                    ctx.beginPath(); ctx.strokeStyle = color;
                    ctx.arc(cx, cy, radius, start, fillAngle); ctx.stroke();
                    if (overPacing) return; // color-invariant ring (Sonnet): no tick
                    // Under/on-pace radial tick at the elapsed position.
                    var ti = radius - thick / 2, to = radius + thick / 2;
                    ctx.beginPath();
                    ctx.strokeStyle = Qt.rgba(0.55, 0.55, 0.55, 0.85);
                    ctx.lineWidth = Math.max(1.5, thick * 0.18);
                    ctx.moveTo(cx + ti * Math.cos(elapsedAngle), cy + ti * Math.sin(elapsedAngle));
                    ctx.lineTo(cx + to * Math.cos(elapsedAngle), cy + to * Math.sin(elapsedAngle));
                    ctx.stroke();
                }

                onPaint: {
                    var ctx = getContext("2d");
                    ctx.reset();
                    var w = width, cx = w / 2, cy = height / 2;
                    var thickOuter = Math.max(2, w * 0.10);
                    var thickInner = Math.max(2, w * 0.08);
                    var gap = w * 0.03;
                    var rOuter = cx - thickOuter / 2 - 1;
                    var rInner = rOuter - thickOuter / 2 - gap - thickInner / 2;

                    var allM = compact.findMeter("all");
                    var sonM = compact.findMeter("sonnet");
                    var pl = compact.periodLens;
                    var allRaw = (allM && allM.pct) || 0;
                    var sonRaw = (sonM && sonM.pct) || 0;
                    var allPacing = Usage.pacingPct(allM, pl);
                    var allElapsed = Usage.elapsedFraction(allM, pl);
                    var sonElapsed = Usage.elapsedFraction(sonM, pl);
                    var c = compact.cfg;
                    if (!c || c.weeklyGreen === undefined) return;

                    if (compact.tierInfo.tier === "broken") {
                        drawRing(ctx, cx, cy, rOuter, thickOuter, Math.max(allRaw, 100), c.weeklyRed, null, null);
                        if (sonRaw > 0)
                            drawRing(ctx, cx, cy, rInner, thickInner, Math.max(sonRaw, 100), c.weeklyRed, null, null);
                        return;
                    }
                    var overColor = allPacing >= c.tCrit ? c.weeklyRed : c.weeklyAmber;
                    drawRing(ctx, cx, cy, rOuter, thickOuter, allRaw, c.weeklyGreen, allElapsed, overColor);
                    if (sonRaw > 0)
                        drawRing(ctx, cx, cy, rInner, thickInner, sonRaw, c.sonnet, sonElapsed, null);
                }
            }

            Kirigami.Icon {
                anchors.centerIn: parent
                width: parent.width * 0.5
                height: width
                source: Qt.resolvedUrl("../icons/claude-64.png")
            }
        }

        PlasmaComponents.Label {
            id: pctLabel
            text: compact.primary ? (compact.primaryPct + "%") : "--"
            color: compact.labelColor
            font.pixelSize: cfg.panelFontSize !== undefined ? cfg.panelFontSize : 11
            verticalAlignment: Text.AlignVCenter
            Layout.alignment: Qt.AlignVCenter
        }
    }

    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function (event) {
            var eligible = compact.meters.filter(function (m) { return Usage.isSelectable(m); });
            if (eligible.length < 2) return;
            var cur = compact.cfg.panelMetric;
            var idx = -1;
            for (var i = 0; i < eligible.length; i++)
                if (eligible[i].label === cur) { idx = i; break; }
            if (idx === -1) idx = 0;
            var delta = event.angleDelta.y > 0 ? -1 : 1;
            var next = eligible[(idx + delta + eligible.length) % eligible.length].label;
            compact.cycleMetric(next);
        }
    }
}
