# 🧭 MSCI-Kompass

Kaufempfehlung von 1 bis 10 für den iShares Core MSCI World UCITS ETF USD (Acc) (ISIN IE00B4L5Y983, Xetra EUNL), mit Push-Nachricht bei guten Kaufgelegenheiten.

**Seite/App:** https://marcomeindorfer.github.io/msci-kompass/

## So funktioniert's

- Eine GitHub Action (`.github/workflows/kompass.yml`) läuft werktags stündlich von 07:15 bis 17:15 UTC (Xetra-Handelszeit, Kurse ca. 15 Min. verzögert).
- `bot.py` lädt die Kurse von Yahoo Finance (Fallback: EUNL.F, dann `data/kurse.csv`).
- Daraus berechnet es die Empfehlung: 1 Punkt + Abstand zum Allzeithoch (bis 7,5) + RSI (+1,5 bis −1) + Abstand unter der 200-Tage-Linie (bis 1).
- Ab Empfehlung 7 kommt eine Push-Nachricht über [ntfy](https://ntfy.sh), ab 9 noch eine. Wieder scharf geschaltet wird die Benachrichtigung, sobald die Empfehlung auf 4 oder darunter fällt. Das Thema steht im Repo-Secret `NTFY_TOPIC`.
- Die Seite `docs/index.html` wird aus `template.html` erzeugt (PWA mit Manifest und Service Worker).
- Der Backtest vergleicht drei Varianten: sofort kaufen, einen Teil für Dips aufheben, nur bei Dips kaufen.

Test-Push: Actions → MSCI-Kompass → Run workflow → „Test-Push senden“.

Keine Anlageberatung.
