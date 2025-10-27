# EMA/MA Crossover Strategy for Freqtrade

Dieses Repository enthält eine Futures-Strategie für Freqtrade, die auf dem Zusammenspiel
zwischen einem geglätteten Simple Moving Average (SMA) und einem nachgeschalteten
Exponential Moving Average (EMA) basiert. Die Strategie ist auf Hyperliquid-Swaps
zugeschnitten, funktioniert aber prinzipiell auf jeder Börse mit Hedge-Mode.

## Funktionsweise
- **Zeitfenster:** Die Signalgenerierung läuft auf dem 15-Minuten-Chart. Zusätzlich wird
der 1-Stunden-Chart als "Higher Timeframe" (HTF) eingemischt, um Regime-Informationen
bereitzustellen.
- **Indikatoren:**
  - `xMA`: SMA des Schlusskurses mit einstellbarer Länge (`length_ma`).
  - `xEMA`: EMA des `xMA` mit eigenem Glättungsfaktor (`length_ema`).
  - `atrp`: Prozentuale Average True Range als Volatilitätsmaß (`atr_len`).
- **Entry-Logik:**
  - Long, wenn der EMA unter den SMA kreuzt und gleichzeitig Mindestanforderungen an
    Volatilität (`min_atr_pct`) und Linienabstand (`min_sep_pct`) erfüllt sind.
  - Short, wenn der EMA über den SMA kreuzt und dieselben Filter erfüllt sind.
  - Der HTF-Regimefilter erlaubt Trades nur in Richtung des vorherrschenden Trends.
    In neutralen Phasen werden Breakout-Entries akzeptiert, wenn die Volatilität (`neutral_min_atr_pct`)
    hoch genug ist und der Kurs das Hoch/Tief der letzten `neutral_breakout_window`
    Kerzen über- bzw. unterschreitet.
- **Exit-Logik:** Trades werden geschlossen, wenn es zum Gegenkreuz von EMA und SMA
  kommt. Weitere ROI- oder Trailing-Logiken sind deaktiviert, damit die Strategie rein
  signalbasiert bleibt.

## Risiko- und Order-Management
- **Stop-Loss:** Ein ATR-basierter Custom-Stop-Loss sichert Positionen dynamisch ab.
  Fällt keine ATR vor, wird auf ein Fallback-Limit (`fallback_stoploss`) zurückgegriffen.
  Gewinne >2×ATR ziehen den Stop nach, ab >3×ATR liegt der Stop mindestens auf Break-even.
  Ein harter Cap (`max_stoploss_pct`) begrenzt die maximale Verlustspanne je Trade.
- **Hebel:** Der dynamische Hebel richtet sich nach der aktuellen Volatilität. Je ruhiger der
  Markt, desto höher kann der Hebel werden, begrenzt durch `leverage_hard_cap` und einen
  ATR-Floor (`leverage_atr_floor`).
- **Protections:** Mehrere Schutzmechanismen (`CooldownPeriod`, `StoplossGuard`,
  `MaxDrawdown`) reduzieren serielle Verluste und erzwingen Handels-Pausen nach
  Drawdowns.
- **Ordertypen:** Standardmäßig werden Limit-Orders mit Good-Til-Cancelled (`gtc`) genutzt.
  Für Notfälle existieren Market-Fallbacks (`force_exit`, `stoploss`, `emergency_exit`).

## Konfiguration
Die Beispielkonfiguration in `config.json` ist auf Hyperliquid ausgerichtet und aktiviert
Dry-Run, Hedge-Mode sowie isolierte Margin. Wichtige Eckpunkte:
- `max_open_trades`: 6 parallele Positionen
- `leverage`: 10 (wird durch die Strategie weiter begrenzt)
- Orderbuchbasierte Entries mit kleinem Preis-Puffer (`price_last_balance`)
- Statische Pairlist mit den liquidesten USDC-Swaps der Börse

Passe die Konfiguration an deine Börse, dein Risikoprofil und deinen Account an, bevor du
live handelst. Achte insbesondere darauf, API-Schlüssel und sensible Daten zu ersetzen.

## Voraussetzungen & Nutzung
1. Freqtrade installieren und konfigurieren (siehe [Freqtrade-Dokumentation](https://www.freqtrade.io)).
2. Strategie-Datei `ema_ma_crossover_strategy.py` in den `user_data/strategies`-Ordner
   deines Bots kopieren oder das Repository direkt als Arbeitsverzeichnis nutzen.
3. `config.json` anpassen (API-Daten, Wallet-Größe, Whitelist usw.).
4. Backtest durchführen, um Einstellungen und Ergebnisse zu verifizieren:
   ```bash
   freqtrade backtesting --config config.json --strategy EmaMaCrossoverStrategy
   ```
5. Optional Hyperopt, Trockentest und schrittweise Live-Schaltung vornehmen.

## Hinweise
- Die Strategie setzt auf Datenkonsistenz (ATR und HTF-Regime). Überwache Logs, falls
  Datenfeeds ausfallen oder Paare illiquide sind.
- Prüfe regelmäßig die Wirksamkeit der Protections und passe Schwellenwerte an die
  Marktbedingungen an.
- Hebelhandel birgt hohe Risiken – nutze angemessene Positionsgrößen und Stopps.

Viel Erfolg beim Testen und Anpassen der Strategie!
