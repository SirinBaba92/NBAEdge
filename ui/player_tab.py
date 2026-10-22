"""
Tab "🏃 Spieler" (Baustein P9): Spieler-Punkte-Prognose gegen die Betano-Meilensteine, Spieler-Wetten, Live-Bewertung und Ausfaelle (in Stufen).
Stufe 1 (hier): Prognose-Ansicht. Alle Prognosen und Chancen sind UNGEPRUEFT und so gekennzeichnet.

Daten: Prognose-Snapshot (analysis/results/forecast_snapshots/<Tag>.json, engine/player_snapshots.py), Betano-Meilensteine aus data/tracking/pre_match_entries.json (nur lesen). Ohne Snapshot fuer ein
Spiel gibt es die Schaltflaeche "Prognose jetzt erstellen" (dieselbe Logik wie analysis/print_player_forecast.py, schreibt den Snapshot genau einmal). Keine Netzabrufe, keine Odds-API-Credits.

Aufbau: Die Prognose-Ansicht ist ein eigenes st.fragment OHNE Takt: Klicks (Spiel, Sortierung, Umschalter) lassen nur diesen Bereich neu laufen, nicht die ganze App (DESIGN_REGELN.md Regel 68).
Reine Hilfsfunktionen (ohne Streamlit) stehen oben und sind in tests/test_player_tab.py geprueft.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from config.runtime import OFFLINE_AUDIT_MODE
from data import day_bets_store as ds
from data import live_feed as lf
from data import pre_match_store as store
from engine import player_odds as po
from engine import player_snapshots as psn
from ui import player_view as pv
from ui.live_card import flat
from ui.score_cards import CARD_CSS

BERLIN = ZoneInfo("Europe/Berlin")


# ----------------------------------------------------------------------------------------------- Logik (ohne Streamlit testbar)
def games_with_players(entries: dict) -> list[str]:
    """Spiele (game_key), fuer die Betano-Spielerquoten gespeichert sind, nach Spieltag und Anpfiff sortiert."""
    keys = [k for k, e in (entries or {}).items() if store.active_player_blocks(e) and po.game_player_odds(entries, k)]
    return sorted(keys, key=lambda k: (k.split("|")[0], k.split("|")[1] if "|" in k else "", k))


def days_with_players(entries: dict) -> list[str]:
    return sorted({k.split("|", 1)[0] for k in games_with_players(entries)})


def default_day(days: list[str], now: float | None = None) -> str | None:
    """Standard-Spieltag: der aktuelle US-Spieltag, wenn er Spielerquoten hat, sonst der neueste mit Quoten."""
    if not days:
        return None
    today = lf.current_us_day(now if now is not None else time.time())
    return today if today in days else days[-1]


def game_label(key: str) -> str:
    """'Cleveland Cavaliers @ Philadelphia 76ers · Fr 01:00' (Gast @ Heim, Anpfiff in Berliner Zeit)."""
    parts = key.split("|")
    try:
        dt = datetime.fromisoformat(parts[1].replace("Z", "+00:00")).astimezone(BERLIN)
        when = f" · {('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')[dt.weekday()]} {dt:%H:%M}"
    except (IndexError, ValueError):
        when = ""
    return f"{parts[3]} @ {parts[2]}{when}" if len(parts) >= 4 else key


def started(key: str, now: float | None = None) -> bool:
    return not ds.is_bet_editable(key.split("|")[1] if "|" in key else None, now)


def create_snapshot(key: str, entries: dict) -> tuple[str, dict]:
    """'Prognose jetzt erstellen': gleiche Logik wie das Skript, schreibt den Snapshot einmalig."""
    return psn.create_for_game(key, entries)


# ----------------------------------------------------------------------------------------------- Streamlit
def _create_clicked(key: str) -> None:
    """Knopf-Callback: Prognose rechnen und Snapshot speichern (laeuft vor dem Neuaufbau, Meldung im Session State)."""
    try:
        status, entry = create_snapshot(key, store.load()["entries"])
        st.session_state["pl_msg"] = ("ok", f"Prognose erstellt ({status}). {entry['note'].capitalize()}.")
    except Exception as e:
        st.session_state["pl_msg"] = ("err", f"Die Prognose konnte nicht erstellt werden: {type(e).__name__}: {str(e)[:160]}")


def _snapshot_notes(entry: dict) -> None:
    created = (entry.get("created_at") or "")[:16].replace("T", " ")
    if entry.get("created_after_start"):
        st.markdown(f"<div class='pl-banner'>Snapshot nach dem Anpfiff erstellt ({created}): Daten nur bis Vortag, nicht als Vorab-Prognose zu werten.</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='pl-info'>Snapshot vom {created} (vor dem Anpfiff erstellt). {pv.escape(entry.get('history') or '')}</div>", unsafe_allow_html=True)
    lines = pv.team_lines(entry)
    if lines:
        st.markdown("<div class='pl-info'>Teamabgleich: " + " &nbsp;|&nbsp; ".join(pv.escape(x) for x in lines) + "</div>", unsafe_allow_html=True)


@st.fragment
def _forecast_view() -> None:
    """Prognose-Ansicht (Fragment ohne Takt): Spiel waehlen, Tabelle, Umschalter und Sortierung."""
    entries = store.load()["entries"]
    days = days_with_players(entries)
    if not days:
        st.info("Noch keine Spielerquoten gespeichert. Sie kommen aus dem Tab „Pre-Match Eingabe“ (Markt Spielerpunkte / Betano-Import).")
        return
    c1, c2 = st.columns([1, 3])
    day_default = default_day(days)
    with c1:
        day = st.selectbox("Spieltag", days, index=days.index(day_default), key="pl_day")
    keys = [k for k in games_with_players(entries) if k.startswith(day + "|")]
    with c2:
        key = st.selectbox("Spiel", keys, format_func=game_label, key=f"pl_game_{day}")
    msg = st.session_state.pop("pl_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    entry = ds.load_forecast_snapshot(key)
    if entry is None:
        st.info("Für dieses Spiel gibt es noch keinen Prognose-Snapshot." + (" Das Spiel hat bereits begonnen: ein jetzt erstellter Snapshot ist nur eingeschränkt aussagekräftig." if started(key) else ""))
        st.button("Prognose jetzt erstellen", key=f"pl_create_{key}", on_click=_create_clicked, args=(key,),
                  help="Rechnet die Prognose für dieses Spiel (ca. 10 Sekunden, kein Netzabruf) und speichert sie einmalig als Snapshot.")
        return
    _snapshot_notes(entry)
    o1, o2 = st.columns(2)
    with o1:
        mode = st.radio("Modell", list(pv.MODES), format_func=pv.MODES.get, horizontal=True, key="pl_mode", help="Teamabgleich: Summe der Spieler an den Teampunkten des Spielmodells ausgerichtet. roh: Einzelprognose ohne Abgleich.")
    with o2:
        sort = st.radio("Sortierung", list(pv.SORTS), format_func=pv.SORTS.get, horizontal=True, key="pl_sort")
    model = pv.build_table_model(entry, mode, sort)
    st.markdown(flat(pv.render_table_html(model)), unsafe_allow_html=True)
    st.caption(f"◀ Modell mindestens {pv.fmt_num(pv.MARK_PP, 0)} Prozentpunkte über dem Buchmacher, ▼ darunter. Differenz = Modell minus Buchmacher-Chance (inkl. Marge), aus ungerundeten Werten. "
               "⚠ bewegt man die Maus darüber: Datenqualität und Hinweise.")


def render_player_tab() -> None:
    """Inhalt des Tabs '🏃 Spieler' (aus app.py aufgerufen)."""
    st.markdown("## 🏃 Spieler")
    st.markdown(flat(CARD_CSS + pv.PLAYER_CSS), unsafe_allow_html=True)
    st.markdown(f"<div class='pl-banner'>{pv.escape(pv.UNVERIFIED_TEXT)}</div>", unsafe_allow_html=True)
    if OFFLINE_AUDIT_MODE:
        st.info("Offline-Prüfmodus: Der Spieler-Tab zeigt nichts an.")
        return
    _forecast_view()
