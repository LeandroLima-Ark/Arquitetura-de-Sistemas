#!/usr/bin/env python3
"""
Script de demo para apresentação ao vivo.
Execute: python demo.py
"""

import json
import subprocess
import sys
import time

import urllib.request
import urllib.error

BASE = "http://localhost:8000"


def req(method: str, path: str, body=None, token=None, correlation_id=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, {"error": str(e)}


def banner(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def step(desc: str, status: int, body: dict):
    ok = "✅" if status < 400 else "❌"
    print(f"\n{ok} {desc}")
    print(f"   Status: {status}")
    print(f"   Body  : {json.dumps(body, indent=2, ensure_ascii=False)[:300]}")


# ─── Demo ──────────────────────────────────────────────────────────────────

banner("DEMO — Sistema de Matrículas Distribuído")

# 1. Health check
banner("1. Health Checks")
s, b = req("GET", "/health")
step("Middleware health", s, b)
s, b = req("GET", "/v1/courses")
step("Listar cursos (público)", s, b)

# 2. Login
banner("2. Autenticação JWT")
s, b = req("POST", "/auth/login", {"username": "aluno", "password": "senha123"})
step("Login como aluno", s, b)
student_token = b.get("access_token", "")

s, b = req("POST", "/auth/login", {"username": "admin", "password": "admin123"})
step("Login como admin", s, b)
admin_token = b.get("access_token", "")

# 3. Matrícula
banner("3. Fluxo de Matrícula (síncrono + assíncrono)")
s, b = req(
    "POST", "/v1/enrollments",
    {"student_id": "aluno-demo-01", "course_id": "c1"},
    token=student_token,
    correlation_id="demo-correlation-001"
)
step("Matricular aluno no curso c1", s, b)

# 4. Idempotência
banner("4. Idempotência — Matrícula duplicada deve retornar 409")
s, b = req(
    "POST", "/v1/enrollments",
    {"student_id": "aluno-demo-01", "course_id": "c1"},
    token=student_token,
    correlation_id="demo-correlation-002"
)
step("Tentar matrícula duplicada (deve ser 409)", s, b)

# 5. Admin: listar matrículas
banner("5. Admin — Listar todas as matrículas")
s, b = req("GET", "/v1/enrollments", token=admin_token)
step("Listar matrículas (admin)", s, b)

# 6. Métricas
banner("6. Métricas do Sistema")
s, b = req("GET", "/metrics")
step("Métricas do middleware", s, b)

# 7. Simulação de falha
banner("7. Tolerância a Falhas — Circuit Breaker")
print("\n  → Parando course-service para demonstrar circuit breaker...")
print("     Execute: docker compose stop course-service")
print("     Depois tente: POST /v1/enrollments")
print("     Você verá 3 retries nos logs e depois circuit breaker OPEN")

banner("DEMO CONCLUÍDA ✅")
print("\n  Acesse:")
print("  • API Docs:  http://localhost:8000/docs")
print("  • Grafana:   http://localhost:3000  (admin/admin)")
print("  • Prometheus:http://localhost:9090")
print("  • RabbitMQ:  http://localhost:15672 (guest/guest)")
