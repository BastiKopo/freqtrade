# -*- coding: utf-8 -*-
"""Freqtrade implementation of the TradingView "UT Bot Alerts" indicator."""

from __future__ import annotations

from typing import Dict

import numpy as np
from pandas import DataFrame, Series

from freqtrade.strategy.interface import IStrategy
from freqtrade.vendor.qtpylib import indicators as qtpylib


class UtBotStrategy(IStrategy):
    """Replicates the behaviour of the TradingView "UT Bot Alerts" script."""

    timeframe: str = "15m"
    process_only_new_candles: bool = True
    startup_candle_count: int = 200

    minimal_roi = {"0": 10.0}
    stoploss: float = -0.2
    trailing_stop: bool = False

    can_short: bool = True
    position_adjustment_enable: bool = False

    order_types: Dict[str, str] = {
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

    order_time_in_force: Dict[str, str] = {
        "entry": "gtc",
        "exit": "gtc",
        "entry_long": "gtc",
        "entry_short": "gtc",
        "exit_long": "gtc",
        "exit_short": "gtc",
        "force_entry": "gtc",
        "force_exit": "gtc",
        "force_entry_long": "gtc",
        "force_entry_short": "gtc",
        "force_exit_long": "gtc",
        "force_exit_short": "gtc",
        "stoploss": "gtc",
        "emergency_exit": "gtc",
    }

    stoploss_on_exchange: bool = False
    stoploss_on_exchange_interval: int = 60
    stoploss_on_exchange_limit_ratio: float = 0.99

    # --- Parameters taken from the TradingView script ---
    atr_period: int = 10
    key_value: float = 1.0
    use_heikin_ashi_source: bool = False

    plot_config = {
        "main_plot": {
            "ut_trailing_stop": {"color": "orange"},
        },
    }

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        config.pop("order_time_in_force", None)
        self.order_time_in_force = self.order_time_in_force.copy()

    # --- Helper methods -------------------------------------------------
    @staticmethod
    def _atr(dataframe: DataFrame, period: int) -> Series:
        high_low = (dataframe["high"] - dataframe["low"]).abs()
        high_close = (dataframe["high"] - dataframe["close"].shift()).abs()
        low_close = (dataframe["low"] - dataframe["close"].shift()).abs()
        tr = np.maximum.reduce([high_low.values, high_close.values, low_close.values])
        tr_series = Series(tr, index=dataframe.index, name="tr")
        return tr_series.ewm(alpha=1.0 / period, adjust=False).mean()

    @staticmethod
    def _crossover(a: Series, b: Series) -> Series:
        return (a > b) & (a.shift(1) <= b.shift(1))

    @staticmethod
    def _crossunder(a: Series, b: Series) -> Series:
        return (a < b) & (a.shift(1) >= b.shift(1))

    @staticmethod
    def _ut_trailing_stop(src: Series, nloss: Series) -> Series:
        values = np.zeros(len(src))

        for i, (price, loss) in enumerate(zip(src.values, nloss.values)):
            prev_stop = values[i - 1] if i > 0 else 0.0
            prev_src = src.iloc[i - 1] if i > 0 else src.iloc[i]

            if not np.isfinite(price):
                values[i] = prev_stop
                continue

            if not np.isfinite(loss):
                loss = 0.0

            if price > prev_stop and prev_src > prev_stop:
                stop_val = max(prev_stop, price - loss)
            elif price < prev_stop and prev_src < prev_stop:
                stop_val = min(prev_stop, price + loss)
            elif price > prev_stop:
                stop_val = price - loss
            else:
                stop_val = price + loss

            values[i] = stop_val

        return Series(values, index=src.index, name="ut_trailing_stop")

    # --- Indicator population ------------------------------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()

        if self.use_heikin_ashi_source:
            ha = qtpylib.heikinashi(df)
            source = ha["close"]
        else:
            source = df["close"]

        atr = self._atr(df, self.atr_period)
        nloss = self.key_value * atr

        df["ut_source"] = source
        df["ut_atr"] = atr
        df["ut_nloss"] = nloss
        df["ut_trailing_stop"] = self._ut_trailing_stop(source, nloss)

        df["ut_crossover"] = self._crossover(source, df["ut_trailing_stop"])
        df["ut_crossunder"] = self._crossunder(source, df["ut_trailing_stop"])

        df["ut_buy"] = (source > df["ut_trailing_stop"]) & df["ut_crossover"]
        df["ut_sell"] = (source < df["ut_trailing_stop"]) & df["ut_crossunder"]

        return df

    # --- Entry / Exit rules --------------------------------------------
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()
        df.loc[df["ut_buy"], "enter_long"] = 1
        df.loc[df["ut_sell"], "enter_short"] = 1
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()
        df.loc[df["ut_sell"], "exit_long"] = 1
        df.loc[df["ut_buy"], "exit_short"] = 1
        return df
