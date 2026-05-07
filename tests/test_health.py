from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok_without_database():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "gas-api",
        "environment": "dev",
        "version": "dev",
    }
