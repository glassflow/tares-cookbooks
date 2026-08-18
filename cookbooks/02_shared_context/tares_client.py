"""The cookbook's slice of a REAL running Tares (`tares up`, 1.8.1 or newer).

The shared code context use case creates its own sources, view, trigger, MCP server and agent
and owns them, so this client only needs three calls: create the GitHub credential once, create
the use case, and read the use case summary. Teardown deletes the use case (which deletes every
object it created) and the credential.

  TARES_URL      the daemon, default http://127.0.0.1:8787
  TARES_TOKEN    only when `tares up --auth` is on (Bearer)
"""
from __future__ import annotations

import os
import sys

import httpx

TARES_URL = os.getenv("TARES_URL", "http://127.0.0.1:8787").rstrip("/")
CREDENTIAL = os.getenv("TARES_GITHUB_CREDENTIAL", "cookbook-github")
USECASE_NAME = os.getenv("TARES_USECASE_NAME", "cookbook shared code context")


def _headers() -> dict:
    tok = os.getenv("TARES_TOKEN")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _cx() -> httpx.Client:
    return httpx.Client(base_url=TARES_URL, headers=_headers(), timeout=30)


def require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        sys.exit(f"missing environment: {', '.join(missing)} (see README, Setup)")


def check_tares() -> dict:
    try:
        with _cx() as cx:
            h = cx.get("/health")
            h.raise_for_status()
            recipes = cx.get("/api/usecases/recipes").json().get("recipes", [])
    except Exception as e:
        sys.exit(f"Tares is not reachable at {TARES_URL}: {e}\nStart it with `tares up` (1.8.1 or newer)")
    if not any(r["key"] == "shared_code_context" for r in recipes):
        sys.exit("this Tares has no shared_code_context recipe; upgrade to 1.8.1 or newer")
    return h.json()


def ensure_credential(token: str) -> str:
    """Store the GitHub token once under CREDENTIAL; rotate it if the name already exists."""
    with _cx() as cx:
        have = {c["name"] for c in cx.get("/api/integrations/github").json()["credentials"]}
        if CREDENTIAL in have:
            r = cx.put(f"/api/integrations/github/{CREDENTIAL}", json={"name": CREDENTIAL, "token": token})
        else:
            r = cx.post("/api/integrations/github", json={"name": CREDENTIAL, "token": token})
        r.raise_for_status()
        t = cx.post(f"/api/integrations/github/{CREDENTIAL}/test").json()
        if not t.get("ok"):
            sys.exit(f"GitHub rejected the token: {t.get('error')}")
        print(f"credential {CREDENTIAL}: signed in as {t.get('login')}")
    return CREDENTIAL


def find_usecase() -> dict | None:
    with _cx() as cx:
        for u in cx.get("/api/usecases").json()["usecases"]:
            if u["name"] == USECASE_NAME:
                return u
    return None


def create_usecase(source_repos: list[str], context_repo: str, *, branch: str = "main",
                   layout: str = "per_repo", context_path: str = "", write_mode: str = "pull_request",
                   bootstrap: bool = False, model: str = "") -> dict:
    params = {
        "credential": CREDENTIAL,
        "source_repos": [{"repo": r, "branch": branch} for r in source_repos],
        "context_repo": context_repo,
        "context_branch": branch,
        "context_path": context_path,
        "layout": layout,
        "trigger": "every_commit",
        "write_mode": write_mode,
        "bootstrap": bootstrap,      # off: the scenario makes the commits, so runs are deterministic
        "max_rounds": 12,
    }
    if model:
        params["model"] = model
    with _cx() as cx:
        r = cx.post("/api/usecases", json={"recipe": "shared_code_context",
                                           "name": USECASE_NAME, "params": params})
        if r.status_code >= 300:
            sys.exit(f"could not create the use case: {r.status_code} {r.text[:300]}")
        return r.json()


def summary(uid: str) -> dict:
    with _cx() as cx:
        r = cx.get(f"/api/usecases/{uid}/summary")
        r.raise_for_status()
        return r.json()


def delete_usecase(uid: str, purge_events: bool = True) -> None:
    with _cx() as cx:
        cx.delete(f"/api/usecases/{uid}", params={"purge_events": str(purge_events).lower()}).raise_for_status()


def delete_credential() -> None:
    with _cx() as cx:
        r = cx.delete(f"/api/integrations/github/{CREDENTIAL}")
        if r.status_code not in (200, 404):
            r.raise_for_status()
