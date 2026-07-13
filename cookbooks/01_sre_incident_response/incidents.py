"""The incidents this cookbook stages on the platform. Each maps to one fault lever and a set
of keywords that should appear in a correct diagnosis."""

INCIDENTS = [
    {
        "name": "db_pool_exhaustion",
        "fault": {"lever": "db_pool_size", "value": 1},
        "root_hint": ["db_pool_size", "pool", "connection"],
        "cause": "DB connection-pool exhaustion (pool size cut to 1 by a deploy)",
    },
    {
        "name": "latency_regression",
        "fault": {"lever": "inject_latency_ms", "value": 800},
        "root_hint": ["latency", "inject_latency_ms", "audit", "slow"],
        "cause": "latency regression from the synchronous audit-log deploy",
    },
    {
        "name": "error_spike",
        "fault": {"lever": "error_rate", "value": 0.3},
        "root_hint": ["error_rate", "feature flag", "user_tier", "pricing"],
        "cause": "error spike from a bad feature-flag / pricing deploy",
    },
    {
        "name": "dependency_outage",
        "fault": {"lever": "dependency_down", "value": "payments-api"},
        "root_hint": ["payments-api", "dependency", "upstream"],
        "cause": "upstream dependency outage (payments-api unreachable)",
    },
]


def found_root_cause(text: str, incident: dict) -> bool:
    low = text.lower()
    return any(h.lower() in low for h in incident["root_hint"])
