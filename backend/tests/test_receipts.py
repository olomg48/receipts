from datetime import datetime, timezone
from decimal import Decimal
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
    monkeypatch.setenv("SINGLE_USER_EMAIL", "owner@example.com")
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


def test_receipt_history_includes_all_receipts_for_single_owner(receipt_client):
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
    assert {row["original_filename"] for row in response.json()} == {
        "mine.pdf",
        "theirs.pdf",
    }


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


def test_receipt_details_include_header_and_ordered_product_lines(receipt_client):
    client, engine, owner, _ = receipt_client
    receipt_id = uuid.uuid4()
    purchased_at = datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc)
    with Session(engine) as session:
        receipt = Receipt(
            id=receipt_id,
            uploaded_by_id=owner.id,
            retailer_id=1,
            original_filename="receipt.pdf",
            storage_key="receipts/details/original.pdf",
            receipt_number="R-123",
            purchased_at=purchased_at,
            currency="PLN",
            subtotal=Decimal("12.50"),
            discount_total=Decimal("1.25"),
            total_paid=Decimal("11.25"),
            status="needs_review",
        )
        product = Product(code="Milk-1L", normalized_code="milk-1l")
        candidate = ProductCodeCandidate(
            observed_code="Unknown-1",
            normalized_code="unknown-1",
            status="pending",
        )
        session.add_all((receipt, product, candidate))
        session.flush()
        session.add_all(
            (
                ReceiptItem(
                    receipt_id=receipt_id,
                    line_number=2,
                    raw_product_code="Unknown-1",
                    product_code_candidate_id=candidate.id,
                    quantity=Decimal("1"),
                    unit="pcs",
                    line_total=Decimal("4.00"),
                    discount_amount=Decimal("0"),
                ),
                ReceiptItem(
                    receipt_id=receipt_id,
                    line_number=1,
                    raw_product_code="Milk1L",
                    product_id=product.id,
                    quantity=Decimal("2"),
                    unit="pcs",
                    unit_price=Decimal("6.25"),
                    line_total=Decimal("12.50"),
                    discount_amount=Decimal("1.25"),
                ),
            )
        )
        session.add(
            ReceiptJob(
                receipt_id=receipt_id,
                status="done",
                stage="complete",
            )
        )
        session.commit()

    response = client.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["retailer_name"] == "Biedronka"
    assert body["receipt_number"] == "R-123"
    assert body["subtotal"] == "12.50"
    assert body["discount_total"] == "1.25"
    assert body["total_paid"] == "11.25"
    assert [item["line_number"] for item in body["items"]] == [1, 2]
    assert body["items"][0] == {
        "line_number": 1,
        "product_code": "Milk1L",
        "canonical_product_code": "Milk-1L",
        "needs_product_review": False,
        "quantity": "2.000",
        "unit": "pcs",
        "unit_price": "6.25",
        "line_total": "12.50",
        "discount_amount": "1.25",
    }
    assert body["items"][1]["product_code"] == "Unknown-1"
    assert body["items"][1]["canonical_product_code"] is None
    assert body["items"][1]["needs_product_review"] is True


def test_analytics_include_all_owners_and_only_completed_receipts(receipt_client):
    client, engine, owner, other_user = receipt_client
    purchased_at = datetime.now(timezone.utc)
    with Session(engine) as session:
        milk = Product(code="Milk-1L", normalized_code="milk-1l")
        owner_receipt = Receipt(
            uploaded_by_id=owner.id,
            retailer_id=1,
            original_filename="complete.pdf",
            storage_key="receipts/complete/original.pdf",
            purchased_at=purchased_at,
            currency="PLN",
            subtotal=Decimal("12.00"),
            discount_total=Decimal("1.25"),
            total_paid=Decimal("10.75"),
            status="complete",
        )
        euro_receipt = Receipt(
            uploaded_by_id=owner.id,
            retailer_id=2,
            original_filename="euro.png",
            storage_key="receipts/euro/original.png",
            purchased_at=purchased_at,
            currency="EUR",
            discount_total=Decimal("0.50"),
            total_paid=Decimal("4.50"),
            status="complete",
        )
        review_receipt = Receipt(
            uploaded_by_id=owner.id,
            retailer_id=1,
            original_filename="review.pdf",
            storage_key="receipts/review/original.pdf",
            purchased_at=purchased_at,
            total_paid=Decimal("500.00"),
            status="needs_review",
        )
        private_receipt = Receipt(
            uploaded_by_id=other_user.id,
            retailer_id=1,
            original_filename="private.pdf",
            storage_key="receipts/private/original.pdf",
            purchased_at=purchased_at,
            total_paid=Decimal("900.00"),
            status="complete",
        )
        session.add_all((milk, owner_receipt, euro_receipt, review_receipt, private_receipt))
        session.flush()
        session.add_all(
            (
                ReceiptItem(
                    receipt_id=owner_receipt.id,
                    line_number=1,
                    raw_product_code="Milk-1L",
                    product_id=milk.id,
                    quantity=Decimal("2"),
                    unit="pcs",
                    discount_amount=Decimal("1.25"),
                ),
                ReceiptItem(
                    receipt_id=review_receipt.id,
                    line_number=1,
                    raw_product_code="Unreviewed",
                    quantity=Decimal("1"),
                    discount_amount=Decimal("10.00"),
                ),
                ReceiptItem(
                    receipt_id=private_receipt.id,
                    line_number=1,
                    raw_product_code="Private",
                    quantity=Decimal("99"),
                    discount_amount=Decimal("99.00"),
                ),
            )
        )
        session.commit()

    response = client.get("/analytics")

    assert response.status_code == 200
    body = response.json()
    assert body["currency_totals"] == [
        {
            "currency": "EUR",
            "receipt_count": 1,
            "total_paid": "4.50",
            "discount_total": "0.50",
        },
        {
            "currency": "PLN",
            "receipt_count": 2,
            "total_paid": "910.75",
            "discount_total": "1.25",
        },
    ]
    current_month = purchased_at.strftime("%Y-%m")
    pln_month = next(
        row
        for row in body["monthly_totals"]
        if row["month"] == current_month and row["currency"] == "PLN"
    )
    assert pln_month["receipt_count"] == 2
    assert pln_month["total_paid"] == "910.75"
    assert [product["product_code"] for product in body["top_products"]] == [
        "Milk-1L",
        "Private",
    ]
    assert body["top_products"][0]["purchase_lines"] == 1
    assert body["top_products"][0]["quantity"] == "2.000"
    assert body["top_products"][0]["discount_total"] == "1.25"


def test_receipt_history_is_available_without_login(receipt_client):
    client, _, _, _ = receipt_client
    response = client.get("/receipts")
    assert response.status_code == 200
    assert response.json() == []


def test_product_review_endpoints_are_available_without_login(receipt_client):
    client, _, _, _ = receipt_client

    response = client.get("/admin/product-candidates")

    assert response.status_code == 200
    assert response.json() == []


def test_product_review_resolution_updates_receipt_without_login(receipt_client):
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
