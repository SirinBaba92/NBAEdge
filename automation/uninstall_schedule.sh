#!/bin/bash
# Entfernt die zwei geplanten Auftraege wieder (kein sudo).
# Aufruf:  bash automation/uninstall_schedule.sh
set -uo pipefail

AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS="de.nbaedge.update-model de.nbaedge.fetch-odds"

for label in $LABELS; do
    dest="$AGENTS/$label.plist"
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || launchctl bootout "$DOMAIN" "$dest" 2>/dev/null || true
    if [ -f "$dest" ]; then
        rm -f "$dest"
        echo "Entfernt: $dest"
    else
        echo "Nicht installiert: $label"
    fi
done

echo
echo "Noch geladene nbaedge-Auftraege (launchctl list | grep nbaedge):"
launchctl list | grep nbaedge || echo "  (keine, alles entfernt)"
