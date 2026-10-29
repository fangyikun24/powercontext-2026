#!/usr/bin/env bash
# End-to-end acceptance walkthrough for the SDD context module.
#
#   ./scripts/verify.sh              # offline checks (no model call)
#   ./scripts/verify.sh --with-model # also run the MiniMax plan/apply/verify cycle
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_MODEL=0
[ "${1:-}" = "--with-model" ] && WITH_MODEL=1

# shellcheck disable=SC1091
[ -d .venv ] && . .venv/bin/activate
PY="python"

hr() { printf '\n================ %s ================\n' "$1"; }

hr "0. clean state"
./scripts/reset.sh

hr "1. configuration"
$PY -m sdd_context doctor || true

hr "2. import specs, code and tests into the database"
$PY -m sdd_context --json ingest

hr "3. build the development context for the task"
$PY -m sdd_context context \
  --task "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders whose total is at least min_total are returned; negative min_total must be rejected" \
  --json > /tmp/sdd-context.json
$PY - <<'PY'
import json
d = json.load(open("/tmp/sdd-context.json"))
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

hr "done"
echo "artifacts: artifacts/logs, artifacts/diffs, artifacts/records"
