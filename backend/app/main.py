import logging

from fastapi import FastAPI, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.db import DatabaseNotConfiguredError, check_database_connection


logger = logging.getLogger(__name__)
app = FastAPI(title="Receipt Tracker API", version="0.1.0")


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

    return {"status": "ok"}
