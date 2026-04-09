import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState


class Trader:
    # Given in resources
    POSITION_LIMITS: Dict[str, int] = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    EMERALDS_FAIR_VALUE = 10000
    HISTORY_LENGTH = 12

    def run(self, state: TradingState):
        trader_state = self._load_state(state.traderData)
        orders_by_product: Dict[str, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            fair_value = self._estimate_fair_value(product, order_depth, trader_state)
            orders = self._build_orders(product, order_depth, fair_value, position)
            orders_by_product[product] = orders

        trader_data = json.dumps(trader_state, separators=(",", ":"))
        conversions = 0
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
            del history[:-self.HISTORY_LENGTH]

        if history:
            return round(sum(history) / len(history))

        return 5000

    def _mid_price(self, order_depth: OrderDepth):
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None

        best_bid = max(order_depth.buy_orders)
        best_ask = min(order_depth.sell_orders)
        return (best_bid + best_ask) / 2

    def _build_orders(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: int,
        position: int,
    ) -> List[Order]:
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

        return orders
