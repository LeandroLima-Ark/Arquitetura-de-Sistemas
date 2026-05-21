"""
Enrollment Service — Sistema de Matrículas
===========================================
Gerencia matrículas com verificação de idempotência.
Retorna 409 se aluno já estiver matriculado no curso.
Expõe métricas Prometheus em /metrics.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Structured JSON Logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": "enrollment-service",
            "message": record.getMessage(),
        }
        if hasattr(record, "correlation_id"):
            log_record["correlation_id"] = record.correlation_id
        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("enrollment-service")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# In-memory data
# ---------------------------------------------------------------------------

ENROLLMENTS: list[dict] = []

# Índice de idempotência: (student_id, course_id) → enrollment_id
_enrollment_index: dict[tuple, str] = {}

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

class ServiceMetrics:
    def __init__(self):
        self.requests_total = 0
        self.errors_total = 0
        self.duplicates_rejected = 0
        self.latencies: list[float] = []

    def record(self, latency_ms: float, error: bool = False):
        self.requests_total += 1
        self.latencies.append(latency_ms)
        if error:
            self.errors_total += 1

    @property
    def avg_latency(self) -> float:
        return round(sum(self.latencies) / len(self.latencies), 2) if self.latencies else 0.0

    def to_prometheus(self) -> str:
        lines = [
            "# HELP enrollment_service_requests_total Total requests",
            "# TYPE enrollment_service_requests_total counter",
            f"enrollment_service_requests_total {self.requests_total}",
            "# HELP enrollment_service_errors_total Total errors",
            "# TYPE enrollment_service_errors_total counter",
            f"enrollment_service_errors_total {self.errors_total}",
            "# HELP enrollment_service_avg_latency_ms Average latency ms",
            "# TYPE enrollment_service_avg_latency_ms gauge",
            f"enrollment_service_avg_latency_ms {self.avg_latency}",
            "# HELP enrollment_service_enrollments_total Total enrollments stored",
            "# TYPE enrollment_service_enrollments_total gauge",
            f"enrollment_service_enrollments_total {len(ENROLLMENTS)}",
            "# HELP enrollment_service_duplicates_rejected_total Duplicate enrollments rejected",
            "# TYPE enrollment_service_duplicates_rejected_total counter",
            f"enrollment_service_duplicates_rejected_total {self.duplicates_rejected}",
        ]
        return "\n".join(lines) + "\n"


svc_metrics = ServiceMetrics()

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EnrollmentRequest(BaseModel):
    student_id: str
    course_id: str

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Enrollment Service — Sistema de Matrículas")


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    start = time.perf_counter()
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id

    response = await call_next(request)

    latency_ms = (time.perf_counter() - start) * 1000
    svc_metrics.record(latency_ms, error=response.status_code >= 400)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "enrollment-service",
        "enrollments": len(ENROLLMENTS),
    }


@app.get("/metrics")
async def metrics_endpoint(request: Request):
    accept = request.headers.get("Accept", "")
    if "text/plain" in accept or "application/openmetrics-text" in accept:
        return PlainTextResponse(
            content=svc_metrics.to_prometheus(),
            media_type="text/plain; version=0.0.4",
        )
    return {
        "requests_total": svc_metrics.requests_total,
        "errors_total": svc_metrics.errors_total,
        "avg_latency_ms": svc_metrics.avg_latency,
        "enrollments_total": len(ENROLLMENTS),
        "duplicates_rejected": svc_metrics.duplicates_rejected,
    }


@app.post("/enrollments", status_code=201)
async def create_enrollment(payload: EnrollmentRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", None)

    # --- Idempotência: verificar duplicata ---
    key = (payload.student_id, payload.course_id)
    if key in _enrollment_index:
        existing_id = _enrollment_index[key]
        svc_metrics.duplicates_rejected += 1
        logger.warning(
            "Duplicate enrollment rejected for student %s in course %s (existing: %s)",
            payload.student_id, payload.course_id, existing_id,
            extra={"correlation_id": correlation_id},
        )
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Student already enrolled in this course",
                "existing_enrollment_id": existing_id,
            },
        )

    # --- Criar matrícula ---
    enrollment = {
        "id": str(uuid.uuid4()),
        "student_id": payload.student_id,
        "course_id": payload.course_id,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }
    ENROLLMENTS.append(enrollment)
    _enrollment_index[key] = enrollment["id"]

    logger.info(
        "Enrollment %s created for student %s in course %s",
        enrollment["id"], payload.student_id, payload.course_id,
        extra={"correlation_id": correlation_id},
    )
    return enrollment


@app.get("/enrollments")
async def list_enrollments(request: Request):
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.info(
        "Listing all enrollments (%d total)", len(ENROLLMENTS),
        extra={"correlation_id": correlation_id},
    )
    return ENROLLMENTS


@app.get("/enrollments/{enrollment_id}")
async def get_enrollment(enrollment_id: str, request: Request):
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.info("Fetching enrollment %s", enrollment_id, extra={"correlation_id": correlation_id})

    for enrollment in ENROLLMENTS:
        if enrollment["id"] == enrollment_id:
            return enrollment

    logger.warning("Enrollment %s not found", enrollment_id, extra={"correlation_id": correlation_id})
    return JSONResponse(status_code=404, content={"detail": "Enrollment not found"})
