"""
Wettliste im Tab "🏀 Spieltag": Filter nach Kategorie, Summen je Kategorie, Kategorien einer Wette aendern (Mehrfachauswahl), alle sichtbaren Wetten gesammelt aendern (hinzufuegen / entfernen / ersetzen, mit Bestaetigung), Kategorien umbenennen.
Die Liste zeigt die Team- UND Spieler-Wetten des Spieltags (gleiche Daten wie die Karten: data/live_feed.bets_live). Aendern betrifft nur das Feld "categories" der Wette
(data/day_bets_store.change_categories), nie Einsatz, Quote, Status, Ergebnis oder die Zahl der Wetten. Eine Wette kann in mehreren Kategorien liegen (mindestens eine); sie zaehlt dann in jeder
davon mit, bei "Alle" genau einmal. Wetten ohne Kategorie (aeltere) erscheinen als "Ohne Kategorie".
Reine Funktionen stehen oben (ohne Streamlit, tests/test_bet_categories.py); das Fragment unten (ohne Takt) ruft sie nur auf.
"""
from __future__ import annotations

import streamlit as st

from data import bet_categories as bc
from data import day_bets_store as ds
from data import live_feed as lf
from ui import live_card as lc
from ui.score_cards import fmt_num

FILTER_ALL, FILTER_NONE = "all", "none"
ZERO = {"wetten": 0, "offen": 0, "gewonnen": 0, "verloren": 0, "nicht_gespielt": 0, "einsatz": 0.0, "gewinn_verlust": 0.0, "ohne_status": 0, "ohne_quote_oder_einsatz": 0}


# ----------------------------------------------------------------------------------------------- reine Funktionen
def collect_items(bet_rows: list[dict]) -> list[dict]:
    """Flache Liste aller aktiven Wetten aus bets_live(): [{'kind': 'team'|'player', 'key': game_key, 'id': Markt | person_id, 'bet', 'live' (BetLive | BetLivePlayer | None), 'categories' (Liste von IDs)}].
    Fehlt das Feld (aeltere Wetten), ist die Liste leer ("Ohne Kategorie"); ein fruehes Einzelfeld "category" wird zur Liste."""
    items = []
    for r in bet_rows:
        for market in ds.MARKETS:
            bet = (r.get("bets") or {}).get(market)
            if bet and bet.get("active", True):
                items.append({"kind": "team", "key": r["key"], "id": market, "bet": bet, "live": (r.get("lives") or {}).get(market), "categories": bc.normalize(bet.get("categories", bet.get("category")))})
        for pid, bet in sorted((r.get("player_bets") or {}).items(), key=lambda kv: int(kv[0])):
            if bet.get("active", True):
                items.append({"kind": "player", "key": r["key"], "id": int(pid), "bet": bet, "live": (r.get("player_lives") or {}).get(int(pid)), "categories": bc.normalize(bet.get("categories", bet.get("category")))})
    return items


def item_categories(item: dict) -> list:
    return bc.normalize(item.get("categories", item.get("category")))


def group_summary(items: list[dict]) -> dict:
    """Summen einer Gruppe: 'wetten' und 'einsatz' zaehlen alle gespeicherten Wetten; offen/gewonnen/verloren/nicht gespielt/Gewinn nur mit Status (wie die bestehende Tagessumme, ds.summarize)."""
    lives = [i["live"] for i in items if i.get("live") is not None]
    s = ds.summarize(lives) if lives else {"wetten": 0, "offen": 0, "gewonnen": 0, "verloren": 0, "gewinn_verlust": 0.0, "ohne_quote_oder_einsatz": 0}
    total = len(items)
    return {"wetten": total, "offen": s["offen"], "gewonnen": s["gewonnen"], "verloren": s["verloren"], "nicht_gespielt": s.get("nicht_gespielt", 0),
            "einsatz": round(sum((i["bet"].get("stake") or 0.0) for i in items), 2), "gewinn_verlust": s["gewinn_verlust"], "ohne_status": total - s["wetten"],
            "ohne_quote_oder_einsatz": s["ohne_quote_oder_einsatz"]}


def summary_by_category(items: list[dict]) -> dict:
    """{'all': Summen aller Wetten (jede genau einmal), team_1: ..., player_raw: ..., 'none': Summen der Wetten ohne Kategorie}. Eine Wette in mehreren Kategorien zaehlt in jeder davon mit;
    die Kategorie-Summen koennen darum zusammen mehr ergeben als 'all'. Jede Kategorie ist immer vorhanden (ggf. Nullen)."""
    out = {FILTER_ALL: group_summary(items)}
    for cid in bc.ALL_IDS:
        out[cid] = group_summary([i for i in items if cid in item_categories(i)])
    out[FILTER_NONE] = group_summary([i for i in items if not item_categories(i)])
    return out


def filter_items(items: list[dict], flt: str) -> list[dict]:
    if flt == FILTER_ALL:
        return list(items)
    if flt == FILTER_NONE:
        return [i for i in items if not item_categories(i)]
    return [i for i in items if flt in item_categories(i)]


MODE_LABELS = {"add": "Kategorien hinzufügen", "remove": "Kategorien entfernen", "replace": "Kategorien ersetzen"}


def plan_change(items: list[dict], mode: str, cats: list) -> dict:
    """Vorschau einer gesammelten Aenderung (ohne zu schreiben): {'apply': [Wetten, bei denen sich etwas aendert], 'same': n (schon so), 'skipped': [(Wette, Grund)]}.
    Team-Wetten nehmen nur Team-Kategorien, Spieler-Wetten nur Spieler-Kategorien; eine Wette behaelt mindestens eine Kategorie."""
    apply, same, skipped = [], 0, []
    for i in items:
        cur = item_categories(i)
        new, why = ds.plan_categories(cur, mode, cats, i["kind"])
        if new is None:
            skipped.append((i, why))
        elif new == cur:
            same += 1
        else:
            apply.append(i)
    return {"apply": apply, "same": same, "skipped": skipped}


def filter_options() -> list[str]:
    return [FILTER_ALL, *bc.ALL_IDS, FILTER_NONE]


def filter_label(flt: str, nm: dict | None = None) -> str:
    return "Alle" if flt == FILTER_ALL else bc.NO_CATEGORY_LABEL if flt == FILTER_NONE else bc.label(flt, nm)


def summary_rows(summaries: dict, nm: dict | None = None) -> list[dict]:
    """Zeilen der kleinen Tabelle: die vier Kategorien, 'Ohne Kategorie' (nur wenn vorhanden) und 'Alle'."""
    rows = []
    for flt in (*bc.ALL_IDS, FILTER_NONE, FILTER_ALL):
        s = summaries[flt]
        if flt == FILTER_NONE and not s["wetten"]:
            continue
        rows.append({"Kategorie": filter_label(flt, nm), "Wetten": s["wetten"], "Offen": s["offen"], "Gewonnen": s["gewonnen"], "Verloren": s["verloren"], "Nicht gespielt": s["nicht_gespielt"],
                     "Einsatz": fmt_num(s["einsatz"], 2), "Gewinn/Verlust": fmt_num(s["gewinn_verlust"], 2, signed=True)})
    return rows


def item_text(item: dict) -> str:
    """'Falken @ Baeren · Total Over 231,5 · Quote 1,90 · Einsatz 20,00 · Status' bzw. 'Anna Alpha: mindestens 20 Punkte · ...'."""
    parts = item["key"].split("|")
    home, away = (parts[2], parts[3]) if len(parts) >= 4 else ("?", "?")
    bet, live = item["bet"], item.get("live")
    odds = "keine Quote" if bet.get("odds") is None else f"Quote {fmt_num(bet['odds'], 2)}"
    stake = "kein Einsatz" if bet.get("stake") is None else f"Einsatz {fmt_num(bet['stake'], 2)}"
    status = getattr(live, "label", None) or "ohne Status"
    if item["kind"] == "player":
        what = f"{bet.get('name', '?')}: mindestens {bet.get('milestone')} Punkte"
    else:
        m, side, line = item["id"], bet.get("side"), bet.get("line")
        name = ds.MARKET_NAMES.get(m, m)
        if m == "winner":
            what = f"{name} {home if side == 'home' else away}"
        elif m == "spread":
            what = f"{name} {home if side == 'home' else away} {fmt_num(line, signed=True) if line is not None else ''}".strip()
        else:
            what = f"{name} {'Over' if side != 'under' else 'Under'} {fmt_num(line) if line is not None else ''}".strip()
    return f"{away} @ {home} · {what} · {odds} · {stake} · {status}"


def change_items(items: list[dict], mode: str, cats: list) -> tuple[bool, str]:
    """Kategorien der Wetten aendern (hinzufuegen / entfernen / ersetzen). Rueckgabe (ok, Meldung); wirft nie."""
    names = bc.names()
    if not items:
        return True, "Keine Wetten zum Ändern."
    if not cats:
        return False, "Bitte mindestens eine Kategorie wählen."
    try:
        res = ds.change_categories([{"key": i["key"], "kind": i["kind"], "id": i["id"]} for i in items], mode, cats)
    except (ds.BetInputError, ds.DayBetsError) as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unerwarteter Fehler beim Ändern ({type(e).__name__}); es wurde nichts geändert."
    text = f"{res['changed']} Wette(n) geändert ({MODE_LABELS[mode]}: {', '.join(names[c] for c in bc.normalize(cats))})"
    if res["unchanged"]:
        text += f", {res['unchanged']} waren schon so"
    if res["skipped"]:
        text += f", {len(res['skipped'])} übersprungen (falsche Wettart oder es bliebe keine Kategorie)"
    return True, text + ". Einsatz, Quote, Status und Ergebnis sind unverändert."


def rename_all(new_names: dict) -> tuple[bool, str]:
    """Geaenderte Namen speichern ({id: Name}). Rueckgabe (ok, Meldung); bei einem Fehler wird nichts geaendert."""
    cur = bc.names()
    changed = {cid: n for cid, n in new_names.items() if cid in bc.ALL_IDS and " ".join(str(n or "").split()) != cur[cid]}
    if not changed:
        return True, "Keine Änderung."
    try:
        bc.rename_many(changed)
    except bc.CategoryError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unerwarteter Fehler beim Speichern der Namen ({type(e).__name__}); es wurde nichts geändert."
    return True, "Namen gespeichert."


# ----------------------------------------------------------------------------------------------- Streamlit
def _set_msg(res: tuple[bool, str]) -> None:
    st.session_state["bl_msg"] = {"ok": res[0], "text": res[1]}


def _on_change_one(item: dict, widget_key: str) -> None:
    cats = st.session_state.get(widget_key) or []
    if not cats:
        _set_msg((False, "Eine Wette braucht mindestens eine Kategorie; nichts geändert."))
    elif bc.normalize(cats) != item_categories(item):
        _set_msg(change_items([item], "replace", cats))


def _on_bulk_ask(visible: list[dict], mode_key: str, cats_key: str) -> None:
    ss = st.session_state
    mode, cats = ss.get(mode_key), bc.normalize(ss.get(cats_key) or [])
    if not cats:
        _set_msg((False, "Bitte mindestens eine Kategorie wählen."))
        return
    plan = plan_change(visible, mode, cats)
    ss["bl_confirm"] = {"mode": mode, "cats": cats, "n": len(plan["apply"]), "of": len(visible), "same": plan["same"], "skipped": len(plan["skipped"]),
                        "items": [{k: i[k] for k in ("kind", "key", "id")} for i in plan["apply"]]}


def _on_bulk_yes() -> None:
    c = st.session_state.pop("bl_confirm", None)
    if c:
        # die Wetten wurden beim Klick auf "Aendern ..." festgelegt (die Anzahl in der Bestaetigung gilt)
        _set_msg(change_items(c["items"], c["mode"], c["cats"]))


def _on_bulk_no() -> None:
    st.session_state.pop("bl_confirm", None)


def _on_rename(keys: dict) -> None:
    _set_msg(rename_all({cid: st.session_state.get(k) for cid, k in keys.items()}))


@st.fragment
def render_bet_list() -> None:
    """Bereich 'Wettliste' (aufklappbar, Fragment ohne Takt) im Tab Spieltag. Liest nur Dateien und den schon geholten Feed-Stand (kein Netzabruf)."""
    from ui import live_tab as lt
    ss = st.session_state
    state = lf.get_feed().state()
    page = lt.get_page(state)
    items = collect_items(page.get("bet_rows") or [])
    nm = bc.names()
    with st.expander(f"Wettliste nach Kategorien · {len(items)} Wette(n)", expanded=False):          # beim Betreten des Tabs geschlossen
        err = ds.load_error()
        if err:
            st.error(err)
            return
        msg = ss.pop("bl_msg", None)
        if msg:
            (st.success if msg["ok"] else st.error)(msg["text"])
        sums = summary_by_category(items)
        flt = st.selectbox("Kategorie", filter_options(), format_func=lambda f: filter_label(f, nm), key="bl_filter")
        if items:
            st.table(summary_rows(sums, nm))
            st.caption("Wetten in mehreren Kategorien zählen mehrfach (die Kategorie-Summen ergeben zusammen mehr als „Alle“). Bei „Alle“ zählt jede Wette genau einmal.")
        st.markdown(lc.flat(lc.render_summary_html(sums[flt])), unsafe_allow_html=True)
        visible = filter_items(items, flt)
        if not visible:
            st.caption("Keine Wetten in dieser Auswahl.")
        for it in visible:
            c1, c3 = st.columns([5, 3])
            c1.markdown(item_text(it))
            cur = item_categories(it)
            opts = list(bc.ids_for_kind(it["kind"]))
            wk = f"bl_cat_{it['kind']}_{it['key']}_{it['id']}_{'-'.join(cur) or 'none'}"
            c3.multiselect("Kategorien", opts, default=[c for c in cur if c in opts], placeholder="Ohne Kategorie – hier wählen", format_func=lambda c: nm[c], key=wk,
                           label_visibility="collapsed", on_change=_on_change_one, args=(it, wk))
        if visible:
            st.markdown("**Alle sichtbaren Wetten ändern**")
            b0, b1, b2 = st.columns([1.6, 2.4, 1.2])
            mk, tk = "bl_bulk_mode", "bl_bulk_cats"
            b0.selectbox("Aktion", list(MODE_LABELS), format_func=MODE_LABELS.get, key=mk, label_visibility="collapsed")
            b1.multiselect("Kategorien", list(bc.ALL_IDS), format_func=lambda c: f"{nm[c]} ({'Team' if bc.kind_of(c) == 'team' else 'Spieler'})", key=tk, label_visibility="collapsed",
                           placeholder="Kategorien wählen …")
            b2.button("Ändern …", key="bl_bulk_ask", on_click=_on_bulk_ask, args=(visible, mk, tk))
        conf = ss.get("bl_confirm")
        if conf:
            rest = conf["of"] - conf["n"]
            st.warning(f"{MODE_LABELS[conf['mode']]}: {', '.join(nm[c] for c in conf['cats'])} – {conf['n']} Wette(n) werden geändert."
                       + (f" {rest} der {conf['of']} sichtbaren Wetten bleiben unverändert ({conf['same']} schon so, {conf['skipped']} nicht anwendbar)." if rest else "")
                       + " Nur die Kategorien ändern sich, nie Einsatz, Quote, Status oder die Zahl der Wetten.")
            y, n_, _ = st.columns([1, 1, 4])
            y.button("Ja, ändern", key="bl_yes", type="primary", on_click=_on_bulk_yes, disabled=not conf["n"])
            n_.button("Abbrechen", key="bl_no", on_click=_on_bulk_no)
        if st.toggle("Kategorien umbenennen", value=False, key="bl_rename_on"):             # kein Expander: Expander lassen sich nicht schachteln
            st.caption("Die Kategorien sind fest; nur die Namen sind änderbar. Die Zuordnung der Wetten bleibt beim Umbenennen erhalten.")
            keys = {}
            cols = st.columns(4)
            for col, cid in zip(cols, bc.ALL_IDS):
                keys[cid] = f"bl_name_{cid}_{nm[cid]}"
                col.text_input(f"{'Team' if bc.kind_of(cid) == 'team' else 'Spieler'}: {bc.DEFAULT_NAMES[cid]}", value=nm[cid], max_chars=bc.MAX_NAME_LEN, key=keys[cid])
            st.button("Namen speichern", key="bl_rename", on_click=_on_rename, args=(keys,))
