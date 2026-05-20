# Tolerância a Falhas

## Visão Geral

Em sistemas distribuídos, falhas são inevitáveis. Serviços podem ficar indisponíveis, a rede pode apresentar latência elevada e brokers de mensagens podem sair do ar. O Middleware API implementa uma **estratégia de resiliência em camadas** para garantir que o sistema continue operando de forma degradada, mesmo quando componentes individuais falham.

A estratégia de tolerância a falhas é composta por três mecanismos principais:

1. **Timeout** — Limita o tempo de espera por respostas
2. **Retry** — Tenta novamente em caso de falhas transitórias
3. **Fallback** — Fornece respostas alternativas quando o serviço está indisponível

---

## Mecanismos de Resiliência

### 1. Timeout (Tempo Limite)

**Configuração:** 5 segundos por chamada HTTP

**Comportamento:**

- Toda chamada HTTP do Middleware para os serviços internos (Course Service, Enrollment Service) possui um timeout de 5 segundos
- Se o serviço não responder dentro desse prazo, a conexão é encerrada e uma exceção de timeout é lançada
- O timeout é aplicado por tentativa individual (não é cumulativo com retries)

**Justificativa do valor de 5 segundos:**

- **Suficientemente longo** para acomodar variações normais de latência na rede Docker interna
- **Suficientemente curto** para evitar que requisições fiquem presas indefinidamente, degradando a experiência do usuário
- Em um cenário real de produção, esse valor seria ajustado com base em métricas de latência observadas (p95, p99)

```python
# Exemplo de implementação
async with httpx.AsyncClient(timeout=5.0) as client:
    response = await client.get(f"{COURSE_SERVICE_URL}/courses/{course_id}")
```

---

### 2. Retry (Tentativas com Backoff Exponencial)

**Configuração:** 3 tentativas com backoff exponencial

**Intervalos entre tentativas:**

| Tentativa | Intervalo de Espera | Tempo Acumulado |
|-----------|---------------------|-----------------|
| 1ª tentativa | Imediata | 0s |
| 2ª tentativa (1º retry) | 1 segundo | 1s |
| 3ª tentativa (2º retry) | 2 segundos | 3s |
| *(se houvesse 4ª)* | *4 segundos* | *7s* |

**Comportamento:**

- Na primeira falha (timeout, erro de conexão, status 5xx), o sistema aguarda 1 segundo e tenta novamente
- Na segunda falha, aguarda 2 segundos e tenta uma última vez
- Se a terceira tentativa falhar, o mecanismo de fallback é acionado
- O backoff exponencial evita sobrecarregar um serviço que já está com problemas

**Justificativa do backoff exponencial:**

- **Evita "tempestade de retries"**: se muitas instâncias tentarem reconectar simultaneamente, isso pode agravar a falha do serviço
- **Dá tempo para recuperação**: intervalos crescentes permitem que o serviço se recupere antes da próxima tentativa
- **3 tentativas é um bom equilíbrio**: suficiente para superar falhas transitórias (picos de latência, restart de container) sem atrasar excessivamente a resposta ao cliente

```python
# Exemplo de implementação
async def call_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = await http_client.get(url, timeout=5.0)
            return response
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                await asyncio.sleep(wait_time)
            else:
                raise
```

---

### 3. Fallback (Degradação Graciosa)

Quando todas as tentativas de retry se esgotam, o sistema **não retorna um erro genérico 500**. Em vez disso, ele fornece uma resposta de fallback informativa e controlada.

**Comportamento por cenário:**

| Serviço Indisponível | Resposta de Fallback |
|----------------------|---------------------|
| Course Service | HTTP 503 com mensagem explicativa |
| Enrollment Service | HTTP 503 com mensagem explicativa |
| RabbitMQ | Matrícula é criada com sucesso, notificação é ignorada (log de warning) |

**Exemplo de resposta de fallback:**

```json
{
  "detail": "Serviço temporariamente indisponível. Tente novamente mais tarde.",
  "correlation_id": "req-12345",
  "fallback": true
}
```

---

## Cenários de Falha

### Cenário 1: Course Service Indisponível

**Situação:** O Course Service (porta 8001) está fora do ar ou não responde.

**Fluxo:**

```
1. Cliente envia POST /v1/enrollments ao Middleware
2. Middleware valida o token JWT ✓
3. Middleware tenta GET /courses/{id} no Course Service
4. Tentativa 1: Timeout após 5s ✗
5. Aguarda 1s → Tentativa 2: Timeout após 5s ✗
6. Aguarda 2s → Tentativa 3: Timeout após 5s ✗
7. Todas as tentativas falharam → Ativa fallback
8. Middleware retorna HTTP 503 ao cliente com mensagem de fallback
```

**Tempo total máximo:** ~18 segundos (5s×3 tentativas + 1s + 2s de backoff)

**Resposta ao Cliente:**

```json
{
  "detail": "Serviço de cursos temporariamente indisponível. Não foi possível validar o curso. Tente novamente mais tarde.",
  "correlation_id": "req-12345",
  "fallback": true
}
```

**Como testar:**

```bash
# Parar o Course Service
docker compose stop course-service

# Tentar criar uma matrícula
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "STU001", "course_id": "CS101"}'

# Verificar a resposta de fallback (HTTP 503)

# Reiniciar o Course Service
docker compose start course-service
```

---

### Cenário 2: Enrollment Service Indisponível

**Situação:** O Enrollment Service (porta 8002) está fora do ar ou não responde.

**Fluxo:**

```
1. Cliente envia POST /v1/enrollments ao Middleware
2. Middleware valida o token JWT ✓
3. Middleware consulta Course Service → Curso encontrado ✓
4. Middleware tenta POST /enrollments no Enrollment Service
5. Tentativa 1: Timeout após 5s ✗
6. Aguarda 1s → Tentativa 2: Timeout após 5s ✗
7. Aguarda 2s → Tentativa 3: Timeout após 5s ✗
8. Todas as tentativas falharam → Ativa fallback
9. Middleware retorna HTTP 503 ao cliente com mensagem de fallback
```

**Resposta ao Cliente:**

```json
{
  "detail": "Serviço de matrículas temporariamente indisponível. Tente novamente mais tarde.",
  "correlation_id": "req-12345",
  "fallback": true
}
```

**Como testar:**

```bash
# Parar o Enrollment Service
docker compose stop enrollment-service

# Tentar criar uma matrícula
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "STU001", "course_id": "CS101"}'

# Verificar a resposta de fallback (HTTP 503)

# Reiniciar o Enrollment Service
docker compose start enrollment-service
```

---

### Cenário 3: RabbitMQ Indisponível

**Situação:** O RabbitMQ (porta 5672) está fora do ar.

**Fluxo:**

```
1. Cliente envia POST /v1/enrollments ao Middleware
2. Middleware valida o token JWT ✓
3. Middleware consulta Course Service → Curso encontrado ✓
4. Middleware cria matrícula no Enrollment Service → Matrícula criada ✓
5. Middleware tenta publicar evento no RabbitMQ
6. Publicação falha → Log de WARNING registrado
7. Middleware retorna HTTP 201 ao cliente (matrícula criada com sucesso)
8. Notificação NÃO é enviada (será perdida)
```

**⚠️ Comportamento Especial:** Diferente dos outros cenários, a **matrícula é criada com sucesso** mesmo quando o RabbitMQ está fora do ar. A notificação é considerada um efeito colateral não-crítico.

**Resposta ao Cliente:**

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

**Log do Middleware (Warning):**

```
WARNING: Falha ao publicar evento enrollment.created no RabbitMQ. Correlation ID: req-12345. A matrícula foi criada, mas a notificação não será enviada.
```

**Como testar:**

```bash
# Parar o RabbitMQ
docker compose stop rabbitmq

# Criar uma matrícula (deve funcionar normalmente)
curl -X POST http://localhost:8000/v1/enrollments \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "STU001", "course_id": "CS101"}'

# Verificar que a matrícula foi criada (HTTP 201)

# Verificar os logs do Middleware para o warning
docker compose logs middleware-api

# Reiniciar o RabbitMQ
docker compose start rabbitmq
```

---

## Estratégia de Consistência

### Consistência Eventual para Notificações

O sistema adota um modelo de **consistência eventual** para o subsistema de notificações:

- A **operação principal** (criação da matrícula) é **fortemente consistente** — o dado é persistido no Enrollment Service antes de retornar sucesso ao cliente
- A **operação secundária** (envio de notificação) é **eventualmente consistente** — a mensagem é publicada no RabbitMQ e processada de forma assíncrona pelo Worker

**Implicações:**

1. **Sem RabbitMQ**: a matrícula é criada, mas nenhuma notificação é enviada. A consistência é "perdida" para a notificação, mas o dado principal está seguro.
2. **Com RabbitMQ**: há um pequeno delay entre a criação da matrícula e o processamento da notificação pelo Worker. Esse delay é geralmente de milissegundos, mas pode aumentar sob carga.
3. **Worker reiniciado**: mensagens pendentes na fila serão processadas quando o Worker reconectar, garantindo a entrega eventual.

---

## Resumo dos Mecanismos

```
┌─────────────────────────────────────────────────────────┐
│                  ESTRATÉGIA DE RESILIÊNCIA               │
├─────────────────┬───────────────────────────────────────┤
│    TIMEOUT      │  5 segundos por chamada HTTP          │
│                 │  Evita requisições presas             │
├─────────────────┼───────────────────────────────────────┤
│    RETRY        │  3 tentativas                         │
│                 │  Backoff: 1s → 2s → 4s               │
│                 │  Supera falhas transitórias           │
├─────────────────┼───────────────────────────────────────┤
│    FALLBACK     │  HTTP 503 com mensagem informativa    │
│                 │  RabbitMQ: matrícula ok, log warning  │
│                 │  Degradação graciosa                  │
├─────────────────┼───────────────────────────────────────┤
│  CONSISTÊNCIA   │  Forte: dados de matrícula            │
│                 │  Eventual: notificações               │
└─────────────────┴───────────────────────────────────────┘
```

---

## Testando a Tolerância a Falhas

### Comandos Rápidos

```bash
# === Testar falha do Course Service ===
docker compose stop course-service
# Fazer requisição e observar fallback
docker compose start course-service

# === Testar falha do Enrollment Service ===
docker compose stop enrollment-service
# Fazer requisição e observar fallback
docker compose start enrollment-service

# === Testar falha do RabbitMQ ===
docker compose stop rabbitmq
# Fazer requisição e observar que matrícula é criada (sem notificação)
docker compose start rabbitmq

# === Testar falha múltipla ===
docker compose stop course-service enrollment-service
# Fazer requisição e observar fallback
docker compose start course-service enrollment-service

# === Verificar logs ===
docker compose logs -f middleware-api
docker compose logs -f notification-worker
```
