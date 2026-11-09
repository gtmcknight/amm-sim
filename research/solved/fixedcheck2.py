import sys, os
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replica2 as R
CFG = (20.0, 0.8, 0.000945)
QCAP = float(sys.argv[1]) if len(sys.argv) > 1 else None
def ev(a):
    fee, seeds = a
    out = []
    for s in seeds:
        r = R.run(s, R.Fixed(fee), cfg=CFG, qcap=QCAP)
        out.append((r['edge'], r['retail'], r['arb'], r['rv'], r['av'], r['fees']))
    return out
if __name__ == '__main__':
    seeds = list(range(30000, 32000))
    with Pool(14) as pool:
        for fee in (0.003, 0.0075):
            res = pool.map(ev, [(fee, seeds[i:i+25]) for i in range(0, len(seeds), 25)])
            rows = [x for b in res for x in b]
            n = len(rows); m = [sum(r[i] for r in rows)/n for i in range(6)]
            sd = (sum((r[0]-m[0])**2 for r in rows)/(n-1))**0.5
            print(f'fixed {fee*1e4:.0f} bps qcap {QCAP}: edge {m[0]:.2f} (se {sd/n**0.5:.2f}) retail {m[1]:.2f} arb {m[2]:.2f} rv {m[3]:.0f} av {m[4]:.0f} fees {m[5]:.2f} fees-edge {m[5]-m[0]:.2f}')
