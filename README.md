# 🧭 MSCI-Kompass

Täglicher Kaufsignal-Check für den MSCI World (iShares Core MSCI World, EUNL) mit Backtest.

**Seite:** https://marcomeindorfer.github.io/msci-kompass/

## So funktioniert's

- Eine GitHub Action (`.github/workflows/kompass.yml`) läuft werktags um 18:30 UTC.
- `bot.py` lädt die Kurse von Yahoo Finance (Fallback: zuletzt gespeicherte `data/kurse.csv`) und berechnet Abstand zum Allzeithoch, 200-Tage-Linie und RSI.
- Daraus ermittelt es die Dip-Stufe:
  - Stufe 1 ab −5 % → 25 % der Rücklage investieren
  - Stufe 2 ab −10 % → 50 % der Rücklage investieren
  - Stufe 3 ab −20 % → die ganze Rücklage investieren
- Jede Stufe löst pro Dip-Phase nur einmal aus. Eine Phase endet, wenn der Kurs wieder innerhalb von 1 % am Hoch ist.
- Bei einer neuen Stufe kommt eine Push-Nachricht über [ntfy](https://ntfy.sh). Das Thema steht im Repo-Secret `NTFY_TOPIC`.
- Die Seite `docs/index.html` wird aus `template.html` erzeugt und über GitHub Pages ausgeliefert.

Einstellungen (Beträge, Stufen) stehen oben in `bot.py`.

Test-Push: Actions → MSCI-Kompass → Run workflow → „Test-Push senden“.

Keine Anlageberatung.
