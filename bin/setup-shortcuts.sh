#!/bin/bash
# Generate config snippets for Global Shortcut (Alt+Space -> ccb up)

CCB_BIN="$(dirname "$0")/../ccb"
CCB_BIN=$(readlink -f "$CCB_BIN")

echo "========================================================"
echo "CCB Global Shortcut Setup Guide"
echo "========================================================"
echo "Proposed Hotkey: Alt+Space"
echo "Command:         $CCB_BIN up"
echo ""

# Detect DE
DE="${XDG_CURRENT_DESKTOP}"
if [ -z "$DE" ]; then
    DE="${DESKTOP_SESSION}"
fi

echo "Detected Desktop Environment: ${DE:-Unknown}"
echo ""

echo "--------------------------------------------------------"
echo "GNOME / Ubuntu"
echo "--------------------------------------------------------"
echo "Run the following commands to set up the shortcut:"
echo ""
echo "gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ name 'CCB Up'"
echo "gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ command '$CCB_BIN up'"
echo "gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ binding '<Alt>space'"
echo "gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings \"['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']\""
echo ""

echo "--------------------------------------------------------"
echo "KDE Plasma"
echo "--------------------------------------------------------"
echo "Open 'System Settings' -> 'Shortcuts' -> 'Custom Shortcuts'."
echo "1. Edit -> New -> Global Shortcut -> Command/URL"
echo "2. Name: CCB Up"
echo "3. Trigger: Alt+Space"
echo "4. Action: $CCB_BIN up"
echo ""

echo "--------------------------------------------------------"
echo "i3wm / Sway"
echo "--------------------------------------------------------"
echo "Add the following line to your config (~/.config/i3/config or ~/.config/sway/config):"
echo ""
echo "bindsym Mod1+space exec --no-startup-id $CCB_BIN up"
echo ""
echo "Then reload config (usually Mod+Shift+R)."
echo "--------------------------------------------------------"
