"""Download a bounded slice of a public repo's history and cache it as JSON.

Usage (from project root, venv active):
    python -m ingest.fetch_repo owner/repo --max-commits 150 --max-prs 80 --max-issues 80

Output: data/raw/<owner>__<repo>/{meta,commits,pulls,issues}.json
The slice is bounded ON PURPOSE (rate limits + demo speed). meta.json records the limits
so the README/PPT can state exactly what was ingested.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ingest.github_client import GitHubClient, GitHubError

REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def parse_repo(text: str) -> str:
    """Accepts 'owner/repo' or a github.com URL; returns 'owner/repo'."""
    text = text.strip().rstrip("/")
    text = re.sub(r"^https?://github\.com/", "", text)
    text = re.sub(r"\.git$", "", text)
    if not REPO_RE.match(text):
        raise ValueError(f"Not a valid repo: {text!r} (expected owner/repo)")
    return text


def slim_user(u):
    return {"login": u.get("login"), "url": u.get("html_url")} if u else None


def slim_comment(c):
    return {
        "id": c.get("id"),
        "user": slim_user(c.get("user")),
        "body": c.get("body") or "",
        "created_at": c.get("created_at"),
        "url": c.get("html_url"),
    }


def fetch_commits(client, repo, limit, with_files=True):
    out = []
    for c in client.paginate(f"/repos/{repo}/commits", max_items=limit):
        item = {
            "sha": c["sha"],
            "message": c["commit"]["message"],
            "author_login": (c.get("author") or {}).get("login"),
            "author_name": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
            "url": c["html_url"],
            "parents": [p["sha"] for p in c.get("parents", [])],
            "files": [],
        }
        if with_files:
            detail = client.get(f"/repos/{repo}/commits/{c['sha']}").json()
            item["files"] = [
                {
                    "filename": f["filename"],
                    "status": f["status"],  # added / modified / removed / renamed
                    "previous_filename": f.get("previous_filename"),
                }
                for f in detail.get("files", [])
            ]
        out.append(item)
        if len(out) % 25 == 0:
            print(f"  commits: {len(out)}", flush=True)
    return out


def fetch_pulls(client, repo, limit):
    out = []
    params = {"state": "all", "sort": "updated", "direction": "desc"}
    for p in client.paginate(f"/repos/{repo}/pulls", params, max_items=limit):
        n = p["number"]
        issue_comments = [slim_comment(c) for c in client.paginate(f"/repos/{repo}/issues/{n}/comments")]
        review_comments = [slim_comment(c) for c in client.paginate(f"/repos/{repo}/pulls/{n}/comments")]
        out.append(
            {
                "number": n,
                "title": p["title"],
                "body": p.get("body") or "",
                "state": p["state"],
                "merged_at": p.get("merged_at"),
                "created_at": p["created_at"],
                "closed_at": p.get("closed_at"),
                "user": slim_user(p.get("user")),
                "url": p["html_url"],
                "merge_commit_sha": p.get("merge_commit_sha"),
                "labels": [l["name"] for l in p.get("labels", [])],
                "comments": issue_comments + review_comments,
            }
        )
        if len(out) % 10 == 0:
            print(f"  pulls: {len(out)}", flush=True)
    return out


def fetch_issues(client, repo, limit):
    """The issues endpoint also returns PRs; we skip those (they have a 'pull_request' key)."""
    out = []
    params = {"state": "all", "sort": "updated", "direction": "desc"}
    for i in client.paginate(f"/repos/{repo}/issues", params):
        if "pull_request" in i:
            continue
        n = i["number"]
        comments = [slim_comment(c) for c in client.paginate(f"/repos/{repo}/issues/{n}/comments")]
        out.append(
            {
                "number": n,
                "title": i["title"],
                "body": i.get("body") or "",
                "state": i["state"],
                "created_at": i["created_at"],
                "closed_at": i.get("closed_at"),
                "user": slim_user(i.get("user")),
                "url": i["html_url"],
                "labels": [l["name"] for l in i.get("labels", [])],
                "comments": comments,
            }
        )
        if len(out) % 10 == 0:
            print(f"  issues: {len(out)}", flush=True)
        if len(out) >= limit:
            break
    return out


def save(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_repo(client, repo, out_root, max_commits, max_prs, max_issues, with_files=True):
    out_dir = Path(out_root) / repo.replace("/", "__")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {repo} -> {out_dir}")
    commits = fetch_commits(client, repo, max_commits, with_files)
    save(out_dir / "commits.json", commits)
    pulls = fetch_pulls(client, repo, max_prs)
    save(out_dir / "pulls.json", pulls)
    issues = fetch_issues(client, repo, max_issues)
    save(out_dir / "issues.json", issues)
    meta = {
        "repo": repo,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "limits": {"max_commits": max_commits, "max_prs": max_prs, "max_issues": max_issues},
        "counts": {"commits": len(commits), "pulls": len(pulls), "issues": len(issues)},
        "api_requests": client.requests_made,
        "note": "Bounded slice: most recent items only, not the full history.",
    }
    save(out_dir / "meta.json", meta)
    print(json.dumps(meta, indent=2))
    return out_dir


def main(argv=None):
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="owner/repo or GitHub URL")
    ap.add_argument("--max-commits", type=int, default=150)
    ap.add_argument("--max-prs", type=int, default=80)
    ap.add_argument("--max-issues", type=int, default=80)
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--no-files", action="store_true", help="skip per-commit file lists (much fewer API calls)")
    args = ap.parse_args(argv)
    try:
        repo = parse_repo(args.repo)
        client = GitHubClient()
        if not client.token:
            print("WARNING: no GITHUB_TOKEN set. Unauthenticated limit is only 60 requests/hour.")
        fetch_repo(client, repo, args.out, args.max_commits, args.max_prs, args.max_issues, not args.no_files)
    except (GitHubError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
