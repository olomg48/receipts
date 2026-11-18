import json
import uuid

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import worker
from app.db import Base
from app.models import (
    ProductCodeCandidate,
    Receipt,
    ReceiptItem,
    ReceiptJob,
    Retailer,
    User,
)
from app.receipt_schemas import ExtractedReceipt


def _create_worker_database(stage=None, extraction_storage_key=None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    user_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    job_id = uuid.uuid4()
    source_key = f"receipts/{receipt_id}/original.pdf"
    with Session(engine) as session:
        session.add_all(
            [
                User(id=user_id),
                Retailer(id=1, code="biedronka", display_name="Biedronka"),
                Receipt(
                    id=receipt_id,
                    uploaded_by_id=user_id,
                    retailer_id=1,
                    original_filename="receipt.pdf",
                    storage_key=source_key,
                    status="queued",
                ),
                ReceiptJob(
                    id=job_id,
                    receipt_id=receipt_id,
                    stage=stage,
                    extraction_storage_key=extraction_storage_key,
                ),
            ]
        )
        session.commit()
    return engine, receipt_id, job_id, source_key


def test_extraction_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ExtractedReceipt.model_validate(
            {
                "currency": "PLN",
                "discount_total": 0,
                "items": [
                    {
                        "line_number": 1,
                        "product_code": "ABC",
                        "quantity": 1,
                        "unknown_value": True,
                    }
                ],
            }
        )


def test_mistral_ocr_posts_the_receipt_as_a_pdf_data_url(monkeypatch):
    requests = []
    result = {"pages": [{"markdown": "Receipt line"}]}

    def responder(request):
        requests.append(request)
        return httpx.Response(200, json=result)

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        worker,
        "_client",
        lambda stage: httpx.Client(
            base_url=worker.MISTRAL_API_BASE,
            transport=httpx.MockTransport(responder),
        ),
    )

    markdown = worker._run_ocr(b"%PDF-1.7", "pdf")

    assert markdown == "Receipt line"
    assert requests[0].url.path == "/v1/ocr"
    payload = json.loads(requests[0].content)
    assert payload["document"]["type"] == "document_url"
    assert payload["document"]["document_url"].startswith("data:application/pdf;base64,")


def test_mistral_ocr_posts_the_receipt_as_a_png_data_url(monkeypatch):
    requests = []

    def responder(request):
        requests.append(request)
        return httpx.Response(200, json={"pages": [{"markdown": "Receipt line"}]})

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        worker,
        "_client",
        lambda stage: httpx.Client(
            base_url=worker.MISTRAL_API_BASE,
            transport=httpx.MockTransport(responder),
        ),
    )

    assert worker._run_ocr(b"\x89PNG", "png") == "Receipt line"
    payload = json.loads(requests[0].content)
    assert payload["document"]["type"] == "image_url"
    assert payload["document"]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    "result",
    [
        {"pages": "not a list"},
        {"pages": [None]},
        {"pages": [{"markdown": []}]},
    ],
)
def test_mistral_ocr_rejects_malformed_page_data(monkeypatch, result):
    def responder(_request):
        return httpx.Response(200, json=result)

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        worker,
        "_client",
        lambda stage: httpx.Client(
            base_url=worker.MISTRAL_API_BASE,
            transport=httpx.MockTransport(responder),
        ),
    )

    with pytest.raises(worker.ProcessingError, match="invalid response"):
        worker._run_ocr(b"\x89PNG", "png")


def test_mistral_extraction_validates_structured_output(monkeypatch):
    output = {
        "receipt_number": "R-1",
        "purchased_at": None,
        "currency": "PLN",
        "subtotal": "10.00",
        "discount_total": "1.00",
        "total_paid": "9.00",
        "items": [
            {
                "line_number": 1,
                "product_code": "ABC",
                "quantity": "1",
                "unit": None,
                "unit_price": "10.00",
                "line_total": "9.00",
                "discount_amount": "1.00",
            }
        ],
    }

    def responder(_request):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        worker,
        "_client",
        lambda stage: httpx.Client(
            base_url=worker.MISTRAL_API_BASE,
            transport=httpx.MockTransport(responder),
        ),
    )

    raw_json, parsed = worker._run_extraction("text", "Biedronka")

    assert json.loads(raw_json) == output
    assert parsed.items[0].product_code == "ABC"
    assert parsed.total_paid == 9


def test_mistral_extraction_reports_schema_path_without_receipt_values(monkeypatch):
    output = {
        "receipt_number": "sensitive-receipt-number",
        "items": [{"line_number": 1, "quantity": "1"}],
    }

    def responder(_request):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        worker,
        "_client",
        lambda stage: httpx.Client(
            base_url=worker.MISTRAL_API_BASE,
            transport=httpx.MockTransport(responder),
        ),
    )

    with pytest.raises(worker.ProcessingError) as error:
        worker._run_extraction("text", "Biedronka")

    assert "items.0.product_code: missing" in str(error.value)
    assert "sensitive-receipt-number" not in str(error.value)


def test_process_next_job_saves_artifacts_and_persists_extracted_receipt(monkeypatch):
    engine, receipt_id, job_id, source_key = _create_worker_database()

    objects = {source_key: b"%PDF-1.7"}
    written_objects = {}
    extraction = ExtractedReceipt.model_validate(
        {
            "receipt_number": "R-1",
            "currency": "PLN",
            "subtotal": "10.00",
            "discount_total": "1.00",
            "total_paid": "9.00",
            "items": [
                {
                    "line_number": 1,
                    "product_code": "ABC",
                    "quantity": "1",
                    "unit_price": "10.00",
                    "line_total": "9.00",
                    "discount_amount": "1.00",
                }
            ],
        }
    )
    raw_json = extraction.model_dump_json()

    monkeypatch.setattr(worker, "get_engine", lambda: engine)
    monkeypatch.setattr(
        worker, "pg_insert", lambda model: sqlite_insert(model.__table__)
    )
    monkeypatch.setattr(worker, "get_object", lambda key: objects[key])

    def put_object(key, data, content_type):
        objects[key] = data
        written_objects[key] = (data, content_type)

    monkeypatch.setattr(worker, "put_object", put_object)
    monkeypatch.setattr(worker, "_run_ocr", lambda data, extension: "# Receipt")
    monkeypatch.setattr(
        worker,
        "_run_extraction",
        lambda markdown, retailer: (raw_json, extraction),
    )

    assert worker.process_next_job() is True

    markdown_key = f"receipts/{receipt_id}/ocr.md"
    extraction_key = f"receipts/{receipt_id}/extraction.json"
    assert written_objects[markdown_key] == (
        b"# Receipt",
        "text/markdown; charset=utf-8",
    )
    assert json.loads(written_objects[extraction_key][0])["receipt_number"] == "R-1"
    assert written_objects[extraction_key][1] == "application/json"

    with Session(engine) as session:
        job = session.get(ReceiptJob, job_id)
        receipt = session.get(Receipt, receipt_id)
        item = session.query(ReceiptItem).filter_by(receipt_id=receipt_id).one()
        candidate = session.query(ProductCodeCandidate).one()
        assert job.status == "done"
        assert job.stage == "complete"
        assert job.ocr_storage_key == markdown_key
        assert job.extraction_storage_key == extraction_key
        assert receipt.status == "needs_review"
        assert receipt.total_paid == 9
        assert item.raw_product_code == "ABC"
        assert item.discount_amount == 1
        assert candidate.observed_code == "ABC"

    engine.dispose()


@pytest.mark.parametrize("stored_result", [b"\xff", b"not-json"])
def test_process_next_job_retries_when_saved_extraction_is_invalid(
    monkeypatch, stored_result
):
    extraction_key = "receipts/receipt-id/extraction.json"
    engine, receipt_id, job_id, _ = _create_worker_database(
        stage="persist",
        extraction_storage_key=extraction_key,
    )
    monkeypatch.setattr(worker, "get_engine", lambda: engine)
    monkeypatch.setattr(
        worker,
        "get_object",
        lambda key: stored_result if key == extraction_key else b"%PDF-1.7",
    )

    assert worker.process_next_job() is True

    with Session(engine) as session:
        job = session.get(ReceiptJob, job_id)
        receipt = session.get(Receipt, receipt_id)
        assert job.status == "pending"
        assert job.stage == "persist"
        assert job.last_error == "Stored extraction result is invalid"
        assert receipt.status == "queued"

    engine.dispose()
