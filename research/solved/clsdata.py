"""How separable are arb and retail first trades, given what the filter knows at that moment?"""
import sys, os, math, json
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import replica2 as R, latt, real
from evalpol import load

class D(latt.LatticePolicy):
    def __init__(self, T, opt):
        latt.LatticePolicy.__init__(self, T, opt); self.rows = []
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        s = y / x; dt = t - self.tlast
        if dt >= 1:
            lo = math.log(self.sp * (1.0 - self.fb)); hi = math.log(self.sp / (1.0 - self.fa))
            q = ((self.m - lo) if is_buy else (hi - self.m)) * 1e4          # crossed-side quote offset from belief mean
            qo = ((hi - self.m) if is_buy else (self.m - lo)) * 1e4         # other side's offset
            sd = math.sqrt(self.v + dt * real.SIG2) * 1e4
            d = abs(math.log(s / self.sp)) * 1e4
            # rival quote on the crossed side relative to ours (estimate): >0 means ours is better
            r2 = self.s2h
            if is_buy: adv = (math.log(self.sp * (1 - self.fb)) - math.log(r2 * real.G2)) * 1e4
            else: adv = (math.log(r2 / real.G2) - math.log(self.sp / (1 - self.fa))) * 1e4
            n0 = self.nmis
            out = latt.LatticePolicy.on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j)
            self.rows.append((1 if arb else 0, q, sd, d, dt, adv, qo, 1 if self.nmis > n0 else 0))
            return out
        return latt.LatticePolicy.on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j)

def ev(seeds):
    T = load(os.path.join(HERE, 'pol_mid.json')); rows = []
    for s in seeds:
        pol = D(T, {'qm': os.path.join(HERE, 'qm_k1e-5.json')}); R.run(s, pol); rows += pol.rows
    return rows

if __name__ == '__main__':
    seeds = list(range(50000, 50084))
    with Pool(14) as pool: res = pool.map(ev, [seeds[i:i+6] for i in range(0, len(seeds), 6)])
    rows = [r for b in res for r in b]
    json.dump(rows, open(os.path.join(HERE, 'clsdata.json'), 'w'))
    n = len(rows); print('first trades', n, 'arb share', sum(r[0] for r in rows) / n, 'current misclass', sum(r[7] for r in rows) / n)
    # Bayes error of an empirical table on (q, d, sd) bins, split-half to avoid overfitting
    def binq(v): return max(-8, min(12, int(math.floor(v / 4.0))))
    def bind(v): return min(11, int(math.floor(math.log2(max(v, 0.25)) * 1.5 + 3)))
    def bins(v): return min(5, int(v / 5.0))
    def bina(v): return max(-3, min(3, int(math.floor(v / 15.0))))
    for name, key in (('q only', lambda r: (binq(r[1]),)), ('q,sd', lambda r: (binq(r[1]), bins(r[2]))), ('q,sd,d', lambda r: (binq(r[1]), bins(r[2]), bind(r[3]))),
                      ('q,sd,d,adv', lambda r: (binq(r[1]), bins(r[2]), bind(r[3]), bina(r[5]))), ('q,sd,d,adv,qo', lambda r: (binq(r[1]), bins(r[2]), bind(r[3]), bina(r[5]), binq(r[6])))):
        tr = rows[::2]; te = rows[1::2]; tab = {}
        for r in tr:
            k = key(r); c = tab.setdefault(k, [0, 0]); c[r[0]] += 1
        err = 0
        for r in te:
            c = tab.get(key(r), [1, 1]); pred = 1 if c[1] > c[0] else 0
            err += pred != r[0]
        print(f'empirical table on {name:16s}: held-out error {err/len(te):.2%}')
    # error by crossed-quote offset
    print('crossed-quote offset bin (bps) | share | arb share | current error')
    for b in range(-8, 13):
        q = [r for r in rows if binq(r[1]) == b]
        if len(q) > 200: print(f'  {b*4:4d}..{b*4+4:<4d} {len(q)/n:6.1%}  {sum(r[0] for r in q)/len(q):5.1%}  {sum(r[7] for r in q)/len(q):5.1%}')
