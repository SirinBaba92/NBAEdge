"""
Eingabe von Spieler-Wetten im Tab "Spieler" (Stufe 2): Spieler und eingelesenen Betano-Meilenstein waehlen, Quote vorbelegt, Einsatz optional, Speichern / Aendern / Entfernen ueber
data/day_bets_store.py (Revisionen, Sperre ab Anpfiff, atomares Schreiben). Kein Netzabruf. Der Bereich ist ein eigenes st.fragment OHNE Takt (Klicks laden nur ihn neu, DESIGN_REGELN.md Regel 68);
nach Speichern/Entfernen laeuft einmal die ganze App neu (st.rerun), damit "Meine Spieler-Wetten" und die Markierung in der Tabelle die Wette zeigen.
Reine Hilfsfunktionen (ohne Streamlit) stehen oben und sind in tests/test_player_bets_ui.py geprueft.
"""
from __future__ import annotations

import hashlib
import time

import streamlit as st

from data import bet_categories as bc
from data import day_bets_store as ds
from ui.score_cards import fmt_num

LOCK_TEXT = "Wette ab Anpfiff gesperrt"


# ----------------------------------------------------------------------------------------------- Hilfsfunktionen (ohne Streamlit)
def game_parts(key: str) -> dict:
    """game_key 'Tag|Anpfiff UTC|Heim|Gast' -> {'game_date', 'start_utc', 'home', 'away'}."""
    d, start, home, away = key.split("|")[:4]
    return {"game_date": d, "start_utc": start, "home": home, "away": away}


def option_label(o: dict) -> str:
    """'20+ · Quote 2,18 · Buchmacher 46 % · Modell 50 % (ungeprüft)' (Modell nur mit Snapshot)."""
    model = "" if o.get("model_team") is None else f" · Modell {int(o['model_team'] * 100 + 0.5)} % (ungeprüft)"
    return f"{o['milestone']}+ · Quote {fmt_num(o['odds'], 2)} · Buchmacher {o['bookmaker_percent']} %{model}"


def bet_text(bet: dict) -> str:
    odds = "—" if bet.get("odds") is None else fmt_num(bet["odds"], 2) + (f" ({bet['odds_source']})" if bet.get("odds_source") else "")
    stake = "—" if bet.get("stake") is None else fmt_num(bet["stake"], 2)
    return f"{bet['name']}: mindestens {bet['milestone']} Punkte · Quote {odds} · Einsatz {stake}"


def save_player_bet(key: str, option_player: dict, milestone: int, odds_text, stake, options: dict, now: float | None = None, categories=None) -> tuple[bool, str]:
    """Spieler-Wette speichern (setzen oder aendern). Rueckgabe (ok, Meldung); jeder Fehler wird eine verstaendliche deutsche Meldung, nichts wird geworfen.
    Nur Meilensteine aus der eingelesenen Liste sind zulaessig; Quelle der Quote: 'gespeichert' (unveraendert aus der Betano-Eingabe), sonst 'manuell'.
    categories: Liste aus player_ta | player_raw (data/bet_categories.py), mindestens eine; ohne Angabe bleiben die Kategorien einer bestehenden Wette erhalten."""
    g = game_parts(key)
    try:
        pre = ds.prefill_player_bet(options, option_player["person_id"], milestone)
        if pre is None:
            return False, "Eingabe nicht gespeichert: Dieser Meilenstein ist nicht in der eingelesenen Betano-Liste."
        odds = ds.parse_odds_optional(odds_text)
        source = None if odds is None else ("gespeichert" if abs(pre["odds"] - odds) < 1e-9 else "manuell")
        res = ds.set_player_bet(g["game_date"], g["start_utc"], g["home"], g["away"], option_player["person_id"], option_player["name"], option_player.get("team"), milestone,
                                odds=odds, stake=stake if stake else None, odds_source=source, odds_ref=pre["odds_ref"], now=now, categories=categories)
    except ds.GameStartedError as e:
        return False, f"{LOCK_TEXT}: {e}"
    except ds.BetInputError as e:
        return False, f"Eingabe nicht gespeichert: {e}"
    except ds.DayBetsError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unerwarteter Fehler beim Speichern ({type(e).__name__}); es wurde nichts geändert."
    return True, ("Gespeichert" if res["status"] == "saved" else "Unverändert (so bereits gespeichert)") + f": {bet_text(res['bet'])}"


def remove_player_bet(key: str, option_player: dict, now: float | None = None) -> tuple[bool, str]:
    """Spieler-Wette entfernen (nicht loeschen: bleibt als Revision erhalten). Rueckgabe (ok, Meldung)."""
    g = game_parts(key)
    try:
        res = ds.remove_player_bet(g["game_date"], g["start_utc"], g["home"], g["away"], option_player["person_id"], now=now)
    except ds.GameStartedError as e:
        return False, f"{LOCK_TEXT}: {e}"
    except ds.DayBetsError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unerwarteter Fehler beim Entfernen ({type(e).__name__}); es wurde nichts geändert."
    if res["status"] == "none":
        return True, f"{option_player['name']}: keine aktive Wette zu entfernen."
    return True, f"Entfernt: {bet_text(res['bet'])} (bleibt als Verlauf in der Datei erhalten)"


def _token(bet: dict | None) -> str:
    return "neu" if not bet or not bet.get("active") else hashlib.md5(f"{bet.get('updated_at')}|{bet.get('categories', bet.get('category'))}".encode()).hexdigest()[:8]


# ----------------------------------------------------------------------------------------------- Knopf-Aktionen (laufen VOR dem Neuaufbau)
def _set_msg(key: str, result: tuple[bool, str]) -> None:
    st.session_state["pe_msg"] = {"ok": result[0], "text": result[1], "game": key}
    if result[0]:
        st.session_state["pe_dirty"] = True


def _on_save(key: str, player: dict, milestone_key: str, odds_key: str, stake_key: str, options: dict, category_key: str | None = None) -> None:
    ss = st.session_state
    _set_msg(key, save_player_bet(key, player, ss.get(milestone_key), ss.get(odds_key), ss.get(stake_key), options, categories=ss.get(category_key) if category_key else None))


def _on_remove(key: str, player: dict) -> None:
    _set_msg(key, remove_player_bet(key, player))


def _in_fragment_rerun() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return bool(ctx and ctx.fragment_ids_this_run)
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------- Streamlit
@st.fragment
def render_player_bet_entry(key: str, entries: dict) -> None:
    """Bereich 'Spieler-Wette eintragen' fuer das gewaehlte Spiel (Fragment ohne Takt)."""
    if st.session_state.pop("pe_dirty", False) and _in_fragment_rerun():
        st.rerun()                                   # nach Speichern/Entfernen: ganze App einmal neu (Meldung bleibt im Session State)
    now = time.time()
    with st.expander("Spieler-Wette eintragen", expanded=False):
        err = ds.load_error()
        if err:
            st.error(f"{err} Das Eintragen ist gesperrt, es wird nichts überschrieben.")
            return
        msg = st.session_state.pop("pe_msg", None)
        if msg and msg.get("game") == key:
            (st.success if msg["ok"] else st.error)(msg["text"])
        options = ds.player_bet_options(key, entries=entries)
        players = options["players"]
        if not players:
            st.caption("Für dieses Spiel sind keine Betano-Meilensteine eingelesen.")
            return
        if not ds.is_bet_editable(game_parts(key)["start_utc"], now):
            st.info(f"🔒 {LOCK_TEXT}. Die gespeicherten Spieler-Wetten sind nur zur Ansicht.")
            for p in players:
                if p["current_bet"]:
                    st.markdown(f"- {bet_text(p['current_bet'])}")
            return
        by_id = {p["person_id"]: p for p in players}
        ids = [p["person_id"] for p in players]
        # Beschriftung bewusst konstant (ohne Wett-Marker): aendert sich die Beschriftung einer Option, bekommt Streamlit eine neue Widget-Identitaet und setzt die Auswahl zurueck
        label = lambda i: f"{by_id[i]['name']} ({by_id[i]['team_abbreviation'] or by_id[i]['team'] or ''})"
        pid = st.selectbox("Spieler", ids, format_func=label, key=f"pe_player_{key}")
        player = by_id[pid]
        cur = player["current_bet"]
        ms = [o["milestone"] for o in player["options"]]
        by_ms = {o["milestone"]: o for o in player["options"]}
        start_ms = cur["milestone"] if cur and cur["milestone"] in by_ms else ms[0]
        p = f"pe_{hashlib.md5(key.encode()).hexdigest()[:6]}_{pid}_{_token(cur)}"
        c1, c2, c3, c4 = st.columns([2.2, 1, 1, 1.2])
        m = c1.selectbox("Meilenstein (mindestens N Punkte, Over)", ms, index=ms.index(start_ms), format_func=lambda n: option_label(by_ms[n]), key=f"{p}_ms")
        same = bool(cur and cur["milestone"] == m)
        start_text = fmt_num(cur["odds"], 2) if same and cur.get("odds") is not None else fmt_num(by_ms[m]["odds"], 2)
        c2.text_input("Quote (optional)", value=start_text, key=f"{p}_odds_{m}", help="Vorbelegt aus der Betano-Eingabe; überschreibbar oder leer lassen.")
        c3.number_input("Einsatz (optional)", min_value=0.0, value=(cur or {}).get("stake"), step=1.0, format="%.2f", key=f"{p}_stake")
        names = bc.names()
        mode_default = bc.default_player_category(st.session_state.get("pl_mode", "team"))
        start_cat = [c for c in bc.normalize((cur or {}).get("categories", (cur or {}).get("category"))) if c in bc.PLAYER_IDS] or [mode_default]
        c4.multiselect("Kategorien", list(bc.PLAYER_IDS), default=start_cat, format_func=lambda c: names[c], key=f"{p}_cat",
                       help="Mehrfachauswahl, mindestens eine. Vorbelegt aus dem angezeigten Modus (Teamabgleich oder roh); die andere Kategorie kann zusätzlich gewählt werden.")
        stamp = by_ms[m].get("updated_at")
        st.caption(f"Quote vorbelegt aus Betano" + (f", Stand {stamp[11:16]}" if stamp else "") + ". Pro Spieler höchstens eine Wette; Ändern ersetzt sie (der alte Stand bleibt als Verlauf).")
        b1, b2, _ = st.columns([1, 1.3, 4])
        b1.button("Speichern", key=f"{p}_save", type="primary", on_click=_on_save, args=(key, player, f"{p}_ms", f"{p}_odds_{m}", f"{p}_stake", options, f"{p}_cat"))
        if cur:
            b2.button("Wette entfernen", key=f"{p}_remove", on_click=_on_remove, args=(key, player))
