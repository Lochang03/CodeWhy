import json

import pytest

from ingest.fetch_repo import fetch_issues, parse_repo
from ingest.github_client import GitHubClient, GitHubError


class FakeResp:
    def __init__(self, status=200, data=None, headers=None, links=None):
        self.status_code = status
        self._data = data if data is not None else []
        self.headers = headers or {}
        self.links = links or {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def client(responses):
    return GitHubClient(token="x", session=FakeSession(responses), sleep=lambda s: None)


def test_parse_repo_variants():
    assert parse_repo("https://github.com/psf/requests") == "psf/requests"
    assert parse_repo("psf/requests/") == "psf/requests"
    assert parse_repo("https://github.com/psf/requests.git") == "psf/requests"
    with pytest.raises(ValueError):
        parse_repo("not a repo")


def test_paginate_follows_next_link():
    c = client([
        FakeResp(data=[{"n": 1}, {"n": 2}], links={"next": {"url": "https://api.github.com/page2"}}),
        FakeResp(data=[{"n": 3}]),
    ])
    assert [i["n"] for i in c.paginate("/x")] == [1, 2, 3]


def test_paginate_respects_max_items():
    c = client([FakeResp(data=[{"n": 1}, {"n": 2}, {"n": 3}])])
    assert len(list(c.paginate("/x", max_items=2))) == 2


def test_rate_limit_far_away_raises_helpful_error():
    far = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "99999999999"}
    c = client([FakeResp(status=403, headers=far)])
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        c.get("/x")


def test_not_found_raises():
    c = client([FakeResp(status=404)])
    with pytest.raises(GitHubError, match="Not found"):
        c.get("/repos/a/b")


def test_server_error_retries_then_succeeds():
    c = client([FakeResp(status=502), FakeResp(data=[{"ok": 1}])])
    assert c.get("/x").json() == [{"ok": 1}]


def test_issues_skip_pull_requests():
    issue = {"number": 1, "title": "bug", "body": None, "state": "closed", "created_at": "2022-01-01T00:00:00Z",
             "closed_at": "2022-02-01T00:00:00Z", "user": {"login": "a", "html_url": "u"},
             "html_url": "https://github.com/a/b/issues/1", "labels": [{"name": "bug"}]}
    pr_as_issue = dict(issue, number=2, pull_request={"url": "x"})
    c = client([FakeResp(data=[pr_as_issue, issue]), FakeResp(data=[])])  # list page, then comments of #1
    out = fetch_issues(c, "a/b", limit=10)
    assert [i["number"] for i in out] == [1]
    assert out[0]["body"] == ""
    assert out[0]["labels"] == ["bug"]
