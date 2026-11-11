#!/usr/bin/env python3
"""Measure the tagger on a hand-tagged test set and apply the retag gate (v0.5 D5).

    python scripts/eval_tagger.py path/to/testset.json
    python scripts/eval_tagger.py path/to/testset.json --tags-json tags.json --threshold 0.8

It tags every call in the test set with the REAL tagger (your configured LLM backend, so it
costs a few LLM calls per call) using the same pipeline as production, then reports per-tag
precision and recall and whether the ten most-used tags reach the threshold. Exit code 0 means
the gate passed; 1 means it failed (do not start a full retag); 2 means a usage/setup problem.

Safety: it works in a THROWAWAY database in a temporary directory (migrated from scratch), so it
never reads or writes your real data. The test set itself is read-only.

Custom tags: the throwaway database only has the core taxonomy. To evaluate your custom tags,
export your tags once (``GET /api/tags`` while logged in) into a JSON file and pass --tags-json.
The test-set format is documented in documentation/guides/tagger-evaluation.md; real test sets contain customer
text, so keep them out of the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TAG_COLUMNS = {
    "key", "emoji", "name", "description", "signal_strength", "sort_order", "is_active",
    "origin", "category", "min_confidence", "negative_hint", "example",
}


def load_tags(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, list):
        raise SystemExit("--tags-json must contain a JSON list of tags (as returned by GET /api/tags)")
    return [{k: v for k, v in t.items() if k in TAG_COLUMNS} for t in raw if isinstance(t, dict) and t.get("key")]


def migrate(db_file: Path) -> None:
    """Create the schema in a fresh database with the project's own migrations."""
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit(f"Could not prepare the throwaway database:\n{result.stderr[-800:]}")


async def evaluate(args: argparse.Namespace, llm_factory: Callable[[Any], Any]) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.llm.seller import SellerProfile, set_seller_profile
    from app.llm.tagger_eval import (
        format_report,
        gate,
        load_test_set,
        run_evaluation,
        top_tags_by_usage,
    )

    try:
        test_set = load_test_set(args.testset)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"Cannot use that test set: {err}")
        return 2
    if not test_set.calls:
        print("The test set has no calls.")
        return 2

    if args.company_name:
        set_seller_profile(SellerProfile(name=args.company_name, aliases=args.alias or [], email_domains=args.domain or []))

    utterances = sum(len(c.utterances) for c in test_set.calls)
    print(f"Test set: {len(test_set.calls)} calls, {utterances} utterances, {len(test_set.expected())} expected highlights")

    with tempfile.TemporaryDirectory(prefix="momboard-eval-") as tmp:
        db_file = Path(tmp) / "eval.db"
        migrate(db_file)
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            report = await run_evaluation(test_set, llm_factory, factory, tags=load_tags(args.tags_json))
        finally:
            await engine.dispose()

    top = top_tags_by_usage(test_set.expected(), args.top)
    result = gate(report.scores, top, args.threshold)
    print(f"Predicted {report.predicted_total} highlights (after the sides / filler / one-tag-per-quote rules).\n")
    print(format_report(report, result, top))
    return 0 if result.passed else 1


def main(argv: list[str] | None = None, llm_factory: Callable[[Any], Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("testset", help="Path to the hand-tagged test-set JSON")
    parser.add_argument("--tags-json", help="Your tags (GET /api/tags output) to include custom tags")
    parser.add_argument("--threshold", type=float, default=0.8, help="Minimum precision per top tag (default 0.8)")
    parser.add_argument("--top", type=int, default=10, help="How many most-used tags the gate checks (default 10)")
    parser.add_argument("--company-name", help="Your company name (as in Settings -> Your company)")
    parser.add_argument("--alias", action="append", help="A company alias (repeatable)")
    parser.add_argument("--domain", action="append", help="A company email domain (repeatable)")
    args = parser.parse_args(argv)

    if llm_factory is None:
        from app.config import get_settings
        from app.llm.factory import create_llm_client

        settings = get_settings()

        def llm_factory(_call: Any) -> Any:  # noqa: ANN401 - mirrors the injectable signature
            return create_llm_client(settings, agent="tagger")

    return asyncio.run(evaluate(args, llm_factory))


if __name__ == "__main__":
    sys.exit(main())
