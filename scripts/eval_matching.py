#!/usr/bin/env python3
"""Check hypothesis matching against beliefs with known answers (v0.5 D8).

    python scripts/eval_matching.py path/to/known_beliefs.json

For each belief it runs the REAL matching (broad search, then strict judging) over the database
in DATABASE_URL, and checks that the known call appears in the top 5 and that at most 1 in 5
matches is a call you labelled unrelated. Exit code 0 = passed, 1 = failed, 2 = bad input.

Read-only: the database is opened read-only and the preview never saves. It does spend LLM calls
(roughly 10-20 per belief). Format and advice: docs/matching-evaluation.md. The real list names
real calls, so keep it out of the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def readonly_url(database_url: str) -> str:
    """A read-only SQLite URL for the given DATABASE_URL (refuses anything else)."""
    if not database_url.startswith("sqlite"):
        raise SystemExit("This check only supports a SQLite DATABASE_URL (it opens the file read-only).")
    path = database_url.split(":///", 1)[1]
    if not path.startswith("/"):
        path = str((ROOT / path).resolve())
    return f"sqlite+aiosqlite:///file:{path}?mode=ro&uri=true"


async def evaluate(args: argparse.Namespace, llm_factory=None) -> int:  # noqa: ANN001
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.services.matching_eval import gate, load_beliefs, run_evaluation

    try:
        beliefs = load_beliefs(args.beliefs)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"Cannot use that file: {err}")
        return 2
    if not beliefs:
        print("The file has no beliefs.")
        return 2

    settings = get_settings()
    url = readonly_url(args.db or settings.database_url)
    if llm_factory is None:
        from app.llm.factory import create_llm_client

        def llm_factory(_belief):  # noqa: ANN001, ANN202
            return create_llm_client(settings, agent="corpus_chat")

    engine = create_async_engine(url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            from app.services.seller_profile import refresh_seller_profile

            async with factory() as db:
                await refresh_seller_profile(db)
        except Exception:  # noqa: BLE001 - older database without app_settings: carry on without it
            pass
        print(f"Checking {len(beliefs)} beliefs against {Path(url.split('file:')[1].split('?')[0]).name} (read-only)...\n")
        report = await run_evaluation(beliefs, llm_factory, factory)
    finally:
        await engine.dispose()

    labelled = any(b.unrelated for b in beliefs)
    for belief, result, matches in zip(beliefs, report.results, report.match_lists, strict=True):
        status = f"found at #{result.hit_rank}" if result.hit_rank else "NOT FOUND"
        flag = "ok  " if result.found_in_top else "FAIL"
        print(f"[{flag}] {belief.belief[:70]}")
        print(f"        {status}; {result.total} matches, {result.unrelated} labelled unrelated")
        if args.verbose:
            for i, m in enumerate(matches, start=1):
                title = report.titles_by_conversation.get(m["conversation_id"], "?")
                print(f"          {i}. {m['confidence']:.2f} {title[:40]} - {m['quote'][:70]}")
    outcome = gate(report.results, labelled)
    rate = "n/a (no 'unrelated' calls labelled)" if outcome.unrelated_rate is None else f"{outcome.unrelated_rate:.0%}"
    print(f"\nUnrelated rate: {rate}")
    print("GATE PASSED" if outcome.passed else "GATE FAILED")
    for reason in outcome.reasons:
        print(f"  - {reason}")
    return 0 if outcome.passed else 1


def main(argv: list[str] | None = None, llm_factory=None) -> int:  # noqa: ANN001
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("beliefs", help="Path to the known-beliefs JSON")
    parser.add_argument("--db", help="SQLite database URL, e.g. sqlite+aiosqlite:///data/momboard.db (default: DATABASE_URL)")
    parser.add_argument("-v", "--verbose", action="store_true", help="List every match")
    return asyncio.run(evaluate(parser.parse_args(argv), llm_factory))


if __name__ == "__main__":
    sys.exit(main())
