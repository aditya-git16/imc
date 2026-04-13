# IMC Prosperity visualisation

A local Dash dashboard for inspecting IMC Prosperity submission logs.

## What it shows

Three stacked panels sharing a timestamp axis:

1. **Order book & trades** — bid/ask levels 1-3 (blue = bid, red = ask,
   marker size scales with resting volume, fainter markers for deeper levels),
   mid-price line, and our own fills as green/red triangles.
2. **PnL** — the `profit_and_loss` column from the submission activities log.
3. **Position** — running net inventory from own trades.

Hovering any plot prints the algorithm's sandbox/lambda log for the nearest
tick underneath.

## Install & run

```bash
pip install -r viz/requirements.txt
python -m viz.app --log tutorial_round/pnl_logs/64424/64424.log
```

Then open <http://127.0.0.1:8050>.

## Flags

- `--log PATH`   submission `.log` file (required)
- `--port N`     dev-server port (default 8050)
- `--debug`      enable Dash hot-reload

The product selector and max-points slider control which product is rendered
and how aggressively the book snapshots are downsampled (large submissions
have ~20k rows per product — 5k points is a good default).
