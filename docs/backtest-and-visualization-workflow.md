# Backtest and visualization workflow

This guide covers **prosperity3bt**, **jmerle’s Prosperity 3 visualizer**, and the **local Dash dashboard** (`viz/`) for this repository.

## Prerequisites in this repo

- Tutorial CSVs live under `tutorial_round/tutorial_round_data/round0/` (prosperity3bt expects `data_root/roundN/...`).
- `tutorial_round/datamodel.py` is a copy of the backtester’s model (same `from datamodel import ...` layout as competition submissions).
- `tutorial_round/prosperity_logger.py` + `Logger` / `logger.flush()` in `tutorial_submission.py` so logs match jmerle’s format; `DV` JSON goes through `logger.print()` for the local viz.
- The backtester’s `LIMITS` in `prosperity3bt/data.py` includes tutorial products `EMERALDS` and `TOMATOES` where needed.

## 1. One-time setup (from repository root)

```bash
cd /path/to/imc

python3 -m venv .venv
source .venv/bin/activate

pip install -e imc-prosperity-3-backtester
pip install -r viz/requirements.txt
```

Run `source .venv/bin/activate` in every new shell before the commands below.

## 2. Run the backtest and write `run.log`

```bash
cd /path/to/imc
source .venv/bin/activate

mkdir -p backtests

prosperity3bt tutorial_round/tutorial_submission.py 0--1 \
  --data tutorial_round/tutorial_round_data \
  --out backtests/run.log
```

- `**0--1**` means round **0**, day **-1** (note the **two** dashes: `0--1`, not `0-1`).
- `**--data`** must point at a directory that contains `**round0/prices_round_0_day_*.csv**` (and matching trades files).

## 3. jmerle’s visualizer

Use the **same** `run.log` file:

- **Hosted:** [jmerle.github.io/imc-prosperity-3-visualizer](https://jmerle.github.io/imc-prosperity-3-visualizer/) → **Load from file** → select `backtests/run.log`.
- **Local build:** clone [imc-prosperity-3-visualizer](https://github.com/jmerle/imc-prosperity-3-visualizer), `pnpm install` / `pnpm dev`, then load the file in the app.

## 4. Local Dash viz (`viz/`)

```bash
cd /path/to/imc
source .venv/bin/activate

python -m viz.app --log backtests/run.log
```

Open **[http://127.0.0.1:8050](http://127.0.0.1:8050)** (or pass `--port N`).

The parser accepts both **submission JSON** exports and **prosperity3bt text** logs (`Sandbox logs:` / `Activities log:` / `Trade History:`)

