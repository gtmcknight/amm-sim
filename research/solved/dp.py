"""Exact dynamic program for the PERFECT-INFORMATION Simple AMM game (engine @6b6921f8 rules).

State at a decision (right after a trade on our pool):
    w   = ln(our spot / p)            own displacement
    w2  = ln(rival spot / p)          rival (fixed 30 bps) displacement
    j   = retail orders so far in this step (0 = we were just arbed, 1, 2+)
Action: effective ask offset a = ln(ask / p) and bid offset b = ln(p / bid), a >= w, b >= -w
        (fee >= 0).  Fees stay in force until the next trade on our pool, so the passive
        value V_N(w, w2, a, b, j) carries the quotes through silent steps and hidden rival trades.
Own displacement, offsets and price moves live on a 5 bps lattice (passive moves are exact);
retail outcomes use the exact router / constant-product formulas at p = 100 and are interpolated.
Average-reward relative value iteration; one sweep = one step of lookahead.

usage: dp.py solve <lam> <sigma_bps> <size_mean> <out.json>
       dp.py fixed <fee_bps> [lam sigma size]       (model check against the replica's fixed-fee scores)
env:   DP_NW (half-range of w in lattice units, default 160), DP_AMINL (default -8), DP_NA (default 39), DP_QSTEP (0.125)
"""
import sys, os, math, json, time
import numpy as np
from numba import njit, prange

H = 5e-4
W0 = int(os.environ.get('DP_NW', '160'))
NW = 2 * W0 + 1                               # own displacement: +-800 bps
_out = [14, 17, 20, 25, 30, 40, 50, 60, 80, 100, 130, 160]
W2L = np.array([-v for v in _out[::-1]] + list(range(-12, 13)) + _out, dtype=np.float64)   # rival grid, lattice units
N2 = len(W2L); C2 = N2 // 2
FB = 6                                        # rival band half width (30 bps)
NB = 2 * FB + 1
AMINL = int(os.environ.get('DP_AMINL', '-8'))
NA = int(os.environ.get('DP_NA', '39'))       # offsets: -40 .. +150 bps
MZ = 6                                        # price-move lattice: +-30 bps
Y0, X0, P0, KK = 10000.0, 100.0, 100.0, 1.0e6
G2 = 0.997
QSTEP = float(os.environ.get('DP_QSTEP', '0.125'))
_mask = os.environ.get('DP_MASK', '')
MLO, MHI = (int(_mask.split(',')[0]), int(_mask.split(',')[1])) if _mask else (0, 0)   # forbid MLO < offset < MHI


def qnodes(mean, s=1.2, lo=-3.0, hi=4.5, step=QSTEP):
    Phi = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    edges = [-40.0] + [lo + i * step for i in range(int(round((hi - lo) / step)) + 1)] + [40.0]
    mu = math.log(mean) - 0.5 * s * s
    qs, ps = [], []
    for l, u in zip(edges[:-1], edges[1:]):
        pr = Phi(u) - Phi(l)
        m = math.exp(0.5 * s * s) * (Phi(u - s) - Phi(l - s)) / pr
        qs.append(math.exp(mu) * m); ps.append(pr)
    ps = np.array(ps); ps /= ps.sum()
    qs = np.array(qs)
    cap = os.environ.get('DP_QCAP')
    if cap: qs = np.minimum(qs, float(cap))
    return qs, ps


def znodes(sigma_bps):
    s = sigma_bps * 1e-4 / H
    w = np.array([math.exp(-0.5 * (m / s) ** 2) for m in range(-MZ, MZ + 1)])
    return w / w.sum()


def phase_probs(lam):
    p0 = math.exp(-lam); p1 = lam * p0
    h0 = 1.0 - p0
    h1 = (1.0 - p0 - p1) / (1.0 - p0)
    h2 = 1.0 - h1 / (lam / h0 - 1.0)          # so the chain's mean order count is exactly lam
    return np.array([h0, h1, h2])


@njit(cache=False)
def w2pos(v):
    """fractional index of rival displacement v (lattice units) on the W2L grid."""
    if v <= W2L[0]: return 0.0
    if v >= W2L[N2 - 1]: return float(N2 - 1)
    lo = 0; hi = N2 - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if W2L[mid] <= v: lo = mid
        else: hi = mid
    return lo + (v - W2L[lo]) / (W2L[hi] - W2L[lo])


@njit(parallel=True, cache=False)
def build_geo(Q):
    nq = Q.shape[0]
    ed = np.zeros((NW, N2, NA, nq), np.float64)
    posw = np.zeros((NW, N2, NA, nq), np.float32)
    pos2 = np.zeros((NW, N2, NA, nq), np.float32)
    KB = np.zeros((NW, N2, NA), np.int16)
    for iw in prange(NW):
        wl = iw - W0
        y1 = Y0 * math.exp(0.5 * wl * H); x1 = KK / y1
        for i2 in range(N2):
            y2 = Y0 * math.exp(0.5 * W2L[i2] * H)
            for ia in range(NA):
                al = AMINL + ia
                if al < wl: al = wl
                ga = math.exp(-(al - wl) * H)
                r = math.sqrt(ga / G2)
                kb = 0
                for k in range(nq):
                    q = Q[k]
                    u1 = (r * (y2 + G2 * q) - y1) / (ga + r * G2)
                    if u1 < 0.0: u1 = 0.0
                    elif u1 > q: u1 = q
                    u2 = q - u1
                    if u1 > 1e-4:
                        y1n = y1 + u1 * ga
                        ed[iw, i2, ia, k] = u1 - (x1 - KK / y1n) * P0
                        pw = 2.0 * math.log(y1n / Y0) / H + W0
                        p2 = float(i2)
                        if u2 > 1e-4:
                            p2 = w2pos(2.0 * math.log((y2 + u2 * G2) / Y0) / H)
                        if pw > NW - 1: pw = NW - 1
                        posw[iw, i2, ia, k] = pw; pos2[iw, i2, ia, k] = p2
                    else:
                        kb = k + 1
                KB[iw, i2, ia] = kb
    pos2nc = np.zeros((N2, nq), np.float32)
    for i2 in range(N2):
        y2 = Y0 * math.exp(0.5 * W2L[i2] * H)
        for k in range(nq):
            pos2nc[i2, k] = w2pos(2.0 * math.log((y2 + G2 * Q[k]) / Y0) / H)
    return ed, posw, pos2, KB, pos2nc


@njit(cache=False)
def bil(V, pw, p2):
    i = int(pw); j = int(p2)
    if i >= V.shape[0] - 1: i = V.shape[0] - 2
    if j >= V.shape[1] - 1: j = V.shape[1] - 2
    if i < 0: i = 0
    if j < 0: j = 0
    f = pw - i; g = p2 - j
    return (V[i, j] * (1 - f) + V[i + 1, j] * f) * (1 - g) + (V[i, j + 1] * (1 - f) + V[i + 1, j + 1] * f) * g


@njit(parallel=True, cache=False)
def build_G(VD, ed, posw, pos2, KB, PQ):
    nq = PQ.shape[0]
    GB = np.zeros((NW, N2, NA)); GS = np.zeros((NW, N2, NA))
    for iw in prange(NW):
        miw = NW - 1 - iw
        for i2 in range(N2):
            mi2 = N2 - 1 - i2
            for ia in range(NA):
                acc = 0.0
                for k in range(KB[iw, i2, ia], nq):
                    acc += PQ[k] * (ed[iw, i2, ia, k] + bil(VD, posw[iw, i2, ia, k], pos2[iw, i2, ia, k]))
                GB[iw, i2, ia] = acc
                acc = 0.0
                for k in range(KB[miw, mi2, ia], nq):
                    acc += PQ[k] * (ed[miw, mi2, ia, k] + bil(VD, (NW - 1) - posw[miw, mi2, ia, k], (N2 - 1) - pos2[miw, mi2, ia, k]))
                GS[iw, i2, ia] = acc
    return GB, GS


@njit(parallel=True, cache=False)
def step_end(VD0, VN0, PZ, SQ, EW):
    """S(w, w2, a, b): value of ending the step with quotes (a, b) in force."""
    S = np.zeros((NW, N2, NA, NA))
    for iw in prange(NW):
        wl = iw - W0
        for i2 in range(N2):
            l2 = int(W2L[i2])
            for ia in range(NA):
                al = AMINL + ia
                if al < wl: al = wl
                for ib in range(NA):
                    bl = AMINL + ib
                    if bl < -wl: bl = -wl
                    acc = 0.0
                    for m in range(-MZ, MZ + 1):
                        i2c = l2 - m
                        if i2c < -FB: i2c = -FB
                        elif i2c > FB: i2c = FB
                        i2c += FB
                        ac = al - m; bc = bl + m
                        iwc = iw - m
                        if iwc < 0: iwc = 0
                        elif iwc > NW - 1: iwc = NW - 1
                        if ac < 0:
                            iwn = wl - al + W0
                            if iwn < 0: iwn = 0
                            acc += PZ[m + MZ] * (VD0[iwn, i2c] - EW[NW - 1 - iwc] * SQ[-ac])
                        elif bc < 0:
                            iwn = wl + bl + W0
                            if iwn > NW - 1: iwn = NW - 1
                            acc += PZ[m + MZ] * (VD0[iwn, i2c] - EW[iwc] * SQ[-bc])
                        else:
                            iac = ia - m
                            if iac < 0: iac = 0
                            elif iac > NA - 1: iac = NA - 1
                            ibc = ib + m
                            if ibc < 0: ibc = 0
                            elif ibc > NA - 1: ibc = NA - 1
                            acc += PZ[m + MZ] * VN0[iwc, i2c, iac, ibc]
                    S[iw, i2, ia, ib] = acc
    return S


@njit(parallel=True, cache=False)
def passive(VNnext, GB, GS, KB, pos2nc, PQ, hj, S, i2lo, i2hi):
    """V_N for one phase: hj * (retail order next) + (1 - hj) * (step ends)."""
    out = np.zeros((NW, i2hi - i2lo, NA, NA))
    for iw in prange(NW):
        miw = NW - 1 - iw
        for i2 in range(i2lo, i2hi):
            mi2 = N2 - 1 - i2
            for ia in range(NA):
                kb = KB[iw, i2, ia]; gb = GB[iw, i2, ia]
                for ib in range(NA):
                    ks = KB[miw, mi2, ib]
                    nc = 0.0
                    for k in range(kb):
                        p2 = pos2nc[i2, k]; j = int(p2)
                        if j >= N2 - 1: j = N2 - 2
                        f = p2 - j
                        nc += PQ[k] * (VNnext[iw, j, ia, ib] * (1 - f) + VNnext[iw, j + 1, ia, ib] * f)
                    for k in range(ks):
                        p2 = (N2 - 1) - pos2nc[mi2, k]; j = int(p2)
                        if j >= N2 - 1: j = N2 - 2
                        if j < 0: j = 0
                        f = p2 - j
                        nc += PQ[k] * (VNnext[iw, j, ia, ib] * (1 - f) + VNnext[iw, j + 1, ia, ib] * f)
                    out[iw, i2 - i2lo, ia, ib] = hj * 0.5 * (gb + GS[iw, i2, ib] + nc) + (1 - hj) * S[iw, i2, ia, ib]
    return out


@njit(parallel=True, cache=False)
def decide(VN, fixed_fee_l):
    """max over (a, b) at each decision state; fixed_fee_l >= 0 evaluates a constant-fee policy instead."""
    n2 = VN.shape[1]
    VD = np.zeros((NW, n2)); IA = np.zeros((NW, n2), np.int16); IB = np.zeros((NW, n2), np.int16)
    for iw in prange(NW):
        wl = iw - W0
        for i2 in range(n2):
            if fixed_fee_l >= 0:
                ia = wl + fixed_fee_l - AMINL; ib = -wl + fixed_fee_l - AMINL
                if ia < 0: ia = 0
                if ia > NA - 1: ia = NA - 1
                if ib < 0: ib = 0
                if ib > NA - 1: ib = NA - 1
                VD[iw, i2] = VN[iw, i2, ia, ib]; IA[iw, i2] = ia; IB[iw, i2] = ib
            else:
                best = -1e300; bi = 0; bj = 0
                for ia in range(NA):
                    al = AMINL + ia
                    if al < wl: al = wl
                    if al > MLO and al < MHI: continue
                    for ib in range(NA):
                        bl = AMINL + ib
                        if bl < -wl: bl = -wl
                        if bl > MLO and bl < MHI: continue
                        v = VN[iw, i2, ia, ib]
                        if v > best: best = v; bi = ia; bj = ib
                VD[iw, i2] = best; IA[iw, i2] = bi; IB[iw, i2] = bj
    return VD, IA, IB


def solve(lam, sigma_bps, size_mean, fixed_fee_l=-1, tol=2e-7, max_sweeps=600, verbose=True):
    Q, PQ = qnodes(size_mean)
    PZ = znodes(sigma_bps)
    hs = phase_probs(lam)
    SQ = np.array([(1.0 - math.exp(-0.5 * n * H)) ** 2 for n in range(0, 1200)])
    if os.environ.get('DP_NOARBREW'): SQ = SQ * 0.0
    EW = np.array([Y0 * math.exp(0.5 * (iw - W0) * H) for iw in range(NW)])   # Y0 e^{w/2}; mirrored index gives e^{-w/2}
    t0 = time.time()
    ed, posw, pos2, KB, pos2nc = build_geo(Q)
    if verbose: print(f'geometry {time.time()-t0:.1f}s  nq {len(Q)}  h {hs}  grid NW {NW} N2 {N2} NA {NA}', flush=True)
    VD0 = np.zeros((NW, NB)); VN0 = np.zeros((NW, NB, NA, NA))
    VN2 = np.zeros((NW, N2, NA, NA))
    g = 0.0
    lo, hi = C2 - FB, C2 + FB + 1
    for it in range(max_sweeps):
        S = step_end(VD0, VN0, PZ, SQ, EW)
        VD2, IA2, IB2 = decide(VN2, fixed_fee_l)
        GB2, GS2 = build_G(VD2, ed, posw, pos2, KB, PQ)
        VN2 = passive(VN2, GB2, GS2, KB, pos2nc, PQ, hs[2], S, 0, N2)
        VD2, IA2, IB2 = decide(VN2, fixed_fee_l)
        GB2, GS2 = build_G(VD2, ed, posw, pos2, KB, PQ)
        VN1 = passive(VN2, GB2, GS2, KB, pos2nc, PQ, hs[1], S, 0, N2)
        VD1, IA1, IB1 = decide(VN1, fixed_fee_l)
        GB1, GS1 = build_G(VD1, ed, posw, pos2, KB, PQ)
        VN0n = passive(VN1, GB1, GS1, KB, pos2nc, PQ, hs[0], S, lo, hi)
        VD0n, IA0, IB0 = decide(VN0n, fixed_fee_l)
        c0 = VD0n[W0, FB]
        VD0n -= c0; VN0n -= c0      # VN2 is already level with the normalised cross-step arrays
        diff = np.abs(VD0n - VD0).max()
        VD0, VN0 = VD0n, VN0n
        g = c0
        if verbose and (it % 10 == 9 or diff < tol or it < 3):
            print(f'sweep {it+1} t {time.time()-t0:.0f}s gain/step {g:.7f} -> {g*1e4:.3f} per run  diff {diff:.2e}', flush=True)
        if diff < tol: break
    return dict(g=g, VD=(VD0, VD1, VD2), VN=(VN0, VN1, VN2), IA=(IA0, IA1, IA2), IB=(IB0, IB1, IB2), hs=hs)


def refine(VN, IA, IB):
    """Sub-lattice optimum by a parabola through the argmax and its neighbours. Returns effective offsets in bps."""
    n2 = VN.shape[1]
    A = np.zeros((NW, n2)); B = np.zeros((NW, n2))
    for iw in range(NW):
        wl = iw - W0
        for i2 in range(n2):
            ia = int(IA[iw, i2]); ib = int(IB[iw, i2])
            al = float(AMINL + ia); bl = float(AMINL + ib)
            if AMINL + ia <= wl: al = float(wl)
            elif MLO != MHI and (AMINL + ia - 1 > MLO and AMINL + ia - 1 < MHI or AMINL + ia + 1 > MLO and AMINL + ia + 1 < MHI): pass
            elif 0 < ia < NA - 1 and AMINL + ia - 1 >= wl:
                vm, v0, vp = VN[iw, i2, ia - 1, ib], VN[iw, i2, ia, ib], VN[iw, i2, ia + 1, ib]
                den = vm - 2 * v0 + vp
                if den < 0: al += max(-0.5, min(0.5, 0.5 * (vm - vp) / den))
            if AMINL + ib <= -wl: bl = float(-wl)
            elif MLO != MHI and (AMINL + ib - 1 > MLO and AMINL + ib - 1 < MHI or AMINL + ib + 1 > MLO and AMINL + ib + 1 < MHI): pass
            elif 0 < ib < NA - 1 and AMINL + ib - 1 >= -wl:
                vm, v0, vp = VN[iw, i2, ia, ib - 1], VN[iw, i2, ia, ib], VN[iw, i2, ia, ib + 1]
                den = vm - 2 * v0 + vp
                if den < 0: bl += max(-0.5, min(0.5, 0.5 * (vm - vp) / den))
            A[iw, i2] = al * H * 1e4; B[iw, i2] = bl * H * 1e4
    return A, B


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'fixed':
        fee = float(sys.argv[2])
        lam, sg, sz = (float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (0.8, 9.45, 20.0)
        r = solve(lam, sg, sz, fixed_fee_l=int(round(fee / 5.0)))
        print(f'FIXED {fee} bps: {r["g"]*1e4:.3f} per run')
    else:
        lam, sg, sz, out = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
        r = solve(lam, sg, sz)
        tabs = {}
        for j in range(3):
            A, B = refine(r['VN'][j], r['IA'][j], r['IB'][j])
            tabs[f'A{j}'] = A.round(3).tolist(); tabs[f'B{j}'] = B.round(3).tolist()
        tabs.update(dict(g=r['g'], lam=lam, sigma=sg, size=sz, H_bps=H * 1e4, NW=NW, W0=W0, N2=N2, C2=C2, FB=FB,
                         W2L=W2L.tolist(), VD0=r['VD'][0].round(6).tolist(), VD1=r['VD'][1].round(6).tolist()))
        json.dump(tabs, open(out, 'w'))
        np.savez_compressed(out.replace('.json', '_vd.npz'), VD0=r['VD'][0], VD1=r['VD'][1], VD2=r['VD'][2])
        if os.environ.get('DP_SAVEVN'):
            for j in range(3): np.save(out.replace('.json', f'_VN{j}.npy'), r['VN'][j].astype(np.float32))
        print(f'SOLVED lam {lam} sigma {sg} size {sz}: {r["g"]*1e4:.3f} per run -> {out}')
