"""Replay the algorithm's decision logic directly off the book snapshots.

Used as a fallback when a `.log` file has no `lambdaLog` output (older runs, or
submissions that didn't emit `DV` lines). The values this produces should match
what `tutorial_submission.py` now prints on each tick.
"""
from __future__ import annotations

import pandas as pd

HISTORY_LENGTH = 12
EMERALDS_FAIR_VALUE = 10_000


def derive_decisions(prices: pd.DataFrame, own_trades: pd.DataFrame) -> pd.DataFrame:
    """Return {timestamp, product, fv, bt, st, pb, pa, pos, skew} per book snapshot."""
    frames: list[pd.DataFrame] = []
    for product, grp in prices.groupby("product", sort=False):
        g = grp.sort_values("timestamp").reset_index(drop=True)
        fv = _fair_value(product, g["mid_price"])
        pos = _position_series(own_trades, product, g["timestamp"])
        skew = (pos / 20).round().astype(int)

        frames.append(pd.DataFrame({
            "timestamp": g["timestamp"].values,
            "product": product,
            "fv": fv.values,
            "bt": (fv - 2).values,
            "st": (fv + 2).values,
            "pb": (fv - 3 - skew).values,
            "pa": (fv + 3 - skew).values,
            "pos": pos.values,
            "skew": skew.values,
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fair_value(product: str, mid: pd.Series) -> pd.Series:
    if product == "EMERALDS":
        return pd.Series(EMERALDS_FAIR_VALUE, index=mid.index, dtype="float64")
    # TOMATOES (and anything else): rolling mean of last HISTORY_LENGTH mids,
    # rounded — the same formula as Trader._estimate_fair_value.
    return mid.rolling(HISTORY_LENGTH, min_periods=1).mean().round()


def _position_series(
    own_trades: pd.DataFrame,
    product: str,
    timestamps: pd.Series,
) -> pd.Series:
    """Net position at each tick, built from own fills at timestamps ≤ t."""
    sub = own_trades[own_trades["symbol"] == product]
    if sub.empty:
        return pd.Series(0, index=range(len(timestamps)), dtype="int64")
    qty = sub.groupby("timestamp")["signed_qty"].sum().cumsum()
    pos = qty.reindex(timestamps.values, method="ffill").fillna(0).astype(int)
    return pos.reset_index(drop=True)
