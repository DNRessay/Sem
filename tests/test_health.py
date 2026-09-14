from fastapi.testclient import TestClient

from main import app


def test_health_endpoint_does_not_require_db_or_cache():
    # Deliberately not used as a context manager: that would run the FastAPI
    # lifespan (Neon connect + cache warm), which needs real infra. /health
    # must answer without either, so a broken DB/cache never masks a healthy
    # deploy as down.
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
