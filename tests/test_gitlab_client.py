import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitlab_client import GitLab

API = "https://git.corp/gitlab/api/v4/projects/team%2Fsub%2Fapp/merge_requests/7"
LINK = "https://git.corp/gitlab/team/sub/app/-/merge_requests/7"


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def json(self):
        return self.data


def gitlab(monkeypatch, responses):
    gl = GitLab("https://git.corp/gitlab/", "tok")
    assert gl.session.headers["PRIVATE-TOKEN"] == "tok"
    monkeypatch.setattr(gl.session, "get", lambda url, timeout: responses[url])
    return gl


def test_tracks_only_own_host():
    gl = GitLab("https://git.corp", "tok")
    assert gl.tracks("https://git.corp/a/b/-/merge_requests/1")
    assert not gl.tracks("https://gitlab.com/a/b/-/merge_requests/1")
    assert not gl.tracks("https://github.com/a/b/pull/1")


def test_open_unapproved_mr_is_not_done(monkeypatch):
    gl = gitlab(monkeypatch, {API: Resp({"state": "opened"}), f"{API}/approvals": Resp({"approved_by": []})})
    assert gl.is_done(LINK) is False


def test_approved_or_merged_mr_is_done(monkeypatch):
    approved = {API: Resp({"state": "opened"}), f"{API}/approvals": Resp({"approved_by": [{"user": {}}]})}
    assert gitlab(monkeypatch, approved).is_done(LINK) is True
    assert gitlab(monkeypatch, {API: Resp({"state": "merged"})}).is_done(LINK) is True


def test_api_error_gives_unknown(monkeypatch):
    assert gitlab(monkeypatch, {API: Resp({}, status=404)}).is_done(LINK) is None


USERS = "https://git.corp/gitlab/api/v4/users?username=alice.gl"


def gitlab_with_put(monkeypatch, reviewers, users=({"id": 5},)):
    gl = gitlab(monkeypatch, {API: Resp({"reviewers": reviewers}), USERS: Resp(list(users))})
    puts = []
    monkeypatch.setattr(gl.session, "put", lambda url, json, timeout: puts.append((url, json)) or Resp({}))
    return gl, puts


def test_add_reviewer_keeps_existing(monkeypatch):
    gl, puts = gitlab_with_put(monkeypatch, [{"id": 3}])
    assert gl.add_reviewer(LINK, "alice.gl") is True
    assert puts == [(API, {"reviewer_ids": [3, 5]})]


def test_add_reviewer_already_there(monkeypatch):
    gl, puts = gitlab_with_put(monkeypatch, [{"id": 5}])
    assert gl.add_reviewer(LINK, "alice.gl") is True
    assert puts == []


def test_add_reviewer_unknown_user(monkeypatch):
    gl, puts = gitlab_with_put(monkeypatch, [], users=())
    assert gl.add_reviewer(LINK, "alice.gl") is False
    assert puts == []
