# CodeWhy graph + API schema (agree on this BEFORE coding against it)

## Node types
| Node | Key properties |
|---|---|
| File | path, first_seen, last_changed |
| Module | path (directory/package) |
| Function / ConfigKey | name, file_path (added later if time allows) |
| Commit | sha, message, date, url |
| PullRequest | number, title, body, state, merged_at, url |
| Issue | number, title, body, state, closed_at, labels, url |
| Decision | id, summary, date, status (`current` / `superseded` / `possibly_expired`) |
| Incident | issue number, label (bug / regression / outage) |
| Person | login, last_active |

## Edge types
`MODIFIED` (Commit->File), `PART_OF` (Commit->PullRequest), `CLOSES` (PR->Issue),
`REFERENCES` (Commit/PR->Issue), `AUTHORED` (Person->Commit/PR/Issue), `RENAMED_FROM` (File->File),
`REVERTS` (Commit->Commit), `SUPERSEDES` (Decision->Decision), `DECIDED_IN` (Decision->PR/Commit),
`MOTIVATED_BY` (Decision->Issue/Incident).

Every edge has: `evidence_type` = `verified` | `inferred`, `source_url`, `date`.
- verified = explicit in the source (closing keyword, PR/commit link, revert commit, file rename).
- inferred = our heuristic (text similarity, same lines touched later). Always labelled in the UI.

## API answer shape (see data/sample/*.json)
status: `answered` | `insufficient_evidence`
confidence.level: `high` | `medium` | `low` | `none`; computed from evidence counts, never from the LLM.
Every sentence in `answer` cites evidence ids like `[ev1]`; each id exists in `evidence[]`.
decision.status: `current` | `superseded` | `possibly_expired`.
drift_alert: null or {label, evidence_type: "heuristic", original_reason_evidence, later_change_evidence, needs_verification}.
UI must show verified vs inferred vs heuristic differently, and show "Insufficient evidence in the repository" when status is `insufficient_evidence`.
