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
    
    cmd = f"curl -X {method} {url}"
    if token:
        cmd += f" -H \"Authorization: Bearer <TOKEN>\""
    if body:
        cmd += " -H \"Content-Type: application/json\""
        cmd += f" -d '{json.dumps(body, ensure_ascii=False)}'"
    print(f"\n   💻 Comando: {cmd}")

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
    print(f"   Body  : {json.dumps(body, indent=2, ensure_ascii=False)}")


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
run_id = int(time.time())
student_id = f"aluno-demo-{run_id}"

s, b = req(
    "POST", "/v1/enrollments",
    {"student_id": student_id, "course_id": "c1"},
    token=student_token,
    correlation_id=f"demo-correlation-{run_id}-1"
)
step(f"Matricular aluno no curso c1 ({student_id})", s, b)

# 4. Idempotência
banner("4. Idempotência — Matrícula duplicada deve retornar 409")
s, b = req(
    "POST", "/v1/enrollments",
    {"student_id": student_id, "course_id": "c1"},
    token=student_token,
    correlation_id=f"demo-correlation-{run_id}-2"
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
    
    cmd = f"curl -X {method} {url}"
    if token:
        cmd += f" -H \"Authorization: Bearer <TOKEN>\""
    if body:
        cmd += " -H \"Content-Type: application/json\""
        cmd += f" -d '{json.dumps(body, ensure_ascii=False)}'"
    print(f"\n   💻 Comando: {cmd}")

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
    print(f"   Body  : {json.dumps(body, indent=2, ensure_ascii=False)}")


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
run_id = int(time.time())
student_id = f"aluno-demo-{run_id}"

s, b = req(
    "POST", "/v1/enrollments",
    {"student_id": student_id, "course_id": "c1"},
    token=student_token,
    correlation_id=f"demo-correlation-{run_id}-1"
)
step(f"Matricular aluno no curso c1 ({student_id})", s, b)

# 4. Idempotência
banner("4. Idempotência — Matrícula duplicada deve retornar 409")
s, b = req(
    "POST", "/v1/enrollments",
    {"student_id": student_id, "course_id": "c1"},
    token=student_token,
    correlation_id=f"demo-correlation-{run_id}-2"
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
print("  O Circuit Breaker protege o sistema contra falhas em cascata.")
print("  Quando um serviço cai, o sistema tenta reconectar (Retries).")
print("  Se falhar repetidamente, o 'disjuntor' abre e bloqueia novas requisições imediatamente.")
print("\n  👉 Parando o Course Service automaticamente (docker compose stop course-service)...")
subprocess.run(["docker", "compose", "stop", "course-service"], check=False)
print("  Serviço parado!")
time.sleep(2)

print("\n  Fazendo requisições... As 3 primeiras vão demorar mais por causa das tentativas (retries).")
for i in range(1, 4):
    print(f"\n  -- Tentativa {i} --")
    s, b = req("POST", "/v1/enrollments", {"student_id": f"aluno-cb-{i}", "course_id": "c1"}, token=student_token)
    step(f"Tentativa {i} (Falha + Retries)", s, b)

print("\n  O limite de falhas foi atingido. O Circuit Breaker abriu!")
print("  A próxima requisição falhará IMEDIATAMENTE (Fail Fast):")
s, b = req("POST", "/v1/enrollments", {"student_id": f"aluno-cb-4", "course_id": "c1"}, token=student_token)
step("Tentativa 4 (Circuit Breaker OPEN - Falha Imediata)", s, b)

print("\n  Vamos verificar o status de saúde do sistema agora:")
s, b = req("GET", "/health")
step("Health Check (Veja o status 'open' no course-service)", s, b)

print("\n  👉 Ligando o Course Service novamente (docker compose start course-service)...")
subprocess.run(["docker", "compose", "start", "course-service"], check=False)
print("  Serviço iniciado! O Circuit Breaker voltará ao normal (closed) em breve.")

banner("DEMO CONCLUÍDA ✅")
print("\n  Acesse:")
print("  • API Docs:  http://localhost:8000/docs")
print("  • Grafana:   http://localhost:3000  (admin/admin)")
print("  • Prometheus:http://localhost:9090")
print("  • RabbitMQ:  http://localhost:15672 (guest/guest)")
