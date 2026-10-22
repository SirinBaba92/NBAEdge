"""Tests fuer Pre-Match Eingabe, Schritt 2 und 3: Feldreihenfolge, Status-Chip, Markt "Spread" (halbe Linien, gespiegelte
Linienfelder, weitere Linien), EIN Speichern-Knopf pro Karte (alles oder nichts).
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Calls, Pickle und echte Tracking-Datei nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match_spread.py"""
import datetime as dt, hashlib, json, os, re, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.nba_live as _nba_live
_nba_live.NBA_CACHE_SECONDS = 10 ** 6      # AppTest startet bei jedem Klick das ganze Skript (auch den Live-Tab): dessen 20-s-Zwischenspeicher darf nicht mitten im Test ablaufen
import data.pre_match_store as ps
import ui.pre_match_tab as pmt
import ui.score_cards as sc
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"
real_before = (real_file.stat().st_mtime_ns, hashlib.sha256(real_file.read_bytes()).hexdigest()) if real_file.exists() else None
real_dir = ROOT / "data" / "tracking"
real_dir_before = sorted((p.name, p.stat().st_mtime_ns) for p in real_dir.rglob("*")) if real_dir.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
fsha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
K, P = "New York Knicks", "Philadelphia 76ers"
def pm_expanders(at):
    """Expander des Tabs Pre-Match Eingabe (nicht die Zeilen-Bloecke der Score-Projections-Karten)."""
    return [x for x in at.expander if not any("pc-l" in m.value for m in x.markdown)]
def row(rid="main", line="-4,5", h="1,91", a="1,95", b="Pinnacle"):
    return {"id": rid, "line": line, "home_odds": h, "away_odds": a, "bookmaker": b}
def spread(start, now, rows, sugg=None, home=K, away=P, date="2026-10-20"):
    return ps.save_spread(date, start, home, away, rows, suggestion=sugg, now=now)
def card(start, now, winner=None, rows=None, sugg=None, home=K, away=P, date="2026-10-20"):
    return ps.save_card(date, start, home, away, winner=winner, spread_rows=rows, suggestion=sugg, now=now)
def win(h="1,55", a="2,50", b="Betano"): return {"home_odds": h, "away_odds": a, "bookmaker": b}

# ===================================================== A) Linien: nur ganze und halbe
good = {"-4,5": -4.5, "-4.5": -4.5, "\u22124,5": -4.5, "+3": 3.0, "0": 0.0, "-0": 0.0, "4,5": 4.5, " -10 ": -10.0, "60": 60.0, "-1": -1.0}
check("gueltige Linien: ganze und halbe (Komma/Punkt, +/-/Minuszeichen, 0)", all(ps.parse_line_input(k) == v for k, v in good.items()))
bad = ["", " ", None, "abc", "-4,25", "-4,3", "-4,75", "0,1", "1,2,3", "-", "+-4", "61", "-60,5", "nan", "inf", "1e2", "4,5x"]
errs = {}
for t in bad:
    try: ps.parse_line_input(t); errs[t] = None
    except ps.OddsInputError as e: errs[t] = str(e)
check("Viertel- und andere Linien werden abgelehnt (-4,25, -4,3, -4,75, 0,1), ebenso leer/Text/>60/nan/inf", all(errs.values()), str({k: v for k, v in errs.items() if not v}))
check("Meldung: 'Nur ganze und halbe Linien erlaubt (z. B. -1, -1,5, 0, +2).'", errs["-4,25"] == "Nur ganze und halbe Linien erlaubt (z. B. -1, -1,5, 0, +2)." and errs[""] == "Linie fehlt.")
rh = {-4.3: -4.5, -4.25: -4.5, -4.2: -4.0, 3.1: 3.0, 3.25: 3.5, 0.2: 0.0, -0.2: 0.0, 0.25: 0.5, -4.5: -4.5, 0.0: 0.0, 2.74: 2.5}
check("Rundung des Vorschlags auf 0,5 (Haelften weg von null), nie -0,0", all(ps.round_half(k) == v for k, v in rh.items()) and str(ps.round_half(-0.2)) == "0.0", str({k: ps.round_half(k) for k in rh}))
nl = {-1.5: -2.5, 1.5: 2.5, 0.0: -1.0, -1.0: -2.0, 2.0: 3.0, -0.5: -1.5, 0.5: 1.5}
check("naechste weitere Linie: 1,0 Richtung Favorit (Heim-Fav -1,5 -> -2,5; Gast-Fav +1,5 -> +2,5; Pick'em 0 -> Heim -1)", all(ps.next_line(k) == v for k, v in nl.items()))
check("Anzeige: Gast-Linie = umgekehrte Heim-Linie", [pmt.fmt_line(-v + 0.0) for v in (-4.5, 3.0, 0.0, -1.5)] == ["+4,5", "\u22123,0", "0", "+1,5"])

# ===================================================== B) Speicher: Spread (einzeln)
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
sugg = {"line_home": -4.3, "line_home_rounded": -4.5, "source": "cache_vorab"}
r = spread(start, now, [row()], sugg)
d = json.loads(ps.store_path().read_text()); key = f"2026-10-20|{start}|{K}|{P}"
m = d["entries"][key]["markets"]["spread"]; l = m["lines"][0]
check("Spread gespeichert: Version 5, Hauptlinie 'main' oben, line_home -4,5 / line_away +4,5, Quoten, Buchmacher", d["version"] == 5 and l["id"] == "main" and l["line_home"] == -4.5 and l["line_away"] == 4.5 and l["home_odds"] == 1.91 and l["away_odds"] == 1.95 and l["bookmaker"] == "Pinnacle")
check("market_suggestion speichert ungerundeten (-4,3) UND gerundeten Wert (-4,5)", l["market_suggestion"] == sugg and l["revisions"][0]["market_suggestion"] == sugg)
check("Zeitstempel mit Versatz, 1 Revision; gleiche Werte erneut = 'unchanged'", re.search(r"[+-]\d\d:\d\d$", l["entered_at"]) and len(l["revisions"]) == 1 and spread(start, now + 5, [row()], sugg)["status"] == "unchanged")
spread(start, now + 60, [row(line="-5,5", h="1,87")], sugg)
l = ps.get_entry(key)["markets"]["spread"]["lines"][0]
check("Aendern: 2 Revisionen, entered_at bleibt, Abweichung vom Vorschlag nachvollziehbar (-5,5 gegen -4,3)", [x["line_home"] for x in l["revisions"]] == [-4.5, -5.5] and round(l["line_home"] - l["market_suggestion"]["line_home"], 2) == -1.2)
b = fsha(ps.store_path())
for lab, rows, expect in (("Viertellinie", [row(line="-4,25")], "Nur ganze und halbe"), ("Linie -4,3", [row(line="-4,3")], "Nur ganze und halbe"),
                          ("Quote <= 1", [row(h="1,00")], "Hauptlinie: Die Quote muss"), ("Quote fehlt", [row(a="")], "Hauptlinie: Quote fehlt"),
                          ("ohne Hauptlinie", [], "Hauptlinie fehlt"), ("weitere Linie unvollstaendig", [row(), row(rid=None, line="-1,5", h="", a="2,0")], "Weitere Linie 1: Quote fehlt")):
    try: spread(start, now + 100, rows); msg = None
    except ps.OddsInputError as e: msg = str(e)
    check(f"save_spread Eingabepruefung ({lab}): '{expect}', Datei unveraendert", msg and expect in msg and fsha(ps.store_path()) == b, str(msg))
spread(start, now + 110, [row(line="-5,5", h="1,87"), row(rid=None, line="-6,5", h="1,6", a="2,3", b="Bet365"), row(rid=None, line="-7,5", h="2,2", a="1,65", b="Bet365"), row(rid=None, line="", h="", a="", b="")])
lines = ps.get_entry(key)["markets"]["spread"]["lines"]
check("weitere Linien: IDs x1, x2, Hauptlinie bleibt oben, leere Zeile uebersprungen", [x["id"] for x in lines] == ["main", "x1", "x2"] and lines[1]["line_away"] == 6.5)
ps.remove_spread_line("2026-10-20", start, K, P, "x1", now=now + 120)
lines = ps.get_entry(key)["markets"]["spread"]["lines"]
check("Entfernen: bleibt in der Datei (active=false, removed_at, Revision 'removed'), nichts geloescht", len(lines) == 3 and lines[1]["active"] is False and lines[1]["revisions"][-1]["action"] == "removed" and len(ps.active_spread_lines(ps.get_entry(key))) == 2)
b = fsha(ps.store_path())
for t in (now + 3 * H, now + 3 * H + 5):
    for what, fn in (("save_spread", lambda: spread(start, t, [row(line="-9")])), ("remove", lambda: ps.remove_spread_line("2026-10-20", start, K, P, "x2", now=t)), ("save_card", lambda: card(start, t, win()))):
        try: fn(); raised = False
        except ps.GameStartedError: raised = True
        check(f"{what} {'ab' if t == now + 3 * H else 'nach'} dem Anpfiff: gesperrt, Datei unveraendert", raised and fsha(ps.store_path()) == b)

# ===================================================== C) save_card: alle ausgefuellten Maerkte, alles oder nichts
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H); key = f"2026-10-20|{start}|{K}|{P}"
r = card(start, now, winner=win(), rows=[row(line="-1,5", h="", a=""), row(rid=None, line="-2,5", h="", a="")], sugg=sugg)
e = ps.get_entry(key)
check("nur Sieger ausgefuellt (Spread nur vorbefuellte Linien ohne Quoten): Sieger gespeichert, Spread uebersprungen", r["markets"] == {"winner_incl_ot": "saved", "spread": "skipped", "total": "skipped", "team_totals": "skipped", "player_points": "skipped"} and "spread" not in e["markets"] and e["markets"]["winner_incl_ot"]["home_odds"] == 1.55)
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H); key = f"2026-10-20|{start}|{K}|{P}"
r = card(start, now, winner=win("", "", "Betano"), rows=[row(line="-1,5")], sugg=sugg)
e = ps.get_entry(key)
check("nur Spread ausgefuellt (Sieger leer, nur Buchmacher vorbefuellt): Spread gespeichert, Sieger uebersprungen", r["markets"] == {"winner_incl_ot": "skipped", "spread": "saved", "total": "skipped", "team_totals": "skipped", "player_points": "skipped"} and "winner_incl_ot" not in e["markets"] and e["markets"]["spread"]["lines"][0]["line_home"] == -1.5)
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H); key = f"2026-10-20|{start}|{K}|{P}"
r = card(start, now, winner=win(), rows=[row(line="-1,5"), row(rid=None, line="-2,5", h="2,2", a="1,65", b="X")], sugg=sugg)
e = ps.get_entry(key); w, sp = e["markets"]["winner_incl_ot"], e["markets"]["spread"]
check("beides ausgefuellt: ein Schreibvorgang speichert Sieger, Hauptlinie und weitere Linie (gleicher Zeitstempel)", r["status"] == "saved" and r["markets"] == {"winner_incl_ot": "saved", "spread": "saved", "total": "skipped", "team_totals": "skipped", "player_points": "skipped"} and [l["id"] for l in sp["lines"]] == ["main", "x1"] and w["updated_at"] == sp["updated_at"])
d = ps.load(); check("last_bookmaker je Markt (Sieger Betano, Spread Pinnacle)", d["last_bookmaker"] == {"winner_incl_ot": "Betano", "spread": "Pinnacle"} or (d["last_bookmaker"]["winner_incl_ot"] == "Betano" and d["last_bookmaker"]["spread"] == "Pinnacle"))
hist = list(ps.history_dir().glob("pre_match_entries_2*.json"))
check("Tageskopie nach dem Speichern, kein .tmp", hist and fsha(hist[0]) == fsha(ps.store_path()) and not list(ps.tracking_dir().rglob("*.tmp")))
b = fsha(ps.store_path())
r = card(start, now + 5, winner=win(), rows=[row(line="-1,5"), {**row(rid="x1", line="-2,5", h="2,2", a="1,65", b="X")}], sugg=sugg)
e = ps.get_entry(key)
check("unveraenderter Stand: 'unchanged', keine Datei-Aenderung, keine neue Revision", r["status"] == "unchanged" and fsha(ps.store_path()) == b and len(e["markets"]["winner_incl_ot"]["revisions"]) == 1 and len(e["markets"]["spread"]["lines"][0]["revisions"]) == 1)
r = card(start, now + 10, winner=win(), rows=[row(line="-1,5"), row(rid="x1", line="-2,5", h="2,1", a="1,65", b="X")], sugg=sugg)
e = ps.get_entry(key)
check("nur ein Markt geaendert: Sieger bleibt ohne neue Revision, Spread bekommt eine", r["markets"] == {"winner_incl_ot": "unchanged", "spread": "saved", "total": "skipped", "team_totals": "skipped", "player_points": "skipped"} and len(e["markets"]["winner_incl_ot"]["revisions"]) == 1 and len(e["markets"]["spread"]["lines"][1]["revisions"]) == 2 and len(e["markets"]["spread"]["lines"][0]["revisions"]) == 1)
# alles oder nichts
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H); key = f"2026-10-20|{start}|{K}|{P}"
card(start, now, winner=win(), rows=[row(line="-1,5")], sugg=sugg); base_sha = fsha(ps.store_path())
cases = [
    ("Sieger unvollstaendig (nur Heim-Quote) blockiert den gueltigen Spread", win("1,6", "", "X"), [row(line="-2,5")], ["Sieger inkl. OT: Quote fehlt."]),
    ("Sieger Quote <= 1,00 blockiert alles", win("1,00", "2,5", "X"), [row(line="-2,5")], ["Sieger inkl. OT: Die Quote muss größer als 1,00 sein."]),
    ("Spread ungueltige Linie blockiert den gueltigen Sieger", win("1,7", "2,3", "X"), [row(line="-4,25")], ["Spread · Hauptlinie: Nur ganze und halbe Linien erlaubt"]),
    ("Spread nur eine Quote blockiert den gueltigen Sieger", win("1,7", "2,3", "X"), [row(a="")], ["Spread · Hauptlinie: Quote fehlt."]),
    ("weitere Linie ungueltig (Quote 0,9)", win("1,7", "2,3", "X"), [row(), row(rid=None, line="-2,5", h="0,9", a="1,9")], ["Spread · Weitere Linie 1: Die Quote muss größer als 1,00 sein."]),
    ("beide Maerkte ungueltig: beide Meldungen mit Marktnamen", win("abc", "2,3", "X"), [row(line="-1,3")], ["Sieger inkl. OT: Bitte eine Zahl", "Spread · Hauptlinie: Nur ganze und halbe Linien"]),
    ("gespeicherter Sieger wird geleert: kein stilles Leeren", win("", "", "Betano"), [row(line="-1,5")], ["Sieger inkl. OT: Quote fehlt."]),
    ("gespeicherte Hauptlinie ohne Quoten: Fehler", win(), [row(line="-1,5", h="", a="")], ["Spread · Hauptlinie: Quote fehlt."]),
]
for lab, w, rows, expect in cases:
    try: card(start, now + 20, winner=w, rows=rows, sugg=sugg); errors = None
    except ps.CardInputError as e: errors = e.errors
    except ps.OddsInputError as e: errors = [str(e)]
    check(f"alles oder nichts: {lab}", errors and len(errors) == len(expect) and all(x in y for x, y in zip(expect, errors)) and fsha(ps.store_path()) == base_sha, str(errors))
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
try: card(start, now, winner=win("", "", "Betano"), rows=[row(line="-1,5", h="", a="")]); msg = None
except ps.OddsInputError as e: msg = str(e)
check("gar nichts ausgefuellt: 'Nichts eingetragen.', keine Datei", msg == "Nichts eingetragen." and not ps.store_path().exists())
try: card(start, now, winner=win(), rows=[row(line="-1,5", h="", a=""), row(rid=None, line="-2,5", h="2,0", a="1,8")]); msg = None
except ps.OddsInputError as e: msg = str(e)
check("weitere Linie ausgefuellt, Hauptlinie ohne Quoten: Meldung zur Hauptlinie, nichts gespeichert", msg and "Hauptlinie" in msg and not ps.store_path().exists(), str(msg))
# Dateifehler: alles oder nichts auch beim Schreiben
card(start, now, winner=win(), rows=[row(line="-1,5")]); b = fsha(ps.store_path()); real_replace = os.replace
def boom(*a, **k): raise OSError("voll")
os.replace = boom
try: card(start, now + 2, winner=win("1,9", "2,0", "X"), rows=[row(line="-2,5")]); raised = None
except ps.StoreError as e: raised = str(e)
finally: os.replace = real_replace
check("Fehler beim Ersetzen: StoreError, Datei Byte fuer Byte unveraendert (weder Sieger noch Spread), kein .tmp", raised and fsha(ps.store_path()) == b and not list(ps.tracking_dir().rglob("*.tmp")), str(raised))

# ===================================================== D) Alte Dateiversion (v1)
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
v1 = {"version": 1, "format": "nbaedge-pre-match-entries", "markets": {"winner_incl_ot": "Sieger inkl. OT (Dezimalquoten Heim/Gast)"}, "last_bookmaker": {"winner_incl_ot": "Betano"}, "updated_at": "2026-10-21T01:10:31+02:00",
      "entries": {f"2026-10-20|{start}|{K}|{P}": {"game_date": "2026-10-20", "start_utc": start, "home": K, "away": P, "markets": {"winner_incl_ot": {"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "entered_at": "2026-10-21T01:10:31+02:00", "updated_at": "2026-10-21T01:10:31+02:00", "revisions": [{"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "saved_at": "2026-10-21T01:10:31+02:00"}]}}}}}
ps.store_path().parent.mkdir(parents=True, exist_ok=True); ps.store_path().write_text(json.dumps(v1, indent=2)); old_bytes = ps.store_path().read_bytes()
d = ps.load()
check("Version-1-Datei ist lesbar, Lesen aendert nichts", not d.get("error") and d["version"] == 1 and ps.store_path().read_bytes() == old_bytes)
r = card(start, now, winner=win("1,5", "2,6", "Betano"), rows=[row(line="-1,5")], sugg=sugg)
d = ps.load(); backups = list(ps.history_dir().glob("pre_match_entries.v1_vor_Upgrade_*.json"))
w1 = v1["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"]["winner_incl_ot"]
check("erstes Schreiben (save_card): alte Version byte-genau gesichert, Datei Version 5, Sieger unveraendert (keine neue Revision)", len(backups) == 1 and backups[0].read_bytes() == old_bytes and d["version"] == 5 and d["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"]["winner_incl_ot"] == w1 and r["markets"]["winner_incl_ot"] == "unchanged" and r["markets"]["spread"] == "saved")
d = ps.load(); d["version"] = 99; ps.store_path().write_text(json.dumps(d)); b = fsha(ps.store_path())
try: card(start, now + 1, winner=win("1,9", "2,0", "X")); raised = False
except ps.StoreError: raised = True
check("Datei mit neuerer Version: save_card verweigert, nichts geaendert", raised and fsha(ps.store_path()) == b)

# ===================================================== E) App (AppTest)
def mk_event(home, away, total, home_points, commence, last_update, eid):
    bms = []
    for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(home_points)], home_points):
        ms = [{"key": "totals", "last_update": iso(last_update), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(last_update), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(last_update), "markets": ms})
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}
def setup(with_market=True):
    tmp = fresh_env(remaining=400)
    state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
    n = time.time()
    ev = [mk_event(K, P, 232.0, [-4.5, -4.5, -4.0], n + 3 * H, n - 700, "ev-k")] if with_market else []
    Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu", "data": ev}},
                                                                   "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
    return n
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def kid(at, home):
    p = [x for x in at.session_state["projections"] if x["home_team"] == home][0]
    return hashlib.md5(ps.game_key(p["game_date"], ps.normalize_start(p["game_start"]), home, p["away_team"]).encode()).hexdigest()[:10], p
def head(at, nick): return [m.value for m in at.tabs[-1].markdown if "pm-kick" in m.value and nick in m.value][0]
def corner(at, nick):
    m = re.search(r'<div class="pm-corner">(<div class="pc-chip[^>]*>[^<]*</div>)</div>', head(at, nick)); return m.group(1) if m else ""
def btn(at, key): return [b for b in at.button if b.key == key][0]
def ti(at, key): return at.text_input(key=key)
def knicks_entry(): return [v for v in ps.load()["entries"].values() if v["home"] == K][0]

setup()
at = app().run(); kK, pK = kid(at, K); kS, _ = kid(at, "San Antonio Spurs"); kP, pP = kid(at, "Detroit Pistons")
b0 = f"pm_sp_{kK}_main"
c0 = (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"])
html_all = " ".join(m.value for m in at.tabs[-1].markdown)
# 1) EIN Speichern-Knopf
keys_k = [b.key for b in at.button if b.key and kK in b.key]
check("ein einziger Speichern-Knopf pro editierbarer Karte (pm_save_<id>), keine Knoepfe 'pm_spsave_' / Formular-Knoepfe mehr", f"pm_save_{kK}" in keys_k and f"pm_save_{kS}" in [b.key for b in at.button if b.key] and not any("spsave" in (b.key or "") for b in at.button) and not any(getattr(b.proto, "form_id", "") for b in at.button if b.key and "pm_" in b.key), str(keys_k))
check("Speichern-Knopf steht am Ende der Karte (nach Entfernen/Hinzufuegen-Knoepfen der Karte)", [b.key for b in at.button if b.key and kK in b.key][-1] == f"pm_save_{kK}")
check("Kein Knopf in der Karte des laufenden Spiels (Pistons)", not any(kP in (b.key or "") for b in at.button))
caps = " ".join(c.value for c in at.caption)
check("keine Zeilen 'Zuletzt gespeichert ... erstmals ...' mehr", "Zuletzt gespeichert" not in caps and "erstmals" not in caps)
# 3) Marktnamen
exp_k = pm_expanders(at)[:5]
check("Maerkte sind Expander mit festem Titel, standardmaessig zu: 'SIEGER INKL. OT', 'SPREAD', 'TOTAL', 'TEAM TOTALS', 'SPIELERPUNKTE'", [x.label for x in exp_k] == ["SIEGER INKL. OT", "SPREAD", "TOTAL", "TEAM TOTALS", "SPIELERPUNKTE"] and all(not x.proto.expanded for x in pm_expanders(at)), str([(x.label, x.proto.expanded) for x in exp_k]))
# Feldreihenfolge Gast links / Heim rechts
keys = [x.key for x in at.text_input if x.key and kK in x.key]
check("Reihenfolge Sieger: Quote Gast, Buchmacher (Mitte), Quote Heim; Spread: Linie Gast, Linie Heim; Quote Gast, Buchmacher (Mitte), Quote Heim", [k for k in keys if k.startswith("pm_")][:3] == [f"pm_away_{kK}", f"pm_book_{kK}", f"pm_home_{kK}"] and [k for k in keys if k.startswith(b0)] == [f"{b0}_gline", f"{b0}_line", f"{b0}_away", f"{b0}_book", f"{b0}_home"], str([k for k in keys if k.startswith(b0)]))
check("Spaltenraster: Gast und Heim gleich breit, Mitte schmaler und symmetrisch (COLS = [1, 0.8, 1])", pmt.COLS[0] == pmt.COLS[2] and pmt.COLS[1] < pmt.COLS[0] and pmt.COLS == [1, 0.8, 1])
check("Marktnamen mittig zentriert (CSS text-align:center an .pm-market-title)", re.search(r"\.pm-market-title \{[^}]*text-align:center", pmt.PRE_MATCH_CSS.replace("{{", "{").replace("}}", "}")))
check("bei der Hauptlinie gibt es keinen 'Entfernen'-Knopf", not any(b.key == f"{b0}_rm" for b in at.button))
labels = {x.key: x.label for x in at.text_input if x.key and kK in x.key}
check("Beschriftung nennt das Team (Quote Gast · 76ers, Linie Heim · Knicks ...)", labels[f"pm_away_{kK}"] == "Quote Gast · 76ers" and labels[f"{b0}_gline"] == "Linie Gast · 76ers" and labels[f"{b0}_line"] == "Linie Heim · Knicks")
# 5) Vorschlag auf 0,5
check("Marktvorschlag auf 0,5 gerundet: Mittel -4,3 -> Heim -4,5 / Gast +4,5 vorbefuellt", ti(at, f"{b0}_line").value == "-4,5" and ti(at, f"{b0}_gline").value == "+4,5")
check("Hinweis 'Vorschlag aus Markt (Vorab-Linie): −4,3 (gerundet −4,5)'", "Vorschlag aus Markt (Vorab-Linie): \u22124,3 (gerundet \u22124,5)" in caps)
check("ohne Vorab-Linie (Spurs): Linienfelder leer", ti(at, f"pm_sp_{kS}_main_line").value == "" and ti(at, f"pm_sp_{kS}_main_gline").value == "")
# 4) Spiegelung
ti(at, f"{b0}_line").input("-1,5").run()
check("Heim-Linie tippen: Gast dreht sich um (-1,5 -> +1,5), sofort ohne Speichern", ti(at, f"{b0}_gline").value == "+1,5")
ti(at, f"{b0}_gline").input("+2").run()
check("Gast-Linie tippen: Heim dreht sich um (+2 -> -2,0)", ti(at, f"{b0}_line").value == "-2,0")
ti(at, f"{b0}_gline").input("-3,5").run()
check("Gast -3,5 (Gast-Favorit) -> Heim +3,5", ti(at, f"{b0}_line").value == "+3,5")
ti(at, f"{b0}_gline").input("abc").run()
check("ungueltige Eingabe im Gast-Feld: Heim-Feld bleibt unveraendert (Fehler erst beim Speichern)", ti(at, f"{b0}_line").value == "+3,5")
ti(at, f"{b0}_gline").input("").run()
check("Gast-Feld geleert: Heim-Feld wird ebenfalls leer", ti(at, f"{b0}_line").value == "")
ti(at, f"{b0}_line").input("0").run()
check("Pick'em: Heim 0 -> Gast 0", ti(at, f"{b0}_gline").value == "0")
# +/- Knoepfe
ti(at, f"{b0}_line").input("-1,5").run(); btn(at, f"{b0}_plus").click().run()
check("+ Knopf: Heim -1,5 -> -1,0 (Gast +1,0)", ti(at, f"{b0}_line").value == "\u22121,0".replace("\u2212", "-") and ti(at, f"{b0}_gline").value == "+1,0")
btn(at, f"{b0}_minus").click().run(); btn(at, f"{b0}_minus").click().run()
check("- Knopf zweimal: -1,0 -> -2,0 (Gast +2,0)", ti(at, f"{b0}_line").value == "-2,0" and ti(at, f"{b0}_gline").value == "+2,0")
ti(at, f"{b0}_gline").input("+3").run(); btn(at, f"{b0}_plus").click().run()
check("Knopf nach Eingabe im Gast-Feld: Gast +3 = Heim -3,0, + ergibt Heim -2,5 / Gast +2,5", ti(at, f"{b0}_line").value == "-2,5" and ti(at, f"{b0}_gline").value == "+2,5")
ti(at, f"{b0}_line").input("").run(); btn(at, f"{b0}_plus").click().run()
check("leeres Feld: + beginnt bei 0 -> Heim +0,5 / Gast -0,5", ti(at, f"{b0}_line").value == "+0,5" and ti(at, f"{b0}_gline").value == "-0,5")
check("keine zusaetzlichen Abrufe durch das Bedienen (kein Odds/BDL/NBA)", (len(state["odds_calls"]), state["bdl_calls"], state["nba_calls"]) == c0)

# 1) Speichern: nur Sieger
at = app().run()
ti(at, f"pm_away_{kK}").input("2,50"); ti(at, f"pm_home_{kK}").input("1,55"); ti(at, f"pm_book_{kK}").input("Betano")
btn(at, f"pm_save_{kK}").click().run()
e = knicks_entry()
check("nur Sieger ausgefuellt: Speichern legt nur den Sieger an (Spread mit vorbefuellter Linie, ohne Quoten, wird uebersprungen)", not at.exception and "spread" not in e["markets"] and e["markets"]["winner_incl_ot"]["away_odds"] == 2.5)
check("Rueckmeldung 'Gespeichert.' und blaugrauer Chip 'gespeichert HH:MM' oben rechts", "Gespeichert." in " ".join(c.value for c in at.caption) and re.fullmatch(r'<div class="pc-chip pc-chip-blue">gespeichert (?:\d\d\.\d\d\. )?\d\d:\d\d</div>', corner(at, "Knicks")), corner(at, "Knicks"))
# nur Spread (neue Sitzung, anderes Spiel Spurs)
a = app().run()
ti(a, f"pm_sp_{kS}_main_line").input("-1,5").run()
ti(a, f"pm_sp_{kS}_main_away").input("1,95"); ti(a, f"pm_sp_{kS}_main_home").input("1,91"); ti(a, f"pm_sp_{kS}_main_book").input("Pinnacle")
btn(a, f"pm_save_{kS}").click().run()
es = [v for v in ps.load()["entries"].values() if v["home"] == "San Antonio Spurs"][0]
check("nur Spread ausgefuellt: nur der Spread wird gespeichert (Spurs), Sieger nicht", "winner_incl_ot" not in es["markets"] and es["markets"]["spread"]["lines"][0]["line_home"] == -1.5 and es["markets"]["spread"]["lines"][0]["market_suggestion"] is None)
# beides, Knicks Spread ergaenzen
a = app().run(); b1 = fsha(ps.store_path())
ti(a, f"{b0}_away").input("1,95"); ti(a, f"{b0}_home").input("1,91"); ti(a, f"{b0}_book").input("Pinnacle")
btn(a, f"pm_save_{kK}").click().run()
e = knicks_entry(); ln = e["markets"]["spread"]["lines"][0]
check("Sieger bleibt unveraendert (keine neue Revision), Spread (Vorschlag -4,5 uebernommen) wird ergaenzt; market_suggestion mit ungerundet/gerundet", len(e["markets"]["winner_incl_ot"]["revisions"]) == 1 and ln["line_home"] == -4.5 and ln["market_suggestion"] == {"line_home": -4.3, "line_home_rounded": -4.5, "source": "cache_vorab"}, str(ln["market_suggestion"]))
a = app().run(); b2 = fsha(ps.store_path()); btn(a, f"pm_save_{kK}").click().run()
check("erneut Speichern ohne Aenderung: 'Unveraendert.', Datei gleich, keine neue Revision", "Unverändert." in " ".join(c.value for c in a.caption) and fsha(ps.store_path()) == b2 and len(knicks_entry()["markets"]["spread"]["lines"][0]["revisions"]) == 1)
# ungueltige Maerkte blockieren alles
b3 = fsha(ps.store_path())
a = app().run(); ti(a, f"pm_home_{kK}").input("1,70"); ti(a, f"pm_away_{kK}").input(""); ti(a, f"{b0}_home").input("1,85")
btn(a, f"pm_save_{kK}").click().run()
w = " | ".join(x.value for x in a.warning)
check("Sieger unvollstaendig + Spread geaendert: gelbe Warnung 'Sieger inkl. OT: Quote fehlt.', NICHTS gespeichert (auch der Spread nicht)", "Sieger inkl. OT: Quote fehlt." in w and fsha(ps.store_path()) == b3, w[:100])
a = app().run(); ti(a, f"{b0}_line").input("-4,25"); ti(a, f"pm_home_{kK}").input("1,70"); ti(a, f"pm_away_{kK}").input("2,30")
btn(a, f"pm_save_{kK}").click().run()
w = " | ".join(x.value for x in a.warning)
check("Viertellinie: gelbe Warnung 'Spread · Hauptlinie: Nur ganze und halbe Linien ...', gueltiger Sieger wird NICHT gespeichert", "Spread · Hauptlinie: Nur ganze und halbe Linien" in w and fsha(ps.store_path()) == b3, w[:110])
a = app().run(); ti(a, f"pm_home_{kK}").input("abc"); ti(a, f"{b0}_line").input("-4,3")
btn(a, f"pm_save_{kK}").click().run()
w = [x.value for x in a.warning]
check("beide Maerkte ungueltig: je eine Warnung mit Marktnamen", any(x.startswith("Sieger inkl. OT:") for x in w) and any(x.startswith("Spread · Hauptlinie:") for x in w) and fsha(ps.store_path()) == b3, str(w))
# automatische weitere Linien
def fresh_main(line, home=K):
    a = app().run(); ti(a, f"{b0}_line").input(line).run(); return a
a = fresh_main("-1,5"); btn(a, f"pm_add_{kK}").click().run(); n1 = f"pm_sp_{kK}_n1"
check("Heim-Favorit: Hauptlinie Heim -1,5 -> weitere Linie Heim -2,5 / Gast +2,5", ti(a, f"{n1}_line").value == "-2,5" and ti(a, f"{n1}_gline").value == "+2,5")
btn(a, f"pm_add_{kK}").click().run(); btn(a, f"pm_add_{kK}").click().run()
check("zweite und dritte weitere Linie: -3,5 / +3,5 und -4,5 / +4,5", ti(a, f"pm_sp_{kK}_n2_line").value == "-3,5" and ti(a, f"pm_sp_{kK}_n3_line").value == "-4,5" and ti(a, f"pm_sp_{kK}_n3_gline").value == "+4,5")
check("nach 3 weiteren Linien ist der Knopf noch aktiv (Limit ist 4 weitere = 5 Linien wie die Leiter in Score Projections)", not btn(a, f"pm_add_{kK}").disabled)
btn(a, f"pm_add_{kK}").click().run()
check("vierte weitere Linie: -5,5 / +5,5", ti(a, f"pm_sp_{kK}_n4_line").value == "-5,5" and ti(a, f"pm_sp_{kK}_n4_gline").value == "+5,5")
mx = btn(a, f"pm_add_{kK}")
check("Maximum 4: '+ Weitere Linie hinzufuegen' deaktiviert, Notiz 'maximal 4 weitere Linien'", mx.disabled and "maximal 4 weitere Linien" in " ".join(c.value for c in a.caption))
ti(a, f"{b0}_line").input("-0,5").run()
check("Hauptlinie nachtraeglich geaendert: bereits angelegte weitere Linien bleiben unveraendert (kein stilles Verschieben)", ti(a, f"{n1}_line").value == "-2,5" and ti(a, f"pm_sp_{kK}_n2_line").value == "-3,5" and ti(a, f"pm_sp_{kK}_n3_line").value == "-4,5" and ti(a, f"pm_sp_{kK}_n4_line").value == "-5,5")
a = fresh_main("+1,5"); btn(a, f"pm_add_{kK}").click().run(); btn(a, f"pm_add_{kK}").click().run()
check("Gast-Favorit: Hauptlinie Heim +1,5 (Gast -1,5) -> weitere Linie Heim +2,5 / Gast -2,5, dann +3,5 / -3,5", ti(a, f"pm_sp_{kK}_n1_line").value == "+2,5" and ti(a, f"pm_sp_{kK}_n1_gline").value == "-2,5" and ti(a, f"pm_sp_{kK}_n2_line").value == "+3,5" and ti(a, f"pm_sp_{kK}_n2_gline").value == "-3,5")
a = fresh_main("0"); btn(a, f"pm_add_{kK}").click().run(); btn(a, f"pm_add_{kK}").click().run()
check("Pick'em (0): Favorit ist Heim: weitere Linie Heim -1 / Gast +1, dann Heim -2 / Gast +2", ti(a, f"pm_sp_{kK}_n1_line").value == "-1,0" and ti(a, f"pm_sp_{kK}_n1_gline").value == "+1,0" and ti(a, f"pm_sp_{kK}_n2_line").value == "-2,0")
a = fresh_main("-1,5"); btn(a, f"pm_add_{kK}").click().run(); ti(a, f"pm_sp_{kK}_n1_line").input("-5").run(); btn(a, f"pm_add_{kK}").click().run()
check("neue Linie orientiert sich an der zuletzt angelegten Linie (aktueller Feldwert -5 -> -6)", ti(a, f"pm_sp_{kK}_n2_line").value == "-6,0")
btn(a, f"pm_sp_{kK}_n1_plus").click().run()
check("+ in einer weiteren Zeile: -5 -> -4,5 (Gast +4,5)", ti(a, f"pm_sp_{kK}_n1_line").value == "-4,5" and ti(a, f"pm_sp_{kK}_n1_gline").value == "+4,5")
# weitere Linie speichern, laden, entfernen
a = app().run(); b4 = fsha(ps.store_path())
ti(a, f"{b0}_line").input("-1,5").run(); ti(a, f"{b0}_home").input("1,90"); ti(a, f"{b0}_away").input("1,95")
btn(a, f"pm_add_{kK}").click().run(); n1 = f"pm_sp_{kK}_n1"
check("'Entfernen' einer weiteren Linie ist ein unauffaelliger Textknopf (type tertiary)", btn(a, f"{n1}_rm").proto.type == "tertiary", str(btn(a, f"{n1}_rm").proto.type))
ti(a, f"{n1}_away").input("2,30"); ti(a, f"{n1}_home").input("1,60"); ti(a, f"{n1}_book").input("Bet365")
btn(a, f"pm_save_{kK}").click().run()
lines = knicks_entry()["markets"]["spread"]["lines"]
check("Hauptlinie (geaendert auf -1,5) und weitere Linie (-2,5, Bet365) in einem Klick gespeichert, Hauptlinie oben, Hauptlinien-Revision 2", [l["id"] for l in lines] == ["main", "x1"] and lines[0]["line_home"] == -1.5 and len(lines[0]["revisions"]) == 2 and lines[1]["line_home"] == -2.5 and lines[1]["bookmaker"] == "Bet365")
a = app().run()
check("Neu oeffnen: weitere Linie aus der Datei (-2,5 / +2,5), Zwischenueberschrift 'Weitere Linien (1)'", ti(a, f"pm_sp_{kK}_x1_line").value == "-2,5" and ti(a, f"pm_sp_{kK}_x1_gline").value == "+2,5" and any("Weitere Linien (1)" in m.value for m in a.markdown if "pm-sub" in m.value))
btn(a, f"pm_add_{kK}").click().run(); btn(a, f"pm_add_{kK}").click().run(); btn(a, f"pm_add_{kK}").click().run()
check("gespeicherte + neue Linien zaehlen zusammen (1 + 3 = 4): danach deaktiviert, neue Linie setzt bei der letzten Linie an (x1 -2,5 -> -3,5 -> -4,5 -> -5,5)", ti(a, f"pm_sp_{kK}_n1_line").value == "-3,5" and ti(a, f"pm_sp_{kK}_n2_line").value == "-4,5" and ti(a, f"pm_sp_{kK}_n3_line").value == "-5,5" and btn(a, f"pm_add_{kK}").disabled)
a = app().run(); btn(a, f"pm_sp_{kK}_x1_rm").click().run(); a = app().run()
lines = knicks_entry()["markets"]["spread"]["lines"]
check("Entfernen: Linie bleibt mit active=false und Revision 'removed' in der Datei, Zeile verschwindet, Hinzufuegen wieder moeglich", lines[1]["active"] is False and lines[1]["revisions"][-1]["action"] == "removed" and any("Weitere Linien (0)" in m.value for m in a.markdown if "pm-sub" in m.value) and not btn(a, f"pm_add_{kK}").disabled)
# Sperre: laufendes Spiel
ps.save_market(pP["game_date"], ps.normalize_start(pP["game_start"]), "Detroit Pistons", "Boston Celtics", "winner_incl_ot", "1,48", "2,70", "Bet365", now=ps.parse_utc(pP["game_start"]) - 1000)
a = app().run(); h = " ".join(m.value for m in a.tabs[-1].markdown)
check("laufendes Spiel: Quoten nur angezeigt, keine Felder/Knoepfe, Hinweis 'gesperrt'", "2,70" in h and "Das Spiel läuft: Eingaben sind gesperrt." in h and not any(kP in (x.key or "") for x in a.text_input) and not any(kP in (x.key or "") for x in a.button))
b5 = fsha(ps.store_path()); t_start = ps.parse_utc(pK["game_start"]); calls = {"n": 0}; real_now = pmt._now
def racing_now():
    calls["n"] += 1
    return t_start - 100 if calls["n"] == 1 else t_start + 5
a = app().run(); ti(a, f"pm_home_{kK}").input("1,99"); pmt._now = racing_now
btn(a, f"pm_save_{kK}").click().run(); pmt._now = real_now
check("Spiel beginnt zwischen Anzeige und Klick: nichts gespeichert, Hinweis 'bereits begonnen' angezeigt", any("bereits begonnen" in w.value for w in a.warning) and fsha(ps.store_path()) == b5)
# Chips
check("Chip Pistons (laeuft, gespeichert): grau 'gespeichert ...'", re.fullmatch(r'<div class="pc-chip pc-chip-gray">gespeichert [\d.: ]+</div>', corner(a, "Pistons")), corner(a, "Pistons"))
check("Chip Spurs (vorab, gespeichert): blaugrau; Chip in der Mitte unveraendert 'Vorab'", re.fullmatch(r'<div class="pc-chip pc-chip-blue">gespeichert (?:\d\d\.\d\d\. )?\d\d:\d\d</div>', corner(a, "Spurs")) and 'pc-chip pc-chip-gray">Vorab<' in head(a, "Spurs"))

# Alte Datei in der App lesbar, Speichern hebt Version
tmp = fresh_env(remaining=400); setup()
a0 = app().run(); kK2, pK2 = kid(a0, K)
st_ = ps.normalize_start(pK2["game_start"]); v1k = f"{pK2['game_date']}|{st_}|{K}|{P}"
v1f = {"version": 1, "format": "nbaedge-pre-match-entries", "markets": {"winner_incl_ot": "x"}, "last_bookmaker": {"winner_incl_ot": "Betano"}, "updated_at": "2026-10-21T01:10:31+02:00",
       "entries": {v1k: {"game_date": pK2["game_date"], "start_utc": st_, "home": K, "away": P, "markets": {"winner_incl_ot": {"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "entered_at": "2026-10-21T01:10:31+02:00", "updated_at": "2026-10-21T01:10:31+02:00", "revisions": [{"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "saved_at": "2026-10-21T01:10:31+02:00"}]}}}}}
ps.store_path().parent.mkdir(parents=True, exist_ok=True); ps.store_path().write_text(json.dumps(v1f)); ob = ps.store_path().read_bytes()
a = app().run()
check("alte Version-1-Datei in der App: gespeicherte Sieger-Quoten stehen in den Feldern, Datei unveraendert", ti(a, f"pm_home_{kK2}").value == "1,50" and ti(a, f"pm_away_{kK2}").value == "2,60" and ps.store_path().read_bytes() == ob)
ti(a, f"pm_sp_{kK2}_main_away").input("1,95"); ti(a, f"pm_sp_{kK2}_main_home").input("1,91"); btn(a, f"pm_save_{kK2}").click().run()
check("Speichern des Spreads: Version 5, Sicherungskopie der alten Datei, Sieger-Eintrag unveraendert", ps.load()["version"] == 5 and len(list(ps.history_dir().glob("pre_match_entries.v1_vor_Upgrade_*.json"))) == 1 and ps.load()["entries"][v1k]["markets"]["winner_incl_ot"]["home_odds"] == 1.5)

# ===================================================== F) Farben / Regeln / Rahmen
def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]; c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]; return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
Pl = sc.PALETTE; ratio = (max(lum(Pl["chip_blue_text"]), lum(Pl["chip_blue_bg"])) + 0.05) / (min(lum(Pl["chip_blue_text"]), lum(Pl["chip_blue_bg"])) + 0.05)
check("blaugrauer Chip: Kontrast >= 4,5 : 1, kein Gruen in den Chip-Farben", ratio >= 4.5 and not any(int(Pl[k][3:5], 16) > int(Pl[k][1:3], 16) + 25 and int(Pl[k][3:5], 16) > int(Pl[k][5:7], 16) + 25 for k in Pl if k.startswith("chip_") and Pl[k].startswith("#")))
rules = (ROOT / "DESIGN_REGELN.md").read_text().lower()
check("DESIGN_REGELN.md: ein Speichern-Knopf, Marktnamen als Abschnittsueberschrift (19 px), halbe Linien, weitere Linien", all(s_ in rules for s_ in ("einziger „speichern“-knopf", "19 px", "ganze und halbe linien", "bis zu 3", "oben rechts")))
check("Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
rb = (real_file.stat().st_mtime_ns, hashlib.sha256(real_file.read_bytes()).hexdigest()) if real_file.exists() else None
check("echte data/tracking/pre_match_entries.json (Sieger Thunder @ Spurs) unveraendert und lesbar", rb == real_before and (not real_file.exists() or "San Antonio Spurs" in real_file.read_text()))
check("echtes data/tracking/ durch die Tests weder angelegt noch veraendert", sorted((p.name, p.stat().st_mtime_ns) for p in real_dir.rglob("*")) == real_dir_before if real_dir.exists() else real_dir_before is None)
check("in KEINEM AppTest-Lauf dieser Datei: Streamlit-Exception oder der Satz 'was created with a default value ... Session State API'", not page_checks.bad, "; ".join(page_checks.bad[:2]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
