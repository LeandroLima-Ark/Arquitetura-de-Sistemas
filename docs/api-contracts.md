# Contratos de API

Este documento descreve todos os endpoints disponíveis nos serviços do sistema de matrícula, incluindo exemplos de requisição, resposta e códigos de status HTTP.

---

## Sumário

- [Middleware API (Porta 8000)](#middleware-api-porta-8000)
- [Course Service (Porta 8001)](#course-service-porta-8001)
- [Enrollment Service (Porta 8002)](#enrollment-service-porta-8002)
- [Evento RabbitMQ](#evento-rabbitmq)

---

## Middleware API (Porta 8000)

O Middleware API é o ponto de entrada único do sistema. Todas as requisições de clientes passam por ele.

### Visão Geral dos Endpoints

| Método | Caminho | Auth | Descrição |
|--------|---------|------|-----------|
| GET | `/health` | Não | Health check do middleware |
| GET | `/metrics` | Não | Métricas do sistema |
| POST | `/v1/enrollments` | student, admin | Criar matrícula |
| GET | `/v1/admin/enrollments` | admin | Listar todas as matrículas |

---

### GET /health

Verifica o estado de saúde do Middleware API.

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| X-Correlation-ID | Não | ID de correlação (gerado automaticamente se ausente) |

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8000/health
```

**Resposta de Sucesso (200 OK):**

```json
{
  "status": "healthy",
  "service": "middleware-api",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

---

### GET /metrics

Retorna métricas e estatísticas do sistema.

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| X-Correlation-ID | Não | ID de correlação |

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8000/metrics
```

**Resposta de Sucesso (200 OK):**

```json
{
  "total_requests": 150,
  "successful_requests": 142,
  "failed_requests": 8,
  "average_response_time_ms": 45.2,
  "active_services": {
    "course_service": true,
    "enrollment_service": true,
    "rabbitmq": true
  },
  "uptime_seconds": 3600
}
```

---

### POST /v1/enrollments

Cria uma nova matrícula para um aluno em um curso.

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| Authorization | Sim | Token JWT no formato `Bearer <token>` |
| Content-Type | Sim | `application/json` |
| X-Correlation-ID | Não | ID de correlação (gerado automaticamente se ausente) |

**Roles Permitidas:** `student`, `admin`

**Corpo da Requisição:**

```json
{
  "student_id": "STU001",
  "course_id": "CS101"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| student_id | string | Sim | Identificador do aluno |
| course_id | string | Sim | Identificador do curso |

**Exemplo de Requisição:**

```cmd
curl -X POST http://localhost:8000/v1/enrollments -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." -H "Content-Type: application/json" -H "X-Correlation-ID: req-12345" -d "{\"student_id\": \"STU001\", \"course_id\": \"CS101\"}"
```

**Resposta de Sucesso (201 Created):**

```json
{
  "enrollment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "student_id": "STU001",
  "course_id": "CS101",
  "course_name": "Introdução à Computação",
  "status": "confirmed",
  "enrolled_at": "2025-01-15T10:30:00Z",
  "correlation_id": "req-12345"
}
```

**Respostas de Erro:**

**400 Bad Request** — Campos obrigatórios ausentes:

```json
{
  "detail": "Os campos 'student_id' e 'course_id' são obrigatórios",
  "correlation_id": "req-12345"
}
```

**401 Unauthorized** — Token JWT ausente ou inválido:

```json
{
  "detail": "Token de autenticação não fornecido",
  "correlation_id": "req-12345"
}
```

**403 Forbidden** — Role insuficiente:

```json
{
  "detail": "Acesso negado. Role necessária: student ou admin",
  "correlation_id": "req-12345"
}
```

**404 Not Found** — Curso não encontrado:

```json
{
  "detail": "Curso 'CS999' não encontrado",
  "correlation_id": "req-12345"
}
```

**503 Service Unavailable** — Serviço indisponível (fallback):

```json
{
  "detail": "Serviço temporariamente indisponível. Tente novamente mais tarde.",
  "correlation_id": "req-12345",
  "fallback": true
}
```

---

### GET /v1/admin/enrollments

Lista todas as matrículas registradas no sistema. Restrito a administradores.

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| Authorization | Sim | Token JWT no formato `Bearer <token>` (role: admin) |
| X-Correlation-ID | Não | ID de correlação |

**Roles Permitidas:** `admin`

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8000/v1/admin/enrollments -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." -H "X-Correlation-ID: req-67890"
```

**Resposta de Sucesso (200 OK):**

```json
{
  "enrollments": [
    {
      "enrollment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "student_id": "STU001",
      "course_id": "CS101",
      "enrolled_at": "2025-01-15T10:30:00Z"
    },
    {
      "enrollment_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "student_id": "STU002",
      "course_id": "CS201",
      "enrolled_at": "2025-01-15T11:00:00Z"
    }
  ],
  "total": 2,
  "correlation_id": "req-67890"
}
```

**Respostas de Erro:**

**401 Unauthorized** — Token ausente ou inválido:

```json
{
  "detail": "Token de autenticação não fornecido",
  "correlation_id": "req-67890"
}
```

**403 Forbidden** — Role insuficiente (não é admin):

```json
{
  "detail": "Acesso negado. Role necessária: admin",
  "correlation_id": "req-67890"
}
```

**503 Service Unavailable** — Enrollment Service indisponível:

```json
{
  "detail": "Serviço de matrículas temporariamente indisponível",
  "correlation_id": "req-67890",
  "fallback": true
}
```

---

## Course Service (Porta 8001)

Serviço interno responsável pelo gerenciamento dos dados de cursos. **Não possui autenticação** — é acessado exclusivamente pelo Middleware API dentro da rede Docker.

### Visão Geral dos Endpoints

| Método | Caminho | Descrição |
|--------|---------|-----------|
| GET | `/health` | Health check do serviço |
| GET | `/courses/{course_id}` | Buscar curso por ID |

---

### GET /health

Verifica o estado de saúde do Course Service.

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8001/health
```

**Resposta de Sucesso (200 OK):**

```json
{
  "status": "healthy",
  "service": "course-service"
}
```

---

### GET /courses/{course_id}

Retorna os detalhes de um curso específico pelo seu ID.

**Parâmetros de URL:**

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|-------------|-----------|
| course_id | string | Sim | Identificador único do curso (ex.: CS101) |

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| X-Correlation-ID | Não | ID de correlação propagado pelo Middleware |

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8001/courses/CS101 -H "X-Correlation-ID: req-12345"
```

**Resposta de Sucesso (200 OK):**

```json
{
  "course_id": "CS101",
  "name": "Introdução à Computação",
  "description": "Curso introdutório de ciência da computação",
  "instructor": "Prof. Silva",
  "max_students": 30
}
```

**Respostas de Erro:**

**404 Not Found** — Curso não encontrado:

```json
{
  "detail": "Curso 'CS999' não encontrado"
}
```

---

## Enrollment Service (Porta 8002)

Serviço interno responsável pelo gerenciamento das matrículas. **Não possui autenticação** — é acessado exclusivamente pelo Middleware API dentro da rede Docker.

### Visão Geral dos Endpoints

| Método | Caminho | Descrição |
|--------|---------|-----------|
| GET | `/health` | Health check do serviço |
| POST | `/enrollments` | Criar matrícula |
| GET | `/enrollments` | Listar todas as matrículas |

---

### GET /health

Verifica o estado de saúde do Enrollment Service.

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8002/health
```

**Resposta de Sucesso (200 OK):**

```json
{
  "status": "healthy",
  "service": "enrollment-service"
}
```

---

### POST /enrollments

Cria um novo registro de matrícula.

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| Content-Type | Sim | `application/json` |
| X-Correlation-ID | Não | ID de correlação propagado pelo Middleware |

**Corpo da Requisição:**

```json
{
  "student_id": "STU001",
  "course_id": "CS101"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| student_id | string | Sim | Identificador do aluno |
| course_id | string | Sim | Identificador do curso |

**Exemplo de Requisição:**

```cmd
curl -X POST http://localhost:8002/enrollments -H "Content-Type: application/json" -H "X-Correlation-ID: req-12345" -d "{\"student_id\": \"STU001\", \"course_id\": \"CS101\"}"
```

**Resposta de Sucesso (201 Created):**

```json
{
  "enrollment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "student_id": "STU001",
  "course_id": "CS101",
  "enrolled_at": "2025-01-15T10:30:00Z"
}
```

**Respostas de Erro:**

**400 Bad Request** — Campos obrigatórios ausentes:

```json
{
  "detail": "Os campos 'student_id' e 'course_id' são obrigatórios"
}
```

---

### GET /enrollments

Lista todas as matrículas registradas.

**Headers da Requisição:**

| Header | Obrigatório | Descrição |
|--------|-------------|-----------|
| X-Correlation-ID | Não | ID de correlação propagado pelo Middleware |

**Exemplo de Requisição:**

```cmd
curl -X GET http://localhost:8002/enrollments -H "X-Correlation-ID: req-67890"
```

**Resposta de Sucesso (200 OK):**

```json
{
  "enrollments": [
    {
      "enrollment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "student_id": "STU001",
      "course_id": "CS101",
      "enrolled_at": "2025-01-15T10:30:00Z"
    },
    {
      "enrollment_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "student_id": "STU002",
      "course_id": "CS201",
      "enrolled_at": "2025-01-15T11:00:00Z"
    }
  ],
  "total": 2
}
```

---

## Evento RabbitMQ

### Evento: `enrollment.created`

Publicado pelo Middleware API após a criação bem-sucedida de uma matrícula. Consumido pelo Notification Worker.

**Exchange:** `enrollment_exchange`
**Routing Key:** `enrollment.created`
**Fila:** `enrollment_notifications`

**Formato da Mensagem:**

```json
{
  "event_type": "enrollment.created",
  "timestamp": "2025-01-15T10:30:00Z",
  "correlation_id": "req-12345",
  "data": {
    "enrollment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "student_id": "STU001",
    "course_id": "CS101",
    "course_name": "Introdução à Computação",
    "enrolled_at": "2025-01-15T10:30:00Z"
  }
}
```

| Campo | Tipo | Descrição |
|-------|------|-----------|
| event_type | string | Tipo do evento (`enrollment.created`) |
| timestamp | string (ISO 8601) | Data/hora da publicação do evento |
| correlation_id | string | ID de correlação da requisição original |
| data.enrollment_id | string (UUID) | ID único da matrícula |
| data.student_id | string | ID do aluno |
| data.course_id | string | ID do curso |
| data.course_name | string | Nome do curso |
| data.enrolled_at | string (ISO 8601) | Data/hora da matrícula |

**Comportamento do Worker:**

Ao consumir o evento, o Notification Worker loga uma mensagem simulando o envio de notificação:

```
[NOTIFICATION] Nova matrícula: Aluno STU001 matriculado no curso 'Introdução à Computação' (CS101) - Correlation ID: req-12345
```

---

## Códigos de Status HTTP — Resumo

| Código | Significado | Quando é Retornado |
|--------|-------------|-------------------|
| 200 | OK | Requisição processada com sucesso (GET) |
| 201 | Created | Recurso criado com sucesso (POST) |
| 400 | Bad Request | Dados da requisição inválidos ou incompletos |
| 401 | Unauthorized | Token JWT ausente ou inválido |
| 403 | Forbidden | Token válido, mas role insuficiente para o endpoint |
| 404 | Not Found | Recurso solicitado não encontrado (curso, matrícula) |
| 503 | Service Unavailable | Serviço interno indisponível (resposta de fallback) |
