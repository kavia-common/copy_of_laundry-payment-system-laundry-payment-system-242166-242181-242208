import os
from typing import List, Optional

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Internal helper to read environment variables with an optional default."""
    value = os.getenv(name, default)
    if value is None:
        return None
    # Allow env files to include quoted values.
    return value.strip().strip('"').strip("'")


def _build_postgres_dsn() -> str:
    """Build a PostgreSQL DSN from provided POSTGRES_* env vars.

    The platform provides these variables (do not rename):
      - POSTGRES_URL (preferred, may be full DSN)
      - POSTGRES_USER
      - POSTGRES_PASSWORD
      - POSTGRES_DB
      - POSTGRES_PORT
    """
    postgres_url = _get_env("POSTGRES_URL")
    if postgres_url:
        # Many environments provide full DSN already.
        return postgres_url

    user = _get_env("POSTGRES_USER", "appuser")
    password = _get_env("POSTGRES_PASSWORD", "password")
    db = _get_env("POSTGRES_DB", "postgres")
    port = _get_env("POSTGRES_PORT", "5432")

    # Host is the local DB container; in this template it's localhost with a nonstandard port.
    host = "localhost"
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _parse_allowed_origins() -> List[str]:
    """Parse comma-separated ALLOWED_ORIGINS env var into a list."""
    allowed_origins = _get_env("ALLOWED_ORIGINS", "*")
    if not allowed_origins:
        return ["*"]
    allowed_origins = allowed_origins.strip()
    if allowed_origins == "*":
        return ["*"]
    return [o.strip() for o in allowed_origins.split(",") if o.strip()]


def _parse_allowed_methods() -> List[str]:
    """Parse comma-separated ALLOWED_METHODS env var into a list."""
    value = _get_env("ALLOWED_METHODS", "*")
    if not value or value.strip() == "*":
        return ["*"]
    return [m.strip() for m in value.split(",") if m.strip()]


def _parse_allowed_headers() -> List[str]:
    """Parse comma-separated ALLOWED_HEADERS env var into a list."""
    value = _get_env("ALLOWED_HEADERS", "*")
    if not value or value.strip() == "*":
        return ["*"]
    return [h.strip() for h in value.split(",") if h.strip()]


openapi_tags = [
    {"name": "Health", "description": "Service health and readiness checks."},
    {"name": "Machines", "description": "Laundry machine listing and status endpoints."},
]


app = FastAPI(
    title="Laundry Payment System API",
    description=(
        "Backend API for a tokenized laundry payment system.\n\n"
        "Notes:\n"
        "- DB connection is configured via POSTGRES_* environment variables.\n"
        "- This template currently exposes a minimal set of endpoints to verify end-to-end wiring."
    ),
    version="0.1.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=True,
    allow_methods=_parse_allowed_methods(),
    allow_headers=_parse_allowed_headers(),
)

# Stored on app.state so routes can access it.
app.state.pg_pool = None


class MachineOut(BaseModel):
    """Machine DTO returned by API."""

    id: int = Field(..., description="Machine ID.")
    location: str = Field(..., description="Location name or code for the machine.")
    name: str = Field(..., description="Human-friendly machine name/label.")
    type: str = Field(..., description="Machine type (e.g., washer, dryer).")
    status: str = Field(..., description="Current status (e.g., available, running, offline).")


@app.on_event("startup")
async def _startup() -> None:
    """Create asyncpg pool and ensure minimal schema exists."""
    dsn = _build_postgres_dsn()
    # Keep pool small for template usage.
    app.state.pg_pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)

    async with app.state.pg_pool.acquire() as conn:
        # Minimal schema for bootstrapping/runnability.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS machines (
              id SERIAL PRIMARY KEY,
              location TEXT NOT NULL DEFAULT 'default',
              name TEXT NOT NULL,
              type TEXT NOT NULL CHECK (type IN ('washer','dryer')),
              status TEXT NOT NULL DEFAULT 'available'
            );
            """
        )

        # Seed a few rows if table is empty.
        count = await conn.fetchval("SELECT COUNT(*) FROM machines;")
        if count == 0:
            await conn.execute(
                """
                INSERT INTO machines (location, name, type, status)
                VALUES
                  ('default', 'Washer 1', 'washer', 'available'),
                  ('default', 'Washer 2', 'washer', 'available'),
                  ('default', 'Dryer 1', 'dryer', 'available');
                """
            )


@app.on_event("shutdown")
async def _shutdown() -> None:
    """Close asyncpg pool on shutdown."""
    pool = app.state.pg_pool
    if pool is not None:
        await pool.close()


# PUBLIC_INTERFACE
@app.get(
    "/",
    tags=["Health"],
    summary="Basic health check",
    description="Returns a simple message indicating the API process is running.",
    operation_id="health_root",
)
def health_root():
    """Basic liveness check.

    Returns:
        JSON object with a short message.
    """
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.get(
    "/healthz",
    tags=["Health"],
    summary="Readiness check",
    description="Verifies the API is running and can reach the PostgreSQL database.",
    operation_id="health_ready",
)
async def health_ready():
    """Readiness check (includes DB connectivity).

    Returns:
        JSON object containing DB version and status.
    """
    pool = app.state.pg_pool
    if pool is None:
        return {"status": "starting", "db": "not_initialized"}

    async with pool.acquire() as conn:
        version = await conn.fetchval("SELECT version();")
        return {"status": "ok", "db": {"reachable": True, "version": version}}


# PUBLIC_INTERFACE
@app.get(
    "/api/machines",
    response_model=List[MachineOut],
    tags=["Machines"],
    summary="List machines",
    description="Returns a list of machines currently known to the system (template data).",
    operation_id="list_machines",
)
async def list_machines():
    """List machines.

    Returns:
        A list of machines from the database.
    """
    pool = app.state.pg_pool
    if pool is None:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, location, name, type, status FROM machines ORDER BY id ASC;"
        )
        return [MachineOut(**dict(r)) for r in rows]
