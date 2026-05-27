"""
Middleware API — Sistema de Matrículas
=======================================
Orquestrador central com:
  • Autenticação JWT via auth-service
  • Circuit Breaker (CLOSED / OPEN / HALF-OPEN)
  • Retry com backoff exponencial + timeout
  • Correlation ID em todas as requisições
  • Métricas no formato Prometheus
  • Publicação de eventos no RabbitMQ (assíncrona)
"""

import asyncio
import enum
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from threading import Lock, Thread
from typing import List, Optional

import httpx
import pika
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, PlainTextResponse

# ---------------------------------------------------------------------------
# Structured JSON Logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
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
# Service URLs (from env)
# ---------------------------------------------------------------------------

COURSE_SERVICE_URL    = os.getenv("COURSE_SERVICE_URL",    "http://course-service:8000")
ENROLLMENT_SERVICE_URL = os.getenv("ENROLLMENT_SERVICE_URL", "http://enrollment-service:8000")
AUTH_SERVICE_URL       = os.getenv("AUTH_SERVICE_URL",       "http://auth-service:8000")
RABBITMQ_HOST          = os.getenv("RABBITMQ_HOST",          "rabbitmq")
RABBITMQ_PORT          = int(os.getenv("RABBITMQ_PORT",      "5672"))
RABBITMQ_QUEUE         = "enrollment_notifications"

# ---------------------------------------------------------------------------
# Prometheus-compatible Metrics
# ---------------------------------------------------------------------------

class PrometheusMetrics:
    def __init__(self):
        self._lock = Lock()
        self.requests_total: int = 0
        self.errors_total: int = 0
        self.latencies: List[float] = []
        self.circuit_breaker_open_total: int = 0
        self.retries_total: int = 0
        self.enrollments_created_total: int = 0

    def record_request(self, latency_ms: float, is_error: bool = False):
        with self._lock:
            self.requests_total += 1
            self.latencies.append(latency_ms)
            if is_error:
                self.errors_total += 1

    def record_enrollment(self):
        with self._lock:
            self.enrollments_created_total += 1

    def record_retry(self):
        with self._lock:
            self.retries_total += 1

    def record_circuit_open(self):
        with self._lock:
            self.circuit_breaker_open_total += 1

    @property
    def average_latency_ms(self) -> float:
        with self._lock:
            if not self.latencies:
                return 0.0
            return round(sum(self.latencies) / len(self.latencies), 2)

    def to_prometheus_text(self) -> str:
        with self._lock:
            avg = round(sum(self.latencies) / len(self.latencies), 2) if self.latencies else 0.0
            lines = [
                "# HELP middleware_requests_total Total HTTP requests received",
                "# TYPE middleware_requests_total counter",
                f"middleware_requests_total {self.requests_total}",
                "",
                "# HELP middleware_errors_total Total HTTP errors (4xx/5xx)",
                "# TYPE middleware_errors_total counter",
                f"middleware_errors_total {self.errors_total}",
                "",
                "# HELP middleware_average_latency_ms Average request latency in milliseconds",
                "# TYPE middleware_average_latency_ms gauge",
                f"middleware_average_latency_ms {avg}",
                "",
                "# HELP middleware_enrollments_created_total Total enrollments successfully created",
                "# TYPE middleware_enrollments_created_total counter",
                f"middleware_enrollments_created_total {self.enrollments_created_total}",
                "",
                "# HELP middleware_retries_total Total downstream retries attempted",
                "# TYPE middleware_retries_total counter",
                f"middleware_retries_total {self.retries_total}",
                "",
                "# HELP middleware_circuit_breaker_open_total Times circuit breaker opened",
                "# TYPE middleware_circuit_breaker_open_total counter",
                f"middleware_circuit_breaker_open_total {self.circuit_breaker_open_total}",
            ]
            return "\n".join(lines) + "\n"

    def to_json(self) -> dict:
        with self._lock:
            avg = round(sum(self.latencies) / len(self.latencies), 2) if self.latencies else 0.0
            return {
                "requests_total": self.requests_total,
                "errors_total": self.errors_total,
                "average_latency_ms": avg,
                "enrollments_created_total": self.enrollments_created_total,
                "retries_total": self.retries_total,
                "circuit_breaker_open_total": self.circuit_breaker_open_total,
            }


metrics = PrometheusMetrics()

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CBState(enum.Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Simples circuit breaker por serviço.
    CLOSED  → requisições normais
    OPEN    → falha rápida por `reset_timeout` segundos
    HALF_OPEN → testa uma requisição; se OK, fecha; se falha, reabre
    """

    def __init__(self, name: str, failure_threshold: int = 3, reset_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._state = CBState.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._lock = Lock()

    @property
    def state(self) -> CBState:
        with self._lock:
            if self._state == CBState.OPEN:
                if time.monotonic() - self._opened_at >= self.reset_timeout:
                    self._state = CBState.HALF_OPEN
                    logger.info(
                        "circuit_breaker_half_open",
                        extra={"event": "circuit_breaker_half_open", "correlation_id": None,
                               "status": "warning", "details": {"service": self.name}},
                    )
            return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = CBState.CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._state != CBState.OPEN:
                    self._state = CBState.OPEN
                    self._opened_at = time.monotonic()
                    metrics.record_circuit_open()
                    logger.warning(
                        "circuit_breaker_opened",
                        extra={"event": "circuit_breaker_opened", "correlation_id": None,
                               "status": "warning", "details": {"service": self.name,
                               "failures": self._failure_count}},
                    )

    def is_open(self) -> bool:
        return self.state == CBState.OPEN

    def allow_request(self) -> bool:
        st = self.state
        return st in (CBState.CLOSED, CBState.HALF_OPEN)


# One CB per downstream service
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_cb(service_name: str) -> CircuitBreaker:
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreaker(service_name)
    return _circuit_breakers[service_name]

# ---------------------------------------------------------------------------
# Resilient HTTP (timeout + retry + circuit breaker + fallback)
# ---------------------------------------------------------------------------

TIMEOUT      = 5.0
MAX_RETRIES  = 3
BACKOFF_BASE = 1


async def resilient_request(
    method: str,
    url: str,
    correlation_id: str,
    *,
    json_body: dict | None = None,
    service_name: str = "downstream",
) -> dict:
    cb = get_cb(service_name)

    # Circuit breaker open → fast fail
    if not cb.allow_request():
        logger.warning(
            "circuit_breaker_fast_fail",
            extra={"event": "circuit_breaker_fast_fail", "correlation_id": correlation_id,
                   "status": "warning", "details": {"service": service_name}},
        )
        return {
            "error": "Service unavailable (circuit open)",
            "fallback": True,
            "circuit_open": True,
            "detail": f"{service_name} circuit breaker is OPEN",
        }

    headers = {"X-Correlation-ID": correlation_id}
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.request(method, url, headers=headers, json=json_body)

            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"{service_name} returned {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            if resp.status_code == 404:
                cb.record_success()
                return {"error": "Not found", "status_code": 404}
            if resp.status_code >= 400:
                cb.record_success()
                return {"error": resp.text, "status_code": resp.status_code}

            cb.record_success()
            return resp.json()

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            metrics.record_retry()
            logger.warning(
                "http_retry",
                extra={
                    "event": "http_retry", "correlation_id": correlation_id,
                    "status": "warning",
                    "details": {"service": service_name, "attempt": attempt, "error": str(exc)},
                },
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))

    cb.record_failure()
    logger.error(
        "service_unavailable",
        extra={
            "event": "service_unavailable", "correlation_id": correlation_id,
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
# JWT Auth via auth-service
# ---------------------------------------------------------------------------

async def _validate_jwt(token: str, correlation_id: str) -> dict:
    """Call auth-service to validate the JWT. Returns {valid, role, sub}."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{AUTH_SERVICE_URL}/auth/validate",
                json={"token": token},
                headers={"X-Correlation-ID": correlation_id},
            )
        return resp.json()
    except Exception as exc:
        logger.error(
            "auth_service_unreachable",
            extra={"event": "auth_service_unreachable", "correlation_id": correlation_id,
                   "status": "error", "details": {"error": str(exc)}},
        )
        raise HTTPException(status_code=503, detail="Auth service unavailable")


def require_roles(*allowed_roles: str):
    """FastAPI dependency: validates JWT and checks role."""

    async def _dependency(request: Request) -> str:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        token = auth_header[len("Bearer "):]
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

        result = await _validate_jwt(token, correlation_id)
        if not result.get("valid"):
            raise HTTPException(status_code=401, detail=f"Invalid token: {result.get('error')}")

        role = result.get("role")
        if role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' is not allowed. Required: {allowed_roles}",
            )

        request.state.role = role
        request.state.sub  = result.get("sub")
        return role

    return _dependency

# ---------------------------------------------------------------------------
# RabbitMQ Publisher
# ---------------------------------------------------------------------------

def _publish_event_sync(event: dict, correlation_id: str):
    try:
        credentials = pika.PlainCredentials("guest", "guest")
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials,
            connection_attempts=3, retry_delay=2,
        )
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=RABBITMQ_QUEUE,
            body=json.dumps(event),
            properties=pika.BasicProperties(
                delivery_mode=2,
                message_id=event.get("enrollment_id", str(uuid.uuid4())),  # idempotência
                content_type="application/json",
            ),
        )
        connection.close()
        logger.info(
            "event_published",
            extra={"event": "event_published", "correlation_id": correlation_id,
                   "status": "ok", "details": {"queue": RABBITMQ_QUEUE}},
        )
    except Exception as exc:
        logger.warning(
            "rabbitmq_publish_failed",
            extra={"event": "rabbitmq_publish_failed", "correlation_id": correlation_id,
                   "status": "warning", "details": {"error": str(exc)}},
        )


async def publish_event(event: dict, correlation_id: str):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _publish_event_sync, event, correlation_id)

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Middleware API — Sistema de Matrículas",
    description="Orquestrador central com JWT, Circuit Breaker, Retry e Observabilidade",
    version="2.0.0",
)


@app.middleware("http")
async def metrics_and_correlation_middleware(request: Request, call_next):
    start = time.perf_counter()
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id

    response: Response = await call_next(request)

    latency_ms = (time.perf_counter() - start) * 1000
    is_error = response.status_code >= 400
    metrics.record_request(latency_ms, is_error)
    response.headers["X-Correlation-ID"] = correlation_id

    logger.info(
        "request_handled",
        extra={
            "event": "request_handled", "correlation_id": correlation_id,
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
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "middleware",
        "circuit_breakers": {
            name: cb.state.value
            for name, cb in _circuit_breakers.items()
        },
    }


@app.get("/metrics")
async def get_metrics(request: Request):
    """Expõe métricas no formato Prometheus se Accept = text/plain, senão JSON."""
    accept = request.headers.get("Accept", "")
    if "text/plain" in accept or "application/openmetrics-text" in accept:
        return PlainTextResponse(
            content=metrics.to_prometheus_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    return metrics.to_json()


# -- Auth passthrough --------------------------------------------------------

@app.post("/auth/login")
async def proxy_login(request: Request):
    """Repassa login para o auth-service."""
    body = await request.json()
    correlation_id = request.state.correlation_id
    result = await resilient_request(
        "POST", f"{AUTH_SERVICE_URL}/auth/login", correlation_id,
        json_body=body, service_name="auth-service",
    )
    if result.get("fallback"):
        return JSONResponse(status_code=503, content=result)
    return result


# -- Courses -----------------------------------------------------------------

@app.get("/v1/courses")
async def list_courses(request: Request):
    """Lista todos os cursos disponíveis (público)."""
    correlation_id = request.state.correlation_id
    result = await resilient_request(
        "GET", f"{COURSE_SERVICE_URL}/courses", correlation_id,
        service_name="course-service",
    )
    if isinstance(result, dict) and result.get("fallback"):
        return JSONResponse(status_code=503, content=result)
    return result


@app.get("/v1/courses/{course_id}")
async def get_course(course_id: str, request: Request):
    correlation_id = request.state.correlation_id
    result = await resilient_request(
        "GET", f"{COURSE_SERVICE_URL}/courses/{course_id}", correlation_id,
        service_name="course-service",
    )
    if result.get("fallback"):
        return JSONResponse(status_code=503, content=result)
    if result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
    return result


@app.post("/v1/courses")
async def create_course(
    request: Request,
    role: str = Depends(require_roles("admin")),
):
    """Cria um curso (somente admin)."""
    body = await request.json()
    correlation_id = request.state.correlation_id
    result = await resilient_request(
        "POST", f"{COURSE_SERVICE_URL}/courses", correlation_id,
        json_body=body, service_name="course-service",
    )
    if result.get("fallback"):
        return JSONResponse(status_code=503, content=result)
    return JSONResponse(status_code=201, content=result)


# -- Enrollments -------------------------------------------------------------

@app.post("/v1/enrollments")
async def create_enrollment(
    request: Request,
    role: str = Depends(require_roles("student", "admin")),
):
    correlation_id = request.state.correlation_id
    body = await request.json()
    student_id = body.get("student_id")
    course_id  = body.get("course_id")

    if not student_id or not course_id:
        raise HTTPException(status_code=400, detail="student_id and course_id are required")

    # 1. Verificar curso via course-service
    course_result = await resilient_request(
        "GET", f"{COURSE_SERVICE_URL}/courses/{course_id}", correlation_id,
        service_name="course-service",
    )
    if course_result.get("fallback"):
        return JSONResponse(status_code=503, content=course_result)
    if course_result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
    if not course_result.get("available", True):
        raise HTTPException(status_code=409, detail=f"Course {course_id} is not available")

    # 2. Criar matrícula via enrollment-service
    enrollment_result = await resilient_request(
        "POST", f"{ENROLLMENT_SERVICE_URL}/enrollments", correlation_id,
        json_body={"student_id": student_id, "course_id": course_id},
        service_name="enrollment-service",
    )
    if enrollment_result.get("fallback"):
        return JSONResponse(status_code=503, content=enrollment_result)
    if enrollment_result.get("status_code") == 409:
        raise HTTPException(status_code=409, detail="Student already enrolled in this course")

    enrollment_id = enrollment_result.get("id", str(uuid.uuid4()))

    # 3. Publicar evento (fire-and-forget — tolerância a falha do notification-worker)
    event = {
        "event": "enrollment.created",
        "student_id": student_id,
        "course_id": course_id,
        "enrollment_id": enrollment_id,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await publish_event(event, correlation_id)
    metrics.record_enrollment()

    logger.info(
        "enrollment_created",
        extra={
            "event": "enrollment_created", "correlation_id": correlation_id,
            "status": "ok",
            "details": {"student_id": student_id, "course_id": course_id,
                        "enrollment_id": enrollment_id},
        },
    )

    return JSONResponse(
        status_code=201,
        content={
            "message": "Enrollment created successfully",
            "enrollment": {
                "enrollment_id": enrollment_id,
                "student_id": student_id,
                "course_id": course_id,
            },
            "correlation_id": correlation_id,
        },
    )


@app.get("/v1/enrollments")
async def list_enrollments(
    request: Request,
    role: str = Depends(require_roles("admin")),
):
    correlation_id = request.state.correlation_id
    result = await resilient_request(
        "GET", f"{ENROLLMENT_SERVICE_URL}/enrollments", correlation_id,
        service_name="enrollment-service",
    )
    if isinstance(result, dict) and result.get("fallback"):
        return JSONResponse(status_code=503, content=result)
    return {"enrollments": result, "correlation_id": correlation_id}


@app.get("/v1/enrollments/{enrollment_id}")
async def get_enrollment(
    enrollment_id: str,
    request: Request,
    role: str = Depends(require_roles("student", "admin")),
):
    correlation_id = request.state.correlation_id
    result = await resilient_request(
        "GET", f"{ENROLLMENT_SERVICE_URL}/enrollments/{enrollment_id}", correlation_id,
        service_name="enrollment-service",
    )
    if result.get("fallback"):
        return JSONResponse(status_code=503, content=result)
    if result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return result
