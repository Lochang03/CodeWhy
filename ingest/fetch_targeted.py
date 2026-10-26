"""Fetch SPECIFIC issues / PRs / commits by number or sha (not just the most recent slice).

Usage (project root, venv active):
    python -m ingest.fetch_targeted owner/repo --issues 3205 --pulls 3367 --commits 8859ca368

Output: data/raw/<owner>__<repo>/targeted.json
Failures (wrong number, issue-vs-PR mix-up, bad sha) are recorded under "errors", never hidden.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ingest.fetch_repo import parse_repo, save, slim_comment, slim_user
from ingest.github_client import GitHubClient, GitHubError


def slim_event(e):
    return {
        "event": e.get("event"),
        "created_at": e.get("created_at"),
        "actor": (e.get("actor") or {}).get("login"),
        "commit_id": e.get("commit_id"),
        "commit_url": e.get("commit_url"),
        "label": (e.get("label") or {}).get("name"),
    }


def fetch_issue(client, repo, n):
    i = client.get(f"/repos/{repo}/issues/{n}").json()
    if "pull_request" in i:
        raise GitHubError(f"#{n} is a pull request, not an issue (use --pulls {n})")
    comments = [slim_comment(c) for c in client.paginate(f"/repos/{repo}/issues/{n}/comments")]
    events = [slim_event(e) for e in client.paginate(f"/repos/{repo}/issues/{n}/events")]
    return {
        "number": n, "title": i["title"], "body": i.get("body") or "", "state": i["state"],
        "created_at": i["created_at"], "closed_at": i.get("closed_at"), "user": slim_user(i.get("user")),
        "url": i["html_url"], "labels": [l["name"] for l in i.get("labels", [])],
        "comments": comments,
        "events": events,
    }


def fetch_pull(client, repo, n):
    p = client.get(f"/repos/{repo}/pulls/{n}").json()
    comments = [slim_comment(c) for c in client.paginate(f"/repos/{repo}/issues/{n}/comments")]
    comments += [slim_comment(c) for c in client.paginate(f"/repos/{repo}/pulls/{n}/comments")]
    files = [
        {"filename": f["filename"], "status": f["status"], "previous_filename": f.get("previous_filename")}
        for f in client.paginate(f"/repos/{repo}/pulls/{n}/files")
    ]
    return {
        "number": n, "title": p["title"], "body": p.get("body") or "", "state": p["state"],
        "merged_at": p.get("merged_at"), "created_at": p["created_at"], "closed_at": p.get("closed_at"),
        "user": slim_user(p.get("user")), "url": p["html_url"], "merge_commit_sha": p.get("merge_commit_sha"),
        "labels": [l["name"] for l in p.get("labels", [])], "comments": comments, "files": files,
    }


def fetch_commit(client, repo, sha):
    c = client.get(f"/repos/{repo}/commits/{sha}").json()
    return {
        "sha": c["sha"], "message": c["commit"]["message"],
        "author_login": (c.get("author") or {}).get("login"), "author_name": c["commit"]["author"]["name"],
        "date": c["commit"]["author"]["date"], "url": c["html_url"],
        "parents": [p["sha"] for p in c.get("parents", [])],
        "files": [
            {"filename": f["filename"], "status": f["status"], "previous_filename": f.get("previous_filename")}
            for f in c.get("files", [])
        ],
    }


def fetch_targeted(client, repo, out_root, issues=(), pulls=(), commits=()):
    out_dir = Path(out_root) / repo.replace("/", "__")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"repo": repo, "fetched_at": datetime.now(timezone.utc).isoformat(),
              "issues": [], "pulls": [], "commits": [], "errors": []}
    for kind, items, fn in (("issues", issues, fetch_issue), ("pulls", pulls, fetch_pull), ("commits", commits, fetch_commit)):
        for ref in items:
            try:
                result[kind].append(fn(client, repo, ref))
                print(f"  ok {kind[:-1]} {ref}", flush=True)
            except GitHubError as e:
                result["errors"].append({"kind": kind[:-1], "ref": str(ref), "error": str(e)})
                print(f"  ERROR {kind[:-1]} {ref}: {e}", flush=True)
    result["api_requests"] = client.requests_made
    save(out_dir / "targeted.json", result)
    print(f"Saved {out_dir / 'targeted.json'}")
    return result


def main(argv=None):
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="owner/repo or GitHub URL")
    ap.add_argument("--issues", type=int, nargs="*", default=[])
    ap.add_argument("--pulls", type=int, nargs="*", default=[])
    ap.add_argument("--commits", nargs="*", default=[], help="commit shas (short ok)")
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args(argv)
    if not (args.issues or args.pulls or args.commits):
        print("ERROR: give at least one of --issues / --pulls / --commits")
        sys.exit(1)
    try:
        repo = parse_repo(args.repo)
        client = GitHubClient()
        if not client.token:
            print("WARNING: no GITHUB_TOKEN set. Unauthenticated limit is only 60 requests/hour.")
        res = fetch_targeted(client, repo, args.out, args.issues, args.pulls, args.commits)
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in res.items()
                          if k in ("issues", "pulls", "commits", "errors", "api_requests")}, indent=2))
        if res["errors"]:
            print(json.dumps(res["errors"], indent=2))
    except (GitHubError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()