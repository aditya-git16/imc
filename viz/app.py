"""Dash app entrypoint for the IMC Prosperity visualisation dashboard.

Run locally:
    python -m viz.app --log path/to/submission.log

`--log` is optional; you can set or change the log file from the UI.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import dash
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update

from . import parse, plots

# Single-session cache: one active bundle for the local dev server.
_active_path: Path | None = None
_active_bundle: parse.LogBundle | None = None


def _get_bundle(path: Path) -> parse.LogBundle:
    global _active_path, _active_bundle
    path = path.expanduser().resolve()
    if _active_bundle is not None and _active_path == path:
        return _active_bundle
    _active_bundle = parse.load(path)
    _active_path = path
    return _active_bundle


def _clear_bundle_cache() -> None:
    global _active_path, _active_bundle
    _active_path = None
    _active_bundle = None


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="#666"),
    )
    fig.update_layout(
        template="plotly_white",
        height=920,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def build_app(initial_log: Path | None) -> dash.Dash:
    initial_path_str: str | None = None
    initial_bundle: parse.LogBundle | None = None
    if initial_log is not None:
        p = initial_log.expanduser().resolve()
        if p.is_file():
            initial_path_str = str(p)
            initial_bundle = _get_bundle(p)

    title = "IMC Prosperity viz"
    if initial_bundle and initial_bundle.submission_id:
        title = f"IMC viz — {initial_bundle.submission_id[:8]}"

    app = dash.Dash(__name__, title=title)
    app.layout = _layout(initial_path_str, initial_bundle)
    _register_callbacks(app)
    return app


def _meta_lines(bundle: parse.LogBundle, log_path: Path) -> str:
    return (
        f"submission {bundle.submission_id}  ·  "
        f"{len(bundle.prices):,} book rows  ·  "
        f"{len(bundle.trades):,} trades  ·  "
        f"{len(bundle.own_trades):,} own  ·  "
        f"decisions: {bundle.decisions_source} "
        f"({len(bundle.decisions):,} rows)  ·  "
        f"{log_path}"
    )


def _layout(initial_path_str: str | None, initial_bundle: parse.LogBundle | None) -> html.Div:
    products = initial_bundle.products if initial_bundle else []
    default_product = products[0] if products else None

    meta_text = (
        _meta_lines(initial_bundle, Path(initial_path_str))
        if initial_bundle and initial_path_str
        else "Load a prosperity3bt `.log` file or a submission JSON export."
    )

    return html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "16px"},
        children=[
            html.H3("IMC Prosperity", style={"margin": "0 0 8px"}),
            dcc.Store(id="log-path-store", data=initial_path_str),
            html.Div(
                style={
                    "display": "flex",
                    "flexWrap": "wrap",
                    "gap": 8,
                    "alignItems": "center",
                    "marginBottom": 12,
                },
                children=[
                    html.Label("Log file", style={"fontWeight": 600}),
                    dcc.Input(
                        id="log-path-input",
                        type="text",
                        value=initial_path_str or "",
                        placeholder="/absolute/or/relative/path/to/run.log",
                        debounce=False,
                        style={
                            "flex": "1 1 320px",
                            "minWidth": 240,
                            "padding": "6px 10px",
                            "fontSize": 13,
                            "fontFamily": "ui-monospace, monospace",
                        },
                    ),
                    html.Button(
                        "Load",
                        id="load-log-btn",
                        n_clicks=0,
                        style={
                            "padding": "6px 16px",
                            "cursor": "pointer",
                            "fontWeight": 600,
                        },
                    ),
                ],
            ),
            html.Div(id="log-load-status", style={"fontSize": 12, "marginBottom": 8}),
            html.Div(id="meta-summary", children=meta_text, style={"color": "#666", "fontSize": 12, "marginBottom": 12}),
            html.Div(
                style={
                    "display": "flex",
                    "gap": 16,
                    "alignItems": "center",
                    "marginBottom": 12,
                },
                children=[
                    html.Label("product"),
                    dcc.Dropdown(
                        id="product",
                        options=[{"label": p, "value": p} for p in products],
                        value=default_product,
                        clearable=False,
                        style={"width": 220},
                    ),
                    html.Label("max points"),
                    dcc.Slider(
                        id="max-points",
                        min=500,
                        max=10_000,
                        step=500,
                        value=5000,
                        tooltip={"always_visible": False, "placement": "bottom"},
                    ),
                ],
            ),
            dcc.Loading(
                id="dashboard-loading",
                type="circle",
                children=[dcc.Graph(id="dashboard", config={"displaylogo": False})],
            ),
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


def _register_callbacks(app: dash.Dash) -> None:
    @app.callback(
        Output("log-path-store", "data"),
        Output("log-load-status", "children"),
        Output("meta-summary", "children"),
        Output("product", "options"),
        Output("product", "value"),
        Input("load-log-btn", "n_clicks"),
        State("log-path-input", "value"),
        prevent_initial_call=True,
    )
    def _load_log(_n_clicks, path_str: str | None):
        if not path_str or not path_str.strip():
            return (
                no_update,
                html.Span("Enter a path to a `.log` or JSON file.", style={"color": "#888"}),
                no_update,
                no_update,
                no_update,
            )
        path = Path(path_str.strip())
        if not path.is_file():
            return (
                no_update,
                html.Span(f"Not found: {path}", style={"color": "#b00020"}),
                no_update,
                no_update,
                no_update,
            )
        try:
            _clear_bundle_cache()
            bundle = _get_bundle(path)
        except Exception as e:  # noqa: BLE001 — show parse errors in UI
            return (
                no_update,
                html.Span(f"Error loading log: {e}", style={"color": "#b00020"}),
                no_update,
                no_update,
                no_update,
            )
        opts = [{"label": p, "value": p} for p in bundle.products]
        val = bundle.products[0] if bundle.products else None
        status = html.Span(f"Loaded {path.name}", style={"color": "#1a7f37"})
        return str(path.resolve()), status, _meta_lines(bundle, path.resolve()), opts, val

    @app.callback(
        Output("dashboard", "figure"),
        Input("log-path-store", "data"),
        Input("product", "value"),
        Input("max-points", "value"),
    )
    def _update_figure(store_path: str | None, product: str | None, max_points: int | None):
        if not store_path:
            return _empty_figure("Enter the path to a log file and click Load.")
        path = Path(store_path)
        if not path.is_file():
            return _empty_figure(f"File not found: {path}")
        try:
            bundle = _get_bundle(path)
        except Exception as e:  # noqa: BLE001
            return _empty_figure(f"Error: {e}")
        if not bundle.products:
            return _empty_figure("No products in this log.")
        prod = product if product in bundle.products else bundle.products[0]
        mp = max_points if max_points is not None else 5000
        return plots.build_dashboard(bundle, prod, max_points=int(mp))

    @app.callback(
        Output("log-viewer", "children"),
        Input("dashboard", "hoverData"),
        Input("log-path-store", "data"),
    )
    def _update_log(hover, store_path: str | None):
        if not store_path:
            return "load a log file to inspect sandbox/lambda lines per tick."
        path = Path(store_path)
        if not path.is_file():
            return "(log file missing)"
        try:
            bundle = _get_bundle(path)
        except Exception:  # noqa: BLE001
            return "(could not load log)"
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
    ap.add_argument(
        "--log",
        type=Path,
        default=None,
        help="optional initial path to submission .log or JSON (can change in the UI)",
    )
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    app = build_app(args.log)
    app.run(debug=args.debug, port=args.port)


if __name__ == "__main__":
    main()
