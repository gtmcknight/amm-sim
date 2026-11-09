"""Exact Bayes on a price lattice, real observables only.

Belief = probability mass on cells of width HC around a moving centre.  Each elapsed step convolves with the
price-move kernel; a step with no own trade zeroes the cells where the arb would have traded; the first trade
of a step is a mixture of "arb" (p exactly at the post-trade band edge) and "retail" (p inside the no-arb interval),
weighted by likelihood.  Nothing is thrown away, so a later pin resolves an earlier ambiguous trade.
Quotes: moment-matched (mean, sd) into the uncertainty-aware tables.
on_trade takes exactly what afterSwap gets (see real.py and run.py).

usage: python3 -I latt.py <pol.json> name:key=val,... [more]      e.g. lattice:qm=qm_k1e-5.json
"""
import sys, os, math, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replica2 as R
import real
from real import RealPolicy, phi, G2, RHO, LD_M, LD_S, H0, LD_FULL

HC = 2.5e-4            # cell width (log)
NC = 121               # cells: +-150 bps
N0 = NC // 2
SIG = 0.000945


def kernel(sig, hc):
    s = sig / hc; M = int(math.ceil(4.0 * s))
    w = [math.exp(-0.5 * (k / s) ** 2) for k in range(-M, M + 1)]
    t = sum(w)
    return [v / t for v in w], M

KER, KM = kernel(SIG, HC)


class LatticePolicy(RealPolicy):
    def __init__(self, T, opt=None):
        RealPolicy.__init__(self, T, opt)
        self.c = math.log(100.0)          # log price of cell N0
        self.P = [0.0] * NC; self.P[N0] = 1.0
        self.lo_i = N0; self.hi_i = N0     # support bounds (inclusive)
    # ---- lattice ops
    def diffuse(self):
        P = self.P; lo = max(0, self.lo_i - KM); hi = min(NC - 1, self.hi_i + KM)
        out = [0.0] * NC
        for i in range(self.lo_i, self.hi_i + 1):
            pi_ = P[i]
            if pi_ <= 1e-15: continue
            j0 = i - KM
            for k in range(2 * KM + 1):
                j = j0 + k
                if 0 <= j < NC: out[j] += pi_ * KER[k]
        self.P = out; self.lo_i = lo; self.hi_i = hi
    def cut(self, lo, hi):
        """keep only mass with lo < ln p < hi (the no-arb interval); returns the kept mass before renormalising"""
        P = self.P; c = self.c; tot = 0.0
        for i in range(self.lo_i, self.hi_i + 1):
            if P[i] == 0.0: continue
            x0 = c + (i - N0 - 0.5) * HC; x1 = x0 + HC
            a = lo if lo > x0 else x0; b = hi if hi < x1 else x1
            f = (b - a) / HC
            if f <= 0.0: P[i] = 0.0
            else:
                if f < 1.0: P[i] *= f
                tot += P[i]
        return tot
    def norm(self, tot):
        if tot <= 1e-300: return False
        P = self.P; inv = 1.0 / tot
        lo = None; hi = None
        for i in range(self.lo_i, self.hi_i + 1):
            if P[i] > 0.0:
                P[i] *= inv
                if P[i] < 1e-12: P[i] = 0.0
                else:
                    if lo is None: lo = i
                    hi = i
        if lo is None: return False
        self.lo_i, self.hi_i = lo, hi
        return True
    def dens(self, x):
        pos = (x - self.c) / HC + N0
        i = int(math.floor(pos)); f = pos - i
        if i < 0 or i >= NC - 1: return 0.0
        return (self.P[i] * (1 - f) + self.P[i + 1] * f) / HC
    def moments(self):
        P = self.P; m = 0.0; tot = 0.0
        for i in range(self.lo_i, self.hi_i + 1):
            m += P[i] * (i - N0); tot += P[i]
        if tot <= 0: return self.c, 0.0
        m /= tot; v = 0.0
        for i in range(self.lo_i, self.hi_i + 1):
            v += P[i] * (i - N0 - m) ** 2
        v /= tot
        return self.c + m * HC, v * HC * HC
    def recentre(self, cnew):
        """move the lattice so that cell N0 sits at cnew (linear re-binning)"""
        sh = (cnew - self.c) / HC
        P = self.P; out = [0.0] * NC
        for i in range(self.lo_i, self.hi_i + 1):
            if P[i] == 0.0: continue
            pos = i - sh; j = int(math.floor(pos)); f = pos - j
            if 0 <= j < NC: out[j] += P[i] * (1 - f)
            if 0 <= j + 1 < NC: out[j + 1] += P[i] * f
        self.P = out; self.c = cnew
        self.lo_i = max(0, int(math.floor(self.lo_i - sh)) - 1); self.hi_i = min(NC - 1, int(math.ceil(self.hi_i - sh)) + 1)
    def pin(self, x):
        self.c = x; self.P = [0.0] * NC; self.P[N0] = 1.0; self.lo_i = self.hi_i = N0
    def deposit(self, x, w):
        pos = (x - self.c) / HC + N0
        i = int(math.floor(pos)); f = pos - i
        if 0 <= i < NC: self.P[i] += w * (1 - f); self.lo_i = min(self.lo_i, i); self.hi_i = max(self.hi_i, i)
        if 0 <= i + 1 < NC: self.P[i + 1] += w * f; self.lo_i = min(self.lo_i, i + 1); self.hi_i = max(self.hi_i, i + 1)
    # ---- callback
    def on_trade(self, is_buy, ax, ay, t, x, y, flag=None):
        o = self.o
        s = y / x
        dt = t - self.tlast
        is_arb = False
        self.first = dt >= 1
        if dt >= 1:
            self.cnt = 0
            lo = math.log(self.sp * (1.0 - self.fb)); hi = math.log(self.sp / (1.0 - self.fa))
            ok = True
            for _ in range(min(dt - 1, 30)):
                self.diffuse()
                ok = self.norm(self.cut(lo, hi))
                if not ok: break
            if ok: self.diffuse()
            lp_arb = math.log(s * (1.0 - self.fb)) if is_buy else math.log(s / (1.0 - self.fa))
            if not ok:
                # belief died (model mismatch): restart wide around the arb reading
                self.pin(lp_arb); pi = 1.0
            else:
                l_arb = self.dens(lp_arb)
                eps = o.get('tail', 0.0)
                if eps > 0.0:
                    mm, vv = self.moments()
                    l_arb = (1.0 - eps) * l_arb + eps * phi((lp_arb - mm) / 40e-4) / 40e-4
                d = abs(math.log(s / self.sp))
                # retail branch: p inside the no-arb interval
                Pkeep = self.P[:]; lo_i, hi_i = self.lo_i, self.hi_i
                Z = self.cut(lo, hi)
                l_ret = Z * o.get('rho', RHO) * phi((math.log(max(d, 1e-9)) - LD_M) / LD_S) / (max(d, 1e-9) * LD_S)
                pi = l_arb / (l_arb + l_ret) if (l_arb + l_ret) > 0 else 1.0
                if o.get('oraclearb', 0): pi = 1.0 if flag else 0.0
                hard = o.get('hard', 0.999)
                if pi >= hard or Z <= 1e-300:
                    self.pin(lp_arb)
                elif pi <= 1.0 - hard:
                    self.norm(Z)
                else:
                    # mixture: (1 - pi) * retail posterior + pi * point mass at the arb reading
                    self.norm(Z)
                    P = self.P
                    for i in range(self.lo_i, self.hi_i + 1): P[i] *= (1.0 - pi)
                    if pi > 0.5: self.recentre(lp_arb)
                    self.deposit(lp_arb, pi)
            is_arb = pi > 0.5
            self.m, self.v = self.moments()
            # keep the mass away from the window edge
            if abs(self.m - self.c) > 40 * HC: self.recentre(self.m); self.m, self.v = self.moments()
            pe = math.exp(self.m)
            if self.s2h < pe * G2: self.s2h = pe * G2
            elif self.s2h > pe / G2: self.s2h = pe / G2
            self.synced = False
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
        self.is_arb = is_arb
        self.tlast = t; self.sp = s
        w = (math.log(s) - self.m) * 1e4; w2 = (math.log(self.s2h) - self.m) * 1e4
        fb, fa = self.lookup(w, w2, phs, math.sqrt(self.v) * 1e4)
        self.fb, self.fa = R.clampf(fb), R.clampf(fa)
        return fb, fa


if __name__ == '__main__':
    import run
    path = sys.argv[1]
    n = int(os.environ.get('NSEED', '2048')); s0 = int(os.environ.get('SEED0', '10000'))
    for spec, opt in real.variants(sys.argv[2:]):
        t0 = time.time()
        rows = run.run_policy('lattice', opt, list(range(s0, s0 + n)), path)
        print(run.line(spec, rows) + f' ({time.time()-t0:.0f}s)', flush=True)
