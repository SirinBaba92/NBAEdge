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


def build_table_model(entry: dict, mode: str = "team", sort: str = "team", bets: dict | None = None, live: dict | None = None, absences: dict | None = None) -> dict:
    """Anzeigewerte aus einem Snapshot-Eintrag (ein Spiel). mode: 'team' (Teamabgleich) oder 'raw'; sort: 'team' | 'minutes' | 'diff'.
    Rueckgabe {'players': [{person_id, name, team, abbr, ok, minutes, points, tooltip, rows: [{n, odds, bookmaker, buch_pct, model_pct, diff, mark}], max_diff}], 'mode', 'sort'}.
    Die Differenz wird aus ungerundeten Werten gerechnet (Modell minus Buchmacher-Chance inkl. Marge, in Prozentpunkten). bets: aktive Spieler-Wetten {person_id: Wette} (Marker am Namen). live: {person_id: {'points', 'minutes', 'fouls', 'status', 'chances': {N: Anteil}, 'notes': [...], 'out': bool}} fuer laufende Spiele (Spalten 'Jetzt' und 'Live')."""
    team_mode = mode != "raw"
    players = []
    for p in entry.get("players", []):
        pj = (p.get("p_ge_adjusted") if team_mode else p.get("p_ge_raw")) or {}
        rows = []
        for q in sorted(p.get("quotes") or [], key=lambda q: q["milestone"]):
            m = pj.get(str(q["milestone"])) if p.get("ok") else None
            diff = None if m is None else (m - q["bookmaker_probability"]) * 100
            rows.append({"n": q["milestone"], "odds": q["odds"], "bookmaker": q.get("bookmaker"), "buch_pct": pct_int(q["bookmaker_probability"]),
                         "model_pct": None if m is None else pct_int(m), "diff": diff, "mark": mark_for(diff)})
        if not p.get("ok"):
            minutes = points = None
        else:
            minutes = p["minutes_adjusted"] if team_mode else p["minutes"]["mean"]
            points = p["expected_points_adjusted"] if team_mode else p["expected_points_raw"]
        diffs = [abs(r["diff"]) for r in rows if r["diff"] is not None]
        players.append({"person_id": p["person_id"], "name": p["name"], "team": p.get("team"), "abbr": p.get("team_abbreviation") or "", "ok": bool(p.get("ok")),
                        "minutes": minutes, "points": points, "tooltip": quality_text(p), "rows": rows, "max_diff": max(diffs) if diffs else -1.0,
                        "bet": (bets or {}).get(int(p["person_id"])), "live": (live or {}).get(int(p["person_id"]))})
        mark_abs = ("fehlt" if int(p["person_id"]) in (absences or {}).get("out", {}) else "fraglich" if int(p["person_id"]) in (absences or {}).get("doubtful", {}) else "")
        if mark_abs:
            players[-1]["tooltip"] = (players[-1]["tooltip"] + " | " if players[-1]["tooltip"] else "") + f"Ausfall-Auswahl: {mark_abs} (siehe „Ausfälle“; die Tabelle zeigt weiter den ursprünglichen Snapshot)"
    if sort == "minutes":
        players.sort(key=lambda p: (-(p["minutes"] if p["minutes"] is not None else -1), p["name"]))
    elif sort == "diff":
        players.sort(key=lambda p: (-p["max_diff"], p["name"]))
    else:
        players.sort(key=lambda p: (p["team"] or "", -(p["minutes"] if p["minutes"] is not None else -1), p["name"]))
    return {"players": players, "mode": mode, "sort": sort, "live": bool(live)}


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


def bet_card_html(bet: dict, live, game_label: str, game_clock_label: str | None = None, score: str | None = None) -> str:
    """Karte einer Spieler-Wette: Spieler, Meilenstein, Quote, Einsatz, Status (Text + Farbe), Punkte/noch noetig/Minuten/Fouls, Gewinn/Verlust. live: BetLivePlayer oder None (kein Status)."""
    n = bet["milestone"]
    title = f"{escape(bet['name'])}" + (f" <span class='pl-bet-team'>{escape(bet['team'])}</span>" if bet.get("team") else "")
    money = lambda v: "—" if v is None else fmt_num(float(v), 2)
    line1 = f"Spiel {escape(game_label)} · mindestens {n} Punkte (Over {fmt_num(n - 0.5, 1)}) · Quote {money(bet.get('odds'))} · Einsatz {money(bet.get('stake'))}"
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
        if live.probability is not None:
            parts.append(f"Live-Chance {int(live.probability * 100 + 0.5)} % (ungeprüft)")
        if live.profit is not None:
            parts.append(f"Gewinn/Verlust {fmt_num(live.profit, 2, signed=True)}")
        detail = " · ".join(escape(x) for x in parts)
    notes = [n for n in (getattr(live, "live_notes", ()) or ())] if live is not None else []
    note_html = f"<div class='pl-bet-line pl-bet-note'>⚠ {escape('; '.join(notes))}</div>" if notes else ""
    return (f"<div class='pl-bet'><div class='pl-bet-head'><span class='pl-bet-name'>{title}</span><span class='lv-st lv-st-{color}'>{escape(chip)}</span></div>"
            f"<div class='pl-bet-line'>{line1}</div>" + (f"<div class='pl-bet-line'>{detail}</div>" if detail else "") + note_html + "</div>")


# ----------------------------------------------------------------------------------------------- Ausfaelle (Stufe 4): Vergleich ursprünglich gegen neu
def build_compare_model(base: dict | None, variant: dict, mode: str = "team") -> dict:
    """Vergleich des urspruenglichen Snapshots (base, darf None sein) mit der Variante mit Ausfaellen (Eintrag im Snapshot-Format). Je Spieler der Variante: Minuten/Punkte alt und neu,
    je Meilenstein Quote, Buchmacher, Modell alt und neu, Aenderung (neu minus alt) und Differenz neu gegen Buchmacher (Prozentpunkte, Markierung wie in der Tabelle)."""
    old = build_table_model(base, mode, "team")["players"] if base else []
    new = build_table_model(variant, mode, "team")["players"]
    old_by = {p["person_id"]: p for p in old}
    out = []
    for p in new:
        o = old_by.get(p["person_id"])
        rows = []
        for r in p["rows"]:
            ro = next((x for x in (o["rows"] if o else []) if x["n"] == r["n"]), None)
            delta = None if (ro is None or ro["model_pct"] is None or r["model_pct"] is None) else r["model_pct"] - ro["model_pct"]
            rows.append({**r, "model_old_pct": None if ro is None else ro["model_pct"], "delta": delta})
        flag = "fehlt" if "fehlt" in (p["tooltip"] or "") and not p["ok"] else ("fraglich" if "fraglich" in (p["tooltip"] or "") else "")
        out.append({**p, "rows": rows, "minutes_old": None if o is None else o["minutes"], "points_old": None if o is None else o["points"], "flag": flag})
    return {"players": out, "mode": mode}


def render_compare_html(model: dict) -> str:
    head = ("<thead><tr><th class='l'>Spieler</th><th class='l'>Team</th><th>Min<small> alt → neu</small></th><th>Pkt<small> alt → neu</small></th><th>Meilenstein</th><th>Quote</th>"
            f"<th>Buchmacher<small> inkl. Marge</small></th><th>Modell alt<small> {UNVERIFIED.lower()}</small></th><th>Modell neu<small> {UNVERIFIED.lower()}</small></th><th>Änderung<small> PP</small></th>"
            "<th>Differenz neu<small> PP</small></th></tr></thead>")
    pair = lambda a, b: f"{fmt_min(a)} → {fmt_min(b)}"
    body = []
    for p in model["players"]:
        n = max(1, len(p["rows"]))
        tag = {"fehlt": " <span class='pl-m'>fehlt</span>", "fraglich": " <span class='pl-m'>fraglich</span>"}.get(p["flag"], "")
        sym = f" <span class='pl-q' title='{escape(p['tooltip'], quote=True)}'>⚠</span>" if p["tooltip"] else ""
        first = (f"<td class='l pl-name' rowspan='{n}'>{escape(p['name'])}{tag}{sym}</td><td class='l' rowspan='{n}'>{escape(p['abbr'] or '')}</td>"
                 f"<td rowspan='{n}'>{pair(p['minutes_old'], p['minutes'])}</td><td rowspan='{n}'>{pair(p['points_old'], p['points'])}</td>")
        trs = []
        for i, r in enumerate(p["rows"] or [None]):
            cells = first if i == 0 else ""
            if r is None:
                cells += "<td colspan='7' class='pl-none'>keine Meilensteine eingelesen</td>"
            else:
                old_t = "–" if r["model_old_pct"] is None else f"{r['model_old_pct']} %"
                new_t = "–" if r["model_pct"] is None else f"{r['model_pct']} %"
                dl = "–" if r["delta"] is None else fmt_num(r["delta"], 0, signed=True)
                diff = "–" if r["diff"] is None else fmt_num(r["diff"], 1, signed=True)
                mark = f" <span class='pl-m'>{r['mark']}</span>" if r["mark"] else ""
                cells += (f"<td>{r['n']}+</td><td>{fmt_num(r['odds'], 2)}</td><td>{r['buch_pct']} %</td><td>{old_t}</td><td>{new_t}</td><td>{dl}</td>"
                          f"<td class='pl-diff{' pl-mark' if r['mark'] else ''}'>{diff}{mark}</td>")
            trs.append(f"<tr class='{'pl-first' if i == 0 else ''}'>{cells}</tr>")
        body.append("<tbody class='pl-p'>" + "".join(trs) + "</tbody>")
    return f"<div class='pl-wrap'><table class='pl-table'>{head}{''.join(body)}</table></div>"


PLAYER_CSS = _css()
