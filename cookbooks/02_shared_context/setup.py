"""Wire Tares to your three template copies: store the token as a Tares credential and create the
shared code context use case. Idempotent: safe to run again.

Before this: create the three repos from the templates (one click each on GitHub, "Use this
template"): glassflow/tares-cookbook-orders-service, glassflow/tares-cookbook-billing-service,
glassflow/tares-cookbook-context, named <prefix>-orders-service, <prefix>-billing-service,
<prefix>-context under your user or org (prefix default tares-cb, change with SAMPLE_PREFIX),
and a fine-grained token scoped to those three.

Environment: GITHUB_TOKEN, GITHUB_OWNER; optional TARES_URL, TARES_TOKEN, SAMPLE_PREFIX,
CONTEXT_LAYOUT (per_repo | existing, default per_repo), TARES_MODEL.
"""
from __future__ import annotations

import os

import github_client as gh
import tares_client as tc

PREFIX = os.getenv("SAMPLE_PREFIX", "tares-cb")
SAMPLES = ("orders-service", "billing-service")


def main() -> None:
    tc.require_env("GITHUB_TOKEN", "GITHUB_OWNER")
    tc.check_tares()

    repos = []
    for sname in SAMPLES:
        full = gh.require_repo(f"{PREFIX}-{sname}", template=f"glassflow/tares-cookbook-{sname}")
        repos.append(full)
        print(f"sample repo ready: {full}")
    ctx = gh.require_repo(f"{PREFIX}-context", template="glassflow/tares-cookbook-context")
    print(f"context repo ready: {ctx}")

    tc.ensure_credential(os.environ["GITHUB_TOKEN"])
    existing = tc.find_usecase()
    if existing:
        print(f"use case already exists: {existing['id']} ({existing['status']})")
        return
    inst = tc.create_usecase(repos, ctx, branch=gh.default_branch(ctx),
                             layout=os.getenv("CONTEXT_LAYOUT", "per_repo"),
                             model=os.getenv("TARES_MODEL", ""))
    print(f"use case created: {inst['id']} with {len(inst['objects'])} objects")
    print(f"open {tc.TARES_URL}/usecases/{inst['id']} to watch it")


if __name__ == "__main__":
    main()
