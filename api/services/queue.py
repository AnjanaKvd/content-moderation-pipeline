import os
import json
import logging
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.management import ServiceBusAdministrationClient
from azure.servicebus import ServiceBusMessage

logger = logging.getLogger(__name__)


class ModerationQueue:
    def __init__(self, connection_string: str, queue_name: str):
        self.connection_string = connection_string
        self.queue_name = queue_name
        self.client = ServiceBusClient.from_connection_string(
            conn_str=self.connection_string
        )
        self.sender = self.client.get_queue_sender(queue_name=self.queue_name)

    async def publish_batch(self, job_id: str, comments: list[dict]) -> int:
        total = len(comments)
        messages_published = 0

        try:
            # Chunk into groups of 100
            for i in range(0, total, 100):
                chunk = comments[i : i + 100]
                batch_messages = []

                for j, comment in enumerate(chunk):
                    index = i + j
                    body_dict = {
                        "job_id": job_id,
                        "comment_text": comment.get("comment"),
                        "comment_hash": comment.get("comment_hash"),
                        "index": index,
                        "total": total,
                    }

                    platform = comment.get("platform", "unknown")

                    msg = ServiceBusMessage(
                        body=json.dumps(body_dict),
                        message_id=f"{job_id}-{index}",
                        subject="moderation_request",
                        application_properties={
                            "job_id": job_id,
                            "platform": platform if platform else "unknown",
                        },
                    )
                    batch_messages.append(msg)

                await self.sender.send_messages(batch_messages)
                messages_published += len(batch_messages)

            return messages_published
        except Exception as e:
            logger.error(f"Failed to publish batch to Service Bus: {e}")
            raise

    async def ping(self) -> bool:
        try:
            admin_client = ServiceBusAdministrationClient.from_connection_string(
                self.connection_string
            )
            admin_client.get_queue(self.queue_name)
            admin_client.close()
            return True
        except Exception as e:
            logger.warning(f"Service Bus ping failed: {e}")
            return False

    async def get_queue_depth(self) -> int:
        try:
            admin_client = ServiceBusAdministrationClient.from_connection_string(
                self.connection_string
            )
            props = admin_client.get_queue_runtime_properties(self.queue_name)
            admin_client.close()
            return props.active_message_count
        except Exception as e:
            logger.error(f"Failed to get queue depth: {e}")
            return -1

    async def close(self):
        await self.sender.close()
        await self.client.close()


class NullQueue:
    def __init__(self):
        logger.warning("Service Bus not configured, queue disabled")

    async def ping(self) -> bool:
        return False

    async def publish_batch(self, job_id: str, comments: list[dict]) -> int:
        logger.info(
            f"[NullQueue] Published {len(comments)} messages for job_id {job_id}"
        )
        return len(comments)

    async def get_queue_depth(self) -> int:
        return 0

    async def close(self):
        pass


_queue = None


def get_queue() -> ModerationQueue | NullQueue:
    global _queue
    if _queue is None:
        conn_str = os.environ.get("SERVICEBUS_CONNECTION_STRING")
        queue_name = os.environ.get("SERVICEBUS_QUEUE_NAME", "moderation-queue")

        if conn_str:
            try:
                _queue = ModerationQueue(
                    connection_string=conn_str, queue_name=queue_name
                )
                logger.info("ModerationQueue initialized successfully.")
            except Exception as e:
                logger.error(
                    f"Failed to initialize ModerationQueue, falling back to NullQueue: {e}"
                )
                _queue = NullQueue()
        else:
            _queue = NullQueue()

    return _queue
