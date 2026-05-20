import json
import logging
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Structured JSON logging
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
# In-memory data
# ---------------------------------------------------------------------------

COURSES = {
    "c1": {"id": "c1", "name": "Sistemas Distribuídos", "available": True},
    "c2": {"id": "c2", "name": "Engenharia de Software", "available": True},
    "c3": {"id": "c3", "name": "Banco de Dados", "available": False},
}

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Course Service")


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "course-service"}


@app.get("/courses/{course_id}")
async def get_course(course_id: str, request: Request):
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.info(
        "Fetching course %s", course_id, extra={"correlation_id": correlation_id}
    )

    course = COURSES.get(course_id)
    if course is None:
        logger.warning(
            "Course %s not found", course_id, extra={"correlation_id": correlation_id}
        )
        return JSONResponse(status_code=404, content={"detail": "Course not found"})

    logger.info(
        "Course %s found", course_id, extra={"correlation_id": correlation_id}
    )
    return course
