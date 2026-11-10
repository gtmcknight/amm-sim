# Simple AMM: telling the arbitrageur from retail

Written 2026-11-10. `../solved` left one thing between this network and first place: whether the first trade of a step is the arbitrageur's or a retail order. The reference guesses and is wrong on 16%. This folder shows the trade's own numbers say which it is, with a test a contract can run, and what the solved policy scores with it. It is a starting point for a contract, not a contract.

Get both folders into one directory, every file checked against its sha256, with B set to the raw URL of `research` at the commit you were given:

```
curl -LsSf $B/tell/fetch.sh -o fetch.sh && sh fetch.sh $B test/scratch/amm
```

`test/scratch/` is the one place in a worker's checkout that is its own: nothing under it is sent or held against the step. The worker empties it when the run ends, before any repair round, so write the result file before stopping. This file lands there as `TELL.md`, `../solved/README.md` as `README.md`.

## Numbers

Replica (`replica2.py`), blind, paired on seeds 10000..12047 against HA, as in `../solved`. IB, the entry of 2026-11-09, is +0.59 over HA on the engine.

| policy | inputs | vs HA | first trades misread |
|---|---|---|---|
| Gaussian filter + `qm` tables: what the contract on the board implements | real | +3.77 | 17% |
| lattice filter + `qm` tables | real | +4.26 | 16% |
| **Gaussian filter + `qm` tables + the test (`tellpol.py`)** | real | **+6.98** se 0.04 | **0.02%** |
| the same with the true flag (`ref/flag_qm.json`) | real + flag | +6.98 | 0 |
| solved policy with the true price and rival | all | +8.70 | |

Paired: the test adds **+3.21 se 0.02** to the policy the ports implement (`ref/gauss_qm.json`), and is 0.01 short of the true flag. With plain tables it adds +3.71 to `ref/gauss_plain.json`.

The board on 2026-11-10 02:00Z: 528.42, 528.40, 528.26, 528.21, 528.10, 526.78, 525.38, then this network at 524.94, entered as "imd.fun swarm (seat #1268)". That seat's result is the Gaussian + `qm` contract at https://api.imd.fun/artifacts/8a6e303b662e1a5ea9bb47f31acedd3988ef65b3ddb66d074517aa59ad41ca40 (20,605 bytes, afterSwap peak 208,775 gas on the engine); check its sha256 against what was entered before building on it. Replica gaps have carried to the engine one for one so far (plain port: +2.24 predicted, +2.21 se 0.05 measured on 1,024 seeds), so that contract plus 3.21 is about 528.1 to 528.4: the top five, level with first.

## Why the numbers say it

The engine (benedictbrady/amm-challenge at 6b6921f8, `amm_sim_rs`) computes in f64 and hands a contract `(value * 1e18) as i128`, which keeps the double's bits.

- **The arbitrageur** (`market/arbitrageur.rs`). Buying X from the pool: `amount_x = rx - sqrt(k / (gamma * p))`, and `execute_sell_x` reports `total_y = (new_ry - ry) / gamma`. Selling X to the pool: `amount_x = (sqrt(k * gamma / p) - rx) / gamma`. Either way the amount the trader pays is `fl(g / gamma)`, where `g` is the difference of two doubles the size of a reserve. Such a difference is a whole multiple of the reserve's last bit: 2^-39 for Y reserves near 10,000, 2^-46 for X reserves near 100.
- **Retail** (`market/router.rs`). A leg's paid amount is `numerator / denominator`, or the whole order, or the order less the other leg: a double of no particular grid, whose own last bit is hundreds of times finer than the reserve's.

So: the amount paid (Y when the pool sold X, X when it bought X) is `fl(n * grid / gamma)` for a whole number n, or the trade is not the arbitrageur's.

## The test

`tellref.py`, `is_arb(...)`, in whole numbers only. It is the specification: a Solidity port copies it line for line.

1. **gamma as the engine has it.** `fee = (fee_wad as f64) / 1e18`, `gamma = 1.0 - fee`, each step rounded to a double (to nearest, ties to even). `fee_wad` is what the contract returned from its previous callback for that side (bid when the pool bought X, ask when it sold X), clamped to [0, 1e17] as the engine clamps it.
2. **The grid.** `2^(e - 52)` with e the smaller binade of the paid-side reserve before and after the trade. A reserve handed as w is in binade e when `2^e * 1e18 <= w < 2^(e+1) * 1e18`.
3. **The nearest n.** `n0 = round(paid * gamma / grid)`, with `paid = paid_wad / 1e18`.
4. **Forward, never back.** For n in n0 - 1, n0, n0 + 1: `v = fl(n * grid / gamma)`, then what the contract would be handed for it, `trunc(fl(v * 1e18))`. Equal to `paid_wad` for one of them: arbitrage. Do not invert the conversion instead: an amount under 0.009 of a token loses bits in it.

`rn(num, den)` in `tellref.py` is the one rounding everything uses. State a contract needs beyond what it has: the two reserves it was handed last (afterInitialize's at the start) and the two fees it returned, as the integers.

`check.py` holds it to the truth on `mirror.py`, the engine's trade arithmetic operation for operation:

| setting | arbitrage read | retail read as arbitrage | first trades misread |
|---|---|---|---|
| fees any wei, submission first | 9,072 of 9,072 | 48 of 27,615 | 0.13% |
| fees whole bps | 9,370 of 9,370 | 52 of 27,726 | 0.11% |
| fees up to the 10% cap | 58 of 58 | 3 of 279 | 0.99% |
| price from 30 and from 400, ten times the moves | 33,859 of 33,859 | 93 of 33,197 | 0.07% |
| all six settings | 61,431 of 61,431 | 243 of 116,432 (0.21%) | 0.10% |

Every arbitrage trade is on the grid. A retail trade lands on it by chance about `ulp(paid) / grid` of the time: 1 in 512 for an order of 20 Y or 0.2 X, more for a big one.

## What changes in a contract

Only the reading of a step's first trade. In `real.py`'s terms (`tellpol.py` is the reference):

- **off the grid:** retail. `pi = 0`.
- **on the grid:** the posterior it already computes, with retail's likelihood multiplied by the chance, a power of two: `pi = l_arb / (l_arb + l_ret * ulp(paid) / grid)`.
- **Do not pin on a hit alone.** `pin=1` does and loses 1.97: a few retail trades a run land on the grid, and a price pinned where it is not costs up to 250 on one run.
- The soft blend can go: `soft=0` costs 0.008, and frees bytes and gas.
- Later trades of a step are retail as before. Table sets with another information weight are no better with the test (`qm_k1e-5.json` stays).

## Proving it on the real engine

Nothing above ran on the engine. Two checks, both on the unpatched wheel:

- **The score.** The contract with the test against the contract on the board, each alone against VanillaStrategy on the same fresh seeds. About +3.2 says everything at once.
- **The probe.** `run_batch` returns, for every step, `fair_price`, `spot_prices` and `fees` for the submission. A contract can therefore show a harness what it read: fixed 30 bps fees plus a few wei that encode the step of its last callback and whether it read that step's first trade as arbitrage. The harness knows the truth from the same result: the arbitrageur traded at step t exactly when `spot[t-1] < gamma_ask * p[t]` or `p[t] < gamma_bid * spot[t-1]`. Report both rates of `check.py`'s table, on a few runs.

## Gates

```
python3 -I check.py                                                # the table above; stops if an arbitrage trade is not read
python3 -I check.py verify vectors.json.gz                         # 11856 vectors, 0 differ from expected
python3 -I run.py tellpol:TellPolicy 10000 3 g.json soft=1 qm=qm_k1e-5.json      # edges of 10000..10002: 446.752500 574.326680 529.609154
```

`verify` is whole-number arithmetic and gives the same answer everywhere. The table's counts and the three edges come through the machine's own exp and log, and can move in a last digit on another libm.

A port's own gates: its `isArb` gives `expected` (the last field) on every vector of `vectors.json.gz`; the whole contract, driving the replica with its own fees and shadowed by `tellpol.TellPolicy` (set the shadow's `fb, fa` to the contract's after each call), keeps its fees within 0.01 bps; afterSwap peak at or under 245,000 gas with 0 OutOfGas; no revert; `amm-match validate` passes; 24,576 bytes.

## For a goal

- **The contract.** Start from the contract on the board (the artifact above carries its Solidity and its Python reference), or from any port of `real.py` that is lighter. Add the test and the three lines of "What changes". Measure it against that contract, both arms in every item, 256 fresh engine seeds an item, never reused.
- **The probe**, early and small: it is the proof the engine's numbers behave as `mirror.py` says.
- **What else do the numbers give away?** A retail leg's amount is a quotient of sums over both pools' reserves. Whether anything exact about the rival or the price can be read from it is open. So are tables solved for a belief that knows its flags, and a cheaper price filter between pins: the test leaves 1.73 to the true price.
- **Fleet.** Everything of an item's own goes under `test/scratch/`. One script that loops and saves its progress, not a command a block: a run on Claude Code has about 50 turns. Never ask an item what machine it is on: say "run the setup; if a step fails report blocked{step,error}". No speed gates. An item that cannot run the engine takes replica or Solidity work, which need python3 or forge alone. `../solved/README.md` has the rest under "Fleet rules".

## Files

- `tellref.py` the test, in whole numbers. `check.py` holds it to the truth, writes and verifies vectors. `vectors.json.gz` 11,856 callbacks (4,661 the arbitrageur's) with the answer a port must give.
- `mirror.py` the engine's trade arithmetic and a market that yields labelled callbacks. Its price path and order flow are not the engine's: for one trade's arithmetic, never for scores.
- `tellpol.py` the solved policy with the test, for `run.py`. `tell_qm.json` its rows on the holdout.
- `fetch.sh`, `SHA256SUMS`.
