"""Echter Browsertest (headless Chrome) fuer die Score-Projections-Karten: Expander SPREAD/TOTAL/TEAM TOTAL mit Wahrscheinlichkeits-Balken, Herkunftszeile, eigene Linie
aus der Pre-Match Eingabe. Startet die ECHTE app.py (tests/_harness_score_app.py, simulierte Netzantworten, Temp-Ordner, kein echtes Netz).
NICHT Teil der normalen Testsuite (braucht Google Chrome). Aufruf aus dem Projektordner: venv/bin/python tests/browser_score_check.py"""
import asyncio, base64, datetime as dt, json, os, re, signal, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
tmp = Path(tempfile.mkdtemp(prefix="nbaedge_scorebrowser_"))
import data.rosters as ro
from roster_fixture import fake_index
os.environ["NBAEDGE_ROSTERS"] = str(tmp / "rosters.json")
ro.write(ro.build(fake_index(), dt.datetime.now().astimezone().isoformat(timespec="seconds"), "2026-27"))
os.environ["NBAEDGE_TRACKING_DIR"] = str(tmp / "tracking")                 # Temp-Ordner: beendetes Spiel (Schnappschuss + Ergebnis) fuer die Chips
import snapshot_fixture
from data import live_feed as lf
# Feste Uhr (wie tests/test_player_live.py): T0 = 22.10.2026 21:00 Berliner Zeit = mitten im US-Spieltag D (22.10.), 4 h nach dem Wechsel um 17:00 und 3 h vor Mitternacht (das Datum, das fake_net per date.today() vergibt, ist so gleich D). Alle Harness-Spiele liegen relativ zu T0
# (Knicks/Spurs +3 h, Pistons -10 min, Beendetes -5 h) und damit in D - zu jeder echten Uhrzeit.
T0 = dt.datetime(2026, 10, 22, 21, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
D = lf.current_us_day(T0)
CLOCK_OFFSET = T0 - time.time()                 # die App sieht real + CLOCK_OFFSET (Uhr laeuft weiter, beginnt bei T0)
app_now = lambda: time.time() + CLOCK_OFFSET
_real_time = time.time
time.time = lambda: T0                          # nur fuer die Fixture des beendeten Spiels (Anpfiff T0 - 5 h)
try: snapshot_fixture.finished_game(date=D)
finally: time.time = _real_time
real_snap_existed = (ROOT / "data" / "tracking" / "projection_snapshots.json").exists()
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"; real_bytes = real_file.read_bytes() if real_file.exists() else None
real_roster = ROOT / "data" / "rosters.json"; real_roster_bytes = real_roster.read_bytes() if real_roster.exists() else None
env = {**os.environ, "HARNESS_NBAEDGE_TRACKING_DIR": str(tmp / "tracking"), "HARNESS_NBAEDGE_ROSTERS": str(tmp / "rosters.json"), "PYTHONDONTWRITEBYTECODE": "1"}
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

def free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0)); return so.getsockname()[1]
PORT, CPORT = free_port(), free_port()
while CPORT == PORT: CPORT = free_port()

# Starter fuer den App-Prozess: setzt die Uhr (time.time, datetime.now) auf real + CLOCK_OFFSET und startet dann den unveraenderten Harness. Streamlit fuehrt das Skript bei jedem Rerun neu aus -> nur einmal patchen.
LAUNCHER = tmp / "launch_harness.py"
LAUNCHER.write_text(f'''import datetime as _dt, runpy, time
if not getattr(time, "_nbaedge_clock", False):
    _off, _real, _RD = float(__import__("os").environ["CLOCK_OFFSET"]), time.time, _dt.datetime
    time.time = lambda: _real() + _off
    class _Meta(type(_RD)):
        def __instancecheck__(cls, obj): return isinstance(obj, _RD)
    class _FakeDT(_RD, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None): return _RD.fromtimestamp(_real() + _off, tz)
        @classmethod
        def today(cls): return cls.now()
        @classmethod
        def utcnow(cls): return _RD.fromtimestamp(_real() + _off, _dt.timezone.utc).replace(tzinfo=None)
    class _MetaD(type(_RD.__mro__[1])):
        def __instancecheck__(cls, obj): return isinstance(obj, _RD.__mro__[1])
    class _FakeDate(_RD.__mro__[1], metaclass=_MetaD):
        @classmethod
        def today(cls): return _RD.fromtimestamp(_real() + _off).date()
    _dt.datetime = _FakeDT
    _dt.date = _FakeDate
    time._nbaedge_clock = True
runpy.run_path({str(ROOT / "tests" / "_harness_score_app.py")!r}, run_name="__main__")
''')
env["CLOCK_OFFSET"] = repr(CLOCK_OFFSET)

def listener_pids(port):
    r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True)
    return {int(x) for x in r.stdout.split()}
def descends_from(pid, root):
    """True, wenn pid der Prozess root ist oder von ihm abstammt (ps ppid-Kette)."""
    for _ in range(20):
        if pid == root: return True
        r = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True)
        if not r.stdout.strip(): return False
        pid = int(r.stdout.strip())
    return False
def stop(proc):
    """Prozess samt Kindern beenden (eigene Prozessgruppe): erst SIGTERM, nach 5 s SIGKILL."""
    if proc is None: return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try: os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError): pass
        try: proc.wait(timeout=5); break
        except subprocess.TimeoutExpired: continue
    try: os.killpg(proc.pid, signal.SIGKILL)       # Reste (Chrome-Helfer) auch nach dem Hauptprozess
    except (ProcessLookupError, PermissionError): pass

server_log = tmp / "server.log"; chrome_log = tmp / "chrome.log"
server = chrome = None
failed = True
try:
    with open(server_log, "wb") as sl, open(chrome_log, "wb") as cl:
        server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(LAUNCHER), "--server.port", str(PORT), "--server.address", "127.0.0.1", "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                                  env=env, stdout=sl, stderr=subprocess.STDOUT, start_new_session=True)
        chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={CPORT}", f"--user-data-dir={tmp / 'profile'}", "--no-first-run", "about:blank"],
                                  stdout=cl, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(120):
        if server.poll() is not None: raise RuntimeError(f"Streamlit-Prozess vorzeitig beendet (Code {server.returncode})")
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=1); break
        except Exception: time.sleep(0.5)
    else: raise RuntimeError("Streamlit antwortet nicht auf /healthz")
    own = listener_pids(PORT)
    if server.poll() is not None or not own or not all(descends_from(x, server.pid) for x in own):
        raise RuntimeError(f"Port {PORT} gehoert nicht dem eigenen Serverprozess (Listener {sorted(own)}, eigener {server.pid})")
    for _ in range(120):
        if chrome.poll() is not None: raise RuntimeError(f"Chrome vorzeitig beendet (Code {chrome.returncode})")
        try: pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CPORT}/json/list", timeout=1)); break
        except Exception: time.sleep(0.5)
    else: raise RuntimeError("Chrome-DevTools antworten nicht")
    own_c = listener_pids(CPORT)
    if not own_c or not all(descends_from(x, chrome.pid) for x in own_c):
        raise RuntimeError(f"Chrome-Port {CPORT} gehoert nicht dem eigenen Chrome (Listener {sorted(own_c)}, eigener {chrome.pid})")
    check(f"eigene Prozesse belegen die freien Ports (Streamlit {PORT}, Chrome {CPORT}); T0 = {dt.datetime.fromtimestamp(T0, ZoneInfo('Europe/Berlin')):%d.%m.%Y %H:%M} Berlin, Spieltag D = {D}", True)
    ws_url = [p for p in pages if p["type"] == "page"][0]["webSocketDebuggerUrl"]
    from tornado.websocket import websocket_connect

    async def main():
        ws = await websocket_connect(ws_url, max_message_size=64 * 1024 * 1024)
        n = [0]
        async def call(method, **params):
            n[0] += 1; i = n[0]
            await ws.write_message(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                m = json.loads(await ws.read_message())
                if m.get("id") == i: return m
        async def js(expr):
            r = await call("Runtime.evaluate", expression=expr, returnByValue=True)
            res = r.get("result", {})
            if res.get("exceptionDetails"): print("JS-Fehler:", res["exceptionDetails"].get("exception", {}).get("description", "")[:300])
            return res.get("result", {}).get("value")
        async def shoot_el(nm, expr, pad=30):
            rect = json.loads(await js(f"""(() => {{ const e = {expr}; e.scrollIntoView({{block: 'center'}}); const b = e.getBoundingClientRect(); return JSON.stringify([b.left + scrollX, b.top + scrollY, b.width, b.height]); }})()"""))
            sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - pad), width=rect[2] + 40, height=rect[3] + pad + 20, scale=1))
            (tmp / f"{nm}.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot", nm, tmp / f"{nm}.png", f"({rect[3]:.0f} px hoch)")
        async def typein(expr, text):
            await js(f"{expr}.focus()"); await js(f"{expr}.select()"); await call("Input.insertText", text=text)
            await call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9); await call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
            await asyncio.sleep(1.5)
        await call("Emulation.setDeviceMetricsOverride", width=1440, height=2600, deviceScaleFactor=1, mobile=False)
        await call("Page.navigate", url=f"http://127.0.0.1:{PORT}/")
        await asyncio.sleep(18)
        body = await js("document.body.innerText") or ""
        check("echte Seite geladen ohne Traceback/Exception", "Traceback" not in body and "StreamlitAPIException" not in body and len(body) > 200, body[:100].replace("\n", " "))
        TAB = lambda name: f"[...document.querySelectorAll('[role=\"tab\"]')].find(t => t.innerText.includes('{name}'))"
        await js(f"{TAB('Score Projections')}.click()"); await asyncio.sleep(2.0)
        SC = "[...document.querySelectorAll('.pc-card')].find(c => c.innerText.includes('Knicks'))"
        EX = "[...document.querySelectorAll('[class*=\"st-key-sc_lines_\"]')].find(c => c.innerText.includes('TEAM TOTAL · Knicks'))"
        TTL = "e.querySelector('summary').innerText.trim().split('\\n').pop().trim()"
        async def det_states():
            return json.loads(await js(f"JSON.stringify([...{EX}.querySelectorAll('[data-testid=\"stExpander\"]')].map(e => [{TTL}, e.querySelector('details').open]))"))
        async def toggle(title):
            await js(f"[...{EX}.querySelectorAll('[data-testid=\"stExpander\"]')].find(e => {TTL} === '{title}').querySelector('summary').click()"); await asyncio.sleep(1.0)
        async def rows_of(i):
            return json.loads(await js(f"JSON.stringify([...[...{EX}.querySelectorAll('[data-testid=\"stExpander\"]')][{i}].querySelectorAll('.pc-lrow')].map(r => r.innerText.replace(/\\n/g, ' | ')))"))
        async def shoot_both(nm):
            rect = json.loads(await js(f"""(() => {{ const c = {SC}, e = {EX}; c.scrollIntoView({{block: 'start'}}); const a = c.getBoundingClientRect(), b = e.getBoundingClientRect(); return JSON.stringify([a.left + scrollX, a.top + scrollY, a.width, b.bottom - a.top]); }})()"""))
            sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - 10), width=rect[2] + 40, height=rect[3] + 20, scale=1))
            (tmp / f"{nm}.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot", nm, tmp / f"{nm}.png", f"({rect[3]:.0f} px hoch)")
        TITLES = ["SPREAD", "TOTAL", "TEAM TOTAL · 76ers", "TEAM TOTAL · Knicks"]
        st0 = await det_states()
        check("Knicks-Karte: vier Expander mit festen Titeln, alle standardmaessig ZU", [t for t, o in st0] == TITLES and not any(o for t, o in st0), str(st0))
        gap = json.loads(await js(f"""JSON.stringify((() => {{ const a = {SC}.getBoundingClientRect(), b = {EX}.getBoundingClientRect(); return [Math.round(b.top - a.bottom), Math.round(b.left - a.left), Math.round(b.width - a.width)]; }})())"""))
        check("Platzierung: die vier Expander stehen DIREKT unter der Karte (Abstand <= 2 px, gleiche Breite/Ausrichtung) - nicht in der Karte (native Streamlit-Expander)", 0 <= gap[0] <= 2 and abs(gap[1]) <= 1 and abs(gap[2]) <= 2, str(gap))
        origin = await js(f"{SC}.querySelector('.pc-origin').innerText")
        check("Herkunftszeile ohne Eingabe: 'Spread: Cache HH:MM | Total: Cache HH:MM | Team Totals: keine Linie'", origin.startswith("Spread: Cache ") and "| Total: Cache " in origin and origin.endswith("Team Totals: keine Linie"), origin)
        await shoot_both("score_karte_zu")
        # --- Teil 1 (9c): weisse Schrift in den Plaketten; Balken bleibt Sieg-Orange
        await toggle("TOTAL")
        pillcss = json.loads(await js(f"""JSON.stringify((() => {{ const p = [...{EX}.querySelectorAll('.pc-lpct-pred')][0], seg = [...{EX}.querySelectorAll('.pc-lseg.pc-seg-fav')][0], cs = getComputedStyle(p);
            return [cs.color, cs.backgroundColor, cs.fontWeight, cs.fontSize, getComputedStyle(seg).backgroundColor]; }})())"""))
        check("Plakette: Schrift weiss (255,255,255) und fett (>= 700) in 16 px; Plaketten-Hintergrund abgedunkelt (#ea580c); Balkenanteil bleibt Sieg-Orange (#f97316)",
              pillcss[0] == "rgb(255, 255, 255)" and int(pillcss[2]) >= 700 and pillcss[3] == "16px" and pillcss[1] == "rgb(234, 88, 12)" and pillcss[4] == "rgb(249, 115, 22)", str(pillcss))
        await toggle("TOTAL")
        # --- Teil 4 (9c): beendetes Spiel mit Chips, laufendes ohne
        CH = json.loads(await js("""JSON.stringify([...document.querySelectorAll('[class*="st-key-sc_game_"]')].map(g => [[...g.querySelectorAll('.pc-name')].map(n => n.innerText).join('/'), g.querySelectorAll('.pc-lchip').length, [...g.querySelectorAll('.pc-lchip')].map(c => c.textContent.trim()).filter((x, i, a) => a.indexOf(x) === i)]))"""))
        print("   Karten (Namen, Chips):", CH)
        fin = [c for c in CH if "Heat" in c[0]]; others = [c for c in CH if "Heat" not in c[0]]
        check("beendetes Spiel (Heat/Bulls, Ergebnis 118:100): Chips in den Zeilen ('eingetreten' und 'nicht eingetreten'); laufendes (Pistons/Celtics) und kommende Spiele ohne Chips",
              fin and fin[0][1] >= 19 and set(fin[0][2]) <= {"eingetreten", "nicht eingetreten", "Push"} and "eingetreten" in fin[0][2] and len(others) == 3 and all(o[1] == 0 for o in others), str(CH))
        FIN = "[...document.querySelectorAll('[class*=\"st-key-sc_game_\"]')].find(g => g.innerText.includes('Heat'))"
        for blk in ("SPREAD", "TOTAL"):
            await js(f"[...{FIN}.querySelectorAll('[data-testid=\"stExpander\"]')].find(e => e.querySelector('summary').innerText.trim().split('\\n').pop().trim() === '{blk}').querySelector('summary').click()"); await asyncio.sleep(1.0)
        chipcol = json.loads(await js(f"""JSON.stringify([...{FIN}.querySelectorAll('.pc-lchip')].slice(0, 40).map(c => [c.textContent.trim(), getComputedStyle(c).backgroundColor, getComputedStyle(c).color]))"""))
        def not_green_red(rgb):
            r, g_, b = [int(x) for x in rgb[rgb.index("(") + 1:-1].split(",")[:3]]
            return not (g_ > r + 25 and g_ > b + 25) and not (r > g_ + 60 and r > b + 60)
        check("Chip-Farben: 'eingetreten' blau, 'nicht eingetreten'/'Push' grau - nie gruen oder rot", chipcol and all(not_green_red(c[1]) and not_green_red(c[2]) for c in chipcol), str(chipcol[:2]))
        rect = json.loads(await js(f"""(() => {{ const g = {FIN}; g.scrollIntoView({{block: 'start'}}); const b = g.getBoundingClientRect(); return JSON.stringify([b.left + scrollX, b.top + scrollY, b.width, b.height]); }})()"""))
        sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - 10), width=rect[2] + 40, height=rect[3] + 20, scale=1))
        (tmp / "score_beendet_chips.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot score_beendet_chips", tmp / "score_beendet_chips.png")
        PIS = "[...document.querySelectorAll('[class*=\"st-key-sc_game_\"]')].find(g => g.innerText.includes('Pistons'))"
        rect = json.loads(await js(f"""(() => {{ const g = {PIS}; g.scrollIntoView({{block: 'start'}}); const b = g.getBoundingClientRect(); return JSON.stringify([b.left + scrollX, b.top + scrollY, b.width, b.height]); }})()"""))
        sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - 10), width=rect[2] + 40, height=rect[3] + 20, scale=1))
        (tmp / "score_laufend_ohne_chips.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot score_laufend_ohne_chips", tmp / "score_laufend_ohne_chips.png")
        for blk in ("SPREAD", "TOTAL"):
            await js(f"[...{FIN}.querySelectorAll('[data-testid=\"stExpander\"]')].find(e => e.querySelector('summary').innerText.trim().split('\\n').pop().trim() === '{blk}').querySelector('summary').click()"); await asyncio.sleep(0.8)
        await toggle("SPREAD")
        spr = await rows_of(0); spo = (await det_states())[0][1]
        bars = json.loads(await js(f"JSON.stringify([...[...{EX}.querySelectorAll('[data-testid=\"stExpander\"]')][0].querySelectorAll('.pc-lbar')].map(b => Math.round(b.getBoundingClientRect().width)))"))
        mains = await js(f"[...{EX}.querySelectorAll('[data-testid=\"stExpander\"]')][0].querySelectorAll('.pc-lmain').length")
        check("SPREAD oeffnen: 5 Zeilen (Cache-Linie 4,3 -> 4,5: 2,5 ... 6,5), genau eine Hauptlinie, sichtbare Balken", spo and len(spr) == 5 and mains == 1 and all(w > 100 for w in bars) and "Knicks −2,5" in spr[0] and "Knicks −6,5" in spr[4], str(spr[:2]) + str(bars))
        await shoot_both("score_spread_offen")
        await toggle("TOTAL")
        trs = await rows_of(1)
        pos = json.loads(await js(f"""JSON.stringify((() => {{ const r = [...{EX}.querySelectorAll('[data-testid="stExpander"]')][1].querySelector('.pc-lrow'); const a = r.querySelector('.pc-lpct').getBoundingClientRect(), b = r.querySelector('.pc-lbar').getBoundingClientRect(), c = r.querySelector('.pc-lpct-r').getBoundingClientRect(); return [a.left, b.left, c.left]; }})())"""))
        check("TOTAL oeffnen: 7 Zeilen (228,5 ... 234,5), Over links, Balken Mitte, Under rechts", len(trs) == 7 and pos[0] < pos[1] < pos[2] and "Over" in trs[0] and "Under" in trs[0] and "232,0" in trs[3], str(trs[3]))
        await shoot_both("score_total_offen")
        await toggle("TEAM TOTAL · Knicks")
        tk = await rows_of(3); tkn = await js(f"[...{EX}.querySelectorAll('[data-testid=\"stExpander\"]')][3].innerText")
        check("TEAM TOTAL Knicks: rechnerische Hauptlinie (Total 232,0 / Spread 4,3 -> Heim 118,0) mit Hinweis, 7 Zeilen", len(tk) == 7 and "118,0" in tk[3] and "rechnerisch" in tkn, str(tk[3]) + " | " + tkn[-70:])
        await shoot_both("score_teamtotal_offen")
        # --- Darstellung bei 1440 / 900 / 700 px: grosse Zeilen, Plakette, nichts ueberlappt oder wird abgeschnitten
        for blk in ("SPREAD", "TOTAL"):
            if blk not in [t for t, o in await det_states() if o]: await toggle(blk)
        for w in (1440, 900, 700):
            await call("Emulation.setDeviceMetricsOverride", width=w, height=2600, deviceScaleFactor=1, mobile=False); await asyncio.sleep(2.0)
            m = json.loads(await js(f"""JSON.stringify((() => {{ const bad = []; let n = 0, pills = 0, orange = 0, minH = 999, minBar = 999, maxBar = 0, font = 0, barH = 0;
                const ex = {EX}; const exr = ex.getBoundingClientRect();
                for (const r of ex.querySelectorAll('.pc-lrow')) {{ n++; const rr = r.getBoundingClientRect(); minH = Math.min(minH, rr.height);
                  const parts = ['.pc-lline', '.pc-lpct-l', '.pc-lbar', '.pc-lpct-r'].map(q => r.querySelector(q).getBoundingClientRect());
                  const pl = r.querySelector('.pc-lpct-l .pc-lpill'), pr = r.querySelector('.pc-lpct-r .pc-lpill');
                  font = parseFloat(getComputedStyle(pl).fontSize); barH = parts[2].height; minBar = Math.min(minBar, parts[2].width); maxBar = Math.max(maxBar, parts[2].width);
                  const boxes = [parts[0], pl.getBoundingClientRect(), parts[2], pr.getBoundingClientRect()];
                  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {{ const a = boxes[i], b = boxes[j]; if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) bad.push('overlap ' + i + '/' + j + ' ' + r.innerText.replace(/\\n/g, ' ').slice(0, 40)); }}
                  for (const b of boxes) if (b.left < rr.left - 0.5 || b.right > rr.right + 0.5) bad.push('clip ' + r.innerText.replace(/\\n/g, ' ').slice(0, 40));
                  for (const pp of (pl, pr) ? [pl, pr] : []) if (pp.classList.contains('pc-lpct-pred')) {{ pills++; if (getComputedStyle(pp).backgroundColor === 'rgb(234, 88, 12)') orange++; }}
                  if (pl.scrollWidth > pl.clientWidth + 1 || pr.scrollWidth > pr.clientWidth + 1) bad.push('text-clip');
                }}
                return {{n, pills, orange, minH: Math.round(minH), font, barH, minBar: Math.round(minBar), maxBar: Math.round(maxBar), bad: bad.slice(0, 5), hscroll: document.documentElement.scrollWidth > innerWidth + 1, exW: Math.round(exr.width)}}; }})())"""))
            print(f"   Breite {w}px:", m)
            check(f"{w} px: mind. 19 Zeilen offen; Schrift 15-16 px, Balken 14 px, Zeilenhoehe >= 44 px (schmal: zweizeilig), keine Ueberlappung/Abschneiden, kein horizontales Scrollen",
                  m["n"] >= 19 and m["font"] >= 15 and m["barH"] == 14 and (m["minH"] >= 44) and not m["bad"] and not m["hscroll"] and m["minBar"] >= 80, str(m))
            check(f"{w} px: jede Zeile hat genau eine Plakette im abgedunkelten Orange (kein Gruen/Rot), ausser bei exakt 50 : 50", m["pills"] == m["orange"] and m["pills"] >= m["n"] - 1, f"{m['pills']} Plaketten, {m['orange']} orange")
            await shoot_both(f"score_breite_{w}")
        await call("Emulation.setDeviceMetricsOverride", width=1440, height=2600, deviceScaleFactor=1, mobile=False); await asyncio.sleep(1.0)
        await toggle("SPREAD"); await toggle("TOTAL"); await toggle("TEAM TOTAL · Knicks")
        check("Expander schliessen/oeffnen funktioniert (alle wieder zu)", not any(o for t, o in await det_states()))
        # --- eigene Linie in der Pre-Match Eingabe speichern
        await toggle("SPREAD"); await toggle("TOTAL")
        st_before = await det_states()
        await js(f"{TAB('Pre-Match')}.click()"); await asyncio.sleep(2.0)
        await js(f"{TAB('Score Projections')}.click()"); await asyncio.sleep(2.0)
        st_tabs = await det_states()
        print("   Tabwechsel ohne Rerun: Zustand vorher/nachher:", st_before, "->", st_tabs)
        await js(f"{TAB('Pre-Match')}.click()"); await asyncio.sleep(2.0)
        PM = "document.querySelector('[class*=\"st-key-pm_card_\"]:has(input[aria-label=\"Linie Heim · Knicks\"])')"
        await js(f"[...{PM}.querySelectorAll('[data-testid=\"stExpander\"]')].find(e => e.querySelector('summary').innerText.trim().split('\\n').pop().trim() === 'TOTAL').querySelector('summary').click()"); await asyncio.sleep(1.2)
        await typein(f"{PM}.querySelector('input[aria-label=\"Linie\"]')", "240,5")
        await typein(f"{PM}.querySelector('input[aria-label=\"Quote Over\"]')", "1,9"); await typein(f"{PM}.querySelector('input[aria-label=\"Quote Under\"]')", "1,9")
        await typein(f"{PM}.querySelectorAll('input[aria-label=\"Buchmacher\"]')[2]", "Betano")
        await js("""(() => { document.querySelectorAll('[role="tabpanel"]').forEach((p, i) => p.__m = 'panel' + i); document.querySelectorAll('.pc-card').forEach((c, i) => c.__m = 'card' + i);
            document.querySelectorAll('[class*="st-key-pm_card_"]').forEach((c, i) => c.__m = 'pm' + i); document.querySelectorAll('[class*="st-key-sc_lines_"]').forEach((c, i) => c.__m = 'sc' + i);
            document.querySelectorAll('[data-testid="stTabs"]').forEach((c, i) => c.__m = 'tabs' + i); })()""")
        await js(f"[...{PM}.querySelectorAll('button')].find(b => b.innerText.trim() === 'Speichern').click()"); await asyncio.sleep(6.0)
        st_hidden = await det_states()
        print("   Score-Expander direkt nach dem Speichern (Pre-Match-Tab aktiv, Score-Tab verborgen):", st_hidden)
        surv2 = await js("""JSON.stringify([...document.querySelectorAll('[role="tabpanel"], .pc-card, [class*="st-key-pm_card_"], [class*="st-key-sc_lines_"], [data-testid="stTabs"]')].map(e => e.__m || ('NEU:' + (e.getAttribute('role') || e.className.toString().slice(0, 18)))))""")
        print("   Knoten-Identitaet nach dem Speichern:", surv2)
        saved = json.loads((tmp / "tracking" / "pre_match_entries.json").read_text()) if (tmp / "tracking" / "pre_match_entries.json").exists() else {"entries": {}}
        ent = [v for v in saved["entries"].values() if v["home"] == "New York Knicks"]
        check("Pre-Match: Total 240,5 (Betano) gespeichert (Temp-Datei)", ent and ent[0]["markets"]["total"]["lines"][0]["line"] == 240.5 and ent[0]["markets"]["total"]["lines"][0]["bookmaker"] == "Betano", str(ent[:1])[:100])
        pm_states = await js(f"JSON.stringify([...{PM}.querySelectorAll('[data-testid=\"stExpander\"]')].map(e => [{TTL}, e.querySelector('details').open]))")
        print("   Pre-Match-Expander nach dem Speichern (voller Rerun, ECHTE App mit Tabs):", pm_states)
        check("ECHTE App (mit Tabs): der in der Pre-Match Eingabe geoeffnete Markt TOTAL bleibt nach dem Speichern (erster voller Rerun nach dem Laden) offen, die anderen zu", json.loads(pm_states) == [["SIEGER INKL. OT", False], ["SPREAD", False], ["TOTAL", True], ["TEAM TOTALS", False], ["SPIELERPUNKTE", False]], pm_states)
        await js(f"{TAB('Score Projections')}.click()"); await asyncio.sleep(2.5)
        origin2 = await js(f"{SC}.querySelector('.pc-origin').innerText")
        check("Score Projections nach dem Speichern: Herkunftszeile 'Total: Eigene Linie · Betano · HH:MM', Spread weiter Cache", "Total: Eigene Linie · Betano · " in origin2 and origin2.startswith("Spread: Cache "), origin2)
        warn = await js(f"{SC}.querySelector('.pc-warnings:last-of-type') ? {SC}.innerText : ''")
        check("gelber Hinweis 'Total: Eigene Linie weicht stark vom Cache ab (240,5 vs. 232,0), bitte pruefen'", "Total: Eigene Linie weicht stark vom Cache ab (240,5 vs. 232,0), bitte prüfen" in (warn or ""))
        st_after = await det_states()
        print("   Expander-Zustand vor/nach vollem Rerun:", st_before, "->", st_after)
        check("Expander-Zustand nach dem vollen Rerun (Karte und Inhalt geaendert): SPREAD und TOTAL offen geblieben, die anderen zu", st_after == st_before, str(st_after))
        trows = await rows_of(1)
        check("TOTAL zeigt jetzt genau die eigene Linie 240,5 (eine Zeile, Hauptlinie)", len(trows) == 1 and "240,5" in trows[0] and "hauptlinie" in trows[0].lower(), str(trows))
        await shoot_both("score_eigene_linie")
        # --- Reihenfolge der Karten aendert sich (Sortierung nach |Spread|): Expander-Zustand muss beim Spiel bleiben
        await js(f"{TAB('Score Projections')}.click()"); await asyncio.sleep(1.5)
        async def games():
            """je Karte (SICHTBARE Reihenfolge von oben nach unten): [Spiel (Team-Total-Titel), Container-Schluessel, Namen der Karte darueber, offene Expander]"""
            return json.loads(await js("""JSON.stringify([...document.querySelectorAll('[class*="st-key-sc_lines_"]')].sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top).map(c => {
                const k = [...c.classList].find(x => x.startsWith('st-key-sc_lines_'));
                const tt = [...c.querySelectorAll('[data-testid="stExpander"]')].map(e => e.querySelector('summary').innerText.trim().split('\\n').pop().trim());
                const card = c.closest('[class*="st-key-sc_game_"]').querySelector('.pc-card');
                const names = card ? [...card.querySelectorAll('.pc-name')].map(n => n.innerText).join('/') : '?';
                const open = [...c.querySelectorAll('[data-testid="stExpander"]')].filter(e => e.querySelector('details').open).map((e, i) => e.querySelector('summary').innerText.trim().split('\\n').pop().trim());
                return [tt[2] + '|' + tt[3], k, names, open]; }))"""))
        async def toggle_in(idx, title):
            await js(f"""[...[...document.querySelectorAll('[class*="st-key-sc_lines_"]')].sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)[{idx}].querySelectorAll('[data-testid="stExpander"]')].find(e => e.querySelector('summary').innerText.trim().split('\\n').pop().trim() === '{title}').querySelector('summary').click()"""); await asyncio.sleep(1.0)
        # Ausgangslage: alle Expander zu (Knicks-Karte hat noch SPREAD + TOTAL offen -> schliessen)
        for gi, g in enumerate(await games()):
            for t in g[3]: await toggle_in(gi, t)
        g0 = await games()
        check("Reihenfolge-Test: mindestens 3 Karten mit Expandern, alle zu", len(g0) >= 3 and not any(g[3] for g in g0), str([(g[0], g[2]) for g in g0]))
        await toggle_in(0, "SPREAD"); await toggle_in(1, "TOTAL")
        gA = await games()
        want = {gA[0][0]: ["SPREAD"], gA[1][0]: ["TOTAL"]}
        check("Reihenfolge-Test: Karte 1 hat SPREAD offen, Karte 2 TOTAL offen, Rest zu; Namen der Karte stimmen mit dem Spiel des Expander-Blocks ueberein", [g[3] for g in gA][:2] == [["SPREAD"], ["TOTAL"]] and not any(g[3] for g in gA[2:])
              and all(g[0].split("|")[0].endswith(g[2].split("/")[0]) and g[0].split("|")[1].endswith(g[2].split("/")[1]) for g in gA), str(gA)[:300])
        # Reihenfolge erzwingen: Knicks-Eigenlinie so setzen, dass die Karte die Position wechselt (Temp-Datei der Test-App, nicht die echte)
        os.environ["NBAEDGE_TRACKING_DIR"] = str(tmp / "tracking")
        import data.pre_match_store as psx
        ent = [v for v in psx.load()["entries"].values() if v["home"] == "New York Knicks"][0]
        # Ausgangslage aus der App lesen (nicht raten): sichtbare Reihenfolge der Karten mit Namen (Gast/Heim) und dem angezeigten Modell-Spread (|Spread| der Karte).
        async def card_info():
            return json.loads(await js("""JSON.stringify([...document.querySelectorAll('[class*="st-key-sc_game_"]')].sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top).map(g => {
                const names = [...g.querySelectorAll('.pc-name')].map(n => n.innerText);
                const m = g.querySelector('.pc-model'); const t = m ? m.innerText : '';
                return [names.join('/'), t]; }))"""))
        # feste Schluessel der App (ui/score_order.py + app.py): Statusgruppe (nicht begonnen 0, laeuft 1, beendet 2), Anpfiff, -|exp_spread|, Eingabereihenfolge.
        # Im Harness bekannt: Knicks und Spurs beginnen gleichzeitig (T0 + 3 h, Gruppe 0), Pistons laeuft (Gruppe 1), das Spiel Heat/Bulls ist beendet (Gruppe 2).
        GROUP = {"Knicks": 0, "Spurs": 0, "Pistons": 1, "Heat": 2}
        HOME = {"Knicks": ("New York Knicks", "Philadelphia 76ers"), "Spurs": ("San Antonio Spurs", "Oklahoma City Thunder")}
        def spread_of(model_text):
            mm = re.search(r"Modell\s+\S+\s+[\u2212-](\d+(?:[.,]\d)?)", model_text)       # "SPREAD Modell Knicks −6,1 Markt ..." (Minuszeichen U+2212); "PK" hat kein Minus -> 0
            return float(mm.group(1).replace(",", ".")) if mm else 0.0     # "PK" (Spread 0) hat kein Minus
        def key_view(info):
            return [(GROUP.get(n.split("/")[1], 9), spread_of(t), n.split("/")[1]) for n, t in info]
        def order_ok(info):
            kv = key_view(info)
            return len(kv) >= 4 and all(v_[1] > 0 for v_ in kv if v_[0] == 0) and all(a_[0] <= b_[0] for a_, b_ in zip(kv, kv[1:])) and all(a_[1] >= b_[1] for a_, b_ in zip(kv, kv[1:]) if a_[0] == b_[0] == 0)
        infoA = await card_info()
        print("   Ausgangslage (Karte: Modell-Text):", [(n, t.replace("\n", " ")[:50]) for n, t in infoA])
        check("Reihenfolge-Test: Ausgangslage folgt dem Schluessel der App (Gruppe: nicht begonnen vor laufend vor beendet; bei gleichem Anpfiff absteigend nach |Spread|)", order_ok(infoA), str(key_view(infoA)))
        second = key_view(infoA)[1][2]                     # zweite Karte der Gruppe 0: bekommt den groessten |Spread| und muss dadurch nach oben wandern
        assert second in HOME, f"zweite Karte ist kein Spiel der Gruppe 0: {second}"
        sg_home, sg_away = HOME[second]
        psx.save_card(ent["game_date"], ent["start_utc"], sg_home, sg_away, spread_rows=[{"id": "main", "line": -30.0, "home_odds": "1,9", "away_odds": "1,9", "bookmaker": "Betano"}], now=app_now())    # Eingabe-Zeile "line" = line_home, negativ = Heim-Favorit
        await js("document.body.click()"); await call("Input.dispatchKeyEvent", type="keyDown", key="r", code="KeyR", text="r", windowsVirtualKeyCode=82); await call("Input.dispatchKeyEvent", type="keyUp", key="r", code="KeyR", windowsVirtualKeyCode=82)
        await asyncio.sleep(8.0)
        gB = await games()
        print("   Herkunft Knicks nach der Aenderung:", await js(f"{SC}.querySelector('.pc-origin').innerText"))
        print("   Reihenfolge vorher:", [g[2] for g in gA], " nachher:", [g[2] for g in gB])
        infoB = await card_info()
        print("   Nachher (Karte: Modell-Text):", [(n, t.replace("\n", " ")[:50]) for n, t in infoB])
        check("Reihenfolge-Test: die Kartenreihenfolge hat sich wirklich geaendert, folgt weiter dem Schluessel der App, und die Karte mit dem groessten |Spread| steht jetzt in Gruppe 0 vorn",
              [g[0] for g in gA] != [g[0] for g in gB] and order_ok(infoB) and key_view(infoB)[0][2] == second, str(key_view(infoB)))
        check("Reihenfolge-Test: Der Zustand folgt dem SPIEL, nicht der Position (SPREAD offen beim selben Spiel wie vorher, TOTAL beim selben Spiel, alle anderen zu)",
              {g[0]: g[3] for g in gB if g[3]} == want and all(g[0].split("|")[0].endswith(g[2].split("/")[0]) for g in gB), str([(g[2], g[3]) for g in gB]))
        await shoot_both("score_nach_umsortierung")
        body = await js("document.body.innerText")
        check("im gesamten Browser-Text keine Exception/Traceback", "Traceback" not in body and "StreamlitAPIException" not in body)
        return True
    asyncio.run(main())
    check("echte data/tracking/pre_match_entries.json unveraendert", (real_file.read_bytes() if real_file.exists() else None) == real_bytes)
    check("echte projection_snapshots.json nicht angelegt/geaendert durch den Test", (ROOT / "data" / "tracking" / "projection_snapshots.json").exists() == real_snap_existed)
    check("echte data/rosters.json unveraendert", (real_roster.read_bytes() if real_roster.exists() else None) == real_roster_bytes)
    failed = False
finally:
    stop(chrome); stop(server)
    import shutil
    shutil.rmtree(tmp / "profile", ignore_errors=True)       # Chrome-Profil (ca. 200 MB) nicht liegen lassen; Screenshots und Zaehler bleiben
    if failed or not ok:
        print("--- Serverausgabe (Streamlit) ---"); print(server_log.read_text(errors="replace")[-4000:] if server_log.exists() else "(keine)")
        print("--- Chrome-Ausgabe ---"); print(chrome_log.read_text(errors="replace")[-1500:] if chrome_log.exists() else "(keine)")
print("\nErgebnis:", "ALLE BROWSER-PRUEFUNGEN BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
