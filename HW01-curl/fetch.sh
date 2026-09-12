#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://jsonplaceholder.typicode.com"

usage() {
    cat <<EOF
Usage: $0 <resource> [id]

Examples:
  $0 posts
  $0 posts 1
  $0 users
  $0 comments 5
EOF
    exit 1
}

[[ $# -lt 1 ]] && usage

resource="$1"
id="${2:-}"

url="${BASE_URL}/${resource}"
if [[ -n "$id" ]]; then
    url="${url}/${id}"
fi

http_code=$(curl -s -o /tmp/fetch_response.$$ -w "%{http_code}" "$url")
body=$(cat /tmp/fetch_response.$$)
rm -f /tmp/fetch_response.$$

if [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]]; then
    echo "$body"
    exit 0
else
    echo "HTTP ${http_code}" >&2
    echo "$body" >&2
    exit 1
fi
