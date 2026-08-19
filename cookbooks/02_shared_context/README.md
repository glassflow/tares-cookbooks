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

- **[uv](https://docs.astral.sh/uv/)** (or Python 3.11 / 3.12 with pipx): it installs Tares and
  runs the cookbook scripts.
- **Tares 1.8.1 or newer running locally.** Not running yet? Install and start it (the console
  opens at http://127.0.0.1:8787; leave it running in its own shell):

  ```bash
  uv tool install tares        # or: pipx install tares
  tares up
  ```

- **An Anthropic key** for the maintainer agent (it is a real agent): set it under
  **Settings > Anthropic** in the console, or `export ANTHROPIC_API_KEY=sk-ant-...` before `tares up`.
- **A GitHub account** (user or a throwaway org). Setup step 1 creates three small repos from our
  templates and a token scoped to them; that is all the GitHub side needs.

Docker is not needed for this cookbook; the systems it watches are GitHub repositories.

## Setup

**1. Three repos from our templates** (one click each; private is fine, keep the names):

- [create `tares-cb-orders-service`](https://github.com/new?template_owner=glassflow&template_name=tares-cookbook-orders-service&name=tares-cb-orders-service&visibility=private)
- [create `tares-cb-billing-service`](https://github.com/new?template_owner=glassflow&template_name=tares-cookbook-billing-service&name=tares-cb-billing-service&visibility=private)
- [create `tares-cb-context`](https://github.com/new?template_owner=glassflow&template_name=tares-cookbook-context&name=tares-cb-context&visibility=private)

Pick your user or org as the owner on each. Different names? Set `SAMPLE_PREFIX` below to your prefix.

**2. One token on those three repos**: [new fine-grained token](https://github.com/settings/personal-access-tokens/new),
Repository access "Only select repositories" with the three above, permissions Contents
**Read and write**, Pull requests **Read and write** (Metadata Read-only is added for you). GitHub
starts each permission at Read-only; check both before generating.

**3. Wire Tares:**

```bash
# from the repo root: venv + deps
uv venv && uv pip install -e . && source .venv/bin/activate
cd cookbooks/02_shared_context

export GITHUB_TOKEN=github_pat_...     # the token from step 2
export GITHUB_OWNER=<your user or org>
# optional: SAMPLE_PREFIX (default tares-cb), CONTEXT_LAYOUT (per_repo | existing), TARES_URL

python setup.py
```

`setup.py` checks the three repos are there, stores the token in Tares as the credential
`cookbook-github`
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
  samples/            ← what the two service templates contain, for reference
  tares_client.py     ← credential, use case, summary (REST)
  github_client.py    ← repos, files, pull requests (REST)
  setup.py            ← credential + use case against your three template copies
  scenario.py         ← the three changes and the timing loop
  teardown.py         ← remove what setup created in Tares
```
