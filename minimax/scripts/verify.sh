#!/usr/bin/env bash
# End-to-end acceptance walkthrough for the SDD context module.
#
#   bash scripts/verify.sh              # offline checks (no model call)
#   bash scripts/verify.sh --with-model # also run the MiniMax plan/apply/verify cycle
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_MODEL=0
[ "${1:-}" = "--with-model" ] && WITH_MODEL=1

# shellcheck disable=SC1091
[ -d .venv ] && . .venv/bin/activate
PY="python"
# Put the module root on the path: running ``python scripts/foo.py`` only adds
# ``scripts/`` to sys.path, so ``import sdd_context`` would otherwise fail.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

hr() { printf '\n================ %s ================\n' "$1"; }

hr "0. clean state"
bash scripts/reset.sh

hr "1. configuration"
$PY -m sdd_context doctor || true

hr "2. import specs, code and tests into the database"
$PY -m sdd_context --json ingest

hr "3. build the development context for the task"
# Write the JSON next to the module instead of /tmp: on Windows Git Bash and the
# native Python interpreter resolve /tmp differently, and the default encoding is
# not UTF-8. A relative path with an explicit encoding works everywhere.
SDDCTX_CTX_JSON=".sdd-context.json"
$PY -m sdd_context context \
  --task "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders whose total is at least min_total are returned; negative min_total must be rejected" \
  --json > "$SDDCTX_CTX_JSON"
$PY - "$SDDCTX_CTX_JSON" <<'PY'
import json
import sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("database:", d["database"])
for key in ("specs", "code_targets", "functional_tests", "regression_tests"):
    print(f"\n{key}:")
    for item in d[key]:
        print(f"  {item['locator']}  [{item['reason']}]")
PY

hr "4. context follows an edited specification"
$PY scripts/verify_spec_update.py sample-project

hr "5. pre-change state: target tests must fail, regressions must pass"
cp -R sample-project/snapshots/before/src/orderflow/. sample-project/src/orderflow/
( cd sample-project && $PY -m pytest -q ) || echo "exit code above is EXPECTED (target behaviour missing)"
cp -R sample-project/snapshots/after/src/orderflow/. sample-project/src/orderflow/

hr "6. post-change state: everything must pass"
( cd sample-project && $PY -m pytest -q )

hr "7. task state survives a restart of the module"
$PY scripts/state_roundtrip.py save sample-project
$PY scripts/state_roundtrip.py load sample-project

if [ "$WITH_MODEL" = "1" ]; then
  hr "8. MiniMax performs the change (plan -> apply -> verify)"
  $PY -m sdd_context task plan --task-id SDD-ORD-004 \
    --task "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders whose total is at least min_total are returned; negative min_total must be rejected"
  $PY -m sdd_context task apply --task-id SDD-ORD-004
  $PY -m sdd_context task verify --task-id SDD-ORD-004
  $PY -m sdd_context task status --task-id SDD-ORD-004
fi

rm -f "$SDDCTX_CTX_JSON"

hr "done"
echo "artifacts: artifacts/logs, artifacts/diffs, artifacts/records"