#!/bin/sh
# Fetch ../solved and this folder into ONE directory and check every file's sha256.
# usage: sh fetch.sh <raw URL of research/ at a commit> [dir]        default dir: test/scratch/amm
# This folder's README.md lands as TELL.md and its fetch.sh as fetch-tell.sh; ../solved keeps its names.
set -eu
B=$1; D=${2:-test/scratch/amm}
mkdir -p "$D/ref"
get() {
  if command -v curl >/dev/null 2>&1; then curl -LsSf "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"
  else python3 -c 'import sys,urllib.request;urllib.request.urlretrieve(sys.argv[1],sys.argv[2])' "$1" "$2"; fi
}
get "$B/solved/SHA256SUMS" "$D/SHA256SUMS.solved"
while read -r sum name; do
  get "$B/solved/$name" "$D/$name"
done < "$D/SHA256SUMS.solved"
get "$B/tell/SHA256SUMS" "$D/SHA256SUMS.tell"
while read -r sum name; do
  case "$name" in README.md) out=TELL.md ;; fetch.sh) out=fetch-tell.sh ;; *) out=$name ;; esac
  get "$B/tell/$name" "$D/$out"
done < "$D/SHA256SUMS.tell"
cd "$D"
python3 - <<'PY'
import hashlib, sys
bad = n = 0
renamed = {'README.md': 'TELL.md', 'fetch.sh': 'fetch-tell.sh'}
for manifest, names in (('SHA256SUMS.solved', {}), ('SHA256SUMS.tell', renamed)):
    for line in open(manifest):
        s, name = line.split(); n += 1
        if hashlib.sha256(open(names.get(name, name), 'rb').read()).hexdigest() != s:
            print('MISMATCH', name); bad += 1
print('fetched', n, 'files,', bad, 'mismatched')
sys.exit(1 if bad else 0)
PY
