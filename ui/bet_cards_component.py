"""
Streamlit-Komponente "Spielerkarten mit Wettschein" (ui/components/bet_cards/index.html, ohne Build, kein Netz): die Karten (HTML aus ui/player_view.render_cards_html) sind anklickbar, unten
steht eine feste Wettschein-Leiste. Auswahl und Einsaetze liegen im JavaScript der Komponente; "Alle speichern" schickt eine Aktion {action:'save', nonce, game_key, items} an Python, die hier
EINMAL je nonce ausgefuehrt wird (ui/bet_slip.process_action -> save_player_bet, die Funktion des Formulars). Das Ergebnis geht als Argument 'result' zurueck an die Komponente.
Streamlit liefert den letzten Komponentenwert bei jedem Rerun erneut; darum merkt sich st.session_state die schon ausgefuehrten nonces.
"""
from __future__ import annotations

import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from data import day_bets_store as ds
from ui import bet_slip as bs
from ui import player_bet_entry as pe

_PATH = Path(__file__).resolve().parent / "components" / "bet_cards"
_component = components.declare_component("nbaedge_bet_cards", path=str(_PATH))
DONE_KEY, RESULT_KEY = "bc_done_nonces", "bc_results"


def is_selectable(key: str, now: float | None = None) -> bool:
    """Auswahl und Schein nur vor dem Anpfiff und ohne Dateifehler (gleiche Bedingung wie das Formular 'Spieler-Wette eintragen')."""
    return not ds.load_error() and ds.is_bet_editable(pe.game_parts(key)["start_utc"], now if now is not None else time.time())


def render_bet_cards(key: str, entries: dict, cards_html: str, css: str, default_stake: float = bs.DEFAULT_STAKE) -> None:
    """Komponente zeichnen, eine neue Speicher-Aktion genau einmal ausfuehren und danach die App einmal neu laufen lassen (Ergebnis + gesperrte Meilensteine)."""
    ss = st.session_state
    options = ds.player_bet_options(key, entries=entries)
    result = (ss.get(RESULT_KEY) or {}).get(key)
    value = _component(html=cards_html, css=css, game_key=key, locked=bs.locked_for_component(options), default_stake=default_stake, result=result, key=f"bet_cards_{key}", default=None)
    done = ss.setdefault(DONE_KEY, set())
    res = bs.process_action(key, value, options, done)
    if res is not None:
        ss.setdefault(RESULT_KEY, {})[key] = res
        st.rerun()
