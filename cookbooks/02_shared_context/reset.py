"""Put the three GitHub repos back to their freshly created state so the scenario can run again:
each repo's default branch is rewound to the template's initial commit (no extra commits, no
history for the agent to read), the context repo's demo pull requests are closed and their
`tares/context-*` branches deleted. If GitHub refuses the rewind (a protected branch), the files
are rewritten to the template content instead.

Run teardown.py first (or after; they are independent), then setup.py and scenario.py.
Environment: GITHUB_TOKEN, GITHUB_OWNER; optional SAMPLE_PREFIX, CONTEXT_PATH (default "").
"""
from __future__ import annotations

import os
import pathlib

import github_client as gh
import tares_client as tc

HERE = pathlib.Path(__file__).parent
PREFIX = os.getenv("SAMPLE_PREFIX", "tares-cb")
SAMPLES = ("orders-service", "billing-service")
SEED_README = "# Shared context\n\nKept current by Tares. One page per service; the maintainer agent updates them when the sample services change.\n"


def reset_to_initial(repo: str) -> None:
    """Move the default branch back to the template's initial commit so the repo looks freshly
    created: no reset commits, no leftover history for the agent to read."""
    branch = gh.default_branch(repo)
    root = gh.root_commit(repo, branch)
    if root and gh.force_branch(repo, branch, root):
        print(f"reset: {repo} {branch} -> {root[:7]} (template's initial commit)")
    else:
        print(f"could not rewind {repo}; falling back to rewriting files")
        return False
    return True


def reset_sample(repo: str, sample: str) -> None:
    if reset_to_initial(repo):
        return
    branch = gh.default_branch(repo)
    root = HERE / "samples" / sample
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root))
            gh.put_file(repo, rel, path.read_text(), f"reset {rel} to the template", branch)
    print(f"reset: {repo}")


def reset_context(repo: str) -> None:
    branch = gh.default_branch(repo)
    for pr in gh.open_pulls(repo):
        if pr.get("head", {}).get("ref", "").startswith("tares/context-"):
            gh.close_pull(repo, pr["number"])
            print(f"closed PR #{pr['number']} on {repo}")
    for b in gh.list_branches(repo):
        if b.startswith("tares/context-"):
            gh.delete_branch(repo, b)
            print(f"deleted branch {b}")
    if reset_to_initial(repo):
        return
    ctx_path = os.getenv("CONTEXT_PATH", "").strip("/")
    for f in gh.list_files(repo, ctx_path, branch):
        if f.lower().endswith(".md") and f.split("/")[-1] != "README.md":
            gh.delete_file(repo, f, f"reset: remove {f}", branch)
            print(f"removed {f}")
    readme = f"{ctx_path}/README.md" if ctx_path else "README.md"
    gh.put_file(repo, readme, SEED_README, "reset README to the seed", branch)
    print(f"reset: {repo}")


def main() -> None:
    tc.require_env("GITHUB_TOKEN", "GITHUB_OWNER")
    for s in SAMPLES:
        reset_sample(f"{gh.owner()}/{PREFIX}-{s}", s)
    reset_context(f"{gh.owner()}/{PREFIX}-context")
    print("done; now: python teardown.py && python setup.py && python scenario.py")


if __name__ == "__main__":
    main()
