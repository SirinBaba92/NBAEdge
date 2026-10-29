"""Minutenfehler der Spieler gegen den erwarteten Abstand (rein beschreibend, ohne Netz).
Liest forecast_players_<Saison>.csv.gz (Minuten roh, Minuten tatsaechlich, tspread aus Sicht des Spielerteams) und die Play-by-Play-Dateien (Garbage Time G1 je Spiel). Schreibt analysis/results/minutes_vs_spread.txt."""
import argparse, csv, gzip, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis import build_lineups as bl                      # noqa: E402
from analysis import garbage_time as gt                       # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
EXCLUDE = {"0022400061"}                                      # Play-by-Play unvollstaendig
STARTER_MIN = 28.0                                            # wie analysis/backtest_thresholds.py (Basis-Minuten > 28)
BENCH_MIN = 12.0
OT_MINUTES = 245.0
EDGES = (0.0, 3.0, 6.0, 9.0, 12.0, 15.0, np.inf)
LABELS = ("0-3", "3-6", "6-9", "9-12", "12-15", ">15")
CS = (6.0, 8.0, 10.0)


def bin_of(x: float) -> int:
    for i in range(len(LABELS)):
        if EDGES[i] <= x < EDGES[i + 1]:
            return i
    return len(LABELS) - 1


def load_players(path: Path) -> list[dict]:
    """Zeilen mit Fehler, |tspread|, Seite; ohne ausgeschlossene Spiele und ohne fehlende Werte."""
    out = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["spiel_id"] in EXCLUDE:
                continue
            try:
                e, a, ts = float(r["minuten_erw_roh"]), float(r["minuten_ist"]), float(r["tspread"])
            except ValueError:
                continue
            out.append({"game": r["spiel_id"], "team": r["team"], "exp": e, "act": a, "ts": ts})
    return out


def mark_ot(rows: list[dict]) -> None:
    """Setzt row['ot'] = Summe der tatsaechlichen Minuten des Teams im Spiel > 245."""
    tot = defaultdict(float)
    for r in rows:
        tot[(r["game"], r["team"])] += r["act"]
    for r in rows:
        r["ot"] = tot[(r["game"], r["team"])] > OT_MINUTES


def side_of(ts: float) -> str:
    return "Favorit" if ts > 0 else ("Aussenseiter" if ts < 0 else "gleich")


def error_table(rows: list[dict], role: str) -> dict:
    """{(Seite, Stufe): [Fehler]} fuer role 'starter' (erw > 28) oder 'bank' (12 < erw <= 28)."""
    out = defaultdict(list)
    for r in rows:
        if role == "starter" and not r["exp"] > STARTER_MIN:
            continue
        if role == "bank" and not (BENCH_MIN < r["exp"] <= STARTER_MIN):
            continue
        out[(side_of(r["ts"]), bin_of(abs(r["ts"])))].append(r["act"] - r["exp"])
    return out


def stats(v: list) -> tuple:
    a = np.asarray(v, float)
    return (len(a), float(a.mean()) if len(a) else float("nan"), float(a.std(ddof=1)) if len(a) > 1 else float("nan"))


def gt_share(games: dict) -> dict:
    """games: {spiel_id: (|tspread|, hat_gt)} -> {Stufe: (Spiele, mit GT)}."""
    out = defaultdict(lambda: [0, 0])
    for ats, has in games.values():
        b = out[bin_of(ats)]
        b[0] += 1; b[1] += bool(has)
    return out


def fit_line(rows: list[dict], c: float) -> tuple:
    """Fehler = a + b * max(0, |ts| - c) per kleinste Quadrate -> (a, b)."""
    x = np.array([max(0.0, abs(r["ts"]) - c) for r in rows]); y = np.array([r["act"] - r["exp"] for r in rows])
    A = np.column_stack([np.ones(len(x)), x])
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(a), float(b)


def test_metrics(rows: list[dict], a: float, b: float, c: float) -> dict:
    y = np.array([r["act"] - r["exp"] for r in rows]); x = np.array([max(0.0, abs(r["ts"]) - c) for r in rows])
    res = y - (a + b * x)
    return {"n": len(y), "bias0": float(y.mean()), "mae0": float(np.abs(y).mean()), "bias1": float(res.mean()), "mae1": float(np.abs(res).mean())}


def cross_fit(by_season: dict) -> list[dict]:
    """Alle Kombinationen zwei Saisons anpassen, dritte testen, je c."""
    out = []
    for test in by_season:
        train = [r for s, rs in by_season.items() if s != test for r in rs]
        for c in CS:
            a, b = fit_line(train, c)
            out.append({"test": test, "c": c, "a": a, "b": b, **test_metrics(by_season[test], a, b, c)})
    return out


def game_gt_flag(pbp_dir: Path, season: str, gid: str):
    res = bl.read_pbp(pbp_dir / season / f"{gid}.json.gz")
    if res is None:
        return None
    info = gt.timeline_and_scoring(res[1])
    return bool(gt.gt_permanent(info["timeline"], info["length"], 20))


# ----------------------------------------------------------------------------- Ausgabe
def f(x, d=2):
    return "-" if x != x else f"{x:.{d}f}"


def table_lines(title: str, per_season: dict) -> list[str]:
    """per_season: {Name: {(Seite, Stufe): [Fehler]}}"""
    lines = [title, "  Fehler = tatsaechliche minus erwartete Minuten (roh); Mittel / Streuung / Anzahl"]
    names = list(per_season)
    lines.append("  " + "Seite".ljust(13) + "Stufe".ljust(7) + "".join(n.ljust(26) for n in names))
    for side in ("Favorit", "Aussenseiter", "gleich"):
        for b, lab in enumerate(LABELS):
            cells = [stats(per_season[n].get((side, b), [])) for n in names]
            if not any(c[0] for c in cells):
                continue
            lines.append("  " + side.ljust(13) + lab.ljust(7) + "".join(f"{f(m)} / {f(s)} / {n}".ljust(26) for n, m, s in cells))
    return lines


def build_report(data: dict, gtg: dict, notes: list[str]) -> str:
    """data: {Saison: Zeilen (mit 'ot')}; gtg: {Saison: {spiel_id: (|ts|, GT)}}."""
    seasons = list(data)
    allrows = {s: data[s] for s in seasons}
    pooled = [r for s in seasons for r in data[s]]
    out = ["Minuten gegen erwarteten Abstand (beschreibend, keine Bewertung)",
           f"Fehler = tatsaechliche minus erwartete Minuten roh. Starter: erwartete Minuten > {STARTER_MIN:.0f}; Bank: > {BENCH_MIN:.0f} bis {STARTER_MIN:.0f}.",
           "|tspread| = erwarteter Abstand des Spielerteams (Favorit: tspread > 0). Verlaengerung: Summe der Spielerminuten des Teams > 245. Spiel 0022400061 ausgeschlossen.",
           "In den Dateien stehen nur Spieler mit mehr als 0 tatsaechlichen Minuten.", ""]
    for ot_flag, ot_name in ((False, "OHNE Verlaengerung"), (True, "NUR Verlaengerung (nicht in der Anpassung)")):
        for role, rname in (("starter", "Starter"), ("bank", "Nicht-Starter mit erwarteten Minuten > 12")):
            per = {s: error_table([r for r in data[s] if r["ot"] == ot_flag], role) for s in seasons}
            merged = defaultdict(list)
            for p in per.values():
                for k, v in p.items():
                    merged[k] += v
            per["gesamt"] = merged
            out += table_lines(f"{rname}, {ot_name}", per) + [""]
    out.append("Anteil der Spiele mit Garbage Time G1 (dauerhaft >= 20 Punkte ab Periode 3), nach |tspread| des Spiels")
    out.append("  Stufe".ljust(9) + "".join(s.ljust(18) for s in seasons) + "gesamt")
    shares = {s: gt_share(gtg[s]) for s in seasons}
    tot = gt_share({f"{s}{g}": v for s in seasons for g, v in gtg[s].items()})
    for b, lab in enumerate(LABELS):
        def cell(sh):
            n, k = sh.get(b, [0, 0])
            return f"{k}/{n} = {100 * k / n:.1f} %" if n else "-"
        out.append("  " + lab.ljust(7) + "".join(cell(shares[s]).ljust(18) for s in seasons) + cell(tot))
    out.append("")
    out.append("Einfaches Modell (Starter, ohne Verlaengerung): Fehler = a + b * max(0, |tspread| - c). Anpassung auf zwei Saisons, Test auf der dritten.")
    out.append("  Test-Spalten: Verzerrung = mittlerer Fehler, MAE = mittlerer absoluter Fehler; 'ohne' = ohne Korrektur, 'mit' = nach Abzug a + b*x.")
    by_season = {s: [r for r in data[s] if not r["ot"] and r["exp"] > STARTER_MIN] for s in seasons}
    if len(seasons) >= 3:
        out.append("  Test-Saison  c    a        b         n      Verzerrung ohne/mit   MAE ohne/mit")
        for r in cross_fit(by_season):
            out.append(f"  {r['test']:<12} {r['c']:<4.0f} {r['a']:+.3f}  {r['b']:+.4f}  {r['n']:<6} {r['bias0']:+.3f} / {r['bias1']:+.3f}     {r['mae0']:.3f} / {r['mae1']:.3f}")
        for c in CS:
            bs = [r["b"] for r in cross_fit(by_season) if r["c"] == c]
            out.append(f"  c = {c:.0f}: b je Anpassung = " + ", ".join(f"{b:+.4f}" for b in bs) + ("  (gleiches Vorzeichen)" if all(b > 0 for b in bs) or all(b < 0 for b in bs) else "  (Vorzeichen unterschiedlich)"))
    else:
        out.append("  weniger als 3 Saisons - keine Kreuzanpassung")
    if notes:
        out += ["", "Hinweise:"] + ["  " + n for n in notes]
    return "\n".join(out) + "\n"


def run(pbp_dir: Path, seasons=SEASONS, write=print) -> str:
    data, gtg, notes = {}, {}, []
    for s in seasons:
        rows = load_players(pbp_dir / "derived" / f"forecast_players_{s}.csv.gz")
        mark_ot(rows)
        data[s] = rows
        games = {}
        for r in rows:
            games.setdefault(r["game"], abs(r["ts"]))
        flags, missing = {}, 0
        for g, ats in games.items():
            fl = game_gt_flag(pbp_dir, s, g)
            if fl is None:
                missing += 1
            else:
                flags[g] = (ats, fl)
        gtg[s] = flags
        notes.append(f"{s}: {len(games)} Spiele in der Prognosedatei, davon {missing} ohne lesbares Play-by-Play (nicht im Garbage-Anteil).")
        write(notes[-1])
    return build_report(data, gtg, notes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--out", default=str(ROOT / "analysis" / "results" / "minutes_vs_spread.txt"))
    args = ap.parse_args(argv)
    text = run(Path(args.pbp_dir))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
