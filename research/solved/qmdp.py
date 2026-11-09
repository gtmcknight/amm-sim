"""Uncertainty-aware quote tables from the solved perfect-information values (QMDP step).

For a belief  ln p = estimate + e,  e ~ N(0, s^2)  the quotes are set once for every hypothesis, so
    (a, b)* = argmax  sum_e  bel(e) * V_N[phase](w - e, w2(e), a - e, b + e)
with the rival either synced this step (absolute spot known: w2(e) = R - e) or band-clipped
(w2(e) = clip(R - e, +-30 bps)).  Tables per phase x rival mode x belief sd level.

usage: DP_AMINL=-12 DP_NA=43 venv/bin/python qmdp.py pol_mid.json qm_mid.json
"""
import sys, os, math, json, time
import numpy as np
from numba import njit, prange
import dp
from dp import NW, W0, N2, C2, FB, NB, NA, AMINL, W2L, H

SLEV = [0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 26.0, 34.0]
IGMAX = 60          # offsets beyond +300 bps never trigger


def igtab(s_bps, sigma_bps):
    """expected drop in belief variance (bps^2) at the next step boundary for quotes (a, b) relative to the estimate:
    the arb pins p exactly when the move crosses a quote; otherwise the belief is cut to the no-arb interval."""
    tot = math.sqrt(s_bps ** 2 + sigma_bps ** 2) / (H * 1e4)
    M = int(math.ceil(4 * tot)) + 1
    xs = np.arange(-M, M + 1); pr = np.exp(-0.5 * (xs / tot) ** 2); pr /= pr.sum()
    n = IGMAX - AMINL + 1
    out = np.zeros((n, n))
    v0 = (s_bps ** 2 + sigma_bps ** 2)
    for i in range(n):
        a = AMINL + i
        for j in range(n):
            b = AMINL + j
            sel = (xs <= a) & (xs >= -b)
            ps = pr[sel].sum()
            if ps > 1e-12:
                mu = (pr[sel] * xs[sel]).sum() / ps
                var = (pr[sel] * (xs[sel] - mu) ** 2).sum() / ps * (H * 1e4) ** 2
            else: var = 0.0
            out[i, j] = v0 - ps * var
    return out


def ebel(s_bps):
    if s_bps < 1e-9: return np.array([0], np.int64), np.array([1.0])
    s = s_bps / (H * 1e4); M = int(math.ceil(3 * s))
    es = np.arange(-M, M + 1).astype(np.int64); w = np.exp(-0.5 * (es / s) ** 2)
    return es, w / w.sum()


RHO = 0.26; LD_M = math.log(11.12); LD_S = 1.176      # retail first-trade rate per side and fill law (bps)


def igtab2(s_bps, sigma_bps):
    """expected drop in belief variance (bps^2) over the next step boundary, with the arb/retail ambiguity:
    E[var after] = Z*V_in + overlap terms, where a first trade of size d on a side could be the arb
    (p = quote + d beyond it) or retail (p inside the quotes)."""
    tau = math.sqrt(s_bps ** 2 + sigma_bps ** 2)
    n = IGMAX - AMINL + 1
    hb = H * 1e4
    offs = (AMINL + np.arange(n)) * hb                       # bps
    d = np.arange(0.25, 200.0, 0.5)                          # bps, midpoints
    fd = np.exp(-0.5 * ((np.log(d) - LD_M) / LD_S) ** 2) / (d * LD_S * 2.5066282746)
    Phi = lambda x: 0.5 * (1.0 + math.erf(x / 1.4142135623730951))
    phi = lambda x: math.exp(-0.5 * x * x) / 2.5066282746
    out = np.zeros((n, n))
    for i in range(n):
        a = offs[i]
        dens_a = np.exp(-0.5 * ((a + d) / tau) ** 2) / (tau * 2.5066282746)       # arb on the ask: e' = a + d
        for j in range(n):
            b = offs[j]
            if a + b <= 0:      # crossed quotes: the arb always trades, p is pinned
                out[i, j] = tau * tau; continue
            al = -b / tau; be = a / tau
            Z = Phi(be) - Phi(al)
            if Z < 1e-9:
                out[i, j] = tau * tau; continue
            pa, pb = phi(al), phi(be); r = (pa - pb) / Z
            mu = tau * r; V = tau * tau * (1.0 + (al * pa - be * pb) / Z - r * r)
            ret = Z * RHO * fd
            amb_a = (dens_a * ret / (dens_a + ret + 1e-300) * (a + d - mu) ** 2).sum() * 0.5
            dens_b = np.exp(-0.5 * ((b + d) / tau) ** 2) / (tau * 2.5066282746)   # arb on the bid: e' = -(b + d)
            amb_b = (dens_b * ret / (dens_b + ret + 1e-300) * (-(b + d) - mu) ** 2).sum() * 0.5
            out[i, j] = tau * tau - Z * V - amb_a - amb_b
    return out


@njit(parallel=True, cache=False)
def qtab(VN, es, ws, mode, band, IG, kap):
    n2 = VN.shape[1]
    QA = np.zeros((NW, n2)); QB = np.zeros((NW, n2)); UB = np.zeros((NW, n2))
    for iw in prange(NW):
        wl = iw - W0
        U = np.zeros((NA, NA))
        for i2 in range(n2):
            U[:, :] = 0.0
            Rl = float(i2 - FB) if band else W2L[i2]
            for n in range(es.shape[0]):
                e = es[n]; pw = ws[n]
                iwt = iw - e
                if iwt < 0: iwt = 0
                elif iwt > NW - 1: iwt = NW - 1
                v = Rl - e
                if mode == 1 or band:
                    if v < -FB: v = -float(FB)
                    elif v > FB: v = float(FB)
                if band:
                    j0 = int(round(v)) + FB; f = 0.0
                    if j0 > n2 - 2: j0 = n2 - 2; f = 1.0
                else:
                    p2 = dp.w2pos(v); j0 = int(p2)
                    if j0 > n2 - 2: j0 = n2 - 2
                    f = p2 - j0
                for ia in range(NA):
                    iat = ia - e
                    if iat < 0: iat = 0
                    elif iat > NA - 1: iat = NA - 1
                    for ib in range(NA):
                        ibt = ib + e
                        if ibt < 0: ibt = 0
                        elif ibt > NA - 1: ibt = NA - 1
                        U[ia, ib] += pw * (VN[iwt, j0, iat, ibt] * (1.0 - f) + VN[iwt, j0 + 1, iat, ibt] * f)
            if kap != 0.0:
                for ia in range(NA):
                    al0 = AMINL + ia
                    if al0 < wl: al0 = wl
                    if al0 > IGMAX: al0 = IGMAX
                    for ib in range(NA):
                        bl0 = AMINL + ib
                        if bl0 < -wl: bl0 = -wl
                        if bl0 > IGMAX: bl0 = IGMAX
                        U[ia, ib] += kap * IG[al0 - AMINL, bl0 - AMINL]
            best = -1e300; bi = 0; bj = 0
            for ia in range(NA):
                for ib in range(NA):
                    if U[ia, ib] > best: best = U[ia, ib]; bi = ia; bj = ib
            UB[iw, i2] = best
            al = float(AMINL + bi); bl = float(AMINL + bj)
            if AMINL + bi <= wl: al = float(wl)
            elif bi > 0 and bi < NA - 1 and AMINL + bi - 1 >= wl:
                vm = U[bi - 1, bj]; v0 = U[bi, bj]; vp = U[bi + 1, bj]; den = vm - 2 * v0 + vp
                if den < 0:
                    d = 0.5 * (vm - vp) / den
                    if d > 0.5: d = 0.5
                    if d < -0.5: d = -0.5
                    al += d
            if AMINL + bj <= -wl: bl = float(-wl)
            elif bj > 0 and bj < NA - 1 and AMINL + bj - 1 >= -wl:
                vm = U[bi, bj - 1]; v0 = U[bi, bj]; vp = U[bi, bj + 1]; den = vm - 2 * v0 + vp
                if den < 0:
                    d = 0.5 * (vm - vp) / den
                    if d > 0.5: d = 0.5
                    if d < -0.5: d = -0.5
                    bl += d
            QA[iw, i2] = al * H * 1e4; QB[iw, i2] = bl * H * 1e4
    return QA, QB, UB


if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    T = json.load(open(src))
    VN = [np.load(src.replace('.json', f'_VN{j}.npy')).astype(np.float64) for j in range(3)]
    res = dict(S=SLEV, W0=W0, NW=NW, N2=N2, C2=C2, FB=FB, H_bps=H * 1e4, W2L=W2L.tolist(), lam=T['lam'], sigma=T['sigma'], size=T['size'], g=T['g'])
    t0 = time.time()
    kap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    hs = dp.phase_probs(T['lam'])
    res['kappa'] = kap
    for ph in range(3):
        for mode, tag in ((0, 's'), (1, 'c')):
            if ph == 0 and mode == 0: continue
            A = []; B = []; UU = []
            for s in SLEV:
                es, ws = ebel(s)
                IG = igtab2(s, T['sigma']) if os.environ.get('IG2') else igtab(s, T['sigma'])
                qa, qb, ub = qtab(VN[ph], es, ws, mode, ph == 0, IG, kap * (1.0 - hs[ph]))
                A.append(qa.round(2).tolist()); B.append(qb.round(2).tolist()); UU.append(ub)
            res[f'A{ph}{tag}'] = A; res[f'B{ph}{tag}'] = B
            i2 = FB if ph == 0 else C2
            print(f'phase {ph} mode {tag} done {time.time()-t0:.0f}s   value at w=0,R=0 by sd level minus level 0: ' + ' '.join(f'{UU[k][W0, i2]-UU[0][W0, i2]:+.5f}' for k in range(len(SLEV))), flush=True)
    json.dump(res, open(out, 'w'))
    # sanity: level 0 must reproduce the perfect-information tables
    if kap == 0.0: a0 = np.array(res['A0c'][0]); print('max |A0(s=0) - solved A0| bps:', float(np.abs(a0 - np.array(T['A0'])).max()))
    if kap == 0.0: a1 = np.array(res['A1s'][0]); print('max |A1 synced(s=0) - solved A1| bps:', float(np.abs(a1 - np.array(T['A1'])).max()))
