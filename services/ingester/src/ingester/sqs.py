import boto3
import json
from datetime import datetime
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

from .config import config

logger = logging.getLogger(__name__)

sqs_client = boto3.client('sqs', region_name=config.AWS_REGION)


@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3)
)
def send_ingestion_message(
    camera_id: str,
    s3_bucket: str,
    s3_key: str,
    metadata: dict
) -> str:
    """Envia mensagem para fila SQS apos upload."""
    message_body = {
        "camera_id": camera_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "s3_bucket": s3_bucket,
        "s3_key": s3_key,
        "metadata": metadata
    }

    response = sqs_client.send_message(
        QueueUrl=config.SQS_INGESTION_QUEUE_URL,
        MessageBody=json.dumps(message_body),
        MessageAttributes={
            'Source': {'DataType': 'String', 'StringValue': 'ingester-rtsp-v2'},
            'CameraId': {'DataType': 'String', 'StringValue': camera_id}
        }
    )
    logger.info(f"SQS message: {response['MessageId']}")
    return response['MessageId']
