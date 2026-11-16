import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base
from app.models import Receipt, ReceiptJob, Retailer, User


@pytest.fixture
def receipt_client(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "https://receipts.example.test")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    owner = User(id=uuid.uuid4(), email="owner@example.com")
    other_user = User(id=uuid.uuid4(), email="other@example.com")
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            (
                owner,
                other_user,
                Retailer(id=1, code="biedronka", display_name="Biedronka"),
                Retailer(id=2, code="lidl", display_name="Lidl"),
            )
        )
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    main.app.dependency_overrides[main.get_db_session] = override_session
    main.app.dependency_overrides[main.get_current_user] = lambda: owner
    client = TestClient(main.app)
    yield client, engine, owner, other_user
    main.app.dependency_overrides.clear()
    engine.dispose()


def test_upload_stores_file_and_creates_receipt_job(receipt_client, monkeypatch):
    client, engine, owner, _ = receipt_client
    stored = []
    monkeypatch.setattr(
        main,
        "put_object",
        lambda key, data, content_type: stored.append((key, data, content_type)),
    )

    response = client.post(
        "/receipts",
        data={"retailer_code": "biedronka"},
        files={"file": ("receipt.pdf", b"%PDF-1.7 receipt", "application/pdf")},
        headers={"origin": "https://receipts.example.test"},
    )

    assert response.status_code == 202
    receipt_id = uuid.UUID(response.json()["id"])
    assert response.json()["status"] == "queued"
    assert len(stored) == 1
    assert stored[0][1:] == (b"%PDF-1.7 receipt", "application/pdf")

    with Session(engine) as session:
        receipt = session.get(Receipt, receipt_id)
        job = session.scalar(select(ReceiptJob).where(ReceiptJob.receipt_id == receipt_id))
        assert receipt is not None
        assert receipt.uploaded_by_id == owner.id
        assert receipt.status == "queued"
        assert job is not None
        assert job.status == "pending"


def test_upload_rejects_wrong_retailer_format_without_storing(receipt_client, monkeypatch):
    client, _, _, _ = receipt_client
    stored = []
    monkeypatch.setattr(main, "put_object", lambda *args: stored.append(args))

    response = client.post(
        "/receipts",
        data={"retailer_code": "lidl"},
        files={"file": ("receipt.pdf", b"%PDF-1.7 receipt", "application/pdf")},
        headers={"origin": "https://receipts.example.test"},
    )

    assert response.status_code == 422
    assert stored == []


def test_upload_rejects_cross_origin_request(receipt_client, monkeypatch):
    client, _, _, _ = receipt_client
    monkeypatch.setenv("PUBLIC_APP_ORIGIN", "https://receipts.example.test")
    stored = []
    monkeypatch.setattr(main, "put_object", lambda *args: stored.append(args))

    response = client.post(
        "/receipts",
        data={"retailer_code": "biedronka"},
        files={"file": ("receipt.pdf", b"%PDF-1.7 receipt", "application/pdf")},
        headers={"origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert stored == []


def test_receipt_history_is_scoped_to_signed_in_user(receipt_client):
    client, engine, owner, other_user = receipt_client
    with Session(engine) as session:
        session.add_all(
            (
                Receipt(
                    uploaded_by_id=owner.id,
                    retailer_id=1,
                    original_filename="mine.pdf",
                    storage_key="receipts/mine/original.pdf",
                    status="queued",
                ),
                Receipt(
                    uploaded_by_id=other_user.id,
                    retailer_id=1,
                    original_filename="theirs.pdf",
                    storage_key="receipts/theirs/original.pdf",
                    status="queued",
                ),
            )
        )
        session.commit()

    response = client.get("/receipts")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["original_filename"] == "mine.pdf"


def test_upload_requires_a_session_when_auth_is_configured(
    receipt_client,
    monkeypatch,
):
    client, _, _, _ = receipt_client
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    main.app.dependency_overrides.pop(main.get_current_user)

    response = client.get("/receipts")

    assert response.status_code == 401
