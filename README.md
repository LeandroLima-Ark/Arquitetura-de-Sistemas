# Middleware Distribuído — Sistema de Matrículas

## Descrição

Projeto acadêmico para implementação de um **middleware distribuído** conectando serviços independentes. O domínio abordado é **Educação**, com um sistema simplificado de matrículas em cursos.

O middleware atua como ponto central de comunicação, orquestrando chamadas entre microserviços, garantindo tolerância a falhas, observabilidade e comunicação assíncrona via mensageria.

---

## Arquitetura

```
                         ┌──────────────────┐
                         │     Cliente       │
                         │  (curl / browser) │
                         └────────┬─────────┘
                                  │ HTTP
                                  ▼
                         ┌──────────────────┐
                         │    Middleware     │
                         │   (FastAPI)      │
                         │   porta 8000     │
                         └──┬─────┬────┬───┘
                            │     │    │
               ┌────────────┘     │    └────────────┐
               │                  │                  │
               ▼                  ▼                  ▼
   ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐
   │ Course Service   │  │  Enrollment  │  │    RabbitMQ      │
   │  (FastAPI)       │  │   Service    │  │  (mensageria)    │
   │  porta 8001      │  │  (FastAPI)   │  │  porta 5672      │
   └──────────────────┘  │  porta 8002  │  │  UI: 15672       │
                         └──────────────┘  └────────┬─────────┘
                                                    │
                                                    ▼
                                           ┌──────────────────┐
                                           │  Notification    │
                                           │    Worker        │
                                           │  (Pika consumer) │
                                           └──────────────────┘
```

---

## Serviços

| Serviço               | Descrição                                                    | Porta  |
|------------------------|--------------------------------------------------------------|--------|
| **Middleware**         | API central que orquestra chamadas entre serviços            | 8000   |
| **Course Service**     | Gerenciamento de cursos (CRUD)                               | 8001   |
| **Enrollment Service** | Gerenciamento de matrículas (CRUD)                           | 8002   |
| **RabbitMQ**           | Broker de mensagens para comunicação assíncrona              | 5672   |
| **RabbitMQ Management**| Interface web de gerenciamento do RabbitMQ                   | 15672  |
| **Notification Worker**| Consumidor que processa notificações de matrícula            | —      |

---

## Tecnologias

- **Python 3.11** — Linguagem principal
- **FastAPI** — Framework web assíncrono para APIs REST
- **Docker & Docker Compose** — Containerização e orquestração
- **RabbitMQ** — Message broker para comunicação assíncrona
- **HTTPX** — Cliente HTTP assíncrono para comunicação entre serviços
- **Pika** — Biblioteca Python para comunicação com RabbitMQ

---

## Como Executar

### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) instalado
- [Docker Compose](https://docs.docker.com/compose/install/) instalado

### Subir todos os serviços

```bash
docker compose up --build
```

Para executar em segundo plano (modo detached):

```bash
docker compose up --build -d
```

Para parar todos os serviços:

```bash
docker compose down
```

---

## Como Testar

### 1. Health Check dos Serviços

Verificar se o **Middleware** está saudável:

```bash
curl http://localhost:8000/health
```

Verificar o **Course Service**:

```bash
curl http://localhost:8001/health
```

Verificar o **Enrollment Service**:

```bash
curl http://localhost:8002/health
```

### 2. Realizar uma Matrícula

Enviar uma requisição de matrícula via middleware com autenticação e ID de correlação:

```bash
curl -X POST http://localhost:8000/enrollments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer token-aluno-123" \
  -H "X-Correlation-ID: test-correlation-001" \
  -d '{
    "student_id": "aluno-123",
    "course_id": "curso-456"
  }'
```

### 3. Consultar Métricas

```bash
curl http://localhost:8000/metrics
```

### 4. Consultar Matrículas (Admin)

```bash
curl http://localhost:8000/admin/enrollments \
  -H "Authorization: Bearer token-admin"
```

### 5. Teste de Tolerância a Falhas

Parar o serviço de cursos e verificar a resiliência do middleware:

```bash
# Parar o course-service
docker compose stop course-service

# Tentar realizar uma matrícula (deve retornar erro tratado)
curl -X POST http://localhost:8000/enrollments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer token-aluno-123" \
  -H "X-Correlation-ID: test-fault-001" \
  -d '{
    "student_id": "aluno-789",
    "course_id": "curso-456"
  }'

# Reiniciar o course-service
docker compose start course-service
```

---

## RabbitMQ Management UI

A interface de gerenciamento do RabbitMQ está disponível em:

- **URL:** [http://localhost:15672](http://localhost:15672)
- **Usuário:** `guest`
- **Senha:** `guest`

Através dela é possível:
- Visualizar filas e mensagens
- Monitorar taxas de publicação e consumo
- Verificar conexões ativas
- Gerenciar exchanges e bindings

---

## Tokens de Autenticação

O middleware utiliza autenticação via Bearer Token. Os tokens disponíveis para testes são:

| Token                    | Papel (Role) | Descrição                          |
|--------------------------|-------------- |------------------------------------|
| `token-aluno-123`        | `student`     | Aluno com permissão de matrícula   |
| `token-aluno-456`        | `student`     | Outro aluno para testes            |
| `token-admin`            | `admin`       | Administrador com acesso total     |

> **Nota:** Esses tokens são simulados para fins acadêmicos. Em produção, utilize OAuth2/JWT.

---

## Estrutura do Projeto

```
Arquitetura-de-Sistemas/
├── docker-compose.yml
├── README.md
├── middleware/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
├── services/
│   ├── course-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── enrollment-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   └── notification-worker/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── worker.py
```

---

## Autores

Projeto desenvolvido como parte da disciplina de **Arquitetura de Sistemas**.