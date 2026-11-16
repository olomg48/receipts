import json

import httpx
import pytest
from pydantic import ValidationError

from app import worker
from app.receipt_schemas import ExtractedReceipt


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
