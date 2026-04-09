# Strategy Note -v

This tutorial submission uses a simple market-making and mean-reversion strategy for the two available products: `EMERALDS` and `TOMATOES`.

## Overview

The main idea of the strategy is to estimate a fair value for each product and then trade when the market price appears favorable relative to that estimate. In addition, the bot places passive quotes around its fair value to capture spread while keeping its inventory within the allowed limits.

## EMERALDS Strategy

For `EMERALDS`, the strategy assumes a fixed fair value of `10000`.

This value was inferred from the historical tutorial data, where the mid-price of `EMERALDS` remained very stable and stayed close to `10000` throughout the available sample. Since the price behavior was highly stable, a constant fair-value estimate was used instead of a dynamic model.

The bot therefore:

- buys `EMERALDS` when the ask price is sufficiently below `10000`
- sells `EMERALDS` when the bid price is sufficiently above `10000`
- places passive buy and sell orders around this fair value to try to earn spread

## TOMATOES Strategy

For `TOMATOES`, the price moves more over time, so a fixed fair value is less appropriate.

Instead, the strategy estimates fair value using the average of the last `12` observed mid-prices. The mid-price is defined as:

```text
mid_price = (best_bid + best_ask) / 2
```

The mid-price gives a simple estimate of the current market center. Averaging the recent mid-prices helps smooth out short-term fluctuations and provides a rough short-term fair-value estimate.

Using that estimate, the bot:

- buys `TOMATOES` when the ask price is sufficiently below the estimated fair value
- sells `TOMATOES` when the bid price is sufficiently above the estimated fair value
- places passive buy and sell quotes near the estimated fair value

## Inventory Control

Both tutorial products have a position limit of `80`, so the strategy includes basic inventory management.

The bot tracks its current position in each product and adjusts its passive quoting to avoid building up excessive long or short inventory. If the bot becomes too long, it shifts its quotes to encourage selling. If it becomes too short, it shifts its quotes to encourage buying back inventory.

This helps the strategy stay within the allowed limits and reduces the risk of carrying overly large positions.

## Rationale

This strategy was designed as a simple and conservative tutorial-round approach. Its purpose is not to predict large market moves, but to:

- trade around estimated fair value
- capture spread where possible
- stay within position limits
- remain easy to understand and modify

## Limitations

The strategy is intentionally basic.

- The `EMERALDS` fair value is assumed to be fixed rather than adaptively estimated.
- The `TOMATOES` fair value uses only a short moving average, which may lag when prices move quickly.
- Inventory control is simple and does not fully optimize risk or exit timing.

Overall, this is a reasonable starter strategy for the tutorial round and provides a foundation for more advanced improvements later.
