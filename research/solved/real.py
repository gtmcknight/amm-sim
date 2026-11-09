"""Solved policy driven ONLY by what afterSwap sees (side, amounts, timestamp, reserves).

Filter: Gaussian belief over ln p (mean, variance).
  - new step: variance grows by sigma^2 a step; steps with no trade of ours truncate the belief to our no-arb interval
  - first trade of a step: arb or retail by likelihood ratio. Arb => p is exact (post-trade spot through the fee in force).
    Retail => belief truncated to the no-arb interval.
Rival: absolute spot dead-reckoned (router identity on own retail trades, band clip against the price estimate).
Policy: table lookup at the estimates.  Oracle arguments are used for diagnostics only.

usage: python3 -I real.py <pol.json> [variant ...]      variants: ce | qm:<qmdp.json> ...
"""
import sys, os, math, json, time
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replica2 as R
from evalpol import DPPolicy, load, stats, CALIB

G2 = 1.0 - R.NF
SIG2 = 0.000945 ** 2
RHO = 0.26                       # P(a no-arb step's first own trade is retail on a given side)
LD_M, LD_S = math.log(11.12e-4), 1.176   # own-fill spot move of a retail first trade: lognormal fit
SQ2PI = 2.5066282746310002
H0 = 0.55
LD_FULL = math.log(20.0) - 0.72 + math.log(2.0 / 10000.0)   # ln median of a full order's displacement


def phi(x): return math.exp(-0.5 * x * x) / SQ2PI
def Phi(x): return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


def trunc(m, v, lo, hi):
    """moments of N(m, v) restricted to (lo, hi); returns (mass, mean, var)"""
    if v <= 0.0:
        return (1.0 if lo <= m <= hi else 0.0), m, 0.0
    sd = math.sqrt(v); a = (lo - m) / sd; b = (hi - m) / sd
    Z = Phi(b) - Phi(a)
    if Z < 1e-12:
        # belief is outside the interval: snap to the nearer edge
        return Z, (lo if m < lo else hi), v * 0.25
    pa, pb = phi(a), phi(b)
    r = (pa - pb) / Z
    mean = m + sd * r
    var = v * (1.0 + (a * pa - b * pb) / Z - r * r)
    if var < 0.0: var = 0.0
    return Z, mean, var


class RealPolicy(DPPolicy):
    wants_j = True
    def __init__(self, T, opt=None):
        DPPolicy.__init__(self, T)
        self.o = opt or {}
        self.Q = load(self.o['qm']) if 'qm' in self.o else None
        self.synced = False
        self.m = math.log(100.0); self.v = 0.0
        self.tlast = 0; self.cnt = 0
        self.s2h = 100.0
        self.fb = self.fa = 0.003
        self.sp = 100.0               # own spot after our last callback
        # diagnostics
        self.nmis = 0; self.ncls = 0; self.se = 0.0; self.nse = 0; self.se2 = 0.0
    def init(self, *a):
        fb, fa = self._fees(0.0, 0.0, 0)
        self.fb, self.fa = R.clampf(fb), R.clampf(fa)
        return fb, fa
    def lookup(self, w, w2, phs, sd):
        Q = self.Q
        if Q is None:
            return self._fees(w, w2, phs)
        sd = sd * self.o.get('sdscale', 1.0)
        S = Q['S']; k = 0
        while k < len(S) - 2 and sd >= S[k + 1]: k += 1
        tt = (sd - S[k]) / (S[k + 1] - S[k])
        if tt < 0.0: tt = 0.0
        if tt > 1.0: tt = 1.0
        tag = '0c' if phs == 0 else (str(phs) + ('s' if self.synced else 'c'))
        A, B = Q['A' + tag], Q['B' + tag]
        pw = w / self.h + self.W0
        if pw < 0: pw = 0.0
        if pw > self.NW - 1: pw = float(self.NW - 1)
        l2 = w2 / self.h
        if phs == 0:
            if l2 < -self.FB: l2 = -self.FB
            if l2 > self.FB: l2 = self.FB
            p2 = l2 + self.FB; n2 = 2 * self.FB + 1
        else:
            p2 = self._pos2(l2); n2 = self.N2
        i = int(pw); j = int(p2)
        if i > self.NW - 2: i = self.NW - 2
        if j > n2 - 2: j = n2 - 2
        f = pw - i; g = p2 - j
        def bl(Tb):
            return (Tb[i][j] * (1 - f) + Tb[i + 1][j] * f) * (1 - g) + (Tb[i][j + 1] * (1 - f) + Tb[i + 1][j + 1] * f) * g
        a = bl(A[k]) * (1 - tt) + bl(A[k + 1]) * tt
        b = bl(B[k]) * (1 - tt) + bl(B[k + 1]) * tt
        fa = 1.0 - math.exp(-(a - w) * 1e-4) if a > w else 0.0
        fb = 1.0 - math.exp(-(b + w) * 1e-4) if b > -w else 0.0
        return fb, fa
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        s = y / x
        dt = t - self.tlast
        is_arb = False
        if dt >= 1:
            self.cnt = 0
            lo = math.log(self.sp * (1.0 - self.fb)); hi = math.log(self.sp / (1.0 - self.fa))   # no-arb interval of the quotes in force
            m, v = self.m, self.v
            for _ in range(min(dt - 1, 12)):          # fully silent steps
                v += SIG2
                _, m, v = trunc(m, v, lo, hi)
            v += SIG2                                  # this step's move
            # arb hypothesis: p exactly at the post-trade band edge
            lp_arb = math.log(s * (1.0 - self.fb)) if is_buy else math.log(s / (1.0 - self.fa))
            sd = math.sqrt(v)
            o = self.o
            l_arb = phi((lp_arb - m) / sd) / sd
            eps = o.get('tail', 0.0)
            if eps > 0.0:
                l_arb = (1.0 - eps) * l_arb + eps * phi((lp_arb - m) / 40e-4) / 40e-4
            Z, mt, vt = trunc(m, v, lo, hi)
            d = abs(math.log(s / self.sp))
            if o.get('fill', 0):
                # retail fill density from the order-size law and how our quote compared with the rival's (estimates)
                pe0 = math.exp(mt)
                r2 = self.s2h
                if r2 < pe0 * G2: r2 = pe0 * G2
                elif r2 > pe0 / G2: r2 = pe0 / G2
                if is_buy:   # trader sold: compare bids (log)
                    delta = math.log(r2 * G2) - math.log(self.sp * (1.0 - self.fb))      # >0: rival bid better
                else:
                    delta = math.log(self.sp / (1.0 - self.fa)) - math.log(r2 / G2)      # >0: rival ask better
                if d > -delta:
                    D = 2.0 * d + delta; jac = 2.0
                else:
                    D = d; jac = 1.0
                D = max(D, 1e-9)
                l_ret = Z * 0.5 * H0 * jac * phi((math.log(D) - LD_FULL) / 1.2) / (D * 1.2)
            else:
                l_ret = Z * RHO * phi((math.log(max(d, 1e-9)) - LD_M) / LD_S) / (max(d, 1e-9) * LD_S)
            pi = l_arb / (l_arb + l_ret) if (l_arb + l_ret) > 0 else 0.0
            if o.get('oraclearb', 0): pi = 1.0 if arb else 0.0
            is_arb = pi > 0.5
            self.ncls += 1
            if is_arb != arb: self.nmis += 1
            if o.get('soft', 0) and pi < o.get('hard', 0.995) and pi > 1.0 - o.get('hard', 0.995):
                m2 = pi * lp_arb + (1.0 - pi) * mt
                v2 = pi * (lp_arb - m2) ** 2 + (1.0 - pi) * (vt + (mt - m2) ** 2)
                self.m, self.v = m2, v2
            elif is_arb:
                self.m, self.v = lp_arb, 0.0
            else:
                self.m, self.v = mt, vt
            # rival was arbed at the start of this step: band clip against the estimate
            pe = math.exp(self.m)
            if self.s2h < pe * G2: self.s2h = pe * G2
            elif self.s2h > pe / G2: self.s2h = pe / G2
            self.synced = False
        pe = math.exp(self.m)
        if not is_arb:
            if is_buy:
                cand = s * (1.0 - self.fb) / G2
                if cand < self.s2h: self.s2h = cand; self.synced = True
            else:
                cand = s * G2 / (1.0 - self.fa)
                if cand > self.s2h: self.s2h = cand; self.synced = True
            self.cnt += 1
            phs = 1 if self.cnt <= 1 else 2
        else:
            phs = 0
        err = (self.m - math.log(p)) * 1e4
        self.se += err * err; self.nse += 1
        if not is_arb: self.se2 += err * err
        self.tlast = t; self.sp = s
        w = (math.log(s) - self.m) * 1e4; w2 = (math.log(self.s2h) - self.m) * 1e4
        fb, fa = self.lookup(w, w2, phs, math.sqrt(self.v) * 1e4)
        self.fb, self.fa = R.clampf(fb), R.clampf(fa)
        return fb, fa


def ev(a):
    path, opt, seeds = a
    T = load(path); out = []
    for s in seeds:
        pol = RealPolicy(T, opt)
        r = R.run(s, pol)
        out.append((s, r['edge'], r['retail'], r['arb'], r['rv'], r['av'], pol.nmis, pol.ncls, pol.se, pol.nse))
    return out


def report(pool, path, opt, seeds, ref, label):
    t0 = time.time()
    res = pool.map(ev, [(path, opt, seeds[i:i + 8]) for i in range(0, len(seeds), 8)], chunksize=1)
    res = {r[0]: r for b in res for r in b}
    n = len(seeds); mean = lambda i: sum(res[s][i] for s in seeds) / n
    mh, seh = stats([res[s][1] - ref['HA'][s]['edge'] for s in seeds])
    mis = sum(res[s][6] for s in seeds) / max(1, sum(res[s][7] for s in seeds))
    rms = math.sqrt(sum(res[s][8] for s in seeds) / max(1, sum(res[s][9] for s in seeds)))
    print(f'{label:24s} edge {mean(1):8.3f} retail {mean(2):8.3f} arb {mean(3):7.3f} rv {mean(4):6.0f} av {mean(5):6.0f}  vs HA {mh:+.3f} se {seh:.3f}  misclass {mis:.2%}  p rms {rms:.1f} bps ({time.time()-t0:.0f}s)', flush=True)
    return res


if __name__ == '__main__':
    path = sys.argv[1]
    n = int(os.environ.get('NSEED', '2048'))
    seeds = list(range(10000, 10000 + n))
    rows = json.load(open(CALIB)); ref = {}
    for r in rows: ref.setdefault(r['kind'], {})[r['seed']] = r
    with Pool(14) as pool:
        for spec in (sys.argv[2:] or ['ce']):
            name, _, kv = spec.partition(':')
            opt = {}
            for item in kv.split(','):
                if item:
                    k, _, val = item.partition('=')
                    opt[k] = os.path.join(HERE, val) if k == 'qm' else float(val)
            report(pool, path, opt, seeds, ref, spec)
