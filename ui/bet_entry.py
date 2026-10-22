"""
Bereich "Wetten eintragen" im Tab "🏀 Spieltag" (Baustein 6): Wetten per Auswahl erfassen, speichern ueber data/day_bets_store.py. Kein Netzabruf, keine Odds-Credits.

Der Bereich steht AUSSERHALB der 30-Sekunden-Fragmente des Tabs (ui/live_tab.py), damit die automatische Aktualisierung keine Auswahl zuruecksetzt, und ist selbst ein
st.fragment OHNE run_every: Klicks auf Auswahlfelder (Seite, Linie, Quote ...) lassen nur diesen Bereich neu laufen (statt der ganzen App mit allen Tabs; Messung vorher: ca. 2 s je Klick, davon
Pre-Match-Tab 1,3 s, Eintragsbereich nur 0,04 s). Nach Speichern/Entfernen laeuft einmal die ganze App neu (st.rerun), damit Karten, Tagesuebersicht und Zahlen die Wette zeigen (nur Datei lesen, kein Netz). Reine Hilfsfunktionen
(ohne Streamlit) stehen oben und sind in tests/test_spieltag_bets.py einzeln geprueft; die Streamlit-Darstellung unten ruft sie nur auf.

Ablauf: Spiel waehlen (nur Spiele des aktuellen Spieltags; angepfiffene gesperrt, nur zur Ansicht) -> je Markt "keine Wette" / Seite -> Linie (Standard Hauptlinie, nur .5-Linien,
Auswahl aus selectable_lines) -> Quote (aus der gespeicherten Betano-Eingabe vorbelegt, ueberschreibbar, leerbar) und Einsatz (beide optional) -> "Speichern" / "Wette entfernen" je Markt.
Aenderungen laufen immer ueber set_bet/remove_bet (Revisionen, Sperre ab Anpfiff, atomares Schreiben); Fehler werden als deutsche Meldung gezeigt, nie als Absturz.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from data import day_bets_store as ds
from data import live_feed as lf
from data import market_lines
from ui import live_card as lc
from ui.score_cards import fmt_num

BERLIN = ZoneInfo("Europe/Berlin")
NONE_CODE = "none"
LOCK_TEXT = "Wette ab Anpfiff gesperrt"
LINE_KEYS = {"spread": "spread_home", "total": "total", "team_total_home": "team_total_home", "team_total_away": "team_total_away"}
SIDE_CODES = {"winner": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under"), "team_total_home": ("over", "under"), "team_total_away": ("over", "under")}


# ----------------------------------------------------------------------------------------------- Hilfsfunktionen (ohne Streamlit)
def fmt_hhmm_iso(iso: str | None) -> str:
    """'16:27' (Berliner Zeit) aus einem ISO-Zeitstempel; unlesbar: ''."""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BERLIN).strftime("%H:%M")
    except ValueError:
        return ""


def game_editable(game, now: float | None = None) -> bool:
    """Wette moeglich: Anpfiff bekannt und noch nicht erreicht UND das Scoreboard fuehrt das Spiel noch als 'Vor dem Anpfiff'."""
    return game.status == "PRE" and ds.is_bet_editable(game.start_utc, now)


def find_entry(game, entries: dict) -> dict | None:
    """Pre-Match-Eintrag (gespeicherte Betano-/Hand-Quoten) zu diesem Spiel: Spieltag und beide Spitznamen."""
    for entry in (entries or {}).values():
        if entry.get("game_date") == game.day and lf.same_team(entry.get("home"), game.home_nick) and lf.same_team(entry.get("away"), game.away_nick):
            return entry
    return None


def main_lines_and_sources(game, snapshots: dict, entries: dict, anchor=None) -> tuple[dict, dict]:
    """Hauptlinien wie auf der Karte (Schnappschuss, dann eigene Eingabe, fehlende aus dem Modell) plus Herkunft je Markt:
    ({'spread_home', 'total', 'team_total_home', 'team_total_away'}, {schluessel: {'label', 'bookmaker', 'at'}})."""
    from ui.live_tab import market_lines_for
    ml = market_lines_for(game, snapshots, entries)
    lines, tags = lc.merge_main_lines(ml, anchor)
    sources = {k: {"label": None, "bookmaker": None, "at": None} for k in lines}
    found = lf.find_snapshot(game, snapshots)
    mk = (found[1].get("markets") or {}) if found else {}
    entry = find_entry(game, entries)
    own = market_lines.own_candidates(entry) if entry else {}
    for market, key in LINE_KEYS.items():
        if lines.get(key) is None:
            continue
        d = mk.get(market) or {}
        if tags.get(key) == "Modell-Linie":
            sources[key] = {"label": "Modell-Linie (keine Marktlinie)", "bookmaker": None, "at": None}
        elif d.get("line") is not None:
            sources[key] = {"label": d.get("source") or "Schnappschuss", "bookmaker": d.get("bookmaker") or None, "at": d.get("line_at")}
        elif own.get(market):
            sources[key] = {"label": "eigene Eingabe", "bookmaker": own[market].get("bookmaker") or None, "at": own[market].get("at_iso")}
        else:
            sources[key] = {"label": "rechnerisch aus Total und Spread", "bookmaker": None, "at": None}
    return lines, sources


def line_options(market: str, main_lines: dict, side: str | None, saved_line=None) -> list[float]:
    """Auswaehlbare Linien (selectable_lines: Hauptlinie +- 5, alle .5); eine bereits gespeicherte Linie ausserhalb des Fensters bleibt waehlbar."""
    if market == "winner":
        return []
    sel = ds.selectable_lines(main_lines)
    opts = sel["spread"][side or "home"]["lines"] if market == "spread" else sel[market]["lines"]
    opts = list(opts)
    if saved_line is not None and all(abs(saved_line - x) > 1e-9 for x in opts):
        opts = sorted(opts + [float(saved_line)])
    return opts


def default_line_for(market: str, main_lines: dict, side: str | None):
    key = LINE_KEYS.get(market)
    return None if key is None else ds.default_line(market, main_lines.get(key), side)


def prefill_odds(entry: dict | None, market: str, side: str, line) -> dict | None:
    """Gespeicherte Quote fuer Seite und Linie (Betano-Eingabe) mit Beschriftung: {'odds', 'text' ('1,85'), 'label' ('Betano, Stand 16:27')} oder None."""
    so = ds.stored_odds(entry, market, side, line)
    if not so:
        return None
    hhmm = fmt_hhmm_iso(so.get("updated_at"))
    label = (so.get("bookmaker") or "gespeichert") + (f", Stand {hhmm}" if hhmm else "")
    return {"odds": float(so["odds"]), "text": fmt_num(float(so["odds"]), 2).replace(".", ","), "label": label}


def side_label(market: str, code: str, game) -> str:
    if code == NONE_CODE:
        return "keine Wette"
    if market in ("winner", "spread"):
        return f"{game.home_nick} (Heim)" if code == "home" else f"{game.away_nick} (Gast)"
    return "Over" if code == "over" else "Under"


def line_label(market: str, x: float, side: str | None, main, game) -> str:
    tag = " (Hauptlinie)" if main is not None and abs(x - main) < 1e-9 else ""
    if market == "spread":
        return f"{game.home_nick if side == 'home' else game.away_nick} {fmt_num(x, signed=True)}{tag}"
    return f"{fmt_num(x)}{tag}"


def bet_text(game, market: str, bet: dict) -> str:
    """'Total: Under 231,5 · Quote 1,90 · Einsatz 20,00' (gespeicherter Stand)."""
    odds = f"Quote {lc.fmt_money(bet.get('odds'))}" + (f" ({bet['odds_source']})" if bet.get("odds_source") else "")
    return f"{lc.market_title(market, game)}: {lc.bet_label(market, bet, game)} · {odds} · Einsatz {lc.fmt_money(bet.get('stake'))}"


def save_market_bet(game, market: str, side: str, line, odds_text, stake, info: dict | None = None, prefill: dict | None = None, now: float | None = None) -> tuple[bool, str]:
    """Wette eines Marktes speichern. Rueckgabe (ok, Meldung); jeder Fehler wird zu einer verstaendlichen deutschen Meldung, nichts wird geworfen.
    odds_source: 'gespeichert' (Quote unveraendert aus der Betano-Eingabe), sonst 'manuell'. line_ref: Hauptlinie (aus Sicht der gewaehlten Seite), gewaehlte Linie, Quelle, Zeit, Buchmacher."""
    try:
        odds = ds.parse_odds_optional(odds_text)
        source = None
        if odds is not None:
            source = "gespeichert" if prefill and abs(prefill["odds"] - odds) < 1e-9 else "manuell"
        ref = None
        if market != "winner" and info is not None:
            main_home = info.get("main_home_view")
            main_side = None if main_home is None else default_line_for(market, {LINE_KEYS[market]: main_home}, side)
            ref = ds.make_line_ref(main_side, line, source=info.get("label"), at=info.get("at"), bookmaker=info.get("bookmaker"))
        res = ds.set_bet(game.day, game.start_utc, game.home, game.away, market, side=side, line=line, odds=odds, stake=stake, odds_source=source, line_ref=ref, now=now)
    except ds.GameStartedError as e:
        return False, f"{LOCK_TEXT}: {e}"
    except ds.BetInputError as e:
        return False, f"Eingabe nicht gespeichert: {e}"
    except ds.DayBetsError as e:
        return False, str(e)
    except Exception as e:                                           # nie ein Absturz
        return False, f"Unerwarteter Fehler beim Speichern ({type(e).__name__}); es wurde nichts geändert."
    head = "Gespeichert" if res["status"] == "saved" else "Unverändert (so bereits gespeichert)"
    return True, f"{head}: {bet_text(game, market, res['bet'])}"


def remove_market_bet(game, market: str, now: float | None = None) -> tuple[bool, str]:
    """Wette eines Marktes entfernen (nicht loeschen: bleibt als Revision erhalten). Rueckgabe (ok, Meldung)."""
    try:
        res = ds.remove_bet(game.day, game.start_utc, game.home, game.away, market, now=now)
    except ds.GameStartedError as e:
        return False, f"{LOCK_TEXT}: {e}"
    except ds.DayBetsError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unerwarteter Fehler beim Entfernen ({type(e).__name__}); es wurde nichts geändert."
    if res["status"] == "none":
        return True, f"{lc.market_title(market, game)}: keine aktive Wette zu entfernen."
    return True, f"Entfernt: {bet_text(game, market, res['bet'])} (bleibt als Verlauf in der Datei erhalten)"


def game_label(game, now: float | None = None) -> str:
    base = f"{game.away_nick} @ {game.home_nick} · {lc.fmt_start(game.start_utc)}"
    return base if game_editable(game, now) else f"{base} · 🔒 {LOCK_TEXT}"


# ----------------------------------------------------------------------------------------------- Knopf-Aktionen (laufen VOR dem Neuaufbau der Seite)
def _set_msg(game, result: tuple[bool, str]) -> None:
    st.session_state["be_msg"] = {"ok": result[0], "text": result[1], "game": game.game_id}
    if result[0]:
        st.session_state["be_dirty"] = True          # Daten haben sich geaendert (oder wurden bestaetigt): Karten/Uebersicht muessen neu gebaut werden


def _on_save(game, market: str, side: str, line_key, odds_key: str, stake_key: str, info, prefill) -> None:
    """Callback von 'Speichern': liest die Feldwerte aus dem Session State und speichert; danach baut sich die Seite mit dem neuen Stand und der Bestaetigung auf (kein st.rerun noetig)."""
    ss = st.session_state
    stake = ss.get(stake_key)
    _set_msg(game, save_market_bet(game, market, side, ss.get(line_key) if line_key else None, ss.get(odds_key), stake if stake else None, info, prefill))


def _on_game_change() -> None:
    st.session_state["be_game_sel"] = st.session_state["be_game"]


def _on_remove(game, market: str) -> None:
    _set_msg(game, remove_market_bet(game, market))


# ----------------------------------------------------------------------------------------------- Streamlit-Darstellung
def _token(bet: dict | None) -> str:
    """Stand der gespeicherten Wette als Schluesselteil: aendert sich beim Speichern/Entfernen, damit die Felder neu aus dem Speicher belegt werden."""
    import hashlib
    return "neu" if not bet or not bet.get("active") else hashlib.md5(str(bet.get("updated_at")).encode()).hexdigest()[:8]


def _market_form(st, game, market: str, bet: dict | None, ctx: dict) -> None:
    """Eine Zeile je Markt. Schluessel enthalten Spiel, Markt und den Stand der gespeicherten Wette (token): nach Speichern/Entfernen werden die Felder aus dem Speicher neu belegt."""
    active = bet if bet and bet.get("active") else None
    p = f"be_{game.game_id}_{market}_{_token(bet)}"
    title = lc.market_title(market, game)
    with st.container(border=True):
        st.markdown(f"**{title}**" + (f" · gespeichert: {bet_text(game, market, active)[len(title) + 2:]}" if active else ""))
        codes = (NONE_CODE,) + SIDE_CODES[market]
        idx = codes.index(active["side"]) if active and active["side"] in codes else 0
        cols = st.columns([1.5, 1.6, 1.0, 1.0])
        side = cols[0].selectbox("Seite", codes, index=idx, format_func=lambda c: side_label(market, c, game), key=f"{p}_side")
        if side == NONE_CODE:
            if active:
                st.button("Wette entfernen", key=f"{p}_remove", on_click=_on_remove, args=(game, market))
            return
        line, info, pre = None, None, None
        if market != "winner":
            main_key = LINE_KEYS[market]
            main_home = ctx["lines"].get(main_key)
            default = default_line_for(market, ctx["lines"], side)
            saved_line = active["line"] if active and active["side"] == side else None
            opts = line_options(market, ctx["lines"], side, saved_line)
            if not opts:
                cols[1].caption("Keine Hauptlinie bekannt: Linie kann nicht gewählt werden (nur Sieger).")
                return
            start = saved_line if saved_line is not None else default
            line = cols[1].selectbox("Linie", opts, index=opts.index(start) if start in opts else 0, format_func=lambda x: line_label(market, x, side, default, game), key=f"{p}_line_{side}")
            info = {**ctx["sources"][main_key], "main_home_view": main_home}
        pre = prefill_odds(ctx["entry"], market, side, line)
        same_as_saved = bool(active and active["side"] == side and active.get("line") == line)
        if same_as_saved:
            start_text = "" if active.get("odds") is None else fmt_num(float(active["odds"]), 2)
        else:
            start_text = "" if pre is None else pre["text"]
        lk = "w" if line is None else f"{line:.1f}"
        odds_text = cols[2].text_input("Quote (optional)", value=start_text, placeholder="z. B. 1,85", key=f"{p}_odds_{side}_{lk}")
        stake = cols[3].number_input("Einsatz (optional)", min_value=0.0, value=(active or {}).get("stake"), step=1.0, format="%.2f", key=f"{p}_stake")
        if pre:
            st.caption(f"Quote vorbelegt aus {pre['label']} – überschreibbar oder leer lassen.")
        elif not same_as_saved:
            st.caption("Keine gespeicherte Quote für diese Seite und Linie.")
        b1, b2, _ = st.columns([1, 1.3, 4])
        b1.button("Speichern", key=f"{p}_save", type="primary", on_click=_on_save,
                  args=(game, market, side, None if line is None else f"{p}_line_{side}", f"{p}_odds_{side}_{lk}", f"{p}_stake", info, pre))
        if active:
            b2.button("Wette entfernen", key=f"{p}_remove", on_click=_on_remove, args=(game, market))


def _in_fragment_rerun() -> bool:
    """True, wenn dieser Lauf ein reiner Fragment-Lauf ist (Klick in einem Feld des Fragments), False bei einem Lauf der ganzen App."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return bool(ctx and ctx.fragment_ids_this_run)
    except Exception:
        return False


@st.fragment
def render_bet_entry() -> None:
    """Bereich 'Wetten eintragen' (aufklappbar), ein eigenes Fragment ohne Takt. Aufruf aus ui/live_tab.render_spieltag_tab zwischen den beiden Takt-Fragmenten."""
    if st.session_state.pop("be_dirty", False) and _in_fragment_rerun():
        st.rerun()                                       # nach Speichern/Entfernen: ganze App einmal neu, damit Karten, Uebersicht und Zahlen die Wette zeigen (die Meldung bleibt dafuer erhalten)
    feed = lf.get_feed()
    state = feed.state()
    day_bets = ds.get_day_bets(state.day)
    st.session_state.setdefault("be_expanded", not bool(day_bets))          # einmal je Sitzung: offen, wenn noch keine Wetten gespeichert sind (springt spaeter nicht um)
    now = time.time()
    with st.expander("Wetten eintragen", expanded=st.session_state["be_expanded"]):
        err = ds.load_error()
        if err:
            st.error(f"{err} Das Eintragen ist gesperrt, es wird nichts überschrieben. Bitte die Datei data/tracking/day_bets.json prüfen (eine Sicherungskopie day_bets.corrupt-*.json liegt daneben, sobald ein Speichern versucht wurde).")
            return
        games = sorted(state.games, key=lambda g: (g.start_utc or "", g.game_id))
        if not games:
            st.info("Keine Spiele für diesen Spieltag im Scoreboard: Wetten können erst eingetragen werden, wenn die Spiele gelistet sind.")
            return
        by_id = {g.game_id: g for g in games}
        ids = [g.game_id for g in games]
        first_open = next((g.game_id for g in games if game_editable(g, now)), ids[0])
        # Die Auswahl steht zusaetzlich in einem eigenen Schluessel (be_game_sel, nur durch den Wechsel-Callback geaendert): aendert sich die Beschriftung einer Option (z. B. "gesperrt" nach
        # dem Anpfiff), bekommt Streamlit eine neue Widget-Identitaet und setzt das Feld zurueck; dann gilt wieder die gemerkte Auswahl statt der ersten Option.
        sel = st.session_state.get("be_game_sel")
        if sel not in by_id:
            sel = first_open
            st.session_state["be_game_sel"] = sel
        gid = st.selectbox("Spiel", ids, index=ids.index(sel), format_func=lambda i: game_label(by_id[i], now), key="be_game", on_change=_on_game_change)
        game = by_id[gid]
        msg = st.session_state.pop("be_msg", None)                       # Bestaetigung/Fehler der letzten Knopf-Aktion, nur einmal gezeigt
        if msg and msg.get("game") == gid:
            (st.success if msg["ok"] else st.error)(msg["text"])
        saved = ds.get_bets(game.day, game.start_utc, game.home, game.away, include_removed=True)
        if not game_editable(game, now):
            st.info(f"🔒 {LOCK_TEXT}. Die gespeicherten Wetten sind nur zur Ansicht.")
            active = {m: b for m, b in saved.items() if b.get("active")}
            if not active:
                st.caption("Für dieses Spiel sind keine Wetten gespeichert.")
            for m in ds.MARKETS:
                if m in active:
                    st.markdown(f"- {bet_text(game, m, active[m])}")
            return
        from data import projection_snapshots
        snaps = projection_snapshots.load().get("games", {})
        entries = market_lines.load_entries()
        numbers = lf.live_numbers(game, snaps)
        lines, sources = main_lines_and_sources(game, snaps, entries, numbers.anchor)
        ctx = {"lines": lines, "sources": sources, "entry": find_entry(game, entries)}
        if not numbers.has_anchor:
            st.caption("Kein Schnappschuss für dieses Spiel: Linien kommen aus der eigenen Eingabe oder fehlen; ohne Hauptlinie ist nur der Sieger wählbar.")
        for market in ds.MARKETS:
            _market_form(st, game, market, saved.get(market), ctx)
