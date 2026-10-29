#!/usr/bin/env pwsh
# PowerShell entry point for the same flow as scripts/verify.sh (used on Windows).
param([switch]$WithModel)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

function Section($name) { Write-Host "`n================ $name ================`n" -ForegroundColor Cyan }

Section "0. clean state"
& "$PSScriptRoot\reset.ps1"

Section "1. configuration"
& $py -m sdd_context doctor

Section "2. import specs, code and tests into the database"
& $py -m sdd_context --json ingest

Section "3. build the development context"
$task = "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders whose total is at least min_total are returned; negative min_total must be rejected"
& $py -m sdd_context context --task $task --json | Out-File -Encoding utf8 ".tmp-context.json"
& $py -c @"
import json
d = json.load(open('.tmp-context.json', encoding='utf-8-sig'))
print('database:', d['database'])
for key in ('specs','code_targets','functional_tests','regression_tests'):
    print('\n' + key + ':')
    for item in d[key]:
        print('  ' + item['locator'] + '  [' + item['reason'] + ']')
"@

Section "4. context follows an edited specification"
& $py scripts\verify_spec_update.py sample-project

Section "5. pre-change state (target tests fail)"
Copy-Item "sample-project\snapshots\before\src\orderflow\*.py" "sample-project\src\orderflow\" -Force
Push-Location sample-project; & $py -m pytest -q; $before = $LASTEXITCODE; Pop-Location
Write-Host "exit code: $before (expected non-zero)"

Section "6. post-change state (everything passes)"
Copy-Item "sample-project\snapshots\after\src\orderflow\*.py" "sample-project\src\orderflow\" -Force
Push-Location sample-project; & $py -m pytest -q; $after = $LASTEXITCODE; Pop-Location
Write-Host "exit code: $after (expected 0)"

Section "7. task state survives a restart"
& $py scripts\state_roundtrip.py save sample-project
& $py scripts\state_roundtrip.py load sample-project

if ($WithModel) {
  Section "8. MiniMax performs the change"
  & $py -m sdd_context task plan --task-id SDD-ORD-004 --task $task
  & $py -m sdd_context task apply --task-id SDD-ORD-004
  & $py -m sdd_context task verify --task-id SDD-ORD-004
  & $py -m sdd_context task status --task-id SDD-ORD-004
}

Remove-Item ".tmp-context.json" -ErrorAction SilentlyContinue
Section "done"
