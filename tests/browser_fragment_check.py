"""Echter Browsertest (headless Chrome) fuer Fragmente und Layout im Tab 'Pre-Match Eingabe'. NICHT Teil der normalen Testsuite
(braucht Google Chrome). Startet ein Streamlit-Harness ohne Netzwerk (Temp-Ordner), steuert Chrome per DevTools-Protokoll.
Aufruf aus dem Projektordner: venv/bin/python tests/browser_fragment_check.py"""
import asyncio, json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
tmp = Path(tempfile.mkdtemp(prefix="nbaedge_browser_")); counter = tmp / "counter.json"; counter.write_text("{}")
T0 = time.time()
env = {**os.environ, "NBAEDGE_HARNESS_T0": str(T0), "NBAEDGE_TRACKING_DIR": str(tmp / "tracking"), "NBAEDGE_COUNTER_FILE": str(counter), "NBAEDGE_ROSTERS": str(tmp / "rosters.json"), "PYTHONDONTWRITEBYTECODE": "1"}
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
def counts(): return json.loads(counter.read_text())

# Vorbereitung: Knicks-Karte mit gespeicherten Werten (damit 'Speichern' ohne Aenderung moeglich ist)
import datetime as dt
import data.pre_match_store as ps
os.environ["NBAEDGE_TRACKING_DIR"] = str(tmp / "tracking")
day = dt.date.today().isoformat(); iso = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ps.save_card(day, iso(T0 + 3 * 3600), "New York Knicks", "Philadelphia 76ers", winner={"home_odds": "1,55", "away_odds": "2,50", "bookmaker": "Betano"},
             spread_rows=[{"id": "main", "line": "-4,5", "home_odds": "1,91", "away_odds": "1,95", "bookmaker": "Pinnacle"}], now=T0)
sys.path.insert(0, str(ROOT / "tests"))
import data.rosters as ro
from roster_fixture import fake_index
os.environ["NBAEDGE_ROSTERS"] = str(tmp / "rosters.json")
ro.write(ro.build(fake_index(), dt.datetime.now().astimezone().isoformat(timespec="seconds"), "2026-27"))          # gefaelschter Kader, kein Netz
real_roster = ROOT / "data" / "rosters.json"; real_roster_bytes = real_roster.read_bytes() if real_roster.exists() else None
real = ROOT / "data" / "tracking" / "pre_match_entries.json"; real_bytes = real.read_bytes() if real.exists() else None

server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "tests" / "_harness_pre_match.py"), "--server.port", "8768", "--server.headless", "true",
                           "--browser.gatherUsageStats", "false"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--remote-debugging-port=9335", f"--user-data-dir={tmp / 'profile'}", "--no-first-run", "about:blank"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try: urllib.request.urlopen("http://localhost:8768/healthz", timeout=1); break
        except Exception: time.sleep(0.5)
    for _ in range(60):
        try: pages = json.load(urllib.request.urlopen("http://localhost:9335/json/list")); break
        except Exception: time.sleep(0.5)
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
            if res.get("exceptionDetails"):
                print("JS-Fehler:", res["exceptionDetails"].get("exception", {}).get("description", "")[:300])
            return res.get("result", {}).get("value")
        await call("Emulation.setDeviceMetricsOverride", width=1440, height=2600, deviceScaleFactor=1, mobile=False)
        await call("Page.navigate", url="http://localhost:8768/")
        await asyncio.sleep(12)

        print("Seite geladen:", (await js("document.body.innerText.slice(0, 120)")) or "(leer)", "| Skriptlaeufe:", counts())
        CARD = "document.querySelector('[class*=\"st-key-pm_card_\"]:has(input[aria-label=\"Linie Heim · Knicks\"])')"
        INP = lambda label: f"{CARD}.querySelector('input[aria-label=\"{label}\"]')"
        BTN = lambda text: f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.trim() === '{text}')"
        val = lambda label: js(f"{INP(label)}.value")
        click = lambda text: js(f"{BTN(text)}.click()")

        # ---------------- Expander: Kopf sichtbar, alle Maerkte standardmaessig zu
        TITLES = ["SIEGER INKL. OT", "SPREAD", "TOTAL", "TEAM TOTALS", "SPIELERPUNKTE"]
        async def states():
            return json.loads(await js(f"""JSON.stringify([...{CARD}.querySelectorAll('[data-testid="stExpander"]')].map(e => [e.querySelector('summary').innerText.trim().split('\\n').pop().trim(), e.querySelector('details').open]))"""))
        async def toggle(title):
            await js(f"""[...{CARD}.querySelectorAll('[data-testid="stExpander"]')].find(e => e.querySelector('summary').innerText.trim().split('\\n').pop().trim() === '{title}').querySelector('summary').click()"""); await asyncio.sleep(1.0)
        async def shoot_el(nm, expr, pad=40):
            rect = json.loads(await js(f"""(() => {{ const e = {expr}; e.scrollIntoView({{block: 'center'}}); const b = e.getBoundingClientRect(); return JSON.stringify([b.left + scrollX, b.top + scrollY, b.width, b.height]); }})()"""))
            sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - pad), width=rect[2] + 40, height=rect[3] + pad + 30, scale=1))
            import base64; (tmp / f"{nm}.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot", nm, tmp / f"{nm}.png", f"({rect[3]:.0f} px hoch)")
        st0 = await states()
        check("Karte: fuenf Maerkte als Expander mit festem Titel (Grossbuchstaben), standardmaessig ALLE zu", [t for t, o in st0] == TITLES and not any(o for t, o in st0), str(st0))
        headvis = json.loads(await js(f"""(() => {{ const c = {CARD}; const r = e => {{ const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; }};
            const sv = [...c.querySelectorAll('button')].find(b => b.innerText.trim() === 'Speichern');
            return JSON.stringify({{kopf: c.innerText.includes('Knicks') && c.innerText.includes('76ers') && c.innerText.includes('Vorab'), chip: c.innerText.includes('offen') || c.innerText.includes('gespeichert'), speichern: r(sv), hint: c.innerText.includes('Bis zum Anpfiff änderbar'),
            hoehe: Math.round(c.getBoundingClientRect().height), spread_main_visible: c.querySelector('input[aria-label="Linie Heim · Knicks"]').checkVisibility()}}); }})()"""))
        check("Kartenkopf (Logos/Teams/Zeit/Vorab/Chip) sichtbar, Speichern-Knopf und 'Bis zum Anpfiff aenderbar' sichtbar, Eingabefelder der zugeklappten Maerkte NICHT sichtbar", headvis["kopf"] and headvis["chip"] and headvis["speichern"] and headvis["hint"] and not headvis["spread_main_visible"], str(headvis))
        print("   Hoehe der zugeklappten Karte:", headvis["hoehe"], "px")
        await shoot_el("karte_zu", CARD, pad=20)
        await toggle("SPREAD")
        st1 = await states()
        check("SPREAD oeffnen: nur SPREAD ist offen, Felder sichtbar", [t for t, o in st1 if o] == ["SPREAD"] and await js(f"{CARD}.querySelector('input[aria-label=\"Linie Heim · Knicks\"]').checkVisibility()"), str(st1))
        await shoot_el("karte_spread_offen", CARD, pad=20)
        await toggle("SPREAD")
        check("SPREAD schliessen: wieder alle zu", not any(o for t, o in await states()))
        for t in TITLES: await toggle(t)
        check("alle Maerkte oeffnen: alle fuenf offen", all(o for t, o in await states()))
        tcount0 = counts()["script"]

        # ---------------- Layout (Geometrie)
        g = await js(f"""(() => {{ const r = e => {{ const b = e.getBoundingClientRect(); return [b.left, b.right, b.width, b.top]; }};
            const card = {CARD}; const cb = card.getBoundingClientRect();
            const q = l => card.querySelector('input[aria-label="' + l + '"]');
            const btns = [...card.querySelectorAll('button')];
            const minus = btns.find(b => b.innerText.trim() === '−'), plus = btns.find(b => b.innerText.trim() === '+');
            const titles = [...card.querySelectorAll('.pm-market-title')].map(t => {{ const rg = document.createRange(); rg.selectNodeContents(t); return r(rg); }});
            return JSON.stringify({{card: [cb.left, cb.right], lg: r(q('Linie Gast · 76ers')), lh: r(q('Linie Heim · Knicks')), qg: r(q('Quote Gast · 76ers')), qh: r(q('Quote Heim · Knicks')),
               book: r(card.querySelector('input[aria-label="Buchmacher"]')), minus: r(minus), plus: r(plus), titles}}); }})()""")
        g = json.loads(g); mid = lambda a: (a[0] + a[1]) / 2
        center = (g["lg"][0] + g["lh"][1]) / 2
        check("Linienzeile: Gast- und Heim-Feld gleich breit", abs(g["lg"][2] - g["lh"][2]) < 2, f"{g['lg'][2]:.0f} / {g['lh'][2]:.0f} px")
        check("Quotenzeile: Gast- und Heim-Feld gleich breit, gleiche Breite wie die Linienfelder", abs(g["qg"][2] - g["qh"][2]) < 2 and abs(g["qg"][2] - g["lg"][2]) < 2)
        check("Linienzeile: Gast links, -/+ in der Mitte zwischen den Feldern, Heim rechts", g["lg"][1] < g["minus"][0] and g["plus"][1] < g["lh"][0] and g["lg"][0] < g["lh"][0])
        check("-/+ symmetrisch zwischen den Linienfeldern (Mitte der beiden Knoepfe = Mitte der Luecke)", abs((g["minus"][0] + g["plus"][1]) / 2 - (g["lg"][1] + g["lh"][0]) / 2) < 3, f"{(g['minus'][0] + g['plus'][1]) / 2:.0f} / {(g['lg'][1] + g['lh'][0]) / 2:.0f}")
        check("Quotenzeile: Buchmacher in der Mitte zwischen Quote Gast und Quote Heim", g["qg"][1] < g["book"][0] and g["book"][1] < g["qh"][0] and abs(mid(g["book"]) - center) < 3, f"{mid(g['book']):.0f} / {center:.0f}")
        check("Marktnamen mittig zentriert (Mitte des Textes = Mitte der Karte)", all(abs(mid(t) - (g["card"][0] + g["card"][1]) / 2) < 6 or abs(mid(t) - center) < 6 for t in g["titles"][:2]), str([round(mid(t)) for t in g["titles"][:2]]) + f" Karte {round((g['card'][0] + g['card'][1]) / 2)}")

        # ---------------- Fragment: Klick auf +/- laedt nur die Karte neu
        c0 = counts()
        before = await val("Linie Heim · Knicks"), await val("Linie Gast · 76ers")
        await click("+"); await asyncio.sleep(2.0)
        c1 = counts(); after = await val("Linie Heim · Knicks"), await val("Linie Gast · 76ers")
        check("Klick auf '+': Linie aendert sich sofort (Heim +0,5, Gast folgt)", before != after, f"{before} -> {after}")
        check("Klick auf '+': KEIN voller Skriptlauf (Zaehler 'script' unveraendert)", c1["script"] == c0["script"], f"script {c0['script']} -> {c1['script']}")
        check("Klick auf '+': nur der Eingabebereich der Karte wurde neu aufgebaut (line_row-Zaehler steigt)", c1.get("line_row", 0) > c0.get("line_row", 0), f"line_row {c0.get('line_row')} -> {c1.get('line_row')}")
        await click("−"); await asyncio.sleep(1.5); await click("−"); await asyncio.sleep(1.5)
        c2 = counts()
        check("Klicks auf '-': weiterhin kein voller Skriptlauf", c2["script"] == c0["script"], f"script {c2['script']}")
        # '+ Weitere Linie hinzufuegen'
        await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Weitere Linie hinzufügen')).click()"); await asyncio.sleep(2.0)
        c3 = counts(); n_rows = await js(f"{CARD}.querySelectorAll('input[aria-label=\"Linie Heim · Knicks\"]').length")
        check("'+ Weitere Linie hinzufuegen': neue Zeile erscheint, kein voller Skriptlauf", n_rows == 2 and c3["script"] == c0["script"], f"Zeilen {n_rows}, script {c3['script']}")
        # Eingabe in ein Linienfeld (Tippen + Tab): nur Fragment
        await js(f"{INP('Linie Heim · Knicks')}.focus()"); await call("Input.dispatchKeyEvent", type="keyDown", key="a", modifiers=4)
        await js(f"{INP('Linie Heim · Knicks')}.select()"); await call("Input.insertText", text="-3,5")
        await call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9); await call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
        await asyncio.sleep(2.0); c4 = counts()
        check("Eingabe -3,5 im Heim-Feld: Gast-Feld zeigt +3,5, kein voller Skriptlauf", await val("Linie Gast · 76ers") == "+3,5" and c4["script"] == c0["script"], f"{await val('Linie Gast · 76ers')}, script {c4['script']}")
        # ---------------- Markt Total: Layout, Fragment, Knopffarben
        TL = f"{CARD}.querySelector('input[aria-label=\"Linie\"]')"
        async def typein(expr, text):
            await js(f"{expr}.focus()"); await js(f"{expr}.select()"); await call("Input.insertText", text=text)
            await call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9); await call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
            await asyncio.sleep(1.5)
        tot_over = f"{CARD}.querySelector('input[aria-label=\"Quote Over\"]')"
        check("Total: Hauptlinie mit der Vorab-Marktlinie vorbefuellt (232,0), Vorschlag-Zeile sichtbar", await js(f"{TL}.value") == "232,0" and "Vorschlag aus Markt (Vorab-Linie): 232,0" in (await js(f"{CARD}.innerText") or ""))
        ctext = await js(f"{CARD}.innerText") or ""
        check("Total: Beschriftungen 'Quote Over · 232,0' und 'Quote Under · 232,0' sichtbar", "Quote Over · 232,0" in ctext and "Quote Under · 232,0" in ctext)
        tg = json.loads(await js(f"""(() => {{ const card = {CARD}; const r = e => {{ const b = e.getBoundingClientRect(); return [b.left, b.right, b.width, (b.top + b.bottom) / 2]; }};
            const line = card.querySelector('input[aria-label="Linie"]'); const lr = r(line);
            const near = [...card.querySelectorAll('button')].filter(b => Math.abs(r(b)[3] - lr[3]) < 20).map(b => [b.innerText.trim(), ...r(b)]);
            const ov = card.querySelector('input[aria-label="Quote Over"]'), un = card.querySelector('input[aria-label="Quote Under"]');
            const books = [...card.querySelectorAll('input[aria-label="Buchmacher"]')].map(r);
            const cb = card.getBoundingClientRect();
            return JSON.stringify({{line: lr, near, ov: r(ov), un: r(un), books, card: [cb.left, cb.right]}}); }})()"""))
        mn = [b for b in tg["near"] if b[0] == "−"][0]; pl = [b for b in tg["near"] if b[0] == "+"][0]; ln_ = tg["line"]
        gap_l, gap_r = ln_[0] - mn[2], pl[1] - ln_[1]
        check("Total-Linienzeile: '-' links, Linie in der Mitte, '+' rechts (gleicher Abstand links/rechts)", mn[2] < ln_[0] and pl[1] > ln_[1] and abs(gap_l - gap_r) < 3, f"Abstand links {gap_l:.0f} / rechts {gap_r:.0f} px")
        check("Total: Linienfeld liegt in der Mitte der Karte-Spalten (gleiche Mitte wie das Buchmacher-Feld und gleiche Breite)", abs((ln_[0] + ln_[1]) / 2 - (tg["ov"][1] + tg["un"][0]) / 2) < 3 and abs(ln_[2] - tg["ov"][2] * 0.8) < 6 or abs(ln_[2] - tg["books"][-1][2]) < 3, f"Linie {ln_[2]:.0f}, Over {tg['ov'][2]:.0f}, Under {tg['un'][2]:.0f}")
        check("Total-Quotenzeile: Over und Under gleich breit, Over links, Under rechts", abs(tg["ov"][2] - tg["un"][2]) < 2 and tg["ov"][1] < tg["un"][0], f"{tg['ov'][2]:.0f} / {tg['un'][2]:.0f}")
        await typein(tot_over, "1,95")
        t0 = counts()
        await js(f"[...{CARD}.querySelectorAll('button')].filter(b => Math.abs((b.getBoundingClientRect().top + b.getBoundingClientRect().bottom) / 2 - {tg['line'][3]}) < 20 && b.innerText.trim() === '+')[0].click()"); await asyncio.sleep(2.0)
        t1 = counts(); body_t = await js(f"{CARD}.innerText") or ""
        check("Total '+': Linie 232,5, Beschriftung 'Quote Over · 232,5', eingegebene Over-Quote bleibt, KEIN voller Skriptlauf, nur Total-Zeilen neu aufgebaut",
              await js(f"{TL}.value") == "232,5" and "Quote Over · 232,5" in body_t and await js(f"{tot_over}.value") == "1,95" and t1["script"] == t0["script"] and t1.get("total_row", 0) > t0.get("total_row", 0),
              f"script {t0['script']} -> {t1['script']}, total_row {t0.get('total_row')} -> {t1.get('total_row')}")
        for _ in range(3):
            await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.trim() === '+ Höhere Linie').click()"); await asyncio.sleep(1.5)
        for _ in range(3):
            await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.trim() === '− Niedrigere Linie').click()"); await asyncio.sleep(1.5)
        t2 = counts(); body_t = await js(f"{CARD}.innerText") or ""
        lines_t = json.loads(await js(f"JSON.stringify([...{CARD}.querySelectorAll('input[aria-label=\"Linie\"], input[aria-label=\"Weitere Linie\"]')].map(i => i.value))"))
        dis = json.loads(await js(f"JSON.stringify(['+ Höhere Linie', '− Niedrigere Linie'].map(t => [...{CARD}.querySelectorAll('button')].find(b => b.innerText.trim() === t).disabled))"))
        check("Total: je 3 hoehere und niedrigere Linien, sortiert (hoehere oben, dann niedrigere), Knoepfe deaktiviert, Notizen", lines_t[:7] == ["232,5", "235,5", "234,5", "233,5", "231,5", "230,5", "229,5"] and dis == [True, True]
              and "maximal 3 höhere Linien" in body_t and "maximal 3 niedrigere Linien" in body_t and t2["script"] == t0["script"], f"{lines_t} {dis} script {t2['script']}")
        # Knopffarben im echten Browser: Orange nur Speichern
        cols = json.loads(await js(f"""JSON.stringify([...{CARD}.querySelectorAll('button')].filter(b => b.offsetParent).map(b => [b.innerText.trim().slice(0, 24), getComputedStyle(b).backgroundColor, getComputedStyle(b).color, b.getAttribute('data-testid')]))"""))
        orange = [c[0] for c in cols if c[1] == "rgb(249, 115, 22)"]
        rm = [c for c in cols if c[0] == "Entfernen"]
        print("   Knopffarben:", [(c[0], c[1]) for c in cols][:14])
        check("Knopfstil (Browser): ausschliesslich 'Speichern' ist orange", orange == ["Speichern"], str(orange))
        check("Knopfstil (Browser): 'Entfernen' hat keinen Hintergrund (transparent) und ist nicht orange", len(rm) >= 6 and all(c[1] in ("rgba(0, 0, 0, 0)", "transparent") and c[2] != "rgb(249, 115, 22)" for c in rm), str(rm[:2]))
        check("Knopfstil (Browser): '+ Weitere Linie', '+ Hoehere Linie', '- Niedrigere Linie', -/+ sind grau (nicht orange)", all(c[1] != "rgb(249, 115, 22)" for c in cols if c[0] != "Speichern"))
        await js(f"{CARD}.scrollIntoView()"); await asyncio.sleep(0.5)
        shot0 = await call("Page.captureScreenshot", format="png")
        import base64; (tmp / "total_buttons.png").write_bytes(base64.b64decode(shot0["result"]["data"])); print("Screenshot Total:", tmp / "total_buttons.png")
        # ---------------- Spread mit 4 weiteren Linien (Limit 5 Linien wie die Leiter), Team Totals (je Team 6), kompakte Zeilen
        for _ in range(3):
            await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Weitere Linie hinzufügen')).click()"); await asyncio.sleep(2.5)
        n_sp = await js(f"{CARD}.querySelectorAll('input[aria-label=\"Linie Heim · Knicks\"]').length")
        check("Spread: 4 weitere Linien moeglich (Hauptlinie + 4 kompakte Zeilen), danach Knopf deaktiviert", n_sp == 5 and await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Weitere Linie hinzufügen')).disabled"), str(n_sp))
        tc0 = counts()
        for idx in (1, 2):                                      # Gast, Heim (Index 0 = Total)
            for text in ('+ Höhere Linie', '− Niedrigere Linie'):
                for _ in range(3):
                    await js(f"[...{CARD}.querySelectorAll('button')].filter(b => b.innerText.trim() === '{text}')[{idx}].click()"); await asyncio.sleep(2.5)
        await asyncio.sleep(2.0); tc1 = counts()
        tl_vals = json.loads(await js(f"JSON.stringify([...{CARD}.querySelectorAll('input[aria-label=\"Linie\"], input[aria-label=\"Weitere Linie\"]')].map(i => i.value))"))
        check("Team Totals: je Team 3 hoehere + 3 niedrigere Linien, kein voller Skriptlauf", len(tl_vals) == 7 + 7 + 7 and tc1["script"] == tc0["script"], f"{len(tl_vals)} Linienfelder, script {tc0['script']} -> {tc1['script']}")
        # eine weitere Linie ist genau EINE Zeile hoch (alle Felder auf einer Hoehe, Hoehe = Feldhoehe)
        rows_m = json.loads(await js(f"""(() => {{ const out = []; for (const el of {CARD}.querySelectorAll('input[aria-label="Weitere Linie"]')) {{
            const row = el.closest('[data-testid="stHorizontalBlock"]'); const rb = row.getBoundingClientRect(); const eb = el.getBoundingClientRect();
            const els = [...row.querySelectorAll('input, button')].filter(x => x.getBoundingClientRect().width > 0); const cs = els.map(x => {{ const b = x.getBoundingClientRect(); return Math.round(b.top + b.height / 2); }});
            out.push({{h: rb.height, input_h: eb.height, spread: Math.max(...cs) - Math.min(...cs), n: els.length, top: rb.top}}); }} return JSON.stringify(out); }})()"""))
        check("Total und Team Totals: jede weitere Linie ist genau EINE Zeile hoch (Zeilenhoehe = Feldhoehe, alle Felder auf gleicher Hoehe)", len(rows_m) == 18 and all(abs(r["h"] - r["input_h"]) < 6 and r["spread"] <= 3 and r["n"] == 7 for r in rows_m), str([(round(r["h"]), round(r["input_h"]), r["spread"], r["n"]) for r in rows_m[:3]]))
        rows_s = json.loads(await js(f"""(() => {{ const out = []; for (const el of {CARD}.querySelectorAll('input[aria-label="Linie Heim · Knicks"]')) {{
            const row = el.closest('[data-testid="stHorizontalBlock"]'); const rb = row.getBoundingClientRect(); const els = [...row.querySelectorAll('input, button')].filter(x => x.getBoundingClientRect().width > 0); const cs = els.map(x => {{ const b = x.getBoundingClientRect(); return Math.round(b.top + b.height / 2); }});
            out.push({{h: rb.height, spread: Math.max(...cs) - Math.min(...cs), n: els.length}}); }} return JSON.stringify(out); }})()"""))
        check("Spread: jede weitere Linie ist genau EINE Zeile hoch (8 Elemente in einer Reihe, Hoehe gleich der Feldhoehe)", len(rows_s) == 5 and all(r["h"] < 52 and r["spread"] <= 3 and r["n"] == 8 for r in rows_s[1:]), str(rows_s))
        hdrs = await js(f"[...{CARD}.querySelectorAll('.pm-flabel')].filter(x => x.style.textAlign === 'center' && x.innerText.trim() === 'Buchmacher').length")
        check("Beschriftungen als Kopfzeile: je Expander (Spread, Total, Gast, Heim) genau eine Kopfzeile", hdrs == 4, str(hdrs))
        geo = json.loads(await js(f"""(() => {{ const el = {CARD}.querySelector('input[aria-label="Weitere Linie"]'); const row = el.closest('[data-testid="stHorizontalBlock"]');
            const r = e => {{ const b = e.getBoundingClientRect(); return [b.left, b.right]; }}; const a = k => r(row.querySelector('input[aria-label="' + k + '"]'));
            const bs = [...row.querySelectorAll('button')].filter(x => x.getBoundingClientRect().width > 0).map(r); return JSON.stringify({{over: a('Quote Over (Zeile)'), line: a('Weitere Linie'), under: a('Quote Under (Zeile)'), book: a('Buchmacher (Zeile)'), bs, row: r(row)}}); }})()"""))
        check("Kompakte Total-Zeile: Over links, '-' | Linie | '+' in der Mitte, Under rechts davon, dann Buchmacher und Entfernen; Linie liegt in der Mitte zwischen '-' und '+'",
              geo["over"][1] <= geo["bs"][0][0] and geo["bs"][1][1] <= geo["under"][0] and geo["under"][1] <= geo["book"][0]
              and abs((geo["line"][0] + geo["line"][1]) / 2 - (geo["bs"][0][1] + geo["bs"][1][0]) / 2) < 3, str(geo)[:200])
        check("Zeile bleibt bei 1440 px in einer Reihe (Entfernen liegt innerhalb der Zeile)", geo["bs"][-1][1] <= geo["row"][1] + 1, str(geo["row"]))
        await typein(f"{CARD}.querySelectorAll('input[aria-label=\"Buchmacher\"]')[3]", "Betano")
        bk_vals = json.loads(await js(f"JSON.stringify([...{CARD}.querySelectorAll('input[aria-label=\"Buchmacher (Zeile)\"]')].map(i => i.value))"))
        check("Buchmacher: neue Zeilen des Gast-Team-Totals haben den Buchmacher der Hauptlinie uebernommen (6 Zeilen 'Betano')", bk_vals.count("Betano") >= 6, str(bk_vals))
        TEAM_OVER = lambda i: f"{CARD}.querySelectorAll('input[aria-label=\"Quote Over\"]')[{i}]"
        TEAM_UNDER = lambda i: f"{CARD}.querySelectorAll('input[aria-label=\"Quote Under\"]')[{i}]"
        team_main = json.loads(await js(f"JSON.stringify([...{CARD}.querySelectorAll('input[aria-label=\"Linie\"]')].map(i => i.value))"))
        check("Team Totals: Hauptlinien rechnerisch vorbefuellt (Total 232,0, Spread Heim -4,3: Gast 114,0 / Heim 118,0, gerundet)", team_main[1:] == ["114,0", "118,0"], str(team_main))
        await typein(TEAM_OVER(1), "1,91"); await typein(TEAM_UNDER(1), "1,89"); await typein(TEAM_OVER(2), "1,85"); await typein(TEAM_UNDER(2), "1,95")
        import base64
        for i, nm in ((1, "spread3"), (2, "total6"), (3, "team_totals12")):
            rect = json.loads(await js(f"""(() => {{ const e = {CARD}.querySelectorAll('[data-testid="stExpander"]')[{i}]; e.scrollIntoView({{block: 'center'}}); const b = e.getBoundingClientRect(); return JSON.stringify([b.left + scrollX, b.top + scrollY, b.width, b.height]); }})()"""))
            sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - 60), width=rect[2] + 40, height=rect[3] + 80, scale=1))
            (tmp / f"{nm}.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot", nm, tmp / f"{nm}.png", f"({rect[3]:.0f} px hoch)")
        # ---------------- Spielerpunkte: Kader-Knopf, Spielerauswahl (Suche ohne Akzent), kompakte Zeilen, Screenshot
        rbtn = json.loads(await js("""JSON.stringify((() => { const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === 'Kader aktualisieren'); const cs = getComputedStyle(b);
            return [cs.backgroundColor, cs.color]; })())"""))
        check("Knopf 'Kader aktualisieren' ist dezent (nicht orange)", rbtn[0] != "rgb(249, 115, 22)", str(rbtn))
        await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Spieler hinzufügen')).click()"); await asyncio.sleep(2.0)
        sel_in = f"{CARD}.querySelector('[data-testid=\"stSelectbox\"] input')"
        await js(f"{sel_in}.focus()"); await call("Input.insertText", text="Jokic"); await asyncio.sleep(2.5)
        opts = json.loads(await js("JSON.stringify([...document.querySelectorAll('[role=\"option\"], li[role=\"option\"]')].map(o => o.innerText.trim()))"))
        check("Suche 'Jokic' im Browser findet 'Nikola Jokić' (Akzente egal) und nur diesen", len(opts) == 1 and opts[0].startswith("Nikola Jokić · C · #15 · PHI"), str(opts))
        await call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13); await call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
        await asyncio.sleep(2.0)
        shown = await js(f"{CARD}.querySelector('[data-testid=\"stSelectbox\"]').innerText")
        check("Auswahl uebernommen: 'Nikola Jokić · C · #15 · PHI' steht im Feld, kein voller Skriptlauf", "Nikola Jokić" in (shown or "") and counts()["script"] == tc1["script"], str(shown)[:80] + f" script {counts()['script']}")
        PP_LINE = lambda i: f"{CARD}.querySelectorAll('input[aria-label=\"Schwelle (Punkte)\"]')[{i}]"
        await typein(PP_LINE(0), "19"); await typein(f"{CARD}.querySelectorAll('input[aria-label=\"Quote (mindestens)\"]')[0]", "2,5")
        for _ in range(4):
            await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Meilenstein hinzufügen')).click()"); await asyncio.sleep(2.5)
        pp_vals = json.loads(await js(f"JSON.stringify([...{CARD}.querySelectorAll('input[aria-label=\"Schwelle (Punkte)\"]')].map(i => i.value))"))
        check("Meilensteine: automatisch 19, 20, 21, 22, 23 (letzte + 1), kein voller Skriptlauf", pp_vals == ["19", "20", "21", "22", "23"] and counts()["script"] == tc1["script"], str(pp_vals))
        rows_p = json.loads(await js(f"""(() => {{ const out = []; for (const el of {CARD}.querySelectorAll('input[aria-label="Schwelle (Punkte)"]')) {{
            const row = el.closest('[data-testid="stHorizontalBlock"]'); const rb = row.getBoundingClientRect(); const els = [...row.querySelectorAll('input, button')].filter(x => x.getBoundingClientRect().width > 0);
            const cs = els.map(x => {{ const b = x.getBoundingClientRect(); return Math.round(b.top + b.height / 2); }}); out.push({{h: rb.height, spread: Math.max(...cs) - Math.min(...cs), n: els.length}}); }} return JSON.stringify(out); }})()"""))
        check("Meilenstein-Zeile ist genau EINE Zeile hoch (6 Elemente: -, Schwelle, +, Quote, Buchmacher, Entfernen)", len(rows_p) == 5 and all(r["h"] < 52 and r["spread"] <= 3 and r["n"] == 6 for r in rows_p), str(rows_p[:2]))
        await js(f"{CARD}.querySelector('[data-testid=\"stBorderedContainer\"], [data-testid=\"stVerticalBlockBorderWrapper\"]') && 0")
        import base64
        async def shoot(nm, sel_js):
            rect = json.loads(await js(f"""(() => {{ const e = {sel_js}; e.scrollIntoView({{block: 'center'}}); const b = e.getBoundingClientRect(); return JSON.stringify([b.left + scrollX, b.top + scrollY, b.width, b.height]); }})()"""))
            sh = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=dict(x=max(0, rect[0] - 20), y=max(0, rect[1] - 40), width=rect[2] + 40, height=rect[3] + 70, scale=1))
            (tmp / f"{nm}.png").write_bytes(base64.b64decode(sh["result"]["data"])); print("Screenshot", nm, tmp / f"{nm}.png", f"({rect[3]:.0f} px hoch)")
        PPBOX = f"""(() => {{ let e = {CARD}.querySelector('[data-testid="stSelectbox"]'); while (e && !(e.getAttribute('data-testid') === 'stVerticalBlockBorderWrapper' && [...e.querySelectorAll('button')].some(b => /hinzufügen/.test(b.innerText)))) e = e.parentElement; return e; }})()" """.strip().rstrip('"')
        await shoot("spielerpunkte_meilensteine", PPBOX)
        await js(f"[...{CARD}.querySelectorAll('[data-testid=\"stRadio\"] label')].find(l => l.innerText.trim() === 'Einzellinie').click()"); await asyncio.sleep(2.0)
        notice = await js(f"{CARD}.innerText.includes('Modus gewechselt')")
        await typein(f"{PPBOX}.querySelector('input[aria-label=\"Weitere Linie\"]')", "24,5")
        for _ in range(2):
            await js(f"[...{PPBOX}.querySelectorAll('button')].find(b => /^\\+ Linie hinzufügen/.test(b.innerText.trim())).click()"); await asyncio.sleep(2.5)
        pl_vals = json.loads(await js(f"JSON.stringify([...{PPBOX}.querySelectorAll('input[aria-label=\"Weitere Linie\"]')].map(i => i.value))"))
        check("Einzellinie: Hinweis 'Modus gewechselt' sichtbar, Linien 24,5 / 25,5 / 26,5 (letzte + 1,0)", notice and pl_vals == ["24,5", "25,5", "26,5"], str(pl_vals) + str(notice))
        await shoot("spielerpunkte_einzellinie", PPBOX)
        await js(f"[...{CARD}.querySelectorAll('[data-testid=\"stRadio\"] label')].find(l => l.innerText.trim() === 'Meilensteine').click()"); await asyncio.sleep(2.0)
        await typein(PP_LINE(0), "19"); await typein(f"{CARD}.querySelectorAll('input[aria-label=\"Quote (mindestens)\"]')[0]", "2,5")
        # Total-Under-Quote eintragen (sonst blockiert der unvollstaendige Markt das Speichern, mit Warnung)
        tot_under = f"{CARD}.querySelector('input[aria-label=\"Quote Under\"]')"
        await typein(tot_under, "1,87")
        # Speichern ohne Eingabe (Spurs-Karte, nur vorbefuellte Linie): Warnung im Fragment, kein voller Lauf
        CARD2 = "document.querySelector('[class*=\"st-key-pm_card_\"]:has(input[aria-label=\"Linie Heim · Spurs\"])')"
        await js(f"[...{CARD2}.querySelectorAll('button')].find(b => b.innerText.trim() === 'Speichern').click()"); await asyncio.sleep(2.0)
        c5 = counts(); txt2 = await js(f"{CARD2}.innerText")
        check("Speichern ohne Eingabe (Spurs): Warnung 'Nichts eingetragen.' im Fragment, KEIN voller Skriptlauf", "Nichts eingetragen." in (txt2 or "") and c5["script"] == c0["script"], f"script {c5['script']}")
        # Speichern mit geaenderter Linie (Knicks): schreibt, laedt die ganze App neu (Chip, Werte, Rueckmeldung)
        await js(f"{BTN('Speichern')}.click()"); await asyncio.sleep(4.5)
        c6 = counts(); txt = await js(f"{CARD}.innerText"); head = await js(f"{CARD}.innerText.slice(0, 80)")
        saved = json.loads((tmp / "tracking" / "pre_match_entries.json").read_text())
        ln = [v for v in saved["entries"].values() if v["home"] == "New York Knicks"][0]["markets"]["spread"]["lines"]
        check("Speichern: geaenderte Linie steht in der Datei (Hauptlinie -3,5, weitere Linie, Revisionen)", ln[0]["line_home"] == -3.5 and len(ln[0]["revisions"]) == 2, str([l["line_home"] for l in ln]))
        tt = [v for v in saved["entries"].values() if v["home"] == "New York Knicks"][0]["markets"].get("total", {}).get("lines", [])
        check("Speichern: Total steht in der Datei (Hauptlinie 232,5, nur Zeilen mit Quoten; leere neue Zeilen werden uebersprungen)", len(tt) == 1 and tt[0]["line"] == 232.5 and tt[0]["over_odds"] == 1.95, str([(l["id"], l["line"]) for l in tt]))
        tmk = [v for v in saved["entries"].values() if v["home"] == "New York Knicks"][0]["markets"].get("team_totals", {})
        check("Speichern: Team Totals je Team in der Datei (Gast 114,0 / Heim 118,0, derived), leere neue Zeilen werden uebersprungen",
              len(tmk.get("away", {}).get("lines", [])) == 1 and len(tmk.get("home", {}).get("lines", [])) == 1 and tmk["away"]["lines"][0]["line"] == 114.0 and tmk["home"]["lines"][0]["line"] == 118.0
              and tmk["away"]["lines"][0]["market_suggestion"]["source"] == "derived", str(tmk)[:160])
        ppk = [v for v in saved["entries"].values() if v["home"] == "New York Knicks"][0]["markets"].get("player_points", {}).get("players", [])
        check("Speichern: Spielerpunkte in der Datei (Nikola Jokić, person_id, Team 76ers, Modus Meilensteine, Schwelle 19, Quote 2,5, roster_fetched_at)",
              len(ppk) == 1 and ppk[0]["name"] == "Nikola Jokić" and ppk[0]["team"] == "Philadelphia 76ers" and ppk[0]["mode"] == "milestones" and ppk[0]["lines"][0]["threshold"] == 19 and ppk[0]["lines"][0]["odds"] == 2.5
              and ppk[0]["roster_fetched_at"] and ppk[0]["person_id"], str(ppk)[:200])
        alerts = await js(f"JSON.stringify([...{CARD}.querySelectorAll('[data-testid=\"stAlert\"]')].map(a => a.innerText.trim()))")
        check("Speichern: VOLLER Skriptlauf (Zaehler +1), 'Gespeichert.' sichtbar", c6["script"] == c0["script"] + 1 and "Gespeichert." in (txt or ""), f"script {c0['script']} -> {c6['script']} {alerts}")
        await js(f"{BTN('Speichern')}.click()"); await asyncio.sleep(4.5)
        c7 = counts(); txt = await js(f"{CARD}.innerText")
        check("Speichern ohne Aenderung: ebenfalls voller Lauf (+1) und 'Unveraendert.'", c7["script"] == c6["script"] + 1 and "Unverändert." in (txt or ""), f"script {c6['script']} -> {c7['script']}")
        # ---------------- Expander-Zustand bleibt bei vollem Rerun (Speichern) und Entfernen erhalten
        st_full = await states()
        check("Expander bleiben OFFEN nach dem vollen Rerun beim Speichern (2x gespeichert), Titel unveraendert", [t for t, o in st_full] == TITLES and all(o for t, o in st_full), str(st_full))
        def entry_k():
            d = json.loads((tmp / "tracking" / "pre_match_entries.json").read_text())
            return [v for v in d["entries"].values() if v["home"] == "New York Knicks"][0]
        await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Weitere Linie hinzufügen')).click()"); await asyncio.sleep(2.0)
        await typein(f"{CARD}.querySelectorAll('input[aria-label=\"Quote Gast · 76ers\"]')[2]", "1,90"); await typein(f"{CARD}.querySelectorAll('input[aria-label=\"Quote Heim · Knicks\"]')[2]", "1,92")
        cs0 = counts()["script"]
        await js(f"{BTN('Speichern')}.click()"); await asyncio.sleep(3.5)
        st_a = await states(); sp_lines = [l for l in entry_k()["markets"]["spread"]["lines"] if l["active"]]
        check("Zusaetzliche Spread-Linie gespeichert (voller Rerun), alle Expander bleiben offen", counts()["script"] == cs0 + 1 and len(sp_lines) == 2 and all(o for t, o in st_a), f"script {cs0} -> {counts()['script']}, Linien {len(sp_lines)}, {st_a}")
        await js(f"""(() => {{ const el = [...{CARD}.querySelectorAll('input[aria-label="Linie Heim · Knicks"]')][1]; const row = el.closest('[data-testid="stHorizontalBlock"]');
            [...row.querySelectorAll('button')].find(b => b.innerText.trim() === 'Entfernen').click(); }})()"""); await asyncio.sleep(3.5)
        st_b = await states(); sp_all = entry_k()["markets"]["spread"]["lines"]
        check("Entfernen einer gespeicherten Linie (voller Rerun): Linie inaktiv mit Revision, ALLE Expander bleiben offen, Titel unveraendert", counts()["script"] == cs0 + 2 and sum(1 for l in sp_all if l["active"]) == 1 and sp_all[-1]["revisions"][-1]["action"] == "removed" and [t for t, o in st_b] == TITLES and all(o for t, o in st_b), f"script {counts()['script']}, {st_b}")
        # Eingabe in einem Markt, der danach zugeklappt wird: wird mitgespeichert
        await typein(f"{CARD}.querySelectorAll('input[aria-label=\"Quote Heim · Knicks\"]')[0]", "1,60")
        await toggle("SIEGER INKL. OT")
        check("SIEGER zugeklappt, andere bleiben offen", [(t, o) for t, o in await states()] == [(TITLES[0], False)] + [(t, True) for t in TITLES[1:]])
        cs1 = counts()["script"]
        await js(f"{BTN('Speichern')}.click()"); await asyncio.sleep(3.5)
        st_c = await states()
        check("Eingabe in zugeklapptem Markt wird mitgespeichert (Sieger Heim-Quote 1,60 in der Datei)", entry_k()["markets"]["winner_incl_ot"]["home_odds"] == 1.6 and counts()["script"] == cs1 + 1, str(entry_k()["markets"]["winner_incl_ot"]["home_odds"]))
        check("nach dem vollen Rerun bleibt der zugeklappte Markt zu und die offenen bleiben offen (Zustand wird nicht zurueckgesetzt)", st_c == [[TITLES[0], False]] + [[t, True] for t in TITLES[1:]], str(st_c))
        await toggle("SIEGER INKL. OT")
        await shoot_el("karte_spielerpunkte_offen", f"[...{CARD}.querySelectorAll('[data-testid=\"stExpander\"]')][4]", pad=60)
        # ---------------- 20 Spielerbloecke (Limit): Laden, Layout (keine Ueberbreite, jede Meilenstein-Zeile eine Zeile), Laufzeit, Knopf deaktiviert
        rost = ro.load()["teams"]; have = {b["person_id"] for b in ps.active_player_blocks(entry_k())}
        extra = [dict(q, team=t) for t in ("New York Knicks", "Philadelphia 76ers") for q in rost[t] if q["person_id"] not in have][:20 - len(have)]
        ps.save_card(day, iso(T0 + 3 * 3600), "New York Knicks", "Philadelphia 76ers", player_blocks=[
            {"block_id": None, "person_id": q["person_id"], "name": q["name"], "team": q["team"], "team_abbreviation": q["team_abbreviation"], "mode": "milestones",
             "rows": [{"id": None, "value": str(10 + j), "odds": "2,00", "bookmaker": "Betano"} for j in range(3)]} for q in extra], now=T0 + 5)
        t_load = time.time(); await call("Page.navigate", url="http://localhost:8768/"); await asyncio.sleep(9)
        await toggle("SPIELERPUNKTE"); await asyncio.sleep(3)
        n_blocks = await js(f"{CARD}.querySelectorAll('button').length && [...{CARD}.querySelectorAll('button')].filter(b => b.innerText.includes('Spieler entfernen')).length")
        over = await js("document.documentElement.scrollWidth - window.innerWidth")
        rows20 = json.loads(await js(f"""(() => {{ const out = []; for (const el of {CARD}.querySelectorAll('input[aria-label="Schwelle (Punkte)"]')) {{
            const row = el.closest('[data-testid="stHorizontalBlock"]'); const rb = row.getBoundingClientRect(); const els = [...row.querySelectorAll('input, button')].filter(x => x.getBoundingClientRect().width > 0);
            const cs = els.map(x => {{ const b = x.getBoundingClientRect(); return Math.round(b.top + b.height / 2); }}); out.push({{h: rb.height, spread: Math.max(...cs) - Math.min(...cs), n: els.length}}); }} return JSON.stringify(out); }})()"""))
        add_dis = await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.includes('Spieler hinzufügen')).disabled")
        cap_txt = await js(f"{CARD}.innerText")
        check("20 Spielerbloecke: alle 20 sichtbar, keine Ueberbreite der Seite, jede der 58 Meilenstein-Zeilen (19 Bloecke mit 3 Linien + Jokic mit 1) genau EINE Zeile (6 Elemente)", n_blocks == 20 and over <= 0 and len(rows20) == 19 * 3 + 1 and all(r["h"] < 52 and r["spread"] <= 3 and r["n"] == 6 for r in rows20), f"{n_blocks} Bloecke, Ueberbreite {over}, {len(rows20)} Zeilen")
        check("20 Spielerbloecke: '+ Spieler hinzufuegen' deaktiviert, Hinweis 'maximal 20 Spieler je Spiel'", add_dis is True and "maximal 20 Spieler je Spiel" in (cap_txt or ""), str(add_dis))
        c20a = counts()["script"]; t_click = time.time()
        await js(f"[...{CARD}.querySelectorAll('button')].find(b => b.innerText.trim() === 'Speichern').click()"); await asyncio.sleep(0.5)
        for _ in range(60):
            if counts()["script"] > c20a and "Unverändert" in ((await js(f"{CARD}.innerText")) or ""): break
            await asyncio.sleep(0.5)
        dt_click = time.time() - t_click
        check("20 Spielerbloecke: Speichern (voller Rerun) ist in unter 15 s fertig, 'Unveraendert.' sichtbar, kein Fehler", dt_click < 15 and "Traceback" not in (await js("document.body.innerText")), f"{dt_click:.1f} s")
        print(f"Laufzeit: Laden mit 20 Spielern ca. 9 s Wartezeit, Speichern-Rerun {dt_click:.1f} s")
        await shoot_el("karte_20_spieler", f"[...{CARD}.querySelectorAll('[data-testid=\"stExpander\"]')][4]", pad=40)
        body = await js("document.body.innerText")
        check("im gesamten Browser-Text: keine Streamlit-Warnung 'was created with a default value ...' und keine Exception", "default value" not in body and "Traceback" not in body and "StreamlitAPIException" not in body)
        shot = await call("Page.captureScreenshot", format="png")
        import base64; (tmp / "final.png").write_bytes(base64.b64decode(shot["result"]["data"])); print("Screenshot:", tmp / "final.png")
        return True
    asyncio.run(main())
    # Speichern mit Daten -> voller Rerun: zweite Runde mit gueltigen Werten
    check("echte data/rosters.json unveraendert (Browsertest nutzt gefaelschten Kader im Temp-Ordner)", (real_roster.read_bytes() if real_roster.exists() else None) == real_roster_bytes)
    check("echte data/tracking/pre_match_entries.json unveraendert", (real.read_bytes() if real.exists() else None) == real_bytes)
finally:
    chrome.terminate(); server.terminate()
    import shutil, time as _t; _t.sleep(1.0); shutil.rmtree(tmp / "profile", ignore_errors=True)       # Chrome-Profil (ca. 200 MB) nicht liegen lassen; Screenshots und Zaehler bleiben
print("\nErgebnis:", "ALLE BROWSER-PRUEFUNGEN BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)
