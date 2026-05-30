// A colour picker that uses the native KDE ColorButton when available and
// degrades to a plain hex field + swatch when org.kde.kquickcontrols is not
// installed. Exposes a single `colorString` (#rrggbb) for cfg_ binding.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

RowLayout {
    id: cf
    property string colorString: "#000000"
    spacing: 8

    // Preferred: native colour button (loaded from a separate file so its
    // optional import can fail without taking down this component).
    Loader {
        id: nativeBtn
        source: Qt.resolvedUrl("ColorButtonNative.qml")
        onLoaded: {
            item.value = Qt.binding(function() { return cf.colorString })
            item.edited.connect(function(hex) { cf.colorString = hex })
        }
    }

    // Fallback: only shown if the native module is unavailable.
    RowLayout {
        visible: nativeBtn.status === Loader.Error
        spacing: 6
        Rectangle {
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
            radius: 3
            color: cf.colorString || "transparent"
            border.width: 1
            border.color: Qt.rgba(0.5, 0.5, 0.5, 0.5)
        }
        QQC2.TextField {
            Layout.preferredWidth: 100
            text: cf.colorString
            placeholderText: "#rrggbb"
            onEditingFinished: cf.colorString = text
        }
    }
}
