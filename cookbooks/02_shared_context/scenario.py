"""Make three real changes to the sample repos and time how long each takes to become a pull
request against the context repo.

  1. orders-service: a new required env var (config.toml + README)
  2. billing-service: a new endpoint (README)
  3. orders-service: a renamed CLI flag (cli.py + README)

Each is the kind of change a teammate must know about, so the agent should update the context
repo for each. Runs and pull requests are read from the use case summary.
"""
from __future__ import annotations

import os
import sys
import time

import github_client as gh
import tares_client as tc

PREFIX = os.getenv("SAMPLE_PREFIX", "tares-cb")
WAIT_S = int(os.getenv("SCENARIO_WAIT_S", "600"))


def changes():
    o = f"{gh.owner()}/{PREFIX}-orders-service"
    b = f"{gh.owner()}/{PREFIX}-billing-service"
    yield ("orders-service: new required env var STRIPE_WEBHOOK_SECRET", [
        (o, "config.toml", "# orders-service configuration\n[server]\nport = 8080\n\n[database]\n"
                           "# DATABASE_URL is required; no default\npool_size = 10\n\n[payments]\n"
                           "# STRIPE_WEBHOOK_SECRET is required: incoming Stripe webhooks are verified with it\n"),
        (o, "README.md", "# orders-service\n\nTakes orders over HTTP and writes them to Postgres.\n\n## Endpoints\n\n"
                         "- `POST /orders` create an order\n- `GET /orders/{id}` fetch one order\n- `POST /webhooks/stripe` "
                         "Stripe payment webhooks (verified with STRIPE_WEBHOOK_SECRET)\n\n## Configuration\n\nSee `config.toml`. "
                         "`DATABASE_URL` and `STRIPE_WEBHOOK_SECRET` are required.\n\n## CLI\n\n`orders --port 8080` starts the service.\n"),
    ])
    yield ("billing-service: new endpoint GET /invoices/{id}", [
        (b, "README.md", "# billing-service\n\nCharges customers for orders. Reads orders from orders-service over HTTP.\n\n"
                         "## Endpoints\n\n- `POST /invoices` create an invoice for an order\n- `GET /invoices/{id}` fetch one invoice "
                         "(new)\n\n## Configuration\n\nSee `config.toml`. `ORDERS_URL` points at orders-service.\n"),
    ])
    yield ("orders-service: CLI flag --port renamed to --listen", [
        (o, "cli.py", '"""orders CLI: `orders --listen 8080`."""\nimport argparse\n\n\ndef main():\n'
                      '    p = argparse.ArgumentParser(prog="orders")\n'
                      '    p.add_argument("--listen", type=int, default=8080, help="port to listen on (was --port)")\n'
                      '    args = p.parse_args()\n    print(f"orders-service listening on {args.listen}")\n\n\n'
                      'if __name__ == "__main__":\n    main()\n'),
        (o, "README.md", "# orders-service\n\nTakes orders over HTTP and writes them to Postgres.\n\n## Endpoints\n\n"
                         "- `POST /orders` create an order\n- `GET /orders/{id}` fetch one order\n- `POST /webhooks/stripe` "
                         "Stripe payment webhooks (verified with STRIPE_WEBHOOK_SECRET)\n\n## Configuration\n\nSee `config.toml`. "
                         "`DATABASE_URL` and `STRIPE_WEBHOOK_SECRET` are required.\n\n## CLI\n\n`orders --listen 8080` starts the service "
                         "(the flag was `--port` before).\n"),
    ])


def main() -> None:
    tc.require_env("GITHUB_TOKEN", "GITHUB_OWNER")
    tc.check_tares()
    uc = tc.find_usecase()
    if not uc:
        sys.exit("no use case yet: run setup.py first")
    uid = uc["id"]
    before = {r["id"] for r in tc.summary(uid).get("runs", [])}

    committed = []
    for title, files in changes():
        t0 = time.time()
        for repo, path, content in files:
            sha = gh.put_file(repo, path, content, title, gh.default_branch(repo))
        committed.append((title, files[0][0], t0, sha))
        print(f"committed  {title}  ({files[0][0]} {sha[:7]})")
        time.sleep(3)

    print(f"\nwaiting up to {WAIT_S}s for the agent (poll 60s, trigger window 2m, cooldown 5m per repo)")
    seen = {}
    deadline = time.time() + WAIT_S
    while time.time() < deadline:
        s = tc.summary(uid)
        for r in s.get("runs", []):
            if r["id"] in before or r["id"] in seen or r.get("status") == "running":
                continue
            seen[r["id"]] = r
            started = [c for c in committed if c[1] == r.get("repo")]
            since = f"{time.time() - min(c[2] for c in started):.0f}s after the commit" if started else ""
            print(f"run  {r.get('repo')}  {r.get('status')}  rounds {r.get('rounds')}/{r.get('max_rounds')}  "
                  f"{('PR ' + r['pr_url']) if r.get('pr_url') else 'no PR'}  {since}")
        repos_done = {r.get("repo") for r in seen.values()}
        if {c[1] for c in committed} <= repos_done:
            break
        time.sleep(15)

    ctx = f"{gh.owner()}/{PREFIX}-context"
    pulls = gh.open_pulls(ctx)
    print(f"\nopen pull requests on {ctx}: {len(pulls)}")
    for p in pulls:
        print(f"  #{p['number']} {p['title']}  {p['html_url']}")
    if not seen:
        print("no runs finished in time; check the use case page and the agent's Runs & findings")


if __name__ == "__main__":
    main()
