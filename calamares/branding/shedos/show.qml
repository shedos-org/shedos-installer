/* ShedOS installation slideshow — real screenshots of the running system. */

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

    CaptionedSlide { image: "slides/01-desktop.png";     caption: "A clean Hyprland desktop" }
    CaptionedSlide { image: "slides/02-tour.png";        caption: "A guided tour on first boot — replay with shedman tour" }
    CaptionedSlide { image: "slides/03-switcher.png";    caption: "Switch windows with Alt+Tab" }
    CaptionedSlide { image: "slides/04-keybindings.png"; caption: "Every keybinding, searchable" }
    CaptionedSlide { image: "slides/05-walker.png";      caption: "Launch apps, files, and symbols with Walker" }
    CaptionedSlide { image: "slides/07-power.png";       caption: "Lock, sleep, hibernate, or reboot from one menu" }
    CaptionedSlide { image: "slides/08-terminal.png";    caption: "A tiled terminal and file manager" }
    CaptionedSlide { image: "slides/09-tiling.png";      caption: "Tiling window management" }
    CaptionedSlide { image: "slides/10-merge.png";       caption: "Keep your config edits through upgrades — three-way merge" }
    CaptionedSlide { image: "slides/11-config.png";      caption: "Declarative system config in /etc/shedos/system.toml" }
}
