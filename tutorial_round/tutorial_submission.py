import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState

from prosperity_logger import Logger

logger = Logger()


class Trader:
    # Given in resources
    POSITION_LIMITS: Dict[str, int] = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    # Inferred from csv data
    EMERALDS_FAIR_VALUE = 10000
    # How many previous mid_price to average from behind the current mid_price
    HISTORY_LENGTH = 12

    def run(self, state: TradingState):
        trader_state = self._load_state(state.traderData)
        # Dictionary of orders by product
        orders_by_product: Dict[str, List[Order]] = {}
        # Per-tick decision snapshot emitted for offline visualisation (see viz/).
        decisions: Dict[str, Dict[str, int]] = {}
        # For each product, build orders
        # The items() method returns a view object. The view object contains the key-value pairs of the dictionary, as tuples in a list.
        for product, order_depth in state.order_depths.items():
            # Get the current position for the product, if product key is missing use 0 as default
            position = state.position.get(product, 0)
            # Estimate the fair value for the product
            fair_value = self._estimate_fair_value(product, order_depth, trader_state)
            # Build orders for the product
            orders, decision = self._build_orders(product, order_depth, fair_value, position)
            orders_by_product[product] = orders
            decisions[product] = decision

        # Prefix `DV` lets the local viz (`viz/`) extract fair value / quotes from lambdaLog.
        # It must go through logger.print so it is bundled into the official log line from
        # logger.flush (required by jmerle's visualizer and prosperity3bt output).
        logger.print(json.dumps({"DV": {"t": state.timestamp, "d": decisions}}, separators=(",", ":")))

        trader_data = json.dumps(trader_state, separators=(",", ":"))
        conversions = 0
        logger.flush(state, orders_by_product, conversions, trader_data)
        return orders_by_product, conversions, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, List[float]]:
        if not trader_data:
            return {"TOMATOES": []}

        try:
            data = json.loads(trader_data)
        except json.JSONDecodeError:
            return {"TOMATOES": []}

        if "TOMATOES" not in data or not isinstance(data["TOMATOES"], list):
            data["TOMATOES"] = []
        return data

    def _estimate_fair_value(
        self,
        product: str,
        order_depth: OrderDepth,
        trader_state: Dict[str, List[float]],
    ) -> int:
        if product == "EMERALDS":
            return self.EMERALDS_FAIR_VALUE

        mid_price = self._mid_price(order_depth)
        history = trader_state.setdefault(product, [])

        if mid_price is not None:
            history.append(mid_price)
            # Keep only the most recent HISTORY_LENGTH entries in `history`
            # `history[:-N]` selects all older elements except the last N, and `del` removes them in place.
            del history[:-self.HISTORY_LENGTH]

        if history:
            # average of last 12 mid_prices for tomatoes
            return round(sum(history) / len(history))
        # If no history, return a default value of 5000
        return 5000

    def _build_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: int,
        position: int,
    ):
        orders: List[Order] = []
        limit = self.POSITION_LIMITS[product]

        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)

        buy_threshold = fair_value - 2
        sell_threshold = fair_value + 2

        if order_depth.sell_orders:
            for ask_price in sorted(order_depth.sell_orders):
                ask_volume = -order_depth.sell_orders[ask_price]
                if ask_volume <= 0:
                    continue
                if ask_price > buy_threshold or buy_capacity <= 0:
                    break

                size = min(buy_capacity, ask_volume)
                if size > 0:
                    orders.append(Order(product, ask_price, size))
                    buy_capacity -= size

        if order_depth.buy_orders:
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                bid_volume = order_depth.buy_orders[bid_price]
                if bid_volume <= 0:
                    continue
                if bid_price < sell_threshold or sell_capacity <= 0:
                    break

                size = min(sell_capacity, bid_volume)
                if size > 0:
                    orders.append(Order(product, bid_price, -size))
                    sell_capacity -= size

        inventory_skew = round(position / 20)
        passive_bid = fair_value - 3 - inventory_skew
        passive_ask = fair_value + 3 - inventory_skew

        if buy_capacity > 0:
            quote_size = min(buy_capacity, 8)
            orders.append(Order(product, passive_bid, quote_size))

        if sell_capacity > 0:
            quote_size = min(sell_capacity, 8)
            orders.append(Order(product, passive_ask, -quote_size))

        decision = {
            "fv": int(fair_value),
            "bt": int(buy_threshold),
            "st": int(sell_threshold),
            "pb": int(passive_bid),
            "pa": int(passive_ask),
            "pos": int(position),
            "skew": int(inventory_skew),
        }
        return orders, decision

    @staticmethod
    def _mid_price(order_depth: OrderDepth) -> int | None:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        best_bid = max(order_depth.buy_orders)
        best_ask = min(order_depth.sell_orders)
        return (best_bid + best_ask) // 2
