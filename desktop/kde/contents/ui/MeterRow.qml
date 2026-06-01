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
                // reset_minutes = minutes-from-now snapshot (server schema);
                // refreshed each 30 s poll, so a coarse d/h/m display is fine.
                if (!meter || meter.reset_minutes === undefined || meter.reset_minutes === null) return ""
                const total = meter.reset_minutes
                if (total <= 0) return " resets soon"
                const d = Math.floor(total / 1440)
                const h = Math.floor((total % 1440) / 60)
                const m = Math.floor(total % 60)
                if (d > 0) return " resets in " + d + "d " + h + "h"
                if (h > 0) return " resets in " + h + "h " + m + "m"
                return " resets in " + m + "m"
            }
            color: Qt.rgba(_dimColor.r, _dimColor.g, _dimColor.b, 0.6)
            font.pixelSize: fontSize - 1
        }
    }
}
