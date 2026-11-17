import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base
from app.models import (
    Product,
    ProductCodeCandidate,
    Receipt,
    ReceiptItem,
    ReceiptJob,
    Retailer,
    User,
)


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


def test_receipt_history_includes_failure_reason(receipt_client):
    client, engine, owner, _ = receipt_client
    receipt_id = uuid.uuid4()
    with Session(engine) as session:
        session.add_all(
            (
                Receipt(
                    id=receipt_id,
                    uploaded_by_id=owner.id,
                    retailer_id=1,
                    original_filename="failed.pdf",
                    storage_key="receipts/failed/original.pdf",
                    status="failed",
                ),
                ReceiptJob(
                    receipt_id=receipt_id,
                    status="failed",
                    stage="ocr",
                    last_error="OCR provider could not be reached",
                ),
            )
        )
        session.commit()

    response = client.get("/receipts")

    assert response.status_code == 200
    assert response.json()[0]["stage"] == "ocr"
    assert response.json()[0]["error"] == "OCR provider could not be reached"


def test_upload_requires_a_session_when_auth_is_configured(
    receipt_client,
    monkeypatch,
):
    client, _, _, _ = receipt_client
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    main.app.dependency_overrides.pop(main.get_current_user)

    response = client.get("/receipts")

    assert response.status_code == 401


def test_product_review_endpoints_require_admin(receipt_client):
    client, _, _, _ = receipt_client

    response = client.get("/admin/product-candidates")

    assert response.status_code == 403


def test_admin_can_resolve_candidate_and_complete_receipt(receipt_client):
    client, engine, owner, _ = receipt_client
    owner.is_admin = True
    with Session(engine) as session:
        receipt = Receipt(
            uploaded_by_id=owner.id,
            retailer_id=1,
            original_filename="receipt.pdf",
            storage_key="receipts/review/original.pdf",
            status="needs_review",
        )
        candidate = ProductCodeCandidate(
            observed_code="LechHvdrFree",
            normalized_code="lechhvdrfree",
            status="pending",
        )
        session.add_all((receipt, candidate))
        session.flush()
        session.add(
            ReceiptItem(
                receipt_id=receipt.id,
                line_number=1,
                raw_product_code="LechHvdrFree",
                product_code_candidate_id=candidate.id,
                quantity=1,
                discount_amount=0,
            )
        )
        receipt_id = receipt.id
        candidate_id = candidate.id
        session.commit()

    queue_response = client.get("/admin/product-candidates")
    assert queue_response.status_code == 200
    assert len(queue_response.json()) == 1
    assert queue_response.json()[0]["id"] == str(candidate_id)
    assert queue_response.json()[0]["observed_code"] == "LechHvdrFree"
    assert queue_response.json()[0]["occurrence_count"] == 1

    response = client.post(
        f"/admin/product-candidates/{candidate_id}/resolve",
        json={"resolution_type": "edited_code", "product_code": "LechHydrFree"},
        headers={"origin": "https://receipts.example.test"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["product_code"] == "LechHydrFree"
    with Session(engine) as session:
        saved_candidate = session.get(ProductCodeCandidate, candidate_id)
        saved_product = session.get(Product, uuid.UUID(response.json()["product_id"]))
        saved_item = session.scalar(
            select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id)
        )
        saved_receipt = session.get(Receipt, receipt_id)
        assert saved_candidate is not None
        assert saved_candidate.resolution_type == "edited_code"
        assert saved_candidate.reviewed_by_id == owner.id
        assert saved_product is not None
        assert saved_product.normalized_code == "lechhydrfree"
        assert saved_item is not None
        assert saved_item.product_id == saved_product.id
        assert saved_receipt is not None
        assert saved_receipt.status == "complete"


def test_admin_can_accept_code_as_is(receipt_client):
    client, engine, owner, _ = receipt_client
    owner.is_admin = True
    with Session(engine) as session:
        candidate = ProductCodeCandidate(
            observed_code="FreshMilk-1L",
            normalized_code="freshmilk-1l",
            status="pending",
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    response = client.post(
        f"/admin/product-candidates/{candidate_id}/resolve",
        json={"resolution_type": "accepted_as_is"},
        headers={"origin": "https://receipts.example.test"},
    )

    assert response.status_code == 200
    assert response.json()["product_code"] == "FreshMilk-1L"
    with Session(engine) as session:
        product = session.get(Product, uuid.UUID(response.json()["product_id"]))
        assert product is not None
        assert product.created_by_id == owner.id


def test_admin_can_map_code_to_existing_product(receipt_client):
    client, engine, owner, _ = receipt_client
    owner.is_admin = True
    with Session(engine) as session:
        product = Product(code="Milk-1L", normalized_code="milk-1l")
        candidate = ProductCodeCandidate(
            observed_code="Milk1L",
            normalized_code="milk1l",
            status="pending",
        )
        session.add_all((product, candidate))
        session.commit()
        product_id = product.id
        candidate_id = candidate.id

    response = client.post(
        f"/admin/product-candidates/{candidate_id}/resolve",
        json={"resolution_type": "mapped_existing", "product_id": str(product_id)},
        headers={"origin": "https://receipts.example.test"},
    )

    assert response.status_code == 200
    assert response.json()["product_id"] == str(product_id)
    with Session(engine) as session:
        candidate = session.get(ProductCodeCandidate, candidate_id)
        assert candidate is not None
        assert candidate.canonical_product_id == product_id
        assert candidate.resolution_type == "mapped_existing"


def test_admin_resolution_rejects_cross_origin_request(receipt_client):
    client, engine, owner, _ = receipt_client
    owner.is_admin = True
    with Session(engine) as session:
        candidate = ProductCodeCandidate(
            observed_code="ABC",
            normalized_code="abc",
            status="pending",
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    response = client.post(
        f"/admin/product-candidates/{candidate_id}/resolve",
        json={"resolution_type": "accepted_as_is"},
        headers={"origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    with Session(engine) as session:
        saved = session.get(ProductCodeCandidate, candidate_id)
        assert saved is not None
        assert saved.status == "pending"
