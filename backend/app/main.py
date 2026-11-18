from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import PurePosixPath

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from minio.error import S3Error
from sqlalchemy import func, select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from urllib3.exceptions import HTTPError as Urllib3Error

from app.db import (
    DatabaseNotConfiguredError,
    check_database_connection,
    get_db_session,
)
from app.models import (
    Product,
    ProductCodeCandidate,
    Receipt,
    ReceiptItem,
    ReceiptJob,
    Retailer,
    User,
)
from app.product_codes import normalize_product_code
from app.receipt_schemas import ResolveProductCandidateRequest
from app.storage import (
    StorageBucketUnavailableError,
    StorageNotConfiguredError,
    check_storage_connection,
    delete_object,
    put_object,
)


logger = logging.getLogger(__name__)
app = FastAPI(title="Receipt Tracker API", version="0.2.0")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOADS = {
    ("biedronka", ".pdf"): ("application/pdf", b"%PDF-"),
    ("lidl", ".png"): ("image/png", b"\x89PNG\r\n\x1a\n"),
}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _configured(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _require_same_origin(request: Request) -> None:
    expected_origin = _configured("PUBLIC_APP_ORIGIN")
    supplied_origin = request.headers.get("origin")
    if not expected_origin or supplied_origin != expected_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed",
        )


def _get_single_owner(session: Session) -> User:
    email = (_configured("SINGLE_USER_EMAIL") or "owner@local").casefold()
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        user = User(email=email, display_name="Owner", is_admin=True)
        session.add(user)
        session.flush()
    elif not user.is_admin:
        user.is_admin = True
    return user


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    try:
        check_database_connection()
    except DatabaseNotConfiguredError:
        logger.error("Readiness check failed: DATABASE_URL is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured",
        ) from None
    except SQLAlchemyError:
        logger.exception("Readiness check failed: database connection error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from None

    try:
        check_storage_connection()
    except StorageNotConfiguredError:
        logger.error("Readiness check failed: object storage is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured",
        ) from None
    except (
        StorageBucketUnavailableError,
        S3Error,
        Urllib3Error,
        OSError,
    ):
        logger.exception("Readiness check failed: object storage is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        ) from None

    return {"status": "ok"}


def _safe_filename(filename: str | None) -> str:
    leaf = (filename or "receipt").replace("\\", "/").split("/")[-1].strip()
    sanitized = SAFE_FILENAME.sub("_", leaf).strip(" .")
    return (sanitized or "receipt")[:255]


def _validate_upload(
    file: UploadFile,
    retailer_code: str,
) -> tuple[bytes, str, str]:
    filename = _safe_filename(file.filename)
    suffix = PurePosixPath(filename).suffix.lower()
    expected = ALLOWED_UPLOADS.get((retailer_code, suffix))
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Biedronka receipts must be PDF and Lidl receipts must be PNG",
        )

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded file is empty",
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The file exceeds the 10 MB limit",
        )

    content_type, signature = expected
    if not data.startswith(signature):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The file content does not match its format",
        )
    return data, filename, content_type


@app.post("/receipts", status_code=status.HTTP_202_ACCEPTED, tags=["receipts"])
def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    retailer_code: str = Form(...),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_same_origin(request)
    retailer_code = retailer_code.strip().lower()
    validated = _validate_upload(file, retailer_code)
    data, filename, content_type = validated

    retailer = session.scalar(select(Retailer).where(Retailer.code == retailer_code))
    if retailer is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported retailer",
        )

    user = _get_single_owner(session)
    receipt_id = uuid.uuid4()
    storage_key = f"receipts/{receipt_id}/original{PurePosixPath(filename).suffix.lower()}"
    try:
        put_object(storage_key, data, content_type)
    except StorageNotConfiguredError:
        logger.error("Receipt upload rejected: object storage is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Receipt storage is not configured",
        ) from None
    except (S3Error, Urllib3Error, OSError):
        logger.exception("Receipt upload failed while writing object %s", receipt_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Receipt storage is unavailable",
        ) from None

    receipt = Receipt(
        id=receipt_id,
        uploaded_by_id=user.id,
        retailer_id=retailer.id,
        original_filename=filename,
        storage_key=storage_key,
        status="queued",
    )
    job = ReceiptJob(receipt_id=receipt_id, status="pending", stage="ocr")
    session.add_all((receipt, job))
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Failed to queue receipt %s after storing its file", receipt_id)
        try:
            delete_object(storage_key)
        except (StorageNotConfiguredError, S3Error, Urllib3Error, OSError):
            logger.exception("Failed to clean up orphaned receipt object %s", receipt_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The receipt could not be queued",
        ) from None

    return {"id": str(receipt_id), "status": "queued"}


@app.get("/receipts", tags=["receipts"])
def list_receipts(
    session: Session = Depends(get_db_session),
) -> list[dict[str, object]]:
    rows = session.execute(
        select(
            Receipt,
            Retailer.code,
            Retailer.display_name,
            ReceiptJob.stage,
            ReceiptJob.status,
            ReceiptJob.last_error,
        )
        .join(Retailer, Receipt.retailer_id == Retailer.id)
        .outerjoin(ReceiptJob, ReceiptJob.receipt_id == Receipt.id)
        .order_by(Receipt.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": str(receipt.id),
            "retailer_code": retailer_code,
            "retailer_name": retailer_name,
            "original_filename": receipt.original_filename,
            "receipt_number": receipt.receipt_number,
            "purchased_at": receipt.purchased_at.isoformat()
            if receipt.purchased_at
            else None,
            "currency": receipt.currency,
            "total_paid": str(receipt.total_paid) if receipt.total_paid is not None else None,
            "discount_total": str(receipt.discount_total),
            "status": receipt.status,
            "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
            "stage": stage,
            "error": last_error if job_status == "failed" else None,
        }
        for receipt, retailer_code, retailer_name, stage, job_status, last_error in rows
    ]


@app.get("/analytics", tags=["analytics"])
def receipt_analytics(
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    currency_rows = session.execute(
        select(
            Receipt.currency,
            func.count(Receipt.id),
            func.coalesce(func.sum(Receipt.total_paid), 0),
            func.coalesce(func.sum(Receipt.discount_total), 0),
        )
        .where(Receipt.status == "complete")
        .group_by(Receipt.currency)
        .order_by(Receipt.currency)
    ).all()
    currencies = [row[0] for row in currency_rows]
    currency_totals = [
        {
            "currency": currency,
            "receipt_count": receipt_count,
            "total_paid": _money_text(total_paid),
            "discount_total": _money_text(discount_total),
        }
        for currency, receipt_count, total_paid, discount_total in currency_rows
    ]

    now = datetime.now(timezone.utc)
    current_month_index = now.year * 12 + now.month - 1
    month_keys = []
    for month_index in range(current_month_index - 11, current_month_index + 1):
        year, month = divmod(month_index, 12)
        month_keys.append(f"{year:04d}-{month + 1:02d}")
    first_month_year, first_month = divmod(current_month_index - 11, 12)
    period_start = datetime(first_month_year, first_month + 1, 1, tzinfo=timezone.utc)
    next_month_year, next_month = divmod(current_month_index + 1, 12)
    period_end = datetime(next_month_year, next_month + 1, 1, tzinfo=timezone.utc)
    activity_date = func.coalesce(Receipt.purchased_at, Receipt.created_at)
    recent_receipts = session.execute(
        select(
            Receipt.currency,
            Receipt.purchased_at,
            Receipt.created_at,
            Receipt.total_paid,
            Receipt.discount_total,
        ).where(
            Receipt.status == "complete",
            activity_date >= period_start,
            activity_date < period_end,
        )
    ).all()

    monthly_buckets: dict[tuple[str, str], tuple[int, Decimal, Decimal]] = {
        (month, currency): (0, Decimal("0"), Decimal("0"))
        for month in month_keys
        for currency in currencies
    }
    for receipt in recent_receipts:
        purchased_at = receipt.purchased_at or receipt.created_at
        if purchased_at is None:
            raise RuntimeError("A completed receipt has no purchase or creation date")
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.replace(tzinfo=timezone.utc)
        else:
            purchased_at = purchased_at.astimezone(timezone.utc)
        month = purchased_at.strftime("%Y-%m")
        key = (month, receipt.currency)
        receipt_count, total_paid, discount_total = monthly_buckets[key]
        monthly_buckets[key] = (
            receipt_count + 1,
            total_paid + Decimal(str(receipt.total_paid or 0)),
            discount_total + Decimal(str(receipt.discount_total or 0)),
        )

    monthly_totals = []
    for month in month_keys:
        for currency in currencies:
            receipt_count, total_paid, discount_total = monthly_buckets[(month, currency)]
            monthly_totals.append(
                {
                    "month": month,
                    "currency": currency,
                    "receipt_count": receipt_count,
                    "total_paid": _money_text(total_paid),
                    "discount_total": _money_text(discount_total),
                }
            )

    product_code = func.coalesce(Product.code, ReceiptItem.raw_product_code)
    product_rows = session.execute(
        select(
            product_code.label("product_code"),
            ReceiptItem.unit,
            Receipt.currency,
            func.count(ReceiptItem.id).label("purchase_lines"),
            func.count(func.distinct(Receipt.id)).label("receipt_count"),
            func.sum(ReceiptItem.quantity).label("quantity"),
            func.coalesce(func.sum(ReceiptItem.discount_amount), 0).label(
                "discount_total"
            ),
        )
        .select_from(ReceiptItem)
        .join(Receipt, Receipt.id == ReceiptItem.receipt_id)
        .outerjoin(Product, Product.id == ReceiptItem.product_id)
        .where(Receipt.status == "complete")
        .group_by(product_code, ReceiptItem.unit, Receipt.currency)
        .order_by(
            func.count(ReceiptItem.id).desc(),
            product_code,
            ReceiptItem.unit,
            Receipt.currency,
        )
        .limit(10)
    ).all()

    return {
        "currency_totals": currency_totals,
        "monthly_totals": monthly_totals,
        "top_products": [
            {
                "product_code": code,
                "unit": unit,
                "currency": currency,
                "purchase_lines": purchase_lines,
                "receipt_count": receipt_count,
                "quantity": str(quantity or Decimal("0")),
                "discount_total": _money_text(discount_total),
            }
            for (
                code,
                unit,
                currency,
                purchase_lines,
                receipt_count,
                quantity,
                discount_total,
            ) in product_rows
        ],
    }


def _money_text(value: Decimal | int | float | None) -> str:
    amount = Decimal(str(value if value is not None else "0"))
    return format(amount.quantize(Decimal("0.01")), ".2f")


@app.get("/receipts/{receipt_id}", tags=["receipts"])
def get_receipt(
    receipt_id: uuid.UUID,
    session: Session = Depends(get_db_session),
) -> dict[str, str | None]:
    receipt = session.scalar(select(Receipt).where(Receipt.id == receipt_id))
    if receipt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")

    job = session.scalar(
        select(ReceiptJob)
        .where(ReceiptJob.receipt_id == receipt.id)
        .order_by(ReceiptJob.created_at.desc())
    )
    return {
        "id": str(receipt.id),
        "status": receipt.status,
        "stage": job.stage if job else None,
        "error": job.last_error if job and job.status == "failed" else None,
    }


@app.get("/admin/product-candidates", tags=["products"])
def list_product_candidates(
    session: Session = Depends(get_db_session),
) -> list[dict[str, object]]:
    occurrence_count = (
        select(func.count(ReceiptItem.id))
        .where(ReceiptItem.product_code_candidate_id == ProductCodeCandidate.id)
        .scalar_subquery()
    )
    rows = session.execute(
        select(ProductCodeCandidate, occurrence_count.label("occurrence_count"))
        .where(ProductCodeCandidate.status == "pending")
        .order_by(ProductCodeCandidate.created_at, ProductCodeCandidate.id)
    ).all()
    return [
        {
            "id": str(candidate.id),
            "observed_code": candidate.observed_code,
            "occurrence_count": count,
            "created_at": candidate.created_at.isoformat(),
        }
        for candidate, count in rows
    ]


@app.get("/admin/products", tags=["products"])
def list_products(
    session: Session = Depends(get_db_session),
) -> list[dict[str, str]]:
    products = session.scalars(select(Product).order_by(Product.code, Product.id)).all()
    return [{"id": str(product.id), "code": product.code} for product in products]


@app.post("/admin/product-candidates/{candidate_id}/resolve", tags=["products"])
def resolve_product_candidate(
    candidate_id: uuid.UUID,
    request: Request,
    resolution: ResolveProductCandidateRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_same_origin(request)
    user = _get_single_owner(session)
    candidate = session.scalar(
        select(ProductCodeCandidate)
        .where(ProductCodeCandidate.id == candidate_id)
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product-code candidate not found",
        )
    if candidate.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product-code candidate has already been resolved",
        )

    product: Product | None
    if resolution.resolution_type == "mapped_existing":
        product_id = resolution.product_id
        if product_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A canonical product is required",
            )
        product = session.get(Product, product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical product not found",
            )
    else:
        code = (
            candidate.observed_code
            if resolution.resolution_type == "accepted_as_is"
            else resolution.product_code
        )
        if code is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A canonical product code is required",
            )
        normalized_code = normalize_product_code(code)
        product = session.scalar(
            select(Product).where(Product.normalized_code == normalized_code)
        )
        if product is None:
            product = Product(
                code=code,
                normalized_code=normalized_code,
                created_by_id=user.id,
            )
            session.add(product)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                logger.exception(
                    "Canonical product code conflicted while resolving candidate %s",
                    candidate_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That canonical product code already exists; map to it instead",
                ) from None
        elif resolution.resolution_type == "edited_code":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That canonical product code already exists; map to it instead",
            )

    affected_receipt_ids = session.scalars(
        select(ReceiptItem.receipt_id)
        .where(ReceiptItem.product_code_candidate_id == candidate.id)
        .distinct()
    ).all()
    candidate.status = "resolved"
    candidate.canonical_product_id = product.id
    candidate.resolution_type = resolution.resolution_type
    candidate.reviewed_by_id = user.id
    candidate.reviewed_at = datetime.now(timezone.utc)
    session.execute(
        update(ReceiptItem)
        .where(ReceiptItem.product_code_candidate_id == candidate.id)
        .values(product_id=product.id)
    )

    for receipt_id in affected_receipt_ids:
        pending_item_id = session.scalar(
            select(ReceiptItem.id)
            .join(
                ProductCodeCandidate,
                ReceiptItem.product_code_candidate_id == ProductCodeCandidate.id,
            )
            .where(
                ReceiptItem.receipt_id == receipt_id,
                ProductCodeCandidate.status == "pending",
            )
            .limit(1)
        )
        if pending_item_id is None:
            receipt = session.get(Receipt, receipt_id)
            if receipt is not None and receipt.status == "needs_review":
                receipt.status = "complete"

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.exception("Conflict while resolving product candidate %s", candidate_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The product-code resolution conflicts with existing data",
        ) from None

    return {
        "id": str(candidate.id),
        "status": candidate.status,
        "product_id": str(product.id),
        "product_code": product.code,
    }
