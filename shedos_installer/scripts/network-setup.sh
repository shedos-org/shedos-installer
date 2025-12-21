#!/bin/bash
# ShedOS Network Setup Script
# Offers to connect to WiFi via nmtui if not already connected

# Check if already connected to internet
if ping -c 1 -W 2 archlinux.org > /dev/null 2>&1; then
    echo "Already connected to internet"
    exit 0
fi

# Check if yad is available
if ! command -v yad &> /dev/null; then
    echo "yad not found, skipping WiFi dialog"
    exit 0
fi

# Ask user if they want to connect to WiFi
yad --question \
    --title="Network Connection" \
    --text="You are not connected to the internet.\n\nWould you like to connect to a WiFi network?\n\n(This step is optional - ShedOS includes all packages offline)" \
    --button="Connect to WiFi:0" \
    --button="Skip:1" \
    --width=400 \
    --center

if [ $? -eq 0 ]; then
    # Open terminal with nmtui
    if command -v kitty &> /dev/null; then
        kitty --title "WiFi Setup" nmtui-connect
    elif command -v alacritty &> /dev/null; then
        alacritty -e nmtui-connect
    else
        xterm -e nmtui-connect
    fi
fi

exit 0
