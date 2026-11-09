#!/bin/sh
# Setup block of IMD goals 282fbc03 and amm-filter-1: run once from the amm-challenge checkout root; then `. scratch/env.sh`.
set -eu;R=$PWD/scratch;mkdir -p $R/tmp $R/bin $R/solcx
echo "export TMPDIR=$R/tmp XDG_CACHE_HOME=$R/xc UV_CACHE_DIR=$R/uvc UV_PYTHON_INSTALL_DIR=$R/uvpy SOLCX_BINARY_PATH=$R/solcx VIRTUAL_ENV=$PWD/.venv PATH=$PWD/.venv/bin:$R/bin:\$PATH" >$R/env.sh;. $R/env.sh
command -v uv >/dev/null||{ curl -LsSf https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz|tar --no-same-owner -xz -C $R/tmp;cp $R/tmp/uv-*/uv $R/bin/;}
W=amm_sim_rs-0.1.0.post1-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl;curl -LsSf https://github.com/gtmcknight/amm-sim/releases/download/sim-6b6921f8/$W -o $R/$W
echo "aedb68280aca34c110968f00148387c95885207913fb2cf19a1ab4c5cfd6887a  $R/$W"|sha256sum -c -
uv venv --python 3.12 .venv;uv pip install $R/$W numpy numba cma py-solc-x==2.1.0 pyrevm==0.3.7;uv pip install --no-deps -e .
python -c "import solcx;solcx.install_solc('0.8.24')"
amm-match validate contracts/src/StarterStrategy.sol
