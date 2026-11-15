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


def test_api_requires_token_when_configured(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "secret")
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.post("/chat", json={"tg_id": 1, "text": "привет"}).status_code == 401
    assert client.post("/chat", json={"tg_id": 1, "text": "привет"}, headers={"X-Api-Key": "wrong"}).status_code == 401


def test_reminder_id_must_be_uuid():
    response = TestClient(app).delete("/reminders/not-a-uuid")
    assert response.status_code == 422
