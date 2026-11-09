"""How separable are arb and retail first trades, given what the lattice filter knows at that moment?
Writes clsdata.json (one row per first trade) and prints the misread rate by where the crossed quote sat.
usage: python3 -I clsdata.py [seed0] [n]"""
import sys, os, math, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from par import pmap
import replica2 as R, latt, real
from evalpol import load


class D:
    wants_j = True
    def __init__(self, inner): self.q = inner; self.rows = []
    def init(self, *a): return self.q.init()
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        q = self.q; s = y / x; dt = t - q.tlast
        if dt < 1: return q.on_trade(is_buy, ax, ay, t, x, y)
        lo = math.log(q.sp * (1.0 - q.fb)); hi = math.log(q.sp / (1.0 - q.fa))
        off = ((q.m - lo) if is_buy else (hi - q.m)) * 1e4           # crossed-side quote offset from the belief mean
        other = ((hi - q.m) if is_buy else (q.m - lo)) * 1e4
        sd = math.sqrt(q.v + dt * real.SIG2) * 1e4
        d = abs(math.log(s / q.sp)) * 1e4
        if is_buy: adv = (math.log(q.sp * (1 - q.fb)) - math.log(q.s2h * real.G2)) * 1e4     # >0: our quote beat the rival's (estimate)
        else: adv = (math.log(q.s2h / real.G2) - math.log(q.sp / (1 - q.fa))) * 1e4
        out = q.on_trade(is_buy, ax, ay, t, x, y)
        self.rows.append((1 if arb else 0, off, sd, d, dt, adv, other, 1 if bool(q.is_arb) != bool(arb) else 0))
        return out


def ev(seeds):
    T = load(os.path.join(HERE, 'pol_mid.json')); rows = []
    for s in seeds:
        pol = D(latt.LatticePolicy(T, {'qm': os.path.join(HERE, 'qm_k1e-5.json')})); R.run(s, pol); rows += pol.rows
    return rows


if __name__ == '__main__':
    s0 = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 84
    seeds = list(range(s0, s0 + n))
    res = pmap(ev, [seeds[i:i + 6] for i in range(0, len(seeds), 6)])
    rows = [r for b in res for r in b]
    json.dump(rows, open(os.path.join(HERE, 'clsdata.json'), 'w'))
    m = len(rows); print('first trades', m, 'arb share %.3f' % (sum(r[0] for r in rows) / m), 'misread %.4f' % (sum(r[7] for r in rows) / m))
    print('crossed-quote offset (bps) | share | arb share | misread')
    for b in range(-8, 13):
        q = [r for r in rows if max(-8, min(12, int(math.floor(r[1] / 4.0)))) == b]
        if len(q) > 200: print(f'  {b*4:4d}..{b*4+4:<4d} {len(q)/m:6.1%}  {sum(r[0] for r in q)/len(q):5.1%}  {sum(r[7] for r in q)/len(q):5.1%}')
