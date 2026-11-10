"""The solved policy with the arbitrage test in place of its guess, on the replica, blind.

  python3 -I run.py tellpol:TellPolicy 10000 2048 out.json soft=1 qm=qm_k1e-5.json
  python3 -I pair.py out.json ref/gauss_qm.json        # +3.21: what the test adds to the policy the ports implement
  python3 -I pair.py out.json ref/flag_qm.json         # -0.01: what is left to the true flag
  python3 -I pair.py out.json tell_qm.json             # 0: these rows, as published

`real.RealPolicy` reads a step's first trade as the arbitrageur's or as retail by a likelihood ratio, and
is wrong on 16% of them.  This asks the trade's own numbers first (README): the amount the trader paid
is on the arbitrageur's grid, or it is not.

  off the grid   retail, for certain: every arbitrage trade is on it
  on the grid    the likelihood ratio it already had, with retail's side multiplied by the chance a
                 retail amount lands on the grid, ulp(paid) / grid (1 in 512 for a typical small order)
  pin=1          on the grid => arbitrage outright.  What not to port: -1.97 against this, from the
                 handful of retail trades a run that land on the grid and pin the price where it is not.

The replica computes a trade's amounts with the engine's expressions, so the test is the same one
here, on the floats themselves.  Blind: it takes exactly what afterSwap gets, and keeps the reserves it
was handed last and the fees it returned (`fb`, `fa`: the fees in force).  A harness that drives the
replica with a contract's fees and shadows it with this sets `fb, fa` to the contract's after each call.
"""
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import real


class TellPolicy(real.RealPolicy):
    def __init__(self, T, opt=None):
        opt = dict(opt or {})
        self.pin = bool(opt.pop('pin', 0))
        real.RealPolicy.__init__(self, T, opt)
        self.needs_flag = False                     # the harness tells it nothing
        self.px, self.py = 100.0, 10000.0           # the reserves afterInitialize is handed

    def on_grid(self, is_buy, ax, ay, x, y):
        """(whether the amount paid is fl(n * grid / gamma) for a whole n, the chance a retail amount is)"""
        if is_buy: paid, gamma, grid = ax, 1.0 - self.fb, min(math.ulp(self.px), math.ulp(x))   # the pool bought X: X was paid
        else:      paid, gamma, grid = ay, 1.0 - self.fa, min(math.ulp(self.py), math.ulp(y))   # the pool sold X: Y was paid
        n0 = round(paid * gamma / grid)
        hit = any(n > 0 and (n * grid) / gamma == paid for n in (n0 - 1, n0, n0 + 1))
        return hit, min(1.0, math.ulp(paid) / grid)

    def on_trade(self, is_buy, ax, ay, t, x, y, flag=None):
        hit, chance = self.on_grid(is_buy, ax, ay, x, y)
        self.px, self.py = x, y
        if self.pin or not hit:
            self.o['oraclearb'] = 1                  # RealPolicy takes the flag it is handed: the test's answer
            return real.RealPolicy.on_trade(self, is_buy, ax, ay, t, x, y, hit)
        # On the grid: RealPolicy's own posterior, pi = l_arb / (l_arb + l_ret), with l_ret cut by the chance.
        # l_ret is RHO times the fit, so cutting RHO for this one call is that and nothing else.
        self.o['oraclearb'] = 0
        rho = real.RHO
        real.RHO = rho * chance
        try:
            return real.RealPolicy.on_trade(self, is_buy, ax, ay, t, x, y)
        finally:
            real.RHO = rho
