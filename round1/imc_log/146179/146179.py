"""Round 1 strategy: ASH_COATED_OSMIUM (stable) + INTARIAN_PEPPER_ROOT (trending).

Design (take–clear–make, per product):
  1. Estimate a fair value (FV):
     - OSMIUM: constant 10000 (data std is ~5; mean is 10000 across all 3 days).
     - PEPPER_ROOT: derive from the "market maker" quotes on the book.
       The book has one retail layer (best bid/ask, small size) and a deeper
       MM layer at a fixed offset. The midpoint of the highest-volume bid and
       highest-volume ask is a clean, drift-tracking anchor that beats a
       rolling mid-price EMA for this product.
  2. Take: cross the spread whenever an ask sits at/under FV (buy) or a bid
     sits at/over FV (sell), with a small edge threshold to avoid noise.
  3. Clear: if we're carrying inventory and the book offers neutral-or-better
     exits, flatten — this prevents adverse-selection bleed when FV drifts.
  4. Make: post passive quotes one tick inside the best "thick" level with
     inventory-skew so we lean away from our current position.
"""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity_logger import Logger

logger = Logger()


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 50,
        "INTARIAN_PEPPER_ROOT": 50,
    }

    # OSMIUM is a stable rainforest-resin style asset; fair value is constant.
    OSMIUM_FAIR_VALUE = 10000

    # Minimum volume to treat a level as a "market-maker" quote (vs retail fill).
    MM_VOLUME_THRESHOLD = 15

    # History length for PEPPER_ROOT fair-value smoothing (ticks).
    PEPPER_HISTORY = 4

    # Per-product config: (take_edge, clear_edge, make_edge, make_size_cap)
    # - take_edge: take a resting order only if price is >= this many ticks inside FV.
    # - clear_edge: when flattening inventory, accept price within this many ticks of FV.
    # - make_edge: passive quote distance from FV.
    # - make_size_cap: maximum size per passive quote layer.
    PARAMS: Dict[str, Tuple[int, int, int, int]] = {
        # OSMIUM: stable 10000 → edges in ticks off FV.
        # PEPPER_ROOT: adaptive FV; slightly wider make to avoid drift adverse-selection.
        "ASH_COATED_OSMIUM": (1, 0, 1, 30),
        "INTARIAN_PEPPER_ROOT": (1, 0, 1, 25),
    }

    def run(self, state: TradingState):
        trader_state = self._load_state(state.traderData)

        orders_by_product: Dict[str, List[Order]] = {}
        decisions: Dict[str, Dict[str, int]] = {}

        for product, order_depth in state.order_depths.items():
            if product not in self.POSITION_LIMITS:
                continue

            position = state.position.get(product, 0)
            fair_value = self._estimate_fair_value(product, order_depth, trader_state)
            if fair_value is None:
                continue

            orders, decision = self._build_orders(product, order_depth, fair_value, position)
            orders_by_product[product] = orders
            decisions[product] = decision

        # Decision snapshot for viz/ Dash app (picked up via `DV` prefix from lambdaLog).
        logger.print(json.dumps({"DV": {"t": state.timestamp, "d": decisions}}, separators=(",", ":")))

        trader_data = json.dumps(trader_state, separators=(",", ":"))
        conversions = 0
        logger.flush(state, orders_by_product, conversions, trader_data)
        return orders_by_product, conversions, trader_data

    # ------------------------------------------------------------------ state

    def _load_state(self, trader_data: str) -> Dict[str, List[float]]:
        default = {"INTARIAN_PEPPER_ROOT": []}
        if not trader_data:
            return default
        try:
            data = json.loads(trader_data)
        except json.JSONDecodeError:
            return default
        if "INTARIAN_PEPPER_ROOT" not in data or not isinstance(data["INTARIAN_PEPPER_ROOT"], list):
            data["INTARIAN_PEPPER_ROOT"] = []
        return data

    # ----------------------------------------------------------- fair value

    def _estimate_fair_value(
        self,
        product: str,
        order_depth: OrderDepth,
        trader_state: Dict[str, List[float]],
    ) -> float | None:
        if product == "ASH_COATED_OSMIUM":
            return float(self.OSMIUM_FAIR_VALUE)

        # PEPPER_ROOT: use the midpoint of the largest-volume bid/ask as the
        # instantaneous MM-anchored price, then smooth with a short moving
        # average so single-tick book gaps don't yank the quote around.
        mm_mid = self._mm_mid_price(order_depth)
        if mm_mid is None:
            mm_mid = self._mid_price(order_depth)

        history = trader_state.setdefault(product, [])
        if mm_mid is not None:
            history.append(mm_mid)
            del history[: -self.PEPPER_HISTORY]

        if not history:
            return None
        return sum(history) / len(history)

    def _mm_mid_price(self, order_depth: OrderDepth) -> float | None:
        """Midpoint of the thickest bid and thickest ask (filters retail fills)."""
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None

        mm_bids = [(p, v) for p, v in order_depth.buy_orders.items() if v >= self.MM_VOLUME_THRESHOLD]
        mm_asks = [(p, -v) for p, v in order_depth.sell_orders.items() if -v >= self.MM_VOLUME_THRESHOLD]
        if not mm_bids or not mm_asks:
            return None

        best_mm_bid = max(mm_bids, key=lambda x: x[1])[0]
        best_mm_ask = min(mm_asks, key=lambda x: x[1])[0]
        return (best_mm_bid + best_mm_ask) / 2

    @staticmethod
    def _mid_price(order_depth: OrderDepth) -> float | None:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        return (max(order_depth.buy_orders) + min(order_depth.sell_orders)) / 2

    # ---------------------------------------------------------- order build

    def _build_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
    ):
        limit = self.POSITION_LIMITS[product]
        take_edge, clear_edge, make_edge, make_cap = self.PARAMS[product]
        fv_buy = fair_value - take_edge
        fv_sell = fair_value + take_edge

        orders: List[Order] = []
        buy_capacity = limit - position
        sell_capacity = limit + position

        # Mutable copies of the book so take/clear/make stages reason about remaining liquidity.
        asks = dict(order_depth.sell_orders)  # price -> negative volume
        bids = dict(order_depth.buy_orders)   # price -> positive volume

        # --- 1. TAKE: sweep prices inside FV for free edge. ---------------
        for ask_price in sorted(asks):
            if ask_price > fv_buy or buy_capacity <= 0:
                break
            available = -asks[ask_price]
            if available <= 0:
                continue
            size = min(buy_capacity, available)
            if size > 0:
                orders.append(Order(product, ask_price, size))
                buy_capacity -= size
                asks[ask_price] += size  # reduce magnitude of negative volume

        for bid_price in sorted(bids, reverse=True):
            if bid_price < fv_sell or sell_capacity <= 0:
                break
            available = bids[bid_price]
            if available <= 0:
                continue
            size = min(sell_capacity, available)
            if size > 0:
                orders.append(Order(product, bid_price, -size))
                sell_capacity -= size
                bids[bid_price] -= size

        # --- 2. CLEAR: flatten inventory at or across FV ------------------
        # If we're long, accept any bid >= FV+clear_edge; if short, any ask <= FV-clear_edge.
        effective_position = position + self._net_signed(orders)
        if effective_position > 0 and sell_capacity > 0:
            clear_price = int(round(fair_value + clear_edge))
            qty = min(effective_position, sell_capacity)
            matched = 0
            for bid_price in sorted(bids, reverse=True):
                if bid_price < clear_price or matched >= qty:
                    break
                available = bids[bid_price]
                if available <= 0:
                    continue
                size = min(qty - matched, available)
                if size > 0:
                    orders.append(Order(product, bid_price, -size))
                    sell_capacity -= size
                    bids[bid_price] -= size
                    matched += size
        elif effective_position < 0 and buy_capacity > 0:
            clear_price = int(round(fair_value - clear_edge))
            qty = min(-effective_position, buy_capacity)
            matched = 0
            for ask_price in sorted(asks):
                if ask_price > clear_price or matched >= qty:
                    break
                available = -asks[ask_price]
                if available <= 0:
                    continue
                size = min(qty - matched, available)
                if size > 0:
                    orders.append(Order(product, ask_price, size))
                    buy_capacity -= size
                    asks[ask_price] += size
                    matched += size

        # --- 3. MAKE: post passive quotes one tick inside the thick book --
        # Use remaining asks/bids *after* our takes to identify the top of the
        # surviving book, then join one tick inside.
        surviving_asks = [p for p, v in asks.items() if -v > 0 and p > fair_value + make_edge - 1]
        surviving_bids = [p for p, v in bids.items() if v > 0 and p < fair_value - make_edge + 1]

        best_ask = min(surviving_asks) if surviving_asks else int(round(fair_value + make_edge + 1))
        best_bid = max(surviving_bids) if surviving_bids else int(round(fair_value - make_edge - 1))

        # Inventory skew: shift quotes against our position so we naturally mean-revert inventory.
        skew = position // 50  # gentle 1-tick inventory lean at max position
        passive_bid = min(best_bid + 1, int(round(fair_value - make_edge))) - skew
        passive_ask = max(best_ask - 1, int(round(fair_value + make_edge))) - skew

        # Safety: never quote through FV.
        passive_bid = min(passive_bid, int(round(fair_value - make_edge)))
        passive_ask = max(passive_ask, int(round(fair_value + make_edge)))

        if buy_capacity > 0:
            size = min(buy_capacity, make_cap)
            orders.append(Order(product, passive_bid, size))
        if sell_capacity > 0:
            size = min(sell_capacity, make_cap)
            orders.append(Order(product, passive_ask, -size))

        decision = {
            "fv": int(round(fair_value)),
            "pb": int(passive_bid),
            "pa": int(passive_ask),
            "pos": int(position),
            "skew": int(skew),
            "tb": int(round(fv_buy)),
            "ts": int(round(fv_sell)),
        }
        return orders, decision

    @staticmethod
    def _net_signed(orders: List[Order]) -> int:
        return sum(o.quantity for o in orders)