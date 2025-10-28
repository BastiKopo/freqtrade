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

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, BooleanParameter
from technical.indicators import qtpylib
import talib.abstract as ta


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
        atr = ta.ATR(df, timeperiod=period)
        return atr

    @staticmethod
    def _heikin_ashi_close(df: DataFrame) -> pd.Series:
        ha = qtpylib.heikinashi(df)
        return ha["close"]

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
        df["ema1"] = ta.EMA(df["src"], timeperiod=1)

        df["above"] = qtpylib.crossed_above(df["ema1"], df["trailing_stop"]).astype(int)
        df["below"] = qtpylib.crossed_above(df["trailing_stop"], df["ema1"]).astype(int)

        df["barbuy"] = (df["src"] > df["trailing_stop"]).astype(int)
        df["barsell"] = (df["src"] < df["trailing_stop"]).astype(int)

        df["buy_signal"] = (df["barbuy"].astype(bool) & df["above"].astype(bool))
        df["sell_signal"] = (df["barsell"].astype(bool) & df["below"].astype(bool))

        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["buy_signal"], ["enter_long", "enter_tag"]] = (1, "long")
        df.loc[df["sell_signal"], ["enter_short", "enter_tag"]] = (1, "short")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["sell_signal"], ["exit_long", "exit_tag"]] = (1, "exit_long_signal")
        df.loc[df["buy_signal"], ["exit_short", "exit_tag"]] = (1, "exit_short_signal")
        return df
