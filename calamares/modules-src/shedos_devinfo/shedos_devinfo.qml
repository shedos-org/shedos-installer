/* ShedOS Developer Info Module
 * Collects developer information for git configuration
 */

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import org.kde.kirigami 2.7 as Kirigami
import io.calamares.core 1.0
import io.calamares.ui 1.0

Page {
    id: devInfoPage

    property bool isNextEnabled: emailField.text.length > 0 && emailField.text.includes("@")

    header: Item {
        height: 80
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 8
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: qsTr("Developer Information")
                font.pixelSize: 24
                font.bold: true
                color: "#cdd6f4"
            }
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: qsTr("Configure your development environment")
                font.pixelSize: 14
                color: "#a6adc8"
            }
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(500, parent.width - 80)
        spacing: 24

        // Git Configuration Section
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: gitSection.height + 40
            color: "#313244"
            radius: 12

            ColumnLayout {
                id: gitSection
                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                    margins: 20
                }
                spacing: 16

                Label {
                    text: qsTr("Git Configuration")
                    font.pixelSize: 16
                    font.bold: true
                    color: "#89b4fa"
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("This information will be used to configure git globally on your system.")
                    font.pixelSize: 12
                    color: "#a6adc8"
                    wrapMode: Text.WordWrap
                }

                // Email Field
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Label {
                        text: qsTr("Email Address *")
                        font.pixelSize: 13
                        color: "#cdd6f4"
                    }

                    TextField {
                        id: emailField
                        Layout.fillWidth: true
                        placeholderText: qsTr("your.email@example.com")
                        font.pixelSize: 14
                        color: "#cdd6f4"

                        background: Rectangle {
                            color: "#1e1e2e"
                            border.color: emailField.activeFocus ? "#89b4fa" : "#45475a"
                            border.width: 2
                            radius: 6
                        }

                        onTextChanged: {
                            config.email = text
                        }
                    }

                    Label {
                        visible: emailField.text.length > 0 && !emailField.text.includes("@")
                        text: qsTr("Please enter a valid email address")
                        font.pixelSize: 11
                        color: "#f38ba8"
                    }
                }

                // GitHub Username Field (Optional)
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Label {
                        text: qsTr("GitHub Username (optional)")
                        font.pixelSize: 13
                        color: "#cdd6f4"
                    }

                    TextField {
                        id: githubField
                        Layout.fillWidth: true
                        placeholderText: qsTr("username")
                        font.pixelSize: 14
                        color: "#cdd6f4"

                        background: Rectangle {
                            color: "#1e1e2e"
                            border.color: githubField.activeFocus ? "#89b4fa" : "#45475a"
                            border.width: 2
                            radius: 6
                        }

                        onTextChanged: {
                            config.githubUsername = text
                        }
                    }
                }
            }
        }

        // Info Box
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: infoContent.height + 30
            color: "#1e1e2e"
            border.color: "#89b4fa"
            border.width: 1
            radius: 8

            RowLayout {
                id: infoContent
                anchors {
                    left: parent.left
                    right: parent.right
                    verticalCenter: parent.verticalCenter
                    margins: 15
                }
                spacing: 12

                Label {
                    text: "i"
                    font.pixelSize: 16
                    font.bold: true
                    color: "#89b4fa"

                    background: Rectangle {
                        anchors.centerIn: parent
                        width: 24
                        height: 24
                        radius: 12
                        color: "transparent"
                        border.color: "#89b4fa"
                        border.width: 2
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: qsTr("ShedOS will configure git with your name (from the previous step) and email address. You can change these settings later with 'git config'.")
                    font.pixelSize: 12
                    color: "#a6adc8"
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    // Store data in global storage
    function onActivate() {
        if (config.email) {
            emailField.text = config.email
        }
        if (config.githubUsername) {
            githubField.text = config.githubUsername
        }
    }

    function onLeave() {
        config.email = emailField.text
        config.githubUsername = githubField.text
    }
}
