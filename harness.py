"""V2 paired-edge / gas audit harness for amm-challenge @ 6b6921f8.

Usage (from checkout root, after scratch/setup.sh and the instrumentation patch):
  . scratch/env.sh && python scratch/harness.py STRATEGY.sol SEED_START SEED_END OUT.json [--other OTHER.sol]

Without --other: runs STRATEGY twice independently (reproducibility check).
With --other: runs STRATEGY and OTHER separately (each vs VanillaStrategy, never in one
market) and reports paired diff = edge(STRATEGY) - edge(OTHER) per seed.
Each run is one amm_sim_rs.run_batch(X, Vanilla, configs, 8) call; EVM gas stats are
reset before and read after each run. Any OutOfGas / revert / halt / bad-return in the
strategy's callbacks marks the run invalid; an invalid run makes the result invalid.
"""
import hashlib, json, math, sys, time
from pathlib import Path

import amm_sim_rs
from amm_competition.competition.config import (
    BASELINE_SETTINGS, BASELINE_VARIANCE, build_base_config, resolve_n_workers)
from amm_competition.competition.match import MatchRunner
from amm_competition.evm.baseline import get_vanilla_bytecode_and_abi
from amm_competition.evm.compiler import SolidityCompiler

N_WORKERS = 8
ERR_KEYS = ("oog", "revert", "other_halt", "tx_error", "bad_return")


def build_configs(seed_start, seed_end):
    """Exactly MatchRunner._build_configs (default_rng(seed) draws size, rate, sigma; seed=i),
    built for 0..seed_end-1 and sliced, so seed i gets the identical config the runner makes."""
    runner = MatchRunner(n_simulations=seed_end, config=build_base_config(seed=None),
                         n_workers=N_WORKERS, variance=BASELINE_VARIANCE)
    cfgs = runner._build_configs()[seed_start:seed_end]
    assert [c.seed for c in cfgs] == list(range(seed_start, seed_end))
    return cfgs


def compile_src(path):
    src = Path(path).read_text()
    t = time.time()
    res = SolidityCompiler().compile(src)
    dt = time.time() - t
    if not res.success:
        raise RuntimeError("compile failed: " + "; ".join(res.errors or []))
    return src, list(res.bytecode), dt


def run(label, bytecode, vanilla, cfgs):
    amm_sim_rs.gas_stats_reset()
    t = time.time()
    err = None
    try:
        br = amm_sim_rs.run_batch(bytecode, vanilla, cfgs, N_WORKERS)
        edges = {r.seed: (r.edges["submission"], r.edges["normalizer"]) for r in br.results}
    except Exception as e:  # e.g. afterInitialize OOG/revert propagates as error
        err, edges = f"{type(e).__name__}: {e}", {}
    dt = time.time() - t
    stats = amm_sim_rs.gas_stats()
    sub = [s for s in stats if s["role"] == "Submission"]
    errs = {k: sum(s[k] for s in sub) for k in ERR_KEYS}
    swap = [s for s in sub if s["callback"] == "afterSwap"]
    valid = err is None and not any(errs.values()) and len(edges) == len(cfgs)
    return {"label": label, "seconds": round(dt, 3), "n_sims": len(cfgs), "error": err,
            "valid": valid, "submission_errors": errs,
            "max_ok_gas_afterSwap": max((s["max_ok_gas"] for s in swap), default=0),
            "max_ok_gas_all": max((s["max_ok_gas"] for s in sub), default=0),
            "stats": stats}, edges


def paired(ea, eb, seeds):
    rows = [(s, ea[s][0] - eb[s][0], ea[s][0], eb[s][0]) for s in seeds]
    d = [r[1] for r in rows]
    n = len(d)
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    worst = sorted(rows, key=lambda r: r[1])[:5]
    return {"n": n, "mean_diff": m, "se": sd / math.sqrt(n), "sd": sd,
            "n_nonzero": sum(1 for x in d if x != 0.0), "max_abs_diff": max(abs(x) for x in d),
            "worst": [{"seed": s, "diff": x, "edge": a, "v2_edge": b} for s, x, a, b in worst]}


def main():
    a = sys.argv[1:]
    other = None
    if "--other" in a:
        i = a.index("--other"); other = a[i + 1]; del a[i:i + 2]
    path, s0, s1, out = a[0], int(a[1]), int(a[2]), a[3]
    src, bc, t_comp = compile_src(path)
    vanilla = list(get_vanilla_bytecode_and_abi()[0])
    cfgs = build_configs(s0, s1)
    seeds = list(range(s0, s1))
    ra, ea = run("A", bc, vanilla, cfgs)
    if other:
        _, bc2, t2 = compile_src(other)
        rb, eb = run("B", bc2, vanilla, cfgs)
    else:
        rb, eb = run("A_repeat", bc, vanilla, cfgs)
    ok = ra["valid"] and rb["valid"]
    res = {"sha256": hashlib.sha256(src.encode()).hexdigest(), "seeds": [s0, s1],
           "compile_seconds": round(t_comp, 3), "runs": [ra, rb], "valid": ok,
           # paired is computed whenever both runs completed all seeds; it is labelled
           # invalid (valid=false) if any OOG/revert occurred, never silently dropped.
           "paired": paired(ea, eb, seeds) if (len(ea) == len(eb) == len(seeds)) else {"n": 0},
           "mean_edge_A": sum(ea[s][0] for s in seeds) / len(seeds) if ea else None,
           "mean_vanilla_edge_A": sum(ea[s][1] for s in seeds) / len(seeds) if ea else None}
    Path(out).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "runs"}, indent=1)[:3000])
    for r in (ra, rb):
        print(r["label"], r["seconds"], r["valid"], r["submission_errors"], r["max_ok_gas_all"])
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
