"""
Experiment: empirische, schiefe Minutenverteilung der Starter (Variante E) gegen die heutige Normalverteilung (Roh) bei den Meilenstein-Chancen der Spielerpunkte. NUR LESEND, kein Netz,
engine/player_forecast.py und alle bestehenden Dateien bleiben unveraendert (die Rechnung steht im Speicher dieses Skripts). Schreibt analysis/results/minutes_empirical.txt.

Aufruf (aus dem Projektordner):
  venv/bin/python analysis/backtest_minutes_empirical.py            Replay 2023-24 (falls noch nicht vorhanden) + Auswertung
  venv/bin/python analysis/backtest_minutes_empirical.py --replay-only   nur den Replay 2023-24 rechnen und ablegen

Daten
- Prognose-Bausteine je Spielerzeile (ppm je Spiel, Gewichte, 9 Minutenpunkte, erwartete Minuten roh, Minuten/Punkte tatsaechlich): 2024-25 und 2025-26 aus dem gesicherten Zwischenstand von
  analysis/backtest_player_calibration.py (<pbp-dir>/derived/spielerprognosen_roh/pcal, nur gelesen); 2023-24 wird mit demselben Replay (run_season der Kalibrierung, Verlauf nur vor dem Spieltag) neu gerechnet
  und im Temp-Ordner abgelegt.
- Trainingsfehler der Starter (tatsaechliche minus erwartete Minuten roh): forecast_players_<Saison>.csv.gz, ohne Verlaengerungsspiele (Teamsumme > 245) und ohne Spiel 0022400061 (analysis/minutes_tail.py).
Varianten (nur Starter = erwartete Minuten roh > 28; Nicht-Starter bleiben unveraendert)
- Roh:  9 Minutenpunkte = mu + sd0 * z_i (Normalverteilung des Spielers, wie heute).
- E:    9 Minutenpunkte = mu + (q_i - mittel(q)), q_i = Quantil (i - 0,5) / 9 der Starter-Fehler der zwei Trainingssaisons; die Verschiebung sorgt dafuer, dass das Mittel der 9 Punkte genau mu ist (vor der Begrenzung);
  danach auf 0..48 begrenzt. Der Rest der Rechnung (ppm, Gewichte, Glaettung h = 1 + 0,05 x) ist unveraendert. Gleiche Gruppengroesse je Punkt (je 1/9) wie im Produktivmodell.
- N (Zusatz-Kontrolle): wie E, aber mit den 9 Quantilen einer Normalverteilung mit Mittel 0 und der gemeinsamen Streuung der Trainingsfehler (trennt Form von Breite).
"""
import argparse
import sys
import tempfile
import time
import warnings
from pathlib import Path

import numpy as np
from scipy.special import ndtr, ndtri

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from analysis import minutes_tail as mt  # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
MINUTE_POINTS = 9
MAX_MINUTES = 48.0
STARTER_MIN = 28.0
KS_ALL = np.arange(1, 61)
SCOPES = {"k=1..60": (1, 60), "k=5..40": (5, 40)}
LEVELS = (0.50, 0.65, 0.80)
VARIANTS = ("Roh", "E", "N")
EPS = 1e-6
OUT = HERE / "results" / "minutes_empirical.txt"
EXCLUDED_GAME = "0022400061"


# ----------------------------------------------------------------------------- Kern (rein, getestet)
def quantile_offsets(errors) -> np.ndarray:
    """9 Verschiebungen: Quantile (i - 0,5)/9 der Fehler, minus ihr Mittel (Mittel der Punkte bleibt mu)."""
    q = np.quantile(np.asarray(errors, float), (np.arange(MINUTE_POINTS) + 0.5) / MINUTE_POINTS)
    return q - q.mean()


def normal_offsets(errors) -> np.ndarray:
    return float(np.std(np.asarray(errors, float), ddof=1)) * ndtri((np.arange(MINUTE_POINTS) + 0.5) / MINUTE_POINTS)


def minute_points(mu: float, offsets: np.ndarray) -> np.ndarray:
    return np.clip(mu + offsets, 0.0, MAX_MINUTES)


def milestone_probs(ppm: np.ndarray, w_p: np.ndarray, m_k: np.ndarray, ns: np.ndarray) -> np.ndarray:
    """P(Punkte >= n) wie engine/player_forecast.forecast_player (Normalglaettung h = 1 + 0,05 x, nicht steigend in n)."""
    x = (ppm[:, None] * m_k[None, :]).ravel()
    w = (w_p[:, None] * np.full(len(m_k), 1.0 / len(m_k))[None, :]).ravel()
    h = 1.0 + 0.05 * x
    p = (w[None, :] * (1.0 - ndtr((ns[:, None] - 0.5 - x[None, :]) / h[None, :]))).sum(axis=1)
    return np.minimum.accumulate(np.clip(p, 0.0, 1.0))


def metrics(p: np.ndarray, hit: np.ndarray) -> dict:
    if len(p) == 0:
        return {"n": 0}
    pc = np.clip(p, EPS, 1 - EPS)
    return {"n": len(p), "brier": float(np.mean((p - hit) ** 2)), "ll": float(-np.mean(hit * np.log(pc) + (1 - hit) * np.log(1 - pc))), "bias": float(p.mean() - hit.mean())}


def calibration(p: np.ndarray, hit: np.ndarray, level: float) -> tuple:
    m = p >= level
    n = int(m.sum())
    return (n, float(p[m].mean()), float(hit[m].mean())) if n else (0, float("nan"), float("nan"))


# ----------------------------------------------------------------------------- Daten
def replay_dir(tmp: Path) -> Path:
    return tmp / "pcal"


def rows_path(season: str, pbp: Path, tmp: Path) -> Path:
    if season == "2023-24":
        return replay_dir(tmp) / "rows_2023-24.npz"
    return pbp / "derived" / "spielerprognosen_roh" / "pcal" / f"rows_{season}.npz"


def replay_2023(tmp: Path) -> None:
    """Neuer Replay 2023-24 mit den vorhandenen Funktionen (nur im Speicher umgeleitet)."""
    import backtest_player_calibration as bpc
    import backtest_player_markets as bpm
    replay_dir(tmp).mkdir(parents=True, exist_ok=True)
    bpm.EVAL = {**bpm.EVAL, "2023-24": 2023}
    bpc.TMP = replay_dir(tmp)
    t0 = time.time()
    res = bpc.run_season("2023-24")
    print(f"Replay 2023-24 fertig: {res[1]} Zeilen, {res[2]} Spiele, max. Abweichung Kern {res[3]:.1e}, {time.time() - t0:.0f} s", flush=True)


def excluded_pairs(pbp: Path, season: str) -> set:
    """(Datum als int, Spieler-ID) des ausgeschlossenen Spiels, falls in dieser Saison."""
    import csv, gzip
    out = set()
    with gzip.open(pbp / "derived" / f"forecast_players_{season}.csv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["spiel_id"] == EXCLUDED_GAME:
                out.add((int(r["datum"][:10].replace("-", "")), int(r["spieler_id"])))
    return out


def train_errors(pbp: Path, season: str) -> np.ndarray:
    return np.array([r["act"] - r["exp"] for r in mt.load_starters(pbp / "derived" / f"forecast_players_{season}.csv.gz")])


def load_rows(season: str, pbp: Path, tmp: Path) -> dict:
    z = np.load(rows_path(season, pbp, tmp))
    d = {k: z[k] for k in z.files}                           # einmal ganz einlesen (NpzFile liest sonst bei jedem Zugriff neu)
    ex = excluded_pairs(pbp, season)
    keep = np.array([(int(a), int(b)) not in ex for a, b in zip(d["date"], d["pid"])])
    starter = (d["emin"] > STARTER_MIN) & keep
    return {"d": d, "idx": np.where(starter)[0]}


def compute_probs(rows: dict, offsets: dict) -> dict:
    """{Variante: Matrix [Starter-Zeilen, 60]}; Variante -> offsets (None = Roh mit gespeicherten Punkten)."""
    d, idx = rows["d"], rows["idx"]
    out = {v: np.zeros((len(idx), len(KS_ALL))) for v in VARIANTS}
    for j, i in enumerate(idx):
        a, b = d["off"][i], d["off"][i + 1]
        ppm, w_p = d["ppm_cat"][a:b], d["wp_cat"][a:b]
        out["Roh"][j] = milestone_probs(ppm, w_p, d["mk"][i], KS_ALL)
        for v in ("E", "N"):
            out[v][j] = milestone_probs(ppm, w_p, minute_points(float(d["emin"][i]), offsets[v]), KS_ALL)
    return out


# ----------------------------------------------------------------------------- Auswertung
def select(rows: dict, probs: dict, group: str, no_ot: bool, scope: tuple) -> dict:
    """Zeilen (Spieler x Meilenstein) je Variante: p und Treffer."""
    d, idx = rows["d"], rows["idx"]
    m = np.ones(len(idx), bool)
    if group == "b":
        m &= d["n_hist"][idx] >= 10
    if no_ot:
        m &= d["ot"][idx] == 0
    kmask = (KS_ALL >= scope[0]) & (KS_ALL <= scope[1])
    hit = (d["pts"][idx][:, None] >= KS_ALL[None, :]).astype(float)[m][:, kmask].ravel()
    return {"hit": hit, **{v: probs[v][m][:, kmask].ravel() for v in VARIANTS}, "games": d["gi"][idx][m]}


def fmt_cal(c) -> str:
    return "-" if c[0] == 0 else f"{c[0]}/{100 * c[1]:.1f}%/{100 * c[2]:.1f}%"


def build_report(data: dict, notes: list) -> str:
    """data: {Saison: (rows, probs)} (Testsaison, mit Fold-Wahrscheinlichkeiten)."""
    out = ["Empirische Minutenverteilung der Starter (Variante E) gegen heute (Roh) - Meilenstein-Chancen der Spielerpunkte (beschreibend, keine Bewertung)",
           "Roh = Normalverteilung der Minuten je Spieler (9 Punkte, heute). E = 9 Quantile der Starter-Minutenfehler der zwei Trainingssaisons, auf Mittel = bisherige Prognose verschoben, 0..48 begrenzt.",
           "N = Zusatzkontrolle: 9 Normal-Quantile mit der gemeinsamen Streuung der Trainingsfehler (gleiche Breite wie E, aber symmetrisch). Nur Starter-Zeilen (erwartete Minuten roh > 28); Nicht-Starter unveraendert.",
           "Anpassung auf zwei Saisons, Test auf der dritten; Testsaison = Spalte. 'gesamt' = die drei Testsaisons zusammen. Zeile = Spieler x Meilenstein k; Treffer = Punkte >= k.",
           "Brier = mittlere quadratische Abweichung, LL = Log-Loss (Chance auf 1e-6..1-1e-6 begrenzt), Verzerrung = mittlere Chance minus Trefferquote (in Prozentpunkten). Kleiner Brier/LL = besser.",
           "Kalibrierung: ab Chance 50/65/80 % als Zeilen / mittlere Chance / Trefferquote. 'Richtung' = Vorzeichen von (E minus Roh) in allen drei Testsaisons gleich?", ""]
    names = list(data) + ["gesamt"]
    for no_ot, ot_name in ((False, "ALLE Spiele"), (True, "OHNE Verlaengerungsspiele")):
        for group, gname in (("a", "(a) alle Starter-Zeilen"), ("b", "(b) Starter mit mindestens 10 Spielen im Verlauf")):
            for sname, scope in SCOPES.items():
                out.append(f"{ot_name} - {gname} - {sname}")
                per = {s: select(*data[s][:1], data[s][1], group, no_ot, scope) for s in data}
                per["gesamt"] = {k: np.concatenate([per[s][k] for s in data]) for k in ("hit",) + VARIANTS}
                out.append("  " + "Kennzahl".ljust(22) + "".join(n.rjust(12) for n in names))
                ms = {n: {v: metrics(per[n][v], per[n]["hit"]) for v in VARIANTS} for n in names}
                out.append("  " + "Zeilen".ljust(22) + "".join(str(ms[n]["Roh"]["n"]).rjust(12) for n in names))
                for key, lab, scale, dec in (("brier", "Brier", 1, 5), ("ll", "Log-Loss", 1, 5), ("bias", "Verzerrung (PP)", 100, 2)):
                    for v in VARIANTS:
                        out.append("  " + f"{lab} {v}".ljust(22) + "".join(f"{scale * ms[n][v][key]:.{dec}f}".rjust(12) for n in names))
                    out.append("  " + f"{lab} E-Roh".ljust(22) + "".join(f"{scale * (ms[n]['E'][key] - ms[n]['Roh'][key]):+.{dec}f}".rjust(12) for n in names))
                for key, lab in (("brier", "Brier"), ("ll", "Log-Loss")):
                    sg = [np.sign(ms[s]["E"][key] - ms[s]["Roh"][key]) for s in data]
                    out.append(f"  Richtung {lab}: " + ("in allen drei Saisons gleich (" + ("E besser" if sg[0] < 0 else "E schlechter") + ")" if len(set(sg)) == 1 and sg[0] != 0 else "nicht in allen drei Saisons gleich"))
                for lvl in LEVELS:
                    for v in VARIANTS:
                        out.append("  " + f"ab {int(lvl * 100)} % {v}".ljust(22) + "".join(fmt_cal(calibration(per[n][v], per[n]["hit"], lvl)).rjust(24) for n in names))
                out.append("")
    out += ["Hinweise:"] + ["  " + n for n in notes]
    return "\n".join(out) + "\n"


def run(pbp: Path, tmp: Path, seasons=SEASONS, write=print) -> str:
    if "2023-24" in seasons and not rows_path("2023-24", pbp, tmp).exists():
        replay_2023(tmp)
    errs = {s: train_errors(pbp, s) for s in seasons}
    data, notes = {}, []
    for test in seasons:
        train = np.concatenate([errs[s] for s in seasons if s != test])
        offs = {"E": quantile_offsets(train), "N": normal_offsets(train)}
        notes.append(f"Test {test}: Training {sum(1 for s in seasons if s != test)} Saisons, {len(train)} Starter-Fehler; Punkte E (Verschiebung in Minuten) = " + ", ".join(f"{x:+.2f}" for x in offs["E"]))
        t0 = time.time()
        rows = load_rows(test, pbp, tmp)
        data[test] = (rows, compute_probs(rows, offs))
        write(f"{test}: {len(rows['idx'])} Starter-Zeilen ausgewertet ({time.time() - t0:.0f} s)")
    notes += ["Die Trainingssaisons enthalten auch spaetere Saisons als die Testsaison (so verlangt: alle drei Kombinationen).",
              "Die Verlaengerungsspiele im Training sind per Teamminuten > 245 bestimmt; 'ohne Verlaengerung' in der Auswertung per Spielkennzeichen aus dem Replay (ot).",
              "Starter = erwartete Minuten roh > 28 (nicht die Basis-Minuten wie in analysis/backtest_thresholds.py)."]
    return build_report({s: data[s] for s in seasons}, notes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--tmp", default=str(Path(tempfile.gettempdir()) / "minutes_empirical"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--replay-only", action="store_true")
    a = ap.parse_args(argv)
    pbp, tmp = Path(a.pbp_dir), Path(a.tmp)
    if a.replay_only:
        replay_2023(tmp)
        return 0
    text = run(pbp, tmp)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
