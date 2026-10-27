"""
History-Tab: beendete Spiele mit der Vorab-Prognose (Stand vor Anpfiff, data/tracking/projection_snapshots.json) und dem tatsaechlichen Ergebnis.
Rechnung und Regeln in data/history_view.py (Push bei Ergebnis genau auf der Linie ist ein eigenes Ergebnis, weder Sieg noch Niederlage). Nur lesen, kein Netz.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data import history_view as hv

ICON = {"treffer": "✅", "fehlschlag": "❌", "push": "➖", "kein_tipp": "·", None: "—"}


def _num(x, nd=1, sign=False) -> str:
    if x is None:
        return "—"
    s = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
    return s.replace(".", ",")


def _line(x) -> str:
    return "—" if x is None else (f"{x:.1f}".replace(".", ","))


def _tip(outcome, tip, result) -> str:
    """'✅ Über (Ist: Über)' bzw. '➖ Push' bei Ergebnis genau auf der Linie."""
    if outcome is None:
        return "— (keine Linie)"
    if outcome == "push":
        return f"➖ Push (Tipp {tip})"
    if outcome == "kein_tipp":
        return "· kein Tipp"
    return f"{ICON[outcome]} {tip} (Ist: {result})"


def table_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "Datum": r["day"], "Spiel": f"{r['away']} @ {r['home']}",
            "Prognose (Gast:Heim)": f"{_num(r['pred_away'], 0)}:{_num(r['pred_home'], 0)}",
            "Ergebnis (Gast:Heim)": f"{r['act_away']}:{r['act_home']}",
            "Total Prognose / Ist": f"{_num(r['pred_total'], 0)} / {r['act_total']}",
            "Spread Prognose / Ist": f"{_num(r['pred_spread'], 1, True)} / {r['act_spread']:+d}",
            "Abweichung Gast/Heim": f"{_num(r['dev_away'], 0, True)} / {_num(r['dev_home'], 0, True)}",
            "Abw. Total": _num(r["dev_total"], 1, True), "Abw. Spread": _num(r["dev_spread"], 1, True),
            "Total-Linie": _line(r["total_line"]), "Total": _tip(r["total_outcome"], r["total_tip"], r["total_result"]),
            "Spread-Linie": _line(r["spread_line"]), "Spread (wer deckt)": _tip(r["spread_outcome"], r["spread_tip"], r["spread_result"]),
            "Sieger": f"{ICON[r['winner']]} {hv.OUTCOME_LABEL[r['winner']]}",
        })
    return out


def summary_text(s: dict) -> str:
    def part(name, c):
        txt = f"{c['treffer']} Treffer · {c['fehlschlag']} Fehlschlag · {c['push']} Push"
        if c["kein_tipp"]:
            txt += f" · {c['kein_tipp']} ohne Tipp"
        if c["ohne_linie"]:
            txt += f" · {c['ohne_linie']} ohne Linie"
        return f"**{name}:** {txt}"
    return "  \n".join([part("Sieger", s["winner"]), part("Total (Markt-Linie)", s["total"]), part("Spread (Markt-Linie)", s["spread"])])


def render_history_tab() -> None:
    st.markdown("## 📅 History")
    st.caption("Beendete Spiele mit der Vorab-Prognose (letzter Stand vor dem Anpfiff) und dem tatsächlichen Ergebnis. Abweichung = Ist − Prognose. "
               "Liegt das Ergebnis genau auf einer ganzzahligen Linie, steht dort „Push“ (weder Treffer noch Fehlschlag).")
    rows = hv.finished_games()
    if not rows:
        st.info("Noch keine beendeten Spiele mit Vorab-Prognose.")
        return
    days = sorted({r["day"] for r in rows}, reverse=True)
    choice = st.selectbox("Spieltag", ["Alle"] + days, key="hist_day")
    shown = rows if choice == "Alle" else [r for r in rows if r["day"] == choice]
    s = hv.summarize(shown)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spiele", s["games"])
    c2.metric("Ø Fehler Total", _num(s["mae_total"]) + " P")
    c3.metric("Ø Fehler Spread", _num(s["mae_spread"]) + " P")
    c4.metric("Ø Fehler je Team", _num(s["mae_team"]) + " P")
    st.markdown(summary_text(s))
    st.dataframe(pd.DataFrame(table_rows(shown)), hide_index=True, use_container_width=True)
    n_rec = sum(1 for r in shown if r["result_source"] == "recorder")
    if n_rec:
        st.caption(f"{n_rec} Ergebnis(se) stammen aus den Recorder-Dateien, weil sie im Snapshot noch nicht eingetragen sind.")
