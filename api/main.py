"""Minimal API so the UI can start talking to the backend on day 1.

Run:  uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "data" / "sample"
RAW_DIR = ROOT / "data" / "raw"

app = FastAPI(title="CodeWhy API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/repos")
def list_repos():
    """Repos whose history has been downloaded to data/raw/ (with the bounds used)."""
    repos = []
    if RAW_DIR.exists():
        for meta in RAW_DIR.glob("*/meta.json"):
            repos.append(json.loads(meta.read_text(encoding="utf-8")))
    return {"repos": repos}


@app.get("/mock/answer/{kind}")
def mock_answer(kind: str):
    """MOCK responses (not real findings) so the UI can be built before the backend is ready.
    kind: answered | abstain | drift
    """
    names = {"answered": "answer_answered.json", "abstain": "answer_abstain.json", "drift": "answer_drift.json"}
    if kind not in names:
        raise HTTPException(404, f"kind must be one of {list(names)}")
    return json.loads((SAMPLE_DIR / names[kind]).read_text(encoding="utf-8"))
