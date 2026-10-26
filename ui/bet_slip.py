"""
Wettschein im Tab "Prognose": mehrere Spieler-Wetten auswaehlen und mit EINEM Klick speichern. Gespeichert wird ueber dieselbe Funktion wie im Formular "Spieler-Wette eintragen"
(ui/player_bet_entry.save_player_bet -> data/day_bets_store.set_player_bet): gleiche Pruefungen (Sperre ab Anpfiff, Quote, Einsatz), gleiche Felder, kein zweiter Speicherweg.
Der Schein steht je Spiel im Session State; die Quote gilt so, wie sie beim Hinzufuegen war (kein neuer Abruf). Reine Funktionen stehen oben (ohne App testbar, tests/test_bet_slip.py).
Einschraenkung der Wettliste: je Spieler hoechstens EINE aktive Wette (eine neue wuerde die alte ersetzen). Darum kann der Schein je Spieler nur einen Meilenstein enthalten und Spieler mit
bestehender Wette sind gesperrt.
"""
from __future__ import annotations

import time

import streamlit as st

from data import day_bets_store as ds
from ui import player_bet_entry as pe
from ui.score_cards import fmt_num

DEFAULT_STAKE = 10.0


# ----------------------------------------------------------------------------------------------- Hilfsfunktionen (ohne Streamlit)
def option_label(o: dict, mode: str = "team") -> str:
    """'20+ · Quote 1,85 · Betano 71 % · Modell 72 %' (Modell nur mit Snapshot; Modus Teamabgleich oder roh wie bei den Karten)."""
    m = o.get("model_team") if mode != "raw" else o.get("model_raw")
    model = "" if m is None else f" · Modell {int(m * 100 + 0.5)} %"
    return f"{o['milestone']}+ · Quote {fmt_num(o['odds'], 2)} · Betano {o['bookmaker_percent']} %{model}"


def blocked_milestones(player: dict, slip: list[dict]) -> dict:
    """{Meilenstein: Grund} der nicht waehlbaren Meilensteine eines Spielers: '✓ schon gesetzt' (gespeicherte Wette auf genau diesen), 'Spieler hat schon eine Wette auf N+' (andere Meilensteine,
    weil je Spieler nur eine Wette moeglich ist) oder 'schon im Schein'."""
    out = {}
    cur = player.get("current_bet")
    in_slip = {l["milestone"] for l in slip if int(l["person_id"]) == int(player["person_id"])}
    for o in player["options"]:
        n = o["milestone"]
        if cur and cur.get("active", True) and cur["milestone"] == n:
            out[n] = "✓ schon gesetzt"
        elif cur and cur.get("active", True):
            out[n] = f"Spieler hat schon eine Wette auf {cur['milestone']}+"
        elif in_slip:
            out[n] = "schon im Schein" if n in in_slip else "Spieler ist schon im Schein (je Spieler nur eine Wette)"
    return out


def add_lines(slip: list[dict], player: dict, milestones: list[int], default_stake: float) -> tuple[list[dict], list[str]]:
    """Neue Schein-Zeilen (Spieler, Meilenstein, Quote vom Zeitpunkt des Hinzufuegens, Standard-Einsatz). Rueckgabe (neuer Schein, Meldungen); der alte Schein wird nicht veraendert.
    Gesperrte Meilensteine und mehrere Meilensteine desselben Spielers werden abgelehnt."""
    new, msgs = [dict(l) for l in slip], []
    blocked = blocked_milestones(player, slip)
    by_ms = {o["milestone"]: o for o in player["options"]}
    picked = [n for n in milestones if n in by_ms]
    for n in picked:
        if n in blocked:
            msgs.append(f"{player['name']} {n}+: nicht hinzugefügt ({blocked[n]}).")
    ok = [n for n in picked if n not in blocked]
    if len(ok) > 1:
        msgs.append(f"{player['name']}: je Spieler ist nur eine Wette möglich, bitte nur einen Meilenstein wählen. Nichts hinzugefügt.")
        return new, msgs
    if ok:
        o = by_ms[ok[0]]
        new.append({"person_id": int(player["person_id"]), "name": player["name"], "team": player.get("team"), "milestone": int(o["milestone"]), "odds": float(o["odds"]), "stake": float(default_stake)})
    return new, msgs


def remove_line(slip: list[dict], person_id: int) -> list[dict]:
    return [dict(l) for l in slip if int(l["person_id"]) != int(person_id)]


def totals(slip: list[dict]) -> dict:
    """{'n', 'stake' (Gesamteinsatz), 'avg_odds' (Ø Quote, einfacher Mittelwert; None ohne Zeilen)}."""
    n = len(slip)
    return {"n": n, "stake": round(sum(float(l["stake"] or 0) for l in slip), 2), "avg_odds": None if not n else round(sum(float(l["odds"]) for l in slip) / n, 2)}


def line_problem(line: dict) -> str | None:
    try:
        if float(line["stake"]) <= 0:
            return "Einsatz muss größer als 0 sein"
    except (TypeError, ValueError):
        return "Einsatz ist keine Zahl"
    return None


def save_slip(key: str, slip: list[dict], options: dict, save_fn=None, now: float | None = None) -> dict:
    """Jede Zeile einzeln ueber save_player_bet speichern (Quote und Einsatz wie im Schein). Rueckgabe {'saved': [Zeilen], 'failed': [(Zeile, Meldung)], 'remaining': [Zeilen],
    'messages': [...]}: gespeicherte Zeilen stehen nicht mehr im Schein, fehlgeschlagene bleiben mit Meldung; nie wird eine Ausnahme geworfen."""
    save_fn = save_fn or pe.save_player_bet
    now = now if now is not None else time.time()
    by_id = {int(p["person_id"]): p for p in options["players"]}
    saved, failed = [], []
    for line in slip:
        problem = line_problem(line)
        player = by_id.get(int(line["person_id"]))
        if problem is None and player is None:
            problem = "Spieler nicht in der eingelesenen Betano-Liste"
        if problem is not None:
            failed.append((line, problem))
            continue
        try:
            ok, msg = save_fn(key, player, line["milestone"], repr(float(line["odds"])), round(float(line["stake"]), 2), options, now=now)
        except Exception as e:
            ok, msg = False, f"Unerwarteter Fehler ({type(e).__name__}); nichts geändert."
        (saved if ok else failed).append(line if ok else (line, msg))
    messages = [f"{len(saved)} Wetten gespeichert" if len(saved) != 1 else "1 Wette gespeichert"] if saved else []
    messages += [f"Nicht gespeichert: {l['name']} {l['milestone']}+ – {m}" for l, m in failed]
    return {"saved": saved, "failed": failed, "remaining": [l for l, _ in failed], "messages": messages}


# ----------------------------------------------------------------------------------------------- Streamlit
def _slip_key(key: str) -> str:
    return f"slip_{key}"


def _stake_key(key: str, pid: int) -> str:
    return f"slip_stake_{key}_{pid}"


def _on_add(key: str, player: dict, ms_key: str) -> None:
    ss = st.session_state
    new, msgs = add_lines(ss.get(_slip_key(key), []), player, [int(n) for n in ss.get(ms_key, [])], float(ss.get("slip_default_stake", DEFAULT_STAKE)))
    for l in new:                                                       # neue Zeile: Einsatzfeld mit dem Standard-Einsatz vorbelegen
        ss.setdefault(_stake_key(key, l["person_id"]), l["stake"])
    ss[_slip_key(key)] = new
    ss[ms_key] = []
    if msgs:
        ss["slip_msg"] = {"game": key, "ok": False, "text": " ".join(msgs)}


def _on_remove(key: str, pid: int) -> None:
    ss = st.session_state
    ss[_slip_key(key)] = remove_line(ss.get(_slip_key(key), []), pid)
    ss.pop(_stake_key(key, pid), None)


def _on_clear(key: str) -> None:
    ss = st.session_state
    for l in ss.get(_slip_key(key), []):
        ss.pop(_stake_key(key, l["person_id"]), None)
    ss[_slip_key(key)] = []


def _on_save_all(key: str, options: dict) -> None:
    ss = st.session_state
    slip = [{**l, "stake": ss.get(_stake_key(key, l["person_id"]), l["stake"])} for l in ss.get(_slip_key(key), [])]
    res = save_slip(key, slip, options)
    for l in res["saved"]:
        ss.pop(_stake_key(key, l["person_id"]), None)
    ss[_slip_key(key)] = res["remaining"]
    ss["slip_msg"] = {"game": key, "ok": not res["failed"], "text": " | ".join(res["messages"])}
    if res["saved"]:
        ss["slip_dirty"] = True


@st.fragment
def render_bet_slip(key: str, entries: dict, mode: str = "team") -> None:
    """Bereich 'Wettschein' (Expander, offen) fuer das gewaehlte Spiel; nur vor dem Anpfiff (gleiche Bedingung wie das Formular 'Spieler-Wette eintragen'). Fragment ohne Takt."""
    ss = st.session_state
    if ss.pop("slip_dirty", False):
        st.rerun()                                            # nach dem Speichern die ganze App neu: 'Meine Spieler-Wetten' und Markierungen zeigen die neuen Wetten
    if ds.load_error() or not ds.is_bet_editable(pe.game_parts(key)["start_utc"], time.time()):
        return
    options = ds.player_bet_options(key, entries=entries)
    players = options["players"]
    if not players:
        return
    with st.expander("Wettschein", expanded=True):
        msg = ss.pop("slip_msg", None)
        if msg and msg.get("game") == key:
            (st.success if msg["ok"] else st.error)(msg["text"])
        by_id = {p["person_id"]: p for p in players}
        ids = [p["person_id"] for p in players]
        c0, c1 = st.columns([1, 3])
        c0.number_input("Standard-Einsatz (€)", min_value=0.0, value=DEFAULT_STAKE, step=1.0, format="%.2f", key="slip_default_stake", help="Gilt für neu hinzugefügte Wetten.")
        pid = c1.selectbox("Spieler", ids, format_func=lambda i: f"{by_id[i]['name']} ({by_id[i]['team_abbreviation'] or by_id[i]['team'] or ''})", key=f"slip_player_{key}")
        player = by_id[pid]
        slip = ss.get(_slip_key(key), [])
        blocked = blocked_milestones(player, slip)
        free = [o["milestone"] for o in player["options"] if o["milestone"] not in blocked]
        by_ms = {o["milestone"]: o for o in player["options"]}
        ms_key = f"slip_ms_{key}_{pid}"
        st.multiselect("Meilensteine", free, format_func=lambda n: option_label(by_ms[n], mode), key=ms_key, help="Je Spieler nur ein Meilenstein (die Wettliste kennt je Spieler eine Wette).")
        if blocked:
            st.caption("Nicht wählbar: " + " · ".join(f"{n}+ ({why})" for n, why in blocked.items()))
        st.button("Zum Schein hinzufügen", key=f"slip_add_{key}", on_click=_on_add, args=(key, player, ms_key))
        if not slip:
            st.caption("Der Schein ist leer.")
            return
        for l in slip:
            a, b, c, d = st.columns([2.2, 2, 1.2, 0.8])
            a.markdown(f"**{l['name']}**")
            b.markdown(f"mindestens {l['milestone']} · Quote {fmt_num(l['odds'], 2)}")
            c.number_input("Einsatz (€)", min_value=0.0, value=float(l["stake"]), step=1.0, format="%.2f", key=_stake_key(key, l["person_id"]), label_visibility="collapsed")
            d.button("Entfernen", key=f"slip_rm_{key}_{l['person_id']}", on_click=_on_remove, args=(key, l["person_id"]))
        shown = [{**l, "stake": ss.get(_stake_key(key, l["person_id"]), l["stake"])} for l in slip]
        t = totals(shown)
        st.caption(f"{t['n']} Wette(n) · Gesamteinsatz {fmt_num(t['stake'], 2)} € · Ø Quote {fmt_num(t['avg_odds'], 2)}")
        b1, b2, _ = st.columns([1, 1, 4])
        b1.button("Alle speichern", key=f"slip_save_{key}", type="primary", on_click=_on_save_all, args=(key, options))
        b2.button("Leeren", key=f"slip_clear_{key}", on_click=_on_clear, args=(key,))
