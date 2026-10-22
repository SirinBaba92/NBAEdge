"""Tests fuer engine/live_model.py und engine/bet_status.py (Baustein 2). Reine Rechnung, offline, kein Netz, keine Dateien.
Aufruf aus dem Projektordner: venv/bin/python tests/test_live_model.py"""
import json, os, sys
from pathlib import Path
from statistics import NormalDist
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from engine import game_clock as gc
from engine import live_model as lm
from engine import bet_status as bs
from engine.line_probabilities import SPREAD_SIGMA, TEAM_TOTAL_SIGMA, TOTAL_SIGMA, over_under_rows, percent_pair, prob_above, spread_rows
import config.settings as cfg

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

ND = NormalDist()
A = lm.Anchor(230.0, 8.1, 119.0, 111.0, 0.7798)                 # LAL - GSW (Werte aus dem Schnappschuss vom 21.10.)
A_AWAY = lm.Anchor(241.0, -3.5, 118.0, 123.0, 0.38)             # Auswaertsfavorit
B = gc.build_game_clock
PRE = B(1, "", 0, "")
HALF = B(2, "Halftime", 2, "")
def Q(period, left): return B(2, "", period, f"PT{int(left // 60):02d}M{left % 60:05.2f}S")
FINAL = B(3, "Final", 4, "")

# ----------------------------------------------------------------- Anpfiff = Vorab-Funktionen, je Markt
tip = lm.project(A, PRE, 0, 0)
check("Formelversion", tip.formula_version == lm.FORMULA_VERSION == "live-1" and tip.to_dict()["formula_version"] == "live-1")
check("Anpfiff: erwartete Endstaende = Vorab-Werte exakt", tip.expected_total == 230.0 and tip.expected_home == 119.0 and tip.expected_away == 111.0 and tip.expected_margin == 8.1)
check("Anpfiff: Streuungen = Vorab-Sigmas exakt", (tip.sd_total, tip.sd_home, tip.sd_away, tip.sd_margin) == (TOTAL_SIGMA, TEAM_TOTAL_SIGMA, TEAM_TOTAL_SIGMA, SPREAD_SIGMA))
lines_t = [x / 2 for x in range(420, 500)]
check("Anpfiff: Total Over = prob_above fuer 80 Linien", all(abs(tip.p_over_total(L) - prob_above(230.0, L, TOTAL_SIGMA)) < 1e-12 for L in lines_t))
lines_tt = [x / 2 for x in range(190, 270)]
check("Anpfiff: Team Total Heim/Gast = prob_above", all(abs(tip.p_over_team("home", L) - prob_above(119.0, L, TEAM_TOTAL_SIGMA)) < 1e-12 and abs(tip.p_over_team("away", L) - prob_above(111.0, L, TEAM_TOTAL_SIGMA)) < 1e-12 for L in lines_tt))
rows = over_under_rows(230.0, [226.5, 228.5, 230.5, 232.5], 230.5, TOTAL_SIGMA)
check("Anpfiff: Prozent wie die Total-Tabelle (Score Projections)", all(round(tip.p_over_total(r["line"]) * 100) == r["p_left"] for r in rows))
xs = [0.5 + i for i in range(0, 16)]
ok_sp = True
for anchor, fav in ((A, "home"), (A_AWAY, "away")):
    t0 = lm.project(anchor, PRE, 0, 0)
    for r in spread_rows(anchor.exp_spread, fav, xs, 7.5):
        left, right = r["p_left"], r["p_right"]                # links Gast, rechts Heim
        # Linie x aus Sicht des Favoriten: Favorit -x, Underdog +x
        p_home = t0.p_spread("home", -r["line"] if fav == "home" else r["line"])
        ok_sp &= round(p_home * 100) in (right, 100 - left) and round((1 - p_home) * 100) in (left, 100 - right)
check("Anpfiff: Spread (Heim- und Auswaertsfavorit) gleich den Spread-Tabellen", ok_sp)
for p0 in (0.05, 0.2, 0.5, 0.7798, 0.95):
    an = lm.Anchor(225.0, 3.0, 114.0, 111.0, p0)
    t = lm.project(an, PRE, 0, 0)
    check(f"Anpfiff: Sieger Heim = Vorab-Wahrscheinlichkeit {p0}", abs(t.p_winner("home") - p0) < 1e-9 and abs(t.p_winner("away") - (1 - p0)) < 1e-9, t.p_winner("home"))
check("Anpfiff mit Besitzen aus den ersten Sekunden aendert nichts (Tempo-Gewicht 0)", lm.project(A, PRE, 0, 0, lm.Possessions(1, 1)).expected_total == 230.0)
check("Anpfiff mit anderem Stand 0:0 in Q1 12:00 (laeuft) = Anpfiff", lm.project(A, Q(1, 720), 0, 0).expected_total == 230.0 and lm.project(A, Q(1, 720), 0, 0).p_winner("home") == tip.p_winner("home"))

# ----------------------------------------------------------------- Baustein-Funktionen
t = cfg.LIVE_SHARE_POINTS
check("Zeitverlauf: Stuetzstellen und lineare Mitte", lm.interp(t, 0) == 0 and lm.interp(t, 720) == t[1] and lm.interp(t, 2880) == 1.0 and abs(lm.interp(t, 360) - t[1] / 2) < 1e-12 and abs(lm.interp(t, 1080) - (t[1] + t[2]) / 2) < 1e-12)
check("Zeitverlauf ausserhalb begrenzt", lm.interp(t, -5) == 0 and lm.interp(t, 99999) == 1.0)
check("Gleichstand-Masse: symmetrisch, Summe plausibel, sigma 0 exakt", abs(lm.tie_mass(0, 10) - (ND.cdf(0.05) - ND.cdf(-0.05))) < 1e-12 and lm.tie_mass(0, 0) == 1.0 and lm.tie_mass(3, 0) == 0.0 and abs(lm.tie_mass(2, 7) - lm.tie_mass(-2, 7)) < 1e-12)
check("effektive Marge: monoton und loest die Gleichung", lm.effective_margin(0.3, 10.5) < lm.effective_margin(0.5, 10.5) < lm.effective_margin(0.8, 10.5) and abs(lm.effective_margin(0.5, 10.5)) < 1e-6)
check("Sieger-Verlaengerung nahezu offen mit kleinem Heimvorteil", 0.5 < lm.p_ot_home(3.0, 10.5) < 0.56 and lm.p_ot_home(0, 10.5) == 0.5)

# ----------------------------------------------------------------- Tempo
check("Tempo ohne Besitze = 1,0", lm.pace_multiplier(None, 1500)[0] == 1.0)
m, live, w, est = lm.pace_multiplier(lm.Possessions(50, 50), 24 * 60)
check("Tempo: Halbzeit mit 50 Besitzen je Team = Liga-Pace -> Faktor ~1, Gewicht n/(n+K)", abs(live - 100.0) < 1e-9 and abs(w - 50 / (50 + cfg.LIVE_PACE_K)) < 1e-12 and 0.97 < m < 1.0, (m, live, w))
m_fast = lm.pace_multiplier(lm.Possessions(60, 60), 24 * 60)[0]
m_slow = lm.pace_multiplier(lm.Possessions(40, 40), 24 * 60)[0]
check("schnelleres Spiel -> Faktor groesser, langsameres -> kleiner", m_slow < lm.pace_multiplier(lm.Possessions(50, 50), 24 * 60)[0] < m_fast)
check("Tempo-Faktor begrenzt", lm.pace_multiplier(lm.Possessions(500, 500), 600)[0] == cfg.LIVE_PACE_MULT_CLIP[1] and lm.pace_multiplier(lm.Possessions(1, 1), 2000)[0] >= cfg.LIVE_PACE_MULT_CLIP[0])
check("Tempo: erste Minute ignoriert", lm.pace_multiplier(lm.Possessions(5, 5), 30)[0] == 1.0)
check("Besitze aus Boxscore-Teamwerten", abs(lm.possessions_from_stats({"fieldGoalsAttempted": 82, "freeThrowsAttempted": 31, "reboundsOffensive": 11, "turnoversTotal": 18}) - (82 + 0.44 * 31 - 11 + 18)) < 1e-9)
fast = lm.project(A, HALF, 60, 55, lm.Possessions(60, 60)); norm = lm.project(A, HALF, 60, 55, lm.Possessions(50, 50))
check("schnelleres Tempo erhoeht die erwarteten Restpunkte", fast.expected_total > norm.expected_total and fast.pace_mult > norm.pace_mult)

# ----------------------------------------------------------------- Faktoren neutral (1,0), mitgeschrieben
f0 = lm.project(A, HALF, 62, 52)
check("Faktoren neutral und mitgeschrieben", f0.factors == {"foul_bonus": 1.0, "blowout": 1.0, "star_out": 1.0} and lm.Factors().product == 1.0)
f1 = lm.project(A, HALF, 62, 52, factors=lm.Factors(foul_bonus=1.05))
check("Faktor 1,05 erhoeht Restpunkte, aendert die Marge nicht, wird mitgeschrieben", f1.expected_total > f0.expected_total and f1.expected_margin == f0.expected_margin and f1.factors["foul_bonus"] == 1.05 and f1.p_over_total(230.5) > f0.p_over_total(230.5))

# ----------------------------------------------------------------- Halbzeit
check("Halbzeit: erwartetes Total = Stand + Rest, Streuung verkleinert", f0.phase == gc.HALFTIME and f0.sd_total < tip.sd_total * 0.8 and f0.expected_total < 230.0 + 5 and 220 < f0.expected_total < 235, (f0.expected_total, f0.sd_total))
check("Halbzeit: Restvarianz laut Tabelle (Total)", abs(f0.sd_total - TOTAL_SIGMA * (cfg.LIVE_VAR_REST_TOTAL[2] * (1 - f0.p_tie_anchor * lm.OT_SHARE) + f0.p_tie * lm.OT_SHARE + 0) ** 0.5) < 0.2, f0.sd_total)
check("Spielstand 62:52 zur Halbzeit: Favorit Heim vorn -> Sieger-Chance steigt", f0.p_winner("home") > tip.p_winner("home"))
check("Sieger Heim + Gast = 100 %", abs(f0.p_winner("home") + f0.p_winner("away") - 1) < 1e-12)

# ----------------------------------------------------------------- Endwerte gegen 0/100 %
def p_end(left, h, a):
    return lm.project(A, Q(4, left), h, a)
end_lead = [p_end(s, 112, 102).p_winner("home") for s in (180, 60, 20, 5, 1)]
check("Ende: 10 Punkte vorn, Restzeit sinkt -> Sieger-Chance steigt gegen 100 %", all(x <= y for x, y in zip(end_lead, end_lead[1:])) and end_lead[0] < end_lead[-1] and end_lead[-1] > 0.9999, end_lead)
end_trail = [p_end(s, 102, 112).p_winner("home") for s in (180, 60, 20, 5, 1)]
check("Ende: 10 Punkte hinten -> Sieger-Chance faellt gegen 0 %", all(x >= y for x, y in zip(end_trail, end_trail[1:])) and end_trail[0] > end_trail[-1] and end_trail[-1] < 0.0001, end_trail)
over_far = [p_end(s, 110, 100).p_over_total(240.5) for s in (300, 120, 30, 5)]
check("Ende: Total weit ueber dem Stand -> Over-Chance faellt gegen 0", all(x >= y for x, y in zip(over_far, over_far[1:])) and over_far[-1] < 0.001, over_far)
reg_end = lm.project(A, B(2, "", 4, ""), 112, 102)
check("Q4 vorbei, Vorsprung: Sieger sicher, Spread/Total entschieden durch den Stand", reg_end.p_winner("home") == 1.0 and reg_end.p_spread("home", -9.5) == 1.0 and reg_end.p_spread("home", -10.5) == 0.0 and reg_end.p_over_total(213.5) == 1.0 and reg_end.p_over_total(214.5) == 0.0)
fin = lm.project(A, FINAL, 118, 109)
check("FINAL: alle Wahrscheinlichkeiten exakt 0 oder 1", fin.final and fin.p_winner("home") == 1.0 and fin.p_winner("away") == 0.0 and fin.p_over_total(226.5) == 1.0 and fin.p_over_total(227.5) == 0.0
      and fin.p_over_team("home", 117.5) == 1.0 and fin.p_over_team("home", 118.5) == 0.0 and fin.p_over_team("away", 108.5) == 1.0 and fin.p_spread("home", -8.5) == 1.0 and fin.p_spread("home", -9.5) == 0.0
      and fin.p_spread("away", 9.5) == 1.0 and fin.p_spread("away", 8.5) == 0.0 and fin.sd_total == 0.0)
check("FINAL mit Verlaengerung: Endstand zaehlt (Over trifft durch OT-Punkte)", lm.project(A, B(3, "Final/OT", 5, ""), 125, 123).p_over_total(247.5) == 1.0 and lm.project(A, B(3, "Final/OT", 5, ""), 125, 123).p_winner("away") == 0.0)

# ----------------------------------------------------------------- Verlaengerung
ot_pending = lm.project(A, B(2, "", 4, ""), 115, 115)
check("Ende Q4, Gleichstand: Verlaengerung sicher, ca. 5 Min. Punkte kommen dazu", ot_pending.p_tie == 1.0 and 235 < ot_pending.expected_total - 30 + 30 and abs((ot_pending.expected_total - 230) - (230 * lm.OT_SHARE * cfg.LIVE_OT_SCORING_FACTOR)) < 1e-6, ot_pending.expected_total)
check("Ende Q4, Gleichstand: Sieger = Sieger der Verlaengerung (nahezu offen, Heimvorteil klein)", abs(ot_pending.p_winner("home") - ot_pending.p_ot_home) < 1e-12 and 0.5 < ot_pending.p_ot_home < 0.65)
check("Gleichstand in Q4 mit 3:00 Rest: Gleichstand-Wahrscheinlichkeit am Ende hoch (>10 %), Over-Chance hoeher als ohne Gleichstand", lm.project(A, Q(4, 180), 108, 108).p_tie > 0.10 and lm.project(A, Q(4, 180), 108, 108).p_over_total(232.5) > lm.project(A, Q(4, 180), 112, 100).p_over_total(232.5))
check("Gleichstands-Wahrscheinlichkeit liegt beim Anpfiff bei 2-4 % (Normalverteilung)", 0.02 < tip.p_tie < 0.04)
ot_run = lm.project(A, B(2, "OT 2:00", 5, "PT02M00.00S"), 120, 120)
check("Verlaengerung laeuft: nur 5-Minuten-Basis (Total nur wenig ueber dem Stand), Phase OT", ot_run.phase == gc.OT and 240 < ot_run.expected_total < 256 and ot_run.sd_total < 8, (ot_run.expected_total, ot_run.sd_total))
ot_lead = lm.project(A, B(2, "OT 0:10", 5, "PT00M10.00S"), 125, 118)
check("Verlaengerung, 7 Punkte vorn mit 10 s: Sieger fast sicher", ot_lead.p_winner("home") > 0.999)
ot_tie_end = lm.project(A, B(2, "", 5, ""), 120, 120)
check("Verlaengerung vorbei, Gleichstand: weitere Verlaengerung folgt (p_tie = 1)", ot_tie_end.p_tie == 1.0)
check("Verlaengerung: kein 12-Minuten-Viertel gerechnet (Rest-Erwartung < 6 Punkte je Team bei 2:00)", ot_run.expected_home - 120 < 12 and ot_run.expected_away - 120 < 12)

# ----------------------------------------------------------------- vorzeitige Entscheidung bei Over
ov = lm.project(A, Q(3, 400), 85, 60)
check("Total Over schon uebertroffen (145 > 144,5): Wahrscheinlichkeit 1,0 vor dem Spielende", ov.p_over_total(144.5) == 1.0 and 0 < ov.p_over_total(250.5) < 1)
check("Team Total Over schon uebertroffen: 1,0", ov.p_over_team("home", 84.5) == 1.0 and ov.p_over_team("away", 59.5) == 1.0 and ov.p_over_team("home", 120.5) < 1)
check("Spread und Sieger sind NICHT vorzeitig entschieden", 0 < ov.p_winner("home") < 1 and 0 < ov.p_spread("home", -20.5) < 1)

# ----------------------------------------------------------------- Monotonie
mid = Q(2, 360)
a1, a2, a3 = (lm.project(A, mid, 50 + k, 45) for k in (0, 4, 8))
check("mehr Punkte (Heim) -> Team-Total-Over, Total-Over, Spread Heim, Sieger Heim steigen", a1.p_over_team("home", 110.5) < a2.p_over_team("home", 110.5) < a3.p_over_team("home", 110.5)
      and a1.p_over_total(225.5) < a2.p_over_total(225.5) < a3.p_over_total(225.5) and a1.p_spread("home", -5.5) < a2.p_spread("home", -5.5) < a3.p_spread("home", -5.5) and a1.p_winner("home") < a2.p_winner("home") < a3.p_winner("home"))
check("Gast-Spread und Heim-Spread ergeben 100 % (gleiche Linie)", abs(a2.p_spread("home", -5.5) + a2.p_spread("away", 5.5) - 1) < 1e-12)
check("Anker aus dem echten Schnappschuss lesbar", True)
snap = json.loads((ROOT / "data/tracking/projection_snapshots.json").read_text())["games"]
v = next(iter(snap.values()))["versions"][-1]
an = lm.Anchor.from_snapshot(v)
check("Anchor.from_snapshot: Werte und Sigmas aus dem Schnappschuss", an.exp_total == v["projection"]["exp_total"] and an.sigma_total == v["sigmas"]["total"] and an.source == "schnappschuss")
check("Anchor 'live_nachgerechnet' kennzeichnet die Quelle", lm.Anchor.from_snapshot(v, "live_nachgerechnet").source == "live_nachgerechnet" and lm.project(lm.Anchor.from_snapshot(v, "live_nachgerechnet"), PRE, 0, 0).anchor_source == "live_nachgerechnet")


# ----------------------------------------------------------------- sigmas_version 2: Siegchance aus derselben Verteilung wie der Spread
from engine.line_probabilities import win_prob_home
def anchor_v2(spread, total=230.0):
    return lm.Anchor(total, spread, (total + spread) / 2, (total - spread) / 2, round(win_prob_home(spread), 4), sigmas_version="2")
all_eq = True; all_sp = True
for sp in (-12.0, -3.5, 0.0, 0.4, 5.0, 8.1, 15.0):
    a2 = anchor_v2(sp)
    t2 = lm.project(a2, PRE, 0, 0)
    all_eq &= abs(t2.p_winner("home") - a2.home_win_prob) < 5e-5 and abs(t2.p_winner("home") - ND.cdf(sp / SPREAD_SIGMA)) < 1e-12
    all_sp &= t2.p_winner("home") == t2.p_spread("home", 0.0) and t2.winner_mode == "gleiche_verteilung" and t2.sigmas_version == "2"
check("Version 2: Sieger beim Anpfiff = gespeicherte Vorab-Siegchance (Rundung auf 4 Stellen) und = Phi(Spread / Sigma), 7 Spreads", all_eq)
check("Version 2: Sieger = Spread-Wahrscheinlichkeit bei Linie 0 (exakt gleiche Zahl), Modus 'gleiche_verteilung'", all_sp)
a2 = anchor_v2(8.1)
same = True
for clock_, h_, a_ in ((HALF, 62, 52), (Q(4, 180), 108, 108), (Q(4, 180), 112, 104), (B(2, "", 4, ""), 115, 115), (B(2, "OT 2:00", 5, "PT02M00.00S"), 120, 120), (Q(2, 360), 30, 40)):
    pr = lm.project(a2, clock_, h_, a_)
    same &= pr.p_winner("home") == pr.p_spread("home", 0.0) and abs(pr.p_winner("home") + pr.p_winner("away") - 1) < 1e-12
check("Version 2: Sieger = Spread bei Linie 0 auch im Spiel (Halbzeit, Q4, Ende Q4, Verlaengerung)", same)
check("Version 2: Total, Team Total und Spread beim Anpfiff weiter = Vorab-Funktionen", all(abs(lm.project(a2, PRE, 0, 0).p_over_total(L) - prob_above(230.0, L, TOTAL_SIGMA)) < 1e-12 for L in lines_t)
      and all(abs(lm.project(a2, PRE, 0, 0).p_over_team("home", L) - prob_above(a2.home_score, L, TEAM_TOTAL_SIGMA)) < 1e-12 for L in lines_tt))
check("Version 2: Ende Q4 mit Gleichstand: Sieger nahe 50-65 % (Verlaengerung offen), FINAL exakt 0/1", 0.5 < lm.project(a2, B(2, "", 4, ""), 115, 115).p_winner("home") < 0.65
      and lm.project(a2, FINAL, 118, 109).p_winner("home") == 1.0 and lm.project(a2, FINAL, 100, 109).p_winner("home") == 0.0)
check("Version 2: 10 Punkte vorn bei 5 s Rest: Sieger > 99,9 %", lm.project(a2, Q(4, 5), 112, 102).p_winner("home") > 0.999)
check("Version 1 (Elo-Logistik) bleibt bei der effektiven Marge", lm.project(A, HALF, 62, 52).winner_mode == "effektive_marge" and lm.project(A, HALF, 62, 52).sigmas_version == "1")
vtest = {"projection": {"exp_total": 230.0, "exp_spread": 8.1, "home_score": 119.0, "away_score": 111.0, "home_win_prob": 0.7303}, "sigmas": {"spread": 13.2, "total": 18.6, "team_total": 11.6}}
check("Anchor.from_snapshot: sigmas_version 2 gelesen, fehlend = 1", lm.Anchor.from_snapshot({**vtest, "sigmas_version": "2"}).sigmas_version == "2" and lm.Anchor.from_snapshot(vtest).sigmas_version == "1")
check("Anchor.from_snapshot mit Sigmas aus dem Schnappschuss (alte Version 10,5 / 18 / 12,5 bleibt moeglich)", lm.Anchor.from_snapshot({**vtest, "sigmas": {"spread": 10.5, "total": 18.0, "team_total": 12.5}}).sigma_spread == 10.5)

# ----------------------------------------------------------------- Wettstatus: Grenzen 10 / 35 / 65
S = bs.status_from_probability
check("Grenzen: >65 % Auf Kurs, genau 65 % Offen", S(0.6500001) == bs.ON_TRACK and S(0.65) == bs.OPEN and S(0.80) == bs.ON_TRACK)
check("Grenzen: 35 % Offen, knapp darunter In Gefahr", S(0.35) == bs.OPEN and S(0.3499) == bs.DANGER and S(0.5) == bs.OPEN)
check("Grenzen: genau 10 % In Gefahr, darunter Kaum noch moeglich", S(0.10) == bs.DANGER and S(0.0999) == bs.HOPELESS and S(0.0) == bs.HOPELESS and S(0.2) == bs.DANGER)
check("Farben: gruen/gelb/orange/rot", bs.COLORS[bs.ON_TRACK] == "gruen" and bs.COLORS[bs.OPEN] == "gelb" and bs.COLORS[bs.DANGER] == "orange" and bs.COLORS[bs.HOPELESS] == "rot" and bs.COLORS[bs.LOST] == "rot" and bs.COLORS[bs.WON] == "gruen")
bet_tot = {"market": "total", "line": 144.5, "odds": 1.9, "stake": 10}
st = bs.evaluate_bet(bet_tot, ov)
check("Over Total: Stand 145 > 144,5 -> sofort Gewonnen (Spiel laeuft noch)", st.label == bs.WON and st.decided and st.won and st.probability == 1.0)
check("Gewinn: Einsatz * (Quote - 1)", bs.profit(bet_tot, st) == 9.0)
bet_w = {"market": "winner", "side": "home", "odds": 1.5, "stake": 20}
st = bs.evaluate_bet(bet_w, ov)
check("Sieger: nicht vorzeitig entschieden, Status nach Wahrscheinlichkeit", not st.decided and st.label in (bs.ON_TRACK, bs.OPEN, bs.DANGER, bs.HOPELESS) and bs.profit(bet_w, st) is None)
check("Over laeuft auf Verlust zu: Kaum noch moeglich bei 5 s Rest weit unter der Linie", bs.evaluate_bet({"market": "total", "line": 250.5, "odds": 1.9, "stake": 5}, lm.project(A, Q(4, 5), 105, 100)).label == bs.HOPELESS)
fin_w = lm.project(A, FINAL, 100, 110)
check("FINAL: Sieger Heim verloren, Verlust = -Einsatz", bs.evaluate_bet(bet_w, fin_w).label == bs.LOST and bs.profit(bet_w, bs.evaluate_bet(bet_w, fin_w)) == -20.0)
check("FINAL: Over knapp verfehlt = Verloren; ganzzahlige Linie mit Gleichstand = nicht gewonnen", bs.evaluate_bet({"market": "total", "line": 210.0, "odds": 1.9, "stake": 5}, fin_w).label == bs.LOST and bs.evaluate_bet({"market": "total", "line": 209.5, "odds": 1.9, "stake": 5}, fin_w).label == bs.WON)
check("Spread erst am Ende entschieden", bs.evaluate_bet({"market": "spread", "side": "home", "line": -3.5, "odds": 1.9, "stake": 5}, ov).decided is False and bs.evaluate_bet({"market": "spread", "side": "home", "line": 15.5, "odds": 1.9, "stake": 5}, fin_w).label == bs.WON)
check("Team Total Heim/Gast: Entscheidung aus dem Teamstand", bs.evaluate_bet({"market": "team_total_away", "line": 59.5, "odds": 1.9, "stake": 5}, ov).label == bs.WON and bs.evaluate_bet({"market": "team_total_home", "line": 110.5, "odds": 1.9, "stake": 5}, ov).label != bs.WON)
ub_t = {"market": "total", "side": "under", "line": 144.5, "odds": 2.0, "stake": 10}
ub_h = {"market": "team_total_home", "side": "under", "line": 120.5, "odds": 1.9, "stake": 10}
check("Under Total: Stand 145 > 144,5 -> sofort Verloren (Chance 0), Stand darunter: Chance = 1 - Over-Chance, nicht vorzeitig gewonnen", bs.evaluate_bet(ub_t, ov).label == bs.LOST and bs.evaluate_bet(ub_t, ov).probability == 0.0
      and abs(bs.bet_probability(lm.project(A, Q(3, 400), 70, 60), ub_t) - (1 - lm.project(A, Q(3, 400), 70, 60).p_over_total(144.5))) < 1e-12 and not bs.evaluate_bet(ub_t, lm.project(A, Q(3, 400), 70, 60)).decided)
check("Under: am Ende unter der Linie gewonnen (Gewinn = Einsatz * (Quote - 1)), darueber verloren; Linie erreicht (ganzzahlig) = nicht gewonnen", bs.evaluate_bet(ub_t, lm.project(A, FINAL, 80, 50)).label == bs.WON and bs.profit(ub_t, bs.evaluate_bet(ub_t, lm.project(A, FINAL, 80, 50))) == 10.0
      and bs.evaluate_bet(ub_t, lm.project(A, FINAL, 100, 50)).label == bs.LOST and bs.evaluate_bet({**ub_t, "line": 130.0}, lm.project(A, FINAL, 80, 50)).label == bs.LOST)
check("Under Team Total Gast/Heim: Entscheidung aus dem Teamstand", bs.evaluate_bet(ub_h, ov).label != bs.LOST and bs.evaluate_bet({**ub_h, "market": "team_total_away", "line": 59.5}, ov).label == bs.LOST
      and bs.evaluate_bet({**ub_h, "market": "team_total_away", "line": 61.5}, lm.project(A, FINAL, 85, 60)).label == bs.WON)
check("vor dem Anpfiff: Wartet auf Anpfiff mit Vorab-Chance", bs.evaluate_bet(bet_w, tip, started=False).label == bs.WAITING and abs(bs.evaluate_bet(bet_w, tip, started=False).probability - 0.7798) < 1e-9)
try:
    bs.bet_probability(tip, {"market": "unbekannt"}); raised = False
except ValueError:
    raised = True
check("unbekannter Markt wird abgelehnt", raised)
check("Markt-Liste", bs.MARKETS == ("winner", "spread", "total", "team_total_home", "team_total_away"))

print("\nALLES OK" if ok else "\nFEHLER")
sys.exit(0 if ok else 1)
