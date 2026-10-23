#!/usr/bin/env bash
# Run all tests. Usage: bash scripts/test.sh
set -e
cd "$(dirname "$0")/.."
echo "==> Python tests"
python -m pytest tests/ -q --tb=short
echo
echo "==> Frontend JS tests"
node --test "tests/js/test_tree.mjs" "tests/js/test_highlight.mjs"
echo
echo "==> All tests passed."