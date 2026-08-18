# 02 · Shared code context

A team keeps its shared context (what each service does, its endpoints, config, conventions) in one
GitHub repository. This cookbook has Tares keep that repository current on its own: it watches
commits across two sample services and, when something a teammate must know changes, an agent
updates the context repo and opens a pull request.

It uses the **Shared code context** use case shipped in Tares 1.8.0: one call creates the sources
(one per repo), the timeline view, the trigger, GitHub's hosted MCP server bound to your token, and
the maintainer agent. Nothing to deploy; the agent runs inside Tares.

**Outcome measured:** for three real changes (a new required env var, a new endpoint, a renamed
CLI flag), whether a correct pull request appears against the context repo, and how long after the
commit it lands.

## Prerequisites

The [repo prerequisites](../../README.md#prerequisites-shared-by-every-cookbook), plus:

- **Tares 1.8.1 or newer** running locally: `tares up` (console at http://127.0.0.1:8787).
- **An Anthropic key** set under Settings > Anthropic in the console (or `ANTHROPIC_API_KEY`
  before `tares up`): the maintainer agent is a real agent.
- **A GitHub fine-grained token** on your user or a throwaway org, granted on the three repos this
  cookbook creates (`<prefix>-orders-service`, `<prefix>-billing-service`, `<prefix>-context`; the
  token needs to be able to create them, so grant it on all repositories of the owner, or create the
  three repos by hand first): Contents **Read and write**, Pull requests **Read and write**,
  Metadata Read-only. GitHub starts each permission at Read-only; check them after adding.

## Setup

```bash
# from the repo root: venv + deps
uv venv && uv pip install -e . && source .venv/bin/activate
cd cookbooks/02_shared_context

export GITHUB_TOKEN=github_pat_...     # the fine-grained token above
export GITHUB_OWNER=<your user or org>
# optional: SAMPLE_PREFIX (default tares-cb), CONTEXT_LAYOUT (per_repo | existing), TARES_URL

python setup.py
```

`setup.py` creates the two sample service repos and pushes `samples/*` into them, creates the
context repo with a seed README, stores the token in Tares as the credential `cookbook-github`
(Settings > GitHub), and creates the use case `cookbook shared code context`. It prints the use
case URL; open it. First look on start is off in this cookbook so the only runs you see are the
ones the scenario causes.

## Run the scenario

```bash
python scenario.py
```

It commits three changes, one per beat, then polls the use case:

1. `orders-service`: `STRIPE_WEBHOOK_SECRET` becomes a required env var (config and README)
2. `billing-service`: a new endpoint `GET /invoices/{id}` (README)
3. `orders-service`: the CLI flag `--port` is renamed `--listen` (code and README)

For each run it prints the repo, status, rounds used, the pull request link and the time from the
commit to the run, then lists the open pull requests on the context repo. Expect the first run
about two to three minutes after the first commit (60s source poll, 2m trigger window); the two
`orders-service` commits are batched into one run when they land inside the trigger's 5m cooldown,
which is by design.

Then read the pull requests: each page should say what changed with the commit's short sha next to
the claim, and nothing about refactors or formatting.

## What you'll see

A representative run (Sonnet, `per_repo` layout):

| change | run | rounds | pull request | commit to PR |
|---|---|---|---|---|
| new required env var | ok | 7/12 | `orders-service.md` gains a Configuration entry | ~3 min |
| new endpoint | ok | 6/12 | `billing-service.md` Interfaces updated | ~3 min |
| renamed CLI flag | ok (batched with 1) | 8/12 | `orders-service.md` How to run updated | ~3 min |

Numbers vary by model and by how the commits fall into the trigger window; treat them as
directional.

## Teardown

```bash
python teardown.py     # deletes the use case, its objects and events, and the credential
```

The GitHub repos stay; delete them yourself if they were throwaways.

## Layout

```
cookbooks/02_shared_context/
  samples/            ← two tiny services pushed to the sample repos
  tares_client.py     ← credential, use case, summary (REST)
  github_client.py    ← repos, files, pull requests (REST)
  setup.py            ← create repos, credential, use case
  scenario.py         ← the three changes and the timing loop
  teardown.py         ← remove what setup created in Tares
```
