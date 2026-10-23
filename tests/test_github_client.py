import json
from pathlib import Path

import pytest

from ingest.fetch_repo import fetch_issues, fetch_repo, parse_repo
from ingest.github_client import GitHubClient, GitHubError


class FakeResp:
    def __init__(self, data, status=200, headers=None, next_url=None):
        self._data, self.status_code = data, status
        self.headers = headers or {}
        self.links = {"next": {"url": next_url}} if next_url else {}
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeSession:
    """Returns queued responses in order; records requested URLs."""

    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.urls = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        return self.responses.pop(0)


def client(responses):
    return GitHubClient(token="x", session=FakeSession(responses), sleep=lambda s: None)


def test_parse_repo_accepts_url_and_slug():
    assert parse_repo("https://github.com/psf/requests/") == "psf/requests"
    assert parse_repo("psf/requests") == "psf/requests"
    assert parse_repo("https://github.com/psf/requests.git") == "psf/requests"
    with pytest.raises(ValueError):
        parse_repo("not a repo")


def test_pagination_follows_next_and_respects_max_items():
    c = client([FakeResp([1, 2], next_url="https://api.github.com/p2"), FakeResp([3, 4])])
    assert list(c.paginate("/x")) == [1, 2, 3, 4]
    c = client([FakeResp([1, 2], next_url="https://api.github.com/p2"), FakeResp([3, 4])])
    assert list(c.paginate("/x", max_items=3)) == [1, 2, 3]


def test_rate_limit_far_in_future_raises_helpful_error():
    far = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "99999999999"}
    c = client([FakeResp({}, status=403, headers=far)])
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        c.get("/x")


def test_404_raises():
    c = client([FakeResp({}, status=404)])
    with pytest.raises(GitHubError, match="Not found"):
        c.get("/nope")


def test_issues_skip_pull_requests():
    items = [
        {"number": 1, "title": "real issue", "body": None, "state": "open", "created_at": "t", "closed_at": None,
         "user": {"login": "a", "html_url": "u"}, "html_url": "h1", "labels": [{"name": "bug"}]},
        {"number": 2, "title": "a PR", "pull_request": {}, "html_url": "h2"},
    ]
    c = client([FakeResp(items), FakeResp([])])  # issues page, then comments for #1
    out = fetch_issues(c, "o/r", limit=10)
    assert [i["number"] for i in out] == [1]
    assert out[0]["labels"] == ["bug"] and out[0]["body"] == ""


def test_fetch_repo_writes_files_and_meta(tmp_path):
    commit = {"sha": "abc", "commit": {"message": "m", "author": {"name": "n", "date": "d"}}, "html_url": "u",
              "author": {"login": "a"}, "parents": []}
    detail = {"files": [{"filename": "a.py", "status": "renamed", "previous_filename": "b.py"}]}
    c = client([FakeResp([commit]), FakeResp(detail), FakeResp([]), FakeResp([])])
    out = fetch_repo(c, "o/r", tmp_path, 1, 1, 1)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["counts"] == {"commits": 1, "pulls": 0, "issues": 0}
    commits = json.loads((out / "commits.json").read_text())
    assert commits[0]["files"][0]["previous_filename"] == "b.py"


def test_sample_answers_cite_only_existing_evidence():
    import re
    for f in Path("data/sample").glob("answer_*.json"):
        d = json.loads(f.read_text())
        ids = {e["id"] for e in d["evidence"]}
        cited = set(re.findall(r"\[(ev\d+)\]", d["answer"]))
        assert cited <= ids, f"{f.name} cites unknown evidence {cited - ids}"
        if d["status"] == "insufficient_evidence":
            assert d["evidence"] == [] and d["confidence"]["level"] == "none"
