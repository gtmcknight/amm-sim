# Simple AMM: the filter brief (2026-11-09)

Reference material for IMD goals on Paradigm's AMM fee challenge (paradigm.xyz/puzzles/amm, simulator github.com/benedictbrady/amm-challenge at 6b6921f8). The goal's objective points here; this file carries what did not fit in 3,000 characters.

## Target

RS2 is our file on the board: 520.05, 27th of 744. 10th is 524.66, 1st 528.40 (top five within 0.3). Nothing is entered below a paired gain of +4.6 over RS2 on 4,000 fresh seeds, confirmed on the real engine. Do not spend items on tenths or on overlays of RS2: inside RS2's fee family the measured ceiling is about +1.2 (goal e64e1149, 124 items).

RS2 code: the `code` field of https://api.imd.fun/artifacts/19f2ec857df536e8ab62ab1da89ec6623332521ce46849f15bccff402c63e1e5 (sha256 f24b6ca198b744c380842c3a17964a6dc21f311bb04984b26733afa3fee8eaf2).

## What is measured (pure-Python replica of the engine, `replica.py` here, 1,000 paired seeds)

| Policy | Edge | Retail edge | Arb edge | Retail vol Y | Arb vol Y | Avg fee bps |
|---|---|---|---|---|---|---|
| Fixed 30 bps (the rival's rule) | 342 | 572 | -230 | 79.7k | 41.7k | 30 |
| Fixed 30 bps, no retail flow at all | -3 | 0 | -3 | 0 | 6.3k | 30 |
| Fixed 35 bps | 350 | 559 | -208 | 70.9k | 35.4k | 35 |
| True p, quote p(1+30bps) / p(1-30bps) | 498 | 502 | -5 | 51.8k | 0.5k | 81 |
| True p, best 7-parameter quadratic rule | 521 | 548 | -28 | 71.8k | 18.2k | 40 |
| True p, best 35-knot table (`oracle_table.json`) | 532.5 | | | | | |
| Same table, p known only at own arb trades | 507.6 | | | | | |
| Table retrained for p from own arbs only | 519.2 | | | | | |
| True p and the rival pool's exact spot, table + 18 knots | 533.4 | | | | | |

The replica reads 3 to 5 above the board (fixed 30 bps: 342 here, 338.6 on the board), so 532.5 is about 528 board. Paired differences on common seeds are exact to about 0.05.

What it means:
- 98% of arb loss is retail-induced. A large lognormal order knocks the spot out of the fee band and the arbitrageur unwinds it at once, taking about twice the impact gain the order paid. Price drift alone costs 3 per run.
- Retail edge decomposes into fee revenue (240 at fixed 30 bps) plus impact gain, the sum of dy^2/y over fills (332). The arb claws back 230 of the impact gain. The whole game is keeping the impact gain while keeping the flow share.
- The top five sit at the perfect-price ceiling of "quote on your own displacement". Their fees average 35.3 bps on both sides, retail volume 77.9k, arb volume 23.7k (more arb trades than ours, at near-zero profit each).
- Inside that structure the quality of the price estimate is worth about 13 points. RS2 (520 board) has about 8 of them left to take. Knowing the rival pool's position exactly is worth +0.9; knowing the run's sigma, arrival rate and order size, +0.04.
- The optimum exploits the naive arbitrageur: after a displacement D of the spot from p, set the fee on that side to about D minus 7 bps. The arb then trades next step, profits almost nothing, and corrects the pool. The other side quotes about 35 bps from p. Blocking the arb entirely and waiting for retail to correct the pool measured worse. Doing this needs D, hence p, to a few bps.

## What the organizer and the leaders say

- Benedict Brady, "Learnings from Optimization Arena" (benedict.dev/optimization-arena-learnings, 2026-04-09): April's top 8 were "two black box neural networks implemented in Solidity, a few compact elegantly designed mathematical models that were 200-300 lines of code, and a few kitchen sink approaches with over 100 tuned constants, and one submission that attempted to fully model the competitor AMM". "All the tech trees end in the same spot." Key ideas: "estimating probabilities of arb trades and skewing based on information from the arbs, dynamically adjusting widths based on the estimated sim volatility, suppressing the skew from outlier trades." Top solutions "over-exploit" the naive arb bots and the single rival (x.com/bqbrady/status/2021245167714394582). "High scores are driven by breakthroughs not local optimizations."
- The 522 to 528 move (July to October) came as single-day structural jumps by five people independently. Entry names: ComponentLatticeExactSoft and ComponentLatticeDPAll (pxmwxd_eth, 528.14), bayes_v2 (cktbot), FairPriceFilterQuoter (ujiuifs, 523.8 on a first entry), MixZ11 (KaihuaQIN). Read: an exact posterior of the fair price on a grid, and a policy fitted to that posterior.
- Every public file (74 forks mined) is the YQ state-estimation architecture retuned; nobody above 14th has published code.

## Plan by episode

1. FILTER (the prize). An exact posterior of ln(p/spot) on a grid, updated in afterSwap only (the contract sees nothing between its own trades):
   - an own arb trade pins p exactly: spot after = p(1-askFee) when the arb bought X from us, p/(1-bidFee) when it sold;
   - each silent step (no own trade at that timestamp) truncates the posterior to the no-arb band of the fees in force then;
   - GBM diffusion per elapsed step, sigma estimated from arb-to-arb price moves (sigma is 0.0882% to 0.1008% per step across runs);
   - a retail fill is a weak observation of the rival's marginal price through the router split (the rival is always within 30 bps of p at retail time).
   Score a filter two ways on the same seeds: RMS error of its mean in bps, and the score of `oracle_table.json` driven by its mean in place of p, paired against the true-p run (target: within 2 of 532.5 on the replica). Variants, two items each on different machines: 64-bucket grid; mean-and-variance approximation; a small mixture.
2. POLICY. A table or small net over (filter mean, filter sd, own displacement, arb flag), fitted by CMA-ES in the replica, warm-started from the oracle table, decided on the real engine.
3. PORT. Solidity, afterSwap under 245,000 gas and afterInitialize under 245,000, 0 OutOfGas, fees equal to the Python policy to 1e-6 on 256 seeds.
4. CONFIRM. 4,000 fresh seeds from 5148000 up, never reused, paired against RS2 with both arms alone against VanillaStrategy; return per-seed deltas, the retail/arb split and raw gas counters in the result record.
5. RESTARTS. Four items that get only this file and no RS2 code, one per model family. Keep a learnings file of dead ends with numbers.

## Tools

- Numba replica from goal e64e1149: https://api.imd.fun/artifacts/e8a7a2af9039c24b8bb2d3b5fa1c9113606cbf5a480ac07d02ca26750f1752ea (3,721 markets/s, CH mean within 1.1 of the engine). RS2 as a numba port: https://api.imd.fun/artifacts/1b8e8ca5d0da1f0071a9ae18505d6cbff902b88b2fbc34e523afbd212a9a26ce. Retail/arb split harness: https://api.imd.fun/artifacts/33f54e81f3372088e9eced52c0174f310ac348af98ef5727b73785c088679194.
- `replica.py` here: pure Python, 100 sims per second per core, policies get an oracle view (true p, rival spot) for ceiling tests. Levels differ from the Rust engine by about 1%; compare paired only.
- Real engine: `amm_sim_rs.run_batch(X, VanillaStrategy, configs, 8)`, each strategy alone against VanillaStrategy, configs per `MatchRunner._build_configs`. Calibration once: CH on seeds 0..999 = 525.5258821780834. Setup: `setup-fast.sh` in this repo (seconds, no compiler).
