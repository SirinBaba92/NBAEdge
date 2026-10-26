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
from data import betano_skipped
from data import live_feed as lf
from data import pre_match_store as store
from engine import player_odds as po
from engine import player_snapshots as psn
from ui import live_tab as lt
from ui import player_view as pv
from ui.live_card import LIVE_CSS, flat
from data import absences_store as ab
from ui.player_absence import render_absences
from ui.bet_cards_component import is_selectable, render_bet_cards
from ui.player_bet_entry import render_player_bet_entry
from ui.score_cards import CARD_CSS

BERLIN = ZoneInfo("Europe/Berlin")
AUTO_SECONDS = 30
TABLE_WINDOW = 5.0                 # Standardansicht der Spielertabelle: Meilensteine bis so viele Punkte neben der erwarteten Punktzahl


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


# ----------------------------------------------------------------------------------------------- Zwischenspeicher (gemeinsame Rechnungen)
_MEMO: dict = {}
MEMO_MAX = 24


def _sig(path) -> tuple:
    try:
        st_ = path.stat()
        return (st_.st_mtime_ns, st_.st_size)
    except OSError:
        return (None, None)


def memo(name: str, key, fn):
    """Kleiner Zwischenspeicher je Name: gleicher Schluessel = gleiches Ergebnis (Rechnungen sind rein). Hoechstens MEMO_MAX Eintraege je Name, aelteste fliegen raus."""
    bucket = _MEMO.setdefault(name, {})
    if key in bucket:
        return bucket[key]
    val = fn()
    bucket[key] = val
    while len(bucket) > MEMO_MAX:
        bucket.pop(next(iter(bucket)))
    return val


def cached_entries() -> dict:
    """Pre-Match-Eintraege (data/tracking/pre_match_entries.json, ca. 3 MB) nur neu lesen, wenn sich die Datei aendert. NICHT veraendern."""
    return memo("entries", _sig(store.store_path()), lambda: store.load()["entries"])


def cached_games_with_players(entries: dict) -> list[str]:
    return memo("games", _sig(store.store_path()), lambda: games_with_players(entries))


def cached_snapshot(key: str):
    """Prognose-Snapshot eines Spiels, nur neu gelesen, wenn sich die Datei aendert. NICHT veraendern."""
    return memo("snapshot", (key, _sig(ds.forecast_snapshot_path(key.split("|", 1)[0]))), lambda: ds.load_forecast_snapshot(key))


def game_signature(game) -> tuple:
    """Alles, wovon Live-Rechnungen eines Spiels abhaengen (Stand, Uhr, Spielerwerte, Datenzustand): bleibt es gleich, bleibt auch das Ergebnis gleich."""
    if game is None:
        return ("kein Spiel",)
    return (game.game_id, game.home_score, game.away_score, game.clock.phase, game.clock.period, game.clock.seconds_left, bool(getattr(game, "data_stale", False)), game.source,
            tuple((p.person_id, p.points, p.minutes, p.fouls, p.status, int(p.idle_s)) for p in game.players))


def player_bet_rows(state, day_player_bets: dict) -> list[dict]:
    """Spieler-Wetten des Spieltags mit Live-Status: [{'key', 'game' (GameView|None), 'info' (Spieldaten der Wette), 'bets' {person_id: Wette}, 'lives' {person_id: BetLivePlayer}}], nach Anpfiff.
    Spiel nicht im Scoreboard: game None, lives leer (Wetten bleiben sichtbar, ohne Status). Nur lesend."""
    rows = []
    for key, v in sorted(day_player_bets.items(), key=lambda kv: (kv[1]["game"].get("start_utc") or "", kv[0])):
        g = lf.find_game(state, v["game"]["game_date"], v["game"]["home"], v["game"]["away"])
        snap = cached_snapshot(key)
        pre = {int(p["person_id"]): p for p in (snap or {}).get("players", [])}
        lives = memo("bet_lives", (key, game_signature(g), repr(sorted((pid, b.get("milestone"), b.get("active", True)) for pid, b in v["player_bets"].items())), id(snap)),
                     lambda: ds.evaluate_player_bets(v["player_bets"], g, pre)) if g is not None else {}
        rows.append({"key": key, "game": g, "info": v["game"], "bets": v["player_bets"], "lives": lives})
    return rows


def game_for_key(state, key: str):
    """Spiel des Live-Feeds zu einem game_key (Spieltag + Spitznamen), sonst None."""
    d, _, home, away = key.split("|")[:4]
    return lf.find_game(state, d, home, away)


def live_table_data(game, entry: dict, shown: dict | None = None) -> dict:
    """Live-Werte je Spieler des Snapshots fuer die Tabelle: {person_id: {'points', 'minutes', 'fouls', 'status', 'chances': {N: Anteil}, 'notes', 'out'}}. Nur fuer laufende Spiele mit
    Spielerliste und nicht auf veralteten Daten, sonst {}. Rechnet engine/player_live.live_chance (UNGEPRUEFT). shown: {person_id: {Meilensteine}} - nur diese Zeilen werden gerechnet (Standard: alle)."""
    from engine import player_live as plive
    if game is None or not game.clock.is_live or getattr(game, "data_stale", False) or not game.players:
        return {}
    by_id = {int(p.person_id): p for p in game.players}
    out = {}
    for sp in entry.get("players", []):
        pl = by_id.get(int(sp["person_id"]))
        if pl is None:
            continue
        chances, notes, is_out = {}, [], False
        for q in sp.get("quotes") or []:
            if shown is not None and q["milestone"] not in shown.get(int(sp["person_id"]), ()):
                continue
            try:
                lc_ = plive.live_chance(q["milestone"], pl, game.clock, game.home_score, game.away_score, sp)
            except Exception:
                continue
            chances[q["milestone"]] = lc_.probability
            notes, is_out = list(lc_.notes), is_out or lc_.out
        out[int(sp["person_id"])] = {"points": pl.points, "minutes": pl.minutes, "fouls": pl.fouls, "status": pl.status, "chances": chances, "notes": notes, "out": is_out}
    return out


def bets_summary(rows: list[dict]) -> dict:
    """Tagessumme: alle gespeicherten Wetten zaehlen bei 'Wetten' und 'Einsatz'; offen/gewonnen/verloren/nicht gespielt/Gewinn nur mit Status (ds.summarize)."""
    lives = [bl for r in rows for bl in r["lives"].values()]
    s = ds.summarize(lives) if lives else {"wetten": 0, "offen": 0, "gewonnen": 0, "verloren": 0, "einsatz": 0.0, "einsatz_abgerechnet": 0.0, "gewinn_verlust": 0.0, "ohne_quote_oder_einsatz": 0}
    total = sum(len(r["bets"]) for r in rows)
    out = dict(s)
    out.update(wetten=total, einsatz=round(sum((b.get("stake") or 0.0) for r in rows for b in r["bets"].values()), 2), ohne_status=total - s["wetten"])
    out.setdefault("nicht_gespielt", 0)
    return out


def bets_html(rows: list[dict]) -> tuple[str, list[str]]:
    """(Tagessumme als HTML, Karten als HTML) der Spieler-Wetten."""
    cards = []
    for r in rows:
        g = r["game"]
        label = f"{g.away_nick} @ {g.home_nick}" if g is not None else f"{r['info']['away']} @ {r['info']['home']}"
        score = None if g is None or g.status == "PRE" else f"{g.away_score} : {g.home_score}"
        for pid, bet in r["bets"].items():
            cards.append(pv.bet_card_html(bet, r["lives"].get(pid), label, None if g is None else g.clock_label, score, None if g is None else g.status, bool(g is not None and getattr(g, "data_stale", False))))
    return pv.bet_summary_html(bets_summary(rows)), cards


# ----------------------------------------------------------------------------------------------- Streamlit
@st.fragment(run_every=AUTO_SECONDS)
def _my_bets() -> None:
    """'Meine Spieler-Wetten' (alle 30 s, nur dieser Teil): Tagessumme und eine Karte je Wette mit Live-Status aus dem schon geholten Boxscore. Ruft wie der Spieltag-Tab ueber den gemeinsamen Feed ab."""
    state = lt.pick_state(lf.get_feed(), False, st.session_state.get("sp_auto", True), lt._fragment_rerun())
    rows = player_bet_rows(state, ds.get_day_player_bets(state.day))
    st.markdown(f"### 🎯 Meine Spieler-Wetten · Spieltag {state.day}")
    summary, cards = bets_html(rows)
    st.markdown(flat(summary), unsafe_allow_html=True)
    if cards:
        st.markdown(flat("".join(cards)), unsafe_allow_html=True)
    err = ds.load_error()
    if err:
        st.error(err)
    st.markdown(flat(lt.lc.render_status_html(state)), unsafe_allow_html=True)


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


def _render_table(key: str, entry: dict, mode: str, sort: str, state, show_all: bool = False, table_view: bool = False) -> None:
    game = game_for_key(state, key)
    window = None if show_all else TABLE_WINDOW
    absences = ab.get(key)
    model = pv.build_table_model(entry, mode, sort, ds.get_player_bets_by_key(key), None, absences, window)
    if not table_view and (absences["out"] or absences["doubtful"]):                  # Kartenansicht: Werte der Variante mit Ausfaellen, falls sie zur Auswahl passt (nur Darstellung)
        variant = psn.latest_variant(key, set(absences["out"]), set(absences["doubtful"]))
        if variant is not None:
            model = pv.attach_variant(pv.build_table_model(variant["entry"], mode, sort, ds.get_player_bets_by_key(key), None, None, window), entry, mode)
    shown = pv.shown_milestones(model)
    live = memo("live_table", (key, id(entry), mode, window, game_signature(game), repr(sorted((k, tuple(sorted(v))) for k, v in shown.items()))), lambda: live_table_data(game, entry, shown))
    pv.attach_live(model, live)
    if game is not None and game.clock.is_live:
        score = f"{game.away_score} : {game.home_score} ({game.clock_label}, Abstand {abs(game.home_score - game.away_score)})"
        extra = " · Stand von " + game.source if game.source != "NBA.com" else ""
        st.markdown(f"<div class='pl-info'>Spiel läuft: {pv.escape(game.away_nick)} {pv.escape(score)} {pv.escape(extra)}. Live-Chance = Chance auf den Meilenstein aus Restzeit, erwarteten Minuten (Fouls, Blowout) und Punkten je Minute: UNGEPRÜFT (Version {plive_version()}).</div>", unsafe_allow_html=True)
    if not table_view and is_selectable(key) and ds.player_bet_options(key, entries=cached_entries())["players"]:
        # vor dem Anpfiff: anklickbare Karten mit Wettschein (Komponente); der Ausfall-Kasten bleibt ein normaler Streamlit-Teil darueber
        if absences["out"] or absences["doubtful"]:
            st.markdown(flat(pv.absence_box_html(absences)), unsafe_allow_html=True)
        render_bet_cards(key, cached_entries(), pv.render_cards_html(model), pv.PLAYER_CSS + pv.CARDS_CSS)
    else:
        st.markdown(flat(pv.render_table_html(model) if table_view else pv.render_cards_html(model, absences)), unsafe_allow_html=True)
    if model["hidden_rows"]:
        st.caption(f"Standardansicht: Meilensteine um die erwartete Punktzahl (±{TABLE_WINDOW:g}) und eigene Wetten; {model['hidden_rows']} weitere Zeilen ausgeblendet („Alle Meilensteine anzeigen“ schaltet sie ein).")


def plive_version() -> str:
    from engine import player_live as plive
    return plive.LIVE_VERSION


@st.fragment(run_every=AUTO_SECONDS)
def _table_live(key: str, entry: dict, mode: str, sort: str, show_all: bool = False, table_view: bool = False) -> None:
    """Tabelle eines LAUFENDEN Spiels: alle 30 s neu (gemeinsamer Feed), mit Spalten 'Jetzt' und 'Live'."""
    state = lt.pick_state(lf.get_feed(), False, st.session_state.get("sp_auto", True), lt._fragment_rerun())
    _render_table(key, entry, mode, sort, state, show_all, table_view)


@st.fragment
def _forecast_view() -> None:
    """Prognose-Ansicht (Fragment ohne Takt): Spiel waehlen, Tabelle, Umschalter und Sortierung."""
    entries = cached_entries()
    days = sorted({k.split('|', 1)[0] for k in cached_games_with_players(entries)})
    if not days:
        st.info("Noch keine Spielerquoten gespeichert. Sie kommen aus dem Tab „Pre-Match Eingabe“ (Markt Spielerpunkte / Betano-Import).")
        return
    c1, c2 = st.columns([1, 3])
    day_default = default_day(days)
    with c1:
        day = st.selectbox("Spieltag", days, index=days.index(day_default), key="pl_day")
    keys = [k for k in cached_games_with_players(entries) if k.startswith(day + "|")]
    with c2:
        key = st.selectbox("Spiel", keys, format_func=game_label, key=f"pl_game_{day}")
    msg = st.session_state.pop("pl_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    entry = cached_snapshot(key)
    mode = "team"
    table_view = False
    if entry is None:
        st.info("Für dieses Spiel gibt es noch keinen Prognose-Snapshot." + (" Das Spiel hat bereits begonnen: ein jetzt erstellter Snapshot ist nur eingeschränkt aussagekräftig." if started(key) else ""))
        st.button("Prognose jetzt erstellen", key=f"pl_create_{key}", on_click=_create_clicked, args=(key,),
                  help="Rechnet die Prognose für dieses Spiel (ca. 10 Sekunden, kein Netzabruf) und speichert sie einmalig als Snapshot.")
    else:
        _snapshot_notes(entry)
        o1, o2, o3 = st.columns([1, 1, 1])
        with o3:
            table_view = st.toggle("Tabellenansicht", value=False, key="pl_table_view", help="Aus: Spieler-Karten (Standard). An: die bisherige Tabelle.")
            show_all = st.toggle("Alle Meilensteine anzeigen", value=False, key="pl_all", help=f"Aus: nur Meilensteine um die erwartete Punktzahl (±{TABLE_WINDOW:g}) und eigene Wetten (kleinere, schnellere Tabelle).")
        with o1:
            mode = st.radio("Modell", list(pv.MODES), format_func=pv.MODES.get, horizontal=True, key="pl_mode", help="Teamabgleich: Summe der Spieler an den Teampunkten des Spielmodells ausgerichtet. roh: Einzelprognose ohne Abgleich.")
        with o2:
            sort = st.radio("Sortierung", list(pv.SORTS), format_func=pv.SORTS.get, horizontal=True, key="pl_sort")
        game = game_for_key(lf.get_feed().state(), key)
        if game is not None and game.clock.is_live:
            _table_live(key, entry, mode, sort, show_all, table_view)       # laufendes Spiel: Tabelle mit Live-Spalten im 30-s-Takt
        else:
            _render_table(key, entry, mode, sort, lf.get_feed().state(), show_all, table_view)
        skipped = betano_skipped.caption(key)
        if skipped:
            st.caption(skipped)
        st.caption(f"◀ Modell mindestens {pv.fmt_num(pv.MARK_PP, 0)} Prozentpunkte über dem Buchmacher, ▼ darunter. Differenz = Modell minus Buchmacher-Chance (inkl. Marge), aus ungerundeten Werten. "
                   "⚠ bewegt man die Maus darüber: Datenqualität und Hinweise. 🎯 = meine Wette.")
    render_player_bet_entry(key, entries)
    render_absences(key, entries, entry, mode, show_compare=table_view)


def render_player_tab() -> None:
    """Inhalt des Tabs '🏃 Spieler' (aus app.py aufgerufen)."""
    st.markdown("## 🏃 Spieler")
    st.markdown(flat(CARD_CSS + LIVE_CSS + pv.PLAYER_CSS + pv.CARDS_CSS), unsafe_allow_html=True)
    st.markdown(f"<div class='pl-banner'>{pv.escape(pv.UNVERIFIED_TEXT)}</div>", unsafe_allow_html=True)
    if OFFLINE_AUDIT_MODE:
        st.info("Offline-Prüfmodus: Der Spieler-Tab zeigt nichts an.")
        return
    _my_bets()
    st.markdown("### Prognose")
    _forecast_view()
