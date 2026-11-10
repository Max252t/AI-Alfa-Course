from fastapi.testclient import TestClient

from app.main import app


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_validates_payload():
    client = TestClient(app)
    assert client.post("/chat", json={"text": "привет"}).status_code == 422
    assert client.post("/chat", json={"tg_id": 1, "text": "x" * 5000}).status_code == 422


def test_openapi_lists_core_routes():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for route in ["/chat", "/callback", "/start", "/health", "/materials/search", "/users/{tg_id}/profile", "/reminders/{reminder_id}"]:
        assert route in paths
