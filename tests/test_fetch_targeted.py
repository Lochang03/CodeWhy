import json

from ingest.fetch_targeted import fetch_targeted
from ingest.github_client import GitHubClient


class FakeResp:
    status_code = 200

    def __init__(self, data):
        self._d = data
        self.headers, self.links, self.text = {}, {}, ""

    def json(self):
        return self._d


class FakeSession:
    """Routes by URL so no network is needed."""
    def __init__(self, routes):
        self.routes, self.headers, self.calls = routes, {}, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        path = url.replace("https://api.github.com", "")
        for suffix, data in self.routes.items():
            if path == suffix:
                return FakeResp(data)
        return type("R", (), {"status_code": 404, "headers": {}, "links": {}, "text": "", "json": lambda s: {}})()


USER = {"login": "dev"}
ISSUE = {"number": 5, "title": "Bug", "body": "b", "state": "closed", "created_at": "2024-01-01", "closed_at": "2024-02-01",
         "user": USER, "html_url": "https://github.com/o/r/issues/5", "labels": [{"name": "bug"}]}
PR = {"number": 7, "title": "Fix", "body": "Closes #5", "state": "closed", "merged_at": "2024-02-01", "created_at": "2024-01-30",
      "closed_at": "2024-02-01", "user": USER, "html_url": "https://github.com/o/r/pull/7", "merge_commit_sha": "abc", "labels": []}
COMMIT = {"sha": "abc123", "commit": {"message": "m", "author": {"name": "D", "date": "2024-02-01"}}, "author": USER,
          "html_url": "https://github.com/o/r/commit/abc123", "parents": [{"sha": "p"}],
          "files": [{"filename": "a.py", "status": "modified"}]}


def make(routes):
    return GitHubClient(token="x", session=FakeSession(routes), sleep=lambda s: None)


def test_fetches_issue_pull_commit_and_records_close_event(tmp_path):
    routes = {
        "/repos/o/r/issues/5": ISSUE, "/repos/o/r/issues/5/comments": [],
        "/repos/o/r/issues/5/events": [{"event": "closed", "created_at": "2024-02-01", "actor": USER, "commit_id": "abc123"}],
        "/repos/o/r/pulls/7": PR, "/repos/o/r/issues/7/comments": [], "/repos/o/r/pulls/7/comments": [],
        "/repos/o/r/pulls/7/files": [{"filename": "a.py", "status": "modified"}],
        "/repos/o/r/commits/abc123": COMMIT,
    }
    res = fetch_targeted(make(routes), "o/r", tmp_path, issues=[5], pulls=[7], commits=["abc123"])
    assert res["errors"] == []
    assert res["issues"][0]["events"][0]["commit_id"] == "abc123"
    assert res["pulls"][0]["files"][0]["filename"] == "a.py"
    assert res["commits"][0]["files"][0]["filename"] == "a.py"
    saved = json.loads((tmp_path / "o__r" / "targeted.json").read_text(encoding="utf-8"))
    assert saved["issues"][0]["number"] == 5


def test_issue_number_that_is_a_pr_is_reported_not_hidden(tmp_path):
    routes = {"/repos/o/r/issues/7": {**ISSUE, "number": 7, "pull_request": {"url": "x"}}}
    res = fetch_targeted(make(routes), "o/r", tmp_path, issues=[7])
    assert res["issues"] == [] and "pull request" in res["errors"][0]["error"]


def test_missing_item_is_recorded_and_others_continue(tmp_path):
    routes = {"/repos/o/r/commits/abc123": COMMIT}
    res = fetch_targeted(make(routes), "o/r", tmp_path, pulls=[999], commits=["abc123"])
    assert len(res["commits"]) == 1 and res["errors"][0]["ref"] == "999"