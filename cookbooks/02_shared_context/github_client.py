"""Just enough GitHub REST for the cookbook: check repos exist, put files, list pull requests.
Uses GITHUB_TOKEN (a fine-grained token with Contents and Pull requests Read and write, Metadata
Read-only, on the repos below) and GITHUB_OWNER (your user or a throwaway org)."""
from __future__ import annotations

import base64
import os
import sys
import time

import httpx

API = os.getenv("GITHUB_API", "https://api.github.com").rstrip("/")


def _cx() -> httpx.Client:
    tok = os.getenv("GITHUB_TOKEN")
    if not tok:
        sys.exit("missing environment: GITHUB_TOKEN (see README, Setup)")
    return httpx.Client(base_url=API, timeout=30, headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})


def owner() -> str:
    o = os.getenv("GITHUB_OWNER")
    if not o:
        sys.exit("missing environment: GITHUB_OWNER (your GitHub user or org)")
    return o


def require_repo(name: str, template: str) -> str:
    """Return `owner/name`, which you created from `template` with GitHub's "Use this template". The
    scripts never create repositories: your token stays scoped to exactly these three."""
    full = f"{owner()}/{name}"
    with _cx() as cx:
        r = cx.get(f"/repos/{full}")
        if r.status_code == 200:
            return full
    sys.exit(f"repository {full} does not exist, or the token cannot see it.\n"
             f"Create it from the template https://github.com/{template} (Use this template, name it "
             f"{name}, private is fine) and grant the token access to it, then rerun.")


def put_file(repo: str, path: str, content: str, message: str, branch: str = "main") -> str:
    """Create or update one file on `branch`; returns the commit sha."""
    with _cx() as cx:
        cur = cx.get(f"/repos/{repo}/contents/{path}", params={"ref": branch})
        body = {"message": message, "branch": branch,
                "content": base64.b64encode(content.encode()).decode()}
        if cur.status_code == 200:
            body["sha"] = cur.json()["sha"]
        r = cx.put(f"/repos/{repo}/contents/{path}", json=body)
        if r.status_code >= 300:
            sys.exit(f"could not write {repo}/{path}: {r.status_code} {r.text[:200]}")
        return r.json()["commit"]["sha"]


def default_branch(repo: str) -> str:
    with _cx() as cx:
        return cx.get(f"/repos/{repo}").json().get("default_branch", "main")


def open_pulls(repo: str) -> list[dict]:
    with _cx() as cx:
        r = cx.get(f"/repos/{repo}/pulls", params={"state": "open", "per_page": 50})
        return r.json() if r.status_code == 200 else []


def close_pull(repo: str, number: int) -> None:
    with _cx() as cx:
        cx.patch(f"/repos/{repo}/pulls/{number}", json={"state": "closed"})


def list_branches(repo: str) -> list[str]:
    with _cx() as cx:
        r = cx.get(f"/repos/{repo}/branches", params={"per_page": 100})
        return [b["name"] for b in r.json()] if r.status_code == 200 else []


def delete_branch(repo: str, name: str) -> None:
    with _cx() as cx:
        cx.delete(f"/repos/{repo}/git/refs/heads/{name}")


def list_files(repo: str, path: str = "", branch: str = "main") -> list[str]:
    """File paths directly under `path` on `branch` (not recursive)."""
    with _cx() as cx:
        r = cx.get(f"/repos/{repo}/contents/{path}".rstrip("/"), params={"ref": branch})
        if r.status_code != 200 or not isinstance(r.json(), list):
            return []
        return [e["path"] for e in r.json() if e.get("type") == "file"]


def delete_file(repo: str, path: str, message: str, branch: str = "main") -> None:
    with _cx() as cx:
        cur = cx.get(f"/repos/{repo}/contents/{path}", params={"ref": branch})
        if cur.status_code != 200:
            return
        cx.delete(f"/repos/{repo}/contents/{path}",
                  json={"message": message, "sha": cur.json()["sha"], "branch": branch})


def latest_commit_age_s(repo: str, branch: str = "main") -> float | None:
    """Seconds since the newest commit on `branch`, or None when unknown."""
    from datetime import datetime, timezone
    with _cx() as cx:
        r = cx.get(f"/repos/{repo}/commits", params={"sha": branch, "per_page": 1})
        if r.status_code != 200 or not r.json():
            return None
        ts = r.json()[0]["commit"]["committer"]["date"]
    then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - then).total_seconds()
