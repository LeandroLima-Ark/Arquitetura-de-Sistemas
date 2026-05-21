# Middleware Distribuído — Sistema de Matrículas

> Projeto acadêmico — Disciplina de **Arquitetura de Sistemas**

## Descrição

Sistema distribuído de matrículas implementado com **7 containers Docker** independentes, comunicação síncrona (REST) e assíncrona (RabbitMQ), resiliência (Circuit Breaker + Retry), autenticação JWT, e observabilidade completa (Prometheus + Grafana).

---

## Arquitetura

```
                     ┌──────────────┐
                     │    Cliente   │
                     │ curl/Postman │
                     └──────┬───────┘
                            │ HTTP :8000
                            ▼
                   ┌─────────────────┐
                   │   Middleware    │  ← API Gateway próprio
                   │   (FastAPI)     │  ← JWT Auth, Circuit Breaker
                   │   porta 8000   │  ← Retry, Metrics, Correlation ID
                   └──┬──────┬──────┘
                      │      │           ┌──────────────┐
                      │      └──────────►│ auth-service │ :8003
                      │                  └──────────────┘
          ┌───────────┴──────────┐
          │                      │
          ▼                      ▼
 ┌──────────────────┐  ┌──────────────────┐
 │  course-service  │  │enrollment-service│
 │  (FastAPI) :8001 │  │  (FastAPI) :8002 │
 │  CRUD de cursos  │  │  CRUD matrículas │
 └──────────────────┘  │  + idempotência  │
                       └──────────────────┘
          │ AMQP (publish)
          ▼
   ┌─────────────┐          ┌──────────────────┐
   │  RabbitMQ   │─────────►│notification-work │
   │  :5672      │ consume  │  (Pika consumer) │
   │  UI: :15672 │          └──────────────────┘
   └─────────────┘

Observabilidade:
  Prometheus :9090 ──scrape──► middleware, course-service, enrollment-service
  Grafana    :3000 ──query───► Prometheus
```

---

## Serviços

| Serviço                | Descrição                                              | Porta  |
|------------------------|--------------------------------------------------------|--------|
| **middleware**         | API Gateway: auth, circuit breaker, retry, metrics     | 8000   |
| **auth-service**       | Emissão e validação de JWT                             | 8003   |
| **course-service**     | CRUD de cursos                                         | 8001   |
| **enrollment-service** | CRUD de matrículas com idempotência                    | 8002   |
| **notification-worker**| Consumer RabbitMQ (simula envio de email)              | —      |
| **rabbitmq**           | Message broker + management UI                         | 5672/15672 |
| **prometheus**         | Coleta de métricas                                     | 9090   |
| **grafana**            | Dashboard de observabilidade                           | 3000   |

---

## Tecnologias

- **Python 3.11** + **FastAPI** — todos os serviços HTTP
- **Docker & Docker Compose** — containerização e orquestração
- **RabbitMQ (Pika)** — mensageria assíncrona
- **python-jose** — JWT (HS256)
- **HTTPX** — cliente HTTP assíncrono com timeout
- **Prometheus + Grafana** — observabilidade
- **passlib[bcrypt]** — hash de senhas

---

## Como Executar

### Pré-requisitos

- [Docker Desktop](https://docs.docker.com/get-docker/) instalado e rodando

### Subir todos os serviços

```bash
docker compose up --build
```

Para rodar em background:

```bash
docker compose up --build -d
```

Para parar:

```bash
docker compose down
```

---

## Fluxo de Autenticação (JWT)

### 1. Fazer login e obter JWT

```bash
# Login como aluno
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "aluno", "password": "senha123"}'

# Login como admin
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

**Resposta:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "role": "student",
  "expires_in": 3600
}
```

### Usuários disponíveis

| Usuário | Senha     | Role    |
|---------|-----------|---------|
| aluno   | senha123  | student |
| admin   | admin123  | admin   |

---

## Endpoints

### Matrícula (fluxo principal)

```bash
# Listar cursos (público)
curl http://localhost:8000/v1/courses

# Realizar matrícula (student ou admin)
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Correlation-ID: meu-request-001" \
  -d '{"student_id": "aluno-01", "course_id": "c1"}'

# Listar matrículas (apenas admin)
curl http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <ADMIN_TOKEN>"
```

### Administração de Cursos (admin)

```bash
# Criar novo curso
curl -X POST http://localhost:8000/v1/courses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <ADMIN_TOKEN>" \
  -d '{"name": "Cloud Computing", "description": "AWS/GCP/Azure", "max_students": 25}'
```

### Health & Métricas

```bash
# Saúde do middleware (mostra estado dos circuit breakers)
curl http://localhost:8000/health

# Métricas JSON
curl http://localhost:8000/metrics

# Métricas formato Prometheus
curl -H "Accept: text/plain" http://localhost:8000/metrics

# Saúde individual dos serviços
curl http://localhost:8001/health   # course-service
curl http://localhost:8002/health   # enrollment-service
curl http://localhost:8003/health   # auth-service
```

---

## Demonstração de Tolerância a Falhas

### Cenário 1: Course Service cai (Circuit Breaker)

```bash
# 1. Derrubar o course-service
docker compose stop course-service

# 2. Tentar matrícula — middleware fará 3 retries, depois abre o Circuit Breaker
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"student_id": "aluno-01", "course_id": "c1"}'
# → 503 com {"error": "Service unavailable", "fallback": true}

# 3. Ver estado do circuit breaker
curl http://localhost:8000/health
# → "circuit_breakers": {"course-service": "open"}

# 4. Reiniciar (circuit vai para half-open após 30s)
docker compose start course-service
```

### Cenário 2: Notification Worker cai (Tolerância a Falhas)

```bash
# 1. Derrubar notification-worker
docker compose stop notification-worker

# 2. Fazer matrícula — FUNCIONA NORMALMENTE (desacoplado)
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "aluno-01", "course_id": "c2"}'
# → 201 Created (matrícula criada; evento fica na fila)

# 3. Ver mensagens na fila: http://localhost:15672 (guest/guest)

# 4. Reiniciar worker — processa mensagens acumuladas automaticamente
docker compose start notification-worker
```

### Cenário 3: Matrícula duplicada (Idempotência)

```bash
# Mesma matrícula duas vezes
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "aluno-01", "course_id": "c1"}'
# → 201 Created (primeira vez)

curl -X POST http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "aluno-01", "course_id": "c1"}'
# → 409 Conflict (segunda vez — idempotência aplicada)
```

---

## Observabilidade

### Prometheus
- **URL:** http://localhost:9090
- Query de exemplo: `middleware_requests_total`

### Grafana
- **URL:** http://localhost:3000
- **Login:** admin / admin
- Dashboard **"Sistema de Matrículas — Overview"** pré-configurado

### RabbitMQ Management UI
- **URL:** http://localhost:15672
- **Login:** guest / guest

---

## Estrutura do Projeto

```
Arquitetura-de-Sistemas/
├── docker-compose.yml
├── README.md
├── middleware/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                   ← Gateway: JWT, Circuit Breaker, Retry, Metrics
├── services/
│   ├── auth-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app.py               ← Emissão e validação JWT (HS256)
│   ├── course-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app.py               ← CRUD cursos + Prometheus metrics
│   ├── enrollment-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app.py               ← CRUD matrículas + idempotência + Prometheus
│   └── notification-worker/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── worker.py            ← Consumer RabbitMQ + logs JSON estruturados
├── monitoring/
│   ├── prometheus.yml           ← Scrape config
│   └── grafana/
│       ├── datasources/
│       │   └── prometheus.yml   ← Auto-provisioning Prometheus
│       └── dashboards/
│           ├── dashboard.yml    ← Provisioning config
│           └── overview.json    ← Dashboard pré-configurado
└── docs/
    ├── architecture.md
    ├── api-contracts.md
    ├── fault-tolerance.md
    ├── diagram.md
    └── ai-usage.md
```

---

## Mecanismos de Resiliência

| Mecanismo        | Onde                   | Comportamento                                    |
|------------------|------------------------|--------------------------------------------------|
| **Timeout**      | Middleware → serviços  | 5s por request                                   |
| **Retry**        | Middleware → serviços  | 3 tentativas com backoff exponencial (1s, 2s, 4s)|
| **Circuit Breaker** | Middleware          | Abre após 3 falhas, fecha após 30s (half-open)  |
| **Fallback**     | Middleware             | Resposta amigável quando serviço indisponível    |
| **Idempotência** | Enrollment Service     | 409 se matrícula duplicada (student+course)      |
| **Fila durável** | RabbitMQ               | Mensagens persistem se notification-worker cair  |

---

## Autores

Projeto desenvolvido como parte da disciplina de **Arquitetura de Sistemas**.

> **Nota sobre uso de IA:** Este projeto utilizou assistência de IA (Antigravity/Claude) para implementação. Detalhes em `docs/ai-usage.md`.