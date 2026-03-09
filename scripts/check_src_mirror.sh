#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STRICT=0
if [[ "${1:-}" == "--strict" ]]; then
  STRICT=1
fi

LEFT="src"
RIGHT="typerelease-sync/src"

if [[ ! -d "$LEFT" ]]; then
  echo "missing directory: $LEFT" >&2
  exit 2
fi
if [[ ! -d "$RIGHT" ]]; then
  echo "missing directory: $RIGHT" >&2
  exit 2
fi

DIFF_OUTPUT="$(
  diff -rq \
    --exclude='.DS_Store' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "$LEFT" "$RIGHT" || true
)"

if [[ -z "$DIFF_OUTPUT" ]]; then
  echo "mirror check: src and typerelease-sync/src are in sync"
  exit 0
fi

echo "mirror check: drift detected between $LEFT and $RIGHT"
echo "$DIFF_OUTPUT"

if [[ $STRICT -eq 1 ]]; then
  exit 1
fi

echo "non-strict mode: reporting drift only (exit 0)"
