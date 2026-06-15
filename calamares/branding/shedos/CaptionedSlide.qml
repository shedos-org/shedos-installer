/* A full-bleed screenshot with a caption bar, used by show.qml. */

import QtQuick 2.15
import calamares.slideshow 1.0

Slide {
    property alias image: img.source
    property alias caption: label.text

    Image {
        id: img
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 32
        width: label.implicitWidth + 40
        height: label.implicitHeight + 20
        radius: 8
        color: "#cc14141f"

        Text {
            id: label
            anchors.centerIn: parent
            color: "#ffffff"
            font.pixelSize: 22
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
