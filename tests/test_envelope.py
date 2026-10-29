import json
from pathlib import Path

import pytest

from qa import mock_engine
from qa.envelope import INSUFFICIENT, build_envelope, compute_confidence, insufficient, validate

SAMPLES = sorted((Path(__file__).resolve().parent.parent / "data" / "sample").glob("ask_*.json"))


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_every_sample_is_valid_and_marked_synthetic(path):
    body = json.loads(path.read_text(encoding="utf-8"))
    assert validate(body) == []
    assert body["_mock"] is True


def test_abstain_shape():
    r = insufficient()
    assert r["answer"] == [] and r["confidence"]["level"] == "none" and r["message"] == INSUFFICIENT
    assert validate(r) == []


def test_dangling_evidence_id_is_caught():
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "why")
    r["answer"][0]["evidence_ids"] = ["ev99"]
    assert any("ev99" in p for p in validate(r))


def test_confidence_is_computed_not_asserted():
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "why")
    r["confidence"]["level"] = "high" if r["confidence"]["level"] != "high" else "low"
    assert any("confidence" in p for p in validate(r))


def test_drift_must_carry_both_sides_and_exact_wording():
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "still_needed")
    assert validate(r) == []
    r["drift_alert"]["later_change_evidence"] = []
    assert validate(r)
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "still_needed")
    r["drift_alert"]["label"] = "Definitely outdated"
    assert validate(r)


def test_drift_only_for_still_needed():
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "still_needed")
    r["mode"] = "why"
    assert any("still_needed" in p for p in validate(r))


def test_superseded_needs_later_decision_and_timeline():
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "history")
    assert validate(r) == []
    r["decision"]["superseded_by"] = None
    assert validate(r)


def test_free_question_routing_has_no_llm():
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "free", "Why is it still there?")
    assert r["mode"] == "free" and r["routed_mode"] == "still_needed" and r["drift_alert"]
    r = mock_engine.ask(mock_engine.SAMPLE_ITEM, "free", "What is this code?")
    assert r["status"] == "insufficient_evidence"


def test_unknown_item_abstains():
    assert mock_engine.ask("file:nope.py", "why")["status"] == "insufficient_evidence"


def test_compute_confidence_levels():
    assert compute_confidence([])["level"] == "none"
    one = [{"evidence_type": "inferred", "type": "commit"}]
    assert compute_confidence(one)["level"] == "low"
