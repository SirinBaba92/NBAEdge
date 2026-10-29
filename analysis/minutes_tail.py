"""Verteilung der Minutenfehler der Starter und Ursachen grosser Minutenverluste (rein beschreibend, ohne Netz).
Liest forecast_players_<Saison>.csv.gz, lineups_<Saison>.csv.gz und das Play-by-Play (Garbage Time G1, Fouls). Schreibt analysis/results/minutes_tail.txt."""
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
EXCLUDE = {"0022400061"}
STARTER_MIN = 28.0
OT_MINUTES = 245.0
BIG = 10.0                                                    # grosser Minutenverlust: mindestens 10 Minuten weniger als erwartet
QS = (1, 5, 10, 25, 50, 75, 90, 95, 99)
Q4_START = 3 * bl.REG_SECONDS                                 # 2160 s
FOULS_MIN = 5


def load_starters(path: Path) -> list[dict]:
    """Starter (erwartete Minuten roh > 28) aus Spielen ohne Verlaengerung und ohne ausgeschlossene Spiele."""
    rows, tot = [], defaultdict(float)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["spiel_id"] in EXCLUDE:
                continue
            try:
                row = {"game": r["spiel_id"], "team": r["team"], "pid": int(r["spieler_id"]), "exp": float(r["minuten_erw_roh"]), "act": float(r["minuten_ist"]),
                       "pts_act": float(r["punkte_ist"]), "pts_exp": float(r["punkte_erw_roh"])}
            except ValueError:
                continue
            tot[(row["game"], row["team"])] += row["act"]
            rows.append(row)
    return [r for r in rows if r["exp"] > STARTER_MIN and tot[(r["game"], r["team"])] <= OT_MINUTES]


def dist_stats(err) -> dict:
    a = np.asarray(err, float)
    n = len(a)
    mu, sd = float(a.mean()), float(a.std(ddof=1))
    z = (a - mu) / a.std(ddof=0)
    return {"n": n, "mean": mu, "median": float(np.median(a)), "sd": sd, "skew": float((z ** 3).mean()),
            "q": {q: float(np.quantile(a, q / 100)) for q in QS}}


def shares(err) -> dict:
    a = np.asarray(err, float); n = len(a)
    return {"<=-5": float((a <= -5).sum() / n), "<=-10": float((a <= -BIG).sum() / n), ">=+5": float((a >= 5).sum() / n), ">=+10": float((a >= 10).sum() / n)}


def normal_tails(err) -> dict:
    """Anteil unter mu - 1.64 sd / mu - 2.33 sd und ueber mu + 1.64 sd / mu + 2.33 sd (sd mit ddof=1)."""
    a = np.asarray(err, float); mu, sd = a.mean(), a.std(ddof=1); n = len(a)
    return {"unter -1.64": float((a < mu - 1.64 * sd).sum() / n), "unter -2.33": float((a < mu - 2.33 * sd).sum() / n),
            "ueber +1.64": float((a > mu + 1.64 * sd).sum() / n), "ueber +2.33": float((a > mu + 2.33 * sd).sum() / n)}


def foul_counts(actions: list[dict]) -> dict:
    """{personId: Zahl der Foul-Ereignisse mit personId} (alle Foul-Unterarten, wie in der Aufgabe)."""
    c = defaultdict(int)
    for a in actions:
        if str(a.get("actionType")) == "foul":
            p = bl.to_int(a.get("personId"))
            if p:
                c[p] += 1
    return c


def last_exit(stints: list) -> dict:
    """{Spieler: Ende (Spielsekunden) seines letzten Stints}."""
    out = {}
    for s in stints:
        for p in s["players"]:
            out[p] = max(out.get(p, 0.0), s["end"])
    return out


def classify_loss(row: dict, has_gt: bool, fouls: int, exit_s) -> dict:
    """Ursachen eines grossen Minutenverlusts (ueberlappend): GT, 5+ Fouls, frueher Abgang (letzter Einsatz endet vor Viertel 4); 'rest' = keine davon; exit_s None = Spieler nicht in den Aufstellungen."""
    early = exit_s is not None and exit_s < Q4_START
    f5 = fouls >= FOULS_MIN
    return {"gt": has_gt, "fouls": f5, "frueh": early, "rest": not (has_gt or f5 or early), "unbekannt": exit_s is None}


def process_season(season: str, pbp_dir: Path) -> dict:
    rows = load_starters(pbp_dir / "derived" / f"forecast_players_{season}.csv.gz")
    lineups = gt.read_lineups(pbp_dir / "derived" / f"lineups_{season}.csv.gz")
    big_games = sorted({r["game"] for r in rows if r["act"] - r["exp"] <= -BIG})
    info, missing = {}, 0
    for g in big_games:
        res = bl.read_pbp(pbp_dir / season / f"{g}.json.gz")
        if res is None:
            missing += 1
            continue
        tl = gt.timeline_and_scoring(res[1])
        info[g] = {"gt": bool(gt.gt_permanent(tl["timeline"], tl["length"], 20)), "fouls": foul_counts(res[1]), "exit": last_exit(lineups.get(g, []))}
    causes = []
    for r in rows:
        r["err"] = r["act"] - r["exp"]
        if r["err"] <= -BIG and r["game"] in info:
            i = info[r["game"]]
            r["cause"] = classify_loss(r, i["gt"], i["fouls"].get(r["pid"], 0), i["exit"].get(r["pid"]))
            causes.append(r)
    return {"rows": rows, "causes": causes, "pbp_fehlt": missing}


def pct(x) -> str:
    return f"{100 * x:.1f} %"


def build_report(res: dict) -> str:
    names = list(res) + ["gesamt"]
    allrows = {n: (res[n]["rows"] if n in res else [r for s in res for r in res[s]["rows"]]) for n in names}
    allc = {n: (res[n]["causes"] if n in res else [r for s in res for r in res[s]["causes"]]) for n in names}
    out = ["Minutenfehler der Starter: Verteilung und Ursachen grosser Verluste (beschreibend, keine Bewertung)",
           f"Starter: erwartete Minuten roh > {STARTER_MIN:.0f}. Fehler = tatsaechliche minus erwartete Minuten. Ohne Verlaengerungsspiele (Teamsumme > 245) und ohne Spiel 0022400061.",
           "Spieler ohne Einsatz stehen nicht in den Dateien (tatsaechliche Minuten > 0 vorausgesetzt) - Fehler von -erwartet Minuten fehlen daher; die Verteilung ist am unteren Rand abgeschnitten.", ""]
    st = {n: dist_stats([r["err"] for r in allrows[n]]) for n in names}
    out.append("1. Verteilung des Fehlers (Minuten)")
    out.append("  " + "".ljust(12) + "".join(n.rjust(10) for n in names))
    for key, lab in (("n", "Anzahl"), ("mean", "Mittel"), ("median", "Median"), ("sd", "Streuung"), ("skew", "Schiefe")):
        out.append("  " + lab.ljust(12) + "".join((f"{st[n][key]:>10d}" if key == "n" else f"{st[n][key]:>10.2f}") for n in names))
    for q in QS:
        out.append("  " + f"Quantil {q}%".ljust(12) + "".join(f"{st[n]['q'][q]:>10.2f}" for n in names))
    out += ["", "2. Anteile der Starter", "  " + "".ljust(26) + "".join(n.rjust(10) for n in names)]
    sh = {n: shares([r["err"] for r in allrows[n]]) for n in names}
    for k, lab in (("<=-5", "mind. 5 Min. weniger"), ("<=-10", "mind. 10 Min. weniger"), (">=+5", "mind. 5 Min. mehr"), (">=+10", "mind. 10 Min. mehr")):
        out.append("  " + lab.ljust(26) + "".join(pct(sh[n][k]).rjust(10) for n in names))
    out += ["", "3. Vergleich mit Normalverteilung gleichen Mittels und gleicher Streuung (Normalverteilung: 5,0 % / 1,0 %)", "  " + "".ljust(26) + "".join(n.rjust(10) for n in names)]
    nt = {n: normal_tails([r["err"] for r in allrows[n]]) for n in names}
    for k in ("unter -1.64", "unter -2.33", "ueber +1.64", "ueber +2.33"):
        out.append("  " + (k + " Std.abw.").ljust(26) + "".join(pct(nt[n][k]).rjust(10) for n in names))
    out += ["", f"4. Ursachen grosser Minutenverluste (mind. {BIG:.0f} Min. weniger als erwartet); Ursachen ueberlappen, 'Rest' = keine der drei",
            "  GT = Spiel mit Garbage Time G1; Fouls = mind. 5 Foul-Ereignisse mit personId im Spiel (alle Foul-Arten); frueh = letzter Einsatz endet vor Beginn von Viertel 4", "  " + "".ljust(26) + "".join(n.rjust(10) for n in names)]
    out.append("  " + "Anzahl grosser Verluste".ljust(26) + "".join(str(len(allc[n])).rjust(10) for n in names))
    for k, lab in (("gt", "in Spiel mit GT G1"), ("fouls", "mind. 5 Fouls"), ("frueh", "frueher Abgang"), ("rest", "Rest"), ("unbekannt", "nicht in Aufstellungen")):
        out.append("  " + lab.ljust(26) + "".join((pct(sum(r["cause"][k] for r in allc[n]) / len(allc[n])) if allc[n] else "-").rjust(10) for n in names))
    out += ["", "5. Punkte der Starter, roh: mittlere tatsaechliche gegen erwartete Punkte", "  " + "".ljust(34) + "".join(n.rjust(20) for n in names)]
    for lab, sel in (("mit grossem Minutenverlust", lambda r: r["err"] <= -BIG), ("ohne grossen Minutenverlust", lambda r: r["err"] > -BIG)):
        cells = []
        for n in names:
            sub = [r for r in allrows[n] if sel(r)]
            cells.append(f"{np.mean([r['pts_act'] for r in sub]):.1f}/{np.mean([r['pts_exp'] for r in sub]):.1f} (n={len(sub)})" if sub else "-")
        out.append("  " + lab.ljust(34) + "".join(c.rjust(20) for c in cells))
    out.append("  (Format: tatsaechlich/erwartet)")
    out += ["", "Hinweise:"] + [f"  {s}: {res[s]['pbp_fehlt']} Spiele mit grossem Verlust ohne lesbares Play-by-Play (dort keine Ursache)." for s in res]
    return "\n".join(out) + "\n"


def run(pbp_dir: Path, seasons=SEASONS, write=print) -> str:
    res = {}
    for s in seasons:
        res[s] = process_season(s, pbp_dir)
        write(f"{s}: {len(res[s]['rows'])} Starter, {len(res[s]['causes'])} mit grossem Verlust")
    return build_report(res)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--out", default=str(ROOT / "analysis" / "results" / "minutes_tail.txt"))
    args = ap.parse_args(argv)
    text = run(Path(args.pbp_dir))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
