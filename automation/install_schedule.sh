#!/bin/bash
# Installiert die zwei geplanten Auftraege im Benutzerkonto (kein sudo):
#   de.nbaedge.update-model  taeglich 08:00  (python update_model.py)
#   de.nbaedge.fetch-odds    taeglich 22:00  (python fetch_odds_daily.py)
# Aufruf:  bash automation/install_schedule.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(dirname "$DIR")"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS="de.nbaedge.update-model de.nbaedge.fetch-odds"

echo "Projektordner: $PROJECT"
echo "Ziel:          $AGENTS ($DOMAIN)"

# 1) Voraussetzungen pruefen, bevor irgendetwas installiert wird
for label in $LABELS; do
    src="$DIR/$label.plist"
    [ -f "$src" ] || { echo "Fehlt: $src"; exit 1; }
    plutil -lint "$src" >/dev/null || { echo "plist fehlerhaft: $src"; exit 1; }
    # alle absoluten Pfade in der plist muessen existieren (die plist enthaelt feste Pfade fuer diesen Ordner)
    for p in $(grep -o '<string>/[^<]*</string>' "$src" | sed -e 's/<string>//' -e 's/<\/string>//'); do
        case "$p" in
            */data/*.log) ;;                                  # Log-Dateien entstehen beim ersten Lauf
            *) [ -e "$p" ] || { echo "Pfad aus $label.plist existiert nicht: $p"; echo "(Projekt verschoben? Pfade in den plist-Dateien anpassen.)"; exit 1; } ;;
        esac
    done
done
mkdir -p "$AGENTS" "$PROJECT/data"

# 2) Installieren (erneutes Ausfuehren ersetzt die Auftraege)
for label in $LABELS; do
    dest="$AGENTS/$label.plist"
    launchctl bootout "$DOMAIN" "$dest" 2>/dev/null || true
    cp "$DIR/$label.plist" "$dest"
    launchctl bootstrap "$DOMAIN" "$dest"
    launchctl enable "$DOMAIN/$label"
    echo "Installiert: $label"
done

# 3) Anzeige: welche Auftraege sind geladen?
echo
echo "Geladene Auftraege (launchctl list | grep nbaedge):"
launchctl list | grep nbaedge || echo "  (keine gefunden)"
echo
for label in $LABELS; do
    launchctl print "$DOMAIN/$label" 2>/dev/null | grep -E "^\s*(state|path|program|working directory)|hour|minute" || true
    echo "---"
done
echo "Entfernen mit: bash automation/uninstall_schedule.sh"
