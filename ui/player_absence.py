"""
Bereich "Ausfaelle" im Tab "Spieler" (Stufe 4, Baustein P8): pro Spiel manuell "fehlt" und "fraglich" aus dem Kader (data/rosters.json) waehlen und die Auswahl je Tag speichern
(data/absences_store.py; ESPN-Eintraege kommen automatisch dazu). Kein Netzabruf. Seit 29.10.2026 gibt es KEINE Neuberechnung mehr in der Oberflaeche: die Auswahl aendert keine Zahlen,
die Kennzeichnung "Fehlt/Fraglich" steht im Kasten ueber den Karten. Bereits gespeicherte Neuberechnungen (<Tag>.absences.json) bleiben unangetastet.
Der Bereich ist ein eigenes st.fragment OHNE Takt (DESIGN_REGELN.md Regel 68). Reine Hilfsfunktionen (ohne Streamlit) stehen oben und sind in tests/test_player_absences.py geprueft.
"""
from __future__ import annotations

import hashlib

import streamlit as st

from data import absences_store as ab
from data import rosters


# ----------------------------------------------------------------------------------------------- Hilfsfunktionen (ohne Streamlit)
def game_roster(key: str) -> tuple[list[dict], list[str]]:
    """Kader beider Teams eines Spiels (Gast zuerst, dann Heim, alphabetisch) und fehlende Teams: ([{person_id, name, team, side, team_abbreviation, ...}], [Teamnamen ohne Kader])."""
    _, _, home, away = key.split("|")[:4]
    return rosters.game_players(rosters.load(), away, home)


def player_dict(p: dict) -> dict:
    return {"person_id": int(p["person_id"]), "name": p["name"], "team": p.get("team")}


def save_absences(key: str, out_ids: list[int], doubtful_ids: list[int], now: float | None = None) -> tuple[bool, str]:
    """Auswahl speichern. Rueckgabe (ok, Meldung); nichts wird geworfen."""
    roster, _ = game_roster(key)
    by_id = {int(p["person_id"]): p for p in roster}
    try:
        res = ab.set_absences(key, [player_dict(by_id[i]) for i in out_ids if i in by_id], [player_dict(by_id[i]) for i in doubtful_ids if i in by_id], now=now)
    except ValueError as e:
        return False, f"Auswahl nicht gespeichert: {e}"
    except ab.AbsencesError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unerwarteter Fehler beim Speichern ({type(e).__name__}); es wurde nichts geändert."
    return True, "Auswahl gespeichert." if res["status"] == "saved" else "Auswahl unverändert."


def auto_caption_lines(cur: dict) -> list[str]:
    """Hinweiszeilen zu automatischen Eintraegen (ESPN): 'automatisch (ESPN), Stand HH:MM' (nur wenn solche Eintraege da sind) und nicht zugeordnete Namen. Reine Funktion."""
    auto = cur.get("auto") or {}
    if not auto:
        return []
    stamp = (auto.get("fetched_at") or "")[11:16]
    lines = []
    if any(v.get("source") for m in (cur["out"], cur["doubtful"]) for v in m.values()):
        lines.append(f"automatisch (ESPN), Stand {stamp}" + (" – von Hand geänderte Einträge bleiben unverändert" if stamp else ""))
    if auto.get("unmatched"):
        lines.append("ESPN, nicht zugeordnet (bitte von Hand prüfen): " + "; ".join(auto["unmatched"]))
    return lines


def selection_label(p: dict) -> str:
    return f"{p['name']} ({p.get('team_abbreviation') or p.get('team') or ''})"


# ----------------------------------------------------------------------------------------------- Knopf-Aktionen
def _on_save(key: str, out_key: str, dbt_key: str) -> None:
    ss = st.session_state
    ss["pa_msg"] = {"game": key, "ok_text": save_absences(key, [int(x) for x in ss.get(out_key, [])], [int(x) for x in ss.get(dbt_key, [])])}


# ----------------------------------------------------------------------------------------------- Streamlit
@st.fragment
def render_absences(key: str) -> None:
    """Bereich 'Ausfaelle' fuer das gewaehlte Spiel (Fragment ohne Takt)."""
    with st.expander("Ausfälle (fehlt / fraglich)", expanded=False):
        err = ab.load_error()
        if err:
            st.error(f"{err} Das Eintragen ist gesperrt, es wird nichts überschrieben.")
            return
        roster, missing = game_roster(key)
        if not roster:
            st.info("Kein Kader für dieses Spiel gefunden (data/rosters.json). Bitte im Tab „Pre-Match Eingabe“ den Kader aktualisieren." + (f" Fehlend: {', '.join(missing)}." if missing else ""))
            return
        msg = st.session_state.pop("pa_msg", None)
        if msg and msg.get("game") == key:
            (st.success if msg["ok_text"][0] else st.error)(msg["ok_text"][1])
        cur = ab.get(key)
        ids = [int(p["person_id"]) for p in roster]
        by_id = {int(p["person_id"]): p for p in roster}
        token = hashlib.md5(str(cur["updated_at"]).encode()).hexdigest()[:6]
        base = f"pa_{hashlib.md5(key.encode()).hexdigest()[:6]}_{token}"
        c1, c2 = st.columns(2)
        out_sel = c1.multiselect("Fehlt", ids, default=[i for i in cur["out"] if i in by_id], format_func=lambda i: selection_label(by_id[i]), key=f"{base}_out",
                                 help="Spieler, der sicher nicht spielt (Hinweis; die Zahlen auf den Karten ändern sich nicht).")
        dbt_sel = c2.multiselect("Fraglich", ids, default=[i for i in cur["doubtful"] if i in by_id], format_func=lambda i: selection_label(by_id[i]), key=f"{base}_dbt",
                                 help="Unsicher: nur ein Hinweis, die Prognose gilt, wenn er spielt.")
        if set(out_sel) & set(dbt_sel):
            st.warning("Ein Spieler steht bei „Fehlt“ und „Fraglich“: bitte nur eins wählen.")
        for line in auto_caption_lines(cur):
            st.caption(line)
        st.button("Auswahl speichern", key=f"{base}_save", on_click=_on_save, args=(key, f"{base}_out", f"{base}_dbt"))
        st.caption("Die Auswahl bleibt pro Tag in data/tracking/absences.json gespeichert (in der Datensicherung enthalten). Sie ändert keine Prognose: die Karten gelten für den Fall, dass der Spieler spielt.")
