import json

from graph.engine import ask, items, load_graph, overview
from qa.envelope import INSUFFICIENT, validate

REPO = "o/pyg"


def w(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def make_raw(tmp):
    d = tmp / "o__pyg"
    sha_fix, sha_old, sha_new = "a" * 40, "b" * 40, "c" * 40
    w(d / "meta.json", {"repo": REPO, "fetched_at": "2026-10-26T13:00:00+00:00", "counts": {"commits": 3, "pulls": 1, "issues": 1}, "note": "Bounded slice, most recent items only, not the full history."})
    w(d / "commits.json", [
        {"sha": sha_new, "message": "Refactor session helpers", "author_login": "dev-b", "author_name": "B", "date": "2025-01-10T00:00:00Z", "url": "https://github.com/o/pyg/commit/" + sha_new, "parents": [],
         "files": [{"filename": "pkg/session.py", "status": "modified"}, {"filename": "pkg/util.py", "status": "modified"}]},
        {"sha": sha_old, "message": "Add unrelated thing", "author_login": "dev-b", "author_name": "B", "date": "2025-01-11T00:00:00Z", "url": "https://github.com/o/pyg/commit/" + sha_old, "parents": [],
         "files": [{"filename": "pkg/other.py", "status": "added"}]}])
    w(d / "targeted.json", {"repo": REPO, "issues": [
        {"number": 5, "title": "Bad debug output", "body": "Upstream bug.", "state": "closed", "created_at": "2024-04-27T10:00:00Z", "closed_at": "2024-04-27T11:00:00Z", "user": {"login": "rep"}, "url": "https://github.com/o/pyg/issues/5", "labels": [], "comments": [], "events": []}],
        "pulls": [{"number": 7, "title": "Suppress the decode error", "body": "See https://github.com/o/pyg/issues/5 and https://github.com/up/gmt/pull/99 for the upstream fix.", "state": "closed", "merged_at": "2024-08-05T02:00:00Z", "created_at": "2024-08-01T00:00:00Z", "closed_at": "2024-08-05T02:00:00Z", "user": {"login": "dev-a"}, "url": "https://github.com/o/pyg/pull/7", "merge_commit_sha": sha_fix, "labels": [], "comments": [], "files": [{"filename": "pkg/session.py", "status": "modified"}]}],
        "commits": [{"sha": sha_fix, "message": "Patch the callback to suppress the error (#7)", "author_login": "dev-a", "author_name": "A", "date": "2024-08-05T02:00:00Z", "url": "https://github.com/o/pyg/commit/" + sha_fix, "parents": [], "files": [{"filename": "pkg/session.py", "status": "modified"}]}], "errors": []})
    w(tmp / "up__gmt" / "targeted.json", {"repo": "up/gmt", "issues": [], "commits": [], "errors": [],
        "pulls": [{"number": 99, "title": "Fix debug message", "body": "Fixes https://github.com/o/pyg/issues/5.", "state": "closed", "merged_at": "2024-04-27T11:00:00Z", "created_at": "2024-04-27T10:30:00Z", "closed_at": "2024-04-27T11:00:00Z", "user": {"login": "maint"}, "url": "https://github.com/up/gmt/pull/99", "merge_commit_sha": None, "labels": [], "comments": [], "files": []}]})
    return tmp


def graph(tmp_path):
    return load_graph(REPO, make_raw(tmp_path))


def test_all_modes_produce_valid_envelopes(tmp_path):
    g = graph(tmp_path)
    for mode in ("why", "history", "still_needed", "dna"):
        r = ask(g, "file:pkg/session.py", mode)
        assert validate(r) == [], (mode, validate(r))
        assert r["status"] == "answered"


def test_why_links_commit_pr_issue_and_cross_repo(tmp_path):
    r = ask(graph(tmp_path), "file:pkg/session.py", "why")
    text = " ".join(a["text"] for a in r["answer"])
    assert "PR #7" in text and "issue #5" in text and "up/gmt" in text
    assert all(a["label"] == "verified" for a in r["answer"])
    assert r["confidence"]["level"] == "high"
    assert r["who_to_ask"]["login"] == "dev-a"


def test_file_with_no_history_abstains(tmp_path):
    r = ask(graph(tmp_path), "file:pkg/missing.py", "why")
    assert r["status"] == "insufficient_evidence" and r["message"] == INSUFFICIENT and r["answer"] == []


def test_file_without_links_is_honest_not_invented(tmp_path):
    r = ask(graph(tmp_path), "file:pkg/other.py", "why")
    assert validate(r) == []
    assert any(a["label"] == "unknown" for a in r["answer"])
    assert r["decision"] is None


def test_no_drift_when_fix_came_before_the_change(tmp_path):
    r = ask(graph(tmp_path), "file:pkg/session.py", "still_needed")
    assert r["drift_alert"] is None
    assert any(a["label"] == "unknown" and "already resolved" in a["text"] for a in r["answer"])


def test_drift_fires_when_reason_resolved_after_the_change(tmp_path):
    g = graph(tmp_path)
    g.issues[5]["closed_at"] = "2025-06-01T00:00:00Z"          # issue closed AFTER the workaround
    g.external[("up/gmt", "pull", 99)]["merged_at"] = "2025-06-01T00:00:00Z"
    r = ask(g, "file:pkg/session.py", "still_needed")
    assert validate(r) == []
    d = r["drift_alert"]
    assert d["label"] == "Possibly outdated. Verify." and d["original_reason_evidence"] and d["later_change_evidence"]
    assert d["workaround_still_in_code"]["checked"] is False


def test_revert_marks_decision_superseded(tmp_path):
    g = graph(tmp_path)
    rev = "d" * 40
    g.commits[rev] = {"sha": rev, "message": 'Revert "Patch"\n\nThis reverts commit ' + "a" * 40, "author_login": "x", "author_name": "x",
                      "date": "2025-02-01T00:00:00Z", "url": "https://github.com/o/pyg/commit/" + rev, "parents": [], "files": [{"filename": "pkg/session.py", "status": "modified"}]}
    g.file_commits["pkg/session.py"].append(rev)
    g.reverted_by["a" * 40] = rev
    r = ask(g, "file:pkg/session.py", "history")
    assert validate(r) == []
    assert r["decision"]["status"] == "superseded" and any(t["event"] == "supersession" for t in r["timeline"])


def test_renames_are_followed(tmp_path):
    g = graph(tmp_path)
    g.commits["e" * 40] = {"sha": "e" * 40, "message": "Rename", "author_login": "x", "author_name": "x", "date": "2025-03-01T00:00:00Z", "url": "https://github.com/o/pyg/commit/" + "e" * 40,
                           "parents": [], "files": [{"filename": "pkg/new_session.py", "status": "renamed", "previous_filename": "pkg/session.py"}]}
    g.file_commits["pkg/new_session.py"].append("e" * 40)
    g.prev["pkg/new_session.py"] = "pkg/session.py"
    r = ask(g, "file:pkg/new_session.py", "why")
    assert r["status"] == "answered" and "PR #7" in " ".join(a["text"] for a in r["answer"])


def test_dna_changed_together_is_inferred(tmp_path):
    r = ask(graph(tmp_path), "file:pkg/session.py", "dna")
    assert r["dna"]["changed_together"][0]["path"] == "pkg/util.py"
    assert r["dna"]["changed_together"][0]["evidence_type"] == "inferred"


def test_free_question_routes_without_llm(tmp_path):
    r = ask(graph(tmp_path), "file:pkg/session.py", "free", "Why is it still there?")
    assert r["mode"] == "free" and r["routed_mode"] == "still_needed" and validate(r) == []
    assert ask(graph(tmp_path), "file:pkg/session.py", "free", "What is this code?")["status"] == "insufficient_evidence"


def test_overview_numbers_obey_the_schema_rules(tmp_path):
    o = overview(graph(tmp_path))
    c = o["counts"]
    assert c["explained"] + c["unknown"] == c["total_items"]
    assert c["unchanged_since_decision"] + c["changed_since_decision"] + c["superseded"] <= c["explained"]
    assert c["explained"] == 1 and c["changed_since_decision"] == 1 and c["possibly_outdated"] == 0
    assert "Bounded slice" in o["ingested"]["note"]


def test_items_lists_explained_first(tmp_path):
    it = items(graph(tmp_path))["items"]
    assert it[0]["label"] == "pkg/session.py" and it[0]["state"] == "explained"
    assert items(graph(tmp_path), "other")["items"][0]["state"] == "unknown"
