from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)


def test_list_providers():
    r = client.get("/api/agents/providers")
    assert r.status_code == 200
    body = r.json()
    ids = {p["id"] for p in body}
    assert len(body) == 4
    assert "mock" in ids
    assert "localdeploy" in ids


def test_list_providers_reports_masked_openai_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890")
    r = client.get("/api/agents/providers")
    assert r.status_code == 200
    openai = next(p for p in r.json() if p["id"] == "openai_compatible")
    assert openai["env_api_key_available"] is True
    assert openai["env_api_key_preview"] != "sk-test-1234567890"
    assert openai["env_api_key_preview"].startswith("sk-")
    assert openai["env_api_key_preview"].endswith("7890")


def test_mock_connection_online():
    r = client.post("/api/agents/test-connection", json={"provider": "mock"})
    assert r.status_code == 200
    body = r.json()
    assert body["online"] is True


def test_unknown_provider_400():
    r = client.post("/api/agents/test-connection", json={"provider": "nonsense"})
    assert r.status_code == 400


def test_mock_structured_output():
    r = client.post(
        "/api/agents/test-structured-output",
        json={"provider": "mock", "model": "mock"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["sample"]) > 0


def test_offline_endpoint():
    r = client.post(
        "/api/agents/test-connection",
        json={"provider": "localdeploy", "endpoint_url": "http://127.0.0.1:9/v1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["online"] is False
