"""Parse IMC Prosperity submission `.log` files into tidy dataframes.

A `.log` file is JSON with four keys:
    submissionId   : str
    activitiesLog  : str   — semicolon-separated CSV of order-book snapshots
    logs           : list  — [{sandboxLog, lambdaLog, timestamp}, ...]
    tradeHistory   : list  — [{timestamp, buyer, seller, symbol, price, quantity}, ...]

The helpers here return DataFrames keyed on `timestamp` (in game ticks).
Own trades are identified by `buyer == 'SUBMISSION'` or `seller == 'SUBMISSION'`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pandas as pd

SUBMISSION = "SUBMISSION"


@dataclass
class LogBundle:
    prices: pd.DataFrame          # order-book snapshots
    trades: pd.DataFrame          # all executed trades (market + own)
    own_trades: pd.DataFrame      # subset where we are a counterparty
    sandbox: pd.DataFrame         # per-tick algorithm stdout
    decisions: pd.DataFrame       # per-tick fair value / quote levels / position
    decisions_source: str         # "lambda" if parsed from prints, "derived" otherwise
    submission_id: str
    products: list[str]


def load(path: str | Path) -> LogBundle:
    from . import derive  # local import to avoid circular dependency

    path = Path(path)
    with path.open() as f:
        raw = json.load(f)

    prices = _parse_prices(raw["activitiesLog"])
    trades = _parse_trades(raw.get("tradeHistory", []))
    own_trades = _own_trades(trades)
    sandbox = _parse_sandbox(raw.get("logs", []))
    products = sorted(prices["product"].unique().tolist())

    decisions = _parse_decisions(raw.get("logs", []))
    if decisions.empty:
        decisions = derive.derive_decisions(prices, own_trades)
        source = "derived"
    else:
        source = "lambda"

    return LogBundle(
        prices=prices,
        trades=trades,
        own_trades=own_trades,
        sandbox=sandbox,
        decisions=decisions,
        decisions_source=source,
        submission_id=raw.get("submissionId", ""),
        products=products,
    )


def _parse_prices(text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(text), sep=";")
    # Normalize dtypes — empty book levels come through as NaN already.
    numeric = [c for c in df.columns if c not in ("product",)]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    return df.sort_values(["timestamp", "product"]).reset_index(drop=True)


def _parse_trades(entries: list[dict]) -> pd.DataFrame:
    if not entries:
        return pd.DataFrame(
            columns=["timestamp", "buyer", "seller", "symbol", "price", "quantity"]
        )
    df = pd.DataFrame(entries)
    df["buyer"] = df["buyer"].fillna("")
    df["seller"] = df["seller"].fillna("")
    return df.sort_values("timestamp").reset_index(drop=True)


def _own_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.assign(side=pd.Series(dtype=str))
    mask = (trades["buyer"] == SUBMISSION) | (trades["seller"] == SUBMISSION)
    own = trades[mask].copy()
    own["side"] = own["buyer"].eq(SUBMISSION).map({True: "BUY", False: "SELL"})
    own["signed_qty"] = own["quantity"] * own["side"].map({"BUY": 1, "SELL": -1})
    return own.reset_index(drop=True)


def _parse_sandbox(entries: list[dict]) -> pd.DataFrame:
    if not entries:
        return pd.DataFrame(columns=["timestamp", "sandboxLog", "lambdaLog"])
    df = pd.DataFrame(entries)
    # Drop rows that carry no information — common for quiet ticks.
    has_text = df["sandboxLog"].astype(bool) | df["lambdaLog"].astype(bool)
    return df.loc[has_text].reset_index(drop=True)


def _parse_decisions(entries: list[dict]) -> pd.DataFrame:
    """Pull `DV` lines out of lambdaLog text blobs emitted by Trader.run."""
    rows: list[dict] = []
    for entry in entries:
        text = entry.get("lambdaLog") or ""
        if '"DV"' not in text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not (line.startswith("{") and '"DV"' in line):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            dv = obj.get("DV") or {}
            t = dv.get("t")
            for product, d in (dv.get("d") or {}).items():
                if not isinstance(d, dict):
                    continue
                rows.append({"timestamp": t, "product": product, **d})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["timestamp", "product"]).reset_index(drop=True)


def positions(own_trades: pd.DataFrame, product: str) -> pd.DataFrame:
    """Running net position in `product` after each own trade."""
    sub = own_trades[own_trades["symbol"] == product][["timestamp", "signed_qty"]]
    if sub.empty:
        return pd.DataFrame(columns=["timestamp", "position"])
    out = sub.copy()
    out["position"] = out["signed_qty"].cumsum()
    return out[["timestamp", "position"]].reset_index(drop=True)
