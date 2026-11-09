"""Pure-Python replica of benedictbrady/amm-challenge @6b6921f8 (engine.rs, cfmm.rs,
arbitrageur.rs, router.rs, retail.rs), written from the source for ceiling experiments.
RNG streams differ from the Rust engine, so absolute scores move by the seed set;
compare policies paired on the same seeds.

A policy gets a callback after every trade on its own pool (arb or retail), like afterSwap,
plus an oracle view (true fair price p and the 30 bps pool's spot s2 after the pending
action of the same event), and returns (bid_fee, ask_fee)."""
import math, random

K = 100.0 * 10000.0
MAXF = 0.1
NF = 0.003  # normalizer fee


def clampf(f):
    return 0.0 if f < 0.0 else (MAXF if f > MAXF else f)


def run(seed, policy, n_steps=10000, cfg=None):
    cr = random.Random(10_000_000 + seed)
    size_mean = cr.uniform(19.0, 21.0)
    lam = cr.uniform(0.6, 1.0)
    sigma = cr.uniform(0.000882, 0.001008)
    if cfg:
        size_mean, lam, sigma = cfg
    pr = random.Random(seed)
    rr = random.Random(seed + 1)
    drift = -0.5 * sigma * sigma
    mu_ln = math.log(size_mean) - 0.5 * 1.2 * 1.2
    emlam = math.exp(-lam)
    p = 100.0
    x1, y1 = 100.0, 10000.0
    x2, y2 = 100.0, 10000.0
    fb, fa = policy.init(sigma, lam, size_mean)
    fb, fa = clampf(fb), clampf(fa)
    e1 = e2 = 0.0
    ret1 = arb1 = 0.0  # our retail / arb edge
    rv1 = av1 = 0.0
    sum_fb = sum_fa = 0.0
    g2 = 1.0 - NF
    sqrt = math.sqrt
    for t in range(n_steps):
        p *= math.exp(drift + sigma * pr.gauss(0.0, 1.0))
        # --- arbitrage, normalizer first (pools are independent), then ours
        s2 = y2 / x2
        if s2 < p:
            nx = sqrt(K / (g2 * p)); ax = x2 - nx
            if ax > 0:
                ax = min(ax, x2 * 0.99)
                nrx = x2 - ax; nry = K / nrx; net_y = nry - y2; ty = net_y / g2
                prof = ax * p - ty
                if prof > 0:
                    x2, y2 = nrx, nry; e2 -= prof
        elif s2 > p:
            xv = sqrt(K * g2 / p); ax = (xv - x2) / g2
            if ax > 0:
                nrx = x2 + ax * g2; nry = K / nrx; yo = y2 - nry
                prof = yo - ax * p
                if yo > 0 and prof > 0:
                    x2, y2 = nrx, nry; e2 -= prof
        s1 = y1 / x1
        if s1 < p:
            g = 1.0 - fa
            if g > 0:
                nx = sqrt(K / (g * p)); ax = x1 - nx
                if ax > 0:
                    ax = min(ax, x1 * 0.99)
                    nrx = x1 - ax; nry = K / nrx; net_y = nry - y1; ty = net_y / g
                    prof = ax * p - ty
                    if prof > 0:
                        x1, y1 = nrx, nry; e1 -= prof; arb1 -= prof; av1 += ty
                        fb, fa = policy.on_trade(False, ax, ty, t, x1, y1, True, p, y2 / x2)
                        fb, fa = clampf(fb), clampf(fa)
        elif s1 > p:
            g = 1.0 - fb
            if g > 0:
                xv = sqrt(K * g / p); ax = (xv - x1) / g
                if ax > 0:
                    nrx = x1 + ax * g; nry = K / nrx; yo = y1 - nry
                    prof = yo - ax * p
                    if yo > 0 and prof > 0:
                        x1, y1 = nrx, nry; e1 -= prof; arb1 -= prof; av1 += yo
                        fb, fa = policy.on_trade(True, ax, yo, t, x1, y1, True, p, y2 / x2)
                        fb, fa = clampf(fb), clampf(fa)
        # --- retail
        n = 0; q = rr.random()
        while q > emlam:
            n += 1; q *= rr.random()
        for _ in range(n):
            size = rr.lognormvariate(mu_ln, 1.2)
            buy = rr.random() < 0.5
            if buy:  # trader buys X with Y
                ga = 1.0 - fa
                a1 = sqrt(x1 * ga * y1); a2 = sqrt(x2 * g2 * y2); r = a1 / a2
                d = ga + r * g2
                u1 = (r * (y2 + g2 * size) - y1) / d if d != 0 else size / 2
                u1 = 0.0 if u1 < 0 else (size if u1 > size else u1)
                u2 = size - u1
                if u2 > 1e-4:
                    nry = y2 + u2 * g2; nrx = K / nry; xo = x2 - nrx
                    if xo > 0:
                        e2 += u2 - xo * p; x2, y2 = nrx, nry
                if u1 > 1e-4:
                    nry = y1 + u1 * ga; nrx = K / nry; xo = x1 - nrx
                    if xo > 0:
                        ed = u1 - xo * p; e1 += ed; ret1 += ed; rv1 += u1
                        x1, y1 = nrx, nry
                        fb, fa = policy.on_trade(False, xo, u1, t, x1, y1, False, p, y2 / x2)
                        fb, fa = clampf(fb), clampf(fa)
            else:  # trader sells X
                tx = size / p
                gb = 1.0 - fb
                b1 = sqrt(y1 * gb * x1); b2 = sqrt(y2 * g2 * x2); r = b1 / b2
                d = gb + r * g2
                v1 = (r * (x2 + g2 * tx) - x1) / d if d != 0 else tx / 2
                v1 = 0.0 if v1 < 0 else (tx if v1 > tx else v1)
                v2 = tx - v1
                if v2 > 1e-4:
                    nrx = x2 + v2 * g2; nry = K / nrx; yo = y2 - nry
                    if yo > 0:
                        e2 += v2 * p - yo; x2, y2 = nrx, nry
                if v1 > 1e-4:
                    nrx = x1 + v1 * gb; nry = K / nrx; yo = y1 - nry
                    if yo > 0:
                        ed = v1 * p - yo; e1 += ed; ret1 += ed; rv1 += yo
                        x1, y1 = nrx, nry
                        fb, fa = policy.on_trade(True, v1, yo, t, x1, y1, False, p, y2 / x2)
                        fb, fa = clampf(fb), clampf(fa)
        sum_fb += fb; sum_fa += fa
    return dict(edge=e1, norm=e2, retail=ret1, arb=arb1, rv=rv1, av=av1,
                fb=sum_fb / n_steps * 1e4, fa=sum_fa / n_steps * 1e4,
                sigma=sigma, lam=lam, size=size_mean)


class Fixed:
    def __init__(self, f): self.f = f
    def init(self, *a): return self.f, self.f
    def on_trade(self, *a): return self.f, self.f


class OracleQuote:
    """Quote ask p(1+m) and bid p(1-m) around the TRUE fair price after every own trade."""
    def __init__(self, m): self.m = m
    def init(self, *a): return 0.003, 0.003
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2):
        s = y / x
        fa = 1.0 - s / (p * (1 + self.m))
        fb = 1.0 - p * (1 - self.m) / s
        return fb, fa


class OracleCompete:
    """Know p and the 30 bps pool's spot s2. Ask quote: undercut the rival's ask by u,
    but never below p(1+mlo); bid quote: outbid the rival's bid by u, never above p(1-mlo)."""
    def __init__(self, mlo, u, mhi=1.0):
        self.mlo, self.u, self.mhi = mlo, u, mhi
    def init(self, *a): return 0.003, 0.003
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2):
        s = y / x
        ra = s2 / (1 - NF); rb = s2 * (1 - NF)
        qa = max(p * (1 + self.mlo), min(ra * (1 - self.u), p * (1 + self.mhi)))
        qb = min(p * (1 - self.mlo), max(rb * (1 + self.u), p * (1 - self.mhi)))
        return 1.0 - qb / s, 1.0 - s / qa
