#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${ROOT_DIR}/lib/api.sh"

PASS=0
FAIL=0
FAILED_TESTS=()

assert() {
    local name="$1"
    local actual="$2"
    local expected="$3"
    if [[ "$actual" == "$expected" ]]; then
        echo "  PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (expected: '$expected', got: '$actual')"
        FAIL=$((FAIL + 1))
        FAILED_TESTS+=("$name")
    fi
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

echo "==> Test: GET /posts returns 200 and an array"
api_get "/posts"
require_status 200
assert_contains "body starts with [" "${HTTP_BODY:0:1}" "["
assert_contains "body contains userId" "$HTTP_BODY" "userId"
assert_contains "body contains title" "$HTTP_BODY" "title"

echo "==> Test: GET /posts/1 returns single post"
api_get "/posts/1"
require_status 200
assert_contains "body contains userId" "$HTTP_BODY" "\"userId\""
assert_contains "body contains id:1" "$HTTP_BODY" "\"id\": 1"

echo "==> Test: GET /users returns array with email field"
api_get "/users"
require_status 200
assert_contains "body contains email field" "$HTTP_BODY" "\"email\""
assert_contains "body contains @ symbol" "$HTTP_BODY" "@"

echo "==> Test: GET /posts/9999 returns 404 (resource not found)"
api_get "/posts/9999"
require_status 404

echo "==> Test: fetch.sh CLI end-to-end (posts)"
output=$("${ROOT_DIR}/fetch.sh" posts)
assert_contains "CLI output is array" "${output:0:1}" "["
assert_contains "CLI output contains userId" "$output" "userId"

echo "==> Test: fetch.sh CLI end-to-end (posts 1)"
output=$("${ROOT_DIR}/fetch.sh" posts 1)
assert_contains "CLI output contains id 1" "$output" "\"id\": 1"

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
echo "All tests passed."
exit 0
