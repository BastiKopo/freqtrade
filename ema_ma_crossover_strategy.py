# -*- coding: utf-8 -*-
from typing import List, Tuple
import numpy as np
from pandas import DataFrame

from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair


class EmaMaCrossoverStrategy(IStrategy):
    """
    EMA(SMA) vs. SMA Crossover – kompatibel zu deinem TradingView-Snippet:

        xMA  = SMA(close, length_ma)
        xEMA = EMA(xMA, length_ema)

    Entry:
        Long  wenn xEMA UNTER xMA kreuzt (plus Filter)
        Short wenn xEMA ÜBER  xMA kreuzt (plus Filter)

    Exit:
        Gegenkreuz (signalbasiert). ROI/Trailing deaktiviert.
    """

    # === Basis ===
    timeframe: str = "15m"
    informative_timeframe: str = "1h"
    process_only_new_candles: bool = True
    startup_candle_count: int = 300

    # === Risiko/Ausstiege (Signal-only) ===
    minimal_roi = {"0": 10.0}      # effektiv aus
    trailing_stop: bool = False
    stoploss: float = -0.99        # tatsächliche Steuerung via custom_stoploss
    use_custom_stoploss: bool = True

    # === Futures ===
    can_short: bool = True
    position_adjustment_enable: bool = False

    # ---------- Order-Typen (VOLLSTÄNDIG & alt-kompatibel) ----------
    # Einige Freqtrade-Versionen prüfen sehr strikt auf diese Keys.
    # Wir definieren ALLES, inkl. stoploss_on_exchange-Parameter im Mapping
    # und zusätzlich als Klassenflag (siehe unten).
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "entry_long": "limit",
        "entry_short": "limit",
        "exit_long": "limit",
        "exit_short": "limit",
        "force_entry": "market",
        "force_exit": "market",
        "force_entry_long": "market",
        "force_entry_short": "market",
        "force_exit_long": "market",
        "force_exit_short": "market",
        "stoploss": "market",
        "emergency_exit": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
        "stoploss_on_exchange_limit_ratio": 0.99,
    }

    # Zeit-in-Kraft – Hyperliquid unterstützt aktuell keine expliziten Vorgaben.
    # Daher überlassen wir die Konfiguration dem Freqtrade-Default (GTC).
    order_time_in_force = {}

    # Einige Releases erwarten dieses Flag als Klassenattribut:
    stoploss_on_exchange: bool = False
    stoploss_on_exchange_interval: int = 60
    stoploss_on_exchange_limit_ratio: float = 0.99

    # === Protections (in neuen FT-Versionen in die Strategie) ===
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 4},
        {
            "method": "StoplossGuard",
            "lookback_period_candles": 200,
            "trade_limit": 2,
            "stop_duration_candles": 60,
            "only_per_pair": False
        },
        {
            "method": "MaxDrawdown",
            "lookback_period_candles": 1440,
            "trade_limit": 20,
            "max_allowed_drawdown": 0.10,
            "stop_duration_candles": 240
        },
    ]

    # === Parameter (wie TV-Inputs) ===
    length_ma: int = 10
    length_ema: int = 10
    atr_len: int = 14

    # Filter-Schwellen
    min_atr_pct: float = 0.003    # >= 0.30% ATR
    min_sep_pct: float = 0.0005   # >= 0.05% Abstand (relativ zu Close)

    # === Plot ===
    plot_config = {
        "main_plot": {
            "xMA": {"color": "red"},
            "xEMA": {"color": "blue"},
        },
    }

    # ---------- Helpers ----------
    @staticmethod
    def _crossed_above(a, b):
        return (a > b) & (a.shift(1) <= b.shift(1))

    @staticmethod
    def _crossed_below(a, b):
        return (a < b) & (a.shift(1) >= b.shift(1))

    # ---------- Informative Pairs ----------
    def informative_pairs(self) -> List[Tuple[str, str]]:
        return [(pair, self.informative_timeframe) for pair in self.dp.current_whitelist()]

    # ---------- Indicators ----------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # xMA / xEMA im Haupt-TF
        df["xMA"] = df["close"].rolling(self.length_ma).mean()
        df["xEMA"] = df["xMA"].ewm(span=self.length_ema, adjust=False).mean()

        # ATR (EWMA) + ATR in %
        tr1 = (df["high"] - df["low"]).abs()
        tr2 = (df["high"] - df["close"].shift()).abs()
        tr3 = (df["low"] - df["close"].shift()).abs()
        df["tr"]  = np.maximum.reduce([tr1, tr2, tr3])
        df["atr"] = df["tr"].ewm(alpha=1 / self.atr_len, adjust=False).mean()
        df["atrp"] = df["atr"] / df["close"]

        # H1-Daten für Trendfilter
        i = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.informative_timeframe
        ).copy()
        i["xMA"]  = i["close"].rolling(self.length_ma).mean()
        i["xEMA"] = i["xMA"].ewm(span=self.length_ema, adjust=False).mean()
        i["regime"] = np.where(i["xEMA"] < i["xMA"], 1, np.where(i["xEMA"] > i["xMA"], -1, 0))

        df = merge_informative_pair(
            df,
            i[["date", "xMA", "xEMA", "regime"]],
            self.timeframe,
            self.informative_timeframe,
            ffill=True,
        )
        # Danach heißen die Spalten xMA_1h, xEMA_1h, regime_1h
        return df

    # ---------- Entries ----------
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()

        # Basis-Signale
        long_sig  = self._crossed_below(df["xEMA"], df["xMA"])
        short_sig = self._crossed_above(df["xEMA"], df["xMA"])

        # Filter: Volatilität & Linienabstand
        dist   = (df["xMA"] - df["xEMA"]).abs() / df["close"]
        vol_ok = df["atrp"] > self.min_atr_pct
        sep_ok = dist > self.min_sep_pct

        # H1-Regime
        regime_h1 = df.get("regime_1h", 0).fillna(0)

        long_entry  = long_sig  & vol_ok & sep_ok & (regime_h1 == 1)
        short_entry = short_sig & vol_ok & sep_ok & (regime_h1 == -1)

        df.loc[long_entry,  "enter_long"]  = 1
        df.loc[short_entry, "enter_short"] = 1
        return df

    # ---------- Exits ----------
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()

        long_exit  = self._crossed_above(df["xEMA"], df["xMA"])   # Gegenkreuz
        short_exit = self._crossed_below(df["xEMA"], df["xMA"])   # Gegenkreuz

        df.loc[long_exit,  "exit_long"]  = 1
        df.loc[short_exit, "exit_short"] = 1
        return df

    # ---------- Custom Stoploss (ATR-basiert) ----------
    def custom_stoploss(
        self,
        pair,
        trade,
        current_time,
        current_rate,
        current_profit,
        **kwargs,
    ) -> float:
        df: DataFrame = kwargs.get("dataframe")
        if df is None or current_time not in df.index or "atrp" not in df.columns:
            return -0.02  # Fallback

        atrp = float(df.loc[current_time, "atrp"])
        if not np.isfinite(atrp) or atrp <= 0:
            return -0.02

        # Initial: 2x ATR
        sl = -2.0 * atrp

        # Gewinne absichern
        if current_profit > 2.0 * atrp:
            sl = max(sl, -1.0 * atrp)
        if current_profit > 3.0 * atrp:
            sl = max(sl, 0.0)  # Break-even

        # Sicherheitsgrenze
        return float(max(sl, -0.10))

    # ---------- Leverage (ATR-limitiert) ----------
    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        **kwargs,
    ) -> float:
        df: DataFrame = kwargs.get("dataframe")
        atrp = 0.005
        if df is not None and current_time in df.index and "atrp" in df.columns:
            v = float(df.loc[current_time, "atrp"])
            if np.isfinite(v) and v > 0:
                atrp = v

        # Ziel: min. ~4x ATR Abstand -> ruhiger Markt -> höherer Hebel; volatiler Markt -> niedriger
        vol_cap = max(1.0, min(max_leverage, 4.0 / (atrp * 100.0)))  # z.B. atrp=0.5% -> 8x
        hard_cap = 10.0
        return float(max(1.0, min(vol_cap, hard_cap)))
