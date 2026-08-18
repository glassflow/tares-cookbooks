"""Create the sample repos on GitHub, the context repo, the Tares credential and the use case.
Idempotent: safe to run again.

Environment: GITHUB_TOKEN, GITHUB_OWNER; optional TARES_URL, TARES_TOKEN, SAMPLE_PREFIX,
CONTEXT_LAYOUT (per_repo | existing, default per_repo), TARES_MODEL.
"""
from __future__ import annotations

import os
import pathlib

import github_client as gh
import tares_client as tc

HERE = pathlib.Path(__file__).parent
PREFIX = os.getenv("SAMPLE_PREFIX", "tares-cb")
SAMPLES = ("orders-service", "billing-service")


def push_sample(repo: str, sample: str, branch: str) -> None:
    root = HERE / "samples" / sample
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root))
            gh.put_file(repo, rel, path.read_text(), f"add {rel}", branch)


def main() -> None:
    tc.require_env("GITHUB_TOKEN", "GITHUB_OWNER")
    tc.check_tares()

    repos = []
    for s in SAMPLES:
        full = gh.ensure_repo(f"{PREFIX}-{s}", f"Tares cookbook sample: {s}")
        push_sample(full, s, gh.default_branch(full))
        repos.append(full)
        print(f"sample repo ready: {full}")
    ctx = gh.ensure_repo(f"{PREFIX}-context", "Tares cookbook: shared context repo")
    gh.put_file(ctx, "README.md",
                "# Shared context\n\nKept current by Tares. One page per service.\n", "seed", gh.default_branch(ctx))
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
