"""Regenerates data/sample/*.json (SYNTHETIC, schema v2). Run: python -m qa.make_samples
All content is invented for UI development. URLs are example.com on purpose."""
import json
from pathlib import Path

from qa.envelope import DRIFT_LABEL, build_envelope, compute_confidence, insufficient, validate

OUT = Path(__file__).resolve().parent.parent / "data" / "sample"
REPO = "sample/synthetic"
SYN = "SYNTHETIC SAMPLE DATA: not a real repository finding"
ITEM = {"id": "file:src/net/retry.py", "kind": "file", "label": "src/net/retry.py"}


def ev(i, typ, title, snippet, date, author, et="verified"):
    return {"id": f"ev{i}", "type": typ, "title": title, "snippet": snippet,
            "url": f"https://example.com/{typ}/{i}", "date": date, "author": author, "evidence_type": et}


E1 = ev(1, "commit", "Limit retries to 3", "Cap retries at 3: upstream gateway drops bursts.", "2021-06-10", "dev-a")
E2 = ev(2, "issue", "Gateway drops bursty clients", "Gateway returns 502 under bursts.", "2021-06-01", "dev-b")
E3 = ev(3, "pull_request", "Add retry cap", "Fixes #2. Caps retries to avoid hammering the gateway.", "2021-06-10", "dev-a")
E4 = ev(4, "issue", "Gateway burst handling fixed (closed)", "Gateway now queues bursts.", "2022-11-20", "dev-c")
E5 = ev(5, "commit", "Revert retry cap to 3, use backoff", "Replaces fixed cap with exponential backoff.", "2023-02-02", "dev-c")
E6 = ev(6, "commit", "Touch retry.py with transport.py", "Changed together.", "2022-01-05", "dev-a", "inferred")


def finish(env):
    env["confidence"] = compute_confidence(env["evidence"]) if env["status"] == "answered" else env["confidence"]
    env["_mock"] = True
    env["limitations"] = [SYN] + env["limitations"]
    return env


def why():
    ev_ = [E1, E2, E3]
    return finish(build_envelope(
        mode="why", item=ITEM,
        answer=[
            {"text": "Retries were capped at 3 because the upstream gateway dropped bursty clients.", "evidence_ids": ["ev1", "ev2"], "label": "verified"},
            {"text": "The cap was introduced in the pull request that fixed the gateway issue.", "evidence_ids": ["ev3"], "label": "verified"},
        ],
        evidence=ev_,
        who_to_ask={"login": "dev-a", "reason": "author of ev1", "evidence_ids": ["ev1"], "last_active": "2023-05-01", "still_active": False},
        decision={"summary": "Cap retries at 3", "date": "2021-06-10", "status": "current", "superseded_by": None},
        connected_items=[{"id": "issue:2", "kind": "issue", "label": "Gateway drops bursty clients", "edge_type": "MOTIVATED_BY", "evidence_type": "verified", "evidence_ids": ["ev2"]}],
        connected_note="Based on repo history only, not a prediction.",
        limitations=["Bounded slice of history", "Design docs not ingested"]))


def history():
    ev_ = [E2, E1, E4, E5]
    return finish(build_envelope(
        mode="history", item=ITEM, evidence=ev_,
        decision={"summary": "Cap retries at 3", "date": "2021-06-10", "status": "superseded",
                  "superseded_by": {"summary": "Exponential backoff replaces fixed cap", "date": "2023-02-02", "evidence_ids": ["ev5"]}},
        timeline=[
            {"date": "2021-06-01", "event": "discussion", "text": "Issue reports gateway drops bursts.", "evidence_ids": ["ev2"], "evidence_type": "verified"},
            {"date": "2021-06-10", "event": "original_change", "text": "Retries capped at 3.", "evidence_ids": ["ev1"], "evidence_type": "verified"},
            {"date": "2022-11-20", "event": "later_change", "text": "Gateway issue closed as fixed.", "evidence_ids": ["ev4"], "evidence_type": "verified"},
            {"date": "2023-02-02", "event": "supersession", "text": "Fixed cap replaced by backoff.", "evidence_ids": ["ev5"], "evidence_type": "verified"},
        ],
        limitations=["Bounded slice of history"]))


def still_needed():
    ev_ = [E1, E2, E4]
    return finish(build_envelope(
        mode="still_needed", item=ITEM,
        answer=[
            {"text": "The cap was added for a gateway limitation (ev2, ev1).", "evidence_ids": ["ev1", "ev2"], "label": "verified"},
            {"text": "A later issue says the gateway now queues bursts; whether the cap is now unnecessary is not verified.", "evidence_ids": ["ev4"], "label": "inferred"},
        ],
        evidence=ev_,
        decision={"summary": "Cap retries at 3", "date": "2021-06-10", "status": "possibly_expired", "superseded_by": None},
        drift_alert={"label": DRIFT_LABEL, "evidence_type": "heuristic",
                     "original_reason_evidence": ["ev1", "ev2"], "later_change_evidence": ["ev4"],
                     "workaround_still_in_code": {"checked": True, "path": "src/net/retry.py", "note": "MAX_RETRIES = 3 still present"},
                     "needs_human_verification": ["Confirm the deployed gateway version includes the fix", "Test removing the cap in staging"]},
        limitations=["Bounded slice of history"]))


def dna():
    ev_ = [E2, E1, E6]
    return finish(build_envelope(
        mode="dna", item=ITEM, evidence=ev_,
        dna={"origin": {"text": "Created to cap retries against a flaky gateway.", "evidence_ids": ["ev1"]},
             "key_decisions": [{"summary": "Cap retries at 3", "date": "2021-06-10", "evidence_ids": ["ev1"]}],
             "changed_together": [{"path": "src/net/transport.py", "times": 4, "evidence_type": "inferred"}]},
        connected_items=[{"id": "issue:2", "kind": "issue", "label": "Gateway drops bursty clients", "edge_type": "MOTIVATED_BY", "evidence_type": "verified", "evidence_ids": ["ev2"]}],
        connected_note="Based on repo history only, not a prediction.",
        limitations=["Imports not parsed: changed_together is inferred from commits"]))


def abstain():
    e = insufficient(mode="why", item={"id": "file:src/util/misc.py", "kind": "file", "label": "src/util/misc.py"},
                     limitations=["Bounded slice of history"])
    e["_mock"] = True
    e["limitations"] = [SYN] + e["limitations"]
    return e


OVERVIEW = {"repo": REPO,
            "ingested": {"commits": 150, "pulls": 80, "issues": 80, "fetched_at": "2026-10-23T00:00:00Z",
                         "note": "Bounded slice, not the full history. " + SYN},
            "counts": {"total_items": 10, "explained": 6, "unknown": 4, "unchanged_since_decision": 2,
                       "changed_since_decision": 3, "superseded": 1, "possibly_outdated": 1},
            "_mock": True}
ITEMS = {"items": [
    {"id": "file:src/net/retry.py", "kind": "file", "label": "src/net/retry.py", "evidence_count": 3, "state": "explained"},
    {"id": "file:src/util/misc.py", "kind": "file", "label": "src/util/misc.py", "evidence_count": 0, "state": "unknown"}],
    "_mock": True}


def main():
    files = {"ask_why": why(), "ask_history": history(), "ask_still_needed": still_needed(),
             "ask_dna": dna(), "ask_abstain": abstain(), "overview": OVERVIEW, "items": ITEMS}
    for name, body in files.items():
        if name.startswith("ask_"):
            problems = validate(body)
            assert not problems, (name, problems)
        (OUT / f"{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", ", ".join(files))


if __name__ == "__main__":
    main()
