"""Smallest policy run.py accepts: a fixed 30 bps fee. Copy it, keep the two methods, add your own state.
    python3 -I run.py example_policy:Fixed30 60000 64 out.json
"""


class Fixed30:
    def __init__(self, T, opt):
        self.fee = float(opt.get('fee', 0.003))     # T is the table file (unused here), opt the key=val pairs
    def init(self):
        return self.fee, self.fee                    # (bid_fee, ask_fee) as fractions
    def on_trade(self, is_buy, amount_x, amount_y, timestamp, reserve_x, reserve_y):
        # is_buy: the pool bought X (the trader sold). reserves are after the trade.
        return self.fee, self.fee
