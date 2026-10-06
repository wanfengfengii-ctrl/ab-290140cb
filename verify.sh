#!/bin/sh
# One-shot verification: unit tests, build (byte-compile), API smoke.
# Exits non-zero on the first failing step so the container exit code
# reports the result.
set -eu
cd "$(dirname "$0")"

PY=$(command -v python || command -v python3)

echo "[verify] 1/3 code tests"
"$PY" -m unittest discover -s tests -v

echo "[verify] 2/3 build (byte-compile all sources)"
"$PY" -m compileall -q app tests smoke.py

echo "[verify] 3/3 API smoke (hold + ramp segments)"
"$PY" smoke.py

echo "[verify] OK"
