# CodeWhy graph + API schema (PROPOSED v2, agree before coding against it)

Status: proposal from Lochan's side, to be confirmed by Nii. Replaces docs/graph-schema.md.

## 1. Graph (unchanged from v1)

### Node types
| Node | Key properties |
|---|---|
| File | path, first_seen, last_changed |
| Module | path (directory/package) |
| Function / ConfigKey | name, file_path (only if time allows) |
| Commit | sha, message, date, url |
| PullRequest | number, title, body, state, merged_at, url |
| Issue | number, title, body, state, closed_at, labels, url |
| Decision | id, summary, date, status (`current` / `superseded` / `possibly_expired`) |
| Incident | issue number, label (bug / regression / outage) |
| Person | login, last_active |

### Edge types
`MODIFIED` (Commit->File), `PART_OF` (Commit->PullRequest), `CLOSES` (PR->Issue),
`REFERENCES` (Commit/PR->Issue), `AUTHORED` (Person->Commit/PR/Issue), `RENAMED_FROM` (File->File),
`REVERTS` (Commit->Commit), `SUPERSEDES` (Decision->Decision), `DECIDED_IN` (Decision->PR/Commit),
`MOTIVATED_BY` (Decision->Issue/Incident).

Every edge has `evidence_type`, `source_url`, `date`.
- `verified`: explicit in the source (closing keyword, PR/commit link, revert commit, file rename).
- `inferred`: our heuristic (text similarity, same lines touched later). Always labelled in the UI.
- `heuristic`: used only by the drift detector. Always shown with "Possibly outdated. Verify."

Claim labels shown to the user: `verified` | `inferred` | `unknown`.

## 2. Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /repos` | Cached repos available (exists today). Demo = cached repos only; "Analyze" on an uncached URL must say it is not cached. |
| `GET /repos/{owner}/{repo}/overview` | Counts for the overview screen |
| `GET /repos/{owner}/{repo}/items?q=` | List/search of files and decisions to pick from |
| `POST /ask` | The four buttons AND the question box, one response shape |

## 3. Overview

```json
{
  "repo": "owner/repo",
  "ingested": {"commits": 150, "pulls": 80, "issues": 80, "fetched_at": "ISO date",
               "note": "Bounded slice, not the full history."},
  "counts": {
    "total_items": 0,
    "explained": 0,
    "unknown": 0,
    "unchanged_since_decision": 0,
    "changed_since_decision": 0,
    "superseded": 0,
    "possibly_outdated": 0
  }
}
```

Rules (so the numbers are honest and testable):
- `explained + unknown = total_items`. `unknown` = items with no evidence; never hide it.
- `unchanged_since_decision + changed_since_decision + superseded <= explained` (disjoint buckets).
  `changed` means later commits touched the file (verified from commit file lists).
  `superseded` only when a SUPERSEDES edge exists (verified revert, or flagged inferred).
- `possibly_outdated` is a flag that can overlap the other buckets, not a partition. Expect it to be small (0 to a few). We do not loosen the detector to make it bigger.
- The UI must show the `ingested` slice next to the counts.

## 4. Items list

```json
{"items": [{"id": "file:src/net/retry.py", "kind": "file", "label": "src/net/retry.py",
            "evidence_count": 3, "state": "explained"}]}
```
`state`: `explained` | `unknown`.

## 5. Ask: request

```json
{"repo": "owner/repo", "item_id": "file:src/net/retry.py",
 "mode": "why | history | still_needed | dna | free",
 "question": "only required when mode = free"}
```

| Button | mode |
|---|---|
| Why is it like this? | `why` |
| How did it change? | `history` |
| Is it still needed? | `still_needed` |
| Code DNA | `dna` |
| Question box | `free` (backend routes it, see section 7) |

## 6. Ask: response (same envelope for every mode)

All keys are always present. Fields that do not apply to the mode are `null` or `[]`.

```json
{
  "status": "answered | insufficient_evidence",
  "message": "Insufficient evidence in the repository.",
  "mode": "why",
  "routed_mode": null,
  "item": {"id": "file:src/net/retry.py", "kind": "file", "label": "src/net/retry.py"},

  "answer": [
    {"text": "One sentence.", "evidence_ids": ["ev1"], "label": "verified | inferred | unknown"}
  ],

  "confidence": {
    "level": "high | medium | low | none",
    "basis": {"verified_links": 2, "inferred_links": 1, "distinct_sources": 3}
  },

  "evidence": [
    {"id": "ev1", "type": "commit | pull_request | issue | comment",
     "title": "", "snippet": "", "url": "https://...", "date": "ISO date",
     "author": "login", "evidence_type": "verified | inferred"}
  ],

  "who_to_ask": {"login": "", "reason": "author of ev1", "evidence_ids": ["ev1"],
                 "last_active": "ISO date", "still_active": true},

  "decision": {"summary": "", "date": "", "status": "current | superseded | possibly_expired",
               "superseded_by": null},

  "timeline": [
    {"date": "", "event": "original_change | discussion | later_change | revert | supersession",
     "text": "", "evidence_ids": ["ev1"], "evidence_type": "verified | inferred"}
  ],

  "drift_alert": {
    "label": "Possibly outdated. Verify.",
    "evidence_type": "heuristic",
    "original_reason_evidence": ["ev1"],
    "later_change_evidence": ["ev4"],
    "workaround_still_in_code": {"checked": true, "path": "", "note": ""},
    "needs_human_verification": ["What a human must still check"]
  },

  "dna": {
    "origin": {"text": "", "evidence_ids": ["ev1"]},
    "key_decisions": [{"summary": "", "date": "", "evidence_ids": ["ev1"]}],
    "changed_together": [{"path": "", "times": 0, "evidence_type": "inferred"}]
  },

  "connected_items": [
    {"id": "issue:123", "kind": "issue", "label": "", "edge_type": "MOTIVATED_BY",
     "evidence_type": "verified", "evidence_ids": ["ev2"]}
  ],
  "connected_note": "Based on repo history only, not a prediction.",

  "limitations": ["Bounded slice of history", "Design docs not ingested"]
}
```

Invariants (these become automated tests):
1. Every id in `evidence_ids` exists in `evidence[]`.
2. `status = insufficient_evidence` means `answer = []`, `confidence.level = none`, and `message` is exactly "Insufficient evidence in the repository."
3. `confidence.level` is computed from `confidence.basis` (evidence counts/strength), never from an LLM.
4. `drift_alert` is non-null only for `still_needed`, and always carries both the original reason and the later change. It is never worded as "definitely outdated".
5. A `superseded` decision must also return the later decision in `decision.superseded_by` and in `timeline`.
6. UI must style `verified`, `inferred`, `heuristic` differently.

Which fields each mode fills:
| mode | fields used |
|---|---|
| why | answer, evidence, confidence, who_to_ask, decision, connected_items |
| history | timeline, decision, evidence |
| still_needed | answer, drift_alert (or null), evidence, decision |
| dna | dna, evidence, connected_items |
| free | whichever applies to `routed_mode` |

## 7. Honest limits of the backend for this flow

- **Analyze on any URL**: not possible live in the demo (token + rate limits + time). Cached repos only; the UI says so.
- **Free questions**: no LLM required. The backend matches the question to a known file/issue/PR number/name and routes to a mode. "Why is it still there?" -> `still_needed`. "What is this code?" is not a history question; it gets `insufficient_evidence` unless the item has an origin in the graph. No match -> `insufficient_evidence`.
- **Code DNA "dependencies"**: we do not parse imports. We offer `changed_together` (files committed together), labelled inferred. Real import dependencies only if time allows.
- **Supersession**: verified only for reverts or explicit references. Anything else is `inferred` and shown that way.
- **Who to ask / still active**: based on authors inside the ingested slice only.
- **Everything is limited to the ingested slice** (see `ingested` in the overview).
- `data/sample/` stays synthetic and must be labelled as such in the UI.
