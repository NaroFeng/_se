#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from http_client import HttpClient

BASE_URL = "https://jsonplaceholder.typicode.com"


def usage():
    print("Usage: fetch_raw.py <resource> [id]", file=sys.stderr)
    print("Examples:", file=sys.stderr)
    print("  fetch_raw.py posts", file=sys.stderr)
    print("  fetch_raw.py posts 1", file=sys.stderr)
    print("  fetch_raw.py users", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage()

    resource = sys.argv[1]
    id_ = sys.argv[2] if len(sys.argv) > 2 else ""

    path = f"/{resource}"
    if id_:
        path = f"{path}/{id_}"

    client = HttpClient(BASE_URL)
    try:
        resp = client.get(path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    body_bytes = resp["body"]
    if 200 <= resp["status"] < 300:
        sys.stdout.buffer.write(body_bytes)
        if not body_bytes.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
        sys.exit(0)
    else:
        print(f"HTTP {resp['status']} {resp['reason']}", file=sys.stderr)
        try:
            sys.stdout.buffer.write(body_bytes)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
