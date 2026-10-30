"""CodeWhy API (schema v2, see docs/graph-schema.md).

Run:  uvicorn api.main:app --reload --port 8000     Docs: http://localhost:8000/docs
Cached repos are answered by graph/engine.py (no LLM). The synthetic repo 'sample/synthetic' is served from data/sample
(every such response carries "_mock": true). An uncached repo returns 404 "not cached".
"""
import json
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph import engine
from qa import mock_engine

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

app = FastAPI(title="CodeWhy API")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",  # any local dev server port
    allow_methods=["*"],
    allow_headers=["*"],
)


def cached_repos():
    repos = []
    if RAW_DIR.exists():
        for meta in sorted(RAW_DIR.glob("*/meta.json")):
            repos.append(json.loads(meta.read_text(encoding="utf-8")))
    return repos


_GRAPHS = {}


def _graph(repo: str):
    if repo not in _GRAPHS:
        _GRAPHS[repo] = engine.load_graph(repo, RAW_DIR)
    return _GRAPHS[repo]


def _check_repo(repo: str):
    """'mock' for the synthetic sample, 'real' for a cached repo, 404 otherwise."""
    if repo == mock_engine.SAMPLE_REPO:
        return "mock"
    if any(r["repo"] == repo for r in cached_repos()):
        return "real"
    raise HTTPException(404, f"{repo} is not cached. The demo only works on cached repos.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/repos")
def list_repos():
    sample = {"repo": mock_engine.SAMPLE_REPO, "synthetic": True,
              "note": "SYNTHETIC SAMPLE DATA: not a real repository"}
    return {"repos": cached_repos() + [sample]}


@app.get("/repos/{owner}/{repo}/overview")
def overview(owner: str, repo: str):
    name = f"{owner}/{repo}"
    if _check_repo(name) == "mock":
        return mock_engine.overview()
    return engine.overview(_graph(name))


@app.get("/repos/{owner}/{repo}/items")
def items(owner: str, repo: str, q: str = ""):
    name = f"{owner}/{repo}"
    if _check_repo(name) == "mock":
        return mock_engine.items(q)
    return engine.items(_graph(name), q)


class AskRequest(BaseModel):
    repo: str
    item_id: str
    mode: Literal["why", "history", "still_needed", "dna", "free"]
    question: Optional[str] = None


@app.post("/ask")
def ask(req: AskRequest):
    if req.mode == "free" and not (req.question or "").strip():
        raise HTTPException(422, "question is required when mode = free")
    if _check_repo(req.repo) == "mock":
        return mock_engine.ask(req.item_id, req.mode, req.question)
    return engine.ask(_graph(req.repo), req.item_id, req.mode, req.question)
