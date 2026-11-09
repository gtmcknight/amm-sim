"""Run a solved (dp.py) perfect-information policy on the pure-Python replica.
usage: python3 -I evalpol.py <pol.json>[,<pol2.json>...] hold        seeds 10000..12047, paired vs the stored HA / old oracle table rows
       python3 -I evalpol.py <pol.json> mid [n]                      midpoint parameters (lam .8, sigma 9.45, size 20) vs the DP's own value
"""
import sys, os, math, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from par import pmap
import replica2 as R

CALIB = os.path.join(HERE, 'calib_out_2048.json')
_cache = {}


def load(path):
    if path not in _cache: _cache[path] = json.load(open(path))
    return _cache[path]


class DPPolicy:
    wants_j = True
    def __init__(self, T, use_rival=True, use_phase=True):
        self.T = T; self.W0 = T['W0']; self.NW = T['NW']; self.N2 = T['N2']; self.FB = T['FB']; self.C2 = T['C2']
        self.h = T['H_bps']; self.W2L = T['W2L']; self.use_rival = use_rival; self.use_phase = use_phase
        self.tabs = [(T['A0'], T['B0']), (T['A1'], T['B1']), (T['A2'], T['B2'])]
    def init(self, *a):
        return self._fees(0.0, 0.0, 0)
    def _pos2(self, v):
        W = self.W2L; n = self.N2
        if v <= W[0]: return 0.0
        if v >= W[n - 1]: return float(n - 1)
        lo, hi = 0, n - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if W[mid] <= v: lo = mid
            else: hi = mid
        return lo + (v - W[lo]) / (W[hi] - W[lo])
    def _fees(self, w, w2, ph):
        # w, w2 in bps
        A, B = self.tabs[ph]
        pw = w / self.h + self.W0
        if pw < 0: pw = 0.0
        if pw > self.NW - 1: pw = float(self.NW - 1)
        l2 = w2 / self.h
        if ph == 0:
            if l2 < -self.FB: l2 = -self.FB
            if l2 > self.FB: l2 = self.FB
            p2 = l2 + self.FB; n2 = 2 * self.FB + 1
        else:
            p2 = self._pos2(l2); n2 = self.N2
        i = int(pw); j = int(p2)
        if i > self.NW - 2: i = self.NW - 2
        if j > n2 - 2: j = n2 - 2
        f = pw - i; g = p2 - j
        a = (A[i][j] * (1 - f) + A[i + 1][j] * f) * (1 - g) + (A[i][j + 1] * (1 - f) + A[i + 1][j + 1] * f) * g
        b = (B[i][j] * (1 - f) + B[i + 1][j] * f) * (1 - g) + (B[i][j + 1] * (1 - f) + B[i + 1][j + 1] * f) * g
        fa = 1.0 - math.exp(-(a - w) * 1e-4) if a > w else 0.0
        fb = 1.0 - math.exp(-(b + w) * 1e-4) if b > -w else 0.0
        return fb, fa
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        w = math.log(y / x / p) * 1e4
        w2 = math.log(s2 / p) * 1e4
        ph = 0 if arb else (1 if j <= 1 else 2)
        return self._fees(w, w2, ph)


def ev(a):
    path, seeds, cfg = a
    T = load(path)
    out = []
    for s in seeds:
        r = R.run(s, DPPolicy(T), cfg=cfg)
        out.append((s, r['edge'], r['retail'], r['arb'], r['rv'], r['av'], r['fb'], r['fa']))
    return out


def runset(pool, path, seeds, cfg=None, chunk=8):
    res = pmap(ev, [(path, seeds[i:i + chunk], cfg) for i in range(0, len(seeds), chunk)])
    return {r[0]: r for b in res for r in b}


def stats(d):
    n = len(d); m = sum(d) / n
    sd = (sum((v - m) ** 2 for v in d) / (n - 1)) ** 0.5
    return m, sd / n ** 0.5


if __name__ == '__main__':
    paths = sys.argv[1].split(','); mode = sys.argv[2]
    pool = None
    if True:
        if mode == 'hold':
            seeds = list(range(10000, 12048))
            rows = json.load(open(CALIB)); ref = {}
            for r in rows: ref.setdefault(r['kind'], {})[r['seed']] = r
            for path in paths:
                t0 = time.time(); res = runset(pool, path, seeds)
                n = len(seeds); mean = lambda i: sum(res[s][i] for s in seeds) / n
                print(f'{os.path.basename(path)}: edge {mean(1):.3f} retail {mean(2):.3f} arb {mean(3):.3f} rv {mean(4):.0f} av {mean(5):.0f} bid/ask bps {mean(6):.2f}/{mean(7):.2f}  ({time.time()-t0:.0f}s)')
                for k in ('oracle', 'HA', 'T'):
                    m, se = stats([res[s][1] - ref[k][s]['edge'] for s in seeds])
                    print(f'   vs {k:6s} {m:+.3f} se {se:.3f}')
        else:
            n = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
            seeds = list(range(30000, 30000 + n))
            for path in paths:
                T = load(path)
                res = runset(pool, path, seeds, cfg=(T['size'], T['lam'], T['sigma'] * 1e-4))
                m, se = stats([res[s][1] for s in seeds])
                print(f'{os.path.basename(path)} at its own parameters: replica {m:.3f} se {se:.3f}   DP value {T["g"]*1e4:.3f}')
