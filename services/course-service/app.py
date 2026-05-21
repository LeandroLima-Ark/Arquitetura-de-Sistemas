"""
Course Service — Sistema de Matrículas
========================================
Gerencia cursos: listagem, criação e consulta individual.
Expõe métricas no formato Prometheus em /metrics.
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
            "service": "course-service",
            "message": record.getMessage(),
        }
        if hasattr(record, "correlation_id"):
            log_record["correlation_id"] = record.correlation_id
        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("course-service")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# In-memory data (acadêmico)
# ---------------------------------------------------------------------------

COURSES: dict[str, dict] = {
    "c1": {
        "id": "c1",
        "name": "Sistemas Distribuídos",
        "description": "Arquitetura de sistemas distribuídos e middleware",
        "available": True,
        "max_students": 40,
        "enrolled_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    },
    "c2": {
        "id": "c2",
        "name": "Engenharia de Software",
        "description": "Metodologias ágeis e boas práticas de desenvolvimento",
        "available": True,
        "max_students": 35,
        "enrolled_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    },
    "c3": {
        "id": "c3",
        "name": "Banco de Dados",
        "description": "Modelagem relacional e NoSQL",
        "available": False,
        "max_students": 30,
        "enrolled_count": 30,
        "created_at": datetime.now(timezone.utc).isoformat(),
    },
}

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

class ServiceMetrics:
    def __init__(self):
        self.requests_total = 0
        self.errors_total = 0
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
            "# HELP course_service_requests_total Total requests",
            "# TYPE course_service_requests_total counter",
            f"course_service_requests_total {self.requests_total}",
            "# HELP course_service_errors_total Total errors",
            "# TYPE course_service_errors_total counter",
            f"course_service_errors_total {self.errors_total}",
            "# HELP course_service_avg_latency_ms Average latency ms",
            "# TYPE course_service_avg_latency_ms gauge",
            f"course_service_avg_latency_ms {self.avg_latency}",
            "# HELP course_service_courses_total Total courses registered",
            "# TYPE course_service_courses_total gauge",
            f"course_service_courses_total {len(COURSES)}",
        ]
        return "\n".join(lines) + "\n"


svc_metrics = ServiceMetrics()

# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class CourseCreate(BaseModel):
    name: str
    description: str = ""
    available: bool = True
    max_students: int = 30

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Course Service — Sistema de Matrículas")


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
    return {"status": "healthy", "service": "course-service", "courses": len(COURSES)}


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
        "courses_total": len(COURSES),
    }


@app.get("/courses")
async def list_courses(request: Request):
    correlation_id = request.state.correlation_id
    logger.info("Listing all courses", extra={"correlation_id": correlation_id})
    return list(COURSES.values())


@app.get("/courses/{course_id}")
async def get_course(course_id: str, request: Request):
    correlation_id = request.state.correlation_id
    logger.info("Fetching course %s", course_id, extra={"correlation_id": correlation_id})

    course = COURSES.get(course_id)
    if course is None:
        logger.warning("Course %s not found", course_id, extra={"correlation_id": correlation_id})
        return JSONResponse(status_code=404, content={"detail": "Course not found"})

    logger.info("Course %s found", course_id, extra={"correlation_id": correlation_id})
    return course


@app.post("/courses", status_code=201)
async def create_course(payload: CourseCreate, request: Request):
    correlation_id = request.state.correlation_id
    course_id = str(uuid.uuid4())[:8]
    course = {
        "id": course_id,
        "name": payload.name,
        "description": payload.description,
        "available": payload.available,
        "max_students": payload.max_students,
        "enrolled_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    COURSES[course_id] = course
    logger.info(
        "Course %s created: %s", course_id, payload.name,
        extra={"correlation_id": correlation_id},
    )
    return course


@app.patch("/courses/{course_id}")
async def update_course(course_id: str, request: Request):
    correlation_id = request.state.correlation_id
    course = COURSES.get(course_id)
    if course is None:
        return JSONResponse(status_code=404, content={"detail": "Course not found"})

    body = await request.json()
    for field in ("name", "description", "available", "max_students"):
        if field in body:
            course[field] = body[field]

    logger.info("Course %s updated", course_id, extra={"correlation_id": correlation_id})
    return course
