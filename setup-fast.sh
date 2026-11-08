# amm-challenge @ 6b6921f8 fast setup: prebuilt amm_sim_rs wheel, no Rust, no C compiler, no maturin.
# From the checkout root:  sh scratch/setup.sh   then prefix commands with   . scratch/env.sh &&
# Override the wheel with AMM_WHEEL=<url or path>.
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
