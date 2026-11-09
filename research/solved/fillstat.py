"""Calibrate the arb-vs-retail classifier: size of the first trade of a step, by true type, under the solved policy."""
import sys, os, math, json
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import replica2 as R
from evalpol import DPPolicy, load

class Probe(DPPolicy):
    def __init__(self, T):
        DPPolicy.__init__(self, T); self.tl = -1; self.sp = 100.0; self.rows = []
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        s = y / x
        if t > self.tl:
            self.rows.append((1 if arb else 0, abs(math.log(s / self.sp)) * 1e4, t - self.tl))
        self.tl = t; self.sp = s
        return DPPolicy.on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j)

def ev(seeds):
    T = load(sys.argv[1]); rows = []
    for s in seeds:
        pol = Probe(T); R.run(s, pol); rows += pol.rows
    return rows

if __name__ == '__main__':
    seeds = list(range(40000, 40112))
    with Pool(14) as pool: res = pool.map(ev, [seeds[i:i+8] for i in range(0, len(seeds), 8)])
    rows = [r for b in res for r in b]
    arb = [r for r in rows if r[0]]; ret = [r for r in rows if not r[0]]
    n = len(seeds)
    print(f'first trades of a step per run: arb {len(arb)/n:.0f} retail {len(ret)/n:.0f}')
    for name, rr in (('arb', arb), ('retail', ret)):
        d = sorted(r[1] for r in rr); L = [math.log(max(v, 1e-6)) for v in d]
        m = sum(L) / len(L); sd = (sum((v - m) ** 2 for v in L) / len(L)) ** 0.5
        q = lambda f: d[int(f * (len(d) - 1))]
        print(f'{name:6s} spot move bps: p10 {q(.1):.2f} p25 {q(.25):.2f} p50 {q(.5):.2f} p75 {q(.75):.2f} p90 {q(.9):.2f} p99 {q(.99):.1f}  ln-mean {m:.3f} (median {math.exp(m):.2f}) ln-sd {sd:.3f}')
    # histogram of move size by type, 2.5 bps bins
    print('bin(bps)  arb  retail  P(arb)')
    for lo in [0, 1, 2, 3, 4, 5, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 60]:
        hi = {0:1,1:2,2:3,3:4,4:5,5:7.5,7.5:10,10:12.5,12.5:15,15:20,20:25,25:30,30:40,40:60,60:1e9}[lo]
        a = sum(1 for r in arb if lo <= r[1] < hi); b = sum(1 for r in ret if lo <= r[1] < hi)
        print(f'{lo:5}-{hi:<6} {a/n:7.1f} {b/n:7.1f}  {a/max(1,a+b):.2f}')
