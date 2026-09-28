"""Core logic: link detection, round-robin selection and persistent state.

Kept free of Telegram code so it can be unit-tested directly.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

# GitHub pull requests: https://github.com/<owner>/<repo>/pull/<number>[/files...]
# GitLab merge requests: https://<host>/<group>/.../<repo>/-/merge_requests/<number>
LINK_RE = re.compile(
    r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)"
    r"|https?://([\w.-]+)/([\w./-]+?)/-/merge_requests/(\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reviewer:
    id: int
    name: str
    username: str | None = None


def extract_links(text: str) -> list[str]:
    """Return canonical PR/MR URLs found in text, deduplicated, in order."""
    links: list[str] = []
    for m in LINK_RE.finditer(text or ""):
        if m.group(1):
            owner, repo, num = m.group(1), m.group(2), m.group(3)
            url = f"https://github.com/{owner}/{repo}/pull/{num}".lower()
        else:
            host, path, num = m.group(4), m.group(5), m.group(6)
            url = f"https://{host}/{path}/-/merge_requests/{num}".lower()
        if url not in links:
            links.append(url)
    return links


class State:
    """Round-robin pointer plus already-assigned links, persisted to JSON."""

    def __init__(self, path: Path):
        self.path = path
        self.next_index = 0
        self.assigned: dict[str, int] = {}  # link -> reviewer id
        if path.exists():
            data = json.loads(path.read_text())
            self.next_index = data.get("next_index", 0)
            self.assigned = data.get("assigned", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"next_index": self.next_index, "assigned": self.assigned}
        # Write atomically so a crash mid-write can't corrupt the state file.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)


def pick_reviewer(
    reviewers: list[Reviewer], state: State, author_id: int
) -> Reviewer | None:
    """Pick the next reviewer in rotation who isn't the author.

    Advances the pointer past the chosen reviewer. If the author's turn comes
    up, they are skipped and the next person is chosen. Returns None when no
    one other than the author is available.
    """
    n = len(reviewers)
    for offset in range(n):
        idx = (state.next_index + offset) % n
        if reviewers[idx].id != author_id:
            state.next_index = (idx + 1) % n
            return reviewers[idx]
    return None
