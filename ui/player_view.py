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


def build_table_model(entry: dict, mode: str = "team", sort: str = "team") -> dict:
    """Anzeigewerte aus einem Snapshot-Eintrag (ein Spiel). mode: 'team' (Teamabgleich) oder 'raw'; sort: 'team' | 'minutes' | 'diff'.
    Rueckgabe {'players': [{person_id, name, team, abbr, ok, minutes, points, tooltip, rows: [{n, odds, bookmaker, buch_pct, model_pct, diff, mark}], max_diff}], 'mode', 'sort'}.
    Die Differenz wird aus ungerundeten Werten gerechnet (Modell minus Buchmacher-Chance inkl. Marge, in Prozentpunkten)."""
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
                        "minutes": minutes, "points": points, "tooltip": quality_text(p), "rows": rows, "max_diff": max(diffs) if diffs else -1.0})
    if sort == "minutes":
        players.sort(key=lambda p: (-(p["minutes"] if p["minutes"] is not None else -1), p["name"]))
    elif sort == "diff":
        players.sort(key=lambda p: (-p["max_diff"], p["name"]))
    else:
        players.sort(key=lambda p: (p["team"] or "", -(p["minutes"] if p["minutes"] is not None else -1), p["name"]))
    return {"players": players, "mode": mode, "sort": sort}


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
    head = ("<thead><tr><th class='l'>Spieler</th><th class='l'>Team</th><th>Min</th><th>Pkt</th><th>Meilenstein</th><th>Quote</th><th>Buchmacher<small> inkl. Marge</small></th>"
            f"<th>Modell<small> {UNVERIFIED.lower()}</small></th><th>Differenz<small> PP</small></th></tr></thead>")
    body = []
    for p in model["players"]:
        sym = f"<span class='pl-q' title='{escape(p['tooltip'], quote=True)}'>⚠</span>" if p["tooltip"] else ""
        n = max(1, len(p["rows"]))
        first = (f"<td class='l pl-name' rowspan='{n}'>{escape(p['name'])} {sym}</td><td class='l' rowspan='{n}'>{escape(p['abbr'] or '')}</td>"
                 f"<td rowspan='{n}'>{fmt_min(p['minutes'])}</td><td rowspan='{n}'>{fmt_min(p['points'])}</td>")
        trs = []
        rows = p["rows"] or [None]
        for i, r in enumerate(rows):
            cells = first if i == 0 else ""
            if r is None:
                cells += "<td colspan='5' class='pl-none'>keine Meilensteine eingelesen</td>"
            else:
                diff = "–" if r["diff"] is None else fmt_num(r["diff"], 1, signed=True)
                cls = " pl-mark" if r["mark"] else ""
                mark = f" <span class='pl-m'>{r['mark']}</span>" if r["mark"] else ""
                model_txt = "–" if r["model_pct"] is None else f"{r['model_pct']} %"
                cells += (f"<td>{r['n']}+</td><td>{fmt_num(r['odds'], 2)}</td><td>{r['buch_pct']} %</td><td>{model_txt}</td><td class='pl-diff{cls}'>{diff}{mark}</td>")
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
.pl-m {{ display:inline-block; min-width:1.2em; text-align:center; background:{P['chip_yellow_bg']}; border:1px solid {P['chip_yellow_border']}; border-radius:6px; font-size:12px; padding:0 4px; }}
</style>
"""


PLAYER_CSS = _css()
