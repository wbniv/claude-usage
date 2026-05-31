import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: meterRowRoot
    property var meter: null
    property string meterColor: "#ffffff"
    property int barWidth: 10
    property string fontFamily: "monospace"
    property int fontSize: 10

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
                    ? meterColor : Qt.rgba(1, 1, 1, 0.2)
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
            color: Qt.rgba(1, 1, 1, 0.6)
            font.pixelSize: fontSize - 1
        }
    }
}
