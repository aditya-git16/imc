"""Parse IMC Prosperity submission `.log` files into tidy dataframes.

Supported formats:

1. **API JSON** — an object with keys:
    submissionId   : str
    activitiesLog  : str   — semicolon-separated CSV of order-book snapshots
    logs           : list  — [{sandboxLog, lambdaLog, timestamp}, ...]
    tradeHistory   : list  — [{timestamp, buyer, seller, symbol, price, quantity}, ...]

2. **prosperity3bt text** — files written by `prosperity3bt --out` (same layout jmerle's
   visualizer loads): `Sandbox logs:` … `Activities log:` … optional `Trade History:`.

The helpers here return DataFrames keyed on `timestamp` (in game ticks).
Own trades are identified by `buyer == 'SUBMISSION'` or `seller == 'SUBMISSION'`.
"""
from __future__ import annotations

import json
import re
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
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip("\ufeff").lstrip()
    if stripped.startswith("Sandbox logs:"):
        raw = _parse_prosperity3bt_text(text)
    else:
        raw = json.loads(text)

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


def _parse_prosperity3bt_text(text: str) -> dict:
    """Convert prosperity3bt / jmerle-style text logs into the API JSON shape."""
    text = text.replace("\r\n", "\n")
    if "Sandbox logs:" not in text or "Activities log:" not in text:
        raise ValueError("Not a prosperity3bt text log (missing Sandbox logs / Activities log headers)")

    sandbox_blob = text.split("Sandbox logs:", 1)[1].split("Activities log:", 1)[0].strip()

    after_activities = text.split("Activities log:", 1)[1].lstrip("\n")
    trade_marker = "\n\n\n\n\nTrade History:"
    if trade_marker in after_activities:
        activities_csv, trade_tail = after_activities.split(trade_marker, 1)
        activities_csv = activities_csv.strip()
        trade_tail = trade_tail.strip()
        trade_history = _loads_json_with_trailing_commas(trade_tail) if trade_tail else []
    else:
        activities_csv = after_activities.strip()
        trade_history = []

    logs: list[dict] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(sandbox_blob):
        while idx < len(sandbox_blob) and sandbox_blob[idx].isspace():
            idx += 1
        if idx >= len(sandbox_blob):
            break
        obj, end = decoder.raw_decode(sandbox_blob, idx)
        logs.append(obj)
        idx = end

    return {
        "submissionId": "",
        "activitiesLog": activities_csv,
        "logs": logs,
        "tradeHistory": trade_history,
    }


def _loads_json_with_trailing_commas(blob: str):
    """prosperity3bt trade JSON mimics JS (trailing commas); stdlib json rejects those."""
    cleaned = re.sub(r",(\s*[\]}])", r"\1", blob)
    return json.loads(cleaned)


def _iter_dv_json_objects(text: str):
    """Yield dicts that contain a top-level \"DV\" key (standalone lines or embedded in flush output)."""
    start = 0
    while True:
        i = text.find('{"DV"', start)
        if i == -1:
            return
        try:
            obj, end = json.JSONDecoder().raw_decode(text, i)
        except json.JSONDecodeError:
            start = i + 1
            continue
        if isinstance(obj, dict) and "DV" in obj:
            yield obj
        start = end


def _iter_dv_from_prosperity_flush(text: str):
    """Logger.flush prints one JSON array; the last element is a string containing {\"DV\": ...}."""
    if "DV" not in text or not text.strip().startswith("["):
        return
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        return
    if not isinstance(outer, list):
        return
    for part in outer:
        if not isinstance(part, str) or '"DV"' not in part:
            continue
        try:
            inner = json.loads(part.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(inner, dict) and "DV" in inner:
            yield inner


def _dv_objects_from_lambda(text: str):
    yield from _iter_dv_json_objects(text)
    yield from _iter_dv_from_prosperity_flush(text)


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
    """Pull `DV` payloads out of lambdaLog text (standalone prints or embedded in Logger.flush output)."""
    rows: list[dict] = []
    for entry in entries:
        text = entry.get("lambdaLog") or ""
        # Standalone prints include `"DV"`; Logger.flush embeds DV inside escaped JSON (no bare `"DV"` substring).
        if "DV" not in text:
            continue
        for obj in _dv_objects_from_lambda(text):
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
