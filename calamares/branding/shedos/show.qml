/* ShedOS Installation Slideshow */

import QtQuick 2.15
import calamares.slideshow 1.0

Presentation {
    id: presentation

    function nextSlide() {
        presentation.goToNextSlide()
    }

    Timer {
        interval: 5000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: nextSlide()
    }

    // Slide 1: Security First
    Slide {
        Image {
            anchors.fill: parent
            source: "slides/slide1.png"
            fillMode: Image.PreserveAspectFit
        }
    }

    // Slide 2: Minimal & Powerful
    Slide {
        Image {
            anchors.fill: parent
            source: "slides/slide2.png"
            fillMode: Image.PreserveAspectFit
        }
    }

    // Slide 3: BTRFS Snapshots
    Slide {
        Image {
            anchors.fill: parent
            source: "slides/slide3.png"
            fillMode: Image.PreserveAspectFit
        }
    }

    // Slide 4: Choose Your Profile
    Slide {
        Image {
            anchors.fill: parent
            source: "slides/slide4.png"
            fillMode: Image.PreserveAspectFit
        }
    }

    // Slide 5: Lightning Fast
    Slide {
        Image {
            anchors.fill: parent
            source: "slides/slide5.png"
            fillMode: Image.PreserveAspectFit
        }
    }

    // Slide 6: Almost Ready
    Slide {
        Image {
            anchors.fill: parent
            source: "slides/slide6.png"
            fillMode: Image.PreserveAspectFit
        }
    }
}
