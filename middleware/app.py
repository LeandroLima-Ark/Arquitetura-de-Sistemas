"""
Middleware API – Enrollment System
===================================
Central orchestrator that authenticates requests, calls downstream
services (course-service, enrollment-service) with resilience patterns,
publishes events to RabbitMQ, and exposes health / metrics endpoints.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from threading import Thread
from typing import List

import httpx
import pika
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Structured JSON Logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "service": "middleware",
            "event": getattr(record, "event", record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None),
            "status": getattr(record, "status", record.levelname.lower()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": getattr(record, "details", None),
        }
        return json.dumps(log_entry, default=str)


logger = logging.getLogger("middleware")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(JSONFormatter())
logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# In-memory Metrics
# ---------------------------------------------------------------------------

class Metrics:
    def __init__(self):
        self.requests_total: int = 0
        self.errors_total: int = 0
        self.latencies: List[float] = []

    @property
    def average_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        return round(sum(self.latencies) / len(self.latencies), 2)

    def record_request(self, latency_ms: float, is_error: bool = False):
        self.requests_total += 1
        self.latencies.append(latency_ms)
        if is_error:
            self.errors_total += 1


metrics = Metrics()

# ---------------------------------------------------------------------------
# Token-based Auth
# ---------------------------------------------------------------------------

TOKEN_MAP = {
    "student-token": "student",
    "admin-token": "admin",
}


def _extract_role(request: Request) -> str:
    """Return the role string or raise 401."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = auth_header[len("Bearer "):]
    role = TOKEN_MAP.get(token)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return role


def require_roles(*allowed_roles: str):
    """FastAPI dependency that checks the caller's role."""

    def _dependency(request: Request) -> str:
        role = _extract_role(request)
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return role

    return _dependency

# ---------------------------------------------------------------------------
# Correlation ID helper
# ---------------------------------------------------------------------------

def get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-ID") or str(uuid.uuid4())

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Middleware API – Enrollment System")

# -- Middleware: metrics + correlation id in response -------------------------

@app.middleware("http")
async def metrics_and_correlation_middleware(request: Request, call_next):
    start = time.perf_counter()
    correlation_id = get_correlation_id(request)

    # Stash for downstream usage inside route handlers
    request.state.correlation_id = correlation_id

    response: Response = await call_next(request)

    latency_ms = (time.perf_counter() - start) * 1000
    is_error = response.status_code >= 400
    metrics.record_request(latency_ms, is_error)

    response.headers["X-Correlation-ID"] = correlation_id

    logger.info(
        "request_handled",
        extra={
            "event": "request_handled",
            "correlation_id": correlation_id,
            "status": response.status_code,
            "details": {
                "method": request.method,
                "path": str(request.url.path),
                "latency_ms": round(latency_ms, 2),
            },
        },
    )
    return response

# ---------------------------------------------------------------------------
# Resilient HTTP helper (timeout + retry + fallback)
# ---------------------------------------------------------------------------

TIMEOUT = 5.0  # seconds
MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds


async def resilient_request(
    method: str,
    url: str,
    correlation_id: str,
    *,
    json_body: dict | None = None,
    service_name: str = "downstream",
) -> dict:
    """
    Perform an HTTP request with:
      • 5-second timeout
      • Up to 3 retries with exponential backoff for connection errors / 5xx
      • Graceful fallback dict when all retries are exhausted
    """
    headers = {"X-Correlation-ID": correlation_id}
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.request(
                    method, url, headers=headers, json=json_body
                )

            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"{service_name} returned {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            if resp.status_code == 404:
                return {"error": "Not found", "status_code": 404}

            if resp.status_code >= 400:
                return {"error": resp.text, "status_code": resp.status_code}

            return resp.json()

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            logger.warning(
                "http_retry",
                extra={
                    "event": "http_retry",
                    "correlation_id": correlation_id,
                    "status": "warning",
                    "details": {
                        "service": service_name,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                },
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))

    # All retries exhausted → fallback
    logger.error(
        "service_unavailable",
        extra={
            "event": "service_unavailable",
            "correlation_id": correlation_id,
            "status": "error",
            "details": {"service": service_name, "last_error": str(last_exc)},
        },
    )
    return {
        "error": "Service unavailable",
        "fallback": True,
        "detail": f"{service_name} is currently unavailable",
    }

# ---------------------------------------------------------------------------
# RabbitMQ Publisher (best-effort, non-blocking)
# ---------------------------------------------------------------------------

RABBITMQ_HOST = "rabbitmq"
RABBITMQ_PORT = 5672
RABBITMQ_QUEUE = "enrollment_notifications"


def _publish_event_sync(event: dict, correlation_id: str):
    """Publish a message to RabbitMQ (runs in a worker thread)."""
    try:
        credentials = pika.PlainCredentials("guest", "guest")
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials
        )
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=RABBITMQ_QUEUE,
            body=json.dumps(event),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        connection.close()
        logger.info(
            "event_published",
            extra={
                "event": "event_published",
                "correlation_id": correlation_id,
                "status": "ok",
                "details": {"queue": RABBITMQ_QUEUE},
            },
        )
    except Exception as exc:
        logger.warning(
            "rabbitmq_publish_failed",
            extra={
                "event": "rabbitmq_publish_failed",
                "correlation_id": correlation_id,
                "status": "warning",
                "details": {"error": str(exc)},
            },
        )


async def publish_event(event: dict, correlation_id: str):
    """Fire-and-forget publish in a background thread so we don't block the event loop."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _publish_event_sync, event, correlation_id)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# -- Health ------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "middleware"}


# -- Metrics -----------------------------------------------------------------

@app.get("/metrics")
async def get_metrics():
    return {
        "requests_total": metrics.requests_total,
        "errors_total": metrics.errors_total,
        "average_latency_ms": metrics.average_latency_ms,
    }


# -- POST /v1/enrollments ---------------------------------------------------

@app.post("/v1/enrollments")
async def create_enrollment(
    request: Request,
    role: str = Depends(require_roles("student", "admin")),
):
    correlation_id: str = request.state.correlation_id
    body = await request.json()
    student_id = body.get("student_id")
    course_id = body.get("course_id")

    if not student_id or not course_id:
        raise HTTPException(
            status_code=400, detail="student_id and course_id are required"
        )

    # 1. Verify course exists via course-service
    course_url = f"http://course-service:8000/courses/{course_id}"
    course_result = await resilient_request(
        "GET", course_url, correlation_id, service_name="course-service"
    )
    if course_result.get("fallback"):
        return JSONResponse(status_code=503, content=course_result)
    if course_result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")

    # 2. Create enrollment via enrollment-service
    enrollment_url = "http://enrollment-service:8000/enrollments"
    enrollment_payload = {"student_id": student_id, "course_id": course_id}
    enrollment_result = await resilient_request(
        "POST",
        enrollment_url,
        correlation_id,
        json_body=enrollment_payload,
        service_name="enrollment-service",
    )
    if enrollment_result.get("fallback"):
        return JSONResponse(status_code=503, content=enrollment_result)

    enrollment_id = enrollment_result.get("id", enrollment_result.get("enrollment_id", str(uuid.uuid4())))

    # 3. Publish event (best-effort)
    event = {
        "event": "enrollment.created",
        "student_id": student_id,
        "course_id": course_id,
        "enrollment_id": enrollment_id,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await publish_event(event, correlation_id)

    logger.info(
        "enrollment_created",
        extra={
            "event": "enrollment_created",
            "correlation_id": correlation_id,
            "status": "ok",
            "details": {
                "student_id": student_id,
                "course_id": course_id,
                "enrollment_id": enrollment_id,
            },
        },
    )

    return {
        "message": "Enrollment created successfully",
        "enrollment": {
            "enrollment_id": enrollment_id,
            "student_id": student_id,
            "course_id": course_id,
        },
        "correlation_id": correlation_id,
    }


# -- GET /v1/admin/enrollments ----------------------------------------------

@app.get("/v1/admin/enrollments")
async def list_enrollments(
    request: Request,
    role: str = Depends(require_roles("admin")),
):
    correlation_id: str = request.state.correlation_id

    enrollment_url = "http://enrollment-service:8000/enrollments"
    result = await resilient_request(
        "GET", enrollment_url, correlation_id, service_name="enrollment-service"
    )
    if result.get("fallback"):
        return JSONResponse(status_code=503, content=result)

    return {"enrollments": result, "correlation_id": correlation_id}
