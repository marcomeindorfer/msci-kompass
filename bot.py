"""MSCI-Kompass: taeglicher Kauf-Signal-Bot fuer einen MSCI-World-ETF.

Laeuft in GitHub Actions. Holt Kurse, berechnet Dip-Signale, macht einen
Backtest (sofort kaufen vs. Teil fuer Dips aufheben vs. nur Dip-Kaeufe),
schreibt docs/index.html und schickt bei neuen Signalen eine ntfy-Push.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- Einstellungen
TICKERS = [("EUNL.DE", "iShares Core MSCI World UCITS ETF USD (Acc) · ISIN IE00B4L5Y983 · Xetra, EUR"),
           ("EUNL.F", "iShares Core MSCI World UCITS ETF USD (Acc) · ISIN IE00B4L5Y983 · Frankfurt, EUR")]
SPAR = 100.0        # Backtest: monatlich sofort angelegter Betrag in EUR
RUECKLAGE = 25.0    # Backtest: monatlich fuer Dips aufgehobener Betrag in EUR
# Stufen: (Mindest-Abstand zum Allzeithoch, Stufe, Anteil der Ruecklage)
STUFEN = [(0.05, 1, 0.25), (0.10, 2, 0.50), (0.20, 3, 1.00)]
RESET = 0.01        # innerhalb 1 % am Hoch -> Dip-Phase vorbei, Stufen zuruecksetzen
SEITE = "https://marcomeindorfer.github.io/msci-kompass/"

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "data", "kurse.csv")
STATE = os.path.join(ROOT, "state.json")
OUT = os.path.join(ROOT, "docs", "index.html")
TEMPLATE = os.path.join(ROOT, "template.html")
ANTEIL = {st: a for _, st, a in STUFEN}


# ---------------------------------------------------------------- Kurse
def lade_kurse():
    import yfinance as yf
    fehler = None
    for ticker, name in TICKERS:
        for _ in range(3):
            try:
                df = yf.download(ticker, period="max", interval="1d",
                                 auto_adjust=True, progress=False)
                if df is not None and len(df) > 1000:
                    s = df["Close"]
                    if isinstance(s, pd.DataFrame):
                        s = s.iloc[:, 0]
                    s = s.dropna().astype(float)
                    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                    s = s[~s.index.duplicated(keep="last")].sort_index()
                    s.name = ticker
                    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                    s.to_frame().to_csv(CACHE)
                    return ticker, name, s, None
            except Exception as e:  # noqa: BLE001
                fehler = e
            time.sleep(5)
    if os.path.exists(CACHE):
        df = pd.read_csv(CACHE, index_col=0, parse_dates=True)
        s = df.iloc[:, 0].dropna().astype(float)
        name = dict(TICKERS).get(df.columns[0], df.columns[0])
        return df.columns[0], name, s, (
            f"Kursabruf fehlgeschlagen ({fehler}). Angezeigt werden die zuletzt gespeicherten Kurse.")
    sys.exit(f"Keine Kursdaten verfuegbar: {fehler}")


# ---------------------------------------------------------------- Indikatoren
def stufe_von(dd):
    st = 0
    for schwelle, stufe, _ in STUFEN:
        if dd <= -schwelle:
            st = stufe
    return st


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


# Kaufempfehlung 1-10: Punkte fuer Abstand zum Hoch (Hauptfaktor), RSI (Panik-Verkaeufe)
# und Abstand unter der 200-Tage-Linie. Stuetzpunkte werden linear interpoliert.
SCORE_DD = ([0, 2, 5, 10, 15, 20, 30], [0, 1, 3, 4.5, 5.5, 6.5, 7.5])        # % unter Hoch
SCORE_RSI = ([20, 30, 40, 60, 70, 80], [1.5, 1, 0.3, 0, -0.5, -1])         # RSI 14
SCORE_SMA = ([-15, -10, -5, 0], [1, 0.8, 0.4, 0])                          # % zur 200-Tage-Linie
PUSH_AB, PUSH_STARK, PUSH_RESET = 7, 9, 4   # Push ab 7 und nochmal ab 9; zurueckgesetzt bei <= 4


def score_teile(dd, r, sma_abst):
    """Liefert die drei Punkte-Anteile als Serien (alle Eingaben als pandas Series)."""
    p_dd = pd.Series(np.interp((-dd * 100).to_numpy(), *SCORE_DD), index=dd.index)
    p_rsi = pd.Series(np.interp(r.fillna(50).to_numpy(), *SCORE_RSI), index=dd.index)
    p_sma = pd.Series(np.interp((sma_abst * 100).fillna(0).to_numpy(), *SCORE_SMA), index=dd.index)
    return p_dd, p_rsi, p_sma


def signale(dd):
    """Liste neuer Stufen je Dip-Phase + aktueller Phasenstatus."""
    events, level, phase_start = [], 0, None
    for d, x in dd.items():
        if x >= -RESET:
            level, phase_start = 0, None
            continue
        st = stufe_von(x)
        if st > level:
            if level == 0:
                phase_start = d
            events.append({"d": d, "stufe": st, "dd": float(x)})
            level = st
    return events, level, phase_start


# ---------------------------------------------------------------- Backtest
def backtest(s, events, start=None, samples=False):
    if start is not None:
        s = s[s.index >= start]
    if len(s) < 2:
        return None
    monatsanfang = set(s.index[~s.index.to_period("M").duplicated()])
    ev = {e["d"]: e["stufe"] for e in events}
    pf = {k: {"sh": 0.0, "cash": 0.0} for k in "ABC"}
    eingezahlt, verlauf = 0.0, []
    for d, p in s.items():
        if d in monatsanfang:
            rate = SPAR + RUECKLAGE
            eingezahlt += rate
            pf["A"]["sh"] += rate / p
            pf["B"]["sh"] += SPAR / p
            pf["B"]["cash"] += RUECKLAGE
            pf["C"]["cash"] += rate
        if d in ev:
            for k in "BC":
                betrag = pf[k]["cash"] * ANTEIL[ev[d]]
                pf[k]["sh"] += betrag / p
                pf[k]["cash"] -= betrag
        if samples:
            verlauf.append((d, eingezahlt, *(pf[k]["sh"] * p + pf[k]["cash"] for k in "ABC")))
    p = float(s.iloc[-1])
    ende = {k: {"wert": pf[k]["sh"] * p + pf[k]["cash"], "cash": pf[k]["cash"]} for k in "ABC"}
    return {"eingezahlt": eingezahlt, "ende": ende, "verlauf": verlauf}


# ---------------------------------------------------------------- Push
def push(titel, text, prio=4, tags=("chart_with_downwards_trend",)):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("Kein NTFY_TOPIC gesetzt - Push uebersprungen:", titel)
        return False
    body = json.dumps({"topic": topic, "title": titel, "message": text,
                       "priority": prio, "tags": list(tags), "click": SEITE}).encode()
    req = urllib.request.Request("https://ntfy.sh/", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        print("Push gesendet:", r.status, titel)
    return True


def eur(x, nk=2):
    return f"{x:,.{nk}f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, nk=1):
    return f"{x * 100:+.{nk}f} %".replace(".", ",")


# ---------------------------------------------------------------- Hauptteil
def main():
    ticker, name, s, warnung = lade_kurse()
    ath = s.cummax()
    dd = s / ath - 1
    sma = s.rolling(200).mean()
    r = rsi(s)
    events, level, phase_start = signale(dd)

    heute = s.index[-1]
    kurs, hoch = float(s.iloc[-1]), float(ath.iloc[-1])
    akt = {
        "datum": heute.strftime("%Y-%m-%d"), "kurs": kurs, "hoch": hoch,
        "hochDatum": s[s == hoch].index[-1].strftime("%Y-%m-%d"),
        "dd": float(dd.iloc[-1]), "sma": float(sma.iloc[-1]), "rsi": float(r.iloc[-1]),
        "stufe": level, "phaseStart": phase_start.strftime("%Y-%m-%d") if phase_start is not None else None,
        "neuHeute": bool(events and events[-1]["d"] == heute),
        "naechste": None,
    }
    # Kaufempfehlung 1-10
    p_dd, p_rsi, p_sma = score_teile(dd, r, s / sma - 1)
    score = (1 + p_dd + p_rsi + p_sma).round().clip(1, 10).astype(int)
    akt.update({"score": int(score.iloc[-1]),
                "teile": {"dd": float(p_dd.iloc[-1]), "rsi": float(p_rsi.iloc[-1]), "sma": float(p_sma.iloc[-1])}})
    # Wie gut war jede Empfehlung historisch? Rendite 12 Monate (252 Handelstage) spaeter
    fwd = (s.shift(-252) / s - 1).dropna()
    gruppen = []
    for lo, hi in [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]:
        f = fwd[(score.loc[fwd.index] >= lo) & (score.loc[fwd.index] <= hi)]
        gruppen.append({"von": lo, "bis": hi, "tage": int(len(f)),
                        "avg": float(f.mean()) if len(f) else None,
                        "plus": float((f > 0).mean()) if len(f) else None})
    akt["alle"] = {"tage": int(len(fwd)), "avg": float(fwd.mean()), "plus": float((fwd > 0).mean())}
    akt["gruppen"] = gruppen
    akt["tageHoch"] = float((score >= PUSH_AB).mean())  # Anteil der Tage mit Empfehlung >= 7

    for schwelle, st, anteil in STUFEN:
        if st > level:
            akt["naechste"] = {"stufe": st, "schwelle": schwelle, "anteil": anteil,
                               "kurs": hoch * (1 - schwelle)}
            break

    # Signal-Historie mit Rendite 12 Monate danach
    hist = []
    for e in events:
        p0 = float(s[e["d"]])
        later = s[s.index >= e["d"] + pd.DateOffset(years=1)]
        hist.append({"d": e["d"].strftime("%Y-%m-%d"), "stufe": e["stufe"], "dd": e["dd"],
                     "kurs": p0, "r12": float(later.iloc[0] / p0 - 1) if len(later) else None})

    # Backtest gesamt + je Startjahr
    voll = backtest(s, events, samples=True)
    ver = voll["verlauf"][::5] + [voll["verlauf"][-1]]
    bt_series = {"t": [v[0].strftime("%Y-%m-%d") for v in ver],
                 "ein": [round(v[1], 2) for v in ver],
                 "A": [round(v[2], 2) for v in ver], "B": [round(v[3], 2) for v in ver],
                 "C": [round(v[4], 2) for v in ver]}
    jahre = []
    erstes = s.index[0].year + 1
    for y in range(erstes, heute.year - 2):
        b = backtest(s, events, start=pd.Timestamp(y, 1, 1))
        if b:
            jahre.append({"jahr": y, "ein": b["eingezahlt"],
                          **{k: b["ende"][k]["wert"] for k in "ABC"}})

    # Kursdaten fuer Charts (taeglich, gerundet)
    kurse = {"t": [d.strftime("%Y-%m-%d") for d in s.index],
             "p": [round(float(v), 2) for v in s],
             "sma": [None if pd.isna(v) else round(float(v), 2) for v in sma],
             "dd": [round(float(v) * 100, 2) for v in dd],
             "score": [int(v) for v in score]}

    daten = {
        "ticker": ticker, "name": name, "warnung": warnung,
        "erstellt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "regeln": {"spar": SPAR, "ruecklage": RUECKLAGE, "reset": RESET,
                   "stufen": [{"schwelle": a, "stufe": b, "anteil": c} for a, b, c in STUFEN]},
        "akt": akt, "signale": hist, "kurse": kurse,
        "bt": {"start": s.index[0].strftime("%Y-%m-%d"), "ein": voll["eingezahlt"],
               "ende": voll["ende"], "verlauf": bt_series, "jahre": jahre},
    }

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("/*__DATEN__*/null", json.dumps(daten, separators=(",", ":"), allow_nan=False))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    sc = akt["score"]
    print(f"{ticker} {akt['datum']}: Kurs {kurs:.2f}, Abstand {akt['dd']*100:.1f} %, "
          f"RSI {akt['rsi']:.0f}, Empfehlung {sc}/10")

    # ---------------------------------------------------- Benachrichtigung
    state = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
    gemeldet = int(state.get("gemeldet", 0))
    if sc <= PUSH_RESET:
        gemeldet = 0
    if os.environ.get("TEST_PUSH") == "true":
        push("MSCI-Kompass: Test", f"Push funktioniert. Aktuelle Kaufempfehlung: {sc}/10 "
             f"(Kurs {eur(kurs)}, {pct(akt['dd'])} zum Hoch).", prio=3, tags=("white_check_mark",))
    stufe_jetzt = PUSH_STARK if sc >= PUSH_STARK else PUSH_AB if sc >= PUSH_AB else 0
    if stufe_jetzt > gemeldet:
        if stufe_jetzt == PUSH_STARK:
            titel, kern, prio = f"MSCI World: Seltene Kaufgelegenheit ({sc}/10)", "Ein großer Kauf lohnt sich, solange du das Geld langfristig nicht brauchst.", 5
        else:
            titel, kern, prio = f"MSCI World: Kaufempfehlung {sc}/10", "Jetzt ist ein guter Zeitpunkt für einen größeren Kauf.", 4
        text = f"{kern} Der ETF kostet {eur(kurs)} und liegt {pct(akt['dd'])} unter seinem Hoch."
        if akt["rsi"] < 30:
            text += " Gerade wird viel verkauft (Panik), historisch oft ein guter Einstieg."
        if kurs < akt["sma"]:
            text += " Achtung: Abwärtstrend, es kann noch weiter fallen. Am besten in 2 Teilen kaufen."
        push(titel, text, prio=prio)
        gemeldet = stufe_jetzt
    state = {"gemeldet": gemeldet, "score": sc, "datum": akt["datum"]}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


if __name__ == "__main__":
    main()
