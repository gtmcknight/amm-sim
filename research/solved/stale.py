"""How stale is the last arb pin when retail hits, under the solved perfect-information policy?"""
import sys, os, math, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from par import pmap
import replica2 as R
from evalpol import DPPolicy, load

class Probe(DPPolicy):
    def __init__(self, T):
        DPPolicy.__init__(self, T); self.tpin = -1; self.ppin = 100.0; self.tl = -1
        self.hist = {}; self.sq = {}; self.narb = 0; self.nret = 0; self.first_ret = 0; self.vol = {}
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        if arb:
            self.tpin = t; self.ppin = p; self.narb += 1
        else:
            k = min(t - self.tpin, 6); self.nret += 1
            e = math.log(p / self.ppin) * 1e4
            self.hist[k] = self.hist.get(k, 0) + 1; self.sq[k] = self.sq.get(k, 0.0) + e * e
            self.vol[k] = self.vol.get(k, 0.0) + ay
        self.tl = t
        return DPPolicy.on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j)

def ev(seeds):
    T = load(sys.argv[1]); H = {}; S = {}; V = {}; na = nr = 0
    for s in seeds:
        pol = Probe(T); R.run(s, pol)
        for k, v in pol.hist.items(): H[k] = H.get(k, 0) + v
        for k, v in pol.sq.items(): S[k] = S.get(k, 0) + v
        for k, v in pol.vol.items(): V[k] = V.get(k, 0) + v
        na += pol.narb; nr += pol.nret
    return H, S, V, na, nr

if __name__ == '__main__':
    seeds = list(range(10000, 10280))
    res = pmap(ev, [seeds[i:i+20] for i in range(0, len(seeds), 20)])
    H = {}; S = {}; V = {}; na = nr = 0
    for h, s, v, a, r in res:
        for k in h: H[k] = H.get(k, 0) + h[k]; S[k] = S.get(k, 0) + s[k]; V[k] = V.get(k, 0) + v[k]
        na += a; nr += r
    n = len(seeds); tot = sum(H.values()); tv = sum(V.values())
    print(f'per run: arb trades {na/n:.0f}, retail trades on us {nr/n:.0f}')
    print('steps since last pin | share of retail trades | share of retail volume | rms price move since pin (bps)')
    for k in sorted(H):
        print(f'  {k}{"+" if k==6 else " "}  {H[k]/tot:6.1%}  {V[k]/tv:6.1%}  {math.sqrt(S[k]/H[k]):5.1f}')
    print(f'all: rms {math.sqrt(sum(S.values())/tot):.1f} bps')
