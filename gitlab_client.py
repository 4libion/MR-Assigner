"""Merge request status and reviewers on a GitLab instance, through its REST API."""

from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

import requests

log = logging.getLogger("mr-assigner")


class GitLab:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/")
        parsed = urlparse(self.base)
        self.host = parsed.netloc.lower()
        self.prefix = parsed.path  # set when GitLab is served under a subpath
        self.session = requests.Session()
        self.session.headers["PRIVATE-TOKEN"] = token
        self._user_ids: dict[str, int] = {}  # username -> user id

    def tracks(self, link: str) -> bool:
        """Whether the link is a merge request on this GitLab instance."""
        return urlparse(link).netloc == self.host and "/-/merge_requests/" in link

    def is_done(self, link: str) -> bool | None:
        """True if the MR is merged, closed or approved by anyone; False if it
        still waits for review; None if the status couldn't be read."""
        api = self._mr_api(link)
        try:
            if self._get(api)["state"] != "opened":
                return True
            return bool(self._get(f"{api}/approvals").get("approved_by"))
        except (requests.RequestException, ValueError, KeyError) as e:
            log.warning("GitLab status for %s failed: %s", link, e)
            return None

    def add_reviewer(self, link: str, username: str) -> bool:
        """Add the user to the MR's reviewers, keeping the ones already there."""
        api = self._mr_api(link)
        try:
            user_id = self._user_id(username)
            reviewer_ids = [r["id"] for r in self._get(api).get("reviewers", [])]
            if user_id not in reviewer_ids:
                # The API replaces the whole list, so send the existing reviewers too.
                resp = self.session.put(
                    api, json={"reviewer_ids": reviewer_ids + [user_id]}, timeout=10
                )
                resp.raise_for_status()
            return True
        except (requests.RequestException, ValueError, KeyError, LookupError) as e:
            log.warning("Adding reviewer %s to %s failed: %s", username, link, e)
            return False

    def _user_id(self, username: str) -> int:
        if username not in self._user_ids:
            users = self._get(f"{self.base}/api/v4/users?username={quote(username)}")
            if not users:
                raise LookupError(f"no GitLab user {username!r}")
            self._user_ids[username] = users[0]["id"]
        return self._user_ids[username]

    def _mr_api(self, link: str) -> str:
        path = urlparse(link).path.removeprefix(self.prefix).strip("/")
        project, _, iid = path.partition("/-/merge_requests/")
        return f"{self.base}/api/v4/projects/{quote(project, safe='')}/merge_requests/{iid}"

    def _get(self, url: str):
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
