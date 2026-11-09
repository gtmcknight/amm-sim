"""Run tasks across processes; fall back to one process where a pool cannot start.
PROCS=<n> sets the process count (default: every CPU; 1 = no pool)."""
import os


def pmap(fn, tasks):
    tasks = list(tasks)
    n = int(os.environ.get('PROCS', '0') or 0) or (os.cpu_count() or 1)
    if n <= 1 or len(tasks) <= 1:
        return [fn(t) for t in tasks]
    try:
        from multiprocessing import Pool
        pool = Pool(min(n, len(tasks)))
    except Exception:
        return [fn(t) for t in tasks]
    try:
        return pool.map(fn, tasks, chunksize=1)
    finally:
        pool.close(); pool.join()
