"""Just enough GitHub REST for the cookbook: create repos, put files, list pull requests.
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


def ensure_repo(name: str, description: str) -> str:
    """Create `owner/name` if it does not exist (user or org, whichever GITHUB_OWNER is). Returns full_name."""
    full = f"{owner()}/{name}"
    with _cx() as cx:
        if cx.get(f"/repos/{full}").status_code == 200:
            return full
        me = cx.get("/user").json().get("login")
        url = "/user/repos" if me == owner() else f"/orgs/{owner()}/repos"
        r = cx.post(url, json={"name": name, "description": description, "private": True, "auto_init": True})
        if r.status_code >= 300:
            sys.exit(f"could not create {full}: {r.status_code} {r.text[:200]}")
        time.sleep(2)   # a fresh repo needs a moment before contents calls succeed
    return full


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
