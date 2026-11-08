"""Edge sum of STRATEGY.sol vs the 30 bps Vanilla on seeds S0..S1-1, configs exactly as MatchRunner. Optional 4th arg: workers."""
import sys, time
sys.path.insert(0, 'scratch')
from harness import build_configs, compile_src
import amm_sim_rs
from amm_competition.evm.baseline import get_vanilla_bytecode_and_abi
path, s0, s1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8
src, bytecode, _ = compile_src(path)
vanilla = list(get_vanilla_bytecode_and_abi()[0])
cfgs = build_configs(s0, s1)
t = time.time()
br = amm_sim_rs.run_batch(bytecode, vanilla, cfgs, workers)
edges = [r.edges["submission"] for r in br.results]
print(f"{path} seeds {s0}..{s1-1} n={len(edges)} sum={sum(edges)!r} mean={sum(edges)/len(edges)!r} seconds={time.time()-t:.1f}", flush=True)
