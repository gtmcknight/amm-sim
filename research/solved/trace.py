"""Print a stretch of own trades with the truth beside what the lattice policy believed.
usage: python3 -I trace.py [seed] [first_row] [rows]"""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import replica2 as R, latt
from evalpol import load


class Tr:
    wants_j = True
    def __init__(self, inner): self.q = inner; self.out = []
    def init(self, *a): return self.q.init()
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        q = self.q; s = y / x; dt = t - q.tlast; lp = math.log(p)
        lo = math.log(q.sp * (1.0 - q.fb)); hi = math.log(q.sp / (1.0 - q.fa))
        pre = (t, dt, 'ARB' if arb else 'ret', 'sell' if is_buy else 'buy ', (lo - lp) * 1e4, (hi - lp) * 1e4, (lo - q.m) * 1e4, (hi - q.m) * 1e4,
               (q.m - lp) * 1e4, math.sqrt(q.v) * 1e4, abs(math.log(s / q.sp)) * 1e4)
        o = q.on_trade(is_buy, ax, ay, t, x, y)
        miss = 'MISS' if (q.first and bool(q.is_arb) != bool(arb)) else ''
        self.out.append(pre + ((q.m - lp) * 1e4, math.sqrt(q.v) * 1e4, miss, (math.log(q.s2h) - math.log(s2)) * 1e4, (math.log(s) - lp) * 1e4, q.fb * 1e4, q.fa * 1e4))
        return o


if __name__ == '__main__':
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 10007
    r0 = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 70
    pol = Tr(latt.LatticePolicy(load(os.path.join(HERE, 'pol_mid.json')), {'qm': os.path.join(HERE, 'qm_k1e-5.json')}))
    print('edge', R.run(seed, pol)['edge'])
    print('    t dt type side | true quotes bid/ask rel p | believed bid/ask rel est | est err, sd before | move | est err, sd after | rival err | w true | new fees bid/ask   (bps)')
    for row in pol.out[r0:r0 + n]:
        t, dt, ty, sd, lo_t, hi_t, lo_b, hi_b, e0, s0, d, e1, s1, miss, re, w, fb, fa = row
        print(f'{t:5d} {dt:2d} {ty} {sd} | {lo_t:6.1f} {hi_t:6.1f} | {lo_b:6.1f} {hi_b:6.1f} | {e0:6.1f} {s0:5.1f} | {d:5.1f} | {e1:6.1f} {s1:5.1f} {miss:4s} | {re:5.1f} | {w:6.1f} | {fb:5.1f} {fa:5.1f}')
