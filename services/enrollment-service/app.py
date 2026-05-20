import json
import logging
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Structured JSON logging
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

# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class EnrollmentRequest(BaseModel):
    student_id: str
    course_id: str

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Enrollment Service")


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "enrollment-service"}


@app.post("/enrollments", status_code=201)
async def create_enrollment(payload: EnrollmentRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", None)

    enrollment = {
        "id": str(uuid.uuid4()),
        "student_id": payload.student_id,
        "course_id": payload.course_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    ENROLLMENTS.append(enrollment)

    logger.info(
        "Enrollment %s created for student %s in course %s",
        enrollment["id"],
        payload.student_id,
        payload.course_id,
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
    logger.info(
        "Fetching enrollment %s", enrollment_id,
        extra={"correlation_id": correlation_id},
    )

    for enrollment in ENROLLMENTS:
        if enrollment["id"] == enrollment_id:
            return enrollment

    logger.warning(
        "Enrollment %s not found", enrollment_id,
        extra={"correlation_id": correlation_id},
    )
    return JSONResponse(status_code=404, content={"detail": "Enrollment not found"})
