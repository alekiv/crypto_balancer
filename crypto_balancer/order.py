class Order():
    def __init__(self, pair, direction, amount, price, total_in_quote = None):
        if direction.upper() not in ['BUY', 'SELL']:
            raise ValueError("{} is not a valid direction".format(direction))
        self.pair = pair
        self.direction = direction
        self.amount = float(amount)
        self.price = float(price)
        self.type_ = None
        self.total_in_quote = float(amount) * float(price)

    def __str__(self):
        return f"{self.direction} {self.amount} {self.pair} @ {self.price}"

    def __repr__(self):
        return f"Order('{self.pair}', '{self.direction}', {self.amount}, {self.price}, {self.total_in_quote})"

    def __eq__(self, other):
        return self.pair == other.pair and \
            self.direction == other.direction and \
            self.amount == other.amount and \
            self.price == other.price

    def __lt__(self, other):
        return (self.pair, self.direction, self.amount, self.price, self.total_in_quote) < \
            (other.pair, other.direction, other.amount, other.price, other.total_in_quote)

    def __hash__(self):
        return hash((self.pair, self.direction, self.amount, self.price))

