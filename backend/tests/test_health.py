from fastapi.testclient import TestClient

from app import main


client = TestClient(main.app)


def test_liveness_is_independent_of_database() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_service_unavailable_without_database(
    monkeypatch,
) -> None:
    def missing_database() -> None:
        raise main.DatabaseNotConfiguredError("DATABASE_URL is not set")

    monkeypatch.setattr(main, "check_database_connection", missing_database)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not configured"}


def test_readiness_succeeds_when_database_check_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(main, "check_database_connection", lambda: None)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
