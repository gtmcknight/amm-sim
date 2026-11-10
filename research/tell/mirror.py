"""The engine's trade arithmetic, operation for operation, and a market that yields labelled callbacks.

Mirrors amm_sim_rs at 6b6921f8 (amm/cfmm.rs, market/arbitrageur.rs, market/router.rs, types/wad.rs): two
constant-product pools, an arbitrageur that trades each to the fair price net of fee, a router that
splits retail orders across them.  Python floats are IEEE doubles, as Rust f64, and every expression
keeps the source's order of operations, because the last bit is the point.  The price path and the
order flow are NOT the engine's (other random streams, a simpler arrival law): this is for the
arithmetic of a single trade, never for scores.  Scores come from the replica (`../solved`) and the engine.
"""
import math, random

WAD = 10**18
def to_wad(v): return int(v * 1e18)                     # Wad::from_f64: (value * 1e18) as i128
def fee_f64(w): return float(w) / 1e18                  # Wad::to_f64

class Pool:
    def __init__(self, rx, ry, bid_w, ask_w):
        self.rx, self.ry, self.bid_w, self.ask_w = rx, ry, bid_w, ask_w
    # --- cfmm.rs
    def quote_buy_x(self, amount_x):
        if amount_x <= 0.0: return (0.0, 0.0)
        fee = fee_f64(self.bid_w); gamma = min(max(1.0 - fee, 0.0), 1.0)
        net_x = amount_x * gamma
        k = self.rx * self.ry
        new_rx = self.rx + net_x
        new_ry = k / new_rx
        y_out = self.ry - new_ry
        return (y_out, amount_x * fee) if y_out > 0.0 else (0.0, 0.0)
    def quote_sell_x(self, amount_x):
        if amount_x <= 0.0 or amount_x >= self.rx: return (0.0, 0.0)
        k = self.rx * self.ry
        fee = fee_f64(self.ask_w); gamma = min(max(1.0 - fee, 0.0), 1.0)
        new_rx = self.rx - amount_x
        new_ry = k / new_rx
        net_y = new_ry - self.ry
        if net_y <= 0.0: return (0.0, 0.0)
        total_y = net_y / gamma
        return (total_y, total_y - net_y)
    def quote_x_for_y(self, amount_y):
        if amount_y <= 0.0: return (0.0, 0.0)
        k = self.rx * self.ry
        fee = fee_f64(self.ask_w); gamma = min(max(1.0 - fee, 0.0), 1.0)
        net_y = amount_y * gamma
        new_ry = self.ry + net_y
        new_rx = k / new_ry
        x_out = self.rx - new_rx
        return (x_out, amount_y * fee) if x_out > 0.0 else (0.0, 0.0)
    def execute_buy_x(self, amount_x):
        y_out, fee_amount = self.quote_buy_x(amount_x)
        if y_out <= 0.0: return None
        net_x = amount_x - fee_amount
        self.rx += net_x; self.ry -= y_out
        return (True, to_wad(amount_x), to_wad(y_out), to_wad(self.rx), to_wad(self.ry))
    def execute_sell_x(self, amount_x):
        total_y, fee_amount = self.quote_sell_x(amount_x)
        if total_y <= 0.0: return None
        net_y = total_y - fee_amount
        self.rx -= amount_x; self.ry += net_y
        return (False, to_wad(amount_x), to_wad(total_y), to_wad(self.rx), to_wad(self.ry))
    def execute_buy_x_with_y(self, amount_y):
        x_out, fee_amount = self.quote_x_for_y(amount_y)
        if x_out <= 0.0: return None
        net_y = amount_y - fee_amount
        self.rx -= x_out; self.ry += net_y
        return (False, to_wad(x_out), to_wad(amount_y), to_wad(self.rx), to_wad(self.ry))

# --- arbitrageur.rs
def arb(pool, p):
    spot = pool.ry / pool.rx
    if spot < p:
        k = pool.rx * pool.ry
        gamma = 1.0 - fee_f64(pool.ask_w)
        if gamma <= 0.0 or p <= 0.0: return None
        new_x = math.sqrt(k / (gamma * p))
        amount_x = pool.rx - new_x
        if amount_x <= 0.0: return None
        amount_x = min(amount_x, pool.rx * 0.99)
        total_y, _ = pool.quote_sell_x(amount_x)
        if total_y <= 0.0: return None
        if amount_x * p - total_y <= 0.0: return None
        return pool.execute_sell_x(amount_x)
    if spot > p:
        k = pool.rx * pool.ry
        gamma = 1.0 - fee_f64(pool.bid_w)
        if gamma <= 0.0 or p <= 0.0: return None
        x_virtual = math.sqrt(k * gamma / p)
        net_x = x_virtual - pool.rx
        amount_x = net_x / gamma
        if amount_x <= 0.0: return None
        y_out, _ = pool.quote_buy_x(amount_x)
        if y_out <= 0.0: return None
        if y_out - amount_x * p <= 0.0: return None
        return pool.execute_buy_x(amount_x)
    return None

# --- router.rs (two pools)
MIN_AMOUNT = 0.0001
def split_buy(a1, a2, total_y):
    g1 = 1.0 - fee_f64(a1.ask_w); g2 = 1.0 - fee_f64(a2.ask_w)
    A1 = math.sqrt(a1.rx * g1 * a1.ry); A2 = math.sqrt(a2.rx * g2 * a2.ry)
    if A2 == 0.0: return (total_y, 0.0)
    r = A1 / A2
    num = r * (a2.ry + g2 * total_y) - a1.ry
    den = g1 + r * g2
    y1 = total_y / 2.0 if den == 0.0 else num / den
    y1 = min(max(y1, 0.0), total_y)
    return (y1, total_y - y1)
def split_sell(a1, a2, total_x):
    g1 = 1.0 - fee_f64(a1.bid_w); g2 = 1.0 - fee_f64(a2.bid_w)
    B1 = math.sqrt(a1.ry * g1 * a1.rx); B2 = math.sqrt(a2.ry * g2 * a2.rx)
    if B2 == 0.0: return (total_x, 0.0)
    r = B1 / B2
    num = r * (a2.rx + g2 * total_x) - a1.rx
    den = g1 + r * g2
    x1 = total_x / 2.0 if den == 0.0 else num / den
    x1 = min(max(x1, 0.0), total_x)
    return (x1, total_x - x1)
def route(order_side, size, a1, a2, p):
    out = [None, None]
    if order_side == "buy":
        y1, y2 = split_buy(a1, a2, size)
        if y1 > MIN_AMOUNT: out[0] = a1.execute_buy_x_with_y(y1)
        if y2 > MIN_AMOUNT: out[1] = a2.execute_buy_x_with_y(y2)
    else:
        total_x = size / p
        x1, x2 = split_sell(a1, a2, total_x)
        if x1 > MIN_AMOUNT: out[0] = a1.execute_buy_x(x1)
        if x2 > MIN_AMOUNT: out[1] = a2.execute_buy_x(x2)
    return out

# --- a market around them: every callback of the submission's pool, with the truth
FEE_STYLES = ("wei", "bps", "wide")

def callbacks(seed, steps, submission_first=True, fee_style="wei", sigma=0.00095, p0=100.0):
    """Yields one record a callback of the submission's pool:
    (is_buy, amount_x, amount_y, reserve_x, reserve_y, prev_reserve_x, prev_reserve_y, bid_fee, ask_fee, arb, first)
    the first nine as the integers a contract is handed or keeps, then whether the trade was the
    arbitrageur's and whether it was the pool's first trade of its step.  The submission returns new
    fees after every callback: any whole number of wei ("wei"), whole bps ("bps"), or up to the 10% cap ("wide")."""
    rng = random.Random(seed)
    def fees():
        if fee_style == "bps": return (rng.randint(1, 120) * 10**14, rng.randint(1, 120) * 10**14)
        if fee_style == "wide": return (rng.randint(0, 10**17), rng.randint(0, 10**17))
        return (rng.randint(10**14, 120 * 10**14), rng.randint(10**14, 120 * 10**14))
    bid, ask = fees()
    own = Pool(100.0, 10000.0, bid, ask)
    rival = Pool(100.0, 10000.0, 30 * 10**14, 30 * 10**14)
    p = p0
    if p0 != 100.0:                      # start both pools at the fair price, as the engine does
        own.rx = rival.rx = math.sqrt(1e6 / p0); own.ry = rival.ry = 1e6 / own.rx
    prev = (to_wad(own.rx), to_wad(own.ry))
    for _ in range(steps):
        p *= math.exp(rng.gauss(0.0, sigma))
        first = True
        pools = (own, rival) if submission_first else (rival, own)
        for pool in pools:
            trade = arb(pool, p)
            if pool is own and trade:
                yield trade + prev + (own.bid_w, own.ask_w, True, first)
                prev = (trade[3], trade[4]); first = False
                own.bid_w, own.ask_w = fees()
        n = 0
        while rng.random() < 0.8 / (1 + n) and n < 6:
            n += 1
            size = rng.lognormvariate(math.log(20.0) - 0.72, 1.2)
            side = "buy" if rng.random() < 0.5 else "sell"
            legs = route(side, size, pools[0], pools[1], p)
            trade = legs[0] if pools[0] is own else legs[1]
            if trade:
                yield trade + prev + (own.bid_w, own.ask_w, False, first)
                prev = (trade[3], trade[4]); first = False
                own.bid_w, own.ask_w = fees()
