import json
import logging
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from . import config
from .storage import StorageRef

logger = logging.getLogger(__name__)


def _client():
    return boto3.client("sqs", region_name=config.AWS_REGION)


@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
)
def send_ingestion_message(
    camera_id: str,
    storage: StorageRef,
    metadata: dict,
) -> str:
    """Envia mensagem para fila SQS após armazenar a imagem (S3 ou local)."""
    if not config.ENABLE_SQS:
        logger.info("SQS disabled (ENABLE_SQS=0) - skipping message")
        return ""
    if not config.SQS_INGESTION_QUEUE_URL:
        raise RuntimeError("SQS_INGESTION_QUEUE_URL not configured")

    message_body = {
        "camera_id": camera_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "storage": {
            "backend": storage.backend,
            "uri": storage.uri,
            "bucket": storage.bucket,
            "key": storage.key,
            "abs_path": storage.abs_path,
            "rel_path": storage.rel_path,
        },
        "metadata": metadata,
    }

    response = _client().send_message(
        QueueUrl=config.SQS_INGESTION_QUEUE_URL,
        MessageBody=json.dumps(message_body),
        MessageAttributes={
            "Source": {"DataType": "String", "StringValue": "ingester-rtsp-v2"},
            "CameraId": {"DataType": "String", "StringValue": camera_id},
        },
    )
    logger.info(f"SQS message: {response['MessageId']}")
    return response["MessageId"]

