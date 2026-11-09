"""Per-seed check values for a port: edge of each reference policy on replica seeds 10000..10002.
usage: python3 -I gates.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replica2 as R
from evalpol import DPPolicy, load
import real, latt

T = load(os.path.join(HERE, 'pol_mid.json'))
QM = os.path.join(HERE, 'qm_k1e-5.json')
print('seed   perfect-info      gaussian+plain    gaussian+qm       lattice+qm')
for seed in (10000, 10001, 10002):
    a = R.run(seed, DPPolicy(T))['edge']
    b = R.run(seed, real.RealPolicy(T, {'soft': 1.0}))['edge']
    c = R.run(seed, real.RealPolicy(T, {'soft': 1.0, 'qm': QM}))['edge']
    d = R.run(seed, latt.LatticePolicy(T, {'qm': QM}))['edge']
    print(f'{seed}  {a:.6f}  {b:.6f}  {c:.6f}  {d:.6f}')
