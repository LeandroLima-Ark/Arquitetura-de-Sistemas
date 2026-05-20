# Diagramas da Arquitetura

Este documento contém os diagramas visuais da arquitetura do sistema de matrícula, apresentados em diferentes formatos para facilitar a compreensão.

---

## 1. Diagrama ASCII

Visão geral da arquitetura em formato texto:

```
┌──────────────────────────────────────────────────────────────────────┐
│                        SISTEMA DE MATRÍCULA                         │
│                    Arquitetura de Middleware                         │
└──────────────────────────────────────────────────────────────────────┘

                          ┌─────────────┐
                          │   CLIENTE   │
                          │  (HTTP/REST)│
                          └──────┬──────┘
                                 │
                                 │ HTTP Request
                                 │ (JWT Token)
                                 ▼
                    ┌────────────────────────────┐
                    │      MIDDLEWARE API         │
                    │       (Porta 8000)          │
                    │                            │
                    │  • Autenticação JWT        │
                    │  • Correlation ID          │
                    │  • Timeout (5s)            │
                    │  • Retry (3x, backoff)     │
                    │  • Fallback                │
                    │  • Publicação de Eventos   │
                    │  • Métricas                │
                    └──┬──────────┬──────────┬───┘
                       │          │          │
            ┌──────────┘          │          └──────────┐
            │ REST/HTTP           │ REST/HTTP           │ AMQP
            │ (Síncrono)          │ (Síncrono)          │ (Assíncrono)
            ▼                     ▼                     ▼
  ┌──────────────────┐ ┌──────────────────┐  ┌──────────────────┐
  │  COURSE SERVICE  │ │ENROLLMENT SERVICE│  │    RABBITMQ      │
  │   (Porta 8001)   │ │   (Porta 8002)   │  │   (Porta 5672)   │
  │                  │ │                  │  │                  │
  │ • GET /courses/  │ │ • POST /enroll.  │  │ • Exchange:      │
  │   {course_id}    │ │ • GET /enroll.   │  │   enrollment_    │
  │ • In-Memory      │ │ • In-Memory      │  │   exchange       │
  │   Store          │ │   Store          │  │ • Fila:          │
  │                  │ │                  │  │   enrollment_    │
  │                  │ │                  │  │   notifications  │
  └──────────────────┘ └──────────────────┘  └────────┬─────────┘
                                                      │
                                                      │ Consome
                                                      │ mensagens
                                                      ▼
                                            ┌──────────────────┐
                                            │ NOTIFICATION     │
                                            │ WORKER           │
                                            │                  │
                                            │ • Consome eventos│
                                            │ • Simula envio   │
                                            │   de notificações│
                                            │ • Log no console │
                                            └──────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ LEGENDA:                                                            │
│   ──────►  Comunicação Síncrona (REST/HTTP)                         │
│   ══════►  Comunicação Assíncrona (AMQP/RabbitMQ)                   │
│   [    ]   Serviço containerizado (Docker)                          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Diagrama de Fluxo (Mermaid)

Visão geral da arquitetura mostrando todos os componentes e suas interações:

```mermaid
flowchart TD
    Client["🖥️ Cliente HTTP"]

    subgraph MiddlewareLayer["Camada de Middleware"]
        MW["🔀 Middleware API\n(Porta 8000)"]
        Auth["🔐 Autenticação JWT"]
        CorrID["🏷️ Correlation ID"]
        Resilience["🛡️ Resiliência\n(Timeout / Retry / Fallback)"]
        EventPub["📤 Publicação de Eventos"]
    end

    subgraph Services["Serviços de Domínio"]
        CS["📚 Course Service\n(Porta 8001)\nDados de Cursos\n(In-Memory)"]
        ES["📝 Enrollment Service\n(Porta 8002)\nDados de Matrículas\n(In-Memory)"]
    end

    subgraph Messaging["Camada de Mensageria"]
        RMQ["🐇 RabbitMQ\n(Porta 5672)\nExchange: enrollment_exchange\nFila: enrollment_notifications"]
        NW["📨 Notification Worker\nConsome eventos\nSimula notificações"]
    end

    Client -->|"HTTP REST\n(JSON + JWT)"| MW
    MW --> Auth
    MW --> CorrID
    MW --> Resilience

    MW -->|"GET /courses/{id}\n(REST Síncrono)"| CS
    MW -->|"POST /enrollments\nGET /enrollments\n(REST Síncrono)"| ES

    MW --> EventPub
    EventPub -->|"Publica evento\nenrollment.created\n(AMQP Assíncrono)"| RMQ
    RMQ -->|"Consome mensagem\n(AMQP)"| NW

    style Client fill:#3498db,stroke:#2980b9,color:#fff
    style MW fill:#e67e22,stroke:#d35400,color:#fff
    style Auth fill:#f39c12,stroke:#e67e22,color:#fff
    style CorrID fill:#f39c12,stroke:#e67e22,color:#fff
    style Resilience fill:#f39c12,stroke:#e67e22,color:#fff
    style EventPub fill:#f39c12,stroke:#e67e22,color:#fff
    style CS fill:#2ecc71,stroke:#27ae60,color:#fff
    style ES fill:#9b59b6,stroke:#8e44ad,color:#fff
    style RMQ fill:#e74c3c,stroke:#c0392b,color:#fff
    style NW fill:#1abc9c,stroke:#16a085,color:#fff
```

---

## 3. Diagrama de Sequência — Fluxo de Matrícula (Mermaid)

Diagrama detalhado mostrando o fluxo completo de uma matrícula bem-sucedida, passo a passo:

```mermaid
sequenceDiagram
    autonumber
    actor Client as 🖥️ Cliente
    participant MW as 🔀 Middleware API<br/>(Porta 8000)
    participant CS as 📚 Course Service<br/>(Porta 8001)
    participant ES as 📝 Enrollment Service<br/>(Porta 8002)
    participant RMQ as 🐇 RabbitMQ<br/>(Porta 5672)
    participant NW as 📨 Notification Worker

    Note over Client,NW: Fluxo de Criação de Matrícula (Cenário de Sucesso)

    Client->>+MW: POST /v1/enrollments<br/>Headers: Authorization: Bearer {JWT}<br/>Body: {"student_id": "STU001", "course_id": "CS101"}

    Note over MW: Gera X-Correlation-ID<br/>se não fornecido

    MW->>MW: Valida Token JWT<br/>Verifica role (student/admin)

    Note over MW: Token válido ✓<br/>Role autorizada ✓

    MW->>+CS: GET /courses/CS101<br/>Header: X-Correlation-ID

    CS-->>-MW: 200 OK<br/>{"course_id": "CS101",<br/>"name": "Introdução à Computação",<br/>"instructor": "Prof. Silva"}

    Note over MW: Curso encontrado ✓

    MW->>+ES: POST /enrollments<br/>Header: X-Correlation-ID<br/>Body: {"student_id": "STU001",<br/>"course_id": "CS101"}

    ES-->>-MW: 201 Created<br/>{"enrollment_id": "uuid-...",<br/>"student_id": "STU001",<br/>"course_id": "CS101",<br/>"enrolled_at": "2025-01-15T10:30:00Z"}

    Note over MW: Matrícula criada ✓

    MW->>RMQ: Publica evento enrollment.created<br/>Exchange: enrollment_exchange<br/>Routing Key: enrollment.created

    Note over MW: Evento publicado ✓<br/>(fire-and-forget)

    MW-->>-Client: 201 Created<br/>{"enrollment_id": "uuid-...",<br/>"student_id": "STU001",<br/>"course_id": "CS101",<br/>"course_name": "Introdução à Computação",<br/>"status": "confirmed"}

    Note over Client: Resposta recebida ✓

    RMQ->>+NW: Entrega mensagem da fila<br/>enrollment_notifications

    NW->>NW: Processa evento<br/>Simula envio de notificação

    Note over NW: [NOTIFICATION] Aluno STU001<br/>matriculado em<br/>"Introdução à Computação"

    deactivate NW

    Note over Client,NW: ✅ Fluxo completo de matrícula finalizado
```

---

## 4. Diagrama de Sequência — Cenário de Falha (Course Service Indisponível)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 🖥️ Cliente
    participant MW as 🔀 Middleware API
    participant CS as 📚 Course Service<br/>(INDISPONÍVEL ❌)

    Note over Client,CS: Cenário: Course Service fora do ar

    Client->>+MW: POST /v1/enrollments<br/>Body: {"student_id": "STU001", "course_id": "CS101"}

    MW->>MW: Valida Token JWT ✓

    MW->>CS: GET /courses/CS101 (Tentativa 1)
    Note over MW,CS: ⏱️ Timeout após 5s

    MW->>MW: Aguarda 1s (backoff)

    MW->>CS: GET /courses/CS101 (Tentativa 2)
    Note over MW,CS: ⏱️ Timeout após 5s

    MW->>MW: Aguarda 2s (backoff)

    MW->>CS: GET /courses/CS101 (Tentativa 3)
    Note over MW,CS: ⏱️ Timeout após 5s

    Note over MW: ❌ Todas as tentativas falharam<br/>Ativa FALLBACK

    MW-->>-Client: 503 Service Unavailable<br/>{"detail": "Serviço temporariamente indisponível",<br/>"fallback": true}

    Note over Client: ⚠️ Tempo total: ~18s<br/>(5s×3 + 1s + 2s backoff)
```

---

## 5. Diagrama de Sequência — Cenário de Falha (RabbitMQ Indisponível)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 🖥️ Cliente
    participant MW as 🔀 Middleware API
    participant CS as 📚 Course Service
    participant ES as 📝 Enrollment Service
    participant RMQ as 🐇 RabbitMQ<br/>(INDISPONÍVEL ❌)

    Note over Client,RMQ: Cenário: RabbitMQ fora do ar (degradação graciosa)

    Client->>+MW: POST /v1/enrollments<br/>Body: {"student_id": "STU001", "course_id": "CS101"}

    MW->>MW: Valida Token JWT ✓

    MW->>+CS: GET /courses/CS101
    CS-->>-MW: 200 OK ✓

    MW->>+ES: POST /enrollments
    ES-->>-MW: 201 Created ✓

    MW->>RMQ: Publica evento enrollment.created
    Note over MW,RMQ: ❌ Falha na conexão

    Note over MW: ⚠️ WARNING: Falha ao publicar evento<br/>Matrícula criada com sucesso<br/>Notificação ignorada

    MW-->>-Client: 201 Created ✓<br/>{"enrollment_id": "uuid-...",<br/>"status": "confirmed"}

    Note over Client: ✅ Matrícula criada com sucesso<br/>📭 Notificação NÃO enviada
```
