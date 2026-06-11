"""Multi-lever fault-injecting API server for NavFlow cookbooks.

Extends Anthropic's SRE-demo server with several *independently injectable* faults, so the
same testbed can simulate more than one incident type. Each fault produces distinguishable
Prometheus metrics, distinguishable logs, and a change-log entry (the "deploy" that
introduced it). The metric shape matches the Anthropic cookbook, so the same Grafana
dashboard keeps working.

Faults (set at runtime via POST /admin/fault, or via env at startup):
  - db_pool_size       int    pool exhaustion (low pool + slow query under load)
  - inject_latency_ms  int    latency regression on /api/users (pool stays healthy)
  - error_rate         float  forced 5xx on `error_endpoint` (app exception, DB healthy)
  - dependency_down    str    upstream outage, e.g. "payments-api" (breaks /api/orders)

Healthy defaults = no fault. Inject one, observe, then POST /admin/reset.
"""
import os
import time
import random
import asyncio
import logging
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, Body
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("api-server")

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "demo")
DB_USER = os.getenv("DB_USER", "demo")
DB_PASSWORD = os.getenv("DB_PASSWORD", "demo")
SERVICE_NAME = os.getenv("SERVICE_NAME", "api-server")
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
KNOWN_DEPENDENCIES = ["payments-api", "auth-api"]

# ── the levers (runtime config) ────────────────────────────────────────────────
cfg = {
    "db_pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
    "db_pool_timeout": float(os.getenv("DB_POOL_TIMEOUT", "2")),
    "inject_latency_ms": int(os.getenv("INJECT_LATENCY_MS", "0")),
    "error_rate": float(os.getenv("ERROR_RATE", "0.0")),
    "error_endpoint": os.getenv("ERROR_ENDPOINT", "/api/users"),
    "dependency_down": os.getenv("DEPENDENCY_DOWN", ""),
}
changelog = []  # [{ts, lever, old, new, commit, author, message}]
_lock = threading.Lock()

# Each lever maps to a plausible "deploy" so the agent can correlate cause → effect.
DEPLOY = {
    "db_pool_size": ("alice", "Align resource limits with staging environment"),
    "inject_latency_ms": ("bob", "Add synchronous audit-log write to user lookup"),
    "error_rate": ("carol", "Ship new pricing-tier feature flag"),
    "dependency_down": ("dave", "Roll out v2 checkout integration"),
}

# ── metrics (same shape as the Anthropic cookbook, plus a few) ──────────────────
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests",
                        ["service", "method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_milliseconds", "HTTP request latency (ms)",
                            ["service", "method", "endpoint"],
                            buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000])
DB_CONNECTIONS_ACTIVE = Gauge("db_connections_active", "Active DB connections", ["service"])
DB_CONNECTIONS_MAX = Gauge("db_connections_max", "Max DB connections in pool", ["service"])
DB_POOL_SIZE_GAUGE = Gauge("db_pool_size", "Configured DB pool size", ["service"])
DEPENDENCY_UP = Gauge("dependency_up", "Upstream dependency health (1=up, 0=down)", ["dependency"])
INJECTED_LATENCY = Gauge("injected_latency_ms", "Currently injected latency (ms)")
ERROR_RATE_GAUGE = Gauge("error_injection_rate", "Currently injected error rate")

engine = None
SessionLocal = None


def build_engine():
    """(Re)create the DB engine with the current pool size. Called on startup and pool changes."""
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    engine = create_engine(
        DATABASE_URL, poolclass=QueuePool,
        pool_size=cfg["db_pool_size"], max_overflow=0,
        pool_timeout=cfg["db_pool_timeout"], pool_pre_ping=True,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    DB_POOL_SIZE_GAUGE.labels(service=SERVICE_NAME).set(cfg["db_pool_size"])
    DB_CONNECTIONS_MAX.labels(service=SERVICE_NAME).set(cfg["db_pool_size"])
    logger.info(f"DB pool (re)built: size={cfg['db_pool_size']} timeout={cfg['db_pool_timeout']}s")


def refresh_gauges():
    INJECTED_LATENCY.set(cfg["inject_latency_ms"])
    ERROR_RATE_GAUGE.set(cfg["error_rate"])
    down = {d.strip() for d in cfg["dependency_down"].split(",") if d.strip()}
    for dep in KNOWN_DEPENDENCIES:
        DEPENDENCY_UP.labels(dependency=dep).set(0 if dep in down else 1)


def record(service, endpoint, status, start):
    dur_ms = (time.time() - start) * 1000
    REQUEST_COUNT.labels(service=service, method="GET", endpoint=endpoint, status=status).inc()
    REQUEST_LATENCY.labels(service=service, method="GET", endpoint=endpoint).observe(dur_ms)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {SERVICE_NAME}; config={cfg}")
    for i in range(30):
        try:
            build_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            break
        except Exception as e:
            if i < 29:
                logger.warning(f"DB not ready, retrying in 1s... ({e})")
                await asyncio.sleep(1)
            else:
                raise
    refresh_gauges()
    yield
    if engine:
        engine.dispose()


app = FastAPI(title="NavFlow cookbook demo API", lifespan=lifespan)


def update_conn_metric():
    if engine:
        DB_CONNECTIONS_ACTIVE.labels(service=SERVICE_NAME).set(engine.pool.checkedout())


# ── /api/users — DB-bound path; carries db-pool, latency, and error faults ──────
def _sync_list_users():
    with SessionLocal() as session:
        session.execute(text("SELECT pg_sleep(0.2)"))  # slow query → pool pressure when pool is low
        rows = session.execute(text("SELECT id, name, email FROM users LIMIT 100"))
        return [{"id": r[0], "name": r[1], "email": r[2]} for r in rows]


@app.get("/api/users")
async def list_users():
    start, status = time.time(), "200"
    try:
        if cfg["inject_latency_ms"] > 0:
            await asyncio.sleep(cfg["inject_latency_ms"] / 1000.0)  # latency-regression fault

        # forced error-spike fault (a bad feature flag), distinct from a DB problem
        if cfg["error_endpoint"] == "/api/users" and random.random() < cfg["error_rate"]:
            status = "500"
            logger.error("Unhandled exception in /api/users: KeyError 'user_tier' "
                         "(new_pricing feature flag enabled without backfill)")
            raise HTTPException(status_code=500, detail="Internal error: KeyError 'user_tier'")

        if random.random() < 0.01:  # baseline noise
            status = "500"
            raise HTTPException(status_code=500, detail="Transient database error")

        update_conn_metric()
        loop = asyncio.get_running_loop()
        users = await loop.run_in_executor(None, _sync_list_users)
        return {"users": users, "count": len(users)}

    except HTTPException:
        raise
    except (OperationalError, SQLAlchemyTimeoutError) as e:
        status = "500"
        msg = str(e)
        if "QueuePool limit" in msg or "TimeoutError" in msg:
            logger.error(f"Connection pool exhausted: QueuePool limit of size {cfg['db_pool_size']} "
                         f"overflow 0 reached, connection timed out, timeout {cfg['db_pool_timeout']:.2f}")
            raise HTTPException(status_code=500, detail=f"DB pool exhausted (size {cfg['db_pool_size']})")
        logger.error(f"Database error: {msg}")
        raise HTTPException(status_code=500, detail=f"Database error: {msg}")
    finally:
        record("user-svc", "/api/users", status, start)


# ── /api/orders — depends on payments-api; carries the dependency-outage fault ──
@app.get("/api/orders")
async def list_orders():
    start, status = time.time(), "200"
    try:
        down = {d.strip() for d in cfg["dependency_down"].split(",") if d.strip()}
        if "payments-api" in down:
            status = "503"
            logger.error("Upstream dependency 'payments-api' unreachable: connect timeout after 2.00s")
            raise HTTPException(status_code=503, detail="Upstream payments-api unreachable")
        if random.random() < 0.01:
            status = "500"
            raise HTTPException(status_code=500, detail="Transient cache error")
        orders = [{"id": i, "user_id": i % 10 + 1, "total": round(random.uniform(10, 500), 2),
                   "status": "completed"} for i in range(1, 11)]
        return {"orders": orders, "count": len(orders)}
    except HTTPException:
        raise
    finally:
        record("payment-svc", "/api/orders", status, start)


# ── /api/stats — cached control path; mostly healthy ───────────────────────────
@app.get("/api/stats")
async def get_stats():
    start, status = time.time(), "200"
    try:
        if random.random() < 0.01:
            status = "500"
            raise HTTPException(status_code=500, detail="Transient cache error")
        return {"users_count": 1000 + random.randint(0, 50),
                "orders_count": 5000 + random.randint(0, 100),
                "db_pool": {"size": cfg["db_pool_size"]}}
    except HTTPException:
        raise
    finally:
        record("auth-svc", "/api/stats", status, start)


# ── observability + control plane ──────────────────────────────────────────────
@app.get("/health")
async def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "config": cfg}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {e}")


@app.get("/metrics")
async def metrics():
    update_conn_metric()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/config")
async def get_config():
    """Current lever values. The 'config' an SRE agent inspects to find a misconfiguration."""
    return cfg


@app.get("/admin/changelog")
async def get_changelog(limit: int = 20):
    """Recent config changes ('deploys') — the correlation signal for root cause."""
    return {"changes": changelog[-limit:]}


@app.post("/admin/fault")
async def set_fault(body: dict = Body(...)):
    """Inject a fault: {"lever": "...", "value": ...}. Records a synthetic deploy."""
    lever = body.get("lever")
    if lever not in cfg:
        raise HTTPException(status_code=400, detail=f"unknown lever; valid: {list(cfg)}")
    with _lock:
        old = cfg[lever]
        if isinstance(old, bool):
            new = bool(body.get("value"))
        elif isinstance(old, int):
            new = int(body.get("value"))
        elif isinstance(old, float):
            new = float(body.get("value"))
        else:
            new = str(body.get("value"))
        cfg[lever] = new
        if lever in ("db_pool_size", "db_pool_timeout"):
            build_engine()
        refresh_gauges()
        author, message = DEPLOY.get(lever, ("system", f"change {lever}"))
        entry = {"ts": time.time(), "lever": lever, "old": old, "new": new,
                 "commit": secrets.token_hex(4), "author": author, "message": message}
        changelog.append(entry)
        logger.info(f"FAULT injected: {lever} {old} -> {new} (deploy {entry['commit']} by {author})")
    return {"ok": True, "config": cfg, "change": entry}


@app.post("/admin/reset")
async def reset():
    """Restore everything to healthy."""
    with _lock:
        cfg.update({"db_pool_size": 20, "db_pool_timeout": 2.0, "inject_latency_ms": 0,
                    "error_rate": 0.0, "error_endpoint": "/api/users", "dependency_down": ""})
        build_engine()
        refresh_gauges()
        changelog.append({"ts": time.time(), "lever": "reset", "old": None, "new": "healthy",
                          "commit": secrets.token_hex(4), "author": "system", "message": "Restore healthy config"})
        logger.info("Config reset to healthy")
    return {"ok": True, "config": cfg}


@app.get("/")
async def root():
    return {"service": SERVICE_NAME, "config": cfg,
            "faults": ["db_pool_size", "inject_latency_ms", "error_rate", "dependency_down"],
            "endpoints": ["/api/users", "/api/orders", "/api/stats", "/health", "/metrics",
                          "/admin/config", "/admin/changelog", "/admin/fault", "/admin/reset"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
