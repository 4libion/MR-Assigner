import sys
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assigner import Reviewer, State, due_reminder, extract_links, pick_reviewer

A, B, C = Reviewer(1, "A"), Reviewer(2, "B"), Reviewer(3, "C")


def test_extract_github_and_gitlab_links():
    text = (
        "please review https://github.com/Org/Repo/pull/42/files?x=1 and "
        "https://gitlab.example.com/group/sub/repo/-/merge_requests/7#note_1"
    )
    assert extract_links(text) == [
        "https://github.com/org/repo/pull/42",
        "https://gitlab.example.com/group/sub/repo/-/merge_requests/7",
    ]


def test_extract_dedupes_and_ignores_non_pr_links():
    text = "https://github.com/o/r/pull/1 https://github.com/o/r/pull/1/ https://github.com/o/r/issues/2"
    assert extract_links(text) == ["https://github.com/o/r/pull/1"]


def test_round_robin(tmp_path):
    s = State(tmp_path / "s.json")
    picks = [pick_reviewer([A, B, C], s, author_id=99).name for _ in range(4)]
    assert picks == ["A", "B", "C", "A"]


def test_skips_author(tmp_path):
    s = State(tmp_path / "s.json")
    assert pick_reviewer([A, B, C], s, author_id=1).name == "B"
    assert pick_reviewer([A, B, C], s, author_id=3).name == "A"


def test_no_reviewer_when_only_author(tmp_path):
    s = State(tmp_path / "s.json")
    assert pick_reviewer([A], s, author_id=1) is None


def test_state_persists(tmp_path):
    path = tmp_path / "data" / "s.json"
    s = State(path)
    pick_reviewer([A, B, C], s, author_id=99)
    s.assigned["https://github.com/o/r/pull/1"] = 1
    s.save()
    s2 = State(path)
    assert s2.next_index == 1
    assert "https://github.com/o/r/pull/1" in s2.assigned


TIMES = [time(9), time(14)]
MON = datetime(2026, 9, 28)


def test_due_reminder_picks_latest_passed_slot():
    assert due_reminder(MON.replace(hour=8, minute=59), None, TIMES) is None
    assert due_reminder(MON.replace(hour=9, minute=10), None, TIMES) == MON.replace(hour=9)
    assert due_reminder(MON.replace(hour=14), MON.replace(hour=9), TIMES) == MON.replace(hour=14)


def test_due_reminder_not_twice_or_stale_or_on_weekend():
    assert due_reminder(MON.replace(hour=9, minute=30), MON.replace(hour=9), TIMES) is None
    assert due_reminder(MON.replace(hour=10, minute=1), None, TIMES) is None
    assert due_reminder(datetime(2026, 9, 27, 9, 5), None, TIMES) is None  # Sunday


def test_state_persists_reminder_and_done(tmp_path):
    s = State(tmp_path / "s.json")
    s.done.add("x")
    s.last_reminder = MON.replace(hour=9)
    s.save()
    s2 = State(tmp_path / "s.json")
    assert s2.done == {"x"} and s2.last_reminder == MON.replace(hour=9)
