#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ -z "${SNAPSHOT_API_BASE_URL:-}" || -z "${SNAPSHOT_API_TOKEN:-}" ]]; then
  echo "SNAPSHOT_API_BASE_URL and SNAPSHOT_API_TOKEN must be set"
  exit 1
fi

"$PYTHON_BIN" -m src.crawlers.snapshot_sync \
  --output-dir "$ROOT_DIR/data/catalog_snapshot" \
  --state-dir "$ROOT_DIR/state/catalog_snapshot" \
  --api-base-url "$SNAPSHOT_API_BASE_URL" \
  --api-token "$SNAPSHOT_API_TOKEN" \
  --page-size "${SNAPSHOT_PAGE_SIZE:-1000}" \
  --max-retries "${SNAPSHOT_MAX_RETRIES:-5}" \
  --timeout "${SNAPSHOT_TIMEOUT:-45}" \
  "$@"
