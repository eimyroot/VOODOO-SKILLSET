#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def fetch(url: str):
    req = Request(url, headers={"Accept": "application/json,text/html", "User-Agent": "VOODOO-R4-production-verifier/1"})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, dict(response.headers.items()), response.read(2_097_153)
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read(2_097_153)
    except URLError as exc:
        raise RuntimeError(f"production endpoint unavailable: {exc.reason}") from exc


def json_get(base: str, path: str):
    status, headers, raw = fetch(base.rstrip("/") + path)
    if status != 200:
        raise RuntimeError(f"{path} returned HTTP {status}: {raw[:1000]!r}")
    if len(raw) > 2_097_152:
        raise RuntimeError(f"{path} response too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} did not return JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} JSON must be an object")
    return value, headers


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)

    if not SHA_RE.fullmatch(args.expected_sha):
        parser.error("--expected-sha must be 40 lowercase hexadecimal characters")

    health, headers = json_get(args.base_url, "/api/health")
    assert health.get("status") == "ok", health
    assert health.get("version") == args.expected_version, health
    assert health.get("canonical_sha") == args.expected_sha, health
    assert headers.get("X-Canonical-SHA") == args.expected_sha, headers
    assert health.get("fleet") == "CONFIGURED", health
    assert health.get("fleet_backend") == "supabase-postgres", health
    assert health.get("fleet_execution") == "AVAILABLE", health

    fleet, _ = json_get(args.base_url, "/api/fleet")
    assert fleet.get("status") == "AVAILABLE", fleet
    assert fleet.get("execution") == "AVAILABLE", fleet
    assert fleet.get("backend") == "supabase-postgres", fleet
    assert fleet.get("durable") is True, fleet
    assert fleet.get("database_secret_exposed_to_workers") is False, fleet
    assert fleet.get("event_chain") == "VERIFIED", fleet

    status, _, root = fetch(args.base_url.rstrip("/") + "/")
    assert status == 200, status
    text = root.decode("utf-8", errors="replace")
    assert "VOODOO" in text and "SKILLSET" in text, text[:500]

    print(json.dumps({
        "verdict": "PASS",
        "base_url": args.base_url,
        "canonical_sha": args.expected_sha,
        "version": args.expected_version,
        "fleet_backend": fleet.get("backend"),
        "fleet_event_chain": fleet.get("event_chain"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"PRODUCTION_VERIFY=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"PRODUCTION_VERIFY=BLOCKED {exc}", file=sys.stderr)
        raise SystemExit(2)
