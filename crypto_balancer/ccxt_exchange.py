from typing import Dict, List, Optional, Union
import ccxt

from functools import lru_cache, reduce

from crypto_balancer.order import Order

exchanges = ccxt.exchanges


class CCXTExchange():

    def __init__(self, name, api_key, api_secret, do_cancel_orders=True):
        self.name = name
        self.exch = getattr(ccxt, name)(
            {'nonce': ccxt.Exchange.milliseconds, 'defaultType': 'spot'})
        self.exch.options['defaultType'] = 'spot'
        self.exch.apiKey = api_key
        self.exch.secret = api_secret
        self.exch.requests_trust_env = True
        self.do_cancel_orders = do_cancel_orders
        self.exch.load_markets()
        self.tickers = self.exch.fetch_tickers()
        self.rates = self.get_rates()
        self.free_balances = self.get_free_balances
        self.markets = self.exch.markets
        # self.cancel_orders

    @property
    @lru_cache(maxsize=None)
    def get_free_balances(self):
        # gets free balances
        # If we cancel orders, we will use this to accurately get total free to trade
        balance_info = self.exch.fetch_balance()['info']['balances']
        return {holding['asset']: holding['free'] for holding in balance_info if float(holding['free']) != 0}

    @property
    @lru_cache(maxsize=None)
    def get_locked_balances(self):
        # gets locked balances
        balance_info = self.exch.fetch_balance()['info']['balances']
        return {holding['asset']: holding['locked'] for holding in balance_info if float(holding['locked']) != 0}

    @lru_cache(maxsize=None)
    def get_total_balances(self):
        # we need all coin balances to accurately calculate portfolio total
        # note: this does not mean total available to trade
        total_balance = self.exch.fetch_balance()['total']
        return {total_balance[base] for base in total_balance.keys() if total_balance[base] != 0}

    def get_portfolio_total(self, destination_code: str, mode: str) -> Dict[str, Union[float, Dict[str, float]]]:
        codes = {}
        balance = self.exch.fetch_balance()
        total_destination_value = 0
        for code, quantity in balance['total'].items():
            if code == destination_code or quantity == 0:
                total_destination_value += quantity
                codes[code] = quantity
            else:
                routes = self.get_smart_route(code, destination_code)
                if routes:
                    value = self.convert_route_to_cost(quantity, routes, mode)
                    total_destination_value += value
                    codes[code] = value
        return {"total": total_destination_value, "codes": codes}

    def convert_route_to_cost(self, init_quantity: float, routes: List[Dict[str, Union[str, bool]]], mode: str) -> float:
        init_cost = self.get_rate(routes[0]['symbol'])[mode]
        init_value = (init_quantity * (1 / init_cost)
                      ) if routes[0]["direction"] == 'buy' else (init_quantity * init_cost)
        if init_value == 0:
            return 0
        if len(routes) > 1:
            dest_ticker_price = self.get_rate(routes[1]['symbol'])[mode]
            if routes[1]["direction"] == 'buy':
                cost = init_value / dest_ticker_price
            else:
                cost = init_value * dest_ticker_price
            return cost
        else:
            return init_value

    @property
    @lru_cache(maxsize=None)
    def get_held_assets(self):
        total_balance = self.exch.fetch_balance()['total']
        return [base for base in total_balance.keys() if total_balance[base] != 0]

    @property
    @lru_cache(maxsize=None)
    def get_trade_fees(self, symbol: str, type: str, side: str, amount: float, price: float):
        return self.exch.calculate_fee(symbol=symbol, type=type,
                                       side=side, amount=amount, price=price)

    def get_specific_pairs(self, pairs):
        active_pairs = []
        for i in pairs:
            for j in pairs:
                pair = self.format_symbol(i, j)
                if pair in self.exch.markets.keys() and self.exch.markets[pair]['active']:
                    active_pairs.append(pair)
        return active_pairs

    def get_all_held_symbols(self):
        symbols = self.get_held_assets
        active_symbols = []
        for i in symbols:
            for j in symbols:
                symbol = self.format_symbol(i, j)
                if symbol in self.exch.markets.keys() and self.exch.markets[symbol]['active']:
                    active_symbols.append(symbol)
        return active_symbols

    def get_smart_route(self, starting_code: str, destination_code: str) -> Optional[List[Dict[str, Union[str, bool]]]]:
        # will return ordered pairs that we will need to sell to get to our destination
        sell_symbol = self.format_symbol(starting_code, destination_code)
        buy_symbol = self.format_symbol(destination_code, starting_code)
        grouped_symbols = {}
        symbols = [symbol for symbol in self.exch.markets.values()
                   if symbol['active']]
        for item in symbols:
            grouped_symbols.setdefault(item['symbol'], []).append(item)

        sell_ticker = grouped_symbols.get(sell_symbol)
        buy_ticker = grouped_symbols.get(buy_symbol)
        if not [symbol for symbol in symbols if symbol['base'] == starting_code] and not sell_ticker and not buy_ticker:
            return None
        elif buy_ticker:
            return [{"direction": "buy", "symbol": buy_symbol}]
        elif sell_ticker:
            return [{"direction": "sell", "symbol": sell_symbol}]
        else:
            quote_routes = [symbol['quote']
                            for symbol in symbols if symbol['base'] == starting_code]
            trade_options = [symbol for symbol in symbols if (symbol["quote"] == destination_code or symbol["base"] == destination_code) and (
                symbol["quote"] in quote_routes or symbol["base"] in quote_routes)]
            is_buy = trade_options[0]['base'] == destination_code
            return self.build_trade_routes(starting_code, trade_options[0], is_buy, quote_routes)

    def build_trade_routes(self, starting_code: str, route_to_destination: dict[str, str], is_buy: bool, quote_routes: List[str]) -> List[Dict[str, Union[str, bool]]]:
        base, quote = (route_to_destination["base"], route_to_destination["quote"]) if route_to_destination["quote"] in quote_routes else (
            route_to_destination["quote"], route_to_destination["base"])
        routes = [{'symbol': self.format_symbol(
            starting_code, quote), 'direction': 'sell'}]
        if is_buy:
            routes.append({'symbol': self.format_symbol(
                base, quote), 'direction': 'buy'})
        else:
            routes.append({'symbol': self.format_symbol(
                quote, base), 'direction': 'sell'})
        return routes

    @staticmethod
    def format_symbol(base: str, quote: str) -> str:
        return "{}/{}".format(base, quote)

    @lru_cache(maxsize=None)
    def get_rates(self) -> Dict[str, Dict[str, float]]:
        rates = {}
        tickers = self.tickers
        for pair in tickers:
            ticker = tickers[pair]
            if 'ask' in ticker and 'bid' in ticker:
                high = ticker['ask']
                low = ticker['bid']
            else:
                orderbook = self.exch.fetchOrderBook(pair)
                high = orderbook['asks'][0][0]
                low = orderbook['bids'][0][0]
            mid = (high + low) / 2.0
            rates[pair] = {'mid': mid, 'high': high, 'low': low}

        return rates

    def get_rate(self, symbol: str) -> dict[str, float]:
        ticker = self.tickers[symbol]
        if 'ask' in ticker and 'bid' in ticker:
            high = ticker['ask']
            low = ticker['bid']
        else:
            orderbook = self.exch.fetchOrderBook(symbol)
            high = orderbook['asks'][0][0]
            low = orderbook['bids'][0][0]
        mid = (high + low) / 2.0
        return {'mid': mid, 'high': high, 'low': low}

    def get_lowest_fee_option(self, options: list[dict]):
        pass

    @lru_cache(maxsize=None)
    def get_limit(self, pair: str):
        return self.markets[pair]['limits']

    @property
    @lru_cache(maxsize=None)
    def fee(self):
        return self.exch.fees['trading']['maker']

    def preprocess_order(self, order: Order) -> Optional[Order]:
        try:
            limits = self.limits[order.pair]
        except KeyError:
            return None

        order.amount = float(
            self.exch.amount_to_precision(order.pair, order.amount))
        order.price = float(
            self.exch.price_to_precision(order.pair, order.price))

        if order.price == 0 or order.amount == 0:
            return None

        if order.amount < limits['amount']['min'] or order.amount * order.price < limits['cost']['min']:
            return None

        order.type_ = 'LIMIT'
        return order if order.amount >= limits['amount']['min'] else None

    def check_limits(self, starting_code: str, destination_code: str, weight: float, mode: str, total: float) -> bool:
        trade_routes = self.get_smart_route(starting_code, destination_code)
        symbol = trade_routes[-1]["symbol"] if trade_routes else ""
        limit = self.get_limit(symbol)
        price = self.get_rate(symbol)[mode]
        return not ((total * weight) / price < limit['amount']['min'] or abs(weight * total) < limit['cost']['min'])

    def execute_order(self, order):
        if not order.type_:
            raise ValueError("Order needs preprocessing first")
        return self.exch.create_order(order.pair,
                                      order.type_,
                                      order.direction,
                                      order.amount,
                                      order.price)

    def cancel_orders(self):
        if self.cancel_orders:
            cancelled_orders = []
            for pair in self.pairs:
                open_orders = self.exch.fetch_open_orders(symbol=pair)
                for order in open_orders:
                    self.exch.cancel_order(order['id'], order['symbol'])
                    cancelled_orders.append(order)
            return cancelled_orders

    def get_portfolio_balance() -> float:
        return 0.0
