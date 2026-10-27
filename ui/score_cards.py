"""
Karten fuer den Tab "Score Projections" (nur Darstellung, keine Rechnung).

build_card_vm(proj)      -> Anzeigewerte einer Karte aus dem Projektions-Dict (compute_projection + app.py-Felder)
render_card_html(vm)     -> HTML der Karte (mehrzeilig; app.py reicht es durch flat_html())
CARD_CSS                 -> Stylesheet (einmal pro Tab einbinden)

Gestaltungsregeln: DESIGN_REGELN.md. Logos kommen NUR aus data/logos (eingebettet), nie live.
"""
from __future__ import annotations

import base64
import functools
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path

from config.settings import SPREAD_DEVIATION_YELLOW, TOTAL_DEVIATION_YELLOW
from engine import betano_quotes as bq
from engine import safety_levels as safety

LOGO_DIR = Path(__file__).resolve().parent.parent / "data" / "logos"

# Farben (Kontrast gegen den jeweiligen Hintergrund wird in tests/test_score_cards.py geprueft, >= 4,5 : 1)
PALETTE = {
    "card_bg": "#141726",
    "page_bg": "#0a0a0f",
    "text": "#f1f4fa",          # Teamname, Modellwerte
    "text_soft": "#d7deec",     # Marktwerte, Leistenbeschriftung
    "label": "#a3aec4",         # kleine Labels
    "at": "#8f9bb3",
    "accent": "#f97316",        # NUR Favoriten-Score und Favoriten-Anteil der Leiste
    "dog": "#aab4c8",           # Score des Underdogs
    "bar_other": "#3b4560",
    "chip_gray_bg": "#232940", "chip_gray_text": "#cdd5e6", "chip_gray_border": "#3a4363",
    "chip_yellow_bg": "#3a3212", "chip_yellow_text": "#fde047", "chip_yellow_border": "#8a7314",
    "logo_bg": "#e9edf5",       # heller Kreis hinter den Logos (dunkle Logos wie Spurs/Nets bleiben sichtbar)
    "chip_blue_bg": "#1b2a42", "chip_blue_text": "#bcd0ec", "chip_blue_border": "#3d5a85",   # dezentes Blaugrau (Status "gespeichert")
    "pill_text": "#ffffff",     # weisse, fette Schrift in der Plakette der vorhergesagten Seite
    "pill_bg": "#ea580c",       # Plaketten-Hintergrund: leicht abgedunkeltes Orange (weisse 16-px-Fettschrift: Kontrast >= 3 : 1 = WCAG grosser Text; auf #f97316 waeren es nur 2,8 : 1). Der Balken bleibt #f97316.
    "fb_bg": "#1d2236", "fb_text": "#d7deec", "fb_border": "#4a5572",
    # Sieger-Zeichen "erfuellt" (Sicherheitsstufe, DESIGN_REGELN.md Regel 89): die EINZIGE gruene Stelle der Karte, nie fuer Abweichungen Modell gegen Markt
    "win_ok_bg": "#12301f", "win_ok_text": "#86efac", "win_ok_border": "#2f7d4f",
}

# (Kuerzel, Stadt, Teamname). Abgleich mit nba_api in tests/test_score_cards.py.
TEAMS = [
    ("ATL", "Atlanta", "Hawks"), ("BKN", "Brooklyn", "Nets"), ("BOS", "Boston", "Celtics"),
    ("CHA", "Charlotte", "Hornets"), ("CHI", "Chicago", "Bulls"), ("CLE", "Cleveland", "Cavaliers"),
    ("DAL", "Dallas", "Mavericks"), ("DEN", "Denver", "Nuggets"), ("DET", "Detroit", "Pistons"),
    ("GSW", "Golden State", "Warriors"), ("HOU", "Houston", "Rockets"), ("IND", "Indiana", "Pacers"),
    ("LAC", "Los Angeles", "Clippers"), ("LAL", "Los Angeles", "Lakers"), ("MEM", "Memphis", "Grizzlies"),
    ("MIA", "Miami", "Heat"), ("MIL", "Milwaukee", "Bucks"), ("MIN", "Minnesota", "Timberwolves"),
    ("NOP", "New Orleans", "Pelicans"), ("NYK", "New York", "Knicks"), ("OKC", "Oklahoma City", "Thunder"),
    ("ORL", "Orlando", "Magic"), ("PHI", "Philadelphia", "76ers"), ("PHX", "Phoenix", "Suns"),
    ("POR", "Portland", "Trail Blazers"), ("SAC", "Sacramento", "Kings"), ("SAS", "San Antonio", "Spurs"),
    ("TOR", "Toronto", "Raptors"), ("UTA", "Utah", "Jazz"), ("WAS", "Washington", "Wizards"),
]
_NICK_TO_TEAM = {nick.lower(): (abbr, city, nick) for abbr, city, nick in TEAMS}
_ABBR_TO_TEAM = {abbr: (abbr, city, nick) for abbr, city, nick in TEAMS}


def team_info(name: str) -> dict:
    """Ordnet einen Teamnamen (BallDontLie, Odds API, NBA.com) einem NBA-Team zu.
    "LA Clippers" und "Los Angeles Clippers" ergeben dasselbe Team (Zuordnung ueber den eindeutigen Teamnamen).
    Unbekannte Namen: Kuerzel aus den ersten Buchstaben des letzten Wortes, abbr_known = False."""
    raw = (name or "").strip()
    low = raw.lower()
    if raw.upper() in _ABBR_TO_TEAM:
        abbr, city, nick = _ABBR_TO_TEAM[raw.upper()]
        return {"abbr": abbr, "city": city, "nick": nick, "known": True}
    for nick_low in sorted(_NICK_TO_TEAM, key=len, reverse=True):      # lange Namen zuerst ("trail blazers")
        if low == nick_low or low.endswith(" " + nick_low):
            abbr, city, nick = _NICK_TO_TEAM[nick_low]
            return {"abbr": abbr, "city": city, "nick": nick, "known": True}
    words = raw.split()
    nick = words[-1] if words else "?"
    return {"abbr": nick[:3].upper(), "city": " ".join(words[:-1]), "nick": nick, "known": False}


@functools.lru_cache(maxsize=64)
def _logo_uri(logo_dir: str, abbr: str) -> str | None:
    path = Path(logo_dir) / f"{abbr}.svg"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"<svg" not in data[:2000].lower():
        return None
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")


def logo_uri(abbr: str, logo_dir: Path | str | None = None) -> str | None:
    return _logo_uri(str(logo_dir or LOGO_DIR), abbr)


# ---------------------------------------------------------------------------------------- Formatierung
MINUS = "−"


def fmt_num(value: float, decimals: int = 1, signed: bool = False) -> str:
    """Deutsche Zahl: Komma als Dezimaltrenner, echtes Minuszeichen."""
    text = f"{abs(value):.{decimals}f}".replace(".", ",")
    if value < 0 and float(text.replace(",", ".")) != 0:
        return MINUS + text
    return ("+" + text) if signed and value > 0 else text


def spread_label(home_nick: str, away_nick: str, spread: float) -> str:
    """Favorit mit Minus; spread: positiv = Heimteam ist Favorit."""
    spread = round(float(spread), 1)
    if spread == 0:
        return "PK"
    return f"{home_nick if spread > 0 else away_nick} {MINUS}{fmt_num(abs(spread))}"


BERLIN = ZoneInfo("Europe/Berlin")


def _hhmm(ts, now: float | None = None) -> str:
    """'HH:MM' (Berliner Zeit); an einem anderen Tag als jetzt mit Datum ('20.10. 22:00')."""
    if ts is None:
        return ""
    now = now if now is not None else time.time()
    dt = datetime.fromtimestamp(float(ts), BERLIN)
    return dt.strftime("%H:%M") if dt.date() == datetime.fromtimestamp(now, BERLIN).date() else dt.strftime("%d.%m. %H:%M")


def _origin_part(res: dict, now: float | None) -> str:
    """Quelle einer Marktlinie: 'Eigene Linie · Betano · 23:40', 'Cache 22:00' oder 'keine Linie'."""
    if res.get("line") is None:
        return "keine Linie"
    if res.get("source") == "eigene Eingabe":
        return " · ".join(x for x in ("Eigene Linie", res.get("bookmaker") or "", _hhmm(res.get("at"), now)) if x)
    return ("Cache " + _hhmm(res.get("at"), now)).strip()


def origin_info(proj: dict, h: dict, a: dict, now: float | None = None) -> tuple[str | None, list[str]]:
    """Herkunftszeile ('Spread: Eigene Linie · Betano · 23:40 | Total: Cache 22:00 | Team Totals: ...') und gelbe Hinweise bei grosser
    Abweichung der eigenen Linie vom Cache. Stammen alle vier Maerkte aus derselben Quelle, genuegt 'Alle Linien: ...'.
    Ohne market_lines (z. B. Mock-Daten): (None, [])."""
    ml = proj.get("market_lines")
    if not ml:
        return None, []
    parts = {m: _origin_part(ml[m], now) for m in ("spread", "total", "team_total_away", "team_total_home")}
    if len(set(parts.values())) == 1:
        text = "Alle Linien: " + parts["spread"]
    else:
        if parts["team_total_away"] == parts["team_total_home"]:
            tt = parts["team_total_away"]
        else:
            tt = f"Gast {parts['team_total_away']} / Heim {parts['team_total_home']}"
        text = f"Spread: {parts['spread']} | Total: {parts['total']} | Team Totals: {tt}"
    warns = []
    names = {"spread": "Spread", "total": "Total", "team_total_away": f"Team Total {a['nick']}", "team_total_home": f"Team Total {h['nick']}"}
    for m, res in ml.items():
        if not res.get("warn"):
            continue
        if m == "spread":
            x, y = spread_label(h["nick"], a["nick"], res["line"]), spread_label(h["nick"], a["nick"], res["cache_line"])
        else:
            x, y = fmt_num(res["line"]), fmt_num(res["cache_line"])
        warns.append(f"{names[m]}: Eigene Linie weicht stark vom Cache ab ({x} vs. {y}), bitte prüfen")
    return text, warns


def build_card_vm(proj: dict, entry: dict | None = None, tables: dict | None = None, result: dict | None = None) -> dict:
    """Anzeigewerte. Rechnet nichts neu: alle Zahlen stammen aus proj; Abweichungen sind Differenzen der angezeigten Werte."""
    h, a = team_info(proj["home_team"]), team_info(proj["away_team"])
    h["name"], a["name"] = proj["home_team"], proj["away_team"]
    h["score"], a["score"] = proj["home_score"], proj["away_score"]
    h["p"], a["p"] = float(proj["home_win_prob"]), float(proj["away_win_prob"])
    h["pct"], a["pct"] = round(h["p"] * 100), round(a["p"] * 100)       # wie bisher: Python-round
    fav = "home" if h["p"] > a["p"] else "away" if a["p"] > h["p"] else None

    # Spread (positiv = Heimteam ist Favorit)
    model_spread = round(float(proj["exp_spread"]), 1)
    market_spread = proj.get("market_spread")
    sp = {"model": spread_label(h["nick"], a["nick"], model_spread), "market": "—", "dev": None,
          "dev_text": "ohne Marktlinie", "yellow": False}
    if market_spread is not None:
        ms = round(float(market_spread), 1)
        sp["market"] = spread_label(h["nick"], a["nick"], ms)
        d = round(model_spread - ms, 1)
        sp["dev"] = d
        if d > 0:
            sp["dev_text"] = f"Modell sieht {h['nick']} um {fmt_num(d)} stärker"
        elif d < 0:
            sp["dev_text"] = f"Modell sieht {a['nick']} um {fmt_num(abs(d))} stärker"
        else:
            sp["dev_text"] = "Modell und Markt stimmen überein"
        sp["yellow"] = abs(d) >= SPREAD_DEVIATION_YELLOW

    # Total
    exp_total = float(proj["exp_total"])
    market_total = proj.get("market_total")
    tt = {"model": fmt_num(exp_total), "market": "—", "dev": None,
          "dev_text": "ohne Marktlinie", "yellow": False}
    total_diff = None
    if market_total:
        total_diff = round(exp_total - market_total, 1)       # wie bisher (Market-Disagreement-Logik)
        tt["market"] = fmt_num(float(market_total))
        tt["dev"] = total_diff
        if total_diff > 0:
            tt["dev_text"] = f"Modell {fmt_num(total_diff)} Punkte über dem Markt"
        elif total_diff < 0:
            tt["dev_text"] = f"Modell {fmt_num(abs(total_diff))} Punkte unter dem Markt"
        else:
            tt["dev_text"] = "Modell und Markt stimmen überein"
        tt["yellow"] = abs(total_diff) >= TOTAL_DEVIATION_YELLOW

    # Warnungen: Logik unveraendert
    warnings = []
    if proj.get("lineup_warning"):
        warnings.append("LINEUP RISK")
    if total_diff is not None and abs(total_diff) >= 8:
        warnings.append("MARKET DISAGREEMENT")

    total_diff_display = f"{total_diff:+.1f}" if total_diff is not None else "—"
    details = [
        f"raw model total: {proj['model_total']}",
        f"raw model vs market: {proj['market_diff']}",
        f"market weight: {proj['market_weight']}",
        f"final vs market diff: {total_diff_display}",
        f"playoff modifier: {'ON (-4 total)' if proj.get('is_playoff') else 'OFF'}",
        f"bias adj: H {proj['home_bias_adjustment']:+.1f} / A {proj['away_bias_adjustment']:+.1f}",
    ]
    origin, origin_warnings = origin_info(proj, h, a)
    win_note = None                                  # nur Projektionen mit Siegchance aus der Spread-Verteilung (sigmas_version 2); aeltere Schnappschuss-Karten: kein Hinweis
    if proj.get("win_prob_source") == "normal_spread" and proj.get("sigma_spread"):
        win_note = f"Siegchance und Spread aus derselben Verteilung (Sigma {fmt_num(float(proj['sigma_spread']))})"
    snapshot = tables is not None or result is not None          # Schnappschuss-Karten beendeter Spiele: unveraendert (keine Sicherheitsstufen)
    vm = {"home": h, "away": a, "fav": fav, "spread": sp, "total": tt, "warnings": warnings, "details": details, "win_note": win_note,
          "origin": origin, "origin_warnings": origin_warnings, "lines": _line_blocks(proj, entry, h, a, tables, result),
          "winner": None if snapshot else safety.winner_sign(max(h["p"], a["p"]) if fav else None)}
    vm["minodds_note"] = bool(vm["lines"]) and not snapshot
    vm["moneyline"] = None if snapshot else bq.winner_quotes(entry)          # gespeicherte Betano-Sieger-Quoten (Gast/Heim) als Text, sonst None
    t2 = proj.get("team2")
    if t2 and t2.get("active") and tables is None and result is None:       # nur laufende Projektionen; beendete Spiele (Schnappschuss-Karten) bleiben wie gespeichert
        from engine import team_injury as ti
        vm2 = build_card_vm(ti.variant_proj({k: v for k, v in proj.items() if k != "team2"}, t2), entry)
        vm["t2"] = {"vm": vm2, "note": ti.note_text(proj, t2, h["nick"], a["nick"]), "delta": t2.get("delta_spread")}
    return vm


# ---------------------------------------------------------------------------------------- HTML
def _fmt_x(x: float) -> str:
    """Linie mit echtem Minus; ganzzahlig mit einer Nachkommastelle ('231,0')."""
    return fmt_num(x)


def _line_blocks(proj: dict, entry: dict | None, h: dict, a: dict, tables: dict | None = None, result: dict | None = None) -> list[dict] | None:
    """Vier Bloecke (SPREAD, TOTAL, TEAM TOTAL Gast, TEAM TOTAL Heim) mit Zeilen: Linie links, Balken mit Prozentzahlen (engine/line_probabilities.py).
    Titel sind fest (aendern sich nie). Ohne market_lines (Mock): None."""
    from engine.line_probabilities import build_line_tables
    live = tables is None and result is None                                         # Schnappschuss-Karten beendeter Spiele: keine Betano-Quoten
    tables = tables if tables is not None else build_line_tables(proj, entry)       # tables: gespeicherte Zeilen eines beendeten Spiels (Schnappschuss)
    if tables is None:
        return None
    blocks = []
    for key, title in (("spread", "SPREAD"), ("total", "TOTAL"), ("team_away", f"TEAM TOTAL · {a['nick']}"), ("team_home", f"TEAM TOTAL · {h['nick']}")):
        t = tables[key]
        rows = []
        for r in t["rows"]:
            outcome = None
            if result:                                 # nur beendete Spiele mit Ergebnis: Chip eingetreten / nicht eingetreten / Push
                from engine.line_probabilities import row_outcome
                outcome = row_outcome(t["kind"], r, t.get("favorite"), result["home_points"], result["away_points"], key)
            r = {**r, "outcome": outcome}
            if t["kind"] == "spread":
                fav_home = t["favorite"] == "home"
                fav_nick, dog_nick = (h["nick"], a["nick"]) if fav_home else (a["nick"], h["nick"])
                x = r["line"]
                label = f"{fav_nick} {MINUS}{fmt_num(x)}" if x > 0 else f"{fav_nick} +{fmt_num(abs(x))}" if x < 0 else "PK"
                left_name, right_name = a["nick"], h["nick"]
                rows.append({**r, "label": label, "left": f"{left_name} {r['p_left']} %", "right": f"{r['p_right']} % {right_name}", "style": "spread", "min_odds": safety.row_min_odds_text(r),
                             "quote": bq.row_quote_text(entry, key, t, r) if live else None})
            else:
                rows.append({**r, "label": fmt_num(r["line"]), "left": f"Over {r['p_left']} %", "right": f"{r['p_right']} % Under", "style": "ou", "min_odds": safety.row_min_odds_text(r),
                             "quote": bq.row_quote_text(entry, key, t, r) if live else None})
        blocks.append({"key": key, "title": title, "rows": rows, "note": t.get("note"), "source": t.get("source")})
    return blocks


OUTCOME_TEXT = {"hit": "eingetreten", "miss": "nicht eingetreten", "push": "Push"}


def line_block_body_html(block: dict) -> str:
    """Zeilen eines Blocks (Linie links, Balken in der Mitte, Prozentzahlen an beiden Enden). In JEDER Zeile (Spread, Total, Team Total) ist die
    wahrscheinlichere Seite orange (Balkenanteil + Prozentzahl in einer Plakette), die andere gedaempft wie im Sieg-Balken. Bei 50 : 50 (nach Rundung)
    gibt es keine Plakette und beide Seiten sind gedaempft. Over/Gast steht immer links, Under/Heim rechts. Hauptlinie hervorgehoben."""
    if not block["rows"]:
        return f'<div class="pc-lnote">{escape(block.get("note") or "keine Linie")}</div>'
    body = ""
    has_min = any(r.get("min_odds") for r in block["rows"])           # Spalte "Mindestquote" nur, wenn mindestens eine Zeile eine Seite mit Chance >= 50 % hat (nicht in Schnappschuss-Karten)
    has_q = any(r.get("quote") for r in block["rows"])                # Spalte "Quote" (Betano, orange Seite) nur, wenn mindestens eine Zeile eine gespeicherte Betano-Quote hat
    if has_q:
        body += ('<div class="pc-lhead pc-lhgrid pc-lqcol' + (' pc-lmincol' if has_min else '') + '"><span></span><span class="pc-lhq">Quote</span><span></span><span></span><span></span>'
                 + ('<span class="pc-lhm">Mindestquote</span>' if has_min else '') + '</div>')
    elif has_min:
        body += '<div class="pc-lhead"><span>Mindestquote</span></div>'
    for r in block["rows"]:
        lcls = "pc-lseg pc-seg-fav" if r["predicted"] == "left" else "pc-lseg pc-seg-other"
        rcls = "pc-lseg pc-seg-fav" if r["predicted"] == "right" else "pc-lseg pc-seg-other"
        main = (" pc-lmain" if r["is_main"] else "") + (" pc-lrow-chip" if r.get("outcome") else "") + (" pc-lmincol" if has_min else "") + (" pc-lqcol" if has_q else "")
        qcell = f'<span class="pc-lq">{escape(r["quote"]) if r.get("quote") else ""}</span>' if has_q else ""
        mincell = (f'<span class="pc-lmin">{escape(r["min_odds"]) if r.get("min_odds") else "–"}</span>' if has_min else "")
        chip = (f'<span class="pc-lchip pc-lchip-{r["outcome"]}">{OUTCOME_TEXT[r["outcome"]]}</span>' if r.get("outcome") else "")
        tag = '<span class="pc-ltag">Hauptlinie</span>' if r["is_main"] else ""
        body += (f'<div class="pc-lrow{main}"><span class="pc-lline">{escape(r["label"])}{tag}</span>{qcell}'
                 f'<span class="pc-lpct pc-lpct-l"><span class="pc-lpill{" pc-lpct-pred" if r["predicted"] == "left" else ""}">{escape(r["left"])}</span></span>'
                 f'<span class="pc-lbar" role="img" aria-label="{escape(r["left"])} gegen {escape(r["right"])}">'
                 f'<span class="{lcls}" style="width:{r["p_left"]}%"></span><span class="{rcls}" style="width:{r["p_right"]}%"></span></span>'
                 f'<span class="pc-lpct pc-lpct-r"><span class="pc-lpill{" pc-lpct-pred" if r["predicted"] == "right" else ""}">{escape(r["right"])}</span></span>{chip}{mincell}</div>')
    if block.get("note"):
        body += f'<div class="pc-lnote">{escape(block["note"])}</div>'
    return body


def render_line_expanders(vm: dict, key: str) -> None:
    """Vier Streamlit-Expander (SPREAD, TOTAL, TEAM TOTAL Gast, TEAM TOTAL Heim) direkt unter der Karte, standardmaessig zu, mit festem Titel
    (Titel und expanded aendern sich nie, damit Streamlit den Auf/Zu-Zustand bei jedem Rerun behaelt). Kein Expander im Expander."""
    if not vm.get("lines"):
        return
    import streamlit as st
    with st.container(key=f"sc_lines_{key}"):
        t2_lines = {b["key"]: b for b in (vm.get("t2") or {}).get("vm", {}).get("lines") or []}
        for block in vm["lines"]:
            with st.expander(block["title"]):
                body = line_block_body_html(block)
                if block["key"] in t2_lines and block["key"] != "total":          # Spread und Team Totals aendern sich mit dem Schalter, das Total nicht
                    body = f'<div class="pc-var pc-var-std">{body}</div><div class="pc-var pc-var-t2">{line_block_body_html(t2_lines[block["key"]])}</div>'
                st.markdown("".join(line.strip() for line in body.splitlines()), unsafe_allow_html=True)
        if vm.get("minodds_note"):
            st.markdown(f'<div class="pc-minnote">{escape(safety.note_text())}</div>', unsafe_allow_html=True)


def _logo_html(team: dict, logo_dir) -> str:
    uri = logo_uri(team["abbr"], logo_dir) if team["known"] else None
    if uri:
        return f'<div class="pc-logo-badge"><img class="pc-logo" alt="{escape(team["abbr"])}" src="{uri}"></div>'
    return f'<div class="pc-logo-badge pc-logo-fb" role="img" aria-label="{escape(team["nick"])}">{escape(team["abbr"])}</div>'


def _team_html(team: dict, side_label: str, logo_dir) -> str:
    return (
        '<div class="pc-team">\n'
        f'{_logo_html(team, logo_dir)}\n'
        f'<div class="pc-city">{escape(team["city"])}</div>\n'
        f'<div class="pc-name">{escape(team["nick"])}</div>\n'
        f'<div class="pc-side">{side_label}</div>\n'
        '</div>'
    )


def render_card_head(away_name: str, home_name: str, middle_html: str, logo_dir: Path | str | None = None) -> str:
    """Kopf einer Karte (Logo, Stadt, Teamname, AWAY/HOME links bzw. rechts) mit frei waehlbarer Mitte.
    Wird von Score Projections (Scores) und der Pre-Match-Eingabe (Anpfiff/Status) gemeinsam genutzt."""
    return "\n".join([
        '<div class="pc-head">',
        _team_html(team_info(away_name), "AWAY", logo_dir),
        f'<div class="pc-mid">{middle_html}</div>',
        _team_html(team_info(home_name), "HOME", logo_dir),
        '</div>',
    ])


def _chip(text: str, yellow: bool) -> str:
    return f'<div class="pc-chip {"pc-chip-yellow" if yellow else "pc-chip-gray"}">{escape(text)}</div>'


def _model_col(label: str, block: dict) -> str:
    return (
        '<div class="pc-col">\n'
        f'<div class="pc-label">{label}</div>\n'
        f'<div class="pc-row"><span class="pc-k">Modell</span><span class="pc-v pc-v-model">{escape(block["model"])}</span></div>\n'
        f'<div class="pc-row"><span class="pc-k">Markt</span><span class="pc-v pc-v-market">{escape(block["market"])}</span></div>\n'
        f'{_chip(block["dev_text"], block["yellow"])}\n'
        '</div>'
    )


def _variant_items(vm: dict) -> dict:
    """Die Teile der Karte, die sich zwischen 'Standard' und 'Mit Ausfaellen' aendern: Punkteanzeige, Siegchance-Balken (mit Beschriftung), Spread-Spalte."""
    h, a, fav = vm["home"], vm["away"], vm["fav"]
    cls = lambda side: "pc-score pc-fav" if fav == side else "pc-score pc-dog"
    away_seg = "pc-seg pc-seg-fav" if fav == "away" else "pc-seg pc-seg-other"
    home_seg = "pc-seg pc-seg-fav" if fav == "home" else "pc-seg pc-seg-other"
    return {
        "mid": [f'<span class="{cls("away")}">{a["score"]}</span>', '<span class="pc-at">@</span>', f'<span class="{cls("home")}">{h["score"]}</span>'],
        "bar": [f'<div class="pc-bar-labels"><span>{escape(a["nick"])} {a["pct"]} %</span><span>{escape(h["nick"])} {h["pct"]} %</span></div>',
                f'<div class="pc-bar" role="img" aria-label="Siegwahrscheinlichkeit {escape(a["nick"])} {a["pct"]} %, {escape(h["nick"])} {h["pct"]} %">'
                f'<div class="{away_seg}" style="width:{a["p"] * 100:.1f}%"></div>'
                f'<div class="{home_seg}" style="width:{h["p"] * 100:.1f}%"></div></div>',
                *([f'<div class="pc-bar-odds"><span>{escape("Quote " + ml["away"]) if ml.get("away") else ""}</span><span>{escape("Quote " + ml["home"]) if ml.get("home") else ""}</span></div>'] if (ml := vm.get("moneyline")) else []),
                *([f'<div class="pc-winner pc-winner-{"low" if w["level"] == "low" else "ok"}"><span>{escape(w["text"])}</span></div>'] if (w := vm.get("winner")) else [])],
        "spread": [_model_col("SPREAD", vm["spread"])],
    }


def _switchable(std: list[str], t2: list[str] | None) -> list[str]:
    """Ohne team-2: unveraenderte Teile. Mit team-2: beide Varianten, per CSS (Schalter) umgeblendet."""
    if t2 is None:
        return std
    return ['<div class="pc-var pc-var-std">', *std, '</div>', '<div class="pc-var pc-var-t2">', *t2, '</div>']


def _switch_html() -> str:
    return ('<details class="pc-sw"><summary aria-label="Modellvariante umschalten"><span class="pc-sw-opt pc-sw-std">Standard</span>'
            '<span class="pc-sw-opt pc-sw-t2">Mit Ausfällen</span></summary></details>')


def render_card_html(vm: dict, logo_dir: Path | str | None = None) -> str:
    h, a, fav = vm["home"], vm["away"], vm["fav"]
    t2 = vm.get("t2")
    std = _variant_items(vm)
    alt = _variant_items(t2["vm"]) if t2 else {}
    note_html = f'<div class="pc-warnings"><div class="pc-chip pc-chip-yellow">{escape(t2["note"])}</div></div>' if t2 and t2.get("note") else ""
    warn_html = ""
    if vm["warnings"]:
        warn_html = '<div class="pc-warnings">' + "".join(
            f'<div class="pc-chip pc-chip-yellow">⚠ {escape(w)}</div>' for w in vm["warnings"]) + "</div>"
    details = "".join(f'<div class="pc-info">{escape(line)}</div>' for line in vm["details"])
    origin_html = ""
    if vm.get("origin"):
        origin_html = f'<div class="pc-origin">{escape(vm["origin"])}</div>'
        if vm.get("origin_warnings"):
            origin_html += '<div class="pc-warnings">' + "".join(f'<div class="pc-chip pc-chip-yellow">⚠ {escape(w)}</div>' for w in vm["origin_warnings"]) + "</div>"
    parts = [
        '<div class="pc-card pc-card-attached">' if vm.get("lines") else '<div class="pc-card">',
        _switch_html() if t2 else "",
        '<div class="pc-head">',
        _team_html(a, "AWAY", logo_dir),
        '<div class="pc-mid">',
        *_switchable(std["mid"], alt.get("mid")),
        '</div>',
        _team_html(h, "HOME", logo_dir),
        '</div>',
        *_switchable(std["bar"], alt.get("bar")),
        f'<div class="pc-winnote">{escape(vm["win_note"])}</div>' if vm.get("win_note") else "",
        note_html,
        warn_html,
        '<div class="pc-model-wrap"><div class="pc-model">',
        *_switchable(std["spread"], alt.get("spread")),
        _model_col("TOTAL", vm["total"]),
        '</div></div>',
        origin_html,
        f'<details class="pc-details"><summary>MODEL DETAILS</summary><div class="pc-info-body">{details}</div></details>',
        '</div>',
    ]
    return "\n".join(p for p in parts if p)


def _css() -> str:
    P = PALETTE
    # Breite: Karte nutzt die volle Inhaltsbreite (bis MAX 1400 px); der Inhalt steht zentriert in begrenzter Breite,
    # damit Scores, Leiste und Zahlen nicht weit auseinanderstehen. Schriften wachsen mit der Breite (clamp).
    return f"""
<style>
.pc-card {{ box-sizing:border-box; width:100%; max-width:1400px; background:{P['card_bg']}; border:1px solid #2c3350; border-radius:18px; padding:34px clamp(20px,3vw,48px) 26px; margin:0 0 28px; color:{P['text']}; font-family:'DM Sans',sans-serif; font-variant-numeric:tabular-nums; }}
.pc-head {{ display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:clamp(16px,2.4vw,40px); max-width:1040px; margin:0 auto; }}
.pc-team {{ display:flex; flex-direction:column; align-items:center; text-align:center; gap:4px; min-width:0; }}
.pc-logo-badge {{ width:92px; height:92px; border-radius:50%; background:{P['logo_bg']}; display:flex; align-items:center; justify-content:center; margin-bottom:8px; }}
.pc-logo {{ width:66px; height:66px; object-fit:contain; }}
.pc-logo-fb {{ background:{P['fb_bg']}; border:2px solid {P['fb_border']}; color:{P['fb_text']}; font-weight:700; font-size:24px; letter-spacing:.04em; box-sizing:border-box; }}
.pc-city {{ font-size:12.5px; letter-spacing:.1em; text-transform:uppercase; color:{P['label']}; }}
.pc-name {{ font-size:clamp(22px,2vw,30px); font-weight:700; color:{P['text']}; line-height:1.15; }}
.pc-side {{ font-size:12px; letter-spacing:.16em; color:{P['label']}; margin-top:3px; }}
.pc-mid {{ display:flex; align-items:center; justify-content:center; gap:clamp(14px,2vw,28px); }}
.pc-score {{ font-size:clamp(46px,4.4vw,66px); font-weight:800; line-height:1; font-variant-numeric:tabular-nums; }}
.pc-fav {{ color:{P['accent']}; }}
.pc-dog {{ color:{P['dog']}; }}
.pc-at {{ font-size:clamp(20px,1.8vw,26px); color:{P['at']}; }}
.pc-bar-labels {{ display:flex; justify-content:space-between; max-width:1040px; margin:32px auto 0; font-size:clamp(15px,1.2vw,18px); font-weight:600; color:{P['text_soft']}; font-variant-numeric:tabular-nums; }}
.pc-bar {{ display:flex; height:12px; max-width:1040px; margin:9px auto 0; border-radius:6px; overflow:hidden; background:{P['bar_other']}; }}
.pc-seg-fav {{ background:{P['accent']}; }}
.pc-seg-other {{ background:{P['bar_other']}; }}
.pc-warnings {{ display:flex; flex-wrap:wrap; justify-content:center; gap:10px; max-width:1040px; margin:18px auto 0; }}
.pc-origin {{ font-size:13px; color:{P['label']}; text-align:center; margin-top:16px; }}
.pc-winnote {{ font-size:12px; color:{P['label']}; text-align:center; margin-top:8px; }}
.pc-model-wrap {{ margin-top:28px; padding-top:24px; border-top:1px solid #2c3350; }}
.pc-model {{ display:grid; grid-template-columns:1fr 1fr; gap:clamp(32px,6vw,96px); max-width:780px; margin:0 auto; }}
.pc-label {{ font-size:12px; letter-spacing:.16em; color:{P['label']}; margin-bottom:10px; }}
.pc-row {{ display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:7px 0; font-size:clamp(16px,1.35vw,19px); }}
.pc-k {{ color:{P['label']}; font-size:clamp(14px,1.1vw,16px); }}
.pc-v-model {{ color:{P['text']}; font-weight:700; }}
.pc-v-market {{ color:{P['text_soft']}; font-weight:500; }}
.pc-chip {{ display:inline-block; margin-top:12px; padding:6px 14px; border-radius:999px; font-size:clamp(13px,1vw,14.5px); font-weight:600; letter-spacing:.02em; }}
.pc-chip-gray {{ background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; }}
.pc-chip-yellow {{ background:{P['chip_yellow_bg']}; border:1px solid {P['chip_yellow_border']}; color:{P['chip_yellow_text']}; }}
.pc-warnings .pc-chip {{ margin-top:0; }}
.pc-card-attached {{ margin-bottom:0; border-bottom:none; border-bottom-left-radius:0; border-bottom-right-radius:0; padding-bottom:14px; }}
[class*="st-key-sc_lines_"] {{ box-sizing:border-box; width:100%; max-width:1400px; background:{P['card_bg']}; border:1px solid #2c3350; border-top:none; border-radius:0 0 18px 18px; padding:4px clamp(20px,3vw,48px) 22px; margin:0 0 28px; }}
[class*="st-key-sc_lines_"] [data-testid="stExpander"] {{ margin-top:10px; border-color:#2c3350; }}
[class*="st-key-sc_lines_"] [data-testid="stExpander"] summary {{ font-size:14px; font-weight:700; letter-spacing:.12em; color:{P['text_soft']}; }}
.pc-lrow {{ display:grid; grid-template-columns:minmax(150px,210px) 160px minmax(120px,1fr) 160px; align-items:center; gap:14px; min-height:44px; padding:6px 12px; margin:0 0 6px; border-radius:10px; font-size:16px; }}
.pc-lmain {{ background:#1d2338; box-shadow:inset 3px 0 0 {P['label']}; }}
.pc-lline {{ color:{P['text']}; font-weight:600; font-size:16px; white-space:nowrap; }}
.pc-lmain .pc-lline {{ font-weight:800; }}
.pc-ltag {{ margin-left:8px; font-size:11px; letter-spacing:.08em; color:{P['label']}; font-weight:600; text-transform:uppercase; }}
.pc-lpct {{ display:flex; white-space:nowrap; justify-content:flex-end; }}
.pc-lpct-r {{ justify-content:flex-start; }}
.pc-lpill {{ display:inline-block; padding:4px 11px; border-radius:8px; font-size:16px; color:{P['label']}; }}
.pc-lpct-pred {{ background:{P['pill_bg']}; color:{P['pill_text']}; font-weight:800; }}
.pc-lchip {{ justify-self:end; white-space:nowrap; padding:3px 10px; border-radius:999px; font-size:13px; font-weight:600; }}
.pc-lchip-hit {{ background:{P['chip_blue_bg']}; border:1px solid {P['chip_blue_border']}; color:{P['chip_blue_text']}; }}
.pc-lchip-miss, .pc-lchip-push {{ background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; }}
.pc-lrow-chip {{ grid-template-columns:minmax(150px,210px) 160px minmax(120px,1fr) 160px minmax(104px,auto); }}
.pc-lmincol {{ grid-template-columns:minmax(150px,210px) 160px minmax(120px,1fr) 160px minmax(96px,auto); }}
.pc-lmin {{ justify-self:end; white-space:nowrap; font-weight:700; font-size:16px; color:{P['text_soft']}; font-variant-numeric:tabular-nums; }}
.pc-lhead {{ text-align:right; padding:0 12px 4px; font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:{P['label']}; }}
.pc-lhgrid {{ display:grid; gap:14px; align-items:end; text-align:left; }}
.pc-lhq, .pc-lhm {{ justify-self:end; white-space:nowrap; }}
.pc-lqcol {{ grid-template-columns:minmax(150px,210px) 72px 160px minmax(120px,1fr) 160px; }}
.pc-lqcol.pc-lmincol {{ grid-template-columns:minmax(150px,210px) 72px 160px minmax(120px,1fr) 160px minmax(96px,auto); }}
.pc-lq {{ justify-self:end; white-space:nowrap; font-weight:600; font-size:16px; color:{P['text_soft']}; font-variant-numeric:tabular-nums; }}
.pc-bar-odds {{ display:flex; justify-content:space-between; max-width:1040px; margin:6px auto 0; font-size:14px; font-weight:600; color:{P['text_soft']}; font-variant-numeric:tabular-nums; }}
.pc-minnote {{ font-size:13px; color:{P['label']}; padding:6px 10px 2px; }}
.pc-winner {{ max-width:1040px; margin:10px auto 0; text-align:center; font-size:13px; font-weight:600; }}
.pc-winner span {{ display:inline-block; padding:3px 12px; border-radius:999px; }}
.pc-winner-ok span {{ background:{P['win_ok_bg']}; border:1px solid {P['win_ok_border']}; color:{P['win_ok_text']}; }}
.pc-winner-low span {{ background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; }}
.pc-lbar {{ display:flex; height:14px; border-radius:7px; overflow:hidden; background:{P['bar_other']}; min-width:0; }}
.pc-lseg {{ display:block; height:100%; }}
.pc-lnote {{ font-size:13px; color:{P['label']}; padding:8px 10px 0; }}
.pc-details {{ margin-top:22px; border-top:1px solid #2c3350; padding-top:14px; }}
.pc-details summary {{ cursor:pointer; font-size:13px; letter-spacing:.14em; color:{P['label']}; }}
.pc-info-body {{ margin-top:12px; }}
.pc-info {{ font-size:14px; color:{P['text_soft']}; padding:3px 0; font-variant-numeric:tabular-nums; }}
.pc-card {{ position:relative; }}
.pc-var {{ display:contents; }}
.pc-var-t2 {{ display:none; }}
.pc-card:has(.pc-sw[open]) .pc-var-std, [class*="st-key-sc_game_"]:has(.pc-sw[open]) .pc-var-std {{ display:none; }}
.pc-card:has(.pc-sw[open]) .pc-var-t2, [class*="st-key-sc_game_"]:has(.pc-sw[open]) .pc-var-t2 {{ display:contents; }}
.pc-sw {{ position:absolute; top:12px; right:16px; z-index:2; }}
.pc-sw summary {{ list-style:none; cursor:pointer; display:inline-flex; border:1px solid #2c3350; border-radius:999px; overflow:hidden; font-size:12px; font-weight:600; user-select:none; }}
.pc-sw summary::-webkit-details-marker {{ display:none; }}
.pc-sw-opt {{ padding:4px 12px; color:{P['label']}; }}
.pc-sw-std {{ background:{P['pill_bg']}; color:{P['pill_text']}; }}
.pc-sw[open] .pc-sw-std {{ background:transparent; color:{P['label']}; }}
.pc-sw[open] .pc-sw-t2 {{ background:{P['pill_bg']}; color:{P['pill_text']}; }}
@media (max-width:760px) {{ .pc-head {{ grid-template-columns:1fr; }} .pc-model {{ grid-template-columns:1fr; gap:24px; }} .pc-card {{ padding:24px 18px 18px; }} }}
@media (max-width:1200px) {{ .pc-lrow {{ grid-template-columns:auto 1fr auto; grid-template-areas:"line line line" "pl bar pr"; row-gap:6px; padding:8px 10px; }} .pc-lline {{ grid-area:line; }} .pc-lpct-l {{ grid-area:pl; }} .pc-lbar {{ grid-area:bar; }} .pc-lpct-r {{ grid-area:pr; }} .pc-lrow-chip {{ grid-template-columns:auto 1fr auto; grid-template-areas:"line line chip" "pl bar pr"; }} .pc-lchip {{ grid-area:chip; }} .pc-lmincol {{ grid-template-columns:auto 1fr auto; grid-template-areas:"line line min" "pl bar pr"; }} .pc-lmin {{ grid-area:min; }} .pc-lqcol {{ grid-template-columns:auto 1fr auto; grid-template-areas:"line line quote" "pl bar pr"; }} .pc-lqcol.pc-lmincol {{ grid-template-areas:"line quote min" "pl bar pr"; }} .pc-lq {{ grid-area:quote; }} .pc-lhgrid {{ display:flex; justify-content:flex-end; gap:24px; }} .pc-lhgrid span:empty {{ display:none; }} .pc-lpill {{ padding:3px 8px; font-size:15px; }} }}
</style>
"""


CARD_CSS = _css()
