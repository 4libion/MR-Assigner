import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assigner import Reviewer, State, extract_links, pick_reviewer

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


def test_state_persists_done(tmp_path):
    s = State(tmp_path / "s.json")
    s.done.add("x")
    s.save()
    assert State(tmp_path / "s.json").done == {"x"}
