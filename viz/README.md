# IMC Prosperity Visualisation

A local Dash dashboard for inspecting IMC Prosperity submission logs.

## What it shows

Four stacked panels with shared timestamp axis:

1. **Order book + overlays + own fills**
   - L1-L3 bid/ask clouds (marker size scales with resting volume)
   - strategy overlays when available (`fair value`, passive bid/ask)
   - own buy/sell fills
2. **PnL** from `activitiesLog.profit_and_loss`
3. **Position** from cumulative own trades
4. **Fill edge** per fill and cumulative edge

Hovering any panel shows nearest tick logs (`sandboxLog`, `lambdaLog`) below.

## Input log formats

- **prosperity3bt text log** (`--out run.log`)
- **Prosperity API JSON export**

If `DV` decision payloads are present in `lambdaLog`, the dashboard uses them.
Otherwise it falls back to derived decisions.

## Install and run

```bash
pip install -r viz/requirements.txt
python -m viz.app --log path/to/run.log
```

Open [http://127.0.0.1:8050](http://127.0.0.1:8050).

## CLI flags

- `--log PATH`: initial `.log` or `.json` file (optional, can load in UI)
- `--port N`: server port (default `8050`)
- `--debug`: enable Dash hot reload
