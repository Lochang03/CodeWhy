from fastapi.testclient import TestClient

from api.main import app
from qa.envelope import validate

c = TestClient(app)
SAMPLE = "sample/synthetic"
ITEM = "file:src/net/retry.py"


def test_health():
    assert c.get("/health").json() == {"status": "ok"}


def test_repos_lists_synthetic_sample_labelled():
    repos = c.get("/repos").json()["repos"]
    assert any(r["repo"] == SAMPLE and r["synthetic"] for r in repos)


def test_overview_and_items_for_sample():
    o = c.get("/repos/sample/synthetic/overview").json()
    k = o["counts"]
    assert k["explained"] + k["unknown"] == k["total_items"]
    assert k["unchanged_since_decision"] + k["changed_since_decision"] + k["superseded"] <= k["explained"]
    assert "ingested" in o
    assert c.get("/repos/sample/synthetic/items?q=retry").json()["items"]


def test_uncached_repo_says_not_cached():
    r = c.get("/repos/someone/else/overview")
    assert r.status_code == 404 and "not cached" in r.json()["detail"]


def test_ask_all_modes_return_valid_envelope():
    for mode in ("why", "history", "still_needed", "dna"):
        body = c.post("/ask", json={"repo": SAMPLE, "item_id": ITEM, "mode": mode}).json()
        assert validate(body) == [], mode


def test_ask_abstains_for_unknown_item():
    body = c.post("/ask", json={"repo": SAMPLE, "item_id": "file:x.py", "mode": "why"}).json()
    assert body["status"] == "insufficient_evidence" and body["answer"] == []


def test_free_requires_question():
    r = c.post("/ask", json={"repo": SAMPLE, "item_id": ITEM, "mode": "free"})
    assert r.status_code == 422


def test_bad_mode_rejected():
    assert c.post("/ask", json={"repo": SAMPLE, "item_id": ITEM, "mode": "nope"}).status_code == 422
