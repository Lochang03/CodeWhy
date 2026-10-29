"""Ask-response envelope (schema v2, section 6) + invariant checker.

build_envelope() always returns every key, so the UI never has to guess.
validate() enforces the schema invariants; it is used by the tests and can be
called on any real answer the engine produces.
"""
import copy

INSUFFICIENT = "Insufficient evidence in the repository."
DRIFT_LABEL = "Possibly outdated. Verify."
MODES = {"why", "history", "still_needed", "dna", "free"}
LABELS = {"verified", "inferred", "unknown"}
EVIDENCE_TYPES = {"verified", "inferred"}
LEVELS = {"high", "medium", "low", "none"}
DECISION_STATUS = {"current", "superseded", "possibly_expired"}

TOP_KEYS = [
    "status", "message", "mode", "routed_mode", "item", "answer", "confidence", "evidence",
    "who_to_ask", "decision", "timeline", "drift_alert", "dna", "connected_items",
    "connected_note", "limitations",
]


def compute_confidence(evidence: list) -> dict:
    """Confidence from evidence counts only (invariant 3). Never from an LLM."""
    verified = sum(1 for e in evidence if e["evidence_type"] == "verified")
    inferred = sum(1 for e in evidence if e["evidence_type"] == "inferred")
    sources = len({e["type"] for e in evidence})
    if verified == 0 and inferred == 0:
        level = "none"
    elif verified >= 2 and sources >= 2:
        level = "high"
    elif verified >= 1:
        level = "medium"
    else:
        level = "low"
    return {"level": level,
            "basis": {"verified_links": verified, "inferred_links": inferred, "distinct_sources": sources}}


def build_envelope(mode="why", item=None, **fields) -> dict:
    env = {
        "status": "answered", "message": None, "mode": mode, "routed_mode": None, "item": item,
        "answer": [], "confidence": {"level": "none", "basis": {"verified_links": 0, "inferred_links": 0, "distinct_sources": 0}},
        "evidence": [], "who_to_ask": None, "decision": None, "timeline": [], "drift_alert": None,
        "dna": None, "connected_items": [], "connected_note": None, "limitations": [],
    }
    env.update(fields)
    return env


def insufficient(mode="why", item=None, limitations=None, routed_mode=None) -> dict:
    return build_envelope(mode=mode, item=item, status="insufficient_evidence", message=INSUFFICIENT,
                          routed_mode=routed_mode, limitations=limitations or [])


def _all_evidence_refs(r: dict) -> list:
    refs = []
    for a in r["answer"]:
        refs += a.get("evidence_ids", [])
    for t in r["timeline"]:
        refs += t.get("evidence_ids", [])
    for c in r["connected_items"]:
        refs += c.get("evidence_ids", [])
    if r["who_to_ask"]:
        refs += r["who_to_ask"].get("evidence_ids", [])
    d = r["drift_alert"]
    if d:
        refs += d.get("original_reason_evidence", []) + d.get("later_change_evidence", [])
    if r["dna"]:
        refs += r["dna"]["origin"].get("evidence_ids", [])
        for k in r["dna"]["key_decisions"]:
            refs += k.get("evidence_ids", [])
    return refs


def validate(resp: dict) -> list:
    """Return a list of problems (empty list = valid)."""
    p = []
    missing = [k for k in TOP_KEYS if k not in resp]
    if missing:
        return [f"missing keys: {missing}"]
    if resp["mode"] not in MODES:
        p.append(f"bad mode {resp['mode']}")
    ids = {e["id"] for e in resp["evidence"]}
    if len(ids) != len(resp["evidence"]):
        p.append("duplicate evidence ids")
    for e in resp["evidence"]:
        if e["evidence_type"] not in EVIDENCE_TYPES:
            p.append(f"evidence {e['id']} has bad evidence_type")
        if not e.get("url", "").startswith("http"):
            p.append(f"evidence {e['id']} has no url")
    for ref in _all_evidence_refs(resp):  # invariant 1
        if ref not in ids:
            p.append(f"evidence id {ref} not in evidence[]")
    for a in resp["answer"]:
        if a["label"] not in LABELS:
            p.append("answer label invalid")
        if a["label"] != "unknown" and not a["evidence_ids"]:
            p.append("verified/inferred sentence without evidence")
    if resp["status"] == "insufficient_evidence":  # invariant 2
        if resp["answer"] != [] or resp["confidence"]["level"] != "none" or resp["message"] != INSUFFICIENT:
            p.append("insufficient_evidence must have empty answer, level none, exact message")
    elif resp["status"] == "answered":
        if resp["confidence"] != compute_confidence(resp["evidence"]):  # invariant 3
            p.append("confidence does not match evidence counts")
    else:
        p.append("bad status")
    if resp["confidence"]["level"] not in LEVELS:
        p.append("bad confidence level")
    d = resp["drift_alert"]  # invariant 4
    if d is not None:
        if resp["mode"] != "still_needed" and resp["routed_mode"] != "still_needed":
            p.append("drift_alert only allowed for still_needed")
        if d["label"] != DRIFT_LABEL or d["evidence_type"] != "heuristic":
            p.append("drift_alert wording/type wrong")
        if not d["original_reason_evidence"] or not d["later_change_evidence"]:
            p.append("drift_alert needs both original reason and later change")
        if not d["needs_human_verification"]:
            p.append("drift_alert needs needs_human_verification")
    dec = resp["decision"]  # invariant 5
    if dec and dec["status"] == "superseded":
        if not dec.get("superseded_by"):
            p.append("superseded decision needs superseded_by")
        if not any(t["event"] == "supersession" for t in resp["timeline"]):
            p.append("superseded decision needs a supersession timeline entry")
    return p


def clone(x):
    return copy.deepcopy(x)
