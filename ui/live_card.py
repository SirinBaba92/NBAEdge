"""
Karten und Tagesuebersicht fuer den Tab "Spieltag" (nur Darstellung, keine Rechnung, kein Streamlit).

build_game_vm(...)          -> Anzeigewerte einer Spielkarte (Stand, Zeit, Siegbalken, Maerkte, eigene Wetten)
render_game_card_html(vm)   -> HTML der Karte (nutzt Kartenkopf, Logos, Balken und Farben aus ui/score_cards.py)
render_overview_html(...)   -> Tagesuebersicht: eine Zeile je Spiel nach Anpfiff
render_summary_html(...)    -> Zahlen der Wetten (offen, gewonnen, verloren, Einsatz, Gewinn/Verlust nur abgerechnete)
render_status_html(state)   -> Statuszeile des Live-Feeds (Quelle, Alter der Daten, Fehler, Hinweise)
LIVE_CSS                    -> Stylesheet (zusaetzlich zu ui.score_cards.CARD_CSS)
Gestaltungsregeln: DESIGN_REGELN.md (Abschnitt "Tab Spieltag").
"""
from __future__ import annotations

import math
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from data.day_bets_store import MARKET_NAMES, MARKETS, nearest_half_line
from ui.score_cards import MINUS, PALETTE, fmt_num, render_card_head, spread_label, team_info

BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
NO_ANCHOR_SHORT = "keine Chancen"

# Statusfarben der Wetten (Text immer dabei, nie nur Farbe). Gruen/Orange/Rot gelten NUR fuer Wett-Status und Gewinn/Verlust, nie fuer Modell-Abweichungen.
STATUS = {
    "gruen": {"bg": "#12301f", "text": "#86efac", "border": "#2f7a4a", "bar": "#22c55e"},
    "gelb": {"bg": PALETTE["chip_yellow_bg"], "text": PALETTE["chip_yellow_text"], "border": PALETTE["chip_yellow_border"], "bar": "#eab308"},
    "orange": {"bg": "#3b2410", "text": "#fdba74", "border": "#9a5a1c", "bar": "#d97706"},
    "rot": {"bg": "#3a1414", "text": "#fca5a5", "border": "#8a2c2c", "bar": "#ef4444"},
    "grau": {"bg": PALETTE["chip_gray_bg"], "text": PALETTE["chip_gray_text"], "border": PALETTE["chip_gray_border"], "bar": PALETTE["bar_other"]},
    "blau": {"bg": PALETTE["chip_blue_bg"], "text": PALETTE["chip_blue_text"], "border": PALETTE["chip_blue_border"], "bar": "#3d5a85"},
}
COLOR_CLASS = {k: f"lv-st-{k}" for k in STATUS}
CARD_MARKETS = ("spread", "total", "team_total_home", "team_total_away")


# ----------------------------------------------------------------------------------------------- Formatierung
def pct(p) -> int:
    """Ganze Prozent 0 bis 100 (Live kann 0 und 100 erreichen; kaufmaennisch gerundet)."""
    return max(0, min(100, int(math.floor(float(p) * 100 + 0.5))))


def fmt_start(start_utc: str | None, now: float | None = None) -> str:
    """'Fr 23.10. 01:00 Uhr' (Berliner Zeit); unbekannt: ''."""
    try:
        dt = datetime.fromisoformat(str(start_utc).replace("Z", "+00:00")).astimezone(BERLIN)
    except ValueError:
        return ""
    return f"{WEEKDAYS[dt.weekday()]} {dt.strftime('%d.%m. %H:%M')} Uhr"


def fmt_hhmm(start_utc: str | None) -> str:
    try:
        return datetime.fromisoformat(str(start_utc).replace("Z", "+00:00")).astimezone(BERLIN).strftime("%H:%M")
    except ValueError:
        return ""


def fmt_day(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
        return f"{WEEKDAYS[d.weekday()]} {d.strftime('%d.%m.%Y')}"
    except ValueError:
        return day


def fmt_money(value) -> str:
    return "—" if value is None else fmt_num(float(value), 2)


def flat(html: str) -> str:
    """HTML ohne Einrueckung und Leerzeilen (wie app.flat_html)."""
    return "".join(line.strip() for line in html.splitlines())


def chip(text: str, cls: str) -> str:
    return f'<span class="pc-chip {cls}">{escape(text)}</span>'


def status_chip(game) -> str:
    cls = {"PRE": "pc-chip-gray", "LIVE": "pc-chip-yellow", "PAUSE": "pc-chip-yellow", "FINAL": "pc-chip-gray"}[game.status]
    return chip(game.status_text, cls)


# ----------------------------------------------------------------------------------------------- Reihenfolge
def card_order(games) -> list:
    """Laufende (LIVE/PAUSE) zuerst, dann noch nicht begonnene nach Anpfiff, dann beendete (jeweils nach Anpfiff)."""
    rank = {"LIVE": 0, "PAUSE": 0, "PRE": 1, "FINAL": 2}
    return sorted(games, key=lambda g: (rank[g.status], g.start_utc or "", g.game_id))


def overview_order(games) -> list:
    return sorted(games, key=lambda g: (g.start_utc or "", g.game_id))


# ----------------------------------------------------------------------------------------------- Hauptlinien
def model_main_lines(anchor) -> dict:
    """Notloesung ohne Marktlinie: .5-Linien aus den Vorab-Werten des Modells (nur wenn weder Schnappschuss noch Eingabe eine Linie kennen)."""
    return {"spread_home": nearest_half_line(-float(anchor.exp_spread)), "total": nearest_half_line(anchor.exp_total),
            "team_total_home": nearest_half_line(anchor.home_score), "team_total_away": nearest_half_line(anchor.away_score)}


def merge_main_lines(market_lines: dict | None, anchor) -> tuple[dict, dict]:
    """(Hauptlinien, Herkunft je Markt): Marktlinie (Schnappschuss/Eingabe), fehlende aus dem Modell ('Modell-Linie')."""
    out, src = {}, {}
    model = model_main_lines(anchor) if anchor is not None else {}
    for key in ("spread_home", "total", "team_total_home", "team_total_away"):
        v = (market_lines or {}).get(key)
        if v is not None:
            out[key], src[key] = v, "Hauptlinie"
        elif model.get(key) is not None:
            out[key], src[key] = model[key], "Modell-Linie"
        else:
            out[key], src[key] = None, None
    return out, src


# ----------------------------------------------------------------------------------------------- Anzeigewerte
def bet_label(market: str, bet: dict, game) -> str:
    side, line = bet.get("side"), bet.get("line")
    if market == "winner":
        return f"{game.home_nick if side == 'home' else game.away_nick} gewinnt"
    if market == "spread":
        return f"{game.home_nick if side == 'home' else game.away_nick} {fmt_num(float(line), signed=True)}"
    return f"{'Over' if side == 'over' else 'Under'} {fmt_num(float(line))}"


def market_title(market: str, game) -> str:
    if market == "team_total_home":
        return f"Team Total · {game.home_nick}"
    if market == "team_total_away":
        return f"Team Total · {game.away_nick}"
    return MARKET_NAMES[market]


def _bet_row(market: str, bet: dict, live, game) -> dict:
    row = {"kind": "bet", "market": market, "title": market_title(market, game), "label": bet_label(market, bet, game), "tag": "Wette", "bet": bet}
    detail = [f"Quote {fmt_money(bet.get('odds'))}", f"Einsatz {fmt_money(bet.get('stake'))}"]
    if live is None:
        row.update(status=None, left="kein Status", right="", pl=0, pr=0, color="grau", detail=" · ".join(detail))
        return row
    p = 0 if live.probability is None else pct(live.probability)
    if live.profit is not None:
        detail.append(("Gewinn " if live.profit >= 0 else "Verlust ") + fmt_num(abs(live.profit), 2))
    row.update(status=live.label, state=live.state, color=live.color, left=f"{p} % Chance", right=f"{100 - p} % dagegen", pl=p, pr=100 - p, detail=" · ".join(detail), decided=live.decided)
    return row


def _line_row(market: str, game, numbers, lines: dict, src: dict) -> dict | None:
    if numbers is None or not numbers.has_anchor:
        return None
    if market == "spread":
        line = lines.get("spread_home")
        if line is None:
            return None
        p_home = pct(numbers.p_spread("home", line))
        label = spread_label(game.home_nick, game.away_nick, -float(line))
        return {"kind": "line", "market": market, "title": "Spread", "label": label, "tag": src.get("spread_home"),
                "left": f"{game.away_nick} {100 - p_home} %", "right": f"{p_home} % {game.home_nick}", "pl": 100 - p_home, "pr": p_home}
    line = lines.get(market)
    if line is None:
        return None
    p = pct(numbers.p_over_total(line) if market == "total" else numbers.p_over_team("home" if market == "team_total_home" else "away", line))
    return {"kind": "line", "market": market, "title": market_title(market, game), "label": fmt_num(float(line)), "tag": src.get(market),
            "left": f"Over {p} %", "right": f"{100 - p} % Under", "pl": p, "pr": 100 - p}


def build_game_vm(game, numbers, lives: dict | None = None, bets: dict | None = None, market_lines: dict | None = None) -> dict:
    """Anzeigewerte einer Karte. numbers: LiveNumbers (oder None), lives: {markt: BetLive}, bets: {markt: Wette}, market_lines: {'spread_home', 'total', ...} aus Schnappschuss/Eingabe."""
    lives, bets = lives or {}, bets or {}
    anchor = None if numbers is None else numbers.anchor
    lines, src = merge_main_lines(market_lines, anchor)
    has = numbers is not None and numbers.has_anchor
    p_home = numbers.p_winner("home") if has else None
    vm = {"game": game, "has_numbers": has, "note": None if numbers is None else numbers.note, "bets_count": len(bets), "rows": [], "p_home": p_home,
          "p_away": None if p_home is None else 1.0 - p_home, "bar_caption": None, "final_text": None}
    if has:
        vm["bar_caption"] = {"PRE": "Siegchance (Vorab)", "FINAL": "Endstand"}.get(game.status, "Siegchance (live)")
    if game.status == "FINAL":
        vm["final_text"] = "Endstand" + (" (nach Verlängerung)" if game.clock.ot_number else "")
    rows = []
    if "winner" in bets:
        rows.append(_bet_row("winner", bets["winner"], lives.get("winner"), game))
    for m in CARD_MARKETS:
        if m in bets:
            rows.append(_bet_row(m, bets[m], lives.get(m), game))
        else:
            r = _line_row(m, game, numbers, lines, src)
            if r:
                rows.append(r)
    vm["rows"] = rows
    return vm


# ----------------------------------------------------------------------------------------------- HTML: Karte
def _row_html(r: dict) -> str:
    tag = f'<span class="pc-ltag">{escape(r["tag"])}</span>' if r.get("tag") else ""
    if r["kind"] == "bet":
        c = r["color"]
        st = COLOR_CLASS[c]
        chip_html = f'<span class="lv-st {st}">{escape(r["status"])}</span>' if r.get("status") else ""
        bar = (f'<span class="pc-lbar"><span class="pc-lseg" style="width:{r["pl"]}%;background:{STATUS[c]["bar"]}"></span>'
               f'<span class="pc-lseg pc-seg-other" style="width:{r["pr"]}%"></span></span>') if r.get("status") else '<span class="pc-lbar"></span>'
        left = f'<span class="pc-lpct pc-lpct-l"><span class="pc-lpill lv-pill {st}">{escape(r["left"])}</span></span>'
        right = f'<span class="pc-lpct pc-lpct-r"><span class="pc-lpill">{escape(r["right"])}</span></span>'
        return (f'<div class="pc-lrow pc-lrow-chip lv-bet lv-bet-{escape(str(r.get("state") or "none"))}"><span class="pc-lline">{escape(r["title"])}: {escape(r["label"])}{tag}</span>'
                f'{left}{bar}{right}{chip_html}<span class="lv-detail">{escape(r["detail"])}</span></div>')
    fav_l = r["pl"] > r["pr"]
    fav_r = r["pr"] > r["pl"]
    lcls = "pc-lseg pc-seg-fav" if fav_l else "pc-lseg pc-seg-other"
    rcls = "pc-lseg pc-seg-fav" if fav_r else "pc-lseg pc-seg-other"
    return (f'<div class="pc-lrow"><span class="pc-lline">{escape(r["title"])}: {escape(r["label"])}{tag}</span>'
            f'<span class="pc-lpct pc-lpct-l"><span class="pc-lpill{" pc-lpct-pred" if fav_l else ""}">{escape(r["left"])}</span></span>'
            f'<span class="pc-lbar" role="img" aria-label="{escape(r["left"])} gegen {escape(r["right"])}"><span class="{lcls}" style="width:{r["pl"]}%"></span><span class="{rcls}" style="width:{r["pr"]}%"></span></span>'
            f'<span class="pc-lpct pc-lpct-r"><span class="pc-lpill{" pc-lpct-pred" if fav_r else ""}">{escape(r["right"])}</span></span></div>')


def render_game_card_html(vm: dict, logo_dir=None) -> str:
    g = vm["game"]
    has, p_home = vm["has_numbers"], vm["p_home"]
    fav = None if not has else ("home" if p_home > 0.5 else "away" if p_home < 0.5 else None)
    cls = lambda side: "pc-score pc-fav" if fav == side else "pc-score pc-dog"
    score = ""
    if g.status == "PRE":
        mid = f'<div class="lv-mid"><div class="lv-kick">{escape(fmt_hhmm(g.start_utc))}</div><div class="lv-clock">Anpfiff (Berlin)</div></div>'
    else:
        clock = escape(g.clock_label)
        if g.status == "FINAL" and vm.get("final_text"):
            clock = f"{clock}<br><span class=\"lv-final\">{escape(vm['final_text'])}</span>"
        mid = (f'<div class="lv-mid"><div class="lv-scoreline"><span class="{cls("away")}">{g.away_score}</span><span class="pc-at">@</span><span class="{cls("home")}">{g.home_score}</span></div>'
               f'<div class="lv-clock">{clock}</div></div>')
    top_chips = status_chip(g)
    if vm["bets_count"]:
        top_chips += chip(f"🎯 {vm['bets_count']} Wette{'n' if vm['bets_count'] != 1 else ''}", "pc-chip-blue")
    if g.source != "NBA.com":
        top_chips += chip(f"Stand von {g.source}", "pc-chip-gray")
    parts = [
        f'<div class="pc-card lv-card lv-card-{g.status.lower()}" data-game="{escape(g.game_id)}">',
        f'<div class="lv-toprow"><span class="lv-start">{escape(fmt_start(g.start_utc))}</span><span class="lv-chips">{top_chips}</span></div>',
        render_card_head(g.away, g.home, mid, logo_dir),
    ]
    if has:
        a, h = team_info(g.away), team_info(g.home)
        pa, ph = pct(vm["p_away"]), pct(p_home)
        away_seg = "pc-seg pc-seg-fav" if fav == "away" else "pc-seg pc-seg-other"
        home_seg = "pc-seg pc-seg-fav" if fav == "home" else "pc-seg pc-seg-other"
        parts += [f'<div class="pc-bar-labels"><span>{escape(a["nick"])} {pa} %</span><span>{ph} % {escape(h["nick"])}</span></div>',
                  f'<div class="pc-bar" role="img" aria-label="Siegwahrscheinlichkeit {escape(a["nick"])} {pa} %, {escape(h["nick"])} {ph} %">'
                  f'<div class="{away_seg}" style="width:{vm["p_away"] * 100:.1f}%"></div><div class="{home_seg}" style="width:{p_home * 100:.1f}%"></div></div>',
                  f'<div class="lv-caption">{escape(vm["bar_caption"])}</div>']
    elif vm.get("note"):
        parts.append(f'<div class="lv-note">{escape(vm["note"])}</div>')
    if vm["rows"]:
        parts += ['<div class="pc-model-wrap lv-markets"><div class="pc-label">MÄRKTE</div>', "".join(_row_html(r) for r in vm["rows"]), "</div>"]
    if g.box_error:
        parts.append(f'<div class="lv-note">Boxscore: {escape(g.box_error)}</div>')
    parts.append("</div>")
    return "\n".join(p for p in parts if p)


# ----------------------------------------------------------------------------------------------- HTML: Statuszeile, Uebersicht, Zahlen
def render_status_html(state) -> str:
    """Statuszeile des Feeds: Quelle, Alter der Daten, Fehlertext. Bei Fehler deutlich sichtbar (gelb bei ESPN-Fallback, rot bei veralteten Daten), letzte gute Werte bleiben angezeigt."""
    if state.error is None:
        kind, icon = "ok", "●"
    elif not state.stale:
        kind, icon = "warn", "⚠"
    else:
        kind, icon = "err", "⚠"
    out = [f'<div class="lv-status-line lv-status-{kind}" role="status"><span class="lv-status-dot">{icon}</span><span>{escape(state.status_line)}</span></div>']
    if state.notice:
        out.append(f'<div class="lv-hint">{escape(state.notice)}</div>')
    if state.fallback_note and state.error:
        out.append(f'<div class="lv-hint">{escape(state.fallback_note)}</div>')
    if state.other_day_games:
        n = len(state.other_day_games)
        out.append(f'<div class="lv-hint">{n} Spiel{"e" if n != 1 else ""} eines anderen Spieltags {"stehen" if n != 1 else "steht"} noch auf dem Scoreboard und {"werden" if n != 1 else "wird"} hier nicht angezeigt.</div>')
    return "".join(out)


def render_overview_html(games, day: str, bet_counts: dict | None = None) -> str:
    bet_counts = bet_counts or {}
    head = f'<div class="lv-ohead"><span class="pc-label">TAGESÜBERSICHT</span><span class="lv-oday">Spieltag {escape(fmt_day(day))} (US-Datum)</span></div>'
    if not games:
        return f'<div class="lv-overview">{head}<div class="lv-note">Für diesen Spieltag sind noch keine Spiele gelistet.</div></div>'
    rows = []
    for g in overview_order(games):
        a, h = team_info(g.away), team_info(g.home)
        score = "" if g.status == "PRE" else f'{g.away_score} : {g.home_score}'
        when = fmt_hhmm(g.start_utc) if g.status == "PRE" else g.clock_label
        n = bet_counts.get(g.game_id, 0)
        marker = chip(f"🎯 {n}", "pc-chip-blue") if n else ""
        rows.append(f'<div class="lv-orow lv-orow-{g.status.lower()}"><span class="lv-otime">{escape(fmt_hhmm(g.start_utc))}</span>'
                    f'<span class="lv-oteams">{escape(a["nick"])} @ {escape(h["nick"])}</span><span class="lv-oscore">{score}</span>'
                    f'<span class="lv-oclock">{escape(when)}</span><span class="lv-ochips">{status_chip(g)}{marker}</span></div>')
    return f'<div class="lv-overview">{head}{"".join(rows)}</div>'


def summary_from_rows(bet_rows: list[dict]) -> dict:
    """Zahlen fuer die Uebersicht aus bets_live(): offene/gewonnene/verlorene Wetten (nur mit Status), Einsatz aller gespeicherten Wetten, Gewinn/Verlust nur abgerechneter Wetten mit Quote und Einsatz."""
    from data.day_bets_store import summarize
    lives = [bl for r in bet_rows for bl in r["lives"].values()]
    s = summarize(lives)
    total = sum(len(r["bets"]) for r in bet_rows)
    stake_all = round(sum((b.get("stake") or 0.0) for r in bet_rows for b in r["bets"].values()), 2)
    return {"wetten": total, "offen": s["offen"], "gewonnen": s["gewonnen"], "verloren": s["verloren"], "einsatz": stake_all, "gewinn_verlust": s["gewinn_verlust"],
            "ohne_status": total - s["wetten"], "ohne_quote_oder_einsatz": s["ohne_quote_oder_einsatz"]}


def render_summary_html(summary: dict) -> str:
    if not summary or not summary.get("wetten"):
        return '<div class="lv-sum lv-sum-empty">Für diesen Spieltag sind noch keine Wetten gespeichert.</div>'
    gv = summary["gewinn_verlust"]
    gv_cls = "lv-pos" if gv > 0 else "lv-neg" if gv < 0 else ""
    tiles = [("Wetten", str(summary["wetten"]), ""), ("Offen", str(summary["offen"]), ""), ("Gewonnen", str(summary["gewonnen"]), ""), ("Verloren", str(summary["verloren"]), ""),
             ("Einsatz", fmt_num(summary["einsatz"], 2), ""), ("Gewinn / Verlust (abgerechnet)", fmt_num(gv, 2, signed=True), gv_cls)]
    html = "".join(f'<div class="lv-tile"><div class="pc-label">{escape(k.upper())}</div><div class="lv-val {c}">{escape(v)}</div></div>' for k, v, c in tiles)
    extra = []
    if summary.get("ohne_status"):
        extra.append(f'{summary["ohne_status"]} Wette(n) ohne Status (kein Schnappschuss oder Spiel nicht im Scoreboard)')
    if summary.get("ohne_quote_oder_einsatz"):
        extra.append(f'{summary["ohne_quote_oder_einsatz"]} abgerechnete Wette(n) ohne Quote oder Einsatz zählen nicht im Gewinn')
    note = f'<div class="lv-hint">{escape("; ".join(extra))}</div>' if extra else ""
    return f'<div class="lv-sum"><div class="lv-tiles">{html}</div>{note}</div>'


# ----------------------------------------------------------------------------------------------- CSS
def _css() -> str:
    P = PALETTE
    st_css = "\n".join(f".lv-st-{k} {{ background:{v['bg']}; border:1px solid {v['border']}; color:{v['text']}; }}" for k, v in STATUS.items())
    return f"""
<style>
{st_css}
.lv-card {{ margin-bottom:22px; }}
.lv-toprow {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; max-width:1040px; margin:0 auto 18px; }}
.lv-start {{ font-size:13px; letter-spacing:.1em; text-transform:uppercase; color:{P['label']}; }}
.lv-chips {{ display:flex; gap:8px; flex-wrap:wrap; }}
.lv-chips .pc-chip {{ margin-top:0; }}
.pc-chip-blue {{ background:{P['chip_blue_bg']}; border:1px solid {P['chip_blue_border']}; color:{P['chip_blue_text']}; }}
.lv-mid {{ display:flex; flex-direction:column; align-items:center; gap:8px; }}
.lv-scoreline {{ display:flex; align-items:center; justify-content:center; gap:clamp(14px,2vw,28px); }}
.lv-kick {{ font-size:clamp(34px,3.4vw,52px); font-weight:800; color:{P['text']}; font-variant-numeric:tabular-nums; line-height:1; }}
.lv-clock {{ font-size:clamp(15px,1.3vw,19px); font-weight:600; color:{P['text_soft']}; text-align:center; letter-spacing:.04em; }}
.lv-final {{ font-size:13px; font-weight:500; color:{P['label']}; letter-spacing:.06em; }}
.lv-caption {{ max-width:1040px; margin:8px auto 0; text-align:center; font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:{P['label']}; }}
.lv-note {{ max-width:1040px; margin:18px auto 0; padding:10px 14px; border-radius:10px; background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; font-size:14px; text-align:center; }}
.lv-markets {{ margin-top:22px; padding-top:18px; }}
.lv-markets .pc-lrow {{ grid-template-columns:minmax(220px,300px) 150px minmax(120px,1fr) 150px; }}
.lv-markets .pc-lrow-chip {{ grid-template-columns:minmax(220px,300px) 150px minmax(120px,1fr) 150px minmax(120px,auto); }}
.lv-bet {{ background:#1d2338; box-shadow:inset 3px 0 0 {STATUS['blau']['border']}; row-gap:6px; }}
.lv-detail {{ grid-column:1 / -1; font-size:13px; color:{P['label']}; padding:0 2px 2px; }}
.lv-st {{ justify-self:end; white-space:nowrap; padding:3px 10px; border-radius:999px; font-size:13px; font-weight:700; }}
.lv-pill {{ font-weight:700; }}
.lv-status-line {{ display:flex; align-items:center; gap:10px; margin:6px 0 4px; padding:10px 14px; border-radius:10px; font-size:14px; font-weight:600; }}
.lv-status-ok {{ background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; }}
.lv-status-warn {{ background:{P['chip_yellow_bg']}; border:1px solid {P['chip_yellow_border']}; color:{P['chip_yellow_text']}; }}
.lv-status-err {{ background:{STATUS['rot']['bg']}; border:1px solid {STATUS['rot']['border']}; color:{STATUS['rot']['text']}; }}
.lv-status-dot {{ font-size:15px; }}
.lv-hint {{ font-size:13px; color:{P['label']}; margin:4px 2px 0; }}
.lv-overview {{ box-sizing:border-box; width:100%; max-width:1400px; background:{P['card_bg']}; border:1px solid #2c3350; border-radius:18px; padding:18px clamp(16px,2.4vw,36px) 12px; margin:14px 0 14px; color:{P['text']}; font-family:'DM Sans',sans-serif; }}
.lv-ohead {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:10px; }}
.lv-oday {{ font-size:13px; color:{P['label']}; }}
.lv-orow {{ display:grid; grid-template-columns:70px minmax(160px,1.4fr) 90px minmax(120px,1fr) auto; align-items:center; gap:12px; padding:8px 4px; border-top:1px solid #232940; font-size:16px; font-variant-numeric:tabular-nums; }}
.lv-otime {{ color:{P['label']}; }}
.lv-oteams {{ font-weight:600; color:{P['text']}; }}
.lv-oscore {{ font-weight:800; color:{P['text']}; text-align:center; }}
.lv-oclock {{ color:{P['text_soft']}; }}
.lv-ochips {{ display:flex; gap:8px; justify-content:flex-end; }}
.lv-ochips .pc-chip {{ margin-top:0; padding:3px 12px; }}
.lv-sum {{ box-sizing:border-box; width:100%; max-width:1400px; background:{P['card_bg']}; border:1px solid #2c3350; border-radius:18px; padding:16px clamp(16px,2.4vw,36px); margin:0 0 22px; color:{P['text']}; font-family:'DM Sans',sans-serif; }}
.lv-sum-empty {{ font-size:14px; color:{P['label']}; }}
.lv-tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:16px; }}
.lv-val {{ font-size:clamp(22px,2vw,30px); font-weight:800; font-variant-numeric:tabular-nums; }}
.lv-pos {{ color:{STATUS['gruen']['text']}; }}
.lv-neg {{ color:{STATUS['rot']['text']}; }}
@media (max-width:1200px) {{ .lv-markets .pc-lrow, .lv-markets .pc-lrow-chip {{ grid-template-columns:auto 1fr auto; }} .lv-orow {{ grid-template-columns:56px 1fr auto; }} .lv-oscore, .lv-oclock {{ grid-column:auto; }} }}
</style>
"""


LIVE_CSS = _css()
