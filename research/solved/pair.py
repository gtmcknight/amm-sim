"""Pair two sets of run.py results on their common seeds.

usage: python3 -I pair.py <candidate.json[,more parts]> <reference.json[,more parts]>
Prints paired{n, mean_diff, se, worst5} and each side's own line (with vs HA where HA rows exist: seeds 10000..12047).
"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run
from evalpol import stats


def rows_of(spec):
    rows = {}
    for path in spec.split(','):
        for r in json.load(open(path))['rows']: rows[r['seed']] = r
    return rows


if __name__ == '__main__':
    a, b = rows_of(sys.argv[1]), rows_of(sys.argv[2])
    seeds = sorted(set(a) & set(b))
    if len(seeds) < 2: sys.exit('fewer than two common seeds')
    d = [(a[s]['edge'] - b[s]['edge'], s) for s in seeds]
    m, se = stats([x[0] for x in d])
    worst = sorted(d)[:5]
    print(run.line('candidate', [a[s] for s in seeds]))
    print(run.line('reference', [b[s] for s in seeds]))
    print(json.dumps({'paired': {'n': len(seeds), 'mean_diff': round(m, 4), 'se': round(se, 4), 'worst5': [[s, round(v, 3)] for v, s in worst]}}))
