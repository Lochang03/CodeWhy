"""Serves the SYNTHETIC samples through the real v2 contract, so the UI can be built now.
Replaced by the real graph engine later; the API layer does not change."""
import json
from pathlib import Path

from qa.envelope import clone, insufficient

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
SAMPLE_REPO = "sample/synthetic"
SAMPLE_ITEM = "file:src/net/retry.py"
_FILES = {"why": "ask_why", "history": "ask_history", "still_needed": "ask_still_needed", "dna": "ask_dna"}


def _load(name):
    return json.loads((SAMPLE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def overview():
    return _load("overview")


def items(q=""):
    data = _load("items")
    if q:
        data["items"] = [i for i in data["items"] if q.lower() in i["label"].lower()]
    return data


def route_free(question: str):
    """No-LLM routing (schema section 7). Returns a mode or None."""
    s = question.lower()
    if "still" in s and ("there" in s or "needed" in s or "need" in s):
        return "still_needed"
    if "why" in s:
        return "why"
    if "change" in s or "history" in s:
        return "history"
    return None


def ask(item_id: str, mode: str, question=None) -> dict:
    routed = None
    if mode == "free":
        routed = route_free(question or "")
        if routed is None or item_id != SAMPLE_ITEM:
            r = insufficient(mode="free", item=None, routed_mode=routed, limitations=["Bounded slice of history"])
            r["_mock"] = True
            return r
    effective = routed or mode
    if item_id != SAMPLE_ITEM or effective not in _FILES:
        r = insufficient(mode=mode, item=None, routed_mode=routed, limitations=["Bounded slice of history"])
        r["_mock"] = True
        return r
    r = clone(_load(_FILES[effective]))
    r["mode"], r["routed_mode"] = mode, routed
    return r
