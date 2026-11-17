import pytest

from app import storage


class FakeGarageClient:
    def __init__(self, bucket_exists: bool) -> None:
        self.bucket_exists_result = bucket_exists
        self.checked_bucket: str | None = None

    def bucket_exists(self, bucket: str) -> bool:
        self.checked_bucket = bucket
        return self.bucket_exists_result


def configure_storage(monkeypatch, client: FakeGarageClient) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://garage:3900")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setenv("S3_BUCKET", "receipt-files")
    monkeypatch.setattr(storage, "Minio", lambda *_args, **_kwargs: client)


def test_storage_readiness_checks_the_configured_garage_bucket(monkeypatch) -> None:
    client = FakeGarageClient(bucket_exists=True)
    configure_storage(monkeypatch, client)

    storage.check_storage_connection()

    assert client.checked_bucket == "receipt-files"


def test_storage_readiness_fails_when_bucket_is_missing(monkeypatch) -> None:
    client = FakeGarageClient(bucket_exists=False)
    configure_storage(monkeypatch, client)

    with pytest.raises(storage.StorageBucketUnavailableError):
        storage.check_storage_connection()

    assert client.checked_bucket == "receipt-files"
