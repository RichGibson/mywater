import os
import uuid

import boto3

MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
}


class PhotoValidationError(ValueError):
    pass


def validate_photo(content, content_type):
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise PhotoValidationError(
            f"unsupported photo type '{content_type}'; allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
        )
    if len(content) > MAX_PHOTO_SIZE_BYTES:
        raise PhotoValidationError(
            f"photo exceeds {MAX_PHOTO_SIZE_BYTES} byte limit ({len(content)} bytes)"
        )


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def upload_photo(content, content_type):
    validate_photo(content, content_type)
    extension = ALLOWED_CONTENT_TYPES[content_type]
    key = f"{uuid.uuid4()}.{extension}"
    bucket = os.environ["R2_BUCKET_NAME"]
    client = _r2_client()
    client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=content_type)
    public_base_url = os.environ["R2_PUBLIC_BASE_URL"]
    return f"{public_base_url.rstrip('/')}/{key}"
