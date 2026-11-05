"""
Spiele mit grossen Ausfaellen gegen Spiele ohne: liegt das Modell bei grossen Ausfaellen schlechter? UNGEPRUEFT, kleine Stichprobe, nur Beschreibung.
NUR LESEND (Snapshots, data/tracking/absences.json, data/rosters.json, Recorder-/Liga-Ergebnisse wie analysis/info_value_test.py), kein Netz, aendert weder Modell noch App.
Schreibt NUR analysis/results/ausfall_gruppen.txt.

Aufruf:  venv/bin/python analysis/ausfall_gruppen.py

Definition
- Grosser Ausfall: Spieler, der laut absences.json (history) im letzten Stand VOR dem Anpfiff "fehlt" und dessen erwartete Minuten im Snapshot mindestens MIN_MINUTES (20) betragen.
  Erwartete Minuten: Snapshot teams[<Team>].minutes_new (Rotation), sonst players[].minutes.mean. Ohne Minutenwert zaehlt der Spieler nicht als gross (wird gemeldet).
- Gruppe A: mindestens ein Team hat K_GROSS (3) oder mehr grosse Ausfaelle. Gruppe B: alle anderen Spiele mit Ausfall-Stand vor dem Anpfiff.
  "unbekannt": kein Eintrag in absences.json oder kein Stand (history) vor dem Anpfiff.
- Spiele und Zeilen: genau die von analysis/info_value_test.load_rows() (Snapshot vor Anpfiff erstellt, Ergebnis vorhanden, Spieler mit Einsatz und Prognose).
"""
from __future__ import annotations

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_player_forecasts as ev  # noqa: E402
import info_value_test as ive  # noqa: E402

OUT_TXT = ROOT / "analysis" / "results" / "ausfall_gruppen.txt"
MIN_MINUTES = 20.0
K_GROSS = 3
MIN_SPIELER_TAGE_REGRESSION = 150
B_REG = 300
GRUPPEN = ("A", "B", "unbekannt")


# ----------------------------------------------------------------------------------------------- Einteilung (rein, ohne Dateien)
def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(".", "").strip()


def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def state_before(history: list[dict], start_utc: str) -> dict | None:
    """Letzter history-Eintrag mit at <= Anpfiff, sonst None."""
    start = parse_ts(start_utc)
    best = None
    for h in history or []:
        try:
            at = parse_ts(h["at"])
        except (KeyError, ValueError):
            continue
        if at <= start and (best is None or at >= best[0]):
            best = (at, h)
    return best[1] if best else None


def classify_game(history: list[dict], start_utc: str, who: dict, minutes: dict, min_minutes: float = MIN_MINUTES, k: int = K_GROSS) -> tuple[str, dict]:
    """Einteilung eines Spiels. who: {person_id: (name, team)}; minutes: {(team, norm(name)): erwartete Minuten}.
    Rueckgabe (Gruppe 'A'|'B'|'unbekannt', Info) mit Info = {'gross': {team: [Namen]}, 'ohne_minuten': [Namen], 'ohne_zuordnung': [id]}."""
    st = state_before(history, start_utc)
    info = {"gross": {}, "ohne_minuten": [], "ohne_zuordnung": []}
    if st is None:
        return "unbekannt", info
    for pid in st.get("out") or []:
        w = who.get(int(pid))
        if not w:
            info["ohne_zuordnung"].append(int(pid))
            continue
        name, team = w
        m = minutes.get((team, norm(name)))
        if m is None:
            info["ohne_minuten"].append(name)
        elif m >= min_minutes:
            info["gross"].setdefault(team, []).append(name)
    return ("A" if any(len(v) >= k for v in info["gross"].values()) else "B"), info


# ----------------------------------------------------------------------------------------------- Daten
def _walk_people(obj, out: dict) -> None:
    if isinstance(obj, dict):
        if "person_id" in obj and "name" in obj:
            try:
                out.setdefault(int(obj["person_id"]), (obj["name"], obj.get("team")))
            except (TypeError, ValueError):
                pass
        for v in obj.values():
            _walk_people(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_people(v, out)


def people_map(absences: dict, rosters: dict, snapshots: dict) -> dict:
    """person_id -> (Name, Team): erst absences.json (Stand je Spiel), dann Snapshot-Spieler, dann Kader (aktueller Stand)."""
    who: dict = {}
    for day in (absences.get("days") or {}).values():
        for g in day.values():
            for grp in ("out", "doubtful"):
                for pid, p in (g.get(grp) or {}).items():
                    who.setdefault(int(pid), (p.get("name"), p.get("team")))
    for data in snapshots.values():
        for e in data["games"].values():
            for p in e.get("players") or []:
                who.setdefault(int(p["person_id"]), (p["name"], p.get("team")))
    _walk_people(rosters, who)
    return who


def game_minutes(entry: dict) -> dict:
    out = {}
    for team, t in (entry.get("teams") or {}).items():
        for name, m in (t.get("minutes_new") or {}).items():
            out[(team, norm(name))] = float(m)
    for p in entry.get("players") or []:
        try:
            out.setdefault((p.get("team"), norm(p["name"])), float(p["minutes"]["mean"]))
        except (KeyError, TypeError, ValueError):
            pass
    return out


def load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def classify_all(snapshots: dict, absences: dict, who: dict, games: set) -> dict:
    """(Tag, game_key) -> (Gruppe, Info, Snapshot-Eintrag) fuer alle Spiele in games."""
    res = {}
    for day, data in snapshots.items():
        for key, e in data["games"].items():
            if (day, key) not in games:
                continue
            hist = ((absences.get("days") or {}).get(day) or {}).get(key, {}).get("history")
            grp, info = classify_game(hist or [], e["start_utc"], who, game_minutes(e))
            res[(day, key)] = (grp, info, e)
    return res


# ----------------------------------------------------------------------------------------------- Kennzahlen
def stats(R: list[dict]) -> dict:
    if not R:
        return {"zeilen": 0, "spieler_tage": 0, "spiele": 0}
    y = np.array([r["hit"] for r in R], float)
    pb = np.array([r["bookmaker"] for r in R]); pr = np.array([r["raw"] for r in R]); pt = np.array([r["team"] for r in R])
    cl = sorted({r["cl"] for r in R})
    out = {"zeilen": len(R), "spieler_tage": len(cl), "spiele": len({(r["day"], r["game"]) for r in R}),
           "brier_betano": float(((pb - y) ** 2).mean()), "brier_roh": float(((pr - y) ** 2).mean()), "brier_team": float(((pt - y) ** 2).mean()),
           "verzerrung_betano": float((pb - y).mean()), "verzerrung_roh": float((pr - y).mean()), "regression": None}
    if len(cl) >= MIN_SPIELER_TAGE_REGRESSION:
        ids = {c: i for i, c in enumerate(cl)}
        g = np.array([ids[r["cl"]] for r in R]); G = len(cl)
        by = [np.nonzero(g == i)[0] for i in range(G)]
        X = np.column_stack([np.ones(len(y)), ive.logit(pb), ive.logit(pr)])
        b, _ = ive.fit_lr(X, y)
        rng = np.random.default_rng(1)
        bs = []
        for _ in range(B_REG):
            ii = np.concatenate([by[c] for c in rng.integers(0, G, G)])
            bs.append(ive.fit_lr(X[ii], y[ii])[0][2])
        out["regression"] = {"b2": float(b[2]), "ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}
    return out


def render(res: dict, classes: dict, rows_info: dict) -> list[str]:
    L = ["Spiele mit grossen Ausfaellen gegen Spiele ohne (UNGEPRÜFT, kleine Stichprobe; nur Beschreibung, keine Empfehlung).",
         f"Grosser Ausfall = laut absences.json (Stand vor Anpfiff) 'fehlt' und erwartete Minuten >= {MIN_MINUTES:.0f}; Gruppe A = mindestens ein Team mit >= {K_GROSS} grossen Ausfaellen, B = alle anderen, unbekannt = kein Stand vor Anpfiff.",
         f"Tage: {', '.join(d[5:] for d in rows_info['tage_ausgewertet'])}. Regeln wie analysis/info_value_test.py (Snapshot vor Anpfiff, Ergebnis vorhanden). Brier: kleiner ist besser; Verzerrung = Chance minus Trefferquote.", ""]
    L.append(f"{'Gruppe':<10}{'Spiele':>7}{'Sp.-Tage':>9}{'Zeilen':>8}{'Brier Betano':>14}{'roh':>8}{'Teamabgl.':>11}{'Verz. Betano':>14}{'Verz. roh':>11}")
    for g in GRUPPEN:
        s = res[g]
        if not s["zeilen"]:
            L.append(f"{g:<10}{0:>7}{0:>9}{0:>8}  (keine Zeilen)")
            continue
        L.append(f"{g:<10}{s['spiele']:>7}{s['spieler_tage']:>9}{s['zeilen']:>8}{s['brier_betano']:>14.4f}{s['brier_roh']:>8.4f}{s['brier_team']:>11.4f}{100 * s['verzerrung_betano']:>+13.1f}P{100 * s['verzerrung_roh']:>+10.1f}P")
    L.append("")
    L.append("Informationswert-Regression roh (b2 = Zusatz des Modells zu Betano; Intervall nach Spieler-Tagen):")
    for g in GRUPPEN:
        s = res[g]
        if not s["zeilen"]:
            L.append(f"  {g}: keine Zeilen")
        elif s["regression"]:
            r = s["regression"]
            L.append(f"  {g}: b2 {r['b2']:+.2f} [{r['ci95'][0]:+.2f}; {r['ci95'][1]:+.2f}] ({'Intervall enthält 0' if r['ci95'][0] <= 0 <= r['ci95'][1] else 'Intervall ohne 0'})")
        else:
            L.append(f"  {g}: zu wenig Daten ({s['spieler_tage']} Spieler-Tage, Schwelle {MIN_SPIELER_TAGE_REGRESSION})")
    L.append("")
    L.append("Spiele der Gruppe A (grosse Ausfaelle je Team):")
    for (day, key), (grp, info, e) in sorted(classes.items()):
        if grp == "A":
            parts = [f"{t} {len(n)} ({', '.join(n)})" for t, n in sorted(info["gross"].items()) if len(n) >= 1]
            L.append(f"  {day} {key.split('|')[3]} @ {key.split('|')[2]}: " + "; ".join(parts))
    unb = [f"{d} {k.split('|')[3]} @ {k.split('|')[2]}" for (d, k), (g, _i, _e) in sorted(classes.items()) if g == "unbekannt"]
    L.append("")
    L.append(f"Gruppe unbekannt (kein Ausfall-Stand vor Anpfiff): {len(unb)} Spiele" + (": " + "; ".join(unb) if unb else "."))
    no_min = sorted({n for (_k), (_g, i, _e) in classes.items() for n in i["ohne_minuten"]})
    no_map = sum(len(i["ohne_zuordnung"]) for (_g, i, _e) in classes.values())
    L.append(f"Hinweis: {len(no_min)} Ausgefallene ohne Minutenwert im Snapshot (zaehlen nicht als gross); {no_map} Ausfall-IDs ohne Name/Team (nicht zuordenbar).")
    return L


def main() -> int:
    rows, info = ive.load_rows()
    games = {(r["day"], r["game"]) for r in rows}
    snaps = ev.load_snapshots(ev.snapshot_dir())
    absences = load_json(ROOT / "data" / "tracking" / "absences.json")
    rosters = load_json(ROOT / "data" / "rosters.json")
    who = people_map(absences, rosters, snaps)
    classes = classify_all(snaps, absences, who, games)
    by = {g: [] for g in GRUPPEN}
    for r in rows:
        by[classes[(r["day"], r["game"])][0]].append(r)
    res = {g: stats(by[g]) for g in GRUPPEN}
    lines = render(res, classes, info)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n(gespeichert: {OUT_TXT.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
