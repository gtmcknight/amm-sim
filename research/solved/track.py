"""Drive the solved perfect-information policy with REAL observables, one handicap at a time.

modes (comma list):
  pins    fair price known only at own arb trades (pin = post-trade spot through the fee in force); stale in between
  rival   rival spot dead-reckoned: router identity on every own retail trade + band clip against the price estimate
  count   phase from own callback count (hidden rival-only orders unseen)
The true arb/retail flag is used throughout; real.py and latt.py infer it.
usage: python3 -I track.py <pol.json> <modes|none> [more mode sets ...]
"""
import sys, os, math, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from par import pmap
import replica2 as R
from evalpol import DPPolicy, load, stats, CALIB

G2 = 1.0 - R.NF
LNF = -math.log(G2)


class Tracked(DPPolicy):
    wants_j = True
    def __init__(self, T, modes):
        DPPolicy.__init__(self, T)
        self.m = set(modes)
        self.ph = 100.0; self.tpin = -1; self.tlast = -1; self.cnt = 0
        self.s2h = 100.0
        self.fb = self.fa = 0.003
    def init(self, *a):
        fb, fa = self._fees(0.0, 0.0, 0)
        self.fb, self.fa = R.clampf(fb), R.clampf(fa)
        return fb, fa
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        m = self.m
        s = y / x
        first = t > self.tlast
        if first: self.cnt = 0
        # ---- is this trade the arb?
        is_arb = arb
        # ---- price estimate
        if 'pins' in m:
            if is_arb:
                self.ph = s * (1.0 - self.fb) if is_buy else s / (1.0 - self.fa)
                self.tpin = t
            pe = self.ph
        else:
            pe = p
        # ---- rival estimate
        if 'rival' in m:
            lo = pe * G2; hi = pe / G2
            if first:
                if self.s2h < lo: self.s2h = lo
                elif self.s2h > hi: self.s2h = hi
            if not is_arb:
                if is_buy:   # trader sold X; marginal bids equalise when split
                    cand = s * (1.0 - self.fb) / G2
                    if cand < self.s2h: self.s2h = cand
                else:
                    cand = s * G2 / (1.0 - self.fa)
                    if cand > self.s2h: self.s2h = cand
            s2e = self.s2h
        else:
            s2e = s2
        # ---- phase
        if is_arb: phs = 0
        else:
            self.cnt += 1
            jj = self.cnt if 'count' in m else j
            phs = 1 if jj <= 1 else 2
        self.tlast = t
        w = math.log(s / pe) * 1e4; w2 = math.log(s2e / pe) * 1e4
        fb, fa = self._fees(w, w2, phs)
        self.fb, self.fa = R.clampf(fb), R.clampf(fa)
        return fb, fa


def ev(a):
    path, modes, seeds = a
    T = load(path); out = []
    for s in seeds:
        pol = Tracked(T, modes)
        r = R.run(s, pol)
        out.append((s, r['edge'], r['retail'], r['arb'], r['rv'], r['av']))
    return out


if __name__ == '__main__':
    path = sys.argv[1]
    seeds = list(range(10000, 12048)) if not os.environ.get('NSEED') else list(range(10000, 10000 + int(os.environ['NSEED'])))
    rows = json.load(open(CALIB)); ref = {}
    for r in rows: ref.setdefault(r['kind'], {})[r['seed']] = r
    if True:
        for ms in sys.argv[2:]:
            modes = [] if ms == 'none' else ms.split(',')
            t0 = time.time()
            res = pmap(ev, [(path, modes, seeds[i:i + 8]) for i in range(0, len(seeds), 8)])
            res = {r[0]: r for b in res for r in b}
            n = len(seeds); mean = lambda i: sum(res[s][i] for s in seeds) / n
            mh, seh = stats([res[s][1] - ref['HA'][s]['edge'] for s in seeds])
            print(f'{ms:28s} edge {mean(1):8.3f} retail {mean(2):8.3f} arb {mean(3):7.3f} rv {mean(4):6.0f} av {mean(5):6.0f}  vs HA {mh:+.3f} se {seh:.3f} ({time.time()-t0:.0f}s)', flush=True)
