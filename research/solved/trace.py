import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import replica2 as R, latt, real
from evalpol import load

class Tr(latt.LatticePolicy):
    def __init__(self, T, opt):
        latt.LatticePolicy.__init__(self, T, opt); self.out = []
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        s = y / x; dt = t - self.tlast
        lo = math.log(self.sp * (1.0 - self.fb)); hi = math.log(self.sp / (1.0 - self.fa))
        lp = math.log(p)
        pre = (t, dt, 'ARB' if arb else 'ret', 'sell' if is_buy else 'buy ', (lo - lp) * 1e4, (hi - lp) * 1e4, (lo - self.m) * 1e4, (hi - self.m) * 1e4,
               (self.m - lp) * 1e4, math.sqrt(self.v) * 1e4, abs(math.log(s / self.sp)) * 1e4)
        n0 = self.nmis
        o = latt.LatticePolicy.on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j)
        self.out.append(pre + ((self.m - lp) * 1e4, math.sqrt(self.v) * 1e4, 'MISS' if self.nmis > n0 else '', (math.log(self.s2h) - math.log(s2)) * 1e4,
                               (math.log(s) - lp) * 1e4, self.fb * 1e4, self.fa * 1e4))
        return o

T = load(os.path.join(HERE, 'pol_mid.json'))
pol = Tr(T, {'qm': os.path.join(HERE, 'qm_k1e-5.json')})
r = R.run(10007, pol)
print('edge', r['edge'])
print('    t dt type side | true quotes bid/ask rel p | believed bid/ask rel est | est err, sd before | move | est err, sd after | rival err | w true | new fees bid/ask')
for row in pol.out[3000:3070]:
    t, dt, ty, sd, lo_t, hi_t, lo_b, hi_b, e0, s0, d, e1, s1, miss, re, w, fb, fa = row
    print(f'{t:5d} {dt:2d} {ty} {sd} | {lo_t:6.1f} {hi_t:6.1f} | {lo_b:6.1f} {hi_b:6.1f} | {e0:6.1f} {s0:5.1f} | {d:5.1f} | {e1:6.1f} {s1:5.1f} {miss:4s} | {re:5.1f} | {w:6.1f} | {fb:5.1f} {fa:5.1f}')
