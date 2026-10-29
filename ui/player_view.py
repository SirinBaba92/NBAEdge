"""
Darstellung des Tabs "Spieler" (nur Anzeige, kein Streamlit, keine Rechnung ausser Rundung/Sortierung).

build_table_model(snapshot_entry, mode, sort) -> Anzeigewerte der Spielertabelle eines Spiels aus dem Prognose-Snapshot (engine/player_snapshots.py)
render_table_html(model)                      -> HTML der Tabelle (eine Zeile je Meilenstein, Spielerspalten ueber alle Zeilen des Spielers)
PLAYER_CSS                                    -> Stylesheet (zusaetzlich zu ui.score_cards.CARD_CSS)
Alle Prognosen und Chancen sind UNGEPRUEFT und so gekennzeichnet. Gestaltungsregeln: DESIGN_REGELN.md (Abschnitt "Tab Spieler"). Differenzen Modell gegen Buchmacher sind
neutral (grau) und gelb ab der Schwelle MARK_PP; nie gruen oder rot (Regel 3).
"""
from __future__ import annotations

import math
from html import escape

from config import settings
from engine import safety_levels as sl
from ui.score_cards import MINUS, PALETTE, fmt_num

MARK_PP = 5.0                       # Schwelle fuer die Markierung (Prozentpunkte, ungerundete Differenz)
UNVERIFIED = "UNGEPRÜFT"
UNVERIFIED_TEXT = "UNGEPRÜFT: Die Prognose ist noch nicht gegen Ergebnisse geprüft. Sie gilt für den Fall, dass der Spieler spielt, und kennt keine Ausfälle, Gegner und kein Tempo."
MODES = {"team": "Teamabgleich", "raw": "roh"}
SORTS = {"team": "Team, dann Minuten", "minutes": "Minuten", "diff": "größte Differenz"}


def pct_int(p) -> int:
    return max(0, min(100, int(math.floor(float(p) * 100 + 0.5))))


def mark_for(diff_pp: float | None) -> str:
    """'◀' bei Modell mindestens MARK_PP Prozentpunkte ueber dem Buchmacher, '▼' darunter, sonst ''."""
    if diff_pp is None:
        return ""
    return "◀" if diff_pp >= MARK_PP else "▼" if diff_pp <= -MARK_PP else ""


def quality_text(player: dict) -> str:
    """Tooltip-Text: Datenqualitaet und Hinweise eines Spielers (leer, wenn es nichts zu sagen gibt)."""
    parts = []
    if player.get("quality"):
        parts.append("Datenqualität: " + ", ".join(player["quality"]))
    parts += [w for w in (player.get("warnings") or []) if w]
    if not player.get("ok"):
        parts.insert(0, f"Keine Prognose: {player.get('reason') or 'kein Verlauf'}")
    return " | ".join(parts)


def build_table_model(entry: dict, mode: str = "team", sort: str = "team", bets: dict | None = None, live: dict | None = None, absences: dict | None = None, window: float | None = None) -> dict:
    """Anzeigewerte aus einem Snapshot-Eintrag (ein Spiel). mode: 'team' (Teamabgleich) oder 'raw'; sort: 'team' | 'minutes' | 'diff'.
    Rueckgabe {'players': [{person_id, name, team, abbr, ok, minutes, points, tooltip, rows: [{n, odds, bookmaker, buch_pct, model_pct, diff, mark}], max_diff}], 'mode', 'sort'}.
    Die Differenz wird aus ungerundeten Werten gerechnet (Modell minus Buchmacher-Chance inkl. Marge, in Prozentpunkten). bets: aktive Spieler-Wetten {person_id: Wette} (Marker am Namen). window: Standardansicht verkleinert die Tabelle: je Spieler nur die Meilensteine mit |N - erwartete Punkte| <= window plus die Meilensteine eigener Wetten (None = alle; Spieler ohne Prognose zeigen alle). live: {person_id: {'points', 'minutes', 'fouls', 'status', 'chances': {N: Anteil}, 'notes': [...], 'out': bool}} fuer laufende Spiele (Spalten 'Jetzt' und 'Live')."""
    team_mode = mode != "raw"
    players = []
    for p in entry.get("players", []):
        pj = (p.get("p_ge_adjusted") if team_mode else p.get("p_ge_raw")) or {}
        pj_raw = p.get("p_ge_raw") or {}
        n_games = sl.games_total(p.get("games_used"))                                           # Spiele im Verlauf (nur Anzeige: Hinweis bei wenigen Spielen)
        starter = bool(p.get("ok")) and sl.is_player_starter((p.get("minutes") or {}).get("base"))      # Starter wie in analysis/backtest_thresholds.py (Basis-Minuten > 28)
        rows = []
        for q in sorted(p.get("quotes") or [], key=lambda q: q["milestone"]):
            m = pj.get(str(q["milestone"])) if p.get("ok") else None
            diff = None if m is None else (m - q["bookmaker_probability"]) * 100
            raw_p = pj_raw.get(str(q["milestone"])) if p.get("ok") else None                    # ungerundete Roh-Chance (Starter-Zeichen und Mindestquote der Karten)
            rows.append({"safe_odds": sl.player_safe_odds(starter, n_games, raw_p), "n": q["milestone"], "odds": q["odds"], "bookmaker": q.get("bookmaker"), "buch_pct": pct_int(q["bookmaker_probability"]),
                         "model_pct": None if m is None else pct_int(m), "diff": diff, "mark": mark_for(diff)})
        if not p.get("ok"):
            minutes = points = None
        else:
            minutes = p["minutes_adjusted"] if team_mode else p["minutes"]["mean"]
            points = p["expected_points_adjusted"] if team_mode else p["expected_points_raw"]
        hidden = 0
        if window is not None and p.get("ok"):
            center = p["expected_points_adjusted"] if team_mode else p["expected_points_raw"]
            bet_n = {int(b["milestone"]) for b in [(bets or {}).get(int(p["person_id"]))] if b}
            keep = [r for r in rows if abs(r["n"] - center) <= window or r["n"] in bet_n]
            hidden, rows = len(rows) - len(keep), keep
        diffs = [abs(r["diff"]) for r in rows if r["diff"] is not None]
        players.append({"person_id": p["person_id"], "name": p["name"], "team": p.get("team"), "abbr": p.get("team_abbreviation") or "", "ok": bool(p.get("ok")),
                        "minutes": minutes, "points": points, "tooltip": quality_text(p), "rows": rows, "max_diff": max(diffs) if diffs else -1.0, "games": n_games, "few_games": sl.few_games_text(n_games),
                        "bet": (bets or {}).get(int(p["person_id"])), "live": (live or {}).get(int(p["person_id"])), "hidden_rows": hidden})
        mark_abs = ("fehlt" if int(p["person_id"]) in (absences or {}).get("out", {}) else "fraglich" if int(p["person_id"]) in (absences or {}).get("doubtful", {}) else "")
        if mark_abs:
            players[-1]["tooltip"] = (players[-1]["tooltip"] + " | " if players[-1]["tooltip"] else "") + f"Ausfall-Auswahl: {mark_abs} (siehe „Ausfälle“; die Tabelle zeigt weiter den ursprünglichen Snapshot)"
    if sort == "minutes":
        players.sort(key=lambda p: (-(p["minutes"] if p["minutes"] is not None else -1), p["name"]))
    elif sort == "diff":
        players.sort(key=lambda p: (-p["max_diff"], p["name"]))
    else:
        players.sort(key=lambda p: (p["team"] or "", -(p["minutes"] if p["minutes"] is not None else -1), p["name"]))
    return {"players": players, "mode": mode, "sort": sort, "live": bool(live), "window": window, "hidden_rows": sum(p["hidden_rows"] for p in players)}


def attach_final(model: dict, final: dict | None) -> dict:
    """Erzielte Punkte und Spielminuten eines BEENDETEN Spiels in ein fertiges Tabellenmodell eintragen (nur Anzeige in den Karten): p['final'] = {'points', 'minutes', 'played', 'reason'}.
    final: {person_id: {...}} aus ui/player_tab.final_table_data; leer = Spiel nicht beendet oder Boxscore nicht komplett (dann steht nichts)."""
    for p in model["players"]:
        p["final"] = (final or {}).get(int(p["person_id"]))
    return model


def shown_milestones(model: dict) -> dict:
    """{person_id: {Meilensteine}} der angezeigten Zeilen (damit die Live-Chancen nur dafuer gerechnet werden)."""
    return {p["person_id"]: {r["n"] for r in p["rows"]} for p in model["players"]}


def attach_live(model: dict, live: dict | None) -> dict:
    """Live-Werte nachtraeglich in ein fertiges Tabellenmodell eintragen (Spalten 'Jetzt' und 'Live')."""
    for p in model["players"]:
        p["live"] = (live or {}).get(int(p["person_id"]))
    model["live"] = bool(live)
    return model


def team_lines(entry: dict) -> list[str]:
    """Kurze Zeilen zum Teamabgleich aus dem Snapshot ('Cavaliers: Spieler-Summe 144,1 → Teampunkte 115,0, Faktor 0,85')."""
    out = []
    for team, t in (entry.get("teams") or {}).items():
        if t.get("matched"):
            out.append(f"{team}: Spieler-Summe {fmt_num(t['player_sum'])} → Teampunkte {fmt_num(t['team_points'])}, Faktor {fmt_num(t['factor'], 2)}"
                       + (f" ({t['note']})" if t.get("note") else ""))
        else:
            out.append(f"{team}: {t.get('note') or 'kein Teamabgleich'}")
    return out


def fmt_min(x) -> str:
    return "–" if x is None else fmt_num(x)


def render_table_html(model: dict) -> str:
    """HTML-Tabelle: Spieler | Team | Min | Pkt | Meilenstein | Quote | Buchmacher | Modell | Differenz. Ein <tbody> je Spieler."""
    is_live = bool(model.get("live"))
    head = ("<thead><tr><th class='l'>Spieler</th><th class='l'>Team</th>" + ("<th>Jetzt<small> Pkt · Min · Fouls</small></th>" if is_live else "") + "<th>Min</th><th>Pkt</th><th>Meilenstein</th><th>Quote</th><th>Buchmacher<small> inkl. Marge</small></th>"
            f"<th>Modell<small> {UNVERIFIED.lower()}</small></th><th>Differenz<small> PP</small></th>" + (f"<th>Live<small> {UNVERIFIED.lower()}</small></th>" if is_live else "") + "</tr></thead>")
    body = []
    for p in model["players"]:
        sym = f"<span class='pl-q' title='{escape(p['tooltip'], quote=True)}'>⚠</span>" if p["tooltip"] else ""
        if p.get("bet"):
            b = p["bet"]
            sym += f" <span class='pl-bet-mark' title='Meine Wette: mindestens {b['milestone']} Punkte'>🎯 {b['milestone']}+{'' if b.get('odds') is None else ' @ ' + fmt_num(b['odds'], 2)}</span>"
        n = max(1, len(p["rows"]))
        lv = p.get("live")
        now_cell = ""
        if is_live:
            if lv:
                tip = escape("; ".join(lv.get("notes") or []), quote=True)
                warn = f" <span class='pl-q' title='{tip}'>⚠</span>" if lv.get("notes") else ""
                now_cell = f"<td rowspan='{n}'>{lv['points']} · {fmt_num(lv['minutes'], 1)} · {lv['fouls']}{warn}</td>"
            else:
                now_cell = f"<td rowspan='{n}'>–</td>"
        first = (f"<td class='l pl-name' rowspan='{n}'>{escape(p['name'])} {sym}</td><td class='l' rowspan='{n}'>{escape(p['abbr'] or '')}</td>" + now_cell +
                 f"<td rowspan='{n}'>{fmt_min(p['minutes'])}</td><td rowspan='{n}'>{fmt_min(p['points'])}</td>")
        trs = []
        rows = p["rows"] or [None]
        for i, r in enumerate(rows):
            cells = first if i == 0 else ""
            if r is None:
                cells += f"<td colspan='{6 if is_live else 5}' class='pl-none'>keine Meilensteine eingelesen</td>"
            else:
                diff = "–" if r["diff"] is None else fmt_num(r["diff"], 1, signed=True)
                cls = " pl-mark" if r["mark"] else ""
                mark = f" <span class='pl-m'>{r['mark']}</span>" if r["mark"] else ""
                model_txt = "–" if r["model_pct"] is None else f"{r['model_pct']} %"
                live_cell = ""
                if is_live:
                    ch = (lv or {}).get("chances", {}).get(r["n"])
                    reached = lv is not None and lv["points"] >= r["n"]
                    live_cell = "<td class='pl-live'>" + ("erreicht" if reached else "–" if ch is None else f"{pct_int(ch)} %") + "</td>"
                cells += (f"<td>{r['n']}+</td><td>{fmt_num(r['odds'], 2)}</td><td>{r['buch_pct']} %</td><td>{model_txt}</td><td class='pl-diff{cls}'>{diff}{mark}</td>" + live_cell)
            trs.append(f"<tr class='{'pl-first' if i == 0 else ''}'>{cells}</tr>")
        body.append("<tbody class='pl-p'>" + "".join(trs) + "</tbody>")
    return f"<div class='pl-wrap'><table class='pl-table'>{head}{''.join(body)}</table></div>"


def _css() -> str:
    P = PALETTE
    return f"""
<style>
.pl-banner {{ box-sizing:border-box; max-width:1400px; margin:6px 0 10px; padding:10px 14px; border-radius:10px; background:{P['chip_yellow_bg']}; border:1px solid {P['chip_yellow_border']}; color:{P['chip_yellow_text']}; font-size:14px; font-weight:600; }}
.pl-info {{ box-sizing:border-box; max-width:1400px; margin:4px 0; padding:8px 14px; border-radius:10px; background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; font-size:13px; }}
.pl-wrap {{ box-sizing:border-box; width:100%; max-width:1400px; overflow-x:auto; background:{P['card_bg']}; border:1px solid #2c3350; border-radius:18px; padding:10px clamp(10px,2vw,28px) 14px; margin:8px 0 16px; }}
.pl-table {{ width:100%; border-collapse:collapse; font-size:15px; color:{P['text_soft']}; font-variant-numeric:tabular-nums; }}
.pl-table th {{ text-align:right; font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:{P['label']}; font-weight:600; padding:10px 8px; border-bottom:1px solid #2c3350; white-space:nowrap; }}
.pl-table th small {{ text-transform:none; letter-spacing:0; font-weight:400; }}
.pl-table td {{ text-align:right; padding:5px 8px; white-space:nowrap; }}
.pl-table th.l, .pl-table td.l {{ text-align:left; }}
.pl-p tr.pl-first td {{ border-top:1px solid #2c3350; }}
.pl-p td[rowspan] {{ vertical-align:top; padding-top:8px; }}
.pl-name {{ font-weight:700; color:{P['text']}; }}
.pl-q {{ cursor:help; color:{P['chip_yellow_text']}; font-size:13px; }}
.pl-none {{ text-align:left; color:{P['label']}; font-size:13px; }}
.pl-diff {{ color:{P['text_soft']}; }}
.pl-diff.pl-mark {{ color:{P['chip_yellow_text']}; font-weight:700; }}
.pl-bet-mark {{ font-size:12px; color:{P['chip_blue_text']}; background:{P['chip_blue_bg']}; border:1px solid {P['chip_blue_border']}; border-radius:6px; padding:0 6px; white-space:nowrap; }}
.pl-bet {{ box-sizing:border-box; max-width:1400px; margin:8px 0; padding:12px 16px; border-radius:14px; background:#1d2338; box-shadow:inset 3px 0 0 {P['chip_blue_border']}; border:1px solid #2c3350; }}
.pl-bet-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }}
.pl-bet-name {{ font-size:17px; font-weight:700; color:{P['text']}; }}
.pl-bet-team {{ font-size:13px; font-weight:400; color:{P['label']}; }}
.pl-prob {{ display:inline-flex; flex-direction:column; align-items:flex-end; line-height:1.15; min-width:92px; padding:4px 12px; border-radius:10px; }}
.pl-prob-grau {{ background:transparent; }}
.pl-prob-val {{ font-size:26px; font-weight:800; font-variant-numeric:tabular-nums; }}
.pl-prob-sub {{ font-size:13px; font-weight:600; opacity:.95; }}
.pl-prob-tiny {{ font-size:10px; opacity:.7; letter-spacing:.04em; }}
.pl-prob-grau {{ color:{P['label']}; }}
.pl-bet-note {{ color:{P['chip_yellow_text']}; }}
.pl-bet-line {{ font-size:14px; color:{P['text_soft']}; margin-top:4px; font-variant-numeric:tabular-nums; }}
.pl-live {{ color:{P['text']}; font-weight:600; }}
.pl-m {{ display:inline-block; min-width:1.2em; text-align:center; background:{P['chip_yellow_bg']}; border:1px solid {P['chip_yellow_border']}; border-radius:6px; font-size:12px; padding:0 4px; }}
</style>
"""


# ----------------------------------------------------------------------------------------------- Meine Spieler-Wetten (Stufe 2)
def bet_summary_html(summary: dict) -> str:
    """Tagessumme der Spieler-Wetten (Wetten, offen, gewonnen, verloren, nicht gespielt, Einsatz, Gewinn/Verlust nur abgerechnet). Kacheln wie im Tab Spieltag (lv-tile)."""
    if not summary or not summary.get("wetten"):
        return "<div class='lv-sum lv-sum-empty'>Für diesen Spieltag sind noch keine Spieler-Wetten gespeichert.</div>"
    gv = summary["gewinn_verlust"]
    tiles = [("Wetten", str(summary["wetten"]), ""), ("Offen", str(summary["offen"]), ""), ("Gewonnen", str(summary["gewonnen"]), ""), ("Verloren", str(summary["verloren"]), ""),
             ("Nicht gespielt", str(summary.get("nicht_gespielt", 0)), ""), ("Einsatz", fmt_num(summary["einsatz"], 2), ""),
             ("Gewinn / Verlust (abgerechnet)", fmt_num(gv, 2, signed=True), "lv-pos" if gv > 0 else "lv-neg" if gv < 0 else "")]
    html = "".join(f"<div class='lv-tile'><div class='pc-label'>{escape(k.upper())}</div><div class='lv-val {c}'>{escape(v)}</div></div>" for k, v, c in tiles)
    notes = []
    if summary.get("nicht_gespielt"):
        notes.append(f"{summary['nicht_gespielt']} Wette(n) mit nicht gespieltem Spieler (Einsatz {fmt_num(summary.get('einsatz_nicht_gespielt', 0), 2)}): zählen weder als gewonnen noch als verloren, nicht im Gewinn; bitte beim Buchmacher prüfen")
    if summary.get("ohne_quote_oder_einsatz"):
        notes.append(f"{summary['ohne_quote_oder_einsatz']} abgerechnete Wette(n) ohne Quote oder Einsatz zählen nicht im Gewinn")
    note = f"<div class='lv-hint'>{escape('; '.join(notes))}</div>" if notes else ""
    return f"<div class='lv-sum'><div class='lv-tiles'>{html}</div>{note}</div>"


PROB_GREEN, PROB_RED = 0.70, 0.30      # Live-Chance: ab 70 % gruen, unter 30 % rot, dazwischen gelb


def prob_class(p: float) -> str:
    return "gruen" if p >= PROB_GREEN else "rot" if p < PROB_RED else "gelb"


def live_block_html(live, game_status: str | None, stale: bool = False) -> str | None:
    """Rechte Seite einer Wette bei LAUFENDEM Spiel: gross die Live-Chance (Farbe nach Schwelle), klein 'noch X Pkt.' bzw. 'erreicht', ganz klein 'ungeprueft'. Ohne Zahl (veraltet, keine Chance,
    keine Spielerdaten): '–' und der Grund. None, wenn das Spiel nicht laeuft oder die Wette nicht offen/erreicht ist (dann bleibt das bisherige Badge)."""
    if live is None or game_status not in ("LIVE", "PAUSE") or live.state not in ("laeuft", "gewonnen", "keine_daten"):
        return None
    if live.state == "gewonnen":                                   # Linie erreicht: Over ist sicher gewonnen
        return "<span class='pl-prob lv-st lv-st-gruen'><span class='pl-prob-val'>100 %</span><span class='pl-prob-sub'>erreicht</span></span>"
    if live.state == "laeuft" and live.probability is not None and not stale:
        p = float(live.probability)
        rest = max(0, int(live.needed or 0))
        return (f"<span class='pl-prob lv-st lv-st-{prob_class(p)}'><span class='pl-prob-val'>{int(p * 100 + 0.5)} %</span><span class='pl-prob-sub'>noch {rest} Pkt.</span>"
                "<span class='pl-prob-tiny'>ungeprüft</span></span>")
    if stale:
        reason = "Daten veraltet"
    elif live.state == "keine_daten":
        reason = live.label
    else:
        reason = next(iter(getattr(live, "live_notes", ()) or ()), None) or "keine Live-Chance"
    return f"<span class='pl-prob pl-prob-grau'><span class='pl-prob-val'>–</span><span class='pl-prob-sub'>{escape(reason)}</span></span>"


def bet_card_html(bet: dict, live, game_label: str, game_clock_label: str | None = None, score: str | None = None, game_status: str | None = None, stale: bool = False) -> str:
    """Karte einer Spieler-Wette: Spieler, Meilenstein, Quote, Einsatz, Status (Text + Farbe), Punkte/noch noetig/Minuten/Fouls, Gewinn/Verlust. live: BetLivePlayer oder None (kein Status)."""
    n = bet["milestone"]
    title = f"{escape(bet['name'])}" + (f" <span class='pl-bet-team'>{escape(bet['team'])}</span>" if bet.get("team") else "")
    money = lambda v: "—" if v is None else fmt_num(float(v), 2)
    line1 = f"Spiel {escape(game_label)} · mindestens {n} Punkte (Over {fmt_num(n - 0.5, 1)}) · Quote {money(bet.get('odds'))} · Einsatz {money(bet.get('stake'))}"
    block = None
    if live is None:
        chip, color, detail = "Kein Status (Spiel nicht im Scoreboard)", "grau", ""
    else:
        chip, color = live.label, live.color
        parts = []
        if live.points is not None:
            parts.append(f"Punkte {live.points} von {n}" + (f", noch {live.needed}" if live.needed else ""))
        if live.minutes is not None:
            parts.append(f"{fmt_num(live.minutes, 1)} Min")
        if live.fouls is not None:
            parts.append(f"{live.fouls} Fouls")
        if live.player_status:
            parts.append(live.player_status)
        if score:
            parts.append(f"Spielstand {score}" + (f" ({game_clock_label})" if game_clock_label else ""))
        block = live_block_html(live, game_status, stale)
        if live.probability is not None and block is None:
            parts.append(f"Live-Chance {int(live.probability * 100 + 0.5)} % (ungeprüft)")
        if live.profit is not None:
            parts.append(f"Gewinn/Verlust {fmt_num(live.profit, 2, signed=True)}")
        detail = " · ".join(escape(x) for x in parts)
    notes = [n for n in (getattr(live, "live_notes", ()) or ())] if live is not None else []
    note_html = f"<div class='pl-bet-line pl-bet-note'>⚠ {escape('; '.join(notes))}</div>" if notes else ""
    right = block or f"<span class='lv-st lv-st-{color}'>{escape(chip)}</span>"
    return (f"<div class='pl-bet'><div class='pl-bet-head'><span class='pl-bet-name'>{title}</span>{right}</div>"
            f"<div class='pl-bet-line'>{line1}</div>" + (f"<div class='pl-bet-line'>{detail}</div>" if detail else "") + note_html + "</div>")


PLAYER_CSS = _css()

# ----------------------------------------------------------------------------------------------- Spieler-Karten (Ansicht "Karten", Standard im Tab Prognose)
CARD_HIGHLIGHT_MIN_PCT = 60              # Zeile violett hinterlegt, wenn das angezeigte (gerundete) Modell in Prozent mindestens so hoch ist
BLUE, ORANGE = "#6f8fd6", "#ff7a2f"      # Balken: Betano (inkl. Marge) / Modell roh (Einzelprognose ohne Teamabgleich)
DIFF_COLOR_PP = 3.0                      # Differenz ab +3 gruen, ab -3 rot, sonst grau


def diff_class(diff_pp: float | None) -> str:
    return "pl-cd-grau" if diff_pp is None else "pl-cd-gruen" if diff_pp >= DIFF_COLOR_PP else "pl-cd-rot" if diff_pp <= -DIFF_COLOR_PP else "pl-cd-grau"


def absence_box_html(cur: dict | None) -> str:
    """Gelber Ueberblick 'Ausfaelle fuer dieses Spiel' (ohne Bedienung): Fehlt, Fraglich und Herkunft (automatisch ESPN mit Stand / von Hand) aus den Ausfall-Daten (data/absences_store.get)."""
    cur = cur or {}
    out, dbt = cur.get("out") or {}, cur.get("doubtful") or {}
    if not out and not dbt:
        return ""
    names = lambda m: ", ".join(f"{escape(v['name'])} ({escape(v.get('team') or '–')})" for v in sorted(m.values(), key=lambda v: v["name"])) or "–"
    entries = list(out.values()) + list(dbt.values())
    origin = []
    if any(v.get("source") for v in entries):
        stamp = (cur.get("auto") or {}).get("fetched_at") or next((v.get("fetched_at") for v in entries if v.get("source")), "") or ""
        origin.append("automatisch (ESPN)" + (f", Stand {stamp[11:16]}" if stamp[11:16] else ""))
    if any(not v.get("source") for v in entries):
        origin.append("von Hand")
    return (f"<div class='pl-c-abs'><div class='pl-c-abs-t'>Ausfälle für dieses Spiel</div><div>Fehlt: {names(out)}</div><div>Fraglich: {names(dbt)}</div>"
            f"<div class='pl-c-abs-o'>{' · '.join(origin)}</div></div>")


def _card_row(r: dict, lv: dict | None, who: tuple | None = None, fin: dict | None = None) -> str:
    odds = "" if r.get("odds") is None else f"<span class='pl-c-odds'>@ {fmt_num(r['odds'], 2)}</span>"
    safe = r.get("safe_odds")                                            # nur Starter mit genug Spielen und Roh-Chance ab PLAYER_SAFE_MIN_PROB (engine/safety_levels.player_safe_odds)
    tick = "" if safe is None else (f" <span class='pl-c-ok' title='Starter mit mindestens {settings.PLAYER_MIN_GAMES} Spielen, Roh-Chance mindestens "
                                    f"{round(settings.PLAYER_SAFE_MIN_PROB * 100)} %'>✓</span>")
    min_odds = "" if safe is None else f"<span class='pl-c-minodds'>Mindestquote {sl.odds_text(safe)}</span>"
    buch = max(0, min(100, int(r["buch_pct"])))
    model = r["model_pct"]
    model_bar = "" if model is None else f"<span class='pl-c-bar pl-c-bar-m'><i style='width:{max(0, min(100, int(model)))}%'></i></span>"
    model_txt = "<span class='pl-c-wm'>Modell</span> <b>–</b>" if model is None else f"<span class='pl-c-wm'>Modell</span> <b>{model} %</b>"
    diff = "–" if r["diff"] is None else fmt_num(r["diff"], 1, signed=True)
    mark = f"<span class='pl-c-mark'>{r['mark']}</span>" if r["mark"] else ""
    live_txt = ""
    if lv is not None:
        ch = (lv.get("chances") or {}).get(r["n"])
        live_txt = "<span class='pl-c-live'>" + ("erreicht" if lv["points"] >= r["n"] else "Live –" if ch is None else f"Live {pct_int(ch)} %") + "</span>"
    hi = " pl-c-hi" if model is not None and model >= CARD_HIGHLIGHT_MIN_PCT else ""
    res = ""                                                             # beendetes Spiel: hervorgehobene Zeile (Modell ab 60 %) mit Ergebnis - gruenes Haekchen erreicht, rotes X verfehlt (nicht gespielt: nichts)
    if hi and fin is not None and fin.get("played"):
        got = fin["points"] >= r["n"]
        res = (f"<span class='pl-c-res {'pl-c-res-ok' if got else 'pl-c-res-no'}' title='{r['n']}+ {'erreicht' if got else 'verfehlt'}: {fin['points']} Punkte'>{'✓' if got else '✗'}</span>")
    attrs = "" if who is None else (f" data-pid='{int(who[0])}' data-name='{escape(str(who[1]), quote=True)}' data-n='{int(r['n'])}' data-odds='{'' if r.get('odds') is None else r['odds']}'"
                                     f" data-buch='{buch}' data-model='{'' if model is None else model}'")      # fuer die anklickbare Karten-Komponente (ui/components/bet_cards)
    return (f"<div class='pl-c-row{hi}'{attrs}><div class='pl-c-n'><b>{r['n']}+{tick}</b>{odds}{min_odds}</div>"
            f"<div class='pl-c-mid'><div class='pl-c-bars'><span class='pl-c-bar pl-c-bar-b'><i style='width:{buch}%'></i></span>{model_bar}</div><span class='pl-c-txt'><span class='pl-c-wb'>Betano</span> <b>{buch} %</b> · {model_txt}</span></div>"
            f"<div class='pl-c-d'>{res}<span class='{diff_class(r['diff'])}'>{diff}</span>{mark}{live_txt}</div></div>")


def render_cards_html(model: dict, absences: dict | None = None) -> str:
    """Spieler-Karten (ein Block, Raster): Kopf (Name, Hinweis bei wenigen Spielen, Warnung, Wette, Team), Meta (Punkte erwartet, Minuten), je Meilenstein eine Zeile mit Quote, Balken Betano/Modell und Differenz in PP.
    Gleiche Zahlen und Reihenfolge wie render_table_html (model aus build_table_model; die Karten werden mit mode 'raw' gebaut: Balken und Differenz = Modell roh); bei laufendem Spiel zusaetzlich 'Jetzt' und Live-Chance je Zeile."""
    cards = []
    for p in model["players"]:
        sym = f" <span class='pl-q' title='{escape(p['tooltip'], quote=True)}'>⚠</span>" if p["tooltip"] else ""
        if p.get("bet"):
            b = p["bet"]
            sym += f" <span class='pl-bet-mark' title='Meine Wette: mindestens {b['milestone']} Punkte'>🎯 {b['milestone']}+{'' if b.get('odds') is None else ' @ ' + fmt_num(b['odds'], 2)}</span>"
        few = f" <span class='pl-c-few'>{escape(p['few_games'])}</span>" if p.get("few_games") else ""
        lv = p.get("live")
        meta = (f"<b>{fmt_min(p['points'])}</b> Punkte erwartet · <b>{fmt_min(p['minutes'])}</b> Min" if p["ok"] else "keine Prognose")
        fin = p.get("final")                                             # beendetes Spiel: was der Spieler wirklich gemacht hat (Boxscore)
        if fin is not None:
            meta += " · <span class='pl-c-final'>" + (f"Erzielt <b>{fin['points']}</b> Pkt · <b>{fmt_num(fin['minutes'], 1)}</b> Min" if fin["played"]
                                                       else "Nicht gespielt" + (f" ({escape(fin['reason'])})" if fin.get("reason") else "")) + "</span>"
        now = ""
        if model.get("live"):
            now = ("<div class='pl-c-now'>Jetzt: " + (f"<b>{lv['points']}</b> Pkt · <b>{fmt_num(lv['minutes'], 1)}</b> Min · <b>{lv['fouls']}</b> Fouls"
                                                       + (f" <span class='pl-q' title='{escape('; '.join(lv.get('notes') or []), quote=True)}'>⚠</span>" if lv.get("notes") else "") if lv else "–") + "</div>")
        rows = "".join(_card_row(r, lv, (p["person_id"], p["name"]), p.get("final")) for r in p["rows"]) or "<div class='pl-none'>keine Meilensteine eingelesen</div>"
        cards.append(f"<div class='pl-card'><div class='pl-c-head'><span class='pl-c-name'>{escape(p['name'])}{few}{sym}</span><span class='pl-c-team'>{escape(p['abbr'] or p.get('team') or '')}</span></div>"
                     f"<div class='pl-c-meta'>{meta}</div>{now}{rows}</div>")
    legend = (f"<div class='pl-c-legend'><span class='pl-c-key' style='background:{BLUE}'></span>Betano inkl. Marge · <span class='pl-c-key' style='background:{ORANGE}'></span>Modell roh ({UNVERIFIED.lower()}) · "
              "Zahl rechts = Differenz Modell roh minus Betano in Prozentpunkten"
              f"<br>Violett hinterlegt = Modell ≥ {CARD_HIGHLIGHT_MIN_PCT} % · weiße Linie im Balken = {CARD_HIGHLIGHT_MIN_PCT} %"
              f"<br>✓ = Starter mit mindestens {settings.PLAYER_MIN_GAMES} Spielen und Modell roh ab {round(settings.PLAYER_SAFE_MIN_PROB * 100)} %, darunter die Mindestquote (keine Wettempfehlung)</div>")
    return f"{absence_box_html(absences)}<div class='pl-cards'>{''.join(cards)}</div>{legend}"


def _cards_css() -> str:
    from ui.live_card import STATUS as S
    P = PALETTE
    return f"""
<style>
.pl-cards {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; max-width:1400px; }}
@media (max-width:700px) {{ .pl-cards {{ grid-template-columns:1fr; }} }}
.pl-card {{ box-sizing:border-box; padding:10px 14px 8px; border-radius:14px; background:#1d2338; border:1px solid #2c3350; }}
.pl-c-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:8px; }}
.pl-c-name {{ font-size:20px; font-weight:700; color:{P['text']}; }}
.pl-c-team {{ font-size:15px; color:{P['label']}; }}
.pl-c-meta {{ font-size:15px; color:{P['label']}; margin:3px 0 8px; }}
.pl-c-final {{ display:inline-block; padding:0 8px; border-radius:6px; background:{P['chip_gray_bg']}; border:1px solid {P['chip_gray_border']}; color:{P['chip_gray_text']}; white-space:nowrap; }}
.pl-c-final b {{ color:{P['text']}; }}
.pl-c-now {{ font-size:14px; color:{P['label']}; margin:0 0 8px; }}
.pl-c-head .pl-bet-mark, .pl-c-head .pl-q {{ font-size:14px; }}
.pl-c-meta b, .pl-c-now b {{ color:{P['text']}; }}
.pl-c-row {{ display:grid; grid-template-columns:84px 1fr 112px; gap:12px; align-items:center; padding:7px 6px; margin:0 -6px; border-radius:8px; }}
.pl-c-abs {{ box-sizing:border-box; max-width:1400px; margin:0 0 12px; padding:10px 14px; border-radius:12px; background:rgba(232,182,49,.12); border:1px solid #8f7220; color:#f3d36b; font-size:15px; }}
.pl-c-abs-t {{ font-weight:700; margin-bottom:3px; }} .pl-c-abs-o {{ font-size:12px; color:{P['label']}; margin-top:3px; }}
.pl-c-hi {{ background:rgba(139,92,246,.16); }}
.pl-c-n b {{ display:block; font-size:20px; color:{P['text']}; }}
.pl-c-odds {{ display:block; font-size:14px; color:{P['label']}; }}
.pl-c-minodds {{ display:block; font-size:12px; line-height:1.2; margin-top:2px; color:{P['label']}; white-space:normal; }}
.pl-c-ok {{ font-size:15px; font-weight:700; color:{P['win_ok_text']}; }}
.pl-c-few {{ display:inline-block; margin-left:4px; padding:0 6px; border-radius:6px; font-size:12px; font-weight:600; line-height:1.5; vertical-align:middle; background:{P['chip_yellow_bg']}; border:1px solid {P['chip_yellow_border']}; color:{P['chip_yellow_text']}; }}
.pl-c-mid {{ min-width:0; }}
.pl-c-bar {{ display:block; height:10px; border-radius:5px; background:#2a3250; margin-bottom:5px; overflow:hidden; }}
.pl-c-bar i {{ display:block; height:100%; border-radius:5px; }}
.pl-c-bar-b i {{ background:{BLUE}; }} .pl-c-bar-m i {{ background:{ORANGE}; }}
.pl-c-bars {{ position:relative; }}
.pl-c-bars::after {{ content:""; position:absolute; top:-2px; bottom:3px; left:{CARD_HIGHLIGHT_MIN_PCT}%; width:2px; margin-left:-1px; background:rgba(255,255,255,.7); border-radius:1px; pointer-events:none; }}
.pl-c-txt {{ display:block; font-size:17px; line-height:1.35; color:{P['text']}; white-space:normal; font-variant-numeric:tabular-nums; }}
.pl-c-txt b {{ font-weight:700; }}
.pl-c-wb {{ color:{BLUE}; font-weight:600; }} .pl-c-wm {{ color:{ORANGE}; font-weight:600; }}
.pl-c-d {{ text-align:right; font-size:20px; font-weight:700; white-space:nowrap; font-variant-numeric:tabular-nums; }}
.pl-c-mark {{ font-size:15px; margin-left:3px; color:{P['label']}; font-weight:400; }}
.pl-c-live {{ display:block; font-size:14px; font-weight:400; color:{P['label']}; }}
.pl-c-res {{ font-size:22px; font-weight:800; margin-right:8px; vertical-align:middle; }}
.pl-c-res-ok {{ color:{S['gruen']['text']}; }} .pl-c-res-no {{ color:{S['rot']['text']}; }}
.pl-cd-gruen {{ color:{S['gruen']['text']}; }} .pl-cd-rot {{ color:{S['rot']['text']}; }} .pl-cd-grau {{ color:{P['text_soft']}; }}
.pl-c-legend {{ font-size:12px; color:{P['label']}; margin:8px 0 2px; }}
.pl-c-key {{ display:inline-block; width:10px; height:5px; border-radius:2px; margin-right:4px; vertical-align:middle; }}
</style>
"""


CARDS_CSS = _cards_css()
