"""
Auswertung der Schnappschuesse (nur lesend, ohne Netz): Kalibrierungstabelle je Markt.

  venv/bin/python analysis/eval_snapshots.py [--alle] [Pfad/zu/projection_snapshots.json]

Liest je beendetem Spiel mit Ergebnis die letzte Version vor dem Anpfiff und wertet jede Zeile aus, die eine vorhergesagte (wahrscheinlichere) Seite hat:
Trefferquote der vorhergesagten Seite je Stufe der vorhergesagten Wahrscheinlichkeit (50-60 %, 60-70 %, 70-80 %, 80-90 %, 90+ %), getrennt fuer alle
Zeilen und nur fuer Hauptlinien. Push (ganzzahlige Linie, exakter Treffer) und 50 : 50 zaehlen nicht mit (Push wird separat genannt).
Maerkte: Spread, Total, Team Total (Gast und Heim zusammen). Bei weniger als 30 Zeilen je Stufe: Hinweis "zu wenig Daten". Aendert nichts.
Gruppiert nach sigmas_version der Schnappschuss-Version (fehlt das Feld: Version 1 mit Spread 10,5 / Total 18,0 / Team Total 12,5; ab 23.10.2026 Version 2 mit
13,2 / 18,6 / 11,6): Prozentwerte verschiedener Versionen werden nie in einer Tabelle gemischt. Mit "--alle" zusaetzlich eine zusammengefasste Tabelle.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.projection_snapshots import sigmas_version_of
from engine.line_probabilities import row_outcome

MIN_ROWS = 30
BUCKETS = [(50, 60, "50-60 %"), (60, 70, "60-70 %"), (70, 80, "70-80 %"), (80, 90, "80-90 %"), (90, 101, "90+ %")]
MARKETS = {"spread": ("Spread", ("spread",)), "total": ("Total", ("total",)), "team_total": ("Team Total", ("team_away", "team_home"))}


def collect(data: dict, version: str | None = None) -> dict:
    """{markt: [(p_vorhergesagt in %, getroffen True/False, ist_hauptlinie), ...]} plus Zaehler fuer Push. Nur beendete Spiele mit Ergebnis und Version.
    version: nur Schnappschuesse mit dieser sigmas_version ("1", "2"); None = alle."""
    rows = {m: [] for m in MARKETS}
    push = {m: 0 for m in MARKETS}
    games = 0
    for g in (data.get("games") or {}).values():
        res, versions = g.get("result"), g.get("versions")
        if not res or not versions:
            continue
        if version is not None and sigmas_version_of(versions[-1]) != version:
            continue
        games += 1
        tables = versions[-1].get("tables") or {}
        for m, (_, keys) in MARKETS.items():
            for k in keys:
                t = tables.get(k)
                if not t:
                    continue
                for r in t.get("rows", []):
                    o = row_outcome(t["kind"], r, t.get("favorite"), res["home_points"], res["away_points"], k)
                    if o is None:
                        continue
                    if o == "push":
                        push[m] += 1
                        continue
                    rows[m].append((max(r["p_left"], r["p_right"]), o == "hit", bool(r["is_main"])))
    return {"rows": rows, "push": push, "games": games}


def table(entries: list) -> list[tuple]:
    out = []
    for lo, hi, label in BUCKETS:
        sel = [e for e in entries if lo <= e[0] < hi]
        n = len(sel)
        out.append((label, n, (sum(1 for e in sel if e[1]) / n) if n else None, (sum(e[0] for e in sel) / n) if n else None))
    return out


SIGMAS_TEXT = {"1": "Streuung Version 1 (Spread 10,5 / Total 18,0 / Team Total 12,5)", "2": "Streuung Version 2 (Spread 13,2 / Total 18,6 / Team Total 11,6)"}


def versions_in(data: dict) -> list[str]:
    return sorted({sigmas_version_of(g["versions"][-1]) for g in (data.get("games") or {}).values() if g.get("result") and g.get("versions")})


def render_one(data: dict, version: str | None) -> str:
    c = collect(data, version)
    head = SIGMAS_TEXT.get(version, f"Streuung Version {version}") if version else "alle Versionen zusammen (nicht vergleichbar)"
    lines = [f"Auswertung der Schnappschuesse: {c['games']} beendete Spiele mit Ergebnis | {head}"]
    if not c["games"]:
        lines.append("Noch keine beendeten Spiele mit Schnappschuss und Ergebnis.")
        return "\n".join(lines)
    for m, (title, _) in MARKETS.items():
        for scope, flt in (("alle Zeilen", lambda e: True), ("nur Hauptlinien", lambda e: e[2])):
            entries = [e for e in c["rows"][m] if flt(e)]
            lines += ["", f"{title} - {scope} ({len(entries)} Zeilen" + (f", {c['push'][m]} Push ausgenommen" if scope == "alle Zeilen" and c["push"][m] else "") + ")",
                      f"  {'Stufe':<9}{'Zeilen':>7}{'Trefferquote':>14}{'Ø vorhergesagt':>16}  Hinweis"]
            for label, n, rate, avg in table(entries):
                note = "zu wenig Daten" if n < MIN_ROWS else ""
                lines.append(f"  {label:<9}{n:>7}{(f'{rate * 100:.1f} %' if rate is not None else '-'):>14}{(f'{avg:.1f} %' if avg is not None else '-'):>16}  {note}")
    return "\n".join(lines)


def render(data: dict, mix: bool = False) -> str:
    """Eine Tabelle je sigmas_version (getrennt); mix=True haengt eine zusammengefasste Tabelle an."""
    vs = versions_in(data)
    if not vs:
        return render_one(data, None)
    parts = [render_one(data, v) for v in vs]
    if mix and len(vs) > 1:
        parts.append(render_one(data, None))
    return "\n\n".join(parts)


def main(argv) -> int:
    mix = "--alle" in argv
    argv = [a for a in argv if a != "--alle"]
    path = Path(argv[0]) if argv else None
    if path is None:
        from data.projection_snapshots import snapshot_path
        path = snapshot_path()
    if not path.exists():
        print(f"Keine Schnappschuss-Datei: {path}")
        return 1
    print(render(json.loads(path.read_text(encoding="utf-8")), mix=mix))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
