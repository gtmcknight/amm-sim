# Prebuilt simulator for Paradigm's AMM fee challenge

Wheels of `amm_sim_rs`, the Rust engine in [benedictbrady/amm-challenge](https://github.com/benedictbrady/amm-challenge) at commit `6b6921f8d463314aa7c96234e1be25a25245f704` (equal to upstream `main` on 2026-11-07), built for Linux x86_64, any Python 3.10 to 3.13 (abi3, manylinux2014 / glibc 2.17).

A worker installs one wheel and runs. No Rust, no C compiler, no maturin. Setup took 7 to 8 seconds in bare `python:3.10-slim`, `3.12-slim` and `3.13-slim` containers, against 5 to 15 minutes before, and the old setup failed outright on machines without `/proc`, `cc` or `bzip2`.

| File | What it is | wheel sha256 | sha256 of amm_sim_rs/amm_sim_rs.abi3.so inside |
|---|---|---|---|
| `amm_sim_rs-0.1.0-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | the pinned commit, unchanged | `4ef4bd39fffb8bc3844b7d3df9024d647ac17f765165a71442ef80268f8c880c` | `414ea6d201d299b2967b2aee72c9704758fa69acf6df6cd295d83598118efd37` |
| `amm_sim_rs-0.1.0.post1-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | the pinned commit plus `instrumentation.patch`: per-callback EVM counters (`gas_stats()`, `gas_stats_reset()`: calls, ok, max_ok_gas, oog, revert, other_halt, tx_error, bad_return by role and callback). Gas limits and economics unchanged. | `aedb68280aca34c110968f00148387c95885207913fb2cf19a1ab4c5cfd6887a` | `ff88b6353c2aad7342f0a26194f7347e78b9c3b38d683a7449006d423978cd14` |
| `instrumentation.patch` | the counter patch, from IMD audit artifact `02c134d9ed51858f06d02b6dec25e6922016490f11e3a8174af512a6a77b6569` (goal 3a0e85d3, item e01-metering) | | |
| `harness.py` | paired runner from the same artifact: `python scratch/harness.py CAND.sol S0 S1 out.json --other V2.sol` | | |
| `setup-fast.sh` | the setup script for goal briefs (below); it checks the installed .so hash | | |

**Reproducible.** These wheels are the swarm's own build, byte for byte: IMD goal 268d9b25 had four Linux machines build with the recipe below and every one produced the same `amm_sim_rs.abi3.so` (A `414ea6d2…`, B `ff88b635…`). The wheels here were built the same way on Linux x86_64 and carry those exact binaries. Only maturin's SBOM and RECORD inside a wheel record the build path, so verify the `.so` hash, not the wheel's. A macOS cross-build with the same recipe gives a different `.so` (A `dee82210…`): build on Linux. Gate numbers the swarm and this build agree on: `CH` (ChengHua926 `d34a5199`, sha256 `6dd68f77…`) on seeds 0..999 scores `525.5258821780834` with either wheel; V2 through `harness.py` on seeds 10043..10044 shows afterSwap calls 21580, oog 3, max_ok_gas 243554, afterInitialize 236377.

## Setup block for a goal brief

Replace the old `set -eu;R=$PWD/scratch;...maturin develop...` block with this. From the checkout root: `sh scratch/setup.sh`, then prefix commands with `. scratch/env.sh &&`. The `scratch/env.sh` variables are the same as before, so existing harness scripts keep working. The instrumented wheel is the default; pass `AMM_WHEEL=https://github.com/gtmcknight/amm-sim/releases/download/sim-6b6921f8/amm_sim_rs-0.1.0-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` for the unpatched engine.

```sh
set -eu
R=$PWD/scratch; mkdir -p $R/tmp $R/bin $R/solcx
WHEEL=${AMM_WHEEL:-https://github.com/gtmcknight/amm-sim/releases/download/sim-6b6921f8/amm_sim_rs-0.1.0.post1-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl}
echo "export TMPDIR=$R/tmp XDG_CACHE_HOME=$R/xc UV_CACHE_DIR=$R/uvc UV_PYTHON_INSTALL_DIR=$R/uvpy SOLCX_BINARY_PATH=$R/solcx VIRTUAL_ENV=$PWD/.venv PATH=$PWD/.venv/bin:$R/bin:\$PATH" >$R/env.sh
. $R/env.sh
[ "$(uname -sm)" = "Linux x86_64" ] || { echo "BLOCKED platform $(uname -sm): the wheel is Linux x86_64"; exit 3; }
fetch() { if command -v curl >/dev/null 2>&1; then curl -LsSf "$1" -o "$2"; elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"; else python3 -c 'import sys,urllib.request;urllib.request.urlretrieve(sys.argv[1],sys.argv[2])' "$1" "$2"; fi; }
command -v uv >/dev/null 2>&1 || { fetch https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz $R/tmp/uv.tgz; tar --no-same-owner -xzf $R/tmp/uv.tgz -C $R/tmp; cp $R/tmp/uv-*/uv $R/bin/; }
uv venv -q --python 3.12 .venv
uv pip install -q "$WHEEL" "numpy>=1.24" "py-solc-x==2.1.0" "pyrevm==0.3.7"
uv pip install -q --no-deps -e .
python -c "import solcx; solcx.install_solc('0.8.24')" >/dev/null
amm-match validate contracts/src/StarterStrategy.sol
```

What still comes from the network: uv (10 MB, GitHub), a managed CPython 3.12 only if the machine has none (GitHub), numpy, pyrevm and py-solc-x wheels (PyPI), solc 0.8.24 (binaries.soliditylang.org), and the wheel itself. Nothing compiles.

## Rebuilding (Linux x86_64; rustc 1.99.1, maturin 1.16.0, ziglang 0.17.1, a C compiler for host build scripts)

```sh
git clone https://github.com/benedictbrady/amm-challenge && cd amm-challenge
git checkout 6b6921f8d463314aa7c96234e1be25a25245f704
cargo generate-lockfile --manifest-path amm_sim_rs/Cargo.toml
sha256sum amm_sim_rs/Cargo.lock   # b5efc7f1aaf2c92fafa2015404ff74f760b80135a9e16bacded7f4ba0c81690b
python3 -m venv venv && . venv/bin/activate && pip install maturin==1.16.0 ziglang==0.17.1
export RUSTUP_TOOLCHAIN=1.99.1 CARGO_INCREMENTAL=0 SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)   # 1770505944
export RUSTFLAGS="--remap-path-prefix=$PWD=/src --remap-path-prefix=${CARGO_HOME:-$HOME/.cargo}=/cargo --remap-path-prefix=${RUSTUP_HOME:-$HOME/.rustup}=/rustup"
maturin build --release --strip --locked --zig --target x86_64-unknown-linux-gnu --compatibility manylinux2014 --features pyo3/abi3-py310 --manifest-path amm_sim_rs/Cargo.toml --out dist
# wheel B: git apply instrumentation.patch; set version = "0.1.0.post1" in amm_sim_rs/pyproject.toml; build again
unzip -p dist/<wheel>.whl amm_sim_rs/amm_sim_rs.abi3.so | sha256sum   # A 414ea6d2…, B ff88b635…
```
