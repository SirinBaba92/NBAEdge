"""
Garbage Time (Spiele mit grossem Rueckstand) beschreiben. NEU, rein beschreibend, kein Netz, aendert keine Projektdatei.

Eingabe:  <pbp-dir>/derived/lineups_<Saison>.csv.gz (analysis/build_lineups.py: Stints), das Play-by-Play <pbp-dir>/<Saison>/<spiel_id>.json.gz (Spielstand und Wuerfe mit Zeit)
          und die lokalen Minuten je Spieler und Spiel (data/cache, wie in analysis/build_lineups.py).
          Der Spielstand zu jeder Sekunde kommt aus dem Play-by-Play (die Stints kennen den Abstand nur an ihren Grenzen); Starter, Minuten in der Garbage Time und Minuten je Spiel
          kommen aus den Stints bzw. den lokalen Minuten. Starter je Spiel = die fuenf Spieler von Stint 1 jedes Teams.
Ausgabe:  analysis/results/garbage_time_<Saison>.txt und garbage_time_gesamt.txt (alle Saisons, deren Summen in <pbp-dir>/derived/garbage_<Saison>.json liegen).

Varianten (Abstand = Betrag des Punkteabstands; Spielsekunden: Periode 1-4 je 720 s, Verlaengerung je 300 s)
  G1: Beginn in der ersten Sekunde ab Periode 3 (ab 1440 s), ab der der Abstand bis zum Spielende dauerhaft mindestens 20 Punkte betraegt; Ende = Spielende.
  G2: wie G1 mit mindestens 15 Punkten.
  G3: Abstand mindestens 20 Punkte UND hoechstens 6 Minuten Restzeit im 4. Viertel (2520 bis 2880 s), unabhaengig vom spaeteren Verlauf (kann mehrere Abschnitte ergeben).
Rollen: "fuehrend" = das Team mit den Punkten vorn waehrend des Abschnitts, "zurueckliegend" = das andere.
Start:  venv/bin/python analysis/garbage_time.py --seasons 2023-24
Spaeter (wenn lineups_<Saison>.csv.gz fuer alle Saisons existiert):  venv/bin/python analysis/garbage_time.py
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis import build_lineups as bl                      # noqa: E402  (Zeit, Ereignisse, lokale Minuten; nur lesend genutzt)

HOME = Path.home()
SEASONS = bl.SEASONS
VARIANTS = ("G1", "G2", "G3")
P3_START = 2 * bl.REG_SECONDS                                  # 1440 s
Q4_LAST6 = (bl.period_end(4) - 6 * 60.0, bl.period_end(4))     # 2520 .. 2880 s
SPEC = {"G1": "dauerhaft >= 20 Punkte ab Periode 3", "G2": "dauerhaft >= 15 Punkte ab Periode 3", "G3": ">= 20 Punkte in den letzten 6 Minuten von Viertel 4 (unabhaengig vom Verlauf)"}


# ----------------------------------------------------------------------------- Spielstand und Wuerfe aus dem Play-by-Play
def timeline_and_scoring(actions: list[dict]) -> dict:
    """{'timeline': [(t, heim, gast)] ab (0, 0, 0), 'length': Spielsekunden, 'scoring': [(t, pid, Punkte)], 'home_tri', 'away_tri'}. Stand nur nach oben (wie build_lineups)."""
    ev = bl.parse_events(actions)
    home_tid = bl.infer_home(ev)
    tri = {}
    for e in ev:
        if e["tid"] and e["tri"]:
            tri.setdefault(e["tid"], e["tri"])
    away_tid = next((t for t in tri if t != home_tid), None)
    tl, cur, scoring, max_p = [(0.0, 0, 0)], (0, 0), [], 1
    for e in ev:
        max_p = max(max_p, e["period"])
        if e["score"] is not None and e["score"][0] >= cur[0] and e["score"][1] >= cur[1] and e["score"] != cur:
            cur = e["score"]
            tl.append((e["t"], cur[0], cur[1]))
        res = str(e["a"].get("shotResult") or "")
        if res == "Made" and e["pid"] > 0:
            pts = {"2pt": 2, "3pt": 3, "freethrow": 1}.get(e["type"])
            if pts:
                scoring.append((e["t"], e["pid"], pts))
    return {"timeline": tl, "length": bl.game_length(max_p), "scoring": scoring, "home_tri": tri.get(home_tid), "away_tri": tri.get(away_tid)}


# ----------------------------------------------------------------------------- Abschnitte der Garbage Time
def gt_permanent(tl: list, length: float, k: float, t_min: float = P3_START) -> list:
    """G1/G2: [(start, ende, fuehrend 'home'|'away')] mit einem Abschnitt oder leer. Beginn = erste Sekunde ab t_min, ab der der Abstand bis zum Spielende immer >= k ist."""
    start = None
    for t, h, a in tl:
        if abs(h - a) >= k:
            if start is None:
                start = t
        else:
            start = None
    if start is None:
        return []
    h, a = tl[-1][1], tl[-1][2]
    s = max(start, t_min)
    return [(s, length, "home" if h > a else "away")] if s < length else []


def gt_window(tl: list, length: float, k: float, window: tuple = Q4_LAST6) -> list:
    """G3: Abschnitte innerhalb des Zeitfensters, in denen der Abstand >= k ist (nach Fuehrungsseite getrennt): [(start, ende, 'home'|'away')]."""
    out = []
    for i, (t, h, a) in enumerate(tl):
        end = tl[i + 1][0] if i + 1 < len(tl) else length
        s, e = max(t, window[0]), min(end, window[1])
        if e > s and abs(h - a) >= k:
            side = "home" if h > a else "away"
            if out and out[-1][2] == side and abs(out[-1][1] - s) < 1e-9:
                out[-1] = (out[-1][0], e, side)
            else:
                out.append((s, e, side))
    return out


def intervals(tl: list, length: float) -> dict:
    return {"G1": gt_permanent(tl, length, 20), "G2": gt_permanent(tl, length, 15), "G3": gt_window(tl, length, 20)}


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


# ----------------------------------------------------------------------------- ein Spiel
def new_acc() -> dict:
    z = lambda: {"n": 0, "sum": 0.0}
    return {v: {"spiele": 0, "spiele_gt": 0, "dauer_min": 0.0,
                "st_gt_min": {"fuehrend": 0.0, "zurueck": 0.0}, "st_alle_min": {"fuehrend": 0.0, "zurueck": 0.0},
                "st_mit": z(), "st_ohne": z(), "ns_mit": z(), "ns_ohne": z(),
                "pkt_in": 0, "min_in": 0.0, "pkt_out": 0, "min_out": 0.0, "pkt_nogt": 0, "min_nogt": 0.0} for v in VARIANTS}


def analyze_game(acc: dict, stints: list, info: dict, local: dict | None) -> None:
    """Ein Spiel in die Summen einrechnen. stints: [{'team', 'nr', 'start', 'end', 'players'}]; info: timeline_and_scoring; local: {pid: Minuten} oder None."""
    starters = {}                                                   # Team -> Starter (Stint 1)
    for s in stints:
        if s["nr"] == 1:
            starters[s["team"]] = set(s["players"])
    all_starters = set().union(*starters.values()) if starters else set()
    mins_stint = defaultdict(float)
    for s in stints:
        for p in s["players"]:
            mins_stint[p] += (s["end"] - s["start"]) / 60.0
    mins = {p: m for p, m in (local or {}).items() if m > 0} or dict(mins_stint)
    iv = intervals(info["timeline"], info["length"])
    team_side = {info["home_tri"]: "home", info["away_tri"]: "away"}
    for v in VARIANTS:
        a = acc[v]
        a["spiele"] += 1
        dur = sum(e - s for s, e, _ in iv[v]) / 60.0
        has = dur > 0
        a["spiele_gt"] += has
        a["dauer_min"] += dur
        st_m = [mins.get(p, 0.0) for p in all_starters if mins.get(p, 0.0) > 0]
        ns_m = [m for p, m in mins.items() if p not in all_starters and m > 0]
        for key, vals in (("st", st_m), ("ns", ns_m)):
            b = a[f"{key}_{'mit' if has else 'ohne'}"]
            b["n"] += len(vals); b["sum"] += sum(vals)
        gt_min_starters = 0.0
        if has:
            for s in stints:
                n_st = sum(1 for p in s["players"] if p in starters.get(s["team"], ()))
                side = team_side.get(s["team"])
                total = (s["end"] - s["start"]) / 60.0 * n_st
                for x0, x1, lead in iv[v]:
                    role = "fuehrend" if side == lead else "zurueck"
                    a["st_gt_min"][role] += overlap(s["start"], s["end"], x0, x1) / 60.0 * n_st
                    gt_min_starters += overlap(s["start"], s["end"], x0, x1) / 60.0 * n_st
                final_lead = iv[v][0][2]
                a["st_alle_min"]["fuehrend" if side == final_lead else "zurueck"] += total
        if v == "G1":                                               # Punkte je Minute der Starter (nur G1)
            starter_min_total = sum(((s["end"] - s["start"]) / 60.0) * sum(1 for p in s["players"] if p in starters.get(s["team"], ())) for s in stints)
            pts_in = sum(pt for t, pid, pt in info["scoring"] if pid in all_starters and any(x0 <= t <= x1 for x0, x1, _ in iv[v]))
            pts_all = sum(pt for t, pid, pt in info["scoring"] if pid in all_starters)
            if has:
                a["pkt_in"] += pts_in; a["min_in"] += gt_min_starters
                a["pkt_out"] += pts_all - pts_in; a["min_out"] += starter_min_total - gt_min_starters
            else:
                a["pkt_nogt"] += pts_all; a["min_nogt"] += starter_min_total


def merge_acc(a: dict, b: dict) -> dict:
    out = new_acc()
    for src in (a, b):
        for v in VARIANTS:
            for k, val in src[v].items():
                if isinstance(val, dict):
                    for kk, vv in val.items():
                        out[v][k][kk] += vv
                else:
                    out[v][k] += val
    return out


# ----------------------------------------------------------------------------- Auswertung als Text
def mean(s: float, n: float) -> str:
    return "-" if not n else f"{s / n:.1f}"


def ratio(x: float, y: float) -> str:
    return "-" if not y else f"{x / y:.3f}"


def pct(x: float, y: float) -> str:
    return "-" if not y else f"{100 * x / y:.1f} %"


def text_for(title: str, acc: dict, ppm: bool = True) -> list[str]:
    lines = [f"=== {title} ===", ""]
    for v in VARIANTS:
        a = acc[v]
        lines += [f"{v}: {SPEC[v]}",
                  f"  Spiele mit Garbage Time: {a['spiele_gt']} von {a['spiele']} ({pct(a['spiele_gt'], a['spiele'])}); mittlere Dauer in diesen Spielen: {mean(a['dauer_min'], a['spiele_gt'])} Min",
                  f"  Anteil der Starter-Minuten, die in der Garbage Time anfallen (in Spielen mit Garbage Time; Minuten der Starter des fuehrenden bzw. zurueckliegenden Teams): "
                  f"fuehrend {pct(a['st_gt_min']['fuehrend'], a['st_alle_min']['fuehrend'])}, zurueckliegend {pct(a['st_gt_min']['zurueck'], a['st_alle_min']['zurueck'])}",
                  f"  Mittlere Minuten eines Starters: mit Garbage Time {mean(a['st_mit']['sum'], a['st_mit']['n'])} (n = {int(a['st_mit']['n'])}), ohne {mean(a['st_ohne']['sum'], a['st_ohne']['n'])} (n = {int(a['st_ohne']['n'])})",
                  f"  Mittlere Minuten eines Nicht-Starters (nur Spieler mit Einsatz): mit Garbage Time {mean(a['ns_mit']['sum'], a['ns_mit']['n'])} (n = {int(a['ns_mit']['n'])}), ohne {mean(a['ns_ohne']['sum'], a['ns_ohne']['n'])} (n = {int(a['ns_ohne']['n'])})"]
        if v == "G1" and ppm:
            lines += [f"  Punkte pro Minute der Starter (nur G1; Punkte aus Wurf- und Freiwurf-Ereignissen): in der Garbage Time {ratio(a['pkt_in'], a['min_in'])} ({a['pkt_in']} Pkt in {a['min_in']:.0f} Starter-Min), "
                      f"ausserhalb in denselben Spielen {ratio(a['pkt_out'], a['min_out'])} ({a['pkt_out']} Pkt in {a['min_out']:.0f} Min), in Spielen ohne Garbage Time {ratio(a['pkt_nogt'], a['min_nogt'])} ({a['pkt_nogt']} Pkt in {a['min_nogt']:.0f} Min)"]
        lines.append("")
    return lines


# ----------------------------------------------------------------------------- Saison
def read_lineups(path: Path) -> dict:
    """{spiel_id: [Stint-Dict]} aus lineups_<Saison>.csv.gz."""
    out = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out[r["spiel_id"]].append({"team": r["team"], "nr": int(r["stint_nr"]), "start": float(r["start_s"]), "end": float(r["ende_s"]), "players": [int(r[f"spieler{i}"]) for i in range(1, 6)]})
    return out


def run_season(season: str, pbp_dir: Path, cache_dir: Path | None = None, limit: int | None = None, write=print) -> dict:
    lineups = read_lineups(pbp_dir / "derived" / f"lineups_{season}.csv.gz")
    local = bl.load_local(season, cache_dir)
    acc, skipped = new_acc(), 0
    for i, gid in enumerate(sorted(lineups)):
        if limit is not None and i >= limit:
            break
        res = bl.read_pbp(pbp_dir / season / f"{gid}.json.gz")
        if res is None:
            skipped += 1
            continue
        analyze_game(acc, lineups[gid], timeline_and_scoring(res[1]), (local.get(gid) or {}).get("minutes"))
        if (i + 1) % 300 == 0:
            write(f"{season}: {i + 1} Spiele")
    return {"season": season, "acc": acc, "uebersprungen": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--seasons", nargs="+", default=list(SEASONS), choices=list(SEASONS))
    ap.add_argument("--results-dir", default=str(ROOT / "analysis" / "results"))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    pbp, res_dir = Path(args.pbp_dir), Path(args.results_dir)
    res_dir.mkdir(parents=True, exist_ok=True)
    for s in args.seasons:
        if not (pbp / "derived" / f"lineups_{s}.csv.gz").exists():
            print(f"{s}: lineups_{s}.csv.gz fehlt - uebersprungen (zuerst analysis/build_lineups.py --seasons {s})")
            continue
        r = run_season(s, pbp, limit=args.limit)
        (pbp / "derived" / f"garbage_{s}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        head = f"Garbage Time {s}: {r['acc']['G1']['spiele']} Spiele ausgewertet, {r['uebersprungen']} Dateien uebersprungen (unlesbar)."
        (res_dir / f"garbage_time_{s}.txt").write_text("\n".join([head, ""] + text_for(s, r["acc"])) + "\n", encoding="utf-8")
        print(head)
    found = [json.loads((pbp / "derived" / f"garbage_{s}.json").read_text(encoding="utf-8")) for s in SEASONS if (pbp / "derived" / f"garbage_{s}.json").exists()]
    if found:
        tot = found[0]["acc"]
        for r in found[1:]:
            tot = merge_acc(tot, r["acc"])
        (res_dir / "garbage_time_gesamt.txt").write_text("\n".join(text_for("gesamt (" + ", ".join(r["season"] for r in found) + ")", tot)) + "\n", encoding="utf-8")
        print((res_dir / "garbage_time_gesamt.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
