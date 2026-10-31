"""CodeWhy graph + answer engine (no LLM). Reads the cached JSON in data/raw and answers in the v2 envelope.

Graph = nodes (files, commits, PRs, issues, external PRs/issues) + typed edges, each labelled verified/inferred.
verified  = explicit in the source: file lists of a commit, a '#N' / URL reference in text, a closing keyword,
            a PR's merge_commit_sha, a 'This reverts commit <sha>' line, previous_filename of a rename.
inferred  = our heuristic (files changed in the same commits).
Nothing here is generated text: every sentence is built from a fact in the graph and cites evidence ids.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from qa.envelope import build_envelope, compute_confidence, insufficient

URL_REF = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(issues|pull)/(\d+)", re.I)
HASH_REF = re.compile(r"(?<![\w/&])#(\d+)\b")
CLOSING = re.compile(r"(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\W{0,3}$", re.I)
REVERT = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.I)
SQUASH = re.compile(r"\(#(\d+)\)\s*$")
BASE_LIMITS = ["Bounded slice of history", "Design docs not ingested",
               "File contents not ingested: whether code is still present is not checked"]


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _day(s):
    return (s or "")[:10]


def _first_line(s):
    return (s or "").strip().split("\n")[0][:160]


def _snip(s, n=240):
    return re.sub(r"\s+", " ", s or "").strip()[:n]


def _parse(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_refs(text, own_repo):
    """-> list of (repo_lower, kind_hint, number, closing). kind_hint: 'issues'/'pull'/None."""
    out = []
    for m in URL_REF.finditer(text or ""):
        out.append((m.group(1).lower(), m.group(2).lower(), int(m.group(3)),
                    bool(CLOSING.search(text[max(0, m.start() - 24):m.start()]))))
    for m in HASH_REF.finditer(text or ""):
        out.append((own_repo.lower(), None, int(m.group(1)), bool(CLOSING.search(text[max(0, m.start() - 24):m.start()]))))
    return out


class Graph:
    def __init__(self, repo):
        self.repo = repo
        self.meta = {}
        self.commits, self.pulls, self.issues = {}, {}, {}
        self.external = {}                      # (repo_lower, 'pull'|'issue', n) -> record
        self.file_commits = defaultdict(list)   # filename -> [sha]
        self.prev = {}                          # new name -> old name (RENAMED_FROM)
        self.reverted_by = {}                   # reverted sha -> reverting commit sha
        self.pr_of_commit = {}                  # sha -> PR number (PART_OF)
        self._link_cache = {}

    # ---------- resolving references ----------
    def resolve(self, repo_l, hint, n):
        if repo_l == self.repo.lower():
            if n in self.pulls and hint != "issues":
                return ("pull", self.repo, self.pulls[n], False)
            if n in self.issues and hint != "pull":
                return ("issue", self.repo, self.issues[n], False)
            return None
        for kind in (("pull", "issue") if hint != "issues" else ("issue",)):
            rec = self.external.get((repo_l, kind, n))
            if rec:
                return (kind, rec["_repo"], rec, True)
        return None

    def links_for_commit(self, sha):
        """Everything verifiably connected to a commit: its PR, direct refs, and refs made by its PR."""
        if sha in self._link_cache:
            return self._link_cache[sha]
        c = self.commits[sha]
        found, seen = [], set()

        def add(res, edge, via):
            if not res:
                return
            kind, repo, rec, ext = res
            key = (repo.lower(), kind, rec["number"])
            if key in seen:
                return
            seen.add(key)
            found.append({"kind": kind, "repo": repo, "rec": rec, "external": ext, "edge": edge, "via": via})

        if sha in self.pr_of_commit:
            add(("pull", self.repo, self.pulls[self.pr_of_commit[sha]], False), "PART_OF", "merge_commit_sha")
        msg = c.get("message", "")
        for repo_l, hint, n, closing in parse_refs(msg, self.repo):
            res = self.resolve(repo_l, hint, n)
            if res:
                edge = "PART_OF" if (res[0] == "pull" and not res[3] and SQUASH.search(msg.split("\n")[0]) and
                                     int(SQUASH.search(msg.split("\n")[0]).group(1)) == n) else ("CLOSES" if closing else "REFERENCES")
                add(res, edge, "commit message")
        for l in list(found):
            if l["kind"] == "pull" and not l["external"]:
                p = l["rec"]
                for repo_l, hint, n, closing in parse_refs((p.get("title") or "") + "\n" + (p.get("body") or ""), self.repo):
                    res = self.resolve(repo_l, hint, n)
                    if res and not (res[0] == "pull" and not res[3] and n == p["number"]):
                        add(res, "CLOSES" if closing else "REFERENCES", f"PR #{p['number']} text")
        self._link_cache[sha] = found
        return found


def load_graph(repo, raw_dir="data/raw"):
    raw = Path(raw_dir)
    g = Graph(repo)
    d = raw / repo.replace("/", "__")
    g.meta = _read(d / "meta.json", {})
    for c in _read(d / "commits.json", []):
        g.commits[c["sha"]] = c
    for p in _read(d / "pulls.json", []):
        g.pulls[p["number"]] = p
    for i in _read(d / "issues.json", []):
        g.issues[i["number"]] = i
    t = _read(d / "targeted.json", {})
    g.targeted_counts = {k: len(t.get(k, [])) for k in ("commits", "pulls", "issues")}
    for c in t.get("commits", []):
        g.commits[c["sha"]] = c
    for p in t.get("pulls", []):
        g.pulls[p["number"]] = {**g.pulls.get(p["number"], {}), **p}
    for i in t.get("issues", []):
        g.issues[i["number"]] = {**g.issues.get(i["number"], {}), **i}
    if raw.exists():
        for other in raw.iterdir():
            if other.is_dir() and other != d:
                ot = _read(other / "targeted.json", {})
                orepo = ot.get("repo")
                if orepo and orepo.lower() != repo.lower():
                    for kind, key in (("pull", "pulls"), ("issue", "issues")):
                        for r in ot.get(key, []):
                            g.external[(orepo.lower(), kind, r["number"])] = {**r, "_repo": orepo}
    for sha, c in g.commits.items():
        for f in c.get("files", []):
            g.file_commits[f["filename"]].append(sha)
            if f.get("previous_filename"):
                g.prev[f["filename"]] = f["previous_filename"]
        m = REVERT.search(c.get("message", ""))
        if m:
            for full in g.commits:
                if full.startswith(m.group(1)):
                    g.reverted_by[full] = sha
    for n, p in g.pulls.items():
        if p.get("merge_commit_sha") in g.commits:
            g.pr_of_commit[p["merge_commit_sha"]] = n
    for sha, c in g.commits.items():
        m = SQUASH.search(_first_line(c.get("message", "")))
        if m and int(m.group(1)) in g.pulls:
            g.pr_of_commit.setdefault(sha, int(m.group(1)))
    return g


# ---------- per-file analysis ----------
def file_names(g, path):
    names, changed = {path}, True
    while changed:
        changed = False
        for n in list(names):
            if n in g.prev and g.prev[n] not in names:
                names.add(g.prev[n]); changed = True
    return names


def analyse(g, path):
    names = file_names(g, path)
    shas = {s for n in names for s in g.file_commits.get(n, [])}
    if not shas:
        return None
    commits = sorted((g.commits[s] for s in shas), key=lambda c: c["date"])
    linked = [(c, g.links_for_commit(c["sha"])) for c in commits]
    linked = [(c, l) for c, l in linked if l]
    return {"path": path, "names": names, "commits": commits, "linked": linked,
            "decision": linked[0] if linked else None}


def drift_signal(g, a):
    """'reason resolved AFTER the change': the decision's own text says workaround/stop-gap, and an
    UPSTREAM (other-repo) PR/issue linked from it was merged/closed later than the decision commit."""
    import re
    if not a["decision"]:
        return None
    dc, dlinks = a["decision"]
    own_text = (dc.get("message") or "") + " " + " ".join(
        ((l["rec"].get("title") or "") + " " + (l["rec"].get("body") or ""))
        for l in dlinks if l["kind"] == "pull" and not l.get("external"))
    if not re.search(r"work[\s-]?around|temporar(?:y|ily)|\bhack\b|\bfallback\b|\buntil\b|\bsuppress", own_text, re.I):
        return None
    d0 = _parse(dc["date"])
    later = []
    for l in dlinks:
        if not l.get("external"):
            continue
        r = l["rec"]
        when = r.get("merged_at") if l["kind"] == "pull" else r.get("closed_at")
        if when and d0 and _parse(when) and _parse(when) > d0:
            later.append(l)
    return later or None

# ---------- evidence helpers ----------
class Ev:
    def __init__(self):
        self.items, self.index = [], {}

    def add(self, key, typ, title, snippet, url, date, author, et="verified"):
        if key in self.index:
            return self.index[key]
        eid = f"ev{len(self.items) + 1}"
        self.index[key] = eid
        self.items.append({"id": eid, "type": typ, "title": title, "snippet": snippet, "url": url,
                           "date": _day(date), "author": author or "unknown", "evidence_type": et})
        return eid

    def commit(self, c):
        return self.add(("c", c["sha"]), "commit", _first_line(c["message"]), _snip(c["message"]), c["url"], c["date"],
                        c.get("author_login") or c.get("author_name"))

    def link(self, l):
        r, repo = l["rec"], l["repo"]
        if l["kind"] == "pull":
            return self.add(("p", repo, r["number"]), "pull_request", f"{repo} PR #{r['number']}: {r['title']}",
                            _snip(r.get("body")), r["url"], r.get("merged_at") or r.get("created_at"), (r.get("user") or {}).get("login"))
        return self.add(("i", repo, r["number"]), "issue", f"{repo} issue #{r['number']}: {r['title']}",
                        _snip(r.get("body")), r["url"], r.get("created_at"), (r.get("user") or {}).get("login"))


def _label(l):
    return f"{'upstream ' if l['external'] else ''}{'PR' if l['kind'] == 'pull' else 'issue'} #{l['rec']['number']}" + \
           (f" ({l['repo']})" if l["external"] else "")


def _item(path):
    return {"id": f"file:{path}", "kind": "file", "label": path}


def _who(g, login, evids):
    if not login or login == "unknown":
        return None
    dates = [c["date"] for c in g.commits.values() if (c.get("author_login") or c.get("author_name")) == login]
    last = max(dates) if dates else None
    ref = _parse(g.meta.get("fetched_at")) or datetime.now(timezone.utc)
    active = bool(last and _parse(last) and (ref - _parse(last)).days <= 365)
    return {"login": login, "reason": f"author of {', '.join(evids)} (within the ingested slice only)",
            "evidence_ids": evids, "last_active": _day(last), "still_active": active}


def _decision(g, a, ev):
    dc, dlinks = a["decision"]
    prs = [l for l in dlinks if l["kind"] == "pull" and not l["external"]]
    summary = prs[0]["rec"]["title"] if prs else _first_line(dc["message"])
    dec = {"summary": summary, "date": _day(dc["date"]), "status": "current", "superseded_by": None}
    rev = g.reverted_by.get(dc["sha"])
    if rev:
        rc = g.commits[rev]
        dec["status"] = "superseded"
        dec["superseded_by"] = {"summary": _first_line(rc["message"]), "date": _day(rc["date"]), "evidence_ids": [ev.commit(rc)]}
    elif drift_signal(g, a):
        dec["status"] = "possibly_expired"
    return dec


def _connected(ev, dlinks):
    out = []
    for l in dlinks:
        et = {"pull": "DECIDED_IN"}.get(l["kind"], "MOTIVATED_BY")
        if l["external"]:
            et = "REFERENCES"
        if l["edge"] == "CLOSES":
            et = "CLOSES"
        out.append({"id": f"{'pr' if l['kind'] == 'pull' else 'issue'}:{l['rec']['number']}" + (f"@{l['repo']}" if l["external"] else ""),
                    "kind": "pull_request" if l["kind"] == "pull" else "issue",
                    "label": f"#{l['rec']['number']} {l['rec']['title']}" + (f" ({l['repo']})" if l["external"] else ""),
                    "edge_type": et, "evidence_type": "verified", "evidence_ids": [ev.link(l)]})
    return out


def _finish(g, env, ev, extra_limits=()):
    env["evidence"] = ev.items
    env["limitations"] = BASE_LIMITS + list(extra_limits)
    env["confidence"] = compute_confidence(ev.items)
    return env


# ---------- the four modes ----------
def answer(g, path, mode, routed=None):
    a = analyse(g, path)
    item = _item(path)
    if not a:
        return insufficient(mode=mode, item=None, routed_mode=routed, limitations=["Bounded slice of history"])
    ev = Ev()
    eff = routed or mode
    first = a["commits"][0]
    if eff == "why":
        if not a["decision"]:
            ids = [ev.commit(first)]
            env = build_envelope(mode=mode, routed_mode=routed, item=item, answer=[
                {"text": f"The earliest ingested change to {path} is commit {first['sha'][:7]} ({_day(first['date'])}): \"{_first_line(first['message'])}\".", "evidence_ids": ids, "label": "verified"},
                {"text": "No pull request or issue is linked to this file's changes in the ingested history, so the reason is not recorded here.", "evidence_ids": [], "label": "unknown"}])
            return _finish(g, env, ev)
        dc, dl = a["decision"]
        ans = [{"text": f"The earliest linked change to {path} is commit {dc['sha'][:7]} on {_day(dc['date'])}: \"{_first_line(dc['message'])}\".",
                "evidence_ids": [ev.commit(dc)], "label": "verified"}]
        for l in dl:
            verb = {"PART_OF": "is part of", "CLOSES": "closes", "REFERENCES": "references"}[l["edge"]]
            ans.append({"text": f"That change {verb} {_label(l)}: \"{l['rec']['title']}\" ({l['via']}).", "evidence_ids": [ev.link(l)], "label": "verified"})
        dec = _decision(g, a, ev)
        who = _who(g, dc.get("author_login") or dc.get("author_name"), [ev.commit(dc)])
        env = build_envelope(mode=mode, routed_mode=routed, item=item, answer=ans, decision=dec, who_to_ask=who,
                             connected_items=_connected(ev, dl), connected_note="Based on repo history only, not a prediction.")
        return _finish(g, env, ev)
    if eff == "history":
        tl, shown = [], a["commits"][:1] + a["commits"][-11:] if len(a["commits"]) > 12 else a["commits"]
        for i, c in enumerate(shown):
            ev_type = "revert" if c["message"].startswith("Revert") else ("original_change" if c is first else "later_change")
            tl.append({"date": _day(c["date"]), "event": ev_type, "text": _first_line(c["message"]), "evidence_ids": [ev.commit(c)], "evidence_type": "verified"})
        dec = None
        if a["decision"]:
            dc, dl = a["decision"]
            for l in dl:
                if l["kind"] == "issue" and not l["external"]:
                    tl.append({"date": _day(l["rec"].get("created_at")), "event": "discussion", "text": f"Issue #{l['rec']['number']}: {l['rec']['title']}", "evidence_ids": [ev.link(l)], "evidence_type": "verified"})
            dec = _decision(g, a, ev)
            if dec["superseded_by"]:
                tl.append({"date": dec["superseded_by"]["date"], "event": "supersession", "text": dec["superseded_by"]["summary"], "evidence_ids": dec["superseded_by"]["evidence_ids"], "evidence_type": "verified"})
        tl.sort(key=lambda t: t["date"])
        extra = [f"Timeline shows the first and the latest {len(shown) - 1} of {len(a['commits'])} commits"] if len(shown) < len(a["commits"]) else []
        return _finish(g, build_envelope(mode=mode, routed_mode=routed, item=item, timeline=tl, decision=dec), ev, extra)
    if eff == "still_needed":
        if not a["decision"]:
            return insufficient(mode=mode, item=item, routed_mode=routed, limitations=BASE_LIMITS)
        dc, dl = a["decision"]
        dec = _decision(g, a, ev)
        orig = [ev.commit(dc)] + [ev.link(l) for l in dl]
        later_commits = [c for c in a["commits"] if c["date"] > dc["date"]]
        ans = [{"text": f"The recorded reason comes from commit {dc['sha'][:7]} ({_day(dc['date'])}) and {', '.join(_label(l) for l in dl)}.", "evidence_ids": orig, "label": "verified"}]
        if later_commits:
            lc = later_commits[-1]
            ans.append({"text": f"{len(later_commits)} later commit(s) touched this file; the latest is {lc['sha'][:7]} on {_day(lc['date'])}.", "evidence_ids": [ev.commit(lc)], "label": "verified"})
        drift = None
        later = drift_signal(g, a)
        resolved_before = [l for l in dl if l not in (later or []) and ((l["kind"] == "issue" and l["rec"].get("closed_at")) or (l["kind"] == "pull" and l["external"] and l["rec"].get("merged_at")))]
        if later:
            lid = [ev.link(l) for l in later]
            ans.append({"text": f"A linked item changed after this decision: {', '.join(_label(l) for l in later)}. This may mean the original reason no longer applies.", "evidence_ids": lid, "label": "inferred"})
            drift = {"label": "Possibly outdated. Verify.", "evidence_type": "heuristic", "original_reason_evidence": orig, "later_change_evidence": lid,
                     "workaround_still_in_code": {"checked": False, "path": path, "note": "File contents are not ingested; a human must confirm the code is still present."},
                     "needs_human_verification": ["Confirm the original reason no longer applies", "Confirm the code is still present and still used"]}
        elif resolved_before:
            lid = [ev.link(l) for l in resolved_before]
            ans.append({"text": f"{', '.join(_label(l) for l in resolved_before)} was already resolved before this change was made. A fix merged upstream does not show that the workaround is unnecessary, for example if older versions of the dependency are still supported. Whether the conditions behind it still apply cannot be determined from the ingested history.", "evidence_ids": lid, "label": "unknown"})
        else:
            ans.append({"text": "Nothing in the ingested history says the original reason has been resolved or removed.", "evidence_ids": [], "label": "unknown"})
        return _finish(g, build_envelope(mode=mode, routed_mode=routed, item=item, answer=ans, decision=dec, drift_alert=drift), ev)
    if eff == "dna":
        origin_ids = [ev.commit(first)]
        key = []
        for c, dl in a["linked"][:3]:
            for l in dl:
                if l["kind"] == "pull" and not l["external"]:
                    key.append({"summary": l["rec"]["title"], "date": _day(c["date"]), "evidence_ids": [ev.link(l)]})
        together = Counter()
        for c in a["commits"]:
            for f in c.get("files", []):
                if f["filename"] not in a["names"]:
                    together[f["filename"]] += 1
        dna = {"origin": {"text": f"First ingested change: \"{_first_line(first['message'])}\" ({_day(first['date'])}).", "evidence_ids": origin_ids},
               "key_decisions": key[:3],
               "changed_together": [{"path": p, "times": n, "evidence_type": "inferred"} for p, n in together.most_common(5)]}
        conn = _connected(ev, a["decision"][1]) if a["decision"] else []
        return _finish(g, build_envelope(mode=mode, routed_mode=routed, item=item, dna=dna, connected_items=conn,
                                         connected_note="Based on repo history only, not a prediction."), ev,
                       ["Imports are not parsed: 'changed together' is inferred from commits"])
    return insufficient(mode=mode, item=item, routed_mode=routed)


# ---------- overview + items ----------
def current_files(g):
    old_names = set(g.prev.values())
    return sorted(f for f in g.file_commits if f not in old_names)


def _file_state(g, path):
    a = analyse(g, path)
    if not a:
        return None
    return a


def items(g, q=""):
    out = []
    for f in current_files(g):
        if q and q.lower() not in f.lower():
            continue
        a = analyse(g, f)
        n = sum(len(l) for _, l in a["linked"]) if a else 0
        out.append({"id": f"file:{f}", "kind": "file", "label": f, "evidence_count": n, "state": "explained" if a and a["decision"] else "unknown"})
    out.sort(key=lambda i: (i["state"] != "explained", -i["evidence_count"], i["label"]))
    return {"items": out[:300]}


def overview(g):
    explained = unchanged = changed = superseded = outdated = 0
    files = current_files(g)
    for f in files:
        a = analyse(g, f)
        if not a or not a["decision"]:
            continue
        explained += 1
        dc = a["decision"][0]
        if g.reverted_by.get(dc["sha"]):
            superseded += 1
        elif any(c["date"] > dc["date"] for c in a["commits"]):
            changed += 1
        else:
            unchanged += 1
        if drift_signal(g, a):
            outdated += 1
    m = g.meta.get("counts") or {}
    note = g.meta.get("note", "Bounded slice, not the full history.")
    if g.targeted_counts and any(g.targeted_counts.values()):
        note += f" Plus specifically fetched items: {g.targeted_counts['commits']} commits, {g.targeted_counts['pulls']} PRs, {g.targeted_counts['issues']} issues."
    return {"repo": g.repo,
            "ingested": {"commits": m.get("commits", len(g.commits)), "pulls": m.get("pulls", len(g.pulls)), "issues": m.get("issues", len(g.issues)),
                         "fetched_at": g.meta.get("fetched_at", ""), "note": note},
            "counts": {"total_items": len(files), "explained": explained, "unknown": len(files) - explained,
                       "unchanged_since_decision": unchanged, "changed_since_decision": changed,
                       "superseded": superseded, "possibly_outdated": outdated}}


def ask(g, item_id, mode, question=None):
    from qa.mock_engine import route_free
    path = item_id[5:] if item_id.startswith("file:") else None
    if path is None:
        return insufficient(mode=mode, item=None)
    if mode == "free":
        routed = route_free(question or "")
        if routed is None:
            return insufficient(mode="free", item=None)
        r = answer(g, path, "free", routed)
        r["mode"], r["routed_mode"] = "free", routed
        return r
    return answer(g, path, mode)
