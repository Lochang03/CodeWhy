# CodeWhy

Understand why code exists, and detect when its original reasoning may no longer hold.
HackFront India, PS T1.1 "Why The Code Is Like This". Team Parallel Minds.

> Status: early scaffold. Only the GitHub fetcher, a mock API and tests exist so far.
> Mock data in `data/sample/` is fake and exists only so the UI can be built early.

## Setup (backend)
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env        # then put your GITHUB_TOKEN in .env
python -m pytest              # should pass
uvicorn api.main:app --reload --port 8000   # http://localhost:8000/docs
```

## Download a repo's history (bounded slice)
```bash
python -m ingest.fetch_repo owner/repo --max-commits 150 --max-prs 80 --max-issues 80
```

## Limitations (kept honest)
- Only a bounded, most-recent slice of a repo is ingested (see `meta.json` for exact limits).
