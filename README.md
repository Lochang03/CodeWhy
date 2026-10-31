# CodeWhy

Understand why code exists, and say so honestly when the evidence is not there.

> Other tools tell you what the code says. CodeWhy tells you why it's that way, whether that reason still applies, and when it can't tell, it says so.

HackFront India | PS T1.1 "Why The Code Is Like This" | Team Parallel Minds: Lochan G, Nidhishree U Kulkarni

## What it does

For a cached public repository, CodeWhy answers "why is this file the way it is?" with links to the commits, pull requests and issues behind it. Every link is labelled **verified** (explicit in the source: a PR's merge commit, a reference written in PR text, a git revert message) or **inferred**. Each answer carries a confidence level computed from evidence counts, and when no evidence exists it answers "Insufficient evidence in the repository."

In the web UI you paste a repository, pick a file, and ask one of four questions (the modes of the `/ask` endpoint):

- **Why is it like this?** (`why`): the reason, with the commits, PRs and issues behind it.
- **How did it change?** (`history`): a timeline from the original change to later ones.
- **Is it still needed?** (`still_needed`): checks whether the original reason may no longer apply. It never claims a workaround can be removed.
- **Code DNA** (`dna`): origin, key decisions and files that change together.

Labels used throughout: **verified**, **inferred**, **heuristic**, **unknown**. The UI shows a "Synthetic sample data" banner only for the synthetic sample repository, never for real repositories.

## Demo data

- GenericMappingTools/pygmt: 150 commits, 80 pull requests and 80 issues (most recent items, fetched 2026-10-26).
- Items fetched by number: commit 8859ca3, PR #3367, issue #3205, and the upstream PR GenericMappingTools/gmt#8461.
- The demo case (the UnicodeDecodeError workaround in `pygmt/clib/session.py`) was found by manual research and fetched by number. The engine did not discover it.
- `sample/synthetic` is a synthetic repository used only for UI development. It is always labelled as synthetic.

## Verified on real data

- `why` for `pygmt/clib/session.py`: commit 8859ca3 -> PR #3367 -> issue #3205 -> upstream GMT PR #8461. All four links are labelled verified, confidence is high, and each link was opened by hand and matched.
- `still_needed` for the same file: raises no drift alert and states that an upstream fix does not show the workaround is unnecessary. Whether the original conditions still apply is reported as unknown.
- `history` for `CITATION.cff`: change #4957 and its revert #4958 appear in order as verified commits.
- A file with one commit and no linked PR (`.readthedocs.yaml`) returns the commit and states that the reason is not recorded.
- An item with no history returns "Insufficient evidence in the repository", empty evidence and confidence "none".
- 52 automated tests pass.

## How it works

GitHub REST API -> cached JSON in `data/raw/` -> in-memory graph (commit-to-PR links, cross-repo references, file renames, reverts) -> FastAPI (`/repos`, `/repos/{owner}/{repo}/overview`, `/repos/{owner}/{repo}/items`, `POST /ask`) -> web UI in `ui/`.

Answers are assembled from graph facts by rule-based code, and every sentence cites evidence ids. No language model is called, and nothing is predicted ("Based on repo history only, not a prediction."). Neo4j is not used; the graph is built in memory from the cached JSON.

## Run it

Backend:
```
python -m venv .venv
.venv\Scripts\activate          (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m pytest
uvicorn api.main:app --port 8000
```
On Windows, if `uvicorn` is not found, use `py -m uvicorn api.main:app --port 8000`.

UI:
1. Keep the API running on port 8000.
2. In VS Code, right-click `ui/index.html` and choose "Open with Live Server" (extension by Ritwick Dey). Double-clicking the file does not work.
3. Type `GenericMappingTools/pygmt` (or click it under "Examples") and press Analyze.
4. Pick `pygmt/clib/session.py` and try the four tabs.

API docs: http://localhost:8000/docs
Test item: repo `GenericMappingTools/pygmt`, item id `file:pygmt/clib/session.py`.

The demo runs from the committed cache and needs no token. To fetch another repository, create a GitHub token, put it in `.env` (see `.env.example`) and run `python -m ingest.fetch_repo owner/repo`.

## Limitations

- Bounded slice: only the most recent items of a repository are ingested. Only cached repositories can be queried; there is no live "analyze any URL". Counts cover only the fetched slice.
- Not every commit can be linked to a pull request: in the demo data, 57 of 151 commits are tied to one. Files without a link answer with what exists and say the reason is not recorded.
- Whether a workaround is still present in the current code is not checked, and design documents, wikis and chat are not ingested.
-- Drift detection is a heuristic. It flags an item only when the decision's own text uses stop-gap wording (workaround, temporary, fallback and similar) and a linked upstream pull request or issue was resolved after the decision. An earlier, looser version flagged 15 of 180 items, mostly ordinary fixes that closed their own issues; we reviewed two alerts, found the rule too loose and tightened it. It now raises no alert on the pygmt demo data. It has only been tested on a constructed case, so its precision on real repositories is unknown.
- "Inferred" links (for example, files changed together) are a heuristic, not explicit references.
- Rename detection exists, but the demo slice only contains a swap of two logo files.
- Revert detection is verified on one case (CITATION.cff, a metadata file, not code).
- Files in `data/sample/` and `ui/sample.json` are synthetic and marked as such. They are not findings from a real repository.

## Next steps

Ingest releases and design documents, check whether workarounds are still present in the code, load the graph into Neo4j, and add a real drift case.