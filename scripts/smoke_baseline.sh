#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "[1/4] Python compile check"
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import ast

for path in sorted(Path("src").rglob("*.py")):
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))

print("ok: parsed all src/*.py")
PY

echo "[2/4] CLI availability check"
"$PYTHON_BIN" -m src.main --help >/dev/null
echo "ok: $PYTHON_BIN -m src.main --help"

echo "[3/4] sources config sanity check"
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

path = Path("config/sources.json")
payload = json.loads(path.read_text(encoding="utf-8"))
sources = payload.get("sources", [])
if not isinstance(sources, list):
    raise SystemExit("config/sources.json: 'sources' must be a list")

ids = []
for src in sources:
    if not isinstance(src, dict):
        raise SystemExit("config/sources.json: source item must be an object")
    sid = src.get("id")
    mode = (src.get("crawl") or {}).get("mode")
    if not sid:
        raise SystemExit("config/sources.json: source without id")
    if not mode:
        raise SystemExit(f"config/sources.json: source '{sid}' has no crawl.mode")
    ids.append(sid)

dups = sorted({sid for sid in ids if ids.count(sid) > 1})
if dups:
    raise SystemExit(f"config/sources.json: duplicate source ids: {dups}")

print(f"ok: {len(sources)} sources, ids unique, crawl.mode present")
PY

echo "[4/4] JSON integrity check (config/state/data)"
"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

roots = [Path("config"), Path("state"), Path("data")]
checked = 0
for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
        checked += 1

print(f"ok: validated {checked} json files")
PY

echo "baseline smoke passed"
