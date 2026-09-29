"""Merge request status from a GitLab instance, through its REST API."""

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

    def _mr_api(self, link: str) -> str:
        path = urlparse(link).path.removeprefix(self.prefix).strip("/")
        project, _, iid = path.partition("/-/merge_requests/")
        return f"{self.base}/api/v4/projects/{quote(project, safe='')}/merge_requests/{iid}"

    def _get(self, url: str):
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
