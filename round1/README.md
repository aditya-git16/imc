# Round 1 Submission Strategy

This document is a detailed reference for `round1/round1_submission.py`: what it
assumes about market structure, how it computes fair value, how it chooses order
prices/sizes, and how to debug behavior from logs.

The strategy is intentionally simple and modular:

1. Estimate fair value per product
2. Aggressively take obvious edge
3. Clear inventory near fair value
4. Post passive quotes with inventory-aware skew

---

## 1) Universe, constraints, and intent

### Traded products

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

### Position limits

- `80` contracts per product (`POSITION_LIMITS`)

### Design intent

- OSMIUM is treated as mostly stationary around a known anchor.
- PEPPER_ROOT is treated as drift-prone and better represented by deep/liquid
  market-maker levels than by raw top-of-book touches.
- Execution is split into three stages (take, clear, make) so inventory control
  is explicit rather than implicit.

---

## 2) Tick-level control flow

At each `run(state)` call:

1. Load persistent `traderData` state (price histories).
2. Iterate through products in `state.order_depths`.
3. Skip unknown products (hard whitelist via `POSITION_LIMITS`).
4. Compute current position and fair value.
5. Build orders with `_build_orders(...)`.
6. Emit decision snapshot in `lambdaLog` as `DV`.
7. Save updated histories back into `traderData`.

Return signature:

- `orders_by_product`
- `conversions = 0`
- `trader_data` (JSON-serialized internal state)

---

## 3) Fair value models

## 3.1 `ASH_COATED_OSMIUM` fair value

### Rationale

OSMIUM is centered near `10000`, but a fully static value is too rigid for local
micro-drift. The model blends a constant anchor with a short micro-price average.

### Inputs and constants

- Static anchor: `OSMIUM_FAIR_VALUE = 10000`
- History length: `OSMIUM_HISTORY = 8`
- Adaptive blend weight: `OSMIUM_ADAPTIVE_WEIGHT = 0.8`

### Micro-price formula

Using best bid/ask and their visible volumes:

- `best_bid`, `best_ask`
- `bid_vol`, `ask_vol`

Micro-price:

- `(best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)`

Interpretation: fair value shifts toward the side with less displayed liquidity.

### Final OSMIUM fair value

- Maintain rolling history of micro-prices (max 8 points).
- Compute adaptive anchor as history mean.
- Blend:
  - `(1 - 0.8) * 10000 + 0.8 * adaptive_anchor`

This dampens one-tick noise but still tracks persistent shift.

## 3.2 `INTARIAN_PEPPER_ROOT` fair value

### Rationale

PEPPER_ROOT top-of-book can include noisy/small retail quotes. The strategy tries
to infer the true center from "thick" levels first, then smooths.

### MM midpoint estimator

- `MM_VOLUME_THRESHOLD = 18`
- Filter bids to levels with volume `>= 18`
- Filter asks to levels with absolute volume `>= 18`
- Pick:
  - bid price from thick bid with largest size
  - ask price from thick ask with largest size
- Midpoint of those two prices = `mm_mid`

If thick levels are missing on either side, fallback to normal top-of-book midpoint.

### Smoothing

- Keep rolling history length `PEPPER_HISTORY = 5`
- Fair value = mean(history)
- If no history and no usable midpoint, return `None` and skip trading that tick.

---

## 4) Execution engine: take -> clear -> make

Parameters per product:

- OSMIUM: `(take_edge=1, clear_edge=0, make_edge=1, make_size_cap=50)`
- PEPPER_ROOT: `(take_edge=1, clear_edge=0, make_edge=1, make_size_cap=40)`

Capacities:

- `buy_capacity = limit - position`
- `sell_capacity = limit + position`

The order book is copied into mutable `asks`/`bids` so later stages account for
liquidity consumed by earlier stages.

## 4.1 Take stage

### Baseline thresholds

- Buy trigger: asks `<= fv - take_edge`
- Sell trigger: bids `>= fv + take_edge`

### Soft inventory-aware adjustment

To avoid getting pinned near limits in quiet books:

- `soft_trigger = limit // 2` (40)
- If heavily short (`position <= -40`), buy threshold becomes less strict by 1 tick.
- If heavily long (`position >= +40`), sell threshold becomes less strict by 1 tick.

This allows inventory recovery even when edge is marginal.

### Sweep mechanics

- Buy side: iterate asks ascending, consume while trigger holds and capacity remains.
- Sell side: iterate bids descending, consume while trigger holds and capacity remains.

## 4.2 Clear stage

Objective: reduce residual inventory at neutral-or-better prices after taking.

- Compute `effective_position = current_position + net_new_orders`.
- If effective long:
  - sell into bids `>= round(fv + clear_edge)`
- If effective short:
  - buy from asks `<= round(fv - clear_edge)`

With `clear_edge = 0`, clear is willing to flatten at fair value.

## 4.3 Make stage

Objective: keep quoting passively when capacity remains.

1. Build surviving top-of-book from mutated `asks`/`bids`.
2. Place quotes roughly one tick inside best surviving levels.
3. Enforce no-quote-through-fair-value safety:
   - bid cannot exceed `fv - make_edge`
   - ask cannot go below `fv + make_edge`

### Inventory skew

- When short (`position < 0`), `skew = -1` shifts both quotes upward.
- Effect:
  - ask becomes more aggressive (higher chance to sell if needed)
  - bid becomes less aggressive
  - net bias is toward reducing short exposure over time

### Size

- Post at most one passive bid and one passive ask
- Each capped by remaining capacity and `make_size_cap`

---

## 5) Decision telemetry (`DV`)

Each tick logs:

- `fv`: rounded fair value
- `pb`: passive bid quote
- `pa`: passive ask quote
- `pos`: starting position at tick
- `tb`: effective take-buy threshold
- `ts`: effective take-sell threshold

These are emitted as:

- `{"DV":{"t":timestamp,"d":{product:decision}}}`

The `viz` dashboard parses these from `lambdaLog` and overlays them on the book.

---

## 6) Persistent state (`traderData`)

Stored JSON object:

- `ASH_COATED_OSMIUM`: list of recent micro-prices
- `INTARIAN_PEPPER_ROOT`: list of recent MM/top-of-book mids

Behavior:

- State is loaded safely (`JSONDecodeError` fallback to defaults).
- Histories are clipped to fixed lengths every update.
- This keeps state compact and deterministic across ticks.

---

## 7) Risk behavior and expected dynamics

### What should happen in healthy runs

- OSMIUM `fv` remains close to 10000 with mild adaptation.
- PEPPER_ROOT `fv` tracks trend with less one-tick noise than raw midpoint.
- Inventory oscillates around zero, not saturating near `+-80`.
- Passive quotes remain outside fair value boundaries.

### Failure patterns to watch

- **Inventory sticking near limits**: take thresholds too strict or make quotes too passive.
- **Frequent adverse passive fills**: fair value lags trend; consider wider make edge.
- **Overtrading/noisy churn**: fair value too reactive; increase history window or edge.

---

## 8) Tuning levers

Primary parameters to tune:

- `OSMIUM_HISTORY`, `OSMIUM_ADAPTIVE_WEIGHT`
- `MM_VOLUME_THRESHOLD`, `PEPPER_HISTORY`
- `take_edge`, `clear_edge`, `make_edge`
- `make_size_cap`
- `soft_trigger` policy

Trade-offs:

- Larger edge -> fewer trades, better average edge, more missed opportunity.
- Smaller edge -> more fills, higher adverse-selection risk.
- More smoothing -> less noise, more lag in trends.
- Larger passive size -> better queue capture, higher inventory swing risk.

---

## 9) Practical evaluation checklist

When reviewing a run:

1. Verify `fv` line vs realized price path for each product.
2. Check whether aggressive fills mostly occur beyond `tb`/`ts`.
3. Confirm clear stage reduces large directional inventory.
4. Inspect fill-edge panel for persistent negative clusters.
5. Compare PnL drawdowns with inventory spikes and FV drift periods.

If needed, replay suspicious windows and inspect `DV` + `lambdaLog` tick by tick.
