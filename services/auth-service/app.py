"""
Auth Service — Sistema de Matrículas
======================================
Serviço de autenticação independente que emite e valida tokens JWT.

Endpoints:
  POST /auth/login    — Autentica usuário, retorna JWT
  POST /auth/validate — Valida JWT, retorna role e subject
  GET  /health        — Healthcheck
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Structured JSON Logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": "auth-service",
            "message": record.getMessage(),
        }
        if hasattr(record, "correlation_id"):
            log_record["correlation_id"] = record.correlation_id
        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("auth-service")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# JWT Config
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60

# ---------------------------------------------------------------------------
# Password Hashing
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# In-memory Users (acadêmico — em produção usar banco de dados)
# ---------------------------------------------------------------------------

# Senhas pré-hasheadas com bcrypt
USERS = {
    "aluno": {
        "username": "aluno",
        "hashed_password": pwd_context.hash("senha123"),
        "role": "student",
    },
    "admin": {
        "username": "admin",
        "hashed_password": pwd_context.hash("admin123"),
        "role": "admin",
    },
    # Aliases para compatibilidade com README
    "student": {
        "username": "student",
        "hashed_password": pwd_context.hash("senha123"),
        "role": "student",
    },
}

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class ValidateRequest(BaseModel):
    token: str

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def create_jwt(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRATION_MINUTES),
        "jti": str(uuid.uuid4()),  # JWT ID para idempotência
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Auth Service — Sistema de Matrículas")


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# -- Health ------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "auth-service"}


# -- POST /auth/login --------------------------------------------------------

@app.post("/auth/login")
async def login(payload: LoginRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    user = USERS.get(payload.username)

    if not user or not pwd_context.verify(payload.password, user["hashed_password"]):
        logger.warning(
            "Login failed for user %s", payload.username,
            extra={"correlation_id": correlation_id},
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_jwt(user["username"], user["role"])

    logger.info(
        "Login successful for user %s (role=%s)", user["username"], user["role"],
        extra={"correlation_id": correlation_id},
    )

    return {
        "access_token": token,
        "token_type": "Bearer",
        "role": user["role"],
        "expires_in": JWT_EXPIRATION_MINUTES * 60,
    }


# -- POST /auth/validate -----------------------------------------------------

@app.post("/auth/validate")
async def validate_token(payload: ValidateRequest, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "unknown")

    try:
        decoded = decode_jwt(payload.token)
        logger.info(
            "Token validated for sub=%s role=%s", decoded.get("sub"), decoded.get("role"),
            extra={"correlation_id": correlation_id},
        )
        return {
            "valid": True,
            "sub": decoded.get("sub"),
            "role": decoded.get("role"),
        }
    except JWTError as e:
        logger.warning(
            "Token validation failed: %s", str(e),
            extra={"correlation_id": correlation_id},
        )
        return {"valid": False, "error": str(e)}
