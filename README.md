# CodeWhy

Understand why code exists, and detect when its original reasoning may no longer hold.
HackFront India, PS T1.1 "Why The Code Is Like This". Team Parallel Minds.

> Other tools tell you what the code says. CodeWhy tells you why it's that way, whether that reason still applies, and when it can't tell, it says so.

## What it does
Paste a GitHub repo, pick a file, and ask one of four questions:
- **Why is it like this?** The reason, with links to the commits, PRs and issues behind it.
- **How did it change?** A timeline of the original change, discussion and later changes.
- **Is it still needed?** A drift check that flags "Possibly outdated. Verify."
- **Code DNA:** origin, key decisions and files that change together.

Every statement is labeled **verified** (explicit in the source), **inferred** (our heuristic), **unknown**, or **heuristic**. When there is no evidence, CodeWhy says exactly: "Insufficient evidence in the repository."

Demo repo: `GenericMappingTools/pygmt` (150 commits, 80 PRs, 80 issues, fetched 2026-10-26), plus `GenericMappingTools/gmt` for an upstream PR. A synthetic sample (`sample/synthetic`) is also included and is always labeled as synthetic.

## Setup (backend)
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m pytest              # should pass
uvicorn api.main:app --reload --port 8000   # http://localhost:8000/docs
```
The demo data is already in `data/raw/`, so no GitHub token is needed to run the demo. A token is only needed to fetch new repos.

## Run the UI
1. Keep the API running on port 8000.
2. In VS Code, right-click `ui/index.html` and choose "Open with Live Server" (extension by Ritwick Dey). Double-clicking the file does not work.
3. Type `GenericMappingTools/pygmt` and click Analyze.
4. Pick a file such as `pygmt/clib/session.py` and try the four buttons.

## Download a repo's history (bounded slice)
```bash
python -m ingest.fetch_repo owner/repo --max-commits 150 --max-prs 80 --max-issues 80
```

## Limitations (kept honest)
- Only a bounded, most-recent slice of a repo is ingested (see `meta.json` for exact limits), not the full history.
- Works only on repositories fetched in advance. Others show "Not cached".
- Design docs, wikis and chat are not ingested.
- File contents are not ingested. Whether a workaround is still present in the code is NOT checked by the tool; we verified it by hand for the demo case.
- "Possibly outdated. Verify." is a heuristic, not a verified fact. An upstream fix alone does not prove a workaround is unnecessary.
- "Inferred" links (for example, files changed together) are a heuristic, not explicit references.
- Answers are built only from facts in the graph, each citing evidence IDs. No LLM, no predictions.
- Counts and answers cover only the fetched slice of history.
- `data/sample/` and `ui/sample.json` contain synthetic data and are labeled as such.