"""Tests fuer den Tab "🏀 Spieltag" (Baustein 5, nur Anzeige): ui/live_tab.py, ui/live_card.py, Einbindung in app.py.
AppTest mit Attrappen (tests/fake_net.py), Temp-Ordner fuer Schnappschuesse und Wetten, kein echter Abruf, keine echten Dateien, keine Browsertests.
Aufruf aus dem Projektordner: venv/bin/python tests/test_spieltag_tab.py"""
import hashlib, json, os, re, sys, time, warnings
from pathlib import Path
from statistics import NormalDist
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state as FN, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
from page_checks import problems
from streamlit.testing.v1 import AppTest
from data import day_bets_store as ds
from data import live_feed as lf
from data import pre_match_store as ps
from data import projection_snapshots as snap
from engine import game_clock as gc
from engine import line_probabilities as lp
import ui.live_card as lc
import ui.live_tab as lt
from ui.score_cards import PALETTE

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def real_snapshot():
    """Hash aller echten Dateien, die der Test nie beschreiben darf (data/tracking/*.json inkl. day_bets.json, pregame_lines.json); fehlende Datei = fehlt im Ergebnis."""
    files = list((ROOT / "data" / "tracking").glob("*.json")) + [ROOT / "data" / "pregame_lines.json"]
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in files if p.exists()}
real_tracking = real_snapshot()                       # direkt vor dem Testlauf
real_now = time.time()
DAY = lf.current_us_day(real_now)                               # Spieltag laut Uhr: unabhaengig von der echten Uhrzeit des Testlaufs
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
NOW = [real_now]
FUT = lambda h: iso(real_now + h * 3600)                         # Anpfiff in h Stunden (Zukunft = Wetten noch aenderbar)
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)

def row(gid, home, away, status=2, period=3, clock="PT06M00.00S", text="", hs=85, as_=60, start=None, day=None):
    h_city, h_name = home.rsplit(" ", 1) if home != "Portland Trail Blazers" else ("Portland", "Trail Blazers")
    a_city, a_name = away.rsplit(" ", 1)
    return {"gameId": gid, "gameStatus": status, "gameStatusText": text, "period": period, "gameClock": clock, "gameEt": f"{day or DAY}T19:00:00-04:00", "gameTimeUTC": start or FUT(3),
            "homeTeam": {"teamCity": h_city, "teamName": h_name, "teamTricode": "HOM", "score": hs, "periods": []}, "awayTeam": {"teamCity": a_city, "teamName": a_name, "teamTricode": "AWY", "score": as_, "periods": []}}
def box(fga=60, fta=20, oreb=8, tov=10):
    s = {"fieldGoalsAttempted": fga, "freeThrowsAttempted": fta, "reboundsOffensive": oreb, "turnoversTotal": tov}
    return {"homeTeam": {"statistics": dict(s)}, "awayTeam": {"statistics": dict(s)}}
def version(total=230.0, spread=8.1, home=119.0, away=111.0, lines=(4.5, 231.5)):
    p = round(NormalDist().cdf(spread / 13.2), 4)
    return {"saved_at": "2026-10-22T10:00:00+02:00", "hash": "h", "projection": {"exp_total": total, "exp_spread": spread, "home_score": home, "away_score": away, "home_win_prob": p},
            "markets": {"spread": {"line": lines[0]}, "total": {"line": lines[1]}, "team_total_home": {"line": None}, "team_total_away": {"line": None}}, "sigmas": {"spread": 13.2, "total": 18.6, "team_total": 11.6}, "sigmas_version": "2"}
def write_snaps(items):
    d = {"version": 1, "format": "nbaedge-projection-snapshots", "updated_at": None, "games": {}}
    for start, home, away, ver in items:
        d["games"][ps.game_key(DAY, start, home, away)] = {"game_date": DAY, "start_utc": start, "home": home, "away": away, "versions": [ver], "card": None, "result": None}
    snap.snapshot_path().parent.mkdir(parents=True, exist_ok=True); snap.snapshot_path().write_text(json.dumps(d)); snap._cache.update(sig=None, data=None)
def setup(rows, boxes=None, snaps=(), board_day=None):
    fresh_env()
    FN["scoreboard"], FN["boxes"], FN["board_date"] = rows, boxes or {}, board_day or DAY
    NOW[0] = real_now
    lf._feed = lf.LiveFeed(now=lambda: NOW[0])
    write_snaps(snaps) if snaps else None
def tab_idx(at): return [t.label for t in at.tabs].index("🏀 Spieltag")
def html(at): return " ".join(m.value for m in at.tabs[tab_idx(at)].markdown)
def card(at, gid):
    c = [m.value for m in at.tabs[tab_idx(at)].markdown if f'data-game="{gid}"' in m.value]
    return c[0] if c else ""
def cards(at): return [re.search(r'data-game="([^"]+)"', m.value).group(1) for m in at.tabs[tab_idx(at)].markdown if 'class="pc-card lv-card' in m.value]
def pcts(card_html): return [int(x) for x in re.findall(r"(\d+) %", card_html)]
def counters(): return (FN["nba_calls"], len(FN["odds_calls"]), FN["bdl_calls"], FN["espn_calls"])

S1, S2, S3, S4, S5, S6 = FUT(2), FUT(3), FUT(1), FUT(4), FUT(5), FUT(6)
ROWS = [row("G1", "Philadelphia 76ers", "Cleveland Cavaliers", 2, 3, "PT06M00.00S", hs=85, as_=60, start=S1),                                          # laeuft Q3
        row("G2", "Boston Celtics", "Miami Heat", 1, 0, "", "7:00 pm ET", hs=0, as_=0, start=S2),                                                    # noch nicht begonnen
        row("G3", "Oklahoma City Thunder", "Denver Nuggets", 2, 2, "", "Halftime", hs=58, as_=55, start=S3),                                         # Halbzeit
        row("G4", "Detroit Pistons", "Chicago Bulls", 2, 4, "", "", hs=100, as_=100, start=S4),                                                      # Ende Q4, Gleichstand
        row("G5", "Utah Jazz", "Phoenix Suns", 2, 5, "PT02M00.00S", hs=110, as_=110, start=S5),                                                     # Verlaengerung
        row("G6", "Houston Rockets", "Dallas Mavericks", 3, 4, "", "Final", hs=120, as_=101, start=S6),                                              # beendet
        row("G7", "Toronto Raptors", "Indiana Pacers", 3, 5, "", "Final/OT", hs=118, as_=116, start=FUT(7))]                                          # beendet nach Verlaengerung
SNAPS = [(S1, "Philadelphia 76ers", "Cleveland Cavaliers", version()), (S2, "Boston Celtics", "Miami Heat", version(225.0, 3.0, 114.0, 111.0, (-3.5, 225.5))),
         (S3, "Oklahoma City Thunder", "Denver Nuggets", version(228.0, 5.0, 116.0, 111.0, (5.5, 228.5))), (S4, "Detroit Pistons", "Chicago Bulls", version(220.0, 1.0, 110.0, 109.0, (1.5, 220.5))),
         (S5, "Utah Jazz", "Phoenix Suns", version(232.0, -2.0, 115.0, 117.0, (-2.5, 232.5))), (S6, "Houston Rockets", "Dallas Mavericks", version(226.0, 4.0, 115.0, 111.0, (4.5, 226.5)))]
BOXES = {"G1": box(60, 20, 8, 10), "G3": box(50, 10, 5, 8), "G4": box(80, 25, 10, 12), "G5": box(85, 28, 11, 12)}

# ================================================================= A) Tab erscheint, alter Tab laeuft weiter
setup(ROWS, BOXES, SNAPS)
at = app().run()
labels = [t.label for t in at.tabs]
check("Start der Seite: keine Exception, keine Warnung", not problems(at), " | ".join(problems(at))[:200])
check("Tab '🏀 Spieltag' steht direkt neben dem bisherigen Live-Tab, der heisst jetzt '🔴 Live (alt)'", labels[:4] == ["📊 Score Projections", "🔴 Live (alt)", "🏀 Spieltag", "🎯 Live Bet Tracker"] and labels[-1].endswith("Pre-Match Eingabe") and len(labels) == 8, str(labels))
old = " ".join(m.value for m in at.tabs[labels.index("🔴 Live (alt)")].markdown)
check("alter Tab unveraendert: Ueberschrift, Player-Props-Block, Live-Bet-Tracker-Tab mit Tabelle", "Live Projection Engine" in old and "Player Props Pre-Game" in old
      and any("Live Bet Tracker" in m.value for m in at.tabs[labels.index("🎯 Live Bet Tracker")].markdown))
check("alter Tab: seine Bedienelemente sind noch da (Datenquelle, Live-Modus, Spielerauswahl)", any(r.label == "Live-Modus" for r in at.radio) and any(b.key == "load_nba_player_props_data" for b in at.button))
check("neue Bedienelemente nur im neuen Tab: Knopf 'Aktualisieren', Schalter 'Automatisch aktualisieren' (Standard an)", [b.key for b in at.button if b.key == "sp_refresh"] == ["sp_refresh"] and at.toggle(key="sp_auto").value is True)
H = html(at)
check("Ueberschrift, Stylesheet (Karten- und Live-CSS), keine weiteren Elemente ausserhalb des Tabs", "## 🏀 Spieltag" in H and ".lv-card" in H and ".pc-card" in H and "lv-status" in H)

# ================================================================= B) Statuszeile, Uebersicht, Reihenfolge
check("Statuszeile: Quelle und Alter der Daten, 'ok'-Stil", 'class="lv-status-line lv-status-ok"' in H and "NBA.com · aktuell (vor 0 s)" in H)
ov = re.search(r'<div class="lv-overview">.*?(?=<div class="lv-sum|$)', H).group(0)
rows_ov = re.findall(r'<div class="lv-orow lv-orow-(\w+)">(.*?)</div></div>', ov)
check("Tagesuebersicht: eine Zeile je Spiel (7), auch das noch nicht begonnene; US-Spieltag in der Kopfzeile", len(re.findall(r'class="lv-orow ', ov)) == 7 and f"Spieltag {lc.fmt_day(DAY)} (US-Datum)" in ov and "Celtics" in ov and "Heat" in ov)
order_ov = re.findall(r'<span class="lv-oteams">([^<]+)</span>', ov)
check("Tagesuebersicht nach Anpfiff sortiert (Thunder zuerst, dann 76ers, Celtics ...)", order_ov == ["Nuggets @ Thunder", "Cavaliers @ 76ers", "Heat @ Celtics", "Bulls @ Pistons", "Suns @ Jazz", "Mavericks @ Rockets", "Pacers @ Raptors"], str(order_ov))
check("Zeile: Uhrzeit/Stand/clock_label je Phase (Q3 6:00, Halbzeit, Ende Q4, OT 2:00, Ende, Ende (OT))", all(x in ov for x in ("Q3 6:00", "Halbzeit", "Ende Q4", "OT 2:00", ">Ende<", "Ende (OT)", "60 : 85", "55 : 58", "100 : 100", "110 : 110", "101 : 120", "116 : 118")))
check("noch nicht begonnenes Spiel in der Uebersicht ohne Stand, mit Anpfiffzeit (Berlin) und Status 'Vor dem Anpfiff'", re.search(r'lv-orow-pre"><span class="lv-otime">(\d\d:\d\d)</span><span class="lv-oteams">Heat @ Celtics</span><span class="lv-oscore"></span><span class="lv-oclock">\1</span>', ov) is not None and "Vor dem Anpfiff" in ov)
check("Status-Chips: laeuft/Pause gelb, Vorab/beendet grau (wie im Pre-Match-Tab)", 'pc-chip pc-chip-yellow">läuft<' in ov and 'pc-chip pc-chip-yellow">Halbzeit<' in ov and 'pc-chip pc-chip-gray">beendet<' in ov and 'pc-chip pc-chip-gray">Vor dem Anpfiff<' in ov)
check("Karten-Reihenfolge: laufende zuerst (nach Anpfiff), dann noch nicht begonnene, dann beendete", cards(at) == ["G3", "G1", "G4", "G5", "G2", "G6", "G7"], str(cards(at)))
check("keine Wetten gespeichert: kurzer Hinweis statt Zahlen", "Für diesen Spieltag sind noch keine Wetten gespeichert." in H and 'class="lv-tiles"' not in H)

# ================================================================= C) Karten je Phase
c1 = card(at, "G1")
check("Karte laeuft (Q3 6:00): Gast links, Heim rechts mit Logos, Stand 60 @ 85, Zeit 'Q3 6:00', Chip 'läuft', Anpfiffzeit oben", 'class="pc-head"' in c1 and "data:image/svg+xml" in c1 and c1.index("Cavaliers") < c1.index("76ers") and ">60<" in c1 and ">85<" in c1
      and "Q3 6:00" in c1 and 'pc-chip-yellow">läuft<' in c1 and re.search(r"(Mo|Di|Mi|Do|Fr|Sa|So) \d\d\.\d\d\. \d\d:\d\d Uhr", c1))
a1 = lf.LiveFeed  # Referenz nur fuer Lesbarkeit
n1 = lf.live_numbers_for_state(lf._feed.state(), snap.load()["games"])["G1"]
exp_home = round(n1.p_winner("home") * 100)
check("Karte laeuft: Siegbalken 'Siegchance (live)' mit den Live-Prozenten aus dem Live-Modell (85:60 in Q3: Heim weit vorn)", "Siegchance (live)" in c1 and f"{exp_home} % 76ers" in c1 and f"Cavaliers {100 - exp_home} %" in c1 and exp_home > 90)
check("Siegbalken: Favorit (hoehere Chance) orange (pc-seg-fav), nach Regel 1 DESIGN_REGELN", re.search(r'<div class="pc-seg pc-seg-other" style="width:[\d.]+%"></div><div class="pc-seg pc-seg-fav"', c1) is not None)
rows_c1 = re.findall(r'<div class="pc-lrow">.*?</div>', c1)
check("Maerkte mit Live-Chancen: Spread, Total, Team Total Heim und Gast (je eine Zeile, Hauptlinie aus dem Schnappschuss)", len(re.findall(r'class="pc-lrow"', c1)) == 4 and "Spread: 76ers −4,5" in c1 and "Total: 231,5" in c1 and "Team Total · 76ers: 118,0" in c1 and "Team Total · Cavaliers: 113,5" in c1 and c1.count("Hauptlinie") >= 4)
tot_p = round(n1.p_over_total(231.5) * 100)
check("Total-Zeile: Over/Under-Prozente = Live-Zahlen (Over 231,5)", f"Over {tot_p} %" in c1 and f"{100 - tot_p} % Under" in c1, f"{tot_p}")
spr_p = round(n1.p_spread("home", -4.5) * 100)
check("Spread-Zeile: Heim deckt -4,5 = Live-Zahl; links Gast, rechts Heim", f"{spr_p} % 76ers" in c1 and f"Cavaliers {100 - spr_p} %" in c1, f"{spr_p}")

c2 = card(at, "G2"); nn = lf.live_numbers_for_state(lf._feed.state(), snap.load()["games"])["G2"]
check("Karte vor dem Anpfiff: Anpfiffzeit statt Stand, 'Siegchance (Vorab)', Chip 'Vor dem Anpfiff', kein 0:0", "Anpfiff (Berlin)" in c2 and "Siegchance (Vorab)" in c2 and 'pc-chip-gray">Vor dem Anpfiff<' in c2 and ">0<" not in c2 and "lv-kick" in c2)
check("Vorab-Werte = Score-Projections-Werte: Sieger = Phi(Spread/13,2), Total Over 225,5 = Vorab-Funktion", f"{round(NormalDist().cdf(3.0 / 13.2) * 100)} % Celtics" in c2 and f"Over {round(lp.prob_above(225.0, 225.5, 18.6) * 100)} %" in c2
      and f"{100 - round(lp.prob_above(225.0, 225.5, 18.6) * 100)} % Under" in c2)
c3 = card(at, "G3")
check("Halbzeit: 'Halbzeit' statt Uhr (kein 12:00), Chip gelb, Stand 55 @ 58, Chancen vorhanden", "Halbzeit" in c3 and "12:00" not in c3 and "0:00" not in c3 and ">55<" in c3 and ">58<" in c3 and "Siegchance (live)" in c3 and 'pc-chip-yellow">Halbzeit<' in c3)
c4 = card(at, "G4")
check("Periodenende Q4 (leere Uhr, Gleichstand): 'Ende Q4', keine 12:00, Chancen mit Verlaengerung (Sieger nahe 50-60 %)", "Ende Q4" in c4 and "12:00" not in c4 and ">100<" in c4 and 40 <= [p for p in pcts(c4)][0] <= 60 and "Siegchance (live)" in c4)
c5 = card(at, "G5")
check("Verlaengerung: 'OT 2:00', Stand 110:110, Chancen; Total-Linie 232,5 bei 220 Punkten + Verlaengerung nahe 50 % (Over)", "OT 2:00" in c5 and ">110<" in c5 and "Siegchance (live)" in c5 and re.search(r"Over (\d+) %", c5) and 25 <= int(re.search(r"Over (\d+) %", c5).group(1)) <= 65)
c6 = card(at, "G6")
check("beendet: 'Ende', 'Endstand', Chip beendet grau, Chancen exakt 0/100 (Heim 120:101)", "Endstand" in c6 and "lv-final" in c6 and 'pc-chip-gray">beendet<' in c6 and "100 % Rockets" in c6 and "Mavericks 0 %" in c6 and "Siegchance" not in c6)
c7 = card(at, "G7")
check("beendet nach Verlaengerung: Endstand 116:118 inklusive Overtime, Hinweis '(nach Verlängerung)', Uhr 'Ende (OT)'", ">116<" in c7 and ">118<" in c7 and "(nach Verlängerung)" in c7 and "Ende (OT)" in c7)
check("beendetes Spiel ohne Schnappschuss (G7): Stand und Hinweis, KEINE Chancen und keine Maerkte", lf.NO_ANCHOR_NOTE in c7 and "pc-bar-labels" not in c7 and "lv-markets" not in c7)
check("Karte ohne Schnappschuss: Hinweistext NO_ANCHOR_NOTE sichtbar, sonst keine Zahlen erfunden", lf.NO_ANCHOR_NOTE in c7 and "%" not in re.sub(r"<[^>]+>", "", c7).replace("100 %", ""))
check("keine Exception und keine Streamlit-Warnung nach allen Karten", not problems(at))

# ================================================================= D) Wetten im Spiel, Tagesuebersicht mit Zahlen
S_B = FUT(2.5)
setup([row("B1", "Philadelphia 76ers", "Cleveland Cavaliers", 2, 3, "PT06M00.00S", hs=85, as_=60, start=S_B), row("B2", "Boston Celtics", "Miami Heat", 1, 0, "", "7:00 pm ET", hs=0, as_=0, start=FUT(3)),
       row("B3", "Houston Rockets", "Dallas Mavericks", 3, 4, "", "Final", hs=120, as_=101, start=FUT(1))], {"B1": box()},
      [(S_B, "Philadelphia 76ers", "Cleveland Cavaliers", version()), (FUT(1), "Houston Rockets", "Dallas Mavericks", version(226.0, 4.0, 115.0, 111.0, (4.5, 226.5))), (FUT(3), "Boston Celtics", "Miami Heat", version(225.0, 3.0, 114.0, 111.0, (-3.5, 225.5)))])
G_B = (DAY, S_B, "Philadelphia 76ers", "Cleveland Cavaliers")
ds.set_bet(*G_B, "winner", side="home", odds=1.5, stake=20)
ds.set_bet(*G_B, "total", side="under", line=144.5, odds=2.0, stake=10)
ds.set_bet(*G_B, "team_total_home", side="over", line=84.5)
ds.set_bet(DAY, FUT(1), "Houston Rockets", "Dallas Mavericks", "spread", side="home", line=-4.5, odds=1.9, stake=5)
ds.set_bet(DAY, FUT(3), "Boston Celtics", "Miami Heat", "winner", side="away", odds=2.4, stake=5)
at = app().run(); H = html(at); cb = card(at, "B1")
check("Wetten: keine Exception", not problems(at), " | ".join(problems(at))[:200])
check("Spiel mit Wetten: Marker '🎯 3 Wetten' an der Karte und in der Uebersicht", "🎯 3 Wetten" in cb and re.search(r'lv-oteams">Cavaliers @ 76ers</span>.*?🎯 3<', H) is not None)
check("Wett-Zeilen ersetzen die Hauptlinien-Zeilen der Maerkte mit Wette (Total, Team Total Heim); Maerkte ohne Wette zeigen weiter die Hauptlinie", cb.count("pc-lrow pc-lrow-chip lv-bet") == 3 and "Total: Under 144,5" in cb and "Team Total · 76ers: Over 84,5" in cb and "Sieger: 76ers gewinnt" in cb
      and "Spread: 76ers −4,5" in cb and "Team Total · Cavaliers: 113,5" in cb and "Total: 231,5" not in cb and "Wette</span>" in cb)
check("Total Under 144,5 bei 145 Punkten: Status 'Verloren' (rot), Chance 0 %, Quote/Einsatz/Verlust", 'lv-st lv-st-rot">Verloren<' in cb and "0 % Chance" in cb and "Quote 2,00 · Einsatz 10,00 · Verlust 10,00" in cb)
check("Team Total Heim Over 84,5 bei 85 Punkten: Status 'Gewonnen' (gruen), ohne Quote/Einsatz ('Quote — · Einsatz —')", 'lv-st lv-st-gruen">Gewonnen<' in cb and "Quote — · Einsatz —" in cb)
check("Sieger-Wette Heim: Status nach Chance (Auf Kurs gruen bei 85:60), Chance in Prozent, Quote 1,50 / Einsatz 20,00", 'lv-st lv-st-gruen">Auf Kurs<' in cb and re.search(r"(\d+) % Chance", cb) and "Quote 1,50 · Einsatz 20,00" in cb)
check("Wett-Balken in Statusfarbe (Gewonnen/Auf Kurs gruen #22c55e, Verloren rot #ef4444)", "background:#22c55e" in cb and "background:#ef4444" in cb)
cf = card(at, "B3")
check("beendetes Spiel mit Wette (Spread Heim -4,5 bei 120:101): 'Gewonnen', Gewinn 4,50", 'lv-st-gruen">Gewonnen<' in cf and "Gewinn 4,50" in cf and "🎯 1 Wette" in cf)
cw = card(at, "B2")
check("Wette vor dem Anpfiff: Status 'Wartet auf Anpfiff' (grau) mit Vorab-Chance", 'lv-st lv-st-grau">Wartet auf Anpfiff<' in cw and "Sieger: Heat gewinnt" in cw and re.search(r"(\d+) % Chance", cw))
sm = re.search(r'<div class="lv-sum">.*?</div></div></div>', H).group(0)
tiles = dict(re.findall(r'<div class="pc-label">([^<]+)</div><div class="lv-val[^"]*">([^<]+)</div>', sm))
check("Tagesuebersicht Zahlen: 5 Wetten, 2 gewonnen (Team Total, Spread), 1 verloren (Under), 2 offen (Sieger B1 + Wette vor Anpfiff), Einsatz 40,00", tiles["WETTEN"] == "5" and tiles["GEWONNEN"] == "2" and tiles["VERLOREN"] == "1" and tiles["OFFEN"] == "2" and tiles["EINSATZ"] == "40,00", str(tiles))
check("Gewinn/Verlust nur abgerechnete Wetten mit Quote und Einsatz: -10,00 (Under) + 4,50 (Spread) = -5,50, rot; Team Total ohne Quote zaehlt nicht (Hinweis)", tiles["GEWINN / VERLUST (ABGERECHNET)"] == "−5,50" and 'lv-val lv-neg' in H and "1 abgerechnete Wette(n) ohne Quote oder Einsatz" in H)
check("bets_live-Zahlen = Tabelle (Gegenprobe ueber die Funktion)", lt.build_page(lf._feed.state())["summary_data"] == {"wetten": 5, "offen": 2, "gewonnen": 2, "verloren": 1, "einsatz": 40.0, "gewinn_verlust": -5.5, "ohne_status": 0, "ohne_quote_oder_einsatz": 1})

# Wette ohne Schnappschuss (Spiel ohne Schnappschuss, aber mit Wette): Wette sichtbar, Hinweis, kein Status
setup([row("N1", "Boston Celtics", "Miami Heat", 2, 3, "PT06M00.00S", hs=70, as_=65, start=FUT(2))], {"N1": box()})
ds.set_bet(DAY, FUT(2), "Boston Celtics", "Miami Heat", "total", side="over", line=230.5, odds=1.9, stake=10)
at = app().run(); cn = card(at, "N1")
_cn_flags = [lf.NO_ANCHOR_NOTE in cn, "pc-bar-labels" not in cn, "Total: Over 230,5" in cn, "kein Status" in cn, "Quote 1,90 · Einsatz 10,00" in cn, ">70<" in cn, ">65<" in cn, not problems(at)]
check("Spiel ohne Schnappschuss mit Wette: Stand ohne Chancen, NO_ANCHOR_NOTE, Wette mit Quote/Einsatz aber 'kein Status'", all(_cn_flags), str(_cn_flags) + " " + " | ".join(problems(at))[:300])
check("Uebersicht: Wette ohne Status wird gezaehlt und erklaert", '1 Wette(n) ohne Status' in html(at) and re.search(r'lv-val ">1</div>', html(at)) is not None or "ohne Status" in html(at))

# ================================================================= E) Fehlerzustand, Aktualisieren, Zwischenspeicher
setup(ROWS, BOXES, SNAPS)
at = app().run()
c0 = counters(); g1_before = card(at, "G1")
at.run(); at.run()
check("App-Reruns (z. B. Klick in anderen Tabs) rufen NICHT neu ab: keine NBA-, Odds-, BDL- oder ESPN-Abrufe", counters() == c0, f"{c0} -> {counters()}")
NOW[0] += 5
at.button(key="sp_refresh").click().run()
check("Knopf 'Aktualisieren' nach 5 s: Zwischenspeicher haelt (kein neuer Scoreboard-Abruf, gleiche Abrufzahl)", counters() == c0 and not problems(at), f"{c0} -> {counters()}")
NOW[0] += 12
FN["nba_status"] = 403
at.button(key="sp_refresh").click().run()
Hh = html(at); n_calls = counters()
check("'Aktualisieren' nach 17 s: genau EIN neuer Scoreboard-Abruf (Boxscores erst nach 30 s), ESPN als Fallback gefragt", FN["nba_calls"] == c0[0] + 1 and FN["espn_calls"] == c0[3] + 1, f"{c0} -> {n_calls}")
check("403: Fehler deutlich sichtbar (rote Zeile 'Daten veraltet seit 17 Sekunden', HTTP 403, naechster Versuch), keine Exception", 'lv-status-line lv-status-err' in Hh and "Daten veraltet seit 17 Sekunden" in Hh and "HTTP 403" in Hh and "nächster Versuch in 30 s" in Hh and not problems(at), Hh[Hh.index("lv-status-line"):][:240])
check("403: letzte gute Werte bleiben angezeigt (gleiche Karten, gleicher Stand 60:85, gleiche Prozente)", cards(at) == ["G3", "G1", "G4", "G5", "G2", "G6", "G7"] and ">85<" in card(at, "G1") and re.findall(r"\d+ %", card(at, "G1")) == re.findall(r"\d+ %", g1_before))
check("403: ESPN-Fallback ohne zuordenbare Spiele: Hinweis, keine Fallback-Daten", "keine zuordenbaren Spiele" in Hh and "Stand von ESPN" not in Hh)
NOW[0] += 20
FN["nba_status"] = 200; NOW[0] += 40
at.button(key="sp_refresh").click().run()
Hx = html(at)
check("danach wieder da: Fehlerzeile weg, Status 'ok', aktuelle Daten", 'lv-status-line lv-status-err' not in Hx and 'lv-status-line lv-status-ok' in Hx and "NBA.com · aktuell" in Hx)

# ESPN-Fallback im Tab: Quelle sichtbar
setup(ROWS[:2], {"G1": box()}, SNAPS[:2])
at = app().run()
NOW[0] += 20
FN["nba_status"] = 403
def espn_event(eid, home, away, state_, period, clock, detail, hs, as_, date):
    return {"id": eid, "date": date, "status": {"clock": 0.0, "displayClock": clock, "period": period, "type": {"state": state_, "detail": detail, "description": detail}},
            "competitions": [{"competitors": [{"homeAway": "home", "score": str(hs), "team": {"displayName": home, "name": home.split()[-1]}}, {"homeAway": "away", "score": str(as_), "team": {"displayName": away, "name": away.split()[-1]}}]}]}
FN["espn"] = {"events": [espn_event("e1", "Philadelphia 76ers", "Cleveland Cavaliers", "in", 4, "3:00", "3:00 - 4th Quarter", 95, 80, S1), espn_event("e2", "Boston Celtics", "Miami Heat", "pre", 0, "0.0", "x", 0, 0, S2)]}
at.button(key="sp_refresh").click().run()
He = html(at)
check("ESPN springt ein: Statuszeile gelb 'Quelle ESPN', NBA.com-Fehler mit Statuscode, Karte zeigt ESPN-Stand 80:95, Chip 'Stand von ESPN', Uhr 'Q4 3:00'", 'lv-status-line lv-status-warn' in He and "Quelle ESPN" in He and "HTTP 403" in He and ">95<" in card(at, "G1") and ">80<" in card(at, "G1") and "Stand von ESPN" in card(at, "G1") and "Q4 3:00" in card(at, "G1") and not problems(at))
FN["nba_status"] = 200

# Spiele anderer Tage und Spieltag ohne Spiele
other_day = (lf.game_day_us({"gameTimeUTC": iso(real_now - 30 * 3600)}))
setup([row("V1", "Memphis Grizzlies", "Sacramento Kings", 3, 4, "", "Final", hs=99, as_=98, start=iso(real_now - 30 * 3600), day="2000-01-01")], {}, (), board_day="2000-01-01")
at = app().run(); Ho = html(at)
check("Scoreboard zeigt nur einen anderen Spieltag: keine Karten, kleiner Hinweis (nicht als Karte), Meldung 'noch keine Spiele'", cards(at) == [] and "eines anderen Spieltags" in Ho and "steht noch auf dem Scoreboard" in Ho and "noch keine Spiele gelistet" in Ho and "Grizzlies" not in " ".join(m.value for m in at.tabs[tab_idx(at)].markdown if "pc-card" in m.value and "data-game" in m.value)
      and "zeigt noch den Spieltag" in Ho and not problems(at))
setup([row("W1", "Boston Celtics", "Miami Heat", 1, 0, "", "x", hs=0, as_=0, start=FUT(2)), row("V1", "Memphis Grizzlies", "Sacramento Kings", 3, 4, "", "Final", hs=99, as_=98, start=iso(real_now - 30 * 3600), day="2000-01-01")], {}, ())
at = app().run(); Ho = html(at)
check("Karten nur fuer den aktuellen Spieltag (W1); Spiel eines frueheren Tages nur als Hinweis", cards(at) == ["W1"] and "1 Spiel eines anderen Spieltags steht noch auf dem Scoreboard" in Ho)
setup([], {}, ())
at = app().run()
check("leeres Scoreboard: keine Karten, Meldung, kein Absturz", cards(at) == [] and "noch keine Spiele gelistet" in html(at) and any("keine Spiele" in i.value for i in at.info) and not problems(at))

# ================================================================= F) Aktualisierungs-Logik (ohne Streamlit)
class StubFeed:
    def __init__(self, state): self.st, self.n = state, 0
    def state(self, now=None): return self.st
    def refresh(self, now=None): self.n += 1; return self.st
class St:
    def __init__(self, games=(), error=None, fetched_at=1.0, age_s=10.0): self.games, self.error, self.fetched_at, self.age_s = games, error, fetched_at, age_s
class Gm:
    def __init__(self, status): self.status = status
live, fin = Gm("LIVE"), Gm("FINAL")
f = StubFeed(St((live,)))
check("Takt (Fragment-Lauf, automatisch an, Spiel laeuft): Abruf", lt.pick_state(f, False, True, True) is f.st and f.n == 1)
f = StubFeed(St((live,)))
lt.pick_state(f, False, False, True); check("Schalter aus: der Takt ruft NICHT ab", f.n == 0)
f = StubFeed(St((live,)))
lt.pick_state(f, False, True, False); check("normaler App-Rerun (kein Fragment-Lauf): kein Abruf", f.n == 0)
f = StubFeed(St((live,)))
lt.pick_state(f, True, False, False); check("Klick auf Aktualisieren: Abruf auch bei ausgeschaltetem Schalter", f.n == 1)
f = StubFeed(St((), fetched_at=None)); lt.pick_state(f, False, False, False)
check("allererstes Laden (noch nie abgerufen, kein Fehler): ein Abruf", f.n == 1)
f = StubFeed(St((), error="x", fetched_at=None)); lt.pick_state(f, False, True, False)
check("erster Abruf war fehlgeschlagen: App-Rerun ruft nicht erneut ab (nur der Takt)", f.n == 0)
f = StubFeed(St((fin,), age_s=100)); lt.pick_state(f, False, True, True); a = f.n
f = StubFeed(St((fin,), age_s=300)); lt.pick_state(f, False, True, True)
check("alle Spiele beendet ohne Fehler: Takt ruft nur alle 5 Minuten ab (100 s: nein, 300 s: ja)", a == 0 and f.n == 1)
f = StubFeed(St((fin,), error="403", age_s=100)); lt.pick_state(f, False, True, True)
check("Fehler: Takt versucht es weiter (auch wenn alle Spiele beendet)", f.n == 1 and lt.auto_due(St((), age_s=0)) and lt.auto_due(St((fin, live), age_s=0)))

# ================================================================= G) reine Anzeigefunktionen, Farben, nichts geschrieben
check("Prozent: 0 bis 100 (Live erreicht 0 und 100), kaufmaennisch gerundet, begrenzt", [lc.pct(x) for x in (0, 0.004, 0.005, 0.5, 0.995, 1.0, 1.2, -0.1)] == [0, 0, 1, 50, 100, 100, 100, 0])
check("Anpfiff in Berliner Zeit mit Wochentag; HH:MM; Spieltag-Text; unbekannt leer", lc.fmt_start("2026-10-22T23:00:00Z") == "Fr 23.10. 01:00 Uhr" and lc.fmt_hhmm("2026-10-22T23:00:00Z") == "01:00" and lc.fmt_day("2026-10-22") == "Do 22.10.2026" and lc.fmt_start(None) == "" and lc.fmt_hhmm("x") == "")
check("deutsche Zahlen in Wett-Zeilen (Komma, echtes Minus, 2 Nachkommastellen)", lc.fmt_money(10) == "10,00" and lc.fmt_money(None) == "—" and lc.fmt_money(-5.5) == "−5,50")
def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
check("Kontrast >= 4,5 : 1 fuer alle Status-Chips (Text gegen Hintergrund): gruen, gelb, orange, rot, grau, blau", all(ratio(v["text"], v["bg"]) >= 4.5 for v in lc.STATUS.values()), str({k: round(ratio(v["text"], v["bg"]), 1) for k, v in lc.STATUS.items()}))
check("Kontrast: Gewinn (gruen) und Verlust (rot) Zahlen gegen die Kartenflaeche, Hinweis- und Notizen-Text", ratio(lc.STATUS["gruen"]["text"], PALETTE["card_bg"]) >= 4.5 and ratio(lc.STATUS["rot"]["text"], PALETTE["card_bg"]) >= 4.5 and ratio(PALETTE["label"], PALETTE["card_bg"]) >= 4.5 and ratio(PALETTE["chip_gray_text"], PALETTE["chip_gray_bg"]) >= 4.5)
check("Balkenfarben der Wett-Zeilen sind unterscheidbar vom neutralen Balkenrest (Kontrast >= 1,6 : 1 gegen #3b4560)", all(ratio(v["bar"], PALETTE["bar_other"]) >= 1.6 for k, v in lc.STATUS.items() if k in ("gruen", "gelb", "orange", "rot")))
check("Stylesheet: Status-Klassen fuer alle sechs Farben", all(f".lv-st-{k}" in lc.LIVE_CSS for k in ("gruen", "gelb", "orange", "rot", "grau", "blau")))
check("Namen werden maskiert (kein HTML aus Teamnamen)", "&lt;b&gt;" in lc.render_status_html(type("S", (), {"error": None, "stale": False, "status_line": "<b>x</b>", "notice": None, "fallback_note": None, "other_day_games": ()})()))
check("nichts ins Projekt geschrieben: keine echte Datei veraendert oder neu angelegt (Tracking-Dateien inkl. day_bets.json, pregame_lines.json: Hash vorher = nachher)", real_snapshot() == real_tracking)
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API'", not page_checks.bad, "; ".join(page_checks.bad[:2]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
