from __future__ import annotations

import os
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error


class StorageNotConfiguredError(RuntimeError):
    pass


class StorageBucketUnavailableError(RuntimeError):
    pass


def get_storage_client() -> tuple[Minio, str]:
    endpoint_url = os.getenv("S3_ENDPOINT_URL")
    access_key = os.getenv("S3_ACCESS_KEY_ID")
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
    bucket = os.getenv("S3_BUCKET")
    if not all((endpoint_url, access_key, secret_key, bucket)):
        raise StorageNotConfiguredError(
            "S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, "
            "and S3_BUCKET must be configured"
        )

    parsed = urlsplit(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StorageNotConfiguredError("S3_ENDPOINT_URL must be an HTTP(S) URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise StorageNotConfiguredError(
            "S3_ENDPOINT_URL must not include a path, query, or fragment"
        )

    client = Minio(
        parsed.netloc,
        access_key=access_key,
        secret_key=secret_key,
        secure=parsed.scheme == "https",
        region=os.getenv("S3_REGION") or None,
    )
    return client, bucket


def check_storage_connection() -> None:
    client, bucket = get_storage_client()
    if not client.bucket_exists(bucket):
        raise StorageBucketUnavailableError(
            f"Configured object storage bucket {bucket!r} does not exist"
        )


def put_object(
    object_key: str,
    data: bytes,
    content_type: str,
) -> None:
    client, bucket = get_storage_client()
    from io import BytesIO

    client.put_object(
        bucket,
        object_key,
        BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def get_object(object_key: str) -> bytes:
    client, bucket = get_storage_client()
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_object(object_key: str) -> None:
    client, bucket = get_storage_client()
    client.remove_object(bucket, object_key)


__all__ = [
    "S3Error",
    "StorageBucketUnavailableError",
    "StorageNotConfiguredError",
    "check_storage_connection",
    "delete_object",
    "get_object",
    "get_storage_client",
    "put_object",
]
