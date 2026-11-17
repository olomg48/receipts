from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from minio.error import S3Error
from sqlalchemy import func, select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from urllib3.exceptions import HTTPError as Urllib3Error

from app.db import (
    DatabaseNotConfiguredError,
    check_database_connection,
    get_db_session,
)
from app.models import (
    AuthIdentity,
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
session_secret = os.getenv("SESSION_SECRET")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret or "authentication-is-not-configured",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
)

oauth = OAuth()
if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
    oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOADS = {
    ("biedronka", ".pdf"): ("application/pdf", b"%PDF-"),
    ("lidl", ".png"): ("image/png", b"\x89PNG\r\n\x1a\n"),
}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _configured(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _require_auth_configuration() -> None:
    required = (
        "SESSION_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "PUBLIC_APP_ORIGIN",
    )
    if any(not _configured(name) for name in required) or not _allowed_emails(
        "INVITED_EMAILS"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )


def _require_same_origin(request: Request) -> None:
    expected_origin = _configured("PUBLIC_APP_ORIGIN")
    supplied_origin = request.headers.get("origin")
    if not expected_origin or supplied_origin != expected_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed",
        )


def _allowed_emails(name: str) -> set[str]:
    return {
        email.strip().casefold()
        for email in os.getenv(name, "").split(",")
        if email.strip()
    }


def get_current_user(
    request: Request,
    session: Session = Depends(get_db_session),
) -> User:
    if not _configured("SESSION_SECRET"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    user_id = request.session.get("user_id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required")
    try:
        parsed_user_id = uuid.UUID(user_id)
    except ValueError:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required") from None

    user = session.get(User, parsed_user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-in required")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
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


@app.get("/auth/google/login", tags=["auth"])
async def google_login(request: Request):
    _require_auth_configuration()
    client = oauth.create_client("google")
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    return await client.authorize_redirect(request, _configured("GOOGLE_REDIRECT_URI"))


@app.get("/auth/google/callback", tags=["auth"])
async def google_callback(
    request: Request,
    session: Session = Depends(get_db_session),
):
    _require_auth_configuration()
    client = oauth.create_client("google")
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )

    token = await client.authorize_access_token(request)
    userinfo = token.get("userinfo") or await client.userinfo(token=token)

    email = userinfo.get("email")
    subject = userinfo.get("sub")
    issuer = userinfo.get("iss") or "https://accounts.google.com"
    if (
        not isinstance(email, str)
        or not isinstance(subject, str)
        or userinfo.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google did not provide a verified account",
        )

    normalized_email = email.casefold()
    allowed = _allowed_emails("INVITED_EMAILS")
    if normalized_email not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has not been invited",
        )

    identity = session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.issuer == issuer,
            AuthIdentity.subject == subject,
        )
    )
    if identity is not None:
        user = session.get(User, identity.user_id)
        if user is None:
            logger.error("Google identity %s has no linked user", subject)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Account could not be loaded",
            )
    else:
        user = session.scalar(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        if user is None:
            user = User(
                email=email,
                display_name=userinfo.get("name"),
                is_admin=normalized_email in _allowed_emails("ADMIN_EMAILS"),
            )
            session.add(user)
            session.flush()
        session.add(
            AuthIdentity(
                user_id=user.id,
                issuer=issuer,
                subject=subject,
            )
        )
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Failed to persist Google identity")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Account could not be saved",
            ) from None

    request.session.clear()
    request.session["user_id"] = str(user.id)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/auth/me", tags=["auth"])
def current_account(user: User = Depends(get_current_user)) -> dict[str, str | bool | None]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
    }


@app.post("/auth/logout", tags=["auth"])
def logout(request: Request, _: User = Depends(get_current_user)) -> dict[str, str]:
    _require_same_origin(request)
    request.session.clear()
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
        .where(Receipt.uploaded_by_id == user.id)
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


@app.get("/receipts/{receipt_id}", tags=["receipts"])
def get_receipt(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict[str, str | None]:
    receipt = session.scalar(
        select(Receipt).where(
            Receipt.id == receipt_id,
            Receipt.uploaded_by_id == user.id,
        )
    )
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
    _: User = Depends(get_current_admin),
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
    _: User = Depends(get_current_admin),
    session: Session = Depends(get_db_session),
) -> list[dict[str, str]]:
    products = session.scalars(select(Product).order_by(Product.code, Product.id)).all()
    return [{"id": str(product.id), "code": product.code} for product in products]


@app.post("/admin/product-candidates/{candidate_id}/resolve", tags=["products"])
def resolve_product_candidate(
    candidate_id: uuid.UUID,
    request: Request,
    resolution: ResolveProductCandidateRequest,
    user: User = Depends(get_current_admin),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    _require_same_origin(request)
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
