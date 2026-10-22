"""
Tab "Pre-Match Eingabe": eigene Quoten pro Spiel vor dem Anpfiff erfassen.
Maerkte: "Sieger inkl. OT", "Spread" (Hauptlinie + weitere Linien) "Total", "Team Totals" und "Spielerpunkte" (Ueber/Unter, Hauptlinie + hoehere/niedrigere Linien; bei Team Totals je Team).
- Weitere Linien (Spread, Total, Team Totals) sind kompakte Einzeiler mit einer Kopfzeile im Expander; der Buchmacher der Zeile folgt dem der Hauptlinie, solange er nicht von Hand geaendert wurde.

- Spiele: dieselben wie in Score Projections (st.session_state.projections), keine zusaetzlichen API-Abrufe.
- Optik: Karte wie in Score Projections (CARD_CSS, Kartenkopf, Logos aus ui/score_cards.py). Die Eingabefelder sind
  echte Streamlit-Widgets in einem Container (mit key), der per CSS wie die Karte aussieht (gleiche Breite bis 1400 px).
- Felder stehen wie im Kartenkopf: links Gast, rechts Heim; der Buchmacher ist das letzte Feld.
- Status-Chip oben rechts (pro Karte): offen (gelb) / gespeichert HH:MM (blaugrau) / gesperrt = grau bzw. kein Chip.
- Eingabebereich je Karte als st.fragment: Klicks auf +/- und Eingaben laden nur die Karte neu, Speichern/Entfernen laedt die ganze App neu.
- Startwerte der Widgets stehen im Session State (vor dem Erzeugen gesetzt), nie zusaetzlich als value= (sonst Streamlit-Warnung).
- EIN Speichern-Knopf am Ende der Karte: speichert alle ausgefuellten Maerkte, alles oder nichts (data/pre_match_store.save_card).
- Spread: beide Linienfelder editierbar und gespiegelt (on_change), nur ganze/halbe Linien, bis zu 3 weitere Linien mit +/- (0,5).
- Eingaben nur vor dem Anpfiff; danach werden gespeicherte Werte nur angezeigt.
- Speicherung und Pruefung: data/pre_match_store.py (data/tracking/pre_match_entries.json).
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from data import pre_match_store as store
from data import rosters
from ui.score_cards import CARD_CSS, PALETTE, render_card_head, team_info

MARKET = store.WINNER
BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MINUS = "−"
MAX_EXTRA_LINES = store.MAX_SPREAD_EXTRA      # Spread: Hauptlinie + 4 weitere = 5 Linien (wie die Leiter in Score Projections)
COLS = [1, 0.8, 1]          # Gast | Mitte (Buchmacher bzw. -/+) | Heim: Gast und Heim gleich breit, Mitte symmetrisch dazwischen
LINE_STEP = 0.5
TOTAL_STEP = 1.0           # naechste weitere Total-Linie: 1,0 Punkt weiter
MAX_TOTAL_DIR = store.MAX_TOTAL_PER_DIRECTION
MS_W = [0.5, 0.9, 0.5, 1.2, 1.6, 0.8]                # Meilenstein-Zeile: - | Schwelle | + | Quote | Buchmacher | Entfernen
MODE_LABELS = {"milestones": "Meilensteine", "line": "Einzellinie"}
PLAYER_CFG = dict(parse=store.parse_player_line_input, lo=store.MIN_PLAYER_LINE, hi=store.MAX_PLAYER_LINE, start=20.5, placeholder="24,5")
SP_W = [1.1, 0.9, 0.5, 0.5, 0.9, 1.1, 1.4, 0.8]      # kompakte Spread-Zeile: Quote Gast | Linie Gast | - | + | Linie Heim | Quote Heim | Buchmacher | Entfernen
OU_W = [1.2, 0.5, 0.9, 0.5, 1.2, 1.4, 0.8]           # kompakte Over/Under-Zeile: Quote Over | - | Linie | + | Quote Under | Buchmacher | Entfernen


def _now() -> float:
    return time.time()


def _css() -> str:
    P = PALETTE
    return f"""
<style>
[class*="st-key-pm_card_"] {{ position:relative; box-sizing:border-box; width:100%; max-width:1400px; background:{P['card_bg']}; border:1px solid #2c3350; border-radius:18px; padding:34px clamp(20px,3vw,48px) 30px; margin:0 0 28px; font-variant-numeric:tabular-nums; }}
.pm-corner {{ position:absolute; top:-18px; right:calc(16px - clamp(20px,3vw,48px)); z-index:2; }}
.pm-corner .pc-chip {{ margin-top:0; }}
.pc-chip-blue {{ background:{P['chip_blue_bg']}; border:1px solid {P['chip_blue_border']}; color:{P['chip_blue_text']}; }}
.pm-mid {{ display:flex; flex-direction:column; align-items:center; gap:12px; }}
.pm-kick {{ font-size:clamp(22px,2.2vw,32px); font-weight:800; line-height:1.15; text-align:center; color:{P['text']}; }}
.pm-chips {{ display:flex; flex-wrap:wrap; justify-content:center; gap:8px; }}
.pm-chips .pc-chip {{ margin-top:0; }}
.pm-section {{ margin-top:30px; padding-top:22px; border-top:1px solid #2c3350; }}
.pm-market-title {{ font-size:19px; font-weight:700; letter-spacing:.05em; color:{P['text']}; margin-bottom:6px; text-align:center; }}
/* Knopfstil: Orange nur fuer "Speichern" (primary). Alle anderen Knoepfe dieser Karten sind dezent grau, "Entfernen" nur Text. app.py faerbt sonst jeden Knopf orange. */
[class*="st-key-pm_card_"] .stButton button {{ background:#222842; color:{P['text_soft']}; border:1px solid #3a4268; font-weight:600; }}
[class*="st-key-pm_card_"] .stButton button:hover {{ background:#2d3454; border-color:#4a5482; color:{P['text']}; }}
[class*="st-key-pm_card_"] .stButton button:disabled {{ background:#1a1f33; color:#5b6384; border-color:#2c3350; }}
[class*="st-key-pm_card_"] .stButton button[data-testid="stBaseButton-primary"] {{ background:#f97316; color:#0a0a0f; border:none; font-weight:700; }}
[class*="st-key-pm_card_"] .stButton button[data-testid="stBaseButton-primary"]:hover {{ background:#ea6a10; color:#0a0a0f; }}
[class*="st-key-pm_card_"] .stButton button[data-testid="stBaseButton-tertiary"] {{ background:transparent; border:none; color:{P['label']}; font-weight:400; font-size:13px; padding:2px 8px; text-decoration:underline; text-underline-offset:3px; }}
[class*="st-key-pm_card_"] .stButton button[data-testid="stBaseButton-tertiary"]:hover {{ background:transparent; color:{P['text']}; }}
.pm-team-title {{ font-size:16px; font-weight:700; color:{P['text_soft']}; text-align:center; margin:22px 0 2px; }}
[class*="st-key-pm_card_"] [data-testid="stExpander"] {{ margin-top:14px; border-color:#2c3350; }}
[class*="st-key-pm_card_"] [data-testid="stExpander"] summary {{ font-size:17px; font-weight:700; letter-spacing:.05em; color:{P['text']}; }}
.pm-sub {{ font-size:14px; font-weight:600; color:{P['label']}; margin:18px 0 6px; }}
.pm-flabel {{ font-size:14px; color:{P['text_soft']}; margin:0 0 4px; }}
[class*="st-key-pm_roster_"] .stButton button {{ background:#222842; color:{P['text_soft']}; border:1px solid #3a4268; font-weight:600; width:auto; }}
[class*="st-key-pm_roster_"] .stButton button:hover {{ background:#2d3454; border-color:#4a5482; color:{P['text']}; }}
.pm-rows {{ max-width:760px; }}
.pm-note {{ font-size:14px; color:{P['label']}; margin-top:10px; }}
.pm-text {{ font-size:clamp(15px,1.2vw,17px); color:{P['text_soft']}; }}
</style>
"""


PRE_MATCH_CSS = _css()


# ------------------------------------------------------------------------------ Formatierung
def berlin_kickoff(start_utc: str | None) -> str:
    ts = store.parse_utc(start_utc) if start_utc else None
    if ts is None:
        return "Anpfiff unbekannt"
    dt = datetime.fromtimestamp(ts, BERLIN)
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d.%m.} · {dt:%H:%M} Uhr"


def berlin_stamp(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(BERLIN).strftime("%d.%m. %H:%M")
    except (TypeError, ValueError):
        return "?"


def berlin_clock(iso: str | None, now: float) -> str:
    """'HH:MM' (Berliner Zeit); an einem anderen Tag als jetzt mit Datum ('20.10. 22:05')."""
    try:
        dt = datetime.fromisoformat(iso).astimezone(BERLIN)
    except (TypeError, ValueError):
        return "?"
    return dt.strftime("%H:%M") if dt.date() == datetime.fromtimestamp(now, BERLIN).date() else dt.strftime("%d.%m. %H:%M")


def game_state(start_utc: str | None, bdl_status: str | None, now: float) -> str:
    """'vorab', 'läuft', 'beendet' oder 'unbekannt'. Massgeblich ist die aktuelle Uhrzeit (nicht der Stand der letzten Aktualisierung)."""
    ts = store.parse_utc(start_utc) if start_utc else None
    if ts is None:
        return "unbekannt"
    if now < ts:
        return "vorab"
    if str(bdl_status or "").strip().lower() == "final" or now > ts + 4 * 3600:
        return "beendet"
    return "läuft"


def fmt_odds(value: float) -> str:
    """Quote fuer die Anzeige: Dezimalkomma, mindestens 2 Nachkommastellen."""
    s = f"{value:.4f}".rstrip("0")
    if len(s.split(".")[1]) < 2:
        s = f"{value:.2f}"
    return s.replace(".", ",")


def fmt_line(value: float, signed: bool = True) -> str:
    """Spread-Linie: '−4,5' mit echtem Minus, '+4,25', '0' fuer Pick'em; mindestens eine Nachkommastelle."""
    if abs(value) < 1e-9:
        return "0"
    s = f"{abs(value):.2f}"
    s = s[:-1] if s.endswith("0") else s
    s = s.replace(".", ",")
    return (MINUS if value < 0 else ("+" if signed else "")) + s


def fmt_total(value: float) -> str:
    """Total-Linie fuer Anzeige und Eingabefeld: Dezimalkomma, eine Nachkommastelle ('231,5', '231,0')."""
    return f"{value:.1f}".replace(".", ",")


def fmt_raw(value: float) -> str:
    """Ungerundeter Vorschlag: eine Nachkommastelle, bei Vierteln zwei ('113,25')."""
    return fmt_total(value) if abs(value * 10 - round(value * 10)) < 1e-9 else f"{value:.2f}".replace(".", ",")


def line_input_text(value: float | None) -> str:
    """Wert fuer das Linienfeld (Dezimalkomma, Minus als '-', damit die Eingabe direkt wieder gueltig ist)."""
    return "" if value is None else fmt_line(value).replace(MINUS, "-")


def _text(container, label: str, key: str, default: str, **kw):
    """Textfeld, dessen Startwert im Session State steht (vor dem Erzeugen gesetzt, OHNE value=). Nie beides fuer denselben Key:
    sonst warnt Streamlit 'was created with a default value but also had its value set via the Session State API'."""
    if key not in st.session_state:
        st.session_state[key] = default
    return container.text_input(label, key=key, **kw)


def _chip(text: str, kind: str = "gray") -> str:
    return f'<div class="pc-chip pc-chip-{kind}">{escape(text)}</div>'


# ------------------------------------------------------------------------------ Spiele
def _suggestion(proj: dict) -> dict | None:
    """Marktvorschlag fuer die Heim-Linie aus der Vorab-Linie der Projektion (gleiche Quelle wie Score Projections).
    Score Projections: market_spread positiv = Heimteam ist Favorit. Linie aus Heim-Sicht = -market_spread.
    Gespeichert werden der ungerundete und der auf 0,5 gerundete Wert."""
    ms = proj["cache_market_spread"] if "cache_market_spread" in proj else proj.get("market_spread")      # nur die Cache-Linie (nie die eigene)
    if ms is None:
        return None
    raw = round(-float(ms) + 0.0, 2)
    return {"line_home": raw, "line_home_rounded": store.round_half(raw), "source": proj.get("market_source")}


def _total_suggestion(proj: dict) -> dict | None:
    """Marktvorschlag fuer die Total-Linie aus der Vorab-Linie der Projektion (gleiche Quelle wie Score Projections, keine Abrufe).
    Gespeichert werden der ungerundete und der auf 0,5 gerundete Wert."""
    mt = proj["cache_market_total"] if "cache_market_total" in proj else proj.get("market_total")
    if not mt:
        return None
    raw = round(float(mt), 2)
    return {"line": raw, "line_rounded": store.round_half(raw), "source": proj.get("market_source")}


def _team_suggestion(proj: dict) -> dict | None:
    """Rechnerischer Vorschlag der Team-Total-Hauptlinien aus Vorab-Total und Spread (der Odds-Cache kennt keine Team Totals)."""
    ms = proj["cache_market_spread"] if "cache_market_spread" in proj else proj.get("market_spread")
    mt = proj["cache_market_total"] if "cache_market_total" in proj else proj.get("market_total")
    if ms is None or not mt:
        return None
    return store.derive_team_suggestions(float(mt), round(-float(ms) + 0.0, 2))


def _games(projections: list[dict]) -> list[dict]:
    games = []
    for p in projections:
        start = store.normalize_start(p.get("game_start"))
        games.append({"home": p["home_team"], "away": p["away_team"], "date": p.get("game_date") or "",
                      "start": start, "bdl_status": p.get("game_status"), "suggestion": _suggestion(p), "total_suggestion": _total_suggestion(p), "team_suggestion": _team_suggestion(p),
                      "key": store.game_key(p.get("game_date") or "", start or "", p["home_team"], p["away_team"])})
    return sorted(games, key=lambda g: (g["start"] is None, g["start"] or ""))


def render_pre_match_tab(projections: list[dict]) -> None:
    st.markdown("## ✍️ Pre-Match Eingabe")
    st.caption(
        "Eigene Quoten vor dem Anpfiff erfassen (für Tracking und Backtest). Gespeichert wird in "
        "data/tracking/pre_match_entries.json mit Zeitstempel. Es werden keine Odds-API-Credits verbraucht."
    )
    data = store.load()
    if data.get("error"):
        st.warning(data["error"] + " Beim nächsten Speichern wird die defekte Datei gesichert und neu begonnen.")
    games = _games(projections)
    if not games:
        st.markdown(
            '<div class="no-bets"><div style="font-size:3rem">✍️</div><div style="margin-top:16px">Keine Spiele gefunden</div></div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown("".join(line.strip() for line in (CARD_CSS + PRE_MATCH_CSS).splitlines()), unsafe_allow_html=True)
    now = _now()
    roster = rosters.load(now)                    # nur die Datei lesen, nie ein Abruf
    _roster_controls(roster)
    for g in games:
        _render_game(g, data["entries"].get(g["key"]), data.get("last_bookmaker", {}), now, roster)


def _corner_chip(state: str, entry: dict | None, now: float) -> str:
    """Status-Chip oben rechts: offen (gelb) / gespeichert HH:MM (blaugrau) / bei laufend, beendet: grau bzw. kein Chip."""
    saved, last = store.saved_summary(entry)
    if state == "vorab":
        return _chip(f"gespeichert {berlin_clock(last, now)}", "blue") if saved else _chip("offen", "yellow")
    return _chip(f"gespeichert {berlin_clock(last, now)}", "gray") if saved else ""


def _render_game(g: dict, entry: dict | None, last_books: dict, now: float, roster: dict) -> None:
    home, away = team_info(g["home"]), team_info(g["away"])
    state = game_state(g["start"], g["bdl_status"], now)
    editable = state == "vorab" and store.is_editable(g["start"], now)
    kid = hashlib.md5(g["key"].encode("utf-8")).hexdigest()[:10]

    status = _chip({"vorab": "Vorab", "läuft": "läuft", "beendet": "beendet", "unbekannt": "Anpfiff unbekannt"}[state],
                   "yellow" if state in ("läuft", "unbekannt") else "gray")
    mid = f'<div class="pm-mid"><div class="pm-kick">{escape(berlin_kickoff(g["start"]))}</div><div class="pm-chips">{status}</div></div>'
    corner = _corner_chip(state, entry, now)
    head = (f'<div class="pm-corner">{corner}</div>\n' if corner else "") + render_card_head(g["away"], g["home"], mid)

    with st.container(key=f"pm_card_{kid}"):
        st.markdown("".join(line.strip() for line in head.splitlines()), unsafe_allow_html=True)
        if editable:
            _card_inputs(g, kid, entry, last_books, home, away, roster)       # Fragment: Klicks laden nur diesen Bereich neu
        else:
            winner = (entry or {}).get("markets", {}).get(MARKET)
            with st.expander("SIEGER INKL. OT"):
                _winner_readonly(winner, home, away, state)
            with st.expander("SPREAD"):
                _spread_readonly(entry, home, away, state)
            with st.expander("TOTAL"):
                _total_readonly(entry, state)
            with st.expander("TEAM TOTALS"):
                _team_totals_readonly(entry, g, state)
            with st.expander("SPIELERPUNKTE"):
                _player_points_readonly(entry, state)


@st.fragment
def _card_inputs(g: dict, kid: str, entry: dict | None, last_books: dict, home: dict, away: dict, roster: dict) -> None:
    """Eingabebereich einer Karte (Maerkte + Speichern). Als Fragment: +/- Knoepfe, Linieneingaben, 'Weitere Linie hinzufuegen' und
    Verwerfen laden nur diesen Bereich neu (nicht die App, nicht andere Tabs). Speichern und Entfernen einer gespeicherten Linie
    schreiben in die Datei und laden danach die ganze App neu (Chip oben rechts, gespeicherte Werte, Rueckmeldung)."""
    winner = (entry or {}).get("markets", {}).get(MARKET)
    # Jeder Markt ist ein Expander mit festem Titel (zu, bis du ihn oeffnest). Der Titel aendert sich nie und `expanded` bleibt immer False:
    # Streamlit behaelt dann den vom Nutzer gesetzten Auf/Zu-Zustand bei jedem Rerun. Widgets in zugeklappten Expandern bleiben erhalten.
    with st.expander("SIEGER INKL. OT"):
        _winner_fields(kid, winner, last_books.get(MARKET, ""), home, away)
    with st.expander("SPREAD"):
        extras = _spread_fields(g, kid, entry, last_books.get(store.SPREAD, ""), home, away)
    with st.expander("TOTAL"):
        t_extras = _total_fields(g, kid, entry, last_books.get(store.TOTAL, ""))
    with st.expander("TEAM TOTALS"):
        tm_extras = _team_fields(g, kid, entry, last_books, home, away)
    with st.expander("SPIELERPUNKTE"):
        pp_saved, pp_lookup = _player_fields(g, kid, entry, last_books.get(store.PLAYER_POINTS, ""), roster)
    _save_button(g, kid, extras, t_extras, tm_extras, pp_saved, pp_lookup, roster)


# ------------------------------------------------------------------------------ Markt Sieger inkl. OT
def _winner_fields(kid: str, saved: dict | None, last_bookmaker: str, home: dict, away: dict) -> None:
    c_away, c_book, c_home = st.columns(COLS)             # Gast links, Buchmacher Mitte, Heim rechts (Gast/Heim gleich breit)
    _text(c_away, f"Quote Gast · {away['nick']}", f"pm_away_{kid}", fmt_odds(saved["away_odds"]) if saved else "", placeholder="z. B. 2,10")
    _text(c_book, "Buchmacher", f"pm_book_{kid}", (saved or {}).get("bookmaker") or last_bookmaker, placeholder="z. B. Pinnacle")
    _text(c_home, f"Quote Heim · {home['nick']}", f"pm_home_{kid}", fmt_odds(saved["home_odds"]) if saved else "", placeholder="z. B. 1,85")


def _winner_readonly(saved: dict | None, home: dict, away: dict, state: str) -> None:
    reason = _lock_reason(state)
    if not saved:
        st.markdown(f'<div class="pm-text">Keine Quoten vor dem Anpfiff eingetragen.</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)
        return
    rows = (
        f'<div class="pc-row"><span class="pc-k">Gast · {escape(away["nick"])}</span><span class="pc-v pc-v-model">{fmt_odds(saved["away_odds"])}</span></div>'
        f'<div class="pc-row"><span class="pc-k">Heim · {escape(home["nick"])}</span><span class="pc-v pc-v-model">{fmt_odds(saved["home_odds"])}</span></div>'
        f'<div class="pc-row"><span class="pc-k">Buchmacher</span><span class="pc-v pc-v-market">{escape(saved.get("bookmaker") or "—")}</span></div>'
        f'<div class="pc-row"><span class="pc-k">eingetragen am</span><span class="pc-v pc-v-market">{berlin_stamp(saved.get("entered_at"))} Uhr</span></div>'
    )
    st.markdown(f'<div class="pm-rows">{rows}</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)


def _lock_reason(state: str) -> str:
    return {"läuft": "Das Spiel läuft: Eingaben sind gesperrt.", "beendet": "Das Spiel ist beendet: Eingaben sind gesperrt.",
            "unbekannt": "Der Anpfiff ist unbekannt: Eingaben sind gesperrt."}.get(state, "Eingaben sind gesperrt.")


# ------------------------------------------------------------------------------ Markt Spread
def _base(kid: str, rid: str) -> str:
    return f"pm_sp_{kid}_{rid}"


def _canonical_line(kid: str, rid: str) -> float | None:
    """Aktuelle Heim-Linie einer Zeile aus den Widget-Werten: zuletzt bearbeitetes Feld (Heim oder Gast), sonst None."""
    ss, base = st.session_state, _base(kid, rid)
    src = ss.get(f"{base}_src", "home")
    text = ss.get(f"{base}_gline" if src == "away" else f"{base}_line")
    try:
        v = store.parse_line_input(text)
    except store.OddsInputError:
        return None
    return (-v if src == "away" else v) + 0.0


def _mirror(base: str, src: str) -> None:
    """on_change: das andere Linienfeld folgt (Heim -1,5 <-> Gast +1,5). Ungueltig: andere Seite bleibt, Fehler beim Speichern."""
    ss = st.session_state
    sk, dk = (f"{base}_line", f"{base}_gline") if src == "home" else (f"{base}_gline", f"{base}_line")
    ss[f"{base}_src"] = src
    text = ss.get(sk, "")
    if not str(text).strip():
        ss[dk] = ""
        return
    try:
        v = store.parse_line_input(text)
    except store.OddsInputError:
        return
    ss[dk] = line_input_text(-v + 0.0)


def _step(base: str, delta: float) -> None:
    """on_click der +/- Knoepfe: Heim-Linie um 0,5 aendern, Gast folgt. Ohne gueltigen Wert wird bei 0 begonnen."""
    ss = st.session_state
    src = ss.get(f"{base}_src", "home")
    try:
        cur = store.parse_line_input(ss.get(f"{base}_gline" if src == "away" else f"{base}_line"))
        cur = -cur if src == "away" else cur
    except store.OddsInputError:
        cur = 0.0
    new = cur + delta + 0.0
    ss[f"{base}_line"] = line_input_text(new)
    ss[f"{base}_gline"] = line_input_text(-new + 0.0)
    ss[f"{base}_src"] = "home"


def _discard_row(kid: str, rid: str) -> None:
    """on_click: eine neue, noch nicht gespeicherte weitere Linie verwerfen (nichts wird gespeichert)."""
    ids = st.session_state.get(f"pm_new_ids_{kid}", [])
    if rid in ids:
        ids.remove(rid)


def _follow_book(main_book_key: str, ids_key: str, prefix: str) -> None:
    """on_change des Buchmachers der Hauptlinie: neue (noch nicht gespeicherte) Zeilen uebernehmen ihn, solange ihr Buchmacher
    nicht von Hand geaendert wurde. Gespeicherte Zeilen bleiben unveraendert (nicht rueckwirkend)."""
    ss = st.session_state
    val = ss.get(main_book_key, "")
    for rid in ss.get(ids_key, []):
        base = f"{prefix}_{rid}"
        if not ss.get(f"{base}_bkdirty"):
            ss[f"{base}_book"] = val


def _book_dirty(base: str) -> None:
    """on_change des Buchmacher-Feldes einer weiteren Zeile: ab jetzt weicht die Zeile von der Hauptlinie ab."""
    st.session_state[f"{base}_bkdirty"] = True


def _add_row(kid: str, base_ids: list) -> None:
    """on_click von '+ Weitere Linie': neue Zeile, Linie 1,0 weiter Richtung Favorit ab der letzten Zeile (aktueller Feldwert)."""
    ss = st.session_state
    new_key, ctr_key = f"pm_new_ids_{kid}", f"pm_new_ctr_{kid}"
    ids = ss.setdefault(new_key, [])
    if len([i for i in base_ids if i != "main"]) + len(ids) >= MAX_EXTRA_LINES:
        return
    ref = (ids[-1] if ids else base_ids[-1])
    ref_line = _canonical_line(kid, ref)
    ss[ctr_key] = ss.get(ctr_key, 0) + 1
    nid = f"n{ss[ctr_key]}"
    ids.append(nid)
    b = _base(kid, nid)
    ss[f"{b}_book"] = ss.get(f"{_base(kid, 'main')}_book", "")           # Buchmacher der Hauptlinie vorbelegt
    if ref_line is not None:
        nxt = store.next_line(ref_line)
        ss[f"{b}_line"], ss[f"{b}_gline"], ss[f"{b}_src"] = line_input_text(nxt), line_input_text(-nxt + 0.0), "home"


def _line_row(kid: str, rid: str, line: dict | None, default_book: str, suggestion: dict | None, home: dict, away: dict,
              label: str, removable: bool = False) -> bool:
    """Hauptlinie des Spreads (grosse Felder). Linienzeile: Linie Gast | - + (Mitte) | Linie Heim; Quotenzeile: Quote Gast | Buchmacher | Quote Heim.
    Weitere Linien sind kompakte Einzeiler (_spread_compact_row)."""
    base = _base(kid, rid)
    if line is not None:
        d_home, d_away_l = line_input_text(line["line_home"]), line_input_text(line["line_away"])
        d_qa, d_qh, d_bm = fmt_odds(line["away_odds"]), fmt_odds(line["home_odds"]), line.get("bookmaker") or default_book
    else:
        q = suggestion["line_home_rounded"] if (suggestion and rid == "main") else None
        d_home, d_away_l = line_input_text(q), line_input_text(None if q is None else -q + 0.0)
        d_qa, d_qh, d_bm = "", "", default_book

    st.markdown(f'<div class="pm-note" style="margin-top:14px">{escape(label)}</div>', unsafe_allow_html=True)
    c_away, c_mid, c_home = st.columns(COLS)
    _text(c_away, f"Linie Gast · {away['nick']}", f"{base}_gline", d_away_l, placeholder="z. B. +1,5", on_change=_mirror, args=(base, "away"))
    _text(c_home, f"Linie Heim · {home['nick']}", f"{base}_line", d_home, placeholder="z. B. -1,5", on_change=_mirror, args=(base, "home"))
    with c_mid:
        st.markdown('<div style="height:1.9rem"></div>', unsafe_allow_html=True)       # auf Hoehe der Eingabefelder
        c_minus, c_plus = st.columns(2)
        c_minus.button("−", key=f"{base}_minus", on_click=_step, args=(base, -LINE_STEP), use_container_width=True,
                       help="Heim-Linie um 0,5 verringern (Gast folgt)")
        c_plus.button("\\+", key=f"{base}_plus", on_click=_step, args=(base, LINE_STEP), use_container_width=True,
                      help="Heim-Linie um 0,5 erhöhen (Gast folgt)")
    c_away2, c_book2, c_home2 = st.columns(COLS)
    _text(c_away2, f"Quote Gast · {away['nick']}", f"{base}_away", d_qa, placeholder="z. B. 1,91")
    _text(c_book2, "Buchmacher", f"{base}_book", d_bm, placeholder="z. B. Pinnacle",
          on_change=_follow_book if rid == "main" else None, args=(f"{base}_book", f"pm_new_ids_{kid}", f"pm_sp_{kid}") if rid == "main" else None)
    _text(c_home2, f"Quote Heim · {home['nick']}", f"{base}_home", d_qh, placeholder="z. B. 1,91")
    return False


def _header(weights: list, texts: list) -> None:
    """Kopfzeile der kompakten Zeilen: die Beschriftungen stehen nur einmal ueber den Zeilen."""
    for col, t in zip(st.columns(weights), texts):
        if t:
            col.markdown(f'<div class="pm-flabel" style="text-align:center">{escape(t)}</div>', unsafe_allow_html=True)


def _spread_compact_row(kid: str, rid: str, line: dict | None, home: dict, away: dict) -> bool:
    """Weitere Spread-Linie als EINE Zeile: Quote Gast | Linie Gast | - | + | Linie Heim | Quote Heim | Buchmacher | Entfernen.
    Rueckgabe: True, wenn 'Entfernen' einer gespeicherten Linie gedrueckt wurde."""
    base = _base(kid, rid)
    if line is not None:
        d_home, d_away_l = line_input_text(line["line_home"]), line_input_text(line["line_away"])
        d_qa, d_qh, d_bm = fmt_odds(line["away_odds"]), fmt_odds(line["home_odds"]), line.get("bookmaker") or ""
    else:
        d_home, d_away_l, d_qa, d_qh, d_bm = "", "", "", "", st.session_state.get(f"{_base(kid, 'main')}_book", "")
    cols = st.columns(SP_W)
    kw = dict(label_visibility="collapsed")
    _text(cols[0], f"Quote Gast · {away['nick']}", f"{base}_away", d_qa, placeholder="1,91", **kw)
    _text(cols[1], f"Linie Gast · {away['nick']}", f"{base}_gline", d_away_l, placeholder="+1,5", on_change=_mirror, args=(base, "away"), **kw)
    cols[2].button("−", key=f"{base}_minus", on_click=_step, args=(base, -LINE_STEP), use_container_width=True, help="Heim-Linie um 0,5 verringern (Gast folgt)")
    cols[3].button("\\+", key=f"{base}_plus", on_click=_step, args=(base, LINE_STEP), use_container_width=True, help="Heim-Linie um 0,5 erhöhen (Gast folgt)")
    _text(cols[4], f"Linie Heim · {home['nick']}", f"{base}_line", d_home, placeholder="-1,5", on_change=_mirror, args=(base, "home"), **kw)
    _text(cols[5], f"Quote Heim · {home['nick']}", f"{base}_home", d_qh, placeholder="1,91", **kw)
    _text(cols[6], "Buchmacher (Zeile)", f"{base}_book", d_bm, placeholder="Buchmacher", on_change=_book_dirty, args=(base,), **kw)
    if rid.startswith("n"):                         # neue, noch nicht gespeicherte Zeile: nur verwerfen (Callback)
        cols[7].button("Entfernen", key=f"{base}_rm", type="tertiary", use_container_width=True, on_click=_discard_row, args=(kid, rid))
        return False
    return cols[7].button("Entfernen", key=f"{base}_rm", type="tertiary", use_container_width=True)


def _row_values(kid: str, rid: str, label: str | None = None) -> dict:
    """Werte einer Zeile fuer den Speicher. Die Heim-Linie kommt aus dem zuletzt bearbeiteten Linienfeld (Heim oder Gast)."""
    base, ss = _base(kid, rid), st.session_state
    src = ss.get(f"{base}_src", "home")
    line_text = ss.get(f"{base}_line")
    if src == "away":
        try:
            line_text = line_input_text(-store.parse_line_input(ss.get(f"{base}_gline")) + 0.0)
        except store.OddsInputError:
            line_text = ss.get(f"{base}_gline")                 # ungueltig: der Speicher meldet den Fehler
    return {"id": None if rid.startswith("n") else rid, "line": line_text, "home_odds": ss.get(f"{base}_home"),
            "away_odds": ss.get(f"{base}_away"), "bookmaker": ss.get(f"{base}_book")}


def _spread_fields(g: dict, kid: str, entry: dict | None, last_book: str, home: dict, away: dict) -> list[str]:
    """Spread-Felder (Hauptlinie + Expander 'Weitere Linien' mit kompakten Zeilen). Gibt die IDs der gespeicherten weiteren Linien zurueck."""
    lines = store.active_spread_lines(entry)
    main = next((l for l in lines if l["id"] == "main"), None)
    extras = [l for l in lines if l["id"] != "main"]
    sugg = g["suggestion"]
    new_ids = st.session_state.setdefault(f"pm_new_ids_{kid}", [])

    _line_row(kid, "main", main, last_book, sugg, home, away, "Hauptlinie")
    if sugg:
        st.caption(f"Vorschlag aus Markt (Vorab-Linie): {fmt_line(sugg['line_home'])}"
                   + (f" (gerundet {fmt_line(sugg['line_home_rounded'])})" if abs(sugg["line_home"] - sugg["line_home_rounded"]) > 1e-9 else ""))

    remove_id = None
    count = len(extras) + len(new_ids)
    st.markdown(f'<div class="pm-sub">Weitere Linien ({len(extras) + len(new_ids)})</div>', unsafe_allow_html=True)       # kein Expander im Expander (Streamlit erlaubt das nicht)
    with st.container():
        if extras or new_ids:
            _header(SP_W, [f"Quote Gast · {away['nick']}", "Linie Gast", "", "", "Linie Heim", f"Quote Heim · {home['nick']}", "Buchmacher", ""])
        for l in extras:
            if _spread_compact_row(kid, l["id"], l, home, away):
                remove_id = l["id"]
        for nid in list(new_ids):
            _spread_compact_row(kid, nid, None, home, away)
        base_ids = ["main"] + [l["id"] for l in extras]
        st.button("\\+ Weitere Linie hinzufügen", key=f"pm_add_{kid}", disabled=count >= MAX_EXTRA_LINES,
                  on_click=_add_row, args=(kid, base_ids))
        if count >= MAX_EXTRA_LINES:
            st.caption(f"maximal {MAX_EXTRA_LINES} weitere Linien")
    if remove_id:
        try:
            store.remove_spread_line(g["date"], g["start"], g["home"], g["away"], remove_id, now=_now())
        except (store.OddsInputError, store.GameStartedError, store.StoreError) as e:
            st.warning(str(e))
        else:
            st.session_state[f"pm_flash_{kid}"] = "Linie entfernt (bleibt als Revision in der Datei)."
            st.rerun(scope="app")
    return [l["id"] for l in extras]


def _all_new_keys(kid: str) -> list[str]:
    return [f"pm_new_ids_{kid}", f"pm_pp_{kid}__new"] + [f"{_ou_prefix(kid, k)}__new" for k in ("tt", "ta", "th")]


def _save_button(g: dict, kid: str, extra_ids: list[str], total_extras: list[tuple], team_extras: dict, pp_saved: list, pp_lookup: dict, roster: dict) -> None:
    """EIN Speichern-Knopf am Ende der Karte (orange): alle ausgefuellten Maerkte, alles oder nichts."""
    flash = st.session_state.pop(f"pm_flash_{kid}", None)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    if st.button("Speichern", key=f"pm_save_{kid}", type="primary"):
        ss = st.session_state
        winner = {"home_odds": ss.get(f"pm_home_{kid}"), "away_odds": ss.get(f"pm_away_{kid}"), "bookmaker": ss.get(f"pm_book_{kid}")}
        new_ids = ss.get(f"pm_new_ids_{kid}", [])
        rows = [_row_values(kid, "main")] + [_row_values(kid, i) for i in extra_ids] + [_row_values(kid, n) for n in new_ids]
        t_rows = _ou_rows(_ou_prefix(kid, "tt"), total_extras)
        team_rows = {side: _ou_rows(_ou_prefix(kid, "ta" if side == "away" else "th"), team_extras.get(side, [])) for side in store.TEAMS}
        names = {"away": team_info(g["away"])["nick"], "home": team_info(g["home"])["nick"]}
        try:
            res = store.save_card(g["date"], g["start"], g["home"], g["away"], winner=winner, spread_rows=rows, suggestion=g["suggestion"],
                                  total_rows=t_rows, total_suggestion=g["total_suggestion"], team_rows=team_rows,
                                  team_suggestion=g["team_suggestion"], team_names=names,
                                  player_blocks=_pp_payload(kid, pp_saved, pp_lookup), roster_fetched_at=roster.get("fetched_at"), now=_now())
        except store.CardInputError as e:
            for msg in e.errors:
                st.warning(msg)
        except (store.OddsInputError, store.GameStartedError, store.StoreError) as e:
            st.warning(str(e))
        else:
            for k in _all_new_keys(kid):
                ss[k] = []
            for k in [k for k in ss.keys() if isinstance(k, str) and k.startswith(f"pm_pp_{kid}_") and k.endswith("__new")]:
                ss[k] = []
            ss[f"pm_flash_{kid}"] = "Gespeichert." if res["status"] == "saved" else "Unverändert."
            st.rerun(scope="app")
    if flash:
        st.caption(flash)
    st.caption("Bis zum Anpfiff änderbar.")


def _spread_readonly(entry: dict | None, home: dict, away: dict, state: str) -> None:
    reason = _lock_reason(state)
    lines = store.active_spread_lines(entry)
    if not lines:
        st.markdown(f'<div class="pm-text">Keine Spread-Linie vor dem Anpfiff eingetragen.</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)
        return
    rows = ""
    for i, l in enumerate(lines):
        label = "Hauptlinie" if l["id"] == "main" else f"Weitere Linie {i}"
        value = (f'{escape(away["nick"])} {fmt_line(l["line_away"])} · {fmt_odds(l["away_odds"])}'
                 f' &nbsp;|&nbsp; {escape(home["nick"])} {fmt_line(l["line_home"])} · {fmt_odds(l["home_odds"])}')
        rows += f'<div class="pc-row"><span class="pc-k">{label}</span><span class="pc-v pc-v-model">{value}</span></div>'
        rows += (f'<div class="pc-row"><span class="pc-k">Buchmacher · eingetragen am</span><span class="pc-v pc-v-market">'
                 f'{escape(l.get("bookmaker") or "—")} · {berlin_stamp(l.get("entered_at"))} Uhr</span></div>')
    st.markdown(f'<div class="pm-rows">{rows}</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------------------ Over/Under-Maerkte (Total, Team Totals): gemeinsame Komponente
DIR_NAMES = {"higher": "Höhere Linie", "lower": "Niedrigere Linie"}


def _ou_prefix(kid: str, which: str) -> str:
    """which: 'tt' = Total, 'ta' = Team Total Gast, 'th' = Team Total Heim."""
    return f"pm_{which}_{kid}"


def _new_dir(nid: str) -> str:
    """Richtung einer neuen (noch nicht gespeicherten) Zeile: 'nh<k>' = hoeher, 'nl<k>' = niedriger."""
    return "higher" if nid.startswith("nh") else "lower"


def _ou_value(prefix: str, rid: str, parse) -> float | None:
    try:
        return parse(st.session_state.get(f"{prefix}_{rid}_line"))
    except store.OddsInputError:
        return None


def _ou_step(base: str, delta: float, parse, lo: float, hi: float, start: float) -> None:
    """on_click der +/- Knoepfe: Linie um 0,5 aendern (Grenzen lo bis hi). Ohne gueltigen Wert wird bei 'start' begonnen."""
    ss = st.session_state
    try:
        cur = parse(ss.get(f"{base}_line"))
    except store.OddsInputError:
        cur = start
    ss[f"{base}_line"] = fmt_total(min(hi, max(lo, cur + delta)))


def _ou_add(prefix: str, direction: str, saved: list, parse, lo: float, hi: float) -> None:
    """on_click von '+ Hoehere Linie' / '- Niedrigere Linie': neue Zeile 1,0 weiter ab der hoechsten (bzw. niedrigsten) Linie dieser Richtung
    (aktueller Feldwert), ohne solche Linie ab der Hauptlinie. saved: [(id, direction)] der gespeicherten weiteren Linien."""
    ss = st.session_state
    ids = ss.setdefault(f"{prefix}__new", [])
    same = [i for i, d in saved if d == direction] + [n for n in ids if _new_dir(n) == direction]
    if len(same) >= MAX_TOTAL_DIR:
        return
    vals = [v for v in (_ou_value(prefix, i, parse) for i in same) if v is not None]
    ref = (max(vals) if direction == "higher" else min(vals)) if vals else _ou_value(prefix, "main", parse)
    ctr = ss[f"{prefix}__ctr"] = ss.get(f"{prefix}__ctr", 0) + 1
    nid = f"{'nh' if direction == 'higher' else 'nl'}{ctr}"
    ids.append(nid)
    ss[f"{prefix}_{nid}_book"] = ss.get(f"{prefix}_main_book", "")           # Buchmacher der Hauptlinie vorbelegt
    if ref is not None:
        nxt = ref + (TOTAL_STEP if direction == "higher" else -TOTAL_STEP)
        if lo <= nxt <= hi:
            ss[f"{prefix}_{nid}_line"] = fmt_total(nxt)


def _ou_discard(prefix: str, nid: str) -> None:
    ids = st.session_state.get(f"{prefix}__new", [])
    if nid in ids:
        ids.remove(nid)


def _ou_main(prefix: str, line: dict | None, default_book: str, sugg: dict | None, cfg: dict) -> None:
    """Hauptlinie (grosse Felder). Linienzeile (Raster 1 : 0,8 : 1): '-' links neben dem Feld, Linie in der Mitte, '+' rechts daneben;
    Quotenzeile: Quote Over | Buchmacher | Quote Under (mit aktueller Linie ueber dem Feld)."""
    base = f"{prefix}_main"
    if line is not None:
        d_line, d_over, d_under, d_bm = fmt_total(line["line"]), fmt_odds(line["over_odds"]), fmt_odds(line["under_odds"]), line.get("bookmaker") or default_book
    else:
        d_line = fmt_total(sugg["line_rounded"]) if sugg else ""
        d_over, d_under, d_bm = "", "", default_book
    c_l, c_m, c_r = st.columns(COLS)
    _text(c_m, "Linie", f"{base}_line", d_line, placeholder=cfg["placeholder"])
    step = dict(parse=cfg["parse"], lo=cfg["lo"], hi=cfg["hi"], start=cfg["start"])
    with c_l:
        st.markdown('<div style="height:1.9rem"></div>', unsafe_allow_html=True)
        _, c_minus = st.columns([2, 1])
        c_minus.button("−", key=f"{base}_minus", on_click=_ou_step, args=(base, -LINE_STEP, *step.values()), use_container_width=True, help="Linie um 0,5 verringern")
    with c_r:
        st.markdown('<div style="height:1.9rem"></div>', unsafe_allow_html=True)
        c_plus, _ = st.columns([1, 2])
        c_plus.button("\\+", key=f"{base}_plus", on_click=_ou_step, args=(base, LINE_STEP, *step.values()), use_container_width=True, help="Linie um 0,5 erhöhen")
    cur = _ou_value(prefix, "main", cfg["parse"])
    suffix = f" · {fmt_total(cur)}" if cur is not None else ""
    c_o, c_b, c_u = st.columns(COLS)
    # Die Beschriftung mit der aktuellen Linie steht als eigener Text ueber dem Feld; das Widget behaelt ein festes Label, denn ein
    # geaendertes Label wuerde das Widget neu erzeugen und die eingegebene Quote verwerfen.
    for col, text, key, default, ph, nm, extra in (
            (c_o, f"Quote Over{suffix}", f"{base}_over", d_over, "z. B. 1,91", "Quote Over", {}),
            (c_b, "Buchmacher", f"{base}_book", d_bm, "z. B. Pinnacle", "Buchmacher", dict(on_change=_follow_book, args=(f"{base}_book", f"{prefix}__new", prefix))),
            (c_u, f"Quote Under{suffix}", f"{base}_under", d_under, "z. B. 1,91", "Quote Under", {})):
        col.markdown(f'<div class="pm-flabel">{escape(text)}</div>', unsafe_allow_html=True)
        _text(col, nm, key, default, placeholder=ph, label_visibility="collapsed", **extra)


def _ou_compact_row(prefix: str, rid: str, line: dict | None, cfg: dict, ref_book_key: str | None = None, leader: bool = False) -> bool:
    """Weitere Linie als EINE Zeile: Quote Over | - | Linie | + | Quote Under | Buchmacher | Entfernen.
    Rueckgabe: True, wenn 'Entfernen' einer gespeicherten Linie gedrueckt wurde."""
    base = f"{prefix}_{rid}"
    if line is not None:
        d_line, d_over, d_under, d_bm = fmt_total(line["line"]), fmt_odds(line["over_odds"]), fmt_odds(line["under_odds"]), line.get("bookmaker") or ""
    else:
        d_line, d_over, d_under, d_bm = "", "", "", st.session_state.get(ref_book_key or f"{prefix}_main_book", "")
    step = (cfg["parse"], cfg["lo"], cfg["hi"], cfg["start"])
    cols = st.columns(OU_W)
    kw = dict(label_visibility="collapsed")
    _text(cols[0], "Quote Over (Zeile)", f"{base}_over", d_over, placeholder="1,91", **kw)
    cols[1].button("−", key=f"{base}_minus", on_click=_ou_step, args=(base, -LINE_STEP, *step), use_container_width=True, help="Linie um 0,5 verringern")
    _text(cols[2], "Weitere Linie", f"{base}_line", d_line, placeholder=cfg["placeholder"], **kw)
    cols[3].button("\\+", key=f"{base}_plus", on_click=_ou_step, args=(base, LINE_STEP, *step), use_container_width=True, help="Linie um 0,5 erhöhen")
    _text(cols[4], "Quote Under (Zeile)", f"{base}_under", d_under, placeholder="1,91", **kw)
    if leader:      # erste Zeile eines Spielerblocks: ihr Buchmacher gilt fuer die folgenden Zeilen, solange diese nicht abweichen
        _text(cols[5], "Buchmacher (Zeile)", f"{base}_book", d_bm, placeholder="Buchmacher", on_change=_follow_book, args=(f"{base}_book", f"{prefix}__new", prefix), **kw)
    else:
        _text(cols[5], "Buchmacher (Zeile)", f"{base}_book", d_bm, placeholder="Buchmacher", on_change=_book_dirty, args=(base,), **kw)
    if rid.startswith("n"):
        cols[6].button("Entfernen", key=f"{base}_rm", type="tertiary", use_container_width=True, on_click=_ou_discard, args=(prefix, rid))
        return False
    return cols[6].button("Entfernen", key=f"{base}_rm", type="tertiary", use_container_width=True)


def _ou_rows(prefix: str, saved: list) -> list[dict]:
    """Zeilen fuer den Speicher: Hauptlinie, gespeicherte weitere Linien ([(id, direction)]), neue Zeilen."""
    ss = st.session_state

    def row(rid, direction):
        b = f"{prefix}_{rid}"
        return {"id": None if rid.startswith("n") else rid, "direction": direction if rid != "main" else None, "line": ss.get(f"{b}_line"),
                "over_odds": ss.get(f"{b}_over"), "under_odds": ss.get(f"{b}_under"), "bookmaker": ss.get(f"{b}_book")}
    return [row("main", None)] + [row(i, d) for i, d in saved] + [row(n, _new_dir(n)) for n in ss.get(f"{prefix}__new", [])]


def _ou_block(prefix: str, lines: list[dict], default_book: str, sugg: dict | None, cfg: dict, remove_fn) -> list[tuple]:
    """Ein Over/Under-Block: Hauptlinie, Vorschlag, Zwischenueberschrift 'Weitere Linien (n)' mit kompakten Zeilen (hoehere oben, niedrigere darunter,
    je Block nach Linie absteigend), Knoepfe '+ Hoehere Linie' / '- Niedrigere Linie' (je bis 3). remove_fn(line_id) entfernt eine
    gespeicherte Linie in der Datei. Gibt [(id, direction)] der gespeicherten weiteren Linien zurueck."""
    ss = st.session_state
    main = next((l for l in lines if l["id"] == "main"), None)
    extras = [l for l in lines if l["id"] != "main"]
    new_ids = ss.setdefault(f"{prefix}__new", [])
    _ou_main(prefix, main, default_book, sugg, cfg)
    if sugg:
        st.caption(f"{cfg['hint']}: {fmt_raw(sugg['line'])}" + (f" (gerundet {fmt_total(sugg['line_rounded'])})" if abs(sugg["line"] - sugg["line_rounded"]) > 1e-9 else ""))
    saved = [(l["id"], l.get("direction") or "higher") for l in extras]
    allrows = [(i, d, l) for (i, d), l in zip(saved, extras)] + [(n, _new_dir(n), None) for n in new_ids]

    def order(r):
        v = _ou_value(prefix, r[0], cfg["parse"]) if f"{prefix}_{r[0]}_line" in ss else (r[2]["line"] if r[2] else None)
        return (0 if r[1] == "higher" else 1, -(v if v is not None else (1e9 if r[1] == "higher" else -1e9)))

    remove_id = None
    st.markdown(f'<div class="pm-sub">Weitere Linien ({len(extras) + len(new_ids)})</div>', unsafe_allow_html=True)
    with st.container():
        if allrows:
            _header(OU_W, ["Quote Over", "", "Linie", "", "Quote Under", "Buchmacher", ""])
        for rid, _direction, l in sorted(allrows, key=order):
            if _ou_compact_row(prefix, rid, l, cfg):
                remove_id = rid
        n_h = sum(1 for r in allrows if r[1] == "higher")
        n_l = sum(1 for r in allrows if r[1] == "lower")
        c1, c2 = st.columns(2)
        args = (cfg["parse"], cfg["lo"], cfg["hi"])
        c1.button("\\+ Höhere Linie", key=f"{prefix}__addh", disabled=n_h >= MAX_TOTAL_DIR, on_click=_ou_add, args=(prefix, "higher", saved, *args), use_container_width=True)
        c2.button("− Niedrigere Linie", key=f"{prefix}__addl", disabled=n_l >= MAX_TOTAL_DIR, on_click=_ou_add, args=(prefix, "lower", saved, *args), use_container_width=True)
        if n_h >= MAX_TOTAL_DIR:
            c1.caption(f"maximal {MAX_TOTAL_DIR} höhere Linien")
        if n_l >= MAX_TOTAL_DIR:
            c2.caption(f"maximal {MAX_TOTAL_DIR} niedrigere Linien")
    if remove_id:
        try:
            remove_fn(remove_id)
        except (store.OddsInputError, store.GameStartedError, store.StoreError) as e:
            st.warning(str(e))
        else:
            ss[f"pm_flash_{prefix.rsplit('_', 1)[1]}"] = "Linie entfernt (bleibt als Revision in der Datei)."
            st.rerun(scope="app")
    return saved


TOTAL_CFG = dict(parse=store.parse_total_input, lo=store.MIN_TOTAL, hi=store.MAX_TOTAL, start=225.0, placeholder="z. B. 231,5",
                 hint="Vorschlag aus Markt (Vorab-Linie)")
TEAM_CFG = dict(parse=store.parse_team_total_input, lo=store.MIN_TEAM_TOTAL, hi=store.MAX_TEAM_TOTAL, start=113.0, placeholder="z. B. 113,5",
                hint="Rechnerischer Vorschlag aus Total und Spread (Vorab-Linie)")


def _total_fields(g: dict, kid: str, entry: dict | None, last_book: str) -> list[tuple]:
    return _ou_block(_ou_prefix(kid, "tt"), store.active_total_lines(entry), last_book, g["total_suggestion"], TOTAL_CFG,
                     lambda lid: store.remove_total_line(g["date"], g["start"], g["home"], g["away"], lid, now=_now()))


def _team_fields(g: dict, kid: str, entry: dict | None, last_books: dict, home: dict, away: dict) -> dict:
    """Team Totals: zwei Bloecke, Gast zuerst, Heim danach. Gibt {'away': [...], 'home': [...]} der gespeicherten weiteren Linien zurueck."""
    out = {}
    for side, which, info, role in (("away", "ta", away, "Gast"), ("home", "th", home, "Heim")):
        st.markdown(f'<div class="pm-team-title">{escape(info["nick"])} ({role})</div>', unsafe_allow_html=True)
        sugg = (g["team_suggestion"] or {}).get(side)
        out[side] = _ou_block(_ou_prefix(kid, which), store.team_total_lines(entry, side), last_books.get(f"{store.TEAM_TOTALS}_{side}", ""), sugg, TEAM_CFG,
                              lambda lid, side=side: store.remove_team_total_line(g["date"], g["start"], g["home"], g["away"], side, lid, now=_now()))
    return out


def _ou_readonly_rows(lines: list[dict]) -> str:
    main = [l for l in lines if l["id"] == "main"]
    ordered = main + sorted([l for l in lines if l["id"] != "main"], key=lambda l: (0 if l.get("direction") == "higher" else 1, -l["line"]))
    rows = ""
    for l in ordered:
        label = "Hauptlinie" if l["id"] == "main" else DIR_NAMES.get(l.get("direction"), "Weitere Linie")
        value = f'Over {fmt_odds(l["over_odds"])} &nbsp;|&nbsp; {fmt_total(l["line"])} &nbsp;|&nbsp; Under {fmt_odds(l["under_odds"])}'
        rows += f'<div class="pc-row"><span class="pc-k">{label}</span><span class="pc-v pc-v-model">{value}</span></div>'
        rows += (f'<div class="pc-row"><span class="pc-k">Buchmacher · eingetragen am</span><span class="pc-v pc-v-market">'
                 f'{escape(l.get("bookmaker") or "—")} · {berlin_stamp(l.get("entered_at"))} Uhr</span></div>')
    return rows


def _total_readonly(entry: dict | None, state: str) -> None:
    reason = _lock_reason(state)
    lines = store.active_total_lines(entry)
    if not lines:
        st.markdown(f'<div class="pm-text">Keine Total-Linie vor dem Anpfiff eingetragen.</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="pm-rows">{_ou_readonly_rows(lines)}</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)


def _team_totals_readonly(entry: dict | None, g: dict, state: str) -> None:
    reason = _lock_reason(state)
    if not any(store.team_total_lines(entry, s) for s in store.TEAMS):
        st.markdown(f'<div class="pm-text">Keine Team-Total-Linie vor dem Anpfiff eingetragen.</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)
        return
    for side, role, name in (("away", "Gast", g["away"]), ("home", "Heim", g["home"])):
        lines = store.team_total_lines(entry, side)
        st.markdown(f'<div class="pm-team-title">{escape(team_info(name)["nick"])} ({role})</div>', unsafe_allow_html=True)
        if lines:
            st.markdown(f'<div class="pm-rows">{_ou_readonly_rows(lines)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="pm-text">Keine Linie eingetragen.</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------------------ Kaderliste (nur Datei lesen; Abruf nur per Knopf)
def _roster_controls(info: dict) -> None:
    """Hinweise zur Kaderdatei und der Knopf 'Kader aktualisieren' (dezent, nicht orange). Der Abruf (1 Abruf an stats.nba.com) laeuft NUR beim Klick."""
    with st.container(key="pm_roster_box"):
        if info["status"] == "missing":
            st.info(info["message"])
        elif info["status"] == "corrupt":
            st.warning(info["message"])
        else:
            notice = rosters.age_notice(info)
            if notice:
                st.warning(("⚠ " if notice[0] == "strong" else "") + notice[1])
            n = sum(len(v) for v in info["teams"].values())
            st.caption(f"Kader (für Spielerpunkte): Stand {berlin_stamp(info['fetched_at'])} Uhr, Saison {info['season']}, {n} Spieler in {len(info['teams'])} Teams.")
        flash = st.session_state.pop("pm_roster_flash", None)
        c1, c2 = st.columns([1, 3])
        clicked = c1.button("Kader aktualisieren", key="pm_roster_refresh", help="Ein einziger Abruf an stats.nba.com (nba_api PlayerIndex), erst nach Erfolg wird die Datei ersetzt.")
        c2.caption("Beim Klick: **1 Abruf an stats.nba.com** (Timeout 30 s, ein Versuch). Beim Start und bei Klicks in der App wird nie abgerufen.")
        if flash:
            st.caption(flash)
        if clicked:
            bar = st.progress(0.0, text="Kader wird abgerufen …")
            try:
                data = rosters.refresh(progress=lambda f, t: bar.progress(f, text=t))
            except rosters.RosterError as e:
                bar.empty()
                st.warning(str(e))
            else:
                st.session_state["pm_roster_flash"] = f"Kader aktualisiert: {sum(len(v) for v in data['teams'].values())} Spieler in {len(data['teams'])} Teams."
                st.rerun()


# ------------------------------------------------------------------------------ Markt Spielerpunkte
def _pp_prefix(kid: str, bid: str) -> str:
    return f"pm_pp_{kid}_{bid}"


def _ss_default(key: str, default) -> None:
    """Startwert im Session State (vor dem Erzeugen des Widgets, nie zusaetzlich value=/index=)."""
    if key not in st.session_state:
        st.session_state[key] = default


def _ms_step(base: str, delta: int) -> None:
    """on_click der +/- Knoepfe einer Meilenstein-Zeile: Schwelle um 1 aendern (1 bis 80); ohne gueltigen Wert wird bei 19 begonnen."""
    ss = st.session_state
    try:
        cur = store.parse_threshold_input(ss.get(f"{base}_line"))
    except store.OddsInputError:
        cur = 19
    ss[f"{base}_line"] = str(min(store.MAX_THRESHOLD, max(store.MIN_THRESHOLD, cur + delta)))


def _ms_compact_row(prefix: str, rid: str, line: dict | None, ref_book_key: str, leader: bool) -> bool:
    """Meilenstein als EINE Zeile: - | Schwelle | + | Quote | Buchmacher | Entfernen (genau eine Quote: mindestens so viele Punkte, kein Under)."""
    base = f"{prefix}_{rid}"
    if line is not None:
        d_thr, d_odds, d_bm = str(line["threshold"]), fmt_odds(line["odds"]), line.get("bookmaker") or ""
    else:
        d_thr, d_odds, d_bm = "", "", st.session_state.get(ref_book_key, "")
    cols = st.columns(MS_W)
    kw = dict(label_visibility="collapsed")
    cols[0].button("−", key=f"{base}_minus", on_click=_ms_step, args=(base, -1), use_container_width=True, help="Schwelle um 1 verringern")
    _text(cols[1], "Schwelle (Punkte)", f"{base}_line", d_thr, placeholder="19", **kw)
    cols[2].button("\\+", key=f"{base}_plus", on_click=_ms_step, args=(base, 1), use_container_width=True, help="Schwelle um 1 erhöhen")
    _text(cols[3], "Quote (mindestens)", f"{base}_over", d_odds, placeholder="2,50", **kw)
    if leader:
        _text(cols[4], "Buchmacher (Zeile)", f"{base}_book", d_bm, placeholder="Buchmacher", on_change=_follow_book, args=(f"{base}_book", f"{prefix}__new", prefix), **kw)
    else:
        _text(cols[4], "Buchmacher (Zeile)", f"{base}_book", d_bm, placeholder="Buchmacher", on_change=_book_dirty, args=(base,), **kw)
    if rid.startswith("n"):
        cols[5].button("Entfernen", key=f"{base}_rm", type="tertiary", use_container_width=True, on_click=_ou_discard, args=(prefix, rid))
        return False
    return cols[5].button("Entfernen", key=f"{base}_rm", type="tertiary", use_container_width=True)


def _pp_value(prefix: str, rid: str, mode: str) -> float | None:
    try:
        t = st.session_state.get(f"{prefix}_{rid}_line")
        return float(store.parse_threshold_input(t)) if mode == "milestones" else store.parse_player_line_input(t)
    except store.OddsInputError:
        return None


def _pp_add_row(prefix: str, saved_ids: list, mode_key: str) -> None:
    """on_click von '+ Meilenstein hinzufuegen' / '+ Linie hinzufuegen': naechste Schwelle = letzte + 1 (Linie: + 1,0), Buchmacher der ersten Zeile vorbelegt."""
    ss = st.session_state
    mode = "line" if ss.get(mode_key) == MODE_LABELS["line"] else "milestones"
    ids = ss.setdefault(f"{prefix}__new", [])
    cap = store.MAX_MILESTONES if mode == "milestones" else store.MAX_PLAYER_LINES
    if len(saved_ids) + len(ids) >= cap:
        return
    allids = list(saved_ids) + list(ids)
    vals = [v for v in (_pp_value(prefix, i, mode) for i in allids) if v is not None]
    ctr = ss[f"{prefix}__ctr"] = ss.get(f"{prefix}__ctr", 0) + 1
    nid = f"n{ctr}"
    ids.append(nid)
    ss[f"{prefix}_{nid}_book"] = ss.get(f"{prefix}_{allids[0]}_book", "") if allids else ""
    if vals:
        nxt = max(vals) + 1
        if mode == "milestones" and nxt <= store.MAX_THRESHOLD:
            ss[f"{prefix}_{nid}_line"] = str(int(nxt))
        elif mode == "line" and nxt <= store.MAX_PLAYER_LINE:
            ss[f"{prefix}_{nid}_line"] = fmt_total(nxt)


def _pp_mode_changed(prefix: str) -> None:
    """Moduswechsel (nur bei noch nicht gespeichertem Spieler): die noch nicht gespeicherten Zeilen werden geleert, nicht still: Hinweis."""
    ss = st.session_state
    for k in [k for k in ss.keys() if isinstance(k, str) and k.startswith(prefix + "_n") and k != f"{prefix}__new" and not k.endswith("_who")]:
        del ss[k]
    ctr = ss[f"{prefix}__ctr"] = ss.get(f"{prefix}__ctr", 0) + 1
    ss[f"{prefix}__new"] = [f"n{ctr}"]
    ss[f"{prefix}__notice"] = "Modus gewechselt: die noch nicht gespeicherten Zeilen dieses Spielers wurden geleert."


def _pp_add_block(kid: str) -> None:
    """on_click von '+ Spieler hinzufuegen': neuer Block (Standard Meilensteine) mit einer leeren Zeile."""
    ss = st.session_state
    ids = ss.setdefault(f"pm_pp_{kid}__new", [])
    ctr = ss[f"pm_pp_{kid}__ctr"] = ss.get(f"pm_pp_{kid}__ctr", 0) + 1
    bid = f"n{ctr}"
    ids.append(bid)
    b = _pp_prefix(kid, bid)
    ss[f"{b}_mode"] = MODE_LABELS["milestones"]
    ss[f"{b}_who"] = None
    ss[f"{b}__ctr"] = 1
    ss[f"{b}__new"] = ["n1"]


def _pp_discard_block(kid: str, bid: str) -> None:
    ids = st.session_state.get(f"pm_pp_{kid}__new", [])
    if bid in ids:
        ids.remove(bid)


def _player_block(kid: str, bid: str, saved: dict | None, labels: dict, options: list, removed: dict) -> None:
    """Ein Spielerblock: Spieler-Auswahl (Tippen zum Filtern), Modus-Umschalter, 'Spieler entfernen', Kopfzeile, Zeilen, Hinzufuegen-Knopf.
    Ein gespeicherter Block ist fest (Spieler und Modus gesperrt)."""
    ss = st.session_state
    prefix = _pp_prefix(kid, bid)
    mode_key, who_key = f"{prefix}_mode", f"{prefix}_who"
    _ss_default(who_key, saved["person_id"] if saved else None)
    _ss_default(mode_key, MODE_LABELS[saved["mode"]] if saved else MODE_LABELS["milestones"])
    if ss.get(who_key) not in options:                      # z. B. nach einer Kader-Aktualisierung: ungueltige Auswahl zuruecksetzen
        ss[who_key] = None
    new_rows = ss.setdefault(f"{prefix}__new", [])
    saved_rows = store.player_lines(saved) if saved else []
    with st.container(border=True):
        c1, c2, c3 = st.columns([3.2, 2.2, 1.1])
        c1.selectbox("Spieler", options, key=who_key, format_func=lambda v: labels.get(v, "Spieler wählen …") if v is not None else "Spieler wählen …",
                     label_visibility="collapsed", disabled=saved is not None, help="Eintippen zum Filtern (Akzente egal: „Jokic“ findet „Jokić“).")
        c2.radio("Modus", list(MODE_LABELS.values()), key=mode_key, horizontal=True, label_visibility="collapsed", disabled=saved is not None,
                 on_change=_pp_mode_changed, args=(prefix,),
                 help="Meilensteine: „mindestens N Punkte“ mit einer Quote. Einzellinie: Linie mit Over/Under. Nach dem Speichern ist der Modus fest." if saved is None
                 else "Der Modus ist gespeichert. Zum Wechseln den Spieler entfernen und neu anlegen.")
        if saved is not None:
            if c3.button("Spieler entfernen", key=f"{prefix}_rmplayer", type="tertiary", use_container_width=True):
                removed["block"] = bid
        else:
            c3.button("Spieler entfernen", key=f"{prefix}_rmplayer", type="tertiary", use_container_width=True, on_click=_pp_discard_block, args=(kid, bid))
        notice = ss.pop(f"{prefix}__notice", None)
        if notice:
            st.caption(notice)
        mode = "line" if ss.get(mode_key) == MODE_LABELS["line"] else "milestones"
        rows = [(l["id"], l) for l in saved_rows] + [(n, None) for n in new_rows]
        if rows:
            if mode == "milestones":
                _header(MS_W, ["", "Schwelle", "", "Quote", "Buchmacher", ""])
            else:
                _header(OU_W, ["Quote Over", "", "Linie", "", "Quote Under", "Buchmacher", ""])
        first_key = f"{prefix}_{rows[0][0]}_book" if rows else ""
        for i, (rid, line) in enumerate(rows):
            pressed = (_ms_compact_row(prefix, rid, line, first_key, i == 0) if mode == "milestones"
                       else _ou_compact_row(prefix, rid, line, PLAYER_CFG, ref_book_key=first_key, leader=(i == 0)))
            if pressed:
                removed["line"] = (bid, rid)
        cap = store.MAX_MILESTONES if mode == "milestones" else store.MAX_PLAYER_LINES
        count = len(rows)
        st.button("\\+ Meilenstein hinzufügen" if mode == "milestones" else "\\+ Linie hinzufügen", key=f"{prefix}_addrow", disabled=count >= cap,
                  on_click=_pp_add_row, args=(prefix, [l["id"] for l in saved_rows], mode_key))
        if count >= cap:
            st.caption(f"maximal {cap} {'Meilensteine' if mode == 'milestones' else 'Linien'} je Spieler")


def _player_fields(g: dict, kid: str, entry: dict | None, last_book: str, roster: dict) -> tuple[list, dict]:
    """Spielerpunkte: Spielerbloecke (bis 10) mit Auswahl aus dem Kader der beiden Teams. Gibt ([(block_id, mode, [row_ids])] der gespeicherten Bloecke,
    {person_id: Spieler}) zurueck; die Werte werden beim Speichern aus dem Session State gelesen."""
    ss = st.session_state
    saved_blocks = store.active_player_blocks(entry)
    new_ids = ss.setdefault(f"pm_pp_{kid}__new", [])
    players, missing = ([], []) if roster["status"] != "ok" else rosters.game_players(roster, g["away"], g["home"])
    lookup = {p["person_id"]: p for p in players}
    if roster["status"] != "ok":
        st.info("Keine Kaderdatei. Bitte „Kader aktualisieren“ drücken. Die Spielerauswahl ist deaktiviert." if roster["status"] == "missing"
                else "Die Kaderdatei ist nicht lesbar. Bitte „Kader aktualisieren“ drücken. Die Spielerauswahl ist deaktiviert.")
    elif missing:
        st.info("Im Kader fehlt: " + ", ".join(missing) + (". Nur das vorhandene Team wird angeboten." if players else ". Die Spielerauswahl ist leer.") + " Bitte „Kader aktualisieren“ drücken.")
    labels = {p["person_id"]: rosters.player_label(p) for p in players}
    for b in saved_blocks:                                   # gespeicherte Spieler bleiben waehlbar, auch wenn der Kader sich geaendert hat
        labels.setdefault(b["person_id"], f'{b["name"]} · {b.get("team_abbreviation") or ""}'.strip(" ·"))
    options = [None] + list(labels.keys())
    removed: dict = {}
    for b in saved_blocks:
        _player_block(kid, b["id"], b, labels, options, removed)
    for bid in list(new_ids):
        _player_block(kid, bid, None, labels, options, removed)
    n = len(saved_blocks) + len(new_ids)
    st.button("\\+ Spieler hinzufügen", key=f"pm_pp_{kid}_addblock", disabled=n >= store.MAX_PLAYERS or roster["status"] != "ok" or not players,
              on_click=_pp_add_block, args=(kid,))
    if n >= store.MAX_PLAYERS:
        st.caption(f"maximal {store.MAX_PLAYERS} Spieler je Spiel")
    st.caption("Spieler nicht gefunden? „Kader aktualisieren“ drücken.")
    if removed:
        try:
            if "block" in removed:
                store.remove_player_block(g["date"], g["start"], g["home"], g["away"], removed["block"], now=_now())
            else:
                store.remove_player_line(g["date"], g["start"], g["home"], g["away"], removed["line"][0], removed["line"][1], now=_now())
        except (store.OddsInputError, store.GameStartedError, store.StoreError) as e:
            st.warning(str(e))
        else:
            ss[f"pm_flash_{kid}"] = "Entfernt (bleibt als Revision in der Datei)."
            st.rerun(scope="app")
    return [(b["id"], b["mode"], [l["id"] for l in store.player_lines(b)]) for b in saved_blocks], lookup


def _pp_payload(kid: str, saved: list, lookup: dict) -> list[dict]:
    """Spielerbloecke fuer den Speicher aus dem Session State (gespeicherte Bloecke mit ihrer festen Identitaet, neue Bloecke mit der Auswahl)."""
    ss = st.session_state
    blocks = []
    saved_meta = {bid: (mode, ids) for bid, mode, ids in saved}
    ids_order = [b for b, _m, _i in saved] + list(ss.get(f"pm_pp_{kid}__new", []))
    for bid in ids_order:
        prefix = _pp_prefix(kid, bid)
        if bid in saved_meta:
            mode, row_ids = saved_meta[bid]
            blk = {"block_id": bid, "person_id": ss.get(f"{prefix}_who"), "name": "", "team": "", "team_abbreviation": ""}
        else:
            mode = "line" if ss.get(f"{prefix}_mode") == MODE_LABELS["line"] else "milestones"
            row_ids = []
            pid = ss.get(f"{prefix}_who")
            p = lookup.get(pid, {})
            blk = {"block_id": None, "person_id": pid, "name": p.get("name", ""), "team": p.get("team", ""), "team_abbreviation": p.get("team_abbreviation", "")}
        rows = []
        for rid in list(row_ids) + list(ss.get(f"{prefix}__new", [])):
            b = f"{prefix}_{rid}"
            row = {"id": None if rid.startswith("n") else rid, "value": ss.get(f"{b}_line"), "bookmaker": ss.get(f"{b}_book")}
            if mode == "milestones":
                row["odds"] = ss.get(f"{b}_over")
            else:
                row["over_odds"], row["under_odds"] = ss.get(f"{b}_over"), ss.get(f"{b}_under")
            rows.append(row)
        blk.update(mode=mode, rows=rows)
        blocks.append(blk)
    return blocks


def _player_points_readonly(entry: dict | None, state: str) -> None:
    reason = _lock_reason(state)
    blocks = store.active_player_blocks(entry)
    if not blocks:
        st.markdown(f'<div class="pm-text">Keine Spielerpunkte vor dem Anpfiff eingetragen.</div><div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)
        return
    for b in blocks:
        st.markdown(f'<div class="pm-team-title">{escape(b["name"])} · {escape(b.get("team_abbreviation") or b.get("team") or "")} ({MODE_LABELS[b["mode"]]})</div>', unsafe_allow_html=True)
        rows = ""
        for l in store.player_lines(b):
            if b["mode"] == "milestones":
                value = f'+{l["threshold"]} Punkte · {fmt_odds(l["odds"])}'
            else:
                value = f'Over {fmt_odds(l["over_odds"])} &nbsp;|&nbsp; {fmt_total(l["line"])} &nbsp;|&nbsp; Under {fmt_odds(l["under_odds"])}'
            rows += f'<div class="pc-row"><span class="pc-k">{escape(l.get("bookmaker") or "—")} · {berlin_stamp(l.get("entered_at"))} Uhr</span><span class="pc-v pc-v-model">{value}</span></div>'
        st.markdown(f'<div class="pm-rows">{rows}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="pm-note">{escape(reason)}</div>', unsafe_allow_html=True)
