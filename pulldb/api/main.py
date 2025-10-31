"""FastAPI-based API service prototype for pullDB.

Defines minimal endpoints (`/api/health`, `/api/status`, `/api/jobs`) as
placeholders. Real implementations will add MySQL integration and validation
logic according to design documentation.
"""

from __future__ import annotations

import fastapi
import pydantic
import uvicorn


app = fastapi.FastAPI(title="pullDB API Service", version="0.0.1.dev0")


class JobRequest(pydantic.BaseModel):
    """Incoming job submission payload.

    Attributes:
        user: Requesting username.
        customer: Customer identifier (mutually exclusive with `qatemplate`).
        qatemplate: QA template restore flag (mutually exclusive with
            `customer`).
        dbhost: Optional override for target host.
        overwrite: Allow restoring over existing target without prompt.
    """

    user: str
    customer: str | None = None
    qatemplate: bool | None = None
    dbhost: str | None = None
    overwrite: bool | None = None

    def validate_mutual_exclusive(self) -> None:
        """Ensure exactly one of customer or qatemplate is specified."""
        if self.customer and self.qatemplate:
            raise ValueError("Specify either customer or qatemplate, not both")
        if not self.customer and not self.qatemplate:
            raise ValueError("Must specify customer=<id> or qatemplate flag")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}


@app.get("/api/status")
async def status() -> dict[str, int | str]:
    """Prototype status endpoint with placeholder metrics."""
    return {"queue_depth": 0, "active_restores": 0, "service": "api"}


@app.post("/api/jobs")
async def submit_job(req: JobRequest) -> dict[str, str]:
    """Accept a restore job request (placeholder)."""
    try:
        req.validate_mutual_exclusive()
    except ValueError as e:
        raise fastapi.HTTPException(status_code=400, detail=str(e)) from e
    return {"job_id": "stub-job-id", "status": "queued"}


def create_app() -> fastapi.FastAPI:
    """Return configured FastAPI application instance."""
    return app


def main(argv: list[str] | None = None) -> int:
    """Run API service with Uvicorn HTTP server."""
    uvicorn.run(app, host="0.0.0.0", port=8080)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
