import pika
import json
import time
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = 5672
QUEUE_NAME = "enrollment_notifications"
MAX_RETRIES = 30
RETRY_INTERVAL = 5


def connect_to_rabbitmq():
    """Connect to RabbitMQ with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                f"Attempting to connect to RabbitMQ at {RABBITMQ_HOST}:{RABBITMQ_PORT} "
                f"(attempt {attempt}/{MAX_RETRIES})"
            )
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=pika.PlainCredentials("guest", "guest"),
                )
            )
            logger.info("Successfully connected to RabbitMQ")
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logger.warning(
                f"Connection attempt {attempt}/{MAX_RETRIES} failed: {e}"
            )
            if attempt < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_INTERVAL} seconds...")
                time.sleep(RETRY_INTERVAL)
            else:
                logger.error(
                    "Max retries reached. Could not connect to RabbitMQ."
                )
                raise


def on_message_received(ch, method, properties, body):
    """Callback for processing received messages."""
    try:
        message = json.loads(body)
        student_id = message.get("student_id", "unknown")
        course_id = message.get("course_id", "unknown")
        correlation_id = message.get("correlation_id", "unknown")

        # Structured JSON log
        structured_log = json.dumps({
            "event": "notification_sent",
            "type": "enrollment_confirmation",
            "student_id": student_id,
            "course_id": course_id,
            "correlation_id": correlation_id,
            "status": "simulated"
        })
        logger.info(f"Structured notification: {structured_log}")

        # Human-readable log
        print(
            f"[NOTIFICATION] Enrollment confirmed for student {student_id} "
            f"in course {course_id} (correlation: {correlation_id})"
        )

        # Acknowledge the message
        ch.basic_ack(delivery_tag=method.delivery_tag)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse message body: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)


def main():
    """Main entry point for the notification worker."""
    logger.info("Starting Notification Worker...")

    connection = connect_to_rabbitmq()
    channel = connection.channel()

    # Declare the queue (idempotent)
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    logger.info(f"Declared queue: {QUEUE_NAME}")

    # Set up consumer
    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=on_message_received,
        auto_ack=False,
    )

    logger.info("Notification Worker is ready. Waiting for messages...")
    channel.start_consuming()


if __name__ == "__main__":
    main()
