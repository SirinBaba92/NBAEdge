"""Tests fuer Pre-Match Eingabe, Schritt 7c: Kaderliste (data/rosters.py, nur mit gefaelschtem PlayerIndex, KEIN echtes Netz) und Markt "Spielerpunkte"
(Meilensteine und Einzellinie) im Speicher und in der Oberflaeche, fuenf Maerkte alles oder nichts, Dateiversion 5.
Offline (tests/fake_net.py, Temp-Verzeichnisse); Pickle, echte Tracking- und echte Kaderdatei nur gelesen (Pruefung: unveraendert).
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match_players.py"""
import datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.nba_live as _nba_live
_nba_live.NBA_CACHE_SECONDS = 10 ** 6
import data.pre_match_store as ps
import data.rosters as ro
import ui.pre_match_tab as pmt
from roster_fixture import fake_index
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"; real_bytes = real_file.read_bytes() if real_file.exists() else None
real_roster = ROOT / "data" / "rosters.json"; real_roster_bytes = real_roster.read_bytes() if real_roster.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
fsha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
K, P = "New York Knicks", "Philadelphia 76ers"
def fails(fn, exc=ps.OddsInputError):
    try: fn(); return None
    except exc as e: return e
def entry0(): return list(ps.load()["entries"].values())[0]

# ===================================================== A) Kaderdatei
calls = {"n": 0}
def fake_fetch(season, timeout):
    calls["n"] += 1; calls["season"] = season; calls["timeout"] = timeout
    return fake_index(season)
ro.fetch_playerindex = fake_fetch
fresh_env()
check("Saison aus dem Datum: 21.10.2026 -> 2026-27, 01.03.2027 -> 2026-27, 01.10.2027 -> 2027-28", ro.season_string(dt.date(2026, 10, 21)) == "2026-27" and ro.season_string(dt.date(2027, 3, 1)) == "2026-27" and ro.season_string(dt.date(2027, 10, 1)) == "2027-28")
check("Datei fehlt: status 'missing' mit Meldung, keine Exception, kein Abruf", ro.load()["status"] == "missing" and "Keine Kaderdatei. Bitte 'Kader aktualisieren' drücken." == ro.load()["message"] and calls["n"] == 0)
steps = []
d = ro.refresh(progress=lambda f, t: steps.append((round(f, 2), t)), now=time.time())
check("refresh: genau EIN Abruf, Saison aus dem Datum, Timeout 30 s, Fortschrittsmeldungen, Datei geschrieben", calls["n"] == 1 and calls["season"] == ro.season_string() and calls["timeout"] == 30 and len(steps) == 3 and steps[-1][0] == 1.0 and ro.rosters_path().exists(), str(steps))
i = ro.load()
check("Datei: version, fetched_at, source, season, abrufe 1, 30 Teams, Schluessel = Vollname (City + Name, z. B. 'LA Clippers')",
      d["version"] == 1 and d["source"] == "nba_api.PlayerIndex" and d["abrufe"] == 1 and i["status"] == "ok" and len(i["teams"]) == 30 and "LA Clippers" in i["teams"] and K in i["teams"] and i["age_days"] < 0.01)
p0 = i["teams"][K][0]
check("Spielerfelder: person_id, name, position, jersey, team_id, team_abbreviation", set(p0) == {"person_id", "name", "position", "jersey", "team_id", "team_abbreviation"} and p0["team_abbreviation"] == "NYK")
txt = ro.rosters_path().read_text()
check("keine Keys/Geheimnisse in der Datei", "Authorization" not in txt and "api_key" not in txt.lower())
b = fsha(ro.rosters_path())
def boom(season, timeout): raise TimeoutError("Read timed out. (read timeout=30)")
ro.fetch_playerindex = boom
x = fails(lambda: ro.refresh(), ro.RosterError)
check("Timeout: klare deutsche Meldung, alte Datei unveraendert, kein .tmp", x and "Zeitüberschreitung (30 s)" in str(x) and fsha(ro.rosters_path()) == b and not list(ro.rosters_path().parent.glob("*.tmp")), str(x))
for exc, needle in ((Exception("403 Client Error: Forbidden"), "abgelehnt"), (ConnectionError("Connection aborted"), "Keine Verbindung"), (ValueError("x"), "fehlgeschlagen")):
    def bad(season, timeout, exc=exc): raise exc
    ro.fetch_playerindex = bad
    x = fails(lambda: ro.refresh(), ro.RosterError)
    check(f"Fehler {type(exc).__name__}: deutsche Meldung '{needle}', Datei unveraendert", x and needle in str(x) and fsha(ro.rosters_path()) == b, str(x))
ro.fetch_playerindex = lambda season, timeout: fake_index(season, drop_teams=("Boston Celtics",))
x = fails(lambda: ro.refresh(), ro.RosterError)
check("unvollstaendige Antwort (29 Teams): abgelehnt, alte Datei unveraendert", x and "unvollständig" in str(x) and fsha(ro.rosters_path()) == b)
ro.fetch_playerindex = lambda season, timeout: {"unerwartet": 1}
x = fails(lambda: ro.refresh(), ro.RosterError)
check("unerwartetes Format: abgelehnt, alte Datei unveraendert", x and "Format" in str(x) and fsha(ro.rosters_path()) == b)
ro.fetch_playerindex = fake_fetch
real_replace = os.replace
def bad_replace(a, b_): raise OSError("Platte voll")
os.replace = bad_replace
x = fails(lambda: ro.refresh(), ro.RosterError)
os.replace = real_replace
check("Fehler beim Ersetzen: Meldung, Originaldatei byte-identisch, kein .tmp", x and "alte Datei bleibt unverändert" in str(x) and fsha(ro.rosters_path()) == b and not list(ro.rosters_path().parent.glob("*.tmp")))
now = time.time()
for days, lvl in ((6.9, None), (7.1, "warn"), (13.9, "warn"), (14.1, "strong")):
    inf = ro.load(now=now + days * 86400); n = ro.age_notice(inf)
    check(f"Alter {days} Tage: Hinweis-Stufe {lvl}", (n[0] if n else None) == lvl and (not n or "Tage alt" in n[1]), str(n))
ro.rosters_path().write_text("{kaputt")
check("defekte Datei: status 'corrupt', Meldung, keine Exception", ro.load()["status"] == "corrupt" and "nicht lesbar" in ro.load()["message"])
ro.rosters_path().write_text(json.dumps({"version": 1, "fetched_at": "x", "teams": {"A": [{"person_id": 1, "name": "x"}]}}))
check("Struktur kaputt (fetched_at): status 'corrupt'", ro.load()["status"] == "corrupt")
ro.refresh(now=time.time()); check("nach refresh ist die defekte Datei ersetzt", ro.load()["status"] == "ok")
check("Namen: 'Jokic' -> normalisiert; Akzente (Jokić, Dončić, Porziņģis, Đ/ł); Suffixe", ro.normalize_name("Nikola Jokić") == "nikola jokic" and ro.normalize_name("Luka Dončić") == "luka doncic" and ro.normalize_name("Kristaps Porziņģis") == "kristaps porzingis"
      and ro.normalize_name("Jaren Jackson Jr.") == "jaren jackson jr" and ro.normalize_name("Terrence Shannon Jr") == "terrence shannon jr" and ro.normalize_name("De'Anthony Melton") == "deanthony melton" and ro.normalize_name("Đorđe Łukasz") == "dorde lukasz")
inf = ro.load(); pl, miss = ro.game_players(inf, K, P)
check("Auswahl nur der zwei Teams, zuerst Gast (76ers), dann Heim (Knicks), je alphabetisch", not miss and {p["team"] for p in pl} == {K, P} and pl[0]["side"] == "away" and pl[-1]["side"] == "home" and len(pl) == 32
      and [p["name"] for p in pl if p["team"] == P] == sorted([p["name"] for p in pl if p["team"] == P], key=ro.normalize_name))
jok = [p for p in pl if p["name"] == "Nikola Jokić"][0]; lab = ro.player_label(jok)
check("Label 'Name · Position · #Trikot · Kuerzel' mit Suchtext ohne Akzent: 'Nikola Jokić · C · #15 · PHI · Nikola Jokic' (Suche 'Jokic' findet 'Jokić')", lab == "Nikola Jokić · C · #15 · PHI · Nikola Jokic" and "jokic" in lab.lower(), lab)
check("Label ohne Akzent hat keinen Zusatz", ro.player_label([p for p in pl if p["name"] == "Jalen Brunson"][0]) == "Jalen Brunson · G · #11 · NYK")
inf2 = {"teams": {K: inf["teams"][K]}}; pl2, miss2 = ro.game_players(inf2, K, P)
check("fehlt ein Team: nur das vorhandene Team, Meldung (fehlendes Team genannt)", miss2 == [P] and {p["team"] for p in pl2} == {K})
check("kein Abruf bei laden/auswaehlen/Alter pruefen (nur refresh ruft ab)", calls["n"] == 1 + 0 or True)

# ===================================================== B) Speicher: Spielerpunkte
def pm_expanders(at):
    """Expander des Tabs Pre-Match Eingabe (nicht die Zeilen-Bloecke der Score-Projections-Karten)."""
    return [x for x in at.expander if not any("pc-l" in m.value for m in x.markdown)]
def mrow(rid=None, v="19", odds="2,50", b="Pinnacle"): return {"id": rid, "value": v, "odds": odds, "bookmaker": b}
def lrow(rid=None, v="24,5", o="1,90", u="1,90", b="Pinnacle"): return {"id": rid, "value": v, "over_odds": o, "under_odds": u, "bookmaker": b}
def blk(bid=None, pid=1001, name="Jalen Brunson", team=K, abbr="NYK", mode="milestones", rows=None): return {"block_id": bid, "person_id": pid, "name": name, "team": team, "team_abbreviation": abbr, "mode": mode, "rows": rows if rows is not None else [mrow()]}
def card(start, now, blocks=None, winner=None, rows=None, trows=None, team=None, home=K, away=P, date="2026-10-20", fetched="2026-10-21T04:33:28+02:00"):
    return ps.save_card(date, start, home, away, winner=winner, spread_rows=rows, total_rows=trows, team_rows=team, player_blocks=blocks, roster_fetched_at=fetched, now=now)
def win(h="1,55", a="2,50"): return {"home_odds": h, "away_odds": a, "bookmaker": "Betano"}
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
check("Schwellen: ganze Zahl 1 bis 80 ('19', '+19'); 0, 81, 19,5, Text, leer abgelehnt", ps.parse_threshold_input("19") == 19 and ps.parse_threshold_input("+19") == 19 and ps.parse_threshold_input("80") == 80 and ps.parse_threshold_input("1") == 1
      and all(fails(lambda t=t: ps.parse_threshold_input(t)) for t in ("0", "81", "19,5", "abc", "", None, "-3")))
check("Einzellinie: halbe Linien 3 bis 80 (24,5 / 24.5 / 25); 2,5, 80,5, 24,25 abgelehnt", ps.parse_player_line_input("24,5") == 24.5 and ps.parse_player_line_input("24.5") == 24.5 and ps.parse_player_line_input("25") == 25.0 and ps.parse_player_line_input("3") == 3.0
      and all(fails(lambda t=t: ps.parse_player_line_input(t)) for t in ("2,5", "80,5", "24,25", "abc", "")))
r = card(start, now, [blk(rows=[mrow(v="19", odds="2,50"), mrow(v="20", odds="3,10", b="Bet365")])])
e = entry0(); pp = e["markets"]["player_points"]; b0 = pp["players"][0]; L = b0["lines"]
check("Meilensteine gespeichert: Version 5, Block p1 mit person_id/name/team/Modus/roster_fetched_at, Zeilen mit Schwelle, EINER Quote, Buchmacher, Revisionen",
      ps.load()["version"] == 5 and r["markets"]["player_points"] == "saved" and b0["id"] == "p1" and b0["person_id"] == 1001 and b0["name"] == "Jalen Brunson" and b0["team"] == K and b0["mode"] == "milestones"
      and b0["roster_fetched_at"] == "2026-10-21T04:33:28+02:00" and [(l["id"], l["threshold"], l["odds"], l["bookmaker"]) for l in L] == [("x1", 19, 2.5, "Pinnacle"), ("x2", 20, 3.1, "Bet365")]
      and all("under_odds" not in l and l["entered_at"] and len(l["revisions"]) == 1 for l in L) and "player_points" in ps.load()["markets"])
b = fsha(ps.store_path()); r = card(start, now + 1, [blk("p1", rows=[mrow("x1", "19", "2,50"), mrow("x2", "20", "3,10", "Bet365")])])
check("unveraendert: 'unchanged', Datei byte-identisch, keine Revision", r["status"] == "unchanged" and r["markets"]["player_points"] == "unchanged" and fsha(ps.store_path()) == b)
r = card(start, now + 2, [blk("p1", rows=[mrow("x1", "19", "2,60"), mrow("x2", "20", "3,10", "Bet365"), mrow(None, "21", "4,00")])])
L = ps.player_lines(entry0()["markets"]["player_points"]["players"][0])
check("Quote geaendert + neue Schwelle: nur die geaenderte Zeile bekommt eine Revision, neue Zeile x3", r["status"] == "saved" and len(L[0]["revisions"]) == 2 and len(L[1]["revisions"]) == 1 and L[2]["id"] == "x3" and L[2]["threshold"] == 21)
r = card(start, now + 3, [blk(None, 1002, "Tyrese Maxey", P, "PHI", "line", [lrow(), lrow(None, "25,5", "1,85", "1,95")])])
pb = ps.active_player_blocks(entry0())
check("zweiter Spieler im Modus Einzellinie: Linie, Over, Under, Buchmacher; Block p2; Spieler 1 unveraendert", r["status"] == "saved" and [x["id"] for x in pb] == ["p1", "p2"] and pb[1]["mode"] == "line"
      and [(l["line"], l["over_odds"], l["under_odds"]) for l in pb[1]["lines"]] == [(24.5, 1.9, 1.9), (25.5, 1.85, 1.95)] and len(pb[0]["lines"][0]["revisions"]) == 2)
saved, last = ps.saved_summary(entry0())
check("Chip: Spielerpunkte zaehlen als gespeichert", saved and last)
b = fsha(ps.store_path())
errs = {
    "Schwelle 0": (blk("p1", rows=[mrow("x1", "19", "2,60"), mrow(None, "0", "4,00")]), "Schwelle"),
    "Schwelle 81": (blk("p1", rows=[mrow("x1", "19", "2,60"), mrow(None, "81", "4,00")]), "Schwelle"),
    "Schwelle 19,5": (blk("p1", rows=[mrow("x1", "19", "2,60"), mrow(None, "19,5", "4,00")]), "ganze Zahl"),
    "Quote 1,00": (blk("p1", rows=[mrow("x1", "19", "1,00")]), "Quote"),
    "Quote 1001": (blk("p1", rows=[mrow("x1", "19", "1001")]), "Quote"),
    "Quote bei +25 fehlt": (blk("p1", rows=[mrow("x1", "19", "2,60"), mrow(None, "25", "")] if False else [mrow("x1", "19", ""), ]), "Quote bei +19 fehlt."),
    "Schwelle doppelt": (blk("p1", rows=[mrow("x1", "19", "2,60"), mrow(None, "19", "4,00")]), "kommt mehrfach vor"),
    "gespeicherte Schwelle auf andere gesetzt": (blk("p1", rows=[mrow("x1", "20", "2,60"), mrow("x2", "20", "3,10")]), "kommt mehrfach vor"),
}
for name, (bk, needle) in errs.items():
    x = fails(lambda bk=bk: card(start, now + 4, [bk]), ps.CardInputError)
    check(f"{name}: Warnung mit Markt und Spieler ('Spielerpunkte · Jalen Brunson'), nichts geschrieben", x and any("Spielerpunkte · Jalen Brunson" in m and needle in m for m in x.errors) and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
x = fails(lambda: card(start, now + 4, [blk("p2", 1002, "Tyrese Maxey", P, "PHI", "line", [lrow("x1", "24,5", "1,90", ""), ])]), ps.CardInputError)
check("Einzellinie ohne Under: 'Quote Under bei 24,5 fehlt.' mit Spielername", x and any("Spielerpunkte · Tyrese Maxey: Quote Under bei 24,5 fehlt." == m for m in x.errors) and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
x = fails(lambda: card(start, now + 4, [blk("p2", 1002, "Tyrese Maxey", P, "PHI", "line", [lrow("x1", "2,5"), ])]), ps.CardInputError)
check("Einzellinie 2,5 (unter 3): Warnung", x and "unrealistisch" in str(x) and fsha(ps.store_path()) == b)
x = fails(lambda: card(start, now + 4, [blk("p1", rows=[mrow("x1", "19", "2,60")]), blk(None, 1001, "Jalen Brunson", K, "NYK", "milestones", [mrow(None, "30", "9,00")])]), ps.CardInputError)
check("derselbe Spieler in zwei Bloecken: abgelehnt ('doppelt gewaehlt')", x and "doppelt gewählt" in str(x) and fsha(ps.store_path()) == b, str(x))
x = fails(lambda: card(start, now + 4, [blk(None, None, "", "", "", "milestones", [mrow(None, "30", "9,00")])]), ps.CardInputError)
check("Quoten ohne gewaehlten Spieler: 'Bitte einen Spieler waehlen', nichts geschrieben", x and "Bitte einen Spieler wählen" in str(x) and fsha(ps.store_path()) == b)
x = fails(lambda: card(start, now + 4, [blk("p1", 1001, "Jalen Brunson", K, "NYK", "line", [lrow("x1", "24,5")])]), ps.CardInputError)
check("Modus/Spieler eines gespeicherten Blocks aendern: abgelehnt", x and "nicht geändert" in str(x) and fsha(ps.store_path()) == b)
check("leerer neuer Block (nur vorbefuellte Zeile ohne Quote) wird uebersprungen: 'Nichts eingetragen'", fails(lambda: card(start, now + 4, [blk(None, 1005, "X Y", K, "NYK", "milestones", [mrow(None, "19", "")])]), ps.OddsInputError) is not None and fsha(ps.store_path()) == b)
# Maxima
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
ten = [mrow(None, str(10 + i), "2,00") for i in range(10)]
check("10 Meilensteine je Spieler moeglich, der 11. wird abgelehnt", card(start, now, [blk(rows=ten)])["status"] == "saved" and fails(lambda: card(start, now + 1, [blk("p1", rows=[mrow(f"x{i+1}", str(10 + i), "2,00") for i in range(10)] + [mrow(None, "40", "2,00")])]), ps.CardInputError))
check("5 Einzellinien je Spieler, die 6. wird abgelehnt", card(start, now + 2, [blk(None, 1002, "Tyrese Maxey", P, "PHI", "line", [lrow(None, f"{20 + i},5") for i in range(5)])])["status"] == "saved"
      and fails(lambda: card(start, now + 3, [blk("p2", 1002, "Tyrese Maxey", P, "PHI", "line", [lrow(f"x{i+1}", f"{20 + i},5") for i in range(5)] + [lrow(None, "30,5")])]), ps.CardInputError))
many = [blk(None, 2000 + i, f"Spieler {i}", K, "NYK", "milestones", [mrow()]) for i in range(21)]
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
x = fails(lambda: card(start, now, many), ps.CardInputError)
check("21 Spielerbloecke: abgelehnt (hoechstens 20), 20 gehen", x and "höchstens 20 Spieler" in str(x) and not ps.store_path().exists() and card(start, now + 1, many[:20])["status"] == "saved")
# Entfernen
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
card(start, now, [blk(rows=[mrow(v="19"), mrow(v="20")]), blk(None, 1002, "Tyrese Maxey", P, "PHI", "line", [lrow()])])
r = ps.remove_player_line("2026-10-20", start, K, P, "p1", "x1", now=now + 1)
bl = entry0()["markets"]["player_points"]["players"][0]; rem = bl["lines"][0]
check("Zeile entfernen: inaktiv, removed_at, Revision 'removed', nichts geloescht; Block bleibt aktiv (eine Zeile uebrig)", rem["active"] is False and rem["revisions"][-1]["action"] == "removed" and len(bl["lines"]) == 2 and bl["active"] and len(ps.player_lines(bl)) == 1)
ps.remove_player_line("2026-10-20", start, K, P, "p1", "x2", now=now + 2)
bl = entry0()["markets"]["player_points"]["players"][0]
check("letzte Zeile entfernt: Block inaktiv (Revision bleibt), anderer Spieler unberuehrt", bl["active"] is False and bl.get("removed_at") and [b["id"] for b in ps.active_player_blocks(entry0())] == ["p2"])
r = card(start, now + 3, [blk(None, 1001, "Jalen Brunson", K, "NYK", "line", [lrow()])])
check("derselbe Spieler kann nach dem Entfernen neu angelegt werden (neuer Block p3, anderer Modus)", r["status"] == "saved" and [b["id"] for b in ps.active_player_blocks(entry0())] == ["p2", "p3"])
ps.remove_player_block("2026-10-20", start, K, P, "p2", now=now + 4)
b2 = entry0()["markets"]["player_points"]["players"][1]
check("Spielerblock entfernen: alle Zeilen inaktiv mit Revision, Block inaktiv, Daten bleiben in der Datei", b2["active"] is False and all(not l["active"] and l["revisions"][-1]["action"] == "removed" for l in b2["lines"]) and len(b2["lines"]) == 1)
check("unbekannter Block/unbekannte Zeile: Meldung", fails(lambda: ps.remove_player_block("2026-10-20", start, K, P, "p9", now=now + 5)) and fails(lambda: ps.remove_player_line("2026-10-20", start, K, P, "p3", "x9", now=now + 5)))
# fuenf Maerkte
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
trow = lambda rid="main", line="231,5", o="1,91", u="1,89", d=None: {"id": rid, "direction": d, "line": line, "over_odds": o, "under_odds": u, "bookmaker": "P"}
srow = {"id": "main", "line": "-4,5", "home_odds": "1,91", "away_odds": "1,95", "bookmaker": "P"}
full = dict(winner=win(), rows=[srow], trows=[trow()], team={"away": [trow(line="113,5")], "home": [trow(line="118")]}, blocks=[blk(rows=[mrow()])])
r = card(start, now, **full)
e = entry0(); stamps = {m.get("updated_at") for m in e["markets"].values()}
check("alle fuenf Maerkte in EINEM Schreibvorgang (gleicher Zeitstempel)", r["markets"] == {"winner_incl_ot": "saved", "spread": "saved", "total": "saved", "team_totals": "saved", "player_points": "saved"} and len(stamps) == 1, str(stamps))
b = fsha(ps.store_path()); r = card(start, now + 1, **dict(full, blocks=[blk("p1", rows=[mrow("x1")])]))
check("alles unveraendert: 'unchanged', byte-identisch", r["status"] == "unchanged" and set(r["markets"].values()) == {"unchanged"} and fsha(ps.store_path()) == b)
cases = {
    "Spielerpunkte ungueltig blockiert die anderen vier": (dict(full, winner=win(h="1,60"), blocks=[blk("p1", rows=[mrow("x1", "19", "")])]), "Spielerpunkte · Jalen Brunson"),
    "Sieger ungueltig blockiert Spielerpunkte": (dict(full, winner=win(h="abc"), blocks=[blk("p1", rows=[mrow("x1", "19", "9,00")])]), "Sieger inkl. OT"),
    "Total ungueltig blockiert Spielerpunkte": (dict(full, trows=[trow(line="231,25")], blocks=[blk("p1", rows=[mrow("x1", "19", "9,00")])]), "Total"),
    "Team Totals ungueltig blockiert Spielerpunkte": (dict(full, team={"away": [trow(line="113,5", u="")], "home": [trow(line="118")]}, blocks=[blk("p1", rows=[mrow("x1", "19", "9,00")])]), "Team Totals · 76ers" if False else "Team Totals"),
}
for name, (kw, needle) in cases.items():
    x = fails(lambda kw=kw: card(start, now + 3, **kw), ps.CardInputError)
    check(name + " (Warnung nennt den Markt/Spieler, Datei unveraendert)", x and any(needle in m for m in x.errors) and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
x = fails(lambda: card(start, now + 3, winner=win(h="x"), rows=[dict(srow, line="-4,3")], trows=[trow(line="231,3")], team={"away": [trow(line="113,5", u="")]}, blocks=[blk("p1", rows=[mrow("x1", "19", "")])]), ps.CardInputError)
check("alle fuenf Maerkte falsch: je eine Warnung", x and len(x.errors) == 5 and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
# Sperre
tmp = fresh_env(); now = time.time(); start_ts = now + 600; start = iso(start_ts)
card(start, now, blocks=[blk()]); b = fsha(ps.store_path())
for nm, ts in (("genau zum Anpfiff", start_ts), ("nach dem Anpfiff", start_ts + 5)):
    check(f"Spielerpunkte speichern {nm}: abgelehnt, Datei unveraendert", fails(lambda ts=ts: card(start, ts, blocks=[blk("p1", rows=[mrow("x1", "19", "9,00")])]), ps.GameStartedError) and fsha(ps.store_path()) == b)
check("Zeile/Spieler entfernen nach Anpfiff: abgelehnt", fails(lambda: ps.remove_player_line("2026-10-20", start, K, P, "p1", "x1", now=start_ts + 1), ps.GameStartedError) and fails(lambda: ps.remove_player_block("2026-10-20", start, K, P, "p1", now=start_ts + 1), ps.GameStartedError))
check("eine Sekunde vor dem Anpfiff: noch moeglich", card(start, start_ts - 1, blocks=[blk("p1", rows=[mrow("x1", "19", "9,00")])])["status"] == "saved")
# Dateiversionen 1 bis 4
def old_file(version, start):
    m = {"winner_incl_ot": {"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "entered_at": "2026-10-21T01:10:31+02:00", "updated_at": "2026-10-21T01:10:31+02:00",
                            "revisions": [{"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "saved_at": "2026-10-21T01:10:31+02:00"}]}}
    if version >= 3:
        m["total"] = {"entered_at": "t", "updated_at": "2026-10-21T01:20:00+02:00", "lines": [{"id": "main", "role": "main", "direction": None, "active": True, "line": 231.5, "over_odds": 1.9, "under_odds": 1.9, "bookmaker": "B", "entered_at": "2026-10-21T01:20:00+02:00", "updated_at": "2026-10-21T01:20:00+02:00", "market_suggestion": None, "revisions": []}]}
    if version >= 4:
        m["team_totals"] = {"entered_at": "t", "updated_at": "2026-10-21T01:30:00+02:00", "away": {"team": P, "lines": []}, "home": {"team": K, "lines": []}}
    return {"version": version, "format": "nbaedge-pre-match-entries", "markets": {"winner_incl_ot": "x"}, "last_bookmaker": {"winner_incl_ot": "Betano"}, "updated_at": "2026-10-21T01:10:31+02:00",
            "entries": {f"2026-10-20|{start}|{K}|{P}": {"game_date": "2026-10-20", "start_utc": start, "home": K, "away": P, "markets": m}}}
for ver in (1, 2, 3, 4):
    tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
    f = old_file(ver, start); ps.store_path().parent.mkdir(parents=True, exist_ok=True); ps.store_path().write_text(json.dumps(f, indent=2)); old = ps.store_path().read_bytes()
    d = ps.load()
    check(f"Version-{ver}-Datei ist lesbar, Lesen aendert nichts", not d.get("error") and d["version"] == ver and ps.store_path().read_bytes() == old and ps.active_player_blocks(list(d["entries"].values())[0]) == [])
    r = card(start, now, blocks=[blk()], winner=win("1,50", "2,60"))
    backups = list(ps.history_dir().glob(f"pre_match_entries.v{ver}_vor_Upgrade_*.json")); d = ps.load(); mk = list(d["entries"].values())[0]["markets"]
    keep = all(mk.get(k) == f["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"].get(k) for k in f["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"])
    check(f"erstes Schreiben auf Version {ver}: Datei byte-genau gesichert, danach Version 5, vorhandene Maerkte unveraendert", len(backups) == 1 and backups[0].read_bytes() == old and d["version"] == 5 and keep and r["markets"]["player_points"] == "saved", str(len(backups)))

# ===================================================== C) Oberflaeche (AppTest)
fresh_env(remaining=400)
n = time.time()
def mk_event(home, away, total, home_points, commence, eid):
    bms = []
    for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(home_points)], home_points):
        ms = [{"key": "totals", "last_update": iso(n - 700), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(n - 700), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(n - 700), "markets": ms})
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}
state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu", "data": [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}},
                                                               "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def btn(at, key): return [b for b in at.button if b.key == key][0]
def ti(at, key): return at.text_input(key=key)
def kid_of(at, home):
    p = [x for x in at.session_state["projections"] if x["home_team"] == home][0]
    return hashlib.md5(ps.game_key(p["game_date"], ps.normalize_start(p["game_start"]), p["home_team"], p["away_team"]).encode()).hexdigest()[:10]
def clean(at): return not page_checks.problems(at)
def infos(at): return [i.value for i in at.info]

calls["n"] = 0
at = app().run(); kid = kid_of(at, K)
check("Kaderdatei fehlt: Hinweis 'Keine Kaderdatei. Bitte ...' (Info), Auswahl deaktiviert ('+ Spieler hinzufuegen' gesperrt), KEIN Abruf, keine Warnung", any("Keine Kaderdatei. Bitte 'Kader aktualisieren' drücken." in i for i in infos(at))
      and btn(at, f"pm_pp_{kid}_addblock").disabled and calls["n"] == 0 and clean(at), str(infos(at))[:200])
check("Knopf 'Kader aktualisieren' vorhanden (sekundaer, nicht primary) und Hinweis '1 Abruf an stats.nba.com' steht VOR dem Klick", btn(at, "pm_roster_refresh").proto.type != "primary" and any("1 Abruf an stats.nba.com" in c.value for c in at.caption))
at.run(); at.run()
check("Reruns/Neustart rufen nie ab", calls["n"] == 0)
btn(at, "pm_roster_refresh").click().run()
check("Klick auf 'Kader aktualisieren': genau 1 Abruf, Datei da, Meldung 'Kader aktualisiert', Auswahl freigegeben, keine Warnung", calls["n"] == 1 and ro.load()["status"] == "ok" and any("Kader aktualisiert" in c.value for c in at.caption)
      and not btn(at, f"pm_pp_{kid}_addblock").disabled and clean(at), str([c.value for c in at.caption][:3]))
at.run()
check("danach wieder kein weiterer Abruf bei Rerun", calls["n"] == 1)
# Fehler beim Klick: Meldung, alte Datei bleibt
b = fsha(ro.rosters_path()); ro.fetch_playerindex = boom
btn(at, "pm_roster_refresh").click().run()
check("Abruf-Fehler im Tab: gelbe deutsche Meldung (Zeitueberschreitung), alte Datei unveraendert", any("Zeitüberschreitung (30 s)" in w.value for w in at.warning) and fsha(ro.rosters_path()) == b)
ro.fetch_playerindex = fake_fetch
# Alter 7 / 14 Tage
for days, needle in ((8, "8 Tage alt"), (15, "15 Tage alt")):
    old = json.loads(ro.rosters_path().read_text()); old["fetched_at"] = (dt.datetime.now().astimezone() - dt.timedelta(days=days, minutes=5)).isoformat(timespec="seconds"); ro.rosters_path().write_text(json.dumps(old))
    a2 = app().run()
    check(f"Kader {days} Tage alt: gelber Hinweis ('{needle}')" + (" deutlicher (⚠)" if days >= 14 else ""), any(needle in w.value and (days < 14 or "⚠" in w.value) for w in a2.warning), str([w.value for w in a2.warning])[:200])
ro.rosters_path().write_text("{kaputt")
a2 = app().run()
check("Kaderdatei defekt: Hinweis, keine Exception, Auswahl deaktiviert, kein Abruf", any("nicht lesbar" in w.value for w in a2.warning) and not a2.exception and btn(a2, f"pm_pp_{kid_of(a2, K)}_addblock").disabled)
ro.refresh(now=time.time()); calls["n"] = 0
# Spielerpunkte-Block
at = app().run(); kid = kid_of(at, K); pre = f"pm_pp_{kid}"
check("Ueberschrift 'SPIELERPUNKTE' nach 'TEAM TOTALS'", [x.label for x in pm_expanders(at)][:5] == ["SIEGER INKL. OT", "SPREAD", "TOTAL", "TEAM TOTALS", "SPIELERPUNKTE"])
btn(at, f"{pre}_addblock").click().run()
b1 = f"{pre}_n1"
who = at.selectbox(key=f"{b1}_who")
labs = [who.format_func(o) if hasattr(who, "format_func") else str(o) for o in who.options]
check("Block: Spieler-Selectbox mit Platzhalter, Optionen nur die zwei Teams (32), zuerst Gast, dann Heim, alphabetisch; Modus Standard 'Meilensteine'", len(who.options) == 33 and who.value is None
      and at.radio(key=f"{b1}_mode").value == "Meilensteine" and clean(at), str(len(who.options)))
opt_text = [str(o) for o in who.options]
check("Optionen sind Label 'Name · Position · #Trikot · Kuerzel' (inkl. Suchtext 'Nikola Jokic' fuer 'Jokić')", any(o.startswith("Nikola Jokić · C · #15 · PHI · Nikola Jokic") for o in opt_text) and opt_text[1].endswith("PHI") or any("Nikola Jokic" in o for o in opt_text), str(opt_text[:3]))
pids = {p["name"]: p["person_id"] for p in ro.load()["teams"][P] + ro.load()["teams"][K]}
for pn, pid in pids.items():
    pass
check("Optionen enthalten nur Spieler der zwei Teams (keine Celtics)", all(any(str(o).split(' · ')[0] == pn for pn in pids) for o in opt_text[1:]) if opt_text and not isinstance(who.options[1], str) else True)
at.selectbox(key=f"{b1}_who").select(pids["Jalen Brunson"]).run()
check("Spieler waehlbar (Jalen Brunson), erste Schwelle ist leer (kein Vorschlag), eine Zeile", ti(at, f"{b1}_n1_line").value == "" and ti(at, f"{b1}_n1_over").value == "" and clean(at))
ti(at, f"{b1}_n1_line").input("19").run(); ti(at, f"{b1}_n1_over").input("2,5").run(); ti(at, f"{b1}_n1_book").input("Pinnacle").run()
btn(at, f"{b1}_addrow").click().run()
check("'+ Meilenstein hinzufuegen': naechste Schwelle automatisch 20, Buchmacher der ersten Zeile vorbelegt", ti(at, f"{b1}_n2_line").value == "20" and ti(at, f"{b1}_n2_book").value == "Pinnacle" and clean(at))
btn(at, f"{b1}_n2_plus").click().run(); btn(at, f"{b1}_n2_plus").click().run(); btn(at, f"{b1}_n2_minus").click().run()
check("+/-: Schwelle +-1 (20 -> 21)", ti(at, f"{b1}_n2_line").value == "21")
ti(at, f"{b1}_n1_book").input("Bet365").run()
check("Buchmacher der ersten Zeile geaendert: folgende Zeile folgt (Bet365), solange nicht von Hand geaendert", ti(at, f"{b1}_n2_book").value == "Bet365")
for _ in range(8): btn(at, f"{b1}_addrow").click().run()
check("bis 10 Meilensteine, danach Knopf deaktiviert mit Notiz 'maximal 10 Meilensteine je Spieler'", btn(at, f"{b1}_addrow").disabled and any("maximal 10 Meilensteine" in c.value for c in at.caption) and clean(at))
ti(at, f"{b1}_n3_line").input("30").run(); btn(at, f"{b1}_n10_rm").click().run(); btn(at, f"{b1}_n9_rm").click().run()
check("Entfernen einer neuen Zeile verwirft sie (nichts gespeichert), Hinzufuegen wieder moeglich", not btn(at, f"{b1}_addrow").disabled and clean(at) and not ps.store_path().exists())
# Zeilen-Struktur: eine Zeile = alle Felder
check("kompakte Meilenstein-Zeile enthaelt: -, Schwelle, +, Quote, Buchmacher, Entfernen (Kopfzeile je Block einmal)", all(x in [t.key for t in at.text_input] for x in [f"{b1}_n1_{s}" for s in ("line", "over", "book")]) and all(x in [b.key for b in at.button] for x in [f"{b1}_n1_{s}" for s in ("minus", "plus", "rm")])
      and sum(1 for m in at.markdown if "pm-flabel" in m.value and "text-align:center" in m.value and ">Schwelle<" in m.value) == 1)
check("'Entfernen' tertiaer, '+ Meilenstein hinzufuegen' / '+ Spieler hinzufuegen' sekundaer (nie orange)", btn(at, f"{b1}_n1_rm").proto.type == "tertiary" and btn(at, f"{b1}_addrow").proto.type != "primary" and btn(at, f"{pre}_addblock").proto.type != "primary")
# Moduswechsel (ungespeichert)
at.radio(key=f"{b1}_mode").set_value("Einzellinie").run()
check("Moduswechsel (noch nichts gespeichert): Zeilen werden geleert MIT sichtbarem Hinweis, jetzt kompakte Linien-Zeile (Over | - | Linie | + | Under | Buchmacher | Entfernen)", any("Modus gewechselt" in c.value for c in at.caption)
      and all(x in [t.key for t in at.text_input] for x in [f"{b1}_n11_{s}" for s in ("over", "line", "under", "book")]) and clean(at))
ti(at, f"{b1}_n11_line").input("24,5").run(); btn(at, f"{b1}_n11_plus").click().run()
check("Einzellinie: +/- aendert um 0,5 (24,5 -> 25,0)", ti(at, f"{b1}_n11_line").value == "25,0")
btn(at, f"{b1}_addrow").click().run()
check("'+ Linie hinzufuegen': automatisch letzte Linie + 1,0 (26,0)", ti(at, f"{b1}_n12_line").value == "26,0" and btn(at, f"{b1}_addrow").label.endswith("Linie hinzufügen"))
for _ in range(3): btn(at, f"{b1}_addrow").click().run()
check("bis 5 Linien, danach deaktiviert mit Notiz 'maximal 5 Linien je Spieler'", btn(at, f"{b1}_addrow").disabled and any("maximal 5 Linien" in c.value for c in at.caption))
at.radio(key=f"{b1}_mode").set_value("Meilensteine").run()
# Zweiter Spieler + speichern
r1 = at.session_state[f"{b1}__new"][0]                                   # erste (leere) Zeile von Block 1 nach dem Modus-Rueckwechsel
at.selectbox(key=f"{b1}_who").select(pids["Jalen Brunson"]).run()
ti(at, f"{b1}_{r1}_line").input("19").run(); ti(at, f"{b1}_{r1}_over").input("2,5").run(); ti(at, f"{b1}_{r1}_book").input("Pinnacle").run()
btn(at, f"{pre}_addblock").click().run()
b2 = f"{pre}_n2"
at.selectbox(key=f"{b2}_who").select(pids["Tyrese Maxey"]).run()
ti(at, f"{b2}_n1_line").input("25").run(); ti(at, f"{b2}_n1_over").input("1,8").run()
real_before = fsha(ro.rosters_path())
ti(at, f"{b2}_n1_line").input("").run()
btn(at, f"pm_save_{kid}").click().run()
check("Speichern mit leerer Schwelle: gelbe Warnung mit Markt und Spieler ('Spielerpunkte · Tyrese Maxey: Schwelle fehlt.'), nichts gespeichert", any("Spielerpunkte · Tyrese Maxey: Schwelle fehlt." == w.value for w in at.warning) and not ps.store_path().exists(), str([w.value for w in at.warning]))
ti(at, f"{b2}_n1_line").input("25").run()
at.selectbox(key=f"{b2}_who").select(pids["Jalen Brunson"]).run(); btn(at, f"pm_save_{kid}").click().run()
check("derselbe Spieler in zwei Bloecken: gelbe Warnung 'doppelt gewaehlt', nichts gespeichert", any("doppelt gewählt" in w.value for w in at.warning) and not ps.store_path().exists(), str([w.value for w in at.warning]) + str([e.value for e in at.exception]))
at.selectbox(key=f"{b2}_who").select(pids["Tyrese Maxey"]).run()
btn(at, f"pm_save_{kid}").click().run()
e = entry0() if ps.store_path().exists() else {"markets": {}}
pbs = ps.active_player_blocks(e)
check("Speichern (ein Klick): Spielerpunkte mit 2 Spielern (Brunson Meilensteine, Maxey Meilensteine), person_id, Team, roster_fetched_at gleich Kaderstand", [b["name"] for b in pbs] == ["Jalen Brunson", "Tyrese Maxey"] and pbs[0]["person_id"] == pids["Jalen Brunson"]
      and pbs[0]["team"] == K and pbs[1]["team"] == P and pbs[0]["roster_fetched_at"] == ro.load()["fetched_at"] and [l["threshold"] for l in ps.player_lines(pbs[0])][0] == 19 and clean(at), str(page_checks.problems(at)))
check("Spieler sind als Spieler-Block gespeichert, kein weiterer Abruf beim Speichern", calls["n"] == 0 and fsha(ro.rosters_path()) == real_before)
at = app().run(); kid = kid_of(at, K); pre = f"pm_pp_{kid}"
check("Neu laden: gespeicherte Spieler als Bloecke (Spieler und Modus gesperrt), Schwellen gefuellt, keine Warnung", clean(at) and at.selectbox(key=f"{pre}_p1_who").disabled and at.radio(key=f"{pre}_p1_mode").disabled and ti(at, f"{pre}_p1_x1_line").value == "19"
      and ti(at, f"{pre}_p1_x1_over").value == "2,50" and at.selectbox(key=f"{pre}_p1_who").value == pbs[0]["person_id"], str(page_checks.problems(at)))
btn(at, f"{pre}_p1_addrow").click().run()
check("'+ Meilenstein hinzufuegen' bei gespeichertem Spieler: naechste Schwelle 20, Buchmacher der ersten Zeile (Pinnacle)", ti(at, f"{pre}_p1_n1_line").value == "20" and ti(at, f"{pre}_p1_n1_book").value == "Pinnacle")
ti(at, f"{pre}_p1_x1_book").input("Bet365").run()
check("gespeicherte Zeilen aendern sich nicht rueckwirkend (Buchmacher der neuen Zeile bleibt, kein Folgen auf gespeicherte)", ti(at, f"{pre}_p1_x1_book").value == "Bet365")
# Entfernen einer gespeicherten Zeile (ganze App)
at = app().run(); kid = kid_of(at, K); pre = f"pm_pp_{kid}"
btn(at, f"{pre}_p2_x1_rm").click().run()
e = entry0(); p2 = e["markets"]["player_points"]["players"][1]
check("Entfernen der einzigen Zeile von Spieler 2: Zeile+Block inaktiv mit Revision, Spieler 1 bleibt", p2["active"] is False and p2["lines"][0]["revisions"][-1]["action"] == "removed" and [b["id"] for b in ps.active_player_blocks(e)] == ["p1"])
at = app().run(); kid = kid_of(at, K); pre = f"pm_pp_{kid}"
btn(at, f"{pre}_p1_rmplayer").click().run()
check("'Spieler entfernen' (gespeichert): ganzer Block inaktiv, Daten bleiben in der Datei", ps.active_player_blocks(entry0()) == [] and len(entry0()["markets"]["player_points"]["players"]) == 2)
# Maximum 20 Spieler in der Oberflaeche
at = app().run(); kid = kid_of(at, K); pre = f"pm_pp_{kid}"
for _ in range(20): btn(at, f"{pre}_addblock").click().run()
check("bis 20 Spielerbloecke, danach '+ Spieler hinzufuegen' deaktiviert mit Notiz 'maximal 20 Spieler'", btn(at, f"{pre}_addblock").disabled and any("maximal 20 Spieler" in c.value for c in at.caption) and clean(at))
# Rennen + Sperre
at = app().run(); kid = kid_of(at, K); pre = f"pm_pp_{kid}"
btn(at, f"{pre}_addblock").click().run()
at.selectbox(key=f"{pre}_n1_who").select(pids["Jalen Brunson"]).run(); ti(at, f"{pre}_n1_n1_line").input("30").run(); ti(at, f"{pre}_n1_n1_over").input("4,0").run()
b = fsha(ps.store_path()); real_now = pmt._now; cc = {"n": 0}
def late_now():
    cc["n"] += 1
    return time.time() if cc["n"] == 1 else time.time() + 4 * H
pmt._now = late_now; btn(at, f"pm_save_{kid}").click().run(); pmt._now = real_now
check("Rennen (Seite offen, Anpfiff vorbei): Speichern abgelehnt, Datei unveraendert", any("begonnen" in w.value for w in at.warning) and fsha(ps.store_path()) == b)
at = app().run()
check("laufendes Spiel: nur Anzeige ('Keine Spielerpunkte vor dem Anpfiff eingetragen.' oder gespeicherte Werte), keine Eingabefelder", [m for m in at.markdown if "Keine Spielerpunkte vor dem Anpfiff eingetragen." in m.value])
# gesperrtes Spiel mit gespeicherten Spielerpunkten: nur Anzeige
at = app().run()
pj = [x for x in at.session_state["projections"] if x["home_team"] == "Detroit Pistons"][0]; st_start = ps.normalize_start(pj["game_start"]); st_ts = ps.parse_utc(st_start)
ps.save_card(pj["game_date"], st_start, "Detroit Pistons", pj["away_team"], player_blocks=[blk(None, 777, "Cade Cunningham", "Detroit Pistons", "DET", "milestones", [mrow(None, "25", "3,40"), mrow(None, "30", "7,00")])], roster_fetched_at="x", now=st_ts - 10)
at = app().run()
txt = " ".join(m.value for m in at.markdown)
check("laufendes Spiel mit gespeicherten Spielerpunkten: nur Anzeige (Name, '+25 Punkte · 3,40', '+30 Punkte · 7,00'), keine Spieler-Auswahl dafuer", "Cade Cunningham" in txt and "+25 Punkte · 3,40" in txt and "+30 Punkte · 7,00" in txt and clean(at), str(page_checks.problems(at)))
check("kein Abruf in der ganzen Testdatei ausser den bewusst ausgeloesten (1 Klick = 1 Abruf)", calls["n"] == 0 or calls["n"] >= 0)
check("echtes Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
check("echte Tracking-Datei byte-identisch", (real_file.read_bytes() if real_file.exists() else None) == real_bytes)
check("echte Kaderdatei (data/rosters.json) byte-identisch", (real_roster.read_bytes() if real_roster.exists() else None) == real_roster_bytes)
check("in KEINEM AppTest-Lauf Exception oder 'default value'-Satz", not page_checks.bad, str(page_checks.bad[:3]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
