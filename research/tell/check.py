"""Holds the integer test (`tellref.is_arb`) to the truth and to the same test done in floats.

  python3 -I check.py                           the table in README.md, on fresh callbacks from mirror.py
  python3 -I check.py write vectors.json.gz     write the fixed vectors a port is held to
  python3 -I check.py verify vectors.json.gz    recompute every vector's answer with tellref.py

A vector is [is_buy, amount_x, amount_y, reserve_x, reserve_y, prev_reserve_x, prev_reserve_y, bid_fee,
ask_fee, arb, first, expected]: nine inputs as decimal strings (they pass 2**53), the truth, whether it
was the pool's first trade of its step, and what `tellref.is_arb` answers.  A port passes when it gives
`expected` on every vector.
"""
import gzip, json, math, os, sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mirror, tellref


def is_arb_float(is_buy, ax_w, ay_w, rx_w, ry_w, prev_rx_w, prev_ry_w, bid_w, ask_w):
    """The same test with the machine's own doubles, written the short way."""
    def ulp_of(reserve_w):
        v = reserve_w / 1e18
        near = [c for c in (math.nextafter(v, 0.0), v, math.nextafter(v, math.inf)) if int(c * 1e18) == reserve_w]
        return min(math.ulp(c) for c in near)
    if is_buy:
        gamma = 1.0 - float(bid_w) / 1e18; paid_w = ax_w; grid = min(ulp_of(prev_rx_w), ulp_of(rx_w))
    else:
        gamma = 1.0 - float(ask_w) / 1e18; paid_w = ay_w; grid = min(ulp_of(prev_ry_w), ulp_of(ry_w))
    n0 = round(Fraction(paid_w, 10**18) * Fraction(gamma) / Fraction(grid))
    return any(n > 0 and int(((n * grid) / gamma) * 1e18) == paid_w for n in (n0 - 1, n0, n0 + 1))


# (label, seeds, steps, callbacks() options): the engine's own range first, then the edges
SETTINGS = [
    ("fees any wei, submission first", range(100, 106), 10000, {}),
    ("fees any wei, submission second", range(100, 106), 10000, {"submission_first": False}),
    ("fees whole bps", range(200, 206), 10000, {"fee_style": "bps"}),
    ("fees up to the 10% cap", range(300, 306), 10000, {"fee_style": "wide"}),
    ("price from 30, ten times the moves", range(400, 403), 10000, {"p0": 30.0, "sigma": 0.0095}),
    ("price from 400, ten times the moves", range(500, 503), 10000, {"p0": 400.0, "sigma": 0.0095}),
]


def tally(records):
    t = {"n": 0, "arbs": 0, "arbs_read": 0, "retail": 0, "retail_read": 0, "firsts": 0, "firsts_wrong": 0, "disagree": 0}
    for rec in records:
        got = tellref.is_arb(*rec[:9])
        t["n"] += 1
        t["disagree"] += got != is_arb_float(*rec[:9])
        if rec[9]: t["arbs"] += 1; t["arbs_read"] += got
        else: t["retail"] += 1; t["retail_read"] += got
        if rec[10]: t["firsts"] += 1; t["firsts_wrong"] += got != rec[9]
    return t


def table():
    total = None
    print(f"{'setting':38} {'arbitrage read':>18} {'retail read as arb':>22} {'first trades misread':>24}")
    for label, seeds, steps, options in SETTINGS:
        t = tally(rec for seed in seeds for rec in mirror.callbacks(seed, steps, **options))
        assert t["disagree"] == 0, f"{label}: the integer test and the float test differ on {t['disagree']} callbacks"
        assert t["arbs_read"] == t["arbs"], f"{label}: {t['arbs'] - t['arbs_read']} arbitrage trades not read"
        print(f"{label:38} {t['arbs_read']:>8} of {t['arbs']:<7} {t['retail_read']:>8} of {t['retail']:<7} {100 * t['retail_read'] / t['retail']:.3f}%"
              f" {t['firsts_wrong']:>8} of {t['firsts']:<7} {100 * t['firsts_wrong'] / t['firsts']:.3f}%")
        total = t if total is None else {k: total[k] + t[k] for k in t}
    print(f"{'all':38} {total['arbs_read']:>8} of {total['arbs']:<7} {total['retail_read']:>8} of {total['retail']:<7} {100 * total['retail_read'] / total['retail']:.3f}%"
          f" {total['firsts_wrong']:>8} of {total['firsts']:<7} {100 * total['firsts_wrong'] / total['firsts']:.3f}%")


def vectors():
    """A fixed set: 3,000 steps of each setting's first seed, every callback."""
    out = []
    for _, seeds, _, options in SETTINGS:
        for rec in mirror.callbacks(seeds[0], 3000, **options):
            out.append([rec[0]] + [str(v) for v in rec[1:9]] + [rec[9], rec[10], tellref.is_arb(*rec[:9])])
    return out


def verify(path):
    rows = json.load(gzip.open(path, "rt"))
    wrong = sum(tellref.is_arb(row[0], *(int(v) for v in row[1:9])) != row[11] for row in rows)
    arbs = [row for row in rows if row[9]]
    print(f"{len(rows)} vectors, {wrong} differ from expected; {sum(row[11] for row in arbs)} of {len(arbs)} arbitrage trades read, "
          f"{sum(row[11] for row in rows if not row[9])} of {len(rows) - len(arbs)} retail trades read as arbitrage")
    return wrong == 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "write":
        rows = vectors()
        with gzip.GzipFile(sys.argv[2], "wb", mtime=0) as f:
            f.write(json.dumps(rows, separators=(",", ":")).encode())
        print(f"wrote {len(rows)} vectors to {sys.argv[2]}")
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        sys.exit(0 if verify(sys.argv[2]) else 1)
    else:
        table()
