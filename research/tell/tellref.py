"""The arbitrage test in whole numbers only, as a contract has to do it.

A contract's afterSwap is handed four integers a trade (amountX, amountY, reserveX, reserveY, each the
engine's f64 times 1e18, truncated) and it knows two more things it can keep itself: the reserves its
previous callback was handed and the fees it returned then.  `is_arb` answers, from those alone, whether
the trade was the arbitrageur's.  No float is used: every step is integer arithmetic a Solidity port can
copy line for line and be held to bit for bit (`vectors.json.gz`, checked by `check.py`).

Why it works is in README.md.  In short: the arbitrageur pays fl(g / gamma), where g is a difference of
two reserve-sized doubles and so sits on the grid of that reserve's last bit; a retail leg's amount is an
arbitrary double, on a grid hundreds of times finer.
"""

WAD = 10**18
BITS = 53


def rn(num, den):
    """The positive rational num/den rounded to a double: (m, e) with value m * 2**e and
    2**52 <= m < 2**53, to nearest, ties to even."""
    assert num > 0 and den > 0
    e = num.bit_length() - den.bit_length() - BITS
    def floor_at(e):
        return (num << -e) // den if e < 0 else num // (den << e)
    q = floor_at(e)
    while q >= (1 << BITS):
        e += 1; q = floor_at(e)
    while q < (1 << (BITS - 1)):
        e -= 1; q = floor_at(e)
    scaled_num, scaled_den = (num << -e, den) if e < 0 else (num, den << e)
    twice = 2 * (scaled_num - q * scaled_den)
    if twice > scaled_den or (twice == scaled_den and (q & 1)):
        q += 1
        if q == (1 << BITS):
            q >>= 1; e += 1
    return q, e


def gamma_of(fee_w):
    """1 - fee as the engine has it: fee = (fee_w as f64) / 1e18, gamma = 1.0 - fee, each rounded.
    Returns (m, e), gamma = m * 2**e."""
    if fee_w == 0:
        return 1 << (BITS - 1), -(BITS - 1)
    m, e = rn(fee_w, 1)                                   # the integer as a double
    num, den = (m << e, WAD) if e >= 0 else (m, WAD << -e)
    m, e = rn(num, den)                                   # divided by 1e18
    assert e < 0
    return rn((1 << -e) - m, 1 << -e)                     # 1.0 minus it


def binade(reserve_w):
    """floor(log2(r)) of the double r behind a reserve's integer: the e with
    2**e * 1e18 <= reserve_w < 2**(e + 1) * 1e18.  1e18 is itself a double, so the edges are exact."""
    def at_least(e):
        return (WAD << e) <= reserve_w if e >= 0 else WAD <= (reserve_w << -e)
    e = reserve_w.bit_length() - WAD.bit_length()
    while not at_least(e): e -= 1
    while at_least(e + 1): e += 1
    return e


def handed(m, e):
    """What a contract is handed for the double m * 2**e: int(fl(v * 1e18))."""
    num, den = (m * WAD << e, 1) if e >= 0 else (m * WAD, 1 << -e)
    pm, pe = rn(num, den)
    return pm << pe if pe >= 0 else pm >> -pe


def is_arb(is_buy, amount_x_w, amount_y_w, reserve_x_w, reserve_y_w, prev_reserve_x_w, prev_reserve_y_w, bid_fee_w, ask_fee_w):
    """True when the amount the trader paid is one the arbitrageur's arithmetic produces.

    is_buy as afterSwap has it: true when the pool bought X.  The fees are the ones in force for the
    trade: what the contract returned from its previous callback, clamped to 10% as the engine clamps."""
    if is_buy:    # the pool bought X: the arbitrageur paid amount_x = (x_virtual - rx) / gamma_bid
        paid_w, fee_w, before_w, after_w = amount_x_w, bid_fee_w, prev_reserve_x_w, reserve_x_w
    else:         # the pool sold X: the arbitrageur paid total_y = (new_ry - ry) / gamma_ask
        paid_w, fee_w, before_w, after_w = amount_y_w, ask_fee_w, prev_reserve_y_w, reserve_y_w
    gm, ge = gamma_of(fee_w)
    grid = min(binade(before_w), binade(after_w)) - (BITS - 1)         # the grid is 2**grid
    # n0 = round(paid * gamma / 2**grid), paid = paid_w / 1e18
    num, den = paid_w * gm, WAD
    shift = ge - grid
    if shift >= 0: num <<= shift
    else: den <<= -shift
    n0 = (2 * num + den) // (2 * den)
    for n in (n0 - 1, n0, n0 + 1):
        if n <= 0: continue
        # v = fl((n * 2**grid) / gamma)
        s = grid - ge
        vm, ve = rn(n << s, gm) if s >= 0 else rn(n, gm << -s)
        if handed(vm, ve) == paid_w:
            return True
    return False
