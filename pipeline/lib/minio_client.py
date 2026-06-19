import os
from io import BytesIO
from pathlib import Path

from minio import Minio


def get_minio_client() -> Minio:
    endpoint = os.getenv("MINIO_ENDPOINT", "http://localhost:9000").replace("http://", "").replace("https://", "")
    secure = os.getenv("MINIO_ENDPOINT", "http://localhost:9000").startswith("https")
    return Minio(
        endpoint,
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=secure,
    )


def get_bucket() -> str:
    return os.getenv("MINIO_BUCKET", "devpulse")


def upload_bytes(data: bytes, object_key: str, content_type: str) -> str:
    client = get_minio_client()
    bucket = get_bucket()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(bucket, object_key, BytesIO(data), len(data), content_type=content_type)
    return object_key


def upload_file(file_path: Path, object_key: str, content_type: str) -> str:
    return upload_bytes(file_path.read_bytes(), object_key, content_type)
