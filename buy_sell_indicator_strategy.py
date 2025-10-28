"""Freqtrade strategy based on TradingView Buy-Sell Indicator by Michael Fernandes.

This strategy mirrors the logic of the Pine Script indicator shared in the user request.
It recreates the ATR-based trailing stop and the accompanying flip conditions to
produce long/short entries as well as opposite exits once the stop is crossed.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import (
    IStrategy,
    IntParameter,
    DecimalParameter,
    BooleanParameter,
)


class BuySellIndicatorStrategy(IStrategy):
    """Implementation of the TradingView "Buy-Sell Indicator" for Freqtrade."""

    # Strategy interface setup
    timeframe = "15m"
    can_short: bool = True

    minimal_roi: Dict[str, float] = {"0": 0.10}
    stoploss = -0.10

    use_custom_stoploss = False
    trailing_stop = False

    # Pine Script inputs exposed as parameters to allow further tweaking.
    key_value = DecimalParameter(0.1, 5.0, decimals=2, default=1.0, space="buy")
    atr_period = IntParameter(1, 50, default=10, space="buy")
    use_heikin_ashi = BooleanParameter(default=False, space="buy")

    def informative_pairs(self):
        return []

    @staticmethod
    def _atr(df: DataFrame, period: int) -> pd.Series:
        """Compute an ATR equivalent without relying on TA-Lib."""

        if period <= 1:
            # ATR with a period of 1 devolves to the true range itself.
            period = 1

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1, skipna=True)

        # Wilder's smoothing for ATR via an exponential moving average.
        alpha = 1.0 / period
        atr = true_range.ewm(alpha=alpha, adjust=False).mean()

        return atr.fillna(method="bfill").fillna(0.0)

    @staticmethod
    def _heikin_ashi_close(df: DataFrame) -> pd.Series:
        open_prices = df["open"].to_numpy(copy=False)
        high_prices = df["high"].to_numpy(copy=False)
        low_prices = df["low"].to_numpy(copy=False)
        close_prices = df["close"].to_numpy(copy=False)

        ha_close = (open_prices + high_prices + low_prices + close_prices) / 4.0
        return pd.Series(ha_close, index=df.index)

    @staticmethod
    def _crossed_above(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
        cond_now = series_a > series_b
        cond_prev = series_a.shift(1) <= series_b.shift(1)
        return (cond_now & cond_prev).fillna(False)

    @staticmethod
    def _crossed_below(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
        cond_now = series_a < series_b
        cond_prev = series_a.shift(1) >= series_b.shift(1)
        return (cond_now & cond_prev).fillna(False)

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        """Return an exponential moving average while accepting period 1 gracefully."""
        if period <= 1:
            return series.astype(float)

        return series.astype(float).ewm(span=period, adjust=False).mean()

    @staticmethod
    def _compute_trailing_stop(src: pd.Series, nloss: pd.Series) -> pd.Series:
        stop_values = np.full(len(src), np.nan, dtype=float)

        for i in range(len(src)):
            current_src = src.iat[i]
            current_nloss = nloss.iat[i]

            if i == 0 or np.isnan(stop_values[i - 1]):
                stop_values[i] = current_src + current_nloss
                continue

            prev_stop = stop_values[i - 1]
            prev_src = src.iat[i - 1]

            if current_src > prev_stop and prev_src > prev_stop:
                stop_values[i] = max(prev_stop, current_src - current_nloss)
            elif current_src < prev_stop and prev_src < prev_stop:
                stop_values[i] = min(prev_stop, current_src + current_nloss)
            elif current_src > prev_stop:
                stop_values[i] = current_src - current_nloss
            else:
                stop_values[i] = current_src + current_nloss

        return pd.Series(stop_values, index=src.index)

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        # Determine the source close, optionally using Heikin Ashi candles.
        src = self._heikin_ashi_close(df) if self.use_heikin_ashi.value else df["close"]
        df["src"] = src

        atr_period = int(self.atr_period.value)
        key_value = float(self.key_value.value)

        df["atr"] = self._atr(df, atr_period)
        df["nloss"] = df["atr"] * key_value

        df["trailing_stop"] = self._compute_trailing_stop(df["src"], df["nloss"])

        # EMA with period 1 effectively mirrors the source but keeps the original logic intact.
        df["ema1"] = self._ema(df["src"], period=1)

        df["above"] = self._crossed_above(df["ema1"], df["trailing_stop"])
        df["below"] = self._crossed_below(df["ema1"], df["trailing_stop"])

        df["barbuy"] = df["src"] > df["trailing_stop"]
        df["barsell"] = df["src"] < df["trailing_stop"]

        df["buy_signal"] = df["barbuy"] & df["above"]
        df["sell_signal"] = df["barsell"] & df["below"]

        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["buy_signal"], ["enter_long", "enter_tag"]] = (1, "long")
        df.loc[df["sell_signal"], ["enter_short", "enter_tag"]] = (1, "short")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["sell_signal"], ["exit_long", "exit_tag"]] = (1, "exit_long_signal")
        df.loc[df["buy_signal"], ["exit_short", "exit_tag"]] = (1, "exit_short_signal")
        return df
