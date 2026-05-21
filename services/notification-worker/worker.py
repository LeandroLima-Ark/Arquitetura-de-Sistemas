"""
Notification Worker — Sistema de Matrículas
============================================
Consumidor RabbitMQ que processa eventos de matrícula.
Simula envio de notificação por email/push com logs JSON estruturados.

Demonstra tolerância a falhas:
  - Se este serviço cair, mensagens ficam na fila (durable=True)
  - Ao reiniciar, processa as mensagens acumuladas automaticamente
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import pika

# ---------------------------------------------------------------------------
# Structured JSON Logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "notification-worker",
            "message": record.getMessage(),
        }
        if hasattr(record, "correlation_id"):
            log_record["correlation_id"] = record.correlation_id
        if hasattr(record, "details"):
            log_record["details"] = record.details
        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("notification-worker")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RABBITMQ_HOST  = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT  = 5672
QUEUE_NAME     = "enrollment_notifications"
MAX_RETRIES    = 30
RETRY_INTERVAL = 5

# Controle de idempotência: conjunto de message_ids já processados
_processed_message_ids: set[str] = set()

# ---------------------------------------------------------------------------
# RabbitMQ connection
# ---------------------------------------------------------------------------

def connect_to_rabbitmq():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Connecting to RabbitMQ at %s:%d (attempt %d/%d)",
                RABBITMQ_HOST, RABBITMQ_PORT, attempt, MAX_RETRIES,
            )
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=pika.PlainCredentials("guest", "guest"),
                )
            )
            logger.info("Connected to RabbitMQ successfully")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logger.warning(
                "RabbitMQ connection attempt %d/%d failed: %s",
                attempt, MAX_RETRIES, str(e),
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_INTERVAL)
            else:
                logger.error("Max retries reached. Could not connect to RabbitMQ.")
                raise

# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

def on_message_received(ch, method, properties, body):
    correlation_id = "unknown"
    try:
        message = json.loads(body)
        student_id     = message.get("student_id", "unknown")
        course_id      = message.get("course_id", "unknown")
        enrollment_id  = message.get("enrollment_id", "unknown")
        correlation_id = message.get("correlation_id", "unknown")

        # --- Idempotência: verificar message_id ---
        message_id = getattr(properties, "message_id", None) or enrollment_id
        if message_id in _processed_message_ids:
            logger.info(
                "Duplicate message ignored (message_id=%s)", message_id,
                extra={"correlation_id": correlation_id,
                       "details": {"message_id": message_id}},
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        _processed_message_ids.add(message_id)

        # --- Simular envio de notificação ---
        logger.info(
            "Processing enrollment notification",
            extra={
                "correlation_id": correlation_id,
                "details": {
                    "event": "notification_sent",
                    "type": "enrollment_confirmation",
                    "student_id": student_id,
                    "course_id": course_id,
                    "enrollment_id": enrollment_id,
                    "channel": "email",
                    "status": "simulated",
                },
            },
        )

        # Simula processamento
        print(
            f"[NOTIFICATION] ✉ Email enviado para aluno {student_id} — "
            f"Matrícula confirmada no curso {course_id} "
            f"(enrollment_id={enrollment_id}, correlation={correlation_id})"
        )

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse message body: %s", str(e),
            extra={"correlation_id": correlation_id},
        )
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logger.error(
            "Error processing message: %s", str(e),
            extra={"correlation_id": correlation_id},
        )
        # nack com requeue=False para não criar loop infinito
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting Notification Worker")

    connection = connect_to_rabbitmq()
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)  # processa uma mensagem por vez
    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=on_message_received,
        auto_ack=False,
    )

    logger.info(
        "Notification Worker ready",
        extra={"details": {"queue": QUEUE_NAME, "host": RABBITMQ_HOST}},
    )
    channel.start_consuming()


if __name__ == "__main__":
    main()
