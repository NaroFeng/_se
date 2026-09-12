#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR_WIN='C:\Users\zz072\Desktop\學期成績\大二上學期\現代軟體工程\hw1-curl'

PS1_FILE="${ROOT_DIR_WIN}\fetch_raw.ps1"
PS1_FILE_UNIX="/c/Users/zz072/Desktop/學期成績/大二上學期/現代軟體工程/hw1-curl/fetch_raw.ps1"

if [[ ! -f "$PS1_FILE_UNIX" ]]; then
    echo "SKIP: PowerShell test skipped (fetch_raw.ps1 not found)"
    exit 0
fi

if ! command -v powershell.exe >/dev/null 2>&1; then
    echo "SKIP: powershell.exe not available"
    exit 0
fi

PASS=0
FAIL=0
FAILED_TESTS=()

run_ps() {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_FILE" "$@" 2>&1
}

assert_contains() {
    local name="$1"
    local haystack="$2"
    local needle="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        echo "  PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (expected to contain: '$needle')"
        FAIL=$((FAIL + 1))
        FAILED_TESTS+=("$name")
    fi
}

assert_eq_int() {
    local name="$1"
    local actual="$2"
    local expected="$3"
    if [[ "$actual" == "$expected" ]]; then
        echo "  PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (expected: $expected, got: $actual)"
        FAIL=$((FAIL + 1))
        FAILED_TESTS+=("$name")
    fi
}

echo "==> Test: PowerShell GET /posts returns 200 and array"
output=$(run_ps posts)
rc=$?
assert_eq_int "exit code is 0" "$rc" "0"
assert_contains "body starts with [" "${output:0:1}" "["
assert_contains "body contains userId" "$output" "userId"
assert_contains "body contains title" "$output" "title"

echo "==> Test: PowerShell GET /posts/1 returns single post"
output=$(run_ps posts 1)
rc=$?
assert_eq_int "exit code is 0" "$rc" "0"
assert_contains "body contains id 1" "$output" '"id": 1'
assert_contains "body contains userId" "$output" '"userId"'

echo "==> Test: PowerShell GET /users has email field"
output=$(run_ps users)
rc=$?
assert_eq_int "exit code is 0" "$rc" "0"
assert_contains "body contains email" "$output" '"email"'
assert_contains "body contains @" "$output" "@"

echo "==> Test: PowerShell GET /posts/9999 returns non-zero exit"
output=$(run_ps posts 9999)
rc=$?
if [[ "$rc" -ne 0 ]]; then
    echo "  PASS  exit code is non-zero ($rc)"
    PASS=$((PASS + 1))
    assert_contains "error mentions 404" "$output" "404"
else
    echo "  FAIL  expected non-zero exit, got $rc"
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("404 non-zero exit")
fi

echo "==> Test: PowerShell no args shows usage"
output=$(run_ps)
rc=$?
if [[ "$rc" -ne 0 ]]; then
    echo "  PASS  no-args exit non-zero"
    PASS=$((PASS + 1))
    assert_contains "stderr contains Usage" "$output" "Usage"
else
    echo "  FAIL  expected non-zero exit on no args, got $rc"
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("no args non-zero")
fi

echo ""
echo "=========================="
echo "Passed: $PASS"
echo "Failed: $FAIL"
if [[ $FAIL -gt 0 ]]; then
    echo "Failed tests:"
    for t in "${FAILED_TESTS[@]}"; do
        echo "  - $t"
    done
    exit 1
fi
echo "All PowerShell tests passed."
exit 0
