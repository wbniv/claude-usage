import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: meterRowRoot
    property var meter: null
    property string meterColor: "#ffffff"
    property int barWidth: 10
    property string fontFamily: "monospace"
    property int fontSize: 10
    property real timestamp: 0
    property int nowTick: 0

    // KQ-6 (pass-29): empty-bar cells + the reset hint were hardcoded white
    // (Qt.rgba(1,1,1,…)) — invisible on a light Plasma theme. Derive both from
    // the theme text colour so they read on light and dark alike.
    readonly property color _dimColor: Kirigami.Theme.textColor

    spacing: 1

    RowLayout {
        spacing: 8

        PlasmaComponents3.Label {
            text: meter ? meter.label : ""
            color: meterColor
            font.family: fontFamily
            font.pixelSize: fontSize
            Layout.fillWidth: true
        }

        PlasmaComponents3.Label {
            text: meter ? Math.round(meter.pct) + "%" : ""
            color: meterColor
            font.family: fontFamily
            font.pixelSize: fontSize
        }
    }

    // Usage bar
    RowLayout {
        spacing: 0
        Repeater {
            model: barWidth
            Rectangle {
                width: 8
                height: 4
                radius: 1
                color: meter && (index / barWidth * 100) < (meter.pct || 0)
                    ? meterColor : Qt.rgba(_dimColor.r, _dimColor.g, _dimColor.b, 0.2)
            }
        }

        PlasmaComponents3.Label {
            text: {
                var _ = nowTick  // force re-eval on each tick
                if (!meter || meter.reset_minutes === undefined || meter.reset_minutes === null) return ""
                const elapsed = timestamp ? Math.max(0, Math.floor((Date.now() / 1000 - timestamp) / 60)) : 0
                const live = Math.max(0, meter.reset_minutes - elapsed)
                if (live <= 0) return " resets soon"
                const d = Math.floor(live / 1440)
                const h = Math.floor((live % 1440) / 60)
                const m = Math.floor(live % 60)
                if (d > 0) return " resets in " + d + "d " + h + "h"
                if (h > 0) return " resets in " + h + "h " + m + "m"
                return " resets in " + m + "m"
            }
            color: Qt.rgba(_dimColor.r, _dimColor.g, _dimColor.b, 0.6)
            font.pixelSize: fontSize - 1
        }
    }
}
