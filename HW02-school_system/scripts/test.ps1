# Run all tests. Usage: .\scripts\test.ps1
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
Write-Host "==> Python tests"
python -m pytest tests/ -q --tb=short
Write-Host ""
Write-Host "==> Frontend JS tests"
node --test "tests/js/test_tree.mjs" "tests/js/test_highlight.mjs"
Write-Host ""
Write-Host "==> All tests passed."