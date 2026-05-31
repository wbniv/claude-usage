// Native KDE colour picker. Isolated in its own file so the optional
// org.kde.kquickcontrols import lives behind a Loader — if the module is
// absent, ColorField.qml's Loader reports an error and falls back to a plain
// hex field instead of the whole config page failing to load.
import QtQuick
import org.kde.kquickcontrols as KQuickControls

KQuickControls.ColorButton {
    id: btn

    // `value` (hex string) is driven by the parent; `edited` fires only when the
    // user accepts a colour in the dialog. We set `color` imperatively (not via a
    // binding) so the dialog's own write to `color` doesn't clobber a binding.
    property string value
    signal edited(string hex)

    onValueChanged: if (value && value !== color.toString()) color = value
    Component.onCompleted: if (value) color = value
    onAccepted: edited(color.toString())
}
