#!/usr/bin/env python3
"""Drive the staged retag rollout through the MomBoard API (v0.5 R1).

    python scripts/retag_rollout.py status
    python scripts/retag_rollout.py snapshot --label "before pilot"
    python scripts/retag_rollout.py batch --limit 100            # dry run: what would be queued
    python scripts/retag_rollout.py batch --limit 100 --yes      # queue the 100 newest
    python scripts/retag_rollout.py compare                      # tag counts now vs the snapshot
    python scripts/retag_rollout.py run --batch-size 100 --yes   # all the rest, batch by batch

Needs your SSH tunnel (or an https URL) and an ADMIN login: it prompts for your password (hidden)
and never takes it from the command line. Every command except `batch --yes` and `run --yes`
changes nothing. See documentation/guides/retag-rollout.md for the gates between the steps.

Resumable by design: only calls not yet on the current taxonomy are picked up, newest first, so
after a failure just run it again. Each call spends LLM tokens: run the pilot first and read the
time estimate from `status` before starting the full run.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retag_conversations import ApiClient, check_base_is_safe  # noqa: E402

POLL_SECONDS = 15.0


def fmt_status(s: dict[str, Any]) -> str:
    lines = [
        f"Taxonomy version {s['version']}: {s['calls_on_current']:,} of {s['total_calls']:,} calls are on the current taxonomy.",
        f"  waiting to be retagged: {s['eligible']:,}     being processed now: {s['in_progress']:,}",
    ]
    if s.get("seconds_per_call"):
        est = f"~{s['estimated_minutes']:,} min" if s.get("estimated_minutes") else "n/a"
        lines.append(f"  measured {s['seconds_per_call']:.0f}s per call (tag + analyze); estimate for the rest: {est}")
    else:
        lines.append("  no timing yet (it appears after a few calls finish) - run the pilot first")
    for t in s.get("tags", []):
        lines.append(f"  missing '{t['name']}': {t['stale_calls']:,} of {t['total_calls']:,} calls")
    return "\n".join(lines)


def fmt_compare(c: dict[str, Any]) -> str:
    if not c.get("snapshot"):
        return "No snapshot yet. Run `snapshot` before the pilot."
    lines = [f"Tag counts vs snapshot '{c['snapshot']['label']}' ({c['snapshot']['taken_at']}):", ""]
    lines.append(f"{'tag':<24}{'before':>8}{'after':>8}{'change':>9}   flag")
    for r in c["rows"]:
        pct = "" if r["pct"] is None else f"{r['pct']:+d}%"
        lines.append(f"{r['name'][:23]:<24}{r['before']:>8,}{r['after']:>8,}{pct:>9}   {(r['flag'] or '').upper()}")
    lines.append("")
    lines.append(f"{c['flagged']} flagged." + ("  Investigate before the full run." if c["flagged"] else "  Nothing alarming."))
    return "\n".join(lines)


def get_json(client: ApiClient, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    status, data = client.request(method, path, body)
    if status != 200 or not isinstance(data, dict):
        raise SystemExit(f"{method} {path} failed (HTTP {status}): {str(data)[:200]}")
    return data


def cmd_batch(client: ApiClient, limit: int, yes: bool) -> int:
    result = get_json(client, "POST", "/api/taxonomy/retag", {"limit": limit, "dry_run": not yes})
    if not yes:
        print(f"DRY RUN: {result['would_queue']} calls would be queued ({result['remaining']:,} waiting in total).")
        if result["protected_highlights"]:
            print(f"  {result['protected_highlights']} suggestions would be kept because decisions or confirmed beliefs depend on them.")
        print("Re-run with --yes to queue them. Each call spends LLM tokens.")
        return 0
    print(f"Queued {result['queued']} calls ({result['remaining']:,} still waiting).")
    if result["protected_highlights"]:
        print(f"  Kept {result['protected_highlights']} suggestions that decisions or confirmed beliefs depend on.")
    return 0


def cmd_run(client: ApiClient, batch_size: int, max_batches: int, yes: bool, sleep=time.sleep, poll: float = POLL_SECONDS) -> int:  # noqa: ANN001
    status = get_json(client, "GET", "/api/taxonomy/status")
    print(fmt_status(status))
    if not yes:
        batches = -(-status["eligible"] // batch_size) if status["eligible"] else 0
        print(f"\nDRY RUN: would run {min(batches, max_batches) if max_batches else batches} batch(es) of up to {batch_size}. Re-run with --yes.")
        return 0
    done = 0
    while status["eligible"] > 0 and (not max_batches or done < max_batches):
        result = get_json(client, "POST", "/api/taxonomy/retag", {"limit": batch_size})
        done += 1
        print(f"\nBatch {done}: queued {result['queued']} ({result['remaining']:,} still waiting). Waiting for it to finish...")
        if result["queued"] == 0:
            break
        stuck = 0
        while True:
            sleep(poll)
            status = get_json(client, "GET", "/api/taxonomy/status")
            print(f"  {status['in_progress']} still processing, {status['eligible']:,} waiting")
            if status["in_progress"] == 0:
                break
            stuck += 1
            if stuck > 240:  # an hour of polling at 15s
                print("Stopped waiting: the batch is taking far too long. Check the server, then run again (it resumes).")
                return 1
    print("\n" + fmt_status(get_json(client, "GET", "/api/taxonomy/status")))
    return 0


def main(argv: list[str] | None = None, client: ApiClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8080", help="MomBoard URL (default: your tunnel)")
    parser.add_argument("--email", help="Admin login email (prompted if omitted)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Progress, what is waiting, and a time estimate")
    snap = sub.add_parser("snapshot", help="Record today's tag counts (admin)")
    snap.add_argument("--label", default="before retag")
    sub.add_parser("compare", help="Tag counts now vs the snapshot")
    batch = sub.add_parser("batch", help="Queue the next N calls (dry run unless --yes)")
    batch.add_argument("--limit", type=int, default=100)
    batch.add_argument("--yes", action="store_true")
    run = sub.add_parser("run", help="Retag everything left, batch by batch, waiting between batches")
    run.add_argument("--batch-size", type=int, default=100)
    run.add_argument("--max-batches", type=int, default=0, help="Stop after this many batches (0 = all)")
    run.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    if client is None:
        check_base_is_safe(args.base)
        email = args.email or input("Email: ").strip()
        password = getpass.getpass(f"Password for {email} (hidden): ")
        client = ApiClient(args.base)
        status, body = client.request("POST", "/auth/login", {"email": email, "password": password})
        del password
        if status != 200:
            print(f"Login failed (HTTP {status}). Nothing was changed.")
            return 1

    if args.command == "status":
        print(fmt_status(get_json(client, "GET", "/api/taxonomy/status")))
        return 0
    if args.command == "snapshot":
        snap_data = get_json(client, "POST", "/api/taxonomy/snapshot", {"label": args.label})
        print(f"Snapshot '{snap_data['label']}' saved: {sum(snap_data['counts'].values()):,} highlights across {len(snap_data['counts'])} tags.")
        return 0
    if args.command == "compare":
        print(fmt_compare(get_json(client, "GET", "/api/taxonomy/compare")))
        return 0
    if args.command == "batch":
        return cmd_batch(client, args.limit, args.yes)
    return cmd_run(client, args.batch_size, args.max_batches, args.yes)


if __name__ == "__main__":
    sys.exit(main())
