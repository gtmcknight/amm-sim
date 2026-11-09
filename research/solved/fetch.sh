#!/bin/sh
# Fetch this whole folder and check every file's sha256.
# usage: sh fetch.sh <base-url-of-this-folder> [dir]        default dir: scratch/solved
set -eu
B=$1; D=${2:-scratch/solved}
mkdir -p "$D/ref"
get() {
  if command -v curl >/dev/null 2>&1; then curl -LsSf "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"
  else python3 -c 'import sys,urllib.request;urllib.request.urlretrieve(sys.argv[1],sys.argv[2])' "$1" "$2"; fi
}
get "$B/SHA256SUMS" "$D/SHA256SUMS"
while read -r sum name; do
  get "$B/$name" "$D/$name"
done < "$D/SHA256SUMS"
cd "$D"
python3 - <<'PY'
import hashlib, sys
bad = n = 0
for line in open('SHA256SUMS'):
    s, name = line.split(); n += 1
    if hashlib.sha256(open(name, 'rb').read()).hexdigest() != s:
        print('MISMATCH', name); bad += 1
print('fetched', n, 'files,', bad, 'mismatched')
sys.exit(1 if bad else 0)
PY
