"""scripts/retag_rollout.py against a fake API client."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"


def load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("retag_rollout", SCRIPTS / "retag_rollout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClient:
    def __init__(self, eligible=250):
        self.eligible, self.in_progress, self.calls = eligible, 0, []
        self.pending_done = 0

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/taxonomy/status":
            if self.in_progress:               # the previous batch "finishes" on the next poll
                self.in_progress = 0
            return 200, {"version": 2, "total_calls": 1000, "calls_on_current": 1000 - self.eligible, "tags": [],
                         "eligible": self.eligible, "in_progress": self.in_progress, "seconds_per_call": 30.0, "estimated_minutes": 125}
        if path == "/api/taxonomy/retag":
            take = min(body["limit"], self.eligible)
            if body.get("dry_run"):
                return 200, {"queued": 0, "would_queue": take, "remaining": self.eligible, "ids": [], "protected_highlights": 2, "taxonomy_version": 2}
            self.eligible -= take
            self.in_progress = take
            return 200, {"queued": take, "would_queue": take, "remaining": self.eligible, "ids": [], "protected_highlights": 1, "taxonomy_version": 2}
        if path == "/api/taxonomy/snapshot":
            return 200, {"label": body["label"], "taken_at": "t", "counts": {"pain": 3, "money": 2}}
        if path == "/api/taxonomy/compare":
            return 200, {"snapshot": {"label": "before pilot", "taken_at": "t"}, "flagged": 1,
                         "rows": [{"key": "pain", "name": "Pain", "before": 20, "after": 60, "delta": 40, "pct": 200, "flag": "jumped"}]}
        return 404, "no"


def test_status_prints_progress_and_the_estimate(capsys):
    assert load().main(["status"], client=FakeClient()) == 0
    out = capsys.readouterr().out
    assert "750 of 1,000" in out and "250" in out and "~125 min" in out and "30s per call" in out


def test_batch_is_a_dry_run_by_default(capsys):
    c = FakeClient()
    assert load().main(["batch", "--limit", "100"], client=c) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "kept because decisions" in out
    assert c.calls[-1][2]["dry_run"] is True


def test_batch_yes_really_queues(capsys):
    c = FakeClient()
    load().main(["batch", "--limit", "100", "--yes"], client=c)
    assert c.calls[-1][2] == {"limit": 100, "dry_run": False} and "Queued 100" in capsys.readouterr().out


def test_snapshot_and_compare(capsys):
    c = FakeClient()
    load().main(["snapshot", "--label", "before pilot"], client=c)
    assert "5 highlights across 2 tags" in capsys.readouterr().out
    load().main(["compare"], client=c)
    out = capsys.readouterr().out
    assert "JUMPED" in out and "+200%" in out and "Investigate before the full run" in out


def test_run_is_a_dry_run_unless_yes(capsys):
    c = FakeClient()
    assert load().main(["run", "--batch-size", "100"], client=c) == 0
    assert "would run 3 batch(es)" in capsys.readouterr().out
    assert not [x for x in c.calls if x[1] == "/api/taxonomy/retag"]


def test_run_works_through_every_batch_and_waits_between_them(capsys):
    mod = load()
    c = FakeClient(eligible=250)
    sleeps: list[float] = []
    rc = mod.cmd_run(c, 100, 0, True, sleep=sleeps.append, poll=0)
    assert rc == 0 and c.eligible == 0
    queued = [x[2]["limit"] for x in c.calls if x[1] == "/api/taxonomy/retag"]
    assert queued == [100, 100, 100]        # 100 + 100 + 50, the last asks for 100 but only 50 remain
    assert len(sleeps) == 3                 # waited for each batch to drain


def test_run_respects_max_batches():
    mod = load()
    c = FakeClient(eligible=1000)
    mod.cmd_run(c, 100, 2, True, sleep=lambda s: None, poll=0)
    assert c.eligible == 800


def test_refuses_plain_http_to_a_remote_host():
    with pytest.raises(SystemExit):
        load().main(["--base", "http://203.0.113.5:8080", "status"])


def test_a_failed_request_exits_with_a_message():
    class Down:
        def request(self, *a, **k):
            return 500, "boom"

    with pytest.raises(SystemExit, match="failed"):
        load().main(["status"], client=Down())
