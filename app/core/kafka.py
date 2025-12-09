"""
Kafka producer and consumer module using confluent-kafka library.

Provides a thread-safe Kafka producer for publishing events
and a consumer for subscribing to topics from other services.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from threading import Lock, Thread
from typing import Any, Callable, Optional

from confluent_kafka import Consumer, KafkaException, Producer

from app.core.config import settings
from app.core.events import EventEnvelope
from app.core.logging import get_logger

logger = get_logger(__name__)


def json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for complex types."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def delivery_callback(err, msg):
    """Callback for message delivery reports."""
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")


class KafkaProducer:
    """
    Singleton Kafka producer using confluent-kafka.

    Thread-safe producer that can be used across the application.
    """

    _instance: Optional[Producer] = None
    _lock: Lock = Lock()
    _started: bool = False

    @classmethod
    def get_producer(cls) -> Optional[Producer]:
        """Get or create the Kafka producer instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    config = {
                        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                        "client.id": "leave-management-service",
                        "acks": "all",
                        "retries": 3,
                        "retry.backoff.ms": 1000,
                        "enable.idempotence": True,
                    }
                    cls._instance = Producer(config)
        return cls._instance

    @classmethod
    async def start(cls):
        """Initialize the Kafka producer."""
        if not settings.KAFKA_ENABLED:
            logger.info("Kafka is disabled, skipping producer initialization")
            return

        if not cls._started:
            producer = cls.get_producer()
            if producer:
                cls._started = True
                logger.info(
                    f"Kafka producer initialized: {settings.KAFKA_BOOTSTRAP_SERVERS}"
                )

    @classmethod
    async def stop(cls):
        """Flush and close the Kafka producer."""
        if cls._started and cls._instance:
            with cls._lock:
                if cls._instance:
                    cls._instance.flush(timeout=10)
                    cls._instance = None
                    cls._started = False
                    logger.info("Kafka producer stopped")

    @classmethod
    def flush(cls, timeout: float = 10.0):
        """Flush pending messages."""
        if cls._instance:
            cls._instance.flush(timeout=timeout)

    @classmethod
    def poll(cls, timeout: float = 0):
        """Poll for delivery callbacks."""
        if cls._instance:
            cls._instance.poll(timeout)


class KafkaConsumer:
    """
    Kafka consumer for subscribing to topics from other services.

    Runs in a background thread to avoid blocking the main event loop.
    """

    _instance: Optional[Consumer] = None
    _thread: Optional[Thread] = None
    _running: bool = False
    _lock: Lock = Lock()
    _handlers: dict[str, list[Callable]] = {}

    @classmethod
    def get_consumer(cls) -> Optional[Consumer]:
        """Get or create the Kafka consumer instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    config = {
                        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                        "group.id": "leave-management-service-group",
                        "client.id": "leave-management-service-consumer",
                        "auto.offset.reset": "earliest",
                        "enable.auto.commit": True,
                        "auto.commit.interval.ms": 5000,
                    }
                    cls._instance = Consumer(config)
        return cls._instance

    @classmethod
    def register_handler(cls, topic: str, handler: Callable):
        """
        Register a handler function for a specific topic.

        Args:
            topic: Kafka topic name
            handler: Async or sync function to handle messages
        """
        if topic not in cls._handlers:
            cls._handlers[topic] = []
        cls._handlers[topic].append(handler)
        logger.info(f"Registered handler for topic: {topic}")

    @classmethod
    def _consume_loop(cls):
        """Background thread that consumes messages."""
        consumer = cls.get_consumer()
        if not consumer:
            logger.error("Failed to create consumer")
            return

        topics = list(cls._handlers.keys())
        if not topics:
            logger.warning("No topics to subscribe to")
            return

        consumer.subscribe(topics)
        logger.info(f"Subscribed to topics: {topics}")

        while cls._running:
            try:
                msg = consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    logger.error(f"Consumer error: {msg.error()}")
                    continue

                topic = msg.topic()
                value = msg.value()

                if value:
                    try:
                        data = json.loads(value.decode("utf-8"))
                        handlers = cls._handlers.get(topic, [])

                        for handler in handlers:
                            try:
                                handler(data)
                            except Exception as e:
                                logger.error(f"Handler error for topic {topic}: {e}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode message: {e}")

            except Exception as e:
                logger.error(f"Consumer loop error: {e}")

        consumer.close()
        logger.info("Consumer closed")

    @classmethod
    async def start(cls):
        """Start the consumer in a background thread."""
        if not settings.KAFKA_ENABLED:
            logger.info("Kafka is disabled, skipping consumer initialization")
            return

        if cls._running:
            logger.warning("Consumer already running")
            return

        if not cls._handlers:
            logger.info("No handlers registered, skipping consumer start")
            return

        cls._running = True
        cls._thread = Thread(target=cls._consume_loop, daemon=True)
        cls._thread.start()
        logger.info("Kafka consumer started")

    @classmethod
    async def stop(cls):
        """Stop the consumer."""
        if cls._running:
            cls._running = False
            if cls._thread:
                cls._thread.join(timeout=5.0)
                cls._thread = None
            with cls._lock:
                cls._instance = None
            logger.info("Kafka consumer stopped")


async def publish_event(topic: str, event: EventEnvelope) -> bool:
    """
    Publish an event to a Kafka topic.

    Args:
        topic: Kafka topic name
        event: Event envelope to publish

    Returns:
        True if event was queued successfully, False otherwise
    """
    if not settings.KAFKA_ENABLED:
        logger.debug(f"Kafka disabled, skipping event: {event.event_type}")
        return False

    try:
        producer = KafkaProducer.get_producer()
        if not producer:
            logger.error("Kafka producer not initialized")
            return False

        event_dict = event.model_dump()
        message = json.dumps(event_dict, default=json_serializer).encode("utf-8")

        producer.produce(
            topic=topic,
            value=message,
            key=event.event_id.encode("utf-8"),
            callback=delivery_callback,
        )

        producer.poll(0)

        logger.info(
            f"Published event {event.event_type} to topic {topic} "
            f"(event_id: {event.event_id})"
        )
        return True

    except KafkaException as e:
        logger.error(f"Kafka error publishing event: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error publishing event: {e}")
        return False


async def publish_event_sync(
    topic: str, event: EventEnvelope, timeout: float = 10.0
) -> bool:
    """
    Publish an event and wait for delivery confirmation.

    Args:
        topic: Kafka topic name
        event: Event envelope to publish
        timeout: Timeout in seconds to wait for delivery

    Returns:
        True if event was delivered successfully, False otherwise
    """
    if not settings.KAFKA_ENABLED:
        logger.debug(f"Kafka disabled, skipping event: {event.event_type}")
        return False

    try:
        producer = KafkaProducer.get_producer()
        if not producer:
            logger.error("Kafka producer not initialized")
            return False

        event_dict = event.model_dump()
        message = json.dumps(event_dict, default=json_serializer).encode("utf-8")

        delivery_result = {"delivered": False, "error": None}

        def sync_callback(err, msg):
            if err is not None:
                delivery_result["error"] = err
                logger.error(f"Message delivery failed: {err}")
            else:
                delivery_result["delivered"] = True
                logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")

        producer.produce(
            topic=topic,
            value=message,
            key=event.event_id.encode("utf-8"),
            callback=sync_callback,
        )

        producer.flush(timeout=timeout)

        if delivery_result["delivered"]:
            logger.info(
                f"Published event {event.event_type} to topic {topic} "
                f"(event_id: {event.event_id})"
            )
            return True
        else:
            logger.error(f"Failed to deliver event: {delivery_result['error']}")
            return False

    except KafkaException as e:
        logger.error(f"Kafka error publishing event: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error publishing event: {e}")
        return False
