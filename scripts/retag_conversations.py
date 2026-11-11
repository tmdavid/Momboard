#!/usr/bin/env python3
"""Re-tag (reprocess) every conversation in a date range, through the MomBoard API.

For each conversation it calls  POST /api/conversations/{id}/reprocess , which
  - deletes that call's AI-SUGGESTED highlights (anything you accepted or rejected is kept),
  - queues a new tag job (which chains into analysis and hypothesis linking).
Each call therefore costs LLM usage, and the worker processes them at its own pace.

Safe by default:
  * It is a DRY RUN unless you pass --yes (lists what it would do; changes nothing).
  * It asks for your password itself (hidden prompt). The password is never taken from the
    command line or printed, and is only sent to --base.
  * Plain http is only allowed to localhost (your SSH tunnel). Anything else must be https.
  * Calls that are already processing/queued are skipped (no double-queueing).
  * Requests are paced (--pace seconds apart) and it stops after 3 failures in a row.

Usage (with your SSH tunnel to the server open on local port 8080):

    python scripts/retag_conversations.py --email you@example.com \
        --from 2026-11-01 --to 2026-11-30                 # dry run
    python scripts/retag_conversations.py --email you@example.com \
        --from 2026-11-01 --to 2026-11-30 --yes           # do it

Dates filter on the conversation's "happened at" date (what Library shows), inclusive.
Conversations with no date are not included. Stdlib only.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any

SKIP_STATUSES = {"processing", "queued", "pending"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class ApiClient:
    """Tiny cookie-session JSON client."""

    def __init__(self, base: str, timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode() or "null"
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as err:
            raw = err.read().decode(errors="replace")
            try:
                return err.code, json.loads(raw)
            except ValueError:
                return err.code, raw
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return 0, str(err)


def check_base_is_safe(base: str) -> None:
    """Never send a password over plain http to anything but localhost."""
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SystemExit(f"--base must be an http(s) URL, got: {base!r}")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        raise SystemExit(
            "Refusing to send a password over plain http to a non-local host. "
            "Use your SSH tunnel (http://127.0.0.1:8080) or an https:// URL."
        )


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from err


def fetch_conversations(client: ApiClient, start: date, end: date) -> list[dict[str, Any]]:
    """All conversations whose happened_at falls in [start, end], inclusive, paged."""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({
            "date_from": f"{start.isoformat()}T00:00:00",
            "date_to": f"{end.isoformat()}T23:59:59",
            "limit": 200,
            "offset": offset,
            "sort": "date_asc",
        })
        status, body = client.request("GET", f"/api/conversations?{query}")
        if status != 200 or not isinstance(body, dict):
            raise SystemExit(f"Could not list conversations (HTTP {status}): {str(body)[:200]}")
        page = body.get("items", [])
        items.extend(page)
        offset += len(page)
        if not page or offset >= body.get("total", 0):
            return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8080", help="MomBoard URL (default: your tunnel)")
    parser.add_argument("--email", help="Login email (prompted if omitted)")
    parser.add_argument("--from", dest="start", type=parse_day, required=True, help="First day, YYYY-MM-DD")
    parser.add_argument("--to", dest="end", type=parse_day, required=True, help="Last day, YYYY-MM-DD (inclusive)")
    parser.add_argument("--yes", action="store_true", help="Actually queue the re-tagging (default: dry run)")
    parser.add_argument("--pace", type=float, default=3.0, help="Seconds between requests (default 3)")
    parser.add_argument("--max", type=int, default=0, help="Stop after this many (0 = no limit)")
    args = parser.parse_args(argv)

    if args.end < args.start:
        raise SystemExit("--to must not be before --from")
    check_base_is_safe(args.base)

    email = args.email or input("Email: ").strip()
    password = getpass.getpass(f"Password for {email} (hidden): ")
    client = ApiClient(args.base)

    status, body = client.request("POST", "/auth/login", {"email": email, "password": password})
    del password  # not needed again
    if status != 200:
        print(f"Login failed (HTTP {status}). Nothing was changed.")
        return 1
    print(f"Logged in as {body.get('email', email)}.")

    conversations = fetch_conversations(client, args.start, args.end)
    todo = [c for c in conversations if c.get("status") not in SKIP_STATUSES]
    skipped = [c for c in conversations if c.get("status") in SKIP_STATUSES]
    if args.max:
        todo = todo[: args.max]

    print(f"\nConversations {args.start} to {args.end}: {len(conversations)} found, "
          f"{len(todo)} to re-tag, {len(skipped)} skipped (already processing).")
    if todo:
        first, last = todo[0], todo[-1]
        print(f"  first: #{first['id']} {str(first.get('happened_at'))[:10]}  {first.get('title', '')[:50]}")
        print(f"  last:  #{last['id']} {str(last.get('happened_at'))[:10]}  {last.get('title', '')[:50]}")
        print(f"  each one deletes that call's AI-suggested highlights and queues a new LLM tagging run "
              f"(accepted/rejected highlights are kept).")

    if not todo:
        print("Nothing to do.")
        return 0
    if not args.yes:
        print("\nDRY RUN: nothing was changed. Re-run with --yes to queue these.")
        return 0

    print(f"\nQueueing {len(todo)} re-tag jobs, {args.pace:g}s apart (Ctrl-C to stop; already queued ones continue)...")
    done = failed = consecutive = 0
    failures: list[tuple[int, int, str]] = []
    try:
        for index, convo in enumerate(todo, start=1):
            status, body = client.request("POST", f"/api/conversations/{convo['id']}/reprocess")
            if status == 200:
                done += 1
                consecutive = 0
            else:
                failed += 1
                consecutive += 1
                failures.append((convo["id"], status, str(body)[:120]))
                print(f"  ! #{convo['id']} failed (HTTP {status}): {str(body)[:120]}")
                if consecutive >= 3:
                    print("Stopping: 3 failures in a row. Check the server, then re-run (it is safe to re-run; "
                          "calls already processing are skipped).")
                    break
            if index % 10 == 0 or index == len(todo):
                print(f"  {index}/{len(todo)} queued ({failed} failed)")
            if index < len(todo):
                time.sleep(args.pace)
    except KeyboardInterrupt:
        print("\nInterrupted. Jobs already queued will still run.")

    print(f"\nDone: {done} queued, {failed} failed, {len(skipped)} skipped.")
    if failures:
        print("Failed ids: " + ", ".join(f"#{i} (HTTP {s})" for i, s, _ in failures))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
