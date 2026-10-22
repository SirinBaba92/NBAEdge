"""
Tab "🏀 Spieltag" (Baustein 5, nur Anzeige): Spiele des aktuellen US-Spieltags mit Live-Chancen und eigenen Wetten. Das Eintragen von Wetten kommt spaeter.

Daten: data/live_feed.py (NBA.com-Scoreboard/Boxscore, ESPN nur als Fallback), Live-Zahlen aus data/live_feed.live_numbers_for_state (engine/live_model), Wetten aus
data/live_feed.bets_live (data/day_bets_store). Keine Odds-API-Credits, keine anderen Abrufe als im Feed (dessen Zwischenspeicher: Scoreboard 15 s, Boxscore 30 s).

Aktualisierung: Nur der Live-Teil laeuft in einem st.fragment mit run_every (30 s); er laedt die uebrige App nicht neu. Ein normaler App-Rerun (z. B. Klick in einem anderen Tab) ruft NICHT
neu ab, ausser beim allerersten Laden. Knopf "Aktualisieren" ruft ab (der Feed haelt trotzdem seine Zwischenspeicher-Zeiten ein); Schalter "Automatisch aktualisieren" (Standard an)
steuert nur den Abruf im 30-Sekunden-Takt: aus = der Takt zeichnet nur den letzten Stand neu. Sind alle Spiele beendet und ohne Fehler, wird nur alle 5 Minuten abgerufen.
"""
from __future__ import annotations

import time

import streamlit as st

from config.runtime import OFFLINE_AUDIT_MODE
from data import day_bets_store as ds
from data import live_feed as lf
from data import market_lines, projection_snapshots
from ui import live_card as lc
from ui.score_cards import CARD_CSS

AUTO_SECONDS = 30
IDLE_REFRESH_SECONDS = 300
LINE_MARKETS = ("spread", "total", "team_total_home", "team_total_away")


# ----------------------------------------------------------------------------------------------- Logik (ohne Streamlit testbar)
def auto_due(state, now: float | None = None) -> bool:
    """Im Takt abrufen? Ja bei nicht beendeten Spielen, Fehler oder noch keinen Spielen; sind alle Spiele beendet und ohne Fehler: nur alle 5 Minuten."""
    if state.error is not None or not state.games or any(g.status != "FINAL" for g in state.games):
        return True
    return (state.age_s or 0) >= IDLE_REFRESH_SECONDS


def pick_state(feed, clicked: bool, auto: bool, fragment_rerun: bool, now: float | None = None):
    """Welchen Zustand zeigt der Tab? Abruf nur bei Klick, beim allerersten Laden und im Takt (Fragment-Lauf, automatisch an, faellig). Sonst der letzte Stand ohne Abruf."""
    state = feed.state(now)
    if clicked:
        return feed.refresh(now)
    if state.fetched_at is None and state.error is None:
        return feed.refresh(now)
    if fragment_rerun and auto and auto_due(state, now):
        return feed.refresh(now)
    return state


def market_lines_for(game, snapshots: dict, entries: dict) -> dict | None:
    """Hauptlinien eines Spiels aus den vorhandenen Daten (keine Abrufe): 1. letzte Linien im Schnappschuss vor dem Anpfiff, 2. eigene Eingabe (Betano/Hand), sonst None.
    Rueckgabe {'spread_home', 'total', 'team_total_home', 'team_total_away'} (Spread aus Heim-Sicht) oder None."""
    resolved = None
    found = lf.find_snapshot(game, snapshots)
    if found:
        mk = found[1].get("markets") or {}
        res = {m: {"line": (mk.get(m) or {}).get("line")} for m in LINE_MARKETS}
        if any(v["line"] is not None for v in res.values()):
            resolved = res
    if resolved is None:
        for entry in (entries or {}).values():
            if entry.get("game_date") == game.day and lf.same_team(entry.get("home"), game.home_nick) and lf.same_team(entry.get("away"), game.away_nick):
                cands = market_lines.own_candidates(entry)
                if cands:
                    resolved = {m: {"line": (cands.get(m) or {}).get("line")} for m in LINE_MARKETS}
                break
    return ds.main_lines_from_resolved(resolved) if resolved else None


def build_page(state, snapshots: dict | None = None, entries: dict | None = None, day_bets: dict | None = None) -> dict:
    """Alle Bausteine der Seite als HTML: {'status', 'overview', 'summary', 'cards': [(game_id, html)], 'empty'}. Nur lesend."""
    snaps = projection_snapshots.load().get("games", {}) if snapshots is None else snapshots
    entries = market_lines.load_entries() if entries is None else entries
    numbers = lf.live_numbers_for_state(state, snaps)
    bet_rows = lf.bets_live(state, snaps, day_bets)
    by_game = {r["game"].game_id: r for r in bet_rows if r["game"] is not None}
    counts = {gid: len(r["bets"]) for gid, r in by_game.items()}
    cards = []
    for g in lc.card_order(state.games):
        r = by_game.get(g.game_id)
        vm = lc.build_game_vm(g, numbers.get(g.game_id), r["lives"] if r else {}, r["bets"] if r else {}, market_lines_for(g, snaps, entries))
        cards.append((g.game_id, lc.render_game_card_html(vm)))
    summary = lc.summary_from_rows([r for r in bet_rows if r["game"] is not None])
    orphans = [r for r in bet_rows if r["game"] is None]
    summary_html = lc.render_summary_html(summary)
    if orphans:
        n = sum(len(r["bets"]) for r in orphans)
        summary_html += f'<div class="lv-hint">{n} gespeicherte Wette(n) gehören zu Spielen, die (noch) nicht im Scoreboard stehen.</div>'
    return {"status": lc.render_status_html(state), "overview": lc.render_overview_html(state.games, state.day, counts), "summary": summary_html, "cards": cards,
            "summary_data": summary, "numbers": numbers, "bet_rows": bet_rows}


# ----------------------------------------------------------------------------------------------- Streamlit
def _fragment_rerun() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return bool(ctx and ctx.fragment_ids_this_run)
    except Exception:
        return False


@st.fragment(run_every=AUTO_SECONDS)
def _live_fragment() -> None:
    feed = lf.get_feed()
    c1, c2, c3 = st.columns([1.1, 1.7, 4])
    with c1:
        clicked = st.button("Aktualisieren", key="sp_refresh", help="Ruft NBA.com ab (Scoreboard höchstens alle 15 s, Boxscore je Spiel höchstens alle 30 s).")
    with c2:
        auto = st.toggle("Automatisch aktualisieren", value=True, key="sp_auto", help="Aus: Der 30-Sekunden-Takt ruft nichts mehr ab und zeichnet nur den letzten Stand neu.")
    with c3:
        st.caption("Aktualisiert nur diesen Bereich alle 30 Sekunden, solange Spiele nicht beendet sind. Keine Odds-API-Credits.")
    state = pick_state(feed, clicked, auto, _fragment_rerun())
    page = build_page(state)
    st.markdown(lc.flat(page["status"]), unsafe_allow_html=True)
    st.markdown(lc.flat(page["overview"]), unsafe_allow_html=True)
    st.markdown(lc.flat(page["summary"]), unsafe_allow_html=True)
    if not page["cards"]:
        st.info("Noch keine Spielkarten: Für diesen Spieltag stehen keine Spiele im Scoreboard." if state.games == () else "Keine Spiele.")
    for gid, html in page["cards"]:
        with st.container(key=f"sp_game_{gid}"):
            st.markdown(lc.flat(html), unsafe_allow_html=True)


def render_spieltag_tab() -> None:
    """Inhalt des Tabs '🏀 Spieltag' (aus app.py aufgerufen)."""
    st.markdown("## 🏀 Spieltag")
    st.markdown(lc.flat(CARD_CSS + lc.LIVE_CSS), unsafe_allow_html=True)
    if OFFLINE_AUDIT_MODE:
        st.info("Offline-Prüfmodus: Der Spieltag-Tab ruft nichts ab.")
        return
    _live_fragment()
