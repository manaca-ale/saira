import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
from io import BytesIO
from datetime import datetime

from . import config

logger = logging.getLogger(__name__)

s3_client = boto3.client("s3", region_name=config.AWS_REGION)

transfer_config = TransferConfig(
    multipart_threshold=1024 * 1024 * 10,
    max_concurrency=8,
    use_threads=True
)


@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3)
)
def upload_image_to_s3(
    data: bytes,
    bucket: str,
    key: str,
    content_type: str = "image/jpeg"
) -> str:
    """Upload de bytes para S3 com retry."""
    if not config.ENABLE_S3:
        raise RuntimeError("S3 is disabled (ENABLE_S3=0)")
    s3_client.upload_fileobj(
        Fileobj=BytesIO(data),
        Bucket=bucket,
        Key=key,
        ExtraArgs={
            'ContentType': content_type,
            'Metadata': {
                'source': 'ingester-rtsp-v2',
                'upload-timestamp': datetime.utcnow().isoformat()
            }
        }
    )
    logger.info(f"Upload: s3://{bucket}/{key}")
    return f"s3://{bucket}/{key}"
