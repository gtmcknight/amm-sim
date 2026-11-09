"""Score a policy on a range of replica seeds, showing it only what afterSwap shows a contract.

usage: python3 -I run.py <policy> <seed0> <n> <out.json> [key=val ...]
  policy   perfect            the solved policy with the true price and rival spot (not blind)
           gauss              real.py's Gaussian filter      e.g. soft=1 qm=qm_k1e-5.json
           lattice            latt.py's lattice filter       e.g. qm=qm_k1e-5.json
           module:Class       your own: put module.py beside this file. Class(T, opt) with
                              init() -> (bid_fee, ask_fee) and on_trade(is_buy, amount_x, amount_y, timestamp,
                              reserve_x, reserve_y) -> (bid_fee, ask_fee). is_buy = the pool bought X.
                              T is pol.json (default pol_mid.json, or pol=<file>), opt the key=val pairs.
  Any seed range, so long runs can be cut into chunks; pair.py joins and compares them.

A blind policy never receives the true price, the rival's spot, the arb flag, the order count or the run's
parameters. If it keeps `m` (ln of its price estimate) the price error is reported; if it sets `first` and
`is_arb` on each call, so is the share of first trades it misread.
"""
import sys, os, math, json, time, importlib
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replica2 as R
from evalpol import DPPolicy, load, stats, CALIB

DEFAULT_POL = os.path.join(HERE, 'pol_mid.json')


class Blind:
    """What the engine shows a strategy, and nothing else."""
    wants_j = True
    def __init__(self, inner):
        self.inner = inner; self.nfirst = 0; self.nmis = 0; self.se = 0.0; self.nse = 0
    def init(self, sigma, lam, size):
        return self.inner.init()
    def on_trade(self, is_buy, ax, ay, t, x, y, arb, p, s2, j):
        inner = self.inner
        if getattr(inner, 'needs_flag', False): out = inner.on_trade(is_buy, ax, ay, t, x, y, arb)   # diagnostic policies only
        else: out = inner.on_trade(is_buy, ax, ay, t, x, y)
        if getattr(inner, 'first', False):
            self.nfirst += 1
            if bool(getattr(inner, 'is_arb', False)) != bool(arb): self.nmis += 1
        m = getattr(inner, 'm', None)
        if m is not None:
            e = (m - math.log(p)) * 1e4
            self.se += e * e; self.nse += 1
        return out


def make(policy, T, opt):
    if policy == 'perfect': return DPPolicy(T), False
    if policy == 'gauss':
        import real
        return real.RealPolicy(T, opt), True
    if policy == 'lattice':
        import latt
        return latt.LatticePolicy(T, opt), True
    mod, _, cls = policy.partition(':')
    return getattr(importlib.import_module(mod), cls)(T, opt), True


def work(a):
    policy, opt, seeds, pol_path = a
    T = load(pol_path); out = []
    for s in seeds:
        obj, blind = make(policy, T, opt)
        w = Blind(obj) if blind else obj
        r = R.run(s, w)
        row = {'seed': s, 'edge': r['edge'], 'retail': r['retail'], 'arb': r['arb'], 'rv': r['rv'], 'av': r['av']}
        if blind: row.update(first=w.nfirst, misread=w.nmis, se=w.se, nse=w.nse)
        out.append(row)
    return out


def run_policy(policy, opt, seeds, pol_path=DEFAULT_POL, procs=None, chunk=8):
    tasks = [(policy, opt, seeds[i:i + chunk], pol_path) for i in range(0, len(seeds), chunk)]
    with Pool(procs or os.cpu_count()) as pool:
        res = pool.map(work, tasks, chunksize=1)
    return sorted((r for b in res for r in b), key=lambda r: r['seed'])


_ha = None
def ha_rows():
    global _ha
    if _ha is None:
        _ha = {r['seed']: r['edge'] for r in json.load(open(CALIB)) if r['kind'] == 'HA'}
    return _ha


def line(label, rows):
    n = len(rows); mean = lambda k: sum(r[k] for r in rows) / n
    out = f'{label:28s} n {n}  edge {mean("edge"):8.3f} retail {mean("retail"):8.3f} arb {mean("arb"):7.3f} rv {mean("rv"):6.0f} av {mean("av"):6.0f}'
    ha = ha_rows()
    if all(r['seed'] in ha for r in rows) and n > 1:
        m, se = stats([r['edge'] - ha[r['seed']] for r in rows])
        out += f'  vs HA {m:+.3f} se {se:.3f}'
    if rows and 'first' in rows[0]:
        f = sum(r['first'] for r in rows); q = sum(r['nse'] for r in rows)
        if f: out += f'  misread {sum(r["misread"] for r in rows) / f:.2%}'
        if q: out += f'  p rms {math.sqrt(sum(r["se"] for r in rows) / q):.1f} bps'
    return out


if __name__ == '__main__':
    policy, seed0, n, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    opt = {}; pol_path = DEFAULT_POL
    for item in sys.argv[5:]:
        k, _, val = item.partition('=')
        if k == 'pol': pol_path = val if os.path.isabs(val) else os.path.join(HERE, val)
        elif k == 'qm': opt[k] = val if os.path.isabs(val) else os.path.join(HERE, val)
        else:
            try: opt[k] = float(val)
            except ValueError: opt[k] = val
    t0 = time.time()
    rows = run_policy(policy, opt, list(range(seed0, seed0 + n)), pol_path)
    json.dump({'policy': policy, 'opt': {k: (os.path.basename(v) if isinstance(v, str) else v) for k, v in opt.items()}, 'rows': rows}, open(out, 'w'))
    print(line(policy, rows) + f' ({time.time()-t0:.0f}s) -> {out}')
