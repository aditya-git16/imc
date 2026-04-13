"""Plotly figure builders for the IMC visualisation dashboard.

The dashboard now stacks four panels sharing a timestamp x-axis:

    1. Order book + mid + strategy overlay (fair value, passive quotes) + own fills
    2. PnL (from the exchange's activities log)
    3. Net position (cumulative from own fills)
    4. Fill edge — per-trade bar + cumulative line; exposes how much of the
       spread you actually captured vs paid away.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import parse

ASK_COLOR = "#d62728"
BID_COLOR = "#1f77b4"
FV_COLOR = "#000000"
PASSIVE_BID_COLOR = "#17becf"   # teal — distinct from the blue bid cloud
PASSIVE_ASK_COLOR = "#ff7f0e"   # orange — distinct from the red ask cloud
BUY_COLOR = "#2ca02c"
SELL_COLOR = "#d62728"

BOOK_LEVELS = (1, 2, 3)


def build_dashboard(
    bundle: parse.LogBundle,
    product: str,
    max_points: int = 5000,
) -> go.Figure:
    prices = bundle.prices[bundle.prices["product"] == product]
    decisions = (
        bundle.decisions[bundle.decisions["product"] == product]
        if not bundle.decisions.empty
        else pd.DataFrame()
    )
    merged = _merge_prices_decisions(prices, decisions)
    merged = _downsample(merged, max_points)

    own = bundle.own_trades[bundle.own_trades["symbol"] == product]
    position = parse.positions(bundle.own_trades, product)
    edges = edge_per_fill(bundle.own_trades, bundle.prices, product)

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.55, 0.15, 0.12, 0.18],
        subplot_titles=(
            f"{product} — order book, fair value & trades",
            "PnL",
            "Position",
            "Fill edge (bars: per-fill edge × qty,  line: cumulative)",
        ),
    )

    _add_book_layers(fig, merged)
    _add_strategy_overlay(fig, merged)
    _add_own_trades(fig, own)
    _add_pnl(fig, merged)
    _add_position(fig, position)
    _add_edge(fig, edges)

    fig.update_layout(
        template="plotly_white",
        height=920,
        margin=dict(l=60, r=20, t=70, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(title_text="timestamp", row=4, col=1)
    fig.update_yaxes(title_text="price", row=1, col=1)
    fig.update_yaxes(title_text="pnl", row=2, col=1)
    fig.update_yaxes(title_text="position", row=3, col=1)
    fig.update_yaxes(title_text="edge (seashells)", row=4, col=1)
    return fig


def _merge_prices_decisions(prices: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return prices.copy()
    return prices.merge(
        decisions.drop(columns=["product"], errors="ignore"),
        on="timestamp",
        how="left",
    )


def _add_book_layers(fig: go.Figure, prices: pd.DataFrame) -> None:
    # Deeper levels rendered fainter so level-1 quotes stand out; the whole
    # book is kept semi-transparent so own-trade markers render on top cleanly.
    for level in BOOK_LEVELS:
        alpha = 0.55 - 0.15 * (level - 1)
        _scatter_level(fig, prices, f"ask_price_{level}", f"ask_volume_{level}",
                       ASK_COLOR, alpha, f"ask L{level}")
        _scatter_level(fig, prices, f"bid_price_{level}", f"bid_volume_{level}",
                       BID_COLOR, alpha, f"bid L{level}")


def _scatter_level(
    fig: go.Figure,
    prices: pd.DataFrame,
    price_col: str,
    vol_col: str,
    color: str,
    alpha: float,
    name: str,
) -> None:
    sub = prices.dropna(subset=[price_col])
    if sub.empty:
        return
    fig.add_trace(
        go.Scatter(
            x=sub["timestamp"],
            y=sub[price_col],
            mode="markers",
            name=name,
            marker=dict(
                color=color,
                size=_size_from_volume(sub[vol_col]),
                opacity=alpha,
                line=dict(width=0),
            ),
            customdata=sub[vol_col],
            hovertemplate="%{x}  px=%{y}  vol=%{customdata}<extra>" + name + "</extra>",
        ),
        row=1,
        col=1,
    )


def _size_from_volume(vol: pd.Series) -> pd.Series:
    v = vol.fillna(0).clip(lower=0)
    if v.max() == 0:
        return pd.Series(4, index=vol.index)
    return 3 + 5 * (v / v.max())


def _add_strategy_overlay(fig: go.Figure, merged: pd.DataFrame) -> None:
    """Fair value + the passive quote lines the algorithm was actually posting."""
    if "fv" not in merged.columns or merged["fv"].isna().all():
        return
    fig.add_trace(
        go.Scatter(
            x=merged["timestamp"], y=merged["fv"],
            mode="lines", name="fair value",
            line=dict(color=FV_COLOR, width=1.8),
            hovertemplate="t=%{x}  fv=%{y}<extra>fair value</extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=merged["timestamp"], y=merged["pb"],
            mode="lines", name="passive bid",
            line=dict(color=PASSIVE_BID_COLOR, width=1.4),
            hovertemplate="t=%{x}  passive bid=%{y}<extra>passive bid</extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=merged["timestamp"], y=merged["pa"],
            mode="lines", name="passive ask",
            line=dict(color=PASSIVE_ASK_COLOR, width=1.4),
            hovertemplate="t=%{x}  passive ask=%{y}<extra>passive ask</extra>",
        ),
        row=1, col=1,
    )


def _add_own_trades(fig: go.Figure, own: pd.DataFrame) -> None:
    for side, color, symbol in (("BUY", BUY_COLOR, "triangle-up"),
                                 ("SELL", SELL_COLOR, "triangle-down")):
        sub = own[own["side"] == side]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["timestamp"],
                y=sub["price"],
                mode="markers",
                name=f"own {side.lower()}",
                marker=dict(color=color, size=14, symbol=symbol,
                            line=dict(color="black", width=1.2)),
                customdata=sub["quantity"],
                hovertemplate="%{x}  px=%{y}  qty=%{customdata}<extra>own " + side + "</extra>",
            ),
            row=1,
            col=1,
        )


def _add_pnl(fig: go.Figure, prices: pd.DataFrame) -> None:
    fig.add_trace(
        go.Scatter(
            x=prices["timestamp"],
            y=prices["profit_and_loss"],
            mode="lines",
            name="pnl",
            line=dict(color="#2ca02c", width=1.5),
            showlegend=False,
        ),
        row=2,
        col=1,
    )


def _add_position(fig: go.Figure, position: pd.DataFrame) -> None:
    if position.empty:
        return
    fig.add_trace(
        go.Scatter(
            x=position["timestamp"],
            y=position["position"],
            mode="lines",
            line=dict(color="#9467bd", width=1.5, shape="hv"),
            name="position",
            showlegend=False,
        ),
        row=3,
        col=1,
    )


def _add_edge(fig: go.Figure, edges: pd.DataFrame) -> None:
    if edges.empty:
        return
    colors = np.where(edges["edge"] >= 0, BUY_COLOR, SELL_COLOR)
    fig.add_trace(
        go.Bar(
            x=edges["timestamp"],
            y=edges["edge"],
            marker_color=colors,
            name="fill edge",
            customdata=np.stack([edges["side"], edges["quantity"], edges["price"]], axis=-1),
            hovertemplate=(
                "t=%{x}  edge=%{y:.1f}<br>"
                "side=%{customdata[0]}  qty=%{customdata[1]}  px=%{customdata[2]}"
                "<extra>fill edge</extra>"
            ),
            showlegend=False,
        ),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=edges["timestamp"],
            y=edges["cum_edge"],
            mode="lines",
            line=dict(color="#111111", width=1.5),
            name="cum edge",
            hovertemplate="t=%{x}  cum edge=%{y:.1f}<extra>cum edge</extra>",
            showlegend=False,
        ),
        row=4,
        col=1,
    )


def edge_per_fill(
    own_trades: pd.DataFrame,
    prices: pd.DataFrame,
    product: str,
) -> pd.DataFrame:
    """For each own fill: edge = (mid − fill_price) × side_sign × quantity.

    Positive = captured edge (bought below mid / sold above). Negative = paid
    edge (picked off or crossed). `mid` uses the latest book snapshot at or
    before the fill timestamp (merge_asof backwards).
    """
    sub = own_trades[own_trades["symbol"] == product].copy()
    if sub.empty:
        return pd.DataFrame(columns=["timestamp", "edge", "cum_edge", "side", "quantity", "price"])
    pri = (
        prices[prices["product"] == product][["timestamp", "mid_price"]]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    merged = pd.merge_asof(
        sub.sort_values("timestamp"),
        pri,
        on="timestamp",
        direction="backward",
    )
    sign = merged["side"].map({"BUY": 1.0, "SELL": -1.0})
    merged["edge"] = (merged["mid_price"] - merged["price"]) * sign * merged["quantity"]
    merged["cum_edge"] = merged["edge"].cumsum()
    return merged[["timestamp", "edge", "cum_edge", "side", "quantity", "price"]]


def _downsample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    step = len(df) // max_points + 1
    return df.iloc[::step].reset_index(drop=True)
