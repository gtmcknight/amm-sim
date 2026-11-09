# Simple AMM: the solved game

Written 2026-11-09. An exact dynamic program for the game with perfect information, the policy it gives, and reference code that runs that policy on what `afterSwap` really sees. It is a starting point for a contract, not a contract.

All numbers are from the pure-Python replica (`replica2.py`, line by line from the engine at 6b6921f8), paired on replica seeds 10000..12047 against HA (mean 529.557 on those seeds, rows in `calib_out_2048.json`). Replica levels do not convert to board scores. Paired gaps have matched the engine so far (HA over T: 1.11 here, 1.01 to 1.15 on the engine). Nothing here has run on the Rust engine.

The network's board entry is IB (522.00, 20th): +0.592 se 0.030 over HA on 512 fresh engine seeds (artifact `afd5183e9ff3235334e041c00b0cd19079599a2c6464db95f8c1586712105557`). Board lines below are placed through it.

This replaces the reading in `../filter-brief.md`: the perfect-price table there was a search result, not a ceiling.

## Numbers

| policy | inputs | edge | vs HA |
|---|---|---|---|
| old 35-knot table (`../oracle_table.json`) | true price | 534.53 | +4.97 |
| #1 on the board (IB + 6.40) | real | | about +7.0 |
| T03, the best of the training goals 077d20ed and cc45e1a7 (IB + 0.77 on 2,048 fresh engine seeds) | real | | about +1.4 |
| **solved policy** | true price and rival | 538.26 | **+8.70** se 0.05 |
| solved policy, rival tracked from own trades | true price | 538.06 | +8.50 |
| solved policy, real inputs plus the true arb/retail flag | real + flag | 536.54 | +6.98 se 0.04 |
| lattice filter + `qm` tables | real | 533.82 | **+4.26** se 0.04 |
| Gaussian filter + `qm` tables | real | 533.33 | +3.77 se 0.04 |
| Gaussian filter + plain tables | real | 532.39 | +2.83 se 0.04 |
| top-10 line (IB + 2.66) | | | +3.25 |

## What the solve says

- **Edge is fee revenue.** Edge = fees collected - 22.2 for every policy (22.23 and 22.16 measured at fixed 30 and 75 bps). The 22.2 is loss to price drift and no policy changes it.
- **The money is in big orders.** Half the impact revenue comes from orders above 173 Y, about 66 a run. Capping sizes at 300 Y takes 72 off fixed-30's 571 retail edge.
- **The best quotes move with the rival pool.** Undisplaced, ask/bid offsets from the true price are 29/46 bps with the rival at its low band edge, 28/28 centered, 46/29 at its high edge. Displaced 60 bps or more with the rival's bid at fair: ask fee 0, bid 2 to 26 bps above fair, so the arb unwinds the pool a step at a time for almost nothing.
- **The rival's spot is known from our own trades.** After an order that splits, both pools sit at the same marginal price: rival spot = own spot x 0.997 / (1 - own fee) on a buy, own spot x (1 - own fee) / 0.997 on a sell. Tracking it that way costs 0.19.
- **Run parameters need no adaptation.** Tables solved for each run's own order rate add +0.04. One table.
- **Price between arb pins is the whole problem.** Using the last pin naively costs 28. Under the solved policy 35% of retail trades land in a step the arb just pinned; 23% are six or more steps stale.
- **What separates +4.26 from #1 is one call:** is the first trade of a step the arb or retail. The filter is wrong 16% of the time. With the true answer the same code scores +6.98, level with #1.

## The model (`dp.py`)

State at a decision: own displacement w = ln(own spot / p), rival displacement w2 = ln(rival spot / p), phase (0 just arbed, 1 after the first retail order of the step, 2 after more). Action: ask offset a = ln(ask / p) and bid offset b = ln(p / bid), with a >= w and b >= -w (fees are not negative). Quotes stay in force until our next trade, so the passive value carries them through silent steps and through orders that go only to the rival. Displacements, offsets and price moves sit on a 5 bps lattice; trades use the exact router and constant-product formulas; sizes are a 62-node lognormal. Relative value iteration, 110 sweeps, about 80 s on 14 cores.

Checks: no retail, fixed 30 bps: -3.545 (replica -3.5). Sizes capped at 300 Y, fixed 30 / 75 bps: 334.77 / 359.50 (replica 334.96 se 0.19 / 359.20 se 0.37). Solved value at midpoint parameters 536.82; the policy simulated at those parameters 536.49 se 1.03.

## The reference policy on real inputs (`real.py`, the Gaussian version)

Kept between calls: m (ln of the price estimate), v (its variance), the fees in force fb and fa, own spot after the last call sp, the last timestamp, own retail calls this step cnt, rival spot estimate s2, a flag synced. Constants: sigma = 9.45 bps a step, rho = 0.26, retail fill law lognormal with median 11.12 bps and log-sd 1.176, G = 0.997.

On each `afterSwap(isBuy, amountX, amountY, timestamp, reserveX, reserveY)`:

1. s = reserveY / reserveX. dt = timestamp - last timestamp.
2. If dt >= 1 this is the first own trade of a new step:
   - cnt = 0. No-arb interval of the quotes in force: lo = ln(sp (1 - fb)), hi = ln(sp / (1 - fa)).
   - For each of the dt - 1 steps with no own trade (cap 12): v += sigma^2, then replace (m, v) by the mean and variance of N(m, v) cut to (lo, hi).
   - v += sigma^2 for this step.
   - Arb reading: lp = ln(s (1 - fb)) if isBuy, else ln(s / (1 - fa)). If this trade is the arb, the price is exactly exp(lp).
   - L_arb = density of N(m, v) at lp. Z, mt, vt = mass, mean and variance of N(m, v) on (lo, hi). d = |ln(s / sp)|. L_ret = Z x rho x lognormal density of d.
   - pi = L_arb / (L_arb + L_ret). If pi >= 0.995: m = lp, v = 0. If pi <= 0.005: m = mt, v = vt. Otherwise the two-point mixture: m' = pi lp + (1 - pi) mt, v' = pi (lp - m')^2 + (1 - pi)(vt + (mt - m')^2).
   - The trade counts as an arb if pi > 0.5.
   - Clip s2 into [exp(m) G, exp(m) / G]. synced = false.
3. If the trade is not an arb: on isBuy, cand = s (1 - fb) / G and s2 = min(s2, cand); otherwise cand = s G / (1 - fa) and s2 = max(s2, cand). synced = true when cand replaced s2. cnt += 1, phase = 1 if cnt = 1 else 2. If it is an arb, phase = 0.
4. w = (ln s - m), R = (ln s2 - m), sd = sqrt(v), all in bps.
5. Look up offsets (a, b): bilinear in (w, R), linear between sd levels. Phase 0 uses the band table with R clipped to +-30 bps. Phases 1 and 2 use the `s` tables when synced, else the `c` tables.
6. ask fee = 1 - exp(-(a - w) 1e-4) if a > w else 0. bid fee = 1 - exp(-(b + w) 1e-4) if b > -w else 0. Store fb, fa (clamped to 0..10%), sp = s, the timestamp.

`latt.py` is the same policy with the Gaussian belief replaced by probability mass on 121 cells of 2.5 bps: each step convolves with the price-move kernel, a step with no own trade zeroes the cells where the arb would have traded, and the first trade of a step becomes a mixture of a point mass at the arb reading and the cut prior. It then feeds its mean and sd to the same tables. Worth +0.5 over the Gaussian version.

## Tables

- `pol_mid.json`: `A0 B0 A1 B1 A2 B2` are ask and bid offsets in bps from the price for phases 0, 1, 2. Rows are own displacement, w = (row - 160) x 5 bps, 321 rows. Columns are rival displacement: 13 columns from -30 to +30 bps for phase 0; 49 columns at `W2L` x 5 bps for phases 1 and 2.
- `qm_k1e-5.json`: the same offsets chosen for a price that is only known to within a spread. `S` lists the eight belief sd levels in bps. `A0c B0c` for phase 0; `A1s B1s A1c B1c A2s B2s A2c B2c` for phases 1 and 2, `s` when the rival was synced this step and `c` when its spot is the band-clipped estimate. Each is level x row x column. The file was built with an information weight (kappa = 1e-5, the third argument of `qmdp.py`) that favors quotes the arb will hit, so even level 0 differs from `pol_mid.json`, in about a quarter of the cells; built with kappa 0, level 0 equals it.

## Gates

```
python3 -I gates.py
seed   perfect-info      gaussian+plain    gaussian+qm       lattice+qm
10000  448.261189  443.455598  443.522608  443.663520
10001  576.779199  571.463409  571.623551  571.977293
10002  531.886497  525.168028  525.865859  526.411631

python3 -I evalpol.py pol_mid.json hold                          # 538.261, vs HA +8.704 se 0.047
python3 -I track.py pol_mid.json none rival,count                # +8.704, +8.499
python3 -I real.py pol_mid.json plain:soft=1 qm:soft=1,qm=qm_k1e-5.json    # +2.828, +3.769
python3 -I latt.py pol_mid.json lattice:qm=qm_k1e-5.json         # +4.263 se 0.039 (NSEED=112: +4.212)
python3 -I real.py pol_mid.json flag:oraclearb=1,qm=qm_k1e-5.json          # +6.985: reads the true flag, a diagnostic and not a policy
python3 -I pair.py ref/flag_qm.json ref/lattice_qm.json                    # mean_diff 2.7219 se 0.0209

# solver, needs numpy + numba (uv venv --python 3.12 venv; uv pip install numpy numba)
DP_SAVEVN=1 DP_AMINL=-12 DP_NA=43 python dp.py solve 0.8 9.45 20 pol_mid.json     # 536.821, tables identical to the file here
DP_AMINL=-12 DP_NA=43 python qmdp.py pol_mid.json qm.json 1e-5                    # identical to qm_k1e-5.json
DP_QCAP=300 DP_NW=100 DP_AMINL=-60 DP_NA=91 python dp.py fixed 30                 # 334.772
# on a slow machine add DP_STATE=st.npz DP_SWEEPS=40 and repeat the solve command until it prints SOLVED; same tables
```

The old table scores 445.678 / 572.593 / 527.968 on those three seeds.

## Two tracks for a goal

**Track A, the contract.** In order:

1. `python3 -I gates.py` matches the digits under Gates. Confirm what bounds a port: 250,000 gas a call, 32 storage slots, no inline assembly, the runtime code size limit.
2. Compress, in Python on the replica: the smallest table set that keeps the Gaussian + `qm` policy within 0.2 of +3.77. Things to try: knot subsets, the mirror ask(w, R) = bid(-w, -R), fewer sd levels, one rival mode. Expand a candidate back to the shipped grid, save it in the format of `qm_k1e-5.json` and score it with `run.py gauss 10000 2048 out.json soft=1 qm=<file>` against `ref/gauss_qm.json`.
3. Port steps 1 to 6 of the reference policy above to Solidity with the compressed tables. Gates: fees within 0.01 bps of `real.py` on the callbacks of 20 replica runs; afterSwap peak at most 245,000 gas; no OutOfGas; `amm-match validate` passes.
4. Engine: the port and IB, each alone against VanillaStrategy on the same fresh seeds from 12,000,000 up, paired. The bar is +2.7 over IB on 4,000 seeds.

**Track B, arb or retail.** Plain Python on the replica, so any machine can run it. The reference misreads 16% of the first trades of a step. Reading them all right is worth +2.72 (`ref/flag_qm.json` against `ref/lattice_qm.json`), which is the distance from 7th to the top two. One idea per item, measured alone:

- quotes chosen against the whole lattice posterior instead of its mean and sd (the value arrays come from `DP_SAVEVN=1`);
- keep the arb reading and the retail reading as two explicit hypotheses, and choose the next quotes so the next arb tells them apart;
- per-run estimates of sigma and of the order rate inside the classifier;
- the router likelihood per price hypothesis, each hypothesis carrying its own rival spot;
- a correction trained through the filter, starting from the tables;
- anything else: two items should get this README without this list.

A numba port of `replica2.py` + `latt.py` that matches `gates.py` to the digit is worth an early item; the pure Python lattice takes about a second a run.

**Rules for both.**

- A policy sees what afterSwap sees. `run.py` enforces it; a result from any other harness needs the same blindness.
- Tune on replica seeds 60000 and up. Score once on 10000..12047 and report `pair.py`'s output against the nearest reference in `ref/`.
- Every Track B result carries its misread rate, its price error and what the idea would cost in gas.
- What Track B wins by 0.3 or more goes into Track A's next port.

## Fleet rules (what two earlier goals on this fleet paid to learn)

Goals 077d20ed and cc45e1a7 trained fee heads on these machines on 2026-11-09. The first lost 32 of its first 104 results to blocks, the second 14 of 205. Each cause below comes with the rule it gives.

- **Speed gates (12 results).** Seats have 1 to 32 CPUs, median 8, and a quarter have 4 or fewer. A rule "search only at 300 markets a second" stopped every 2-CPU seat. No item blocks on speed: a slow seat takes Track B idea work, table compression or a smaller engine block, and says how much it finished.
- **A parity gate on synthetic stress paths (6).** T03's Solidity divides by zero at reserves no market reaches, and the harness's stress sequences (trades up to 15% of the reserve) found it; the engine ran it 11 million calls clean. Gate fee parity on callbacks recorded from replica runs. Run stress sequences as well and report them, and write the contract so it cannot revert, but do not gate on them.
- **Engine time (8).** With a 238,000-gas contract the engine did 128 markets in 460 s on 6 CPUs. Engine work runs in 64-seed commands, sized to the seat (256 seeds on a slow one); report n per arm and never fill in a missing seed.
- **Machines that cannot run the wheel (about 1 in 20).** macOS arm64 and other seats that are not Linux x86_64 stop at SETUP. They take Track B or compression, which need only python3.
- **Seats that cannot reach api.imd.fun (2).** Nothing a brief can mend. Give each line of work a spare copy.
- **Refused briefs (eight batches).** The plane refuses a brief that asks for a command's raw text back, and one whose placeholder is missing from an item's vars. Ask for numbers in the JSON result; put every placeholder, `key` included, in every item's vars as a string; keep a filled brief under 2,900 ASCII characters.
- **Canary holds.** A batch wider than five holds the rest behind its first five. Batches of five or fewer start at once.
- **Results.** One JSON object under 60,000 bytes. Code travels as `code_zb64` with its sha256, so the next item starts from the result's URL. Paired statistics carry sum and sumsq so blocks pool; never average standard errors. `valid` is false on any OutOfGas, any revert or an afterSwap peak over 245,000.
- **Seeds.** Keep a ledger; an engine seed is used once. The two goals have taken engine seeds below 9,000,000. This work starts at 12,000,000.
- **Replica against engine.** A port's gain over IB on the engine should sit within 0.15 of its Python twin's gain over IB's port on the replica. If it does not, the port or the replica is wrong: find out which before anything else.

Where that lane stands: IB 0, J5 +0.55, J11 +0.60, T03 +0.77 over IB after about 350 items, which is roughly 13th. Its own planner wrote that the top 10 is out of reach in its remaining rounds.

## Harness

```
python3 -I run.py lattice 60000 256 base.json qm=qm_k1e-5.json             # a reference on tuning seeds
python3 -I run.py mymodule:MyPolicy 60000 256 cand.json qm=qm_k1e-5.json    # yours on the same seeds
python3 -I pair.py cand.json base.json                                      # paired{n, mean_diff, se, worst5}
python3 -I run.py mymodule:MyPolicy 10000 512 part0.json qm=qm_k1e-5.json   # the holdout, in chunks
python3 -I pair.py part0.json,part1.json,part2.json,part3.json ref/lattice_qm.json
```

`run.py` takes any seed range and writes per-seed rows. Policies are `perfect`, `gauss`, `lattice`, or `module:Class` for your own; `example_policy.py` is the smallest one it accepts. `ref/` holds per-seed results on the holdout for `perfect`, `gauss_plain`, `gauss_qm`, `lattice_qm` and `flag_qm` (the true-flag diagnostic), so nobody reruns them.

## Open

1. **The contract.** The tables are 8 MB of JSON and the lattice is 121 cells; the budget is 250k gas. A first port is the Gaussian filter with the six plain tables (+2.83): O(1) state, and it needs ln, exp and a normal CDF. Match `gates.py` to the digit before changing anything, then measure what coarser knots cost with the same harness.
2. **The engine.** Run the port and IB on the same fresh engine seeds and pair them. The top-10 line is +2.66 over IB; the reference policies sit at +2.24 (Gaussian, plain tables), +3.18 (Gaussian, `qm`) and +3.67 (lattice) over IB if replica gaps carry. Seeds used here are replica seeds (10000..12047 holdout; 20000..20511, 30000..31999, 40000..40111, 50000..50083 for tuning and diagnostics). No engine seed was consumed.
3. **Arb or retail (Track B).** Worth 2.7. Tried, no gain: forbidding the quote zone where the two overlap (`DP_MASK`, costs 0.6 to 2.4 with perfect information and leaves the error at 13 to 15%), buying more pins with tighter quotes (kappa above 1e-5 costs more than it returns), a quote-aware fill likelihood. A table classifier on the filter's own features gets 18.8% against the lattice's 16.2%, so the error is near what those features allow. Not tried: choosing quotes against the whole lattice posterior instead of its mean and sd, per-run estimates of sigma and order rate inside the classifier, the router likelihood per price hypothesis.
4. **Finer lattice.** Offsets are on 5 bps with a parabola fit; a 2.5 bps solve is untested.

## Files

`dp.py` solver. `qmdp.py` uncertainty-aware tables from the solver's saved values. `replica2.py` the replica with a phase count, a size cap and fee accounting. `evalpol.py` perfect-information scoring. `track.py` one handicap at a time. `real.py` Gaussian filter. `latt.py` lattice filter. `run.py` blind runner for any policy and seed range. `pair.py` paired comparison. `example_policy.py` the policy interface. `ref/` per-seed reference results. `gates.py` per-seed check values. `stale.py`, `fillstat.py`, `clsdata.py`, `trace.py`, `fixedcheck2.py` diagnostics. Everything except `dp.py` and `qmdp.py` is plain `python3 -I` with no dependencies.
