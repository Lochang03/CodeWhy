from fastapi.testclient import TestClient

from api.main import app

c = TestClient(app)


def test_health():
    assert c.get("/health").json() == {"status": "ok"}


def test_mock_answers_exist_and_are_marked_mock():
    for kind in ("answered", "abstain", "drift"):
        body = c.get(f"/mock/answer/{kind}").json()
        assert body["_mock"] is True


def test_abstain_mock_has_no_evidence():
    body = c.get("/mock/answer/abstain").json()
    assert body["status"] == "insufficient_evidence" and body["evidence"] == []


def test_answered_mock_citations_exist_in_evidence():
    import re
    body = c.get("/mock/answer/answered").json()
    cited = set(re.findall(r"\[(ev\d+)\]", body["answer"]))
    assert cited and cited <= {e["id"] for e in body["evidence"]}


def test_unknown_kind_404():
    assert c.get("/mock/answer/nope").status_code == 404
