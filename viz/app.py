"""Dash app entrypoint for the IMC Prosperity visualisation dashboard.

Run locally:
    python -m viz.app --log path/to/submission.log

Then open http://127.0.0.1:8050 in a browser.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import dash
from dash import Input, Output, dcc, html

from . import parse, plots


def build_app(log_path: Path) -> dash.Dash:
    bundle = parse.load(log_path)
    app = dash.Dash(__name__, title=f"IMC viz — {bundle.submission_id[:8]}")
    app.layout = _layout(bundle, log_path)
    _register_callbacks(app, bundle)
    return app


def _layout(bundle: parse.LogBundle, log_path: Path) -> html.Div:
    return html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "16px"},
        children=[
            html.H3(f"IMC Prosperity — {log_path.name}", style={"margin": "0 0 8px"}),
            html.Div(
                f"submission {bundle.submission_id}  ·  "
                f"{len(bundle.prices):,} book rows  ·  "
                f"{len(bundle.trades):,} trades  ·  "
                f"{len(bundle.own_trades):,} own  ·  "
                f"decisions: {bundle.decisions_source} "
                f"({len(bundle.decisions):,} rows)",
                style={"color": "#666", "fontSize": 12, "marginBottom": 12},
            ),
            html.Div(
                style={"display": "flex", "gap": 16, "alignItems": "center",
                       "marginBottom": 12},
                children=[
                    html.Label("product"),
                    dcc.Dropdown(
                        id="product",
                        options=[{"label": p, "value": p} for p in bundle.products],
                        value=bundle.products[0] if bundle.products else None,
                        clearable=False,
                        style={"width": 220},
                    ),
                    html.Label("max points"),
                    dcc.Slider(
                        id="max-points",
                        min=500, max=10_000, step=500, value=5000,
                        tooltip={"always_visible": False, "placement": "bottom"},
                    ),
                ],
            ),
            dcc.Graph(id="dashboard", config={"displaylogo": False}),
            html.H4("algorithm log", style={"marginTop": 8, "marginBottom": 4}),
            html.Div(
                id="log-viewer",
                style={
                    "fontFamily": "ui-monospace, SFMono-Regular, Menlo, monospace",
                    "fontSize": 12,
                    "whiteSpace": "pre-wrap",
                    "background": "#fafafa",
                    "border": "1px solid #e5e5e5",
                    "padding": 10,
                    "maxHeight": 280,
                    "overflowY": "auto",
                },
            ),
        ],
    )


def _register_callbacks(app: dash.Dash, bundle: parse.LogBundle) -> None:
    @app.callback(
        Output("dashboard", "figure"),
        Input("product", "value"),
        Input("max-points", "value"),
    )
    def _update_figure(product, max_points):
        return plots.build_dashboard(bundle, product, max_points=max_points)

    @app.callback(
        Output("log-viewer", "children"),
        Input("dashboard", "hoverData"),
    )
    def _update_log(hover):
        # Find the sandbox-log block closest to the hovered timestamp.
        if not hover or "points" not in hover or not hover["points"]:
            return "hover on a plot to see the algorithm log at that tick."
        ts = hover["points"][0]["x"]
        sandbox = bundle.sandbox
        if sandbox.empty:
            return "(no sandbox/lambda log in this submission)"
        idx = (sandbox["timestamp"] - ts).abs().idxmin()
        row = sandbox.loc[idx]
        return (
            f"t={row['timestamp']}  (hover t={ts})\n\n"
            f"sandbox:\n{row['sandboxLog'] or '(empty)'}\n\n"
            f"lambda:\n{row['lambdaLog'] or '(empty)'}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="IMC Prosperity log visualiser")
    ap.add_argument("--log", required=True, type=Path, help="path to submission .log file")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    app = build_app(args.log)
    app.run(debug=args.debug, port=args.port)


if __name__ == "__main__":
    main()
